# 266. A coverage member records the constraint the user stated, and the bound is proved against the quote for the intended action

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **seven narrowly stated scopes, and §9 shows the working for each. §1's proposal
  completeness**: the condition that a proposed row's coverage *"is complete for this request"*
  is restated over §7's test — the row the proposal would write satisfies **condition 6** for this
  request, condition 6 alone because a proposal is written `PROPOSED` and §3's condition 1 asks
  for a live row — because
  the ratified wording is stated over *"every user-facing argument … named by a member"* and a
  member names none, so no row carrying a non-empty coverage could otherwise be proposed at all;
  its purpose, its disposition and its cost are unchanged. **§2's member shape**: a
  `CoverageMember` stops carrying an `argument` and carries a **`kind`** instead, so a member
  records *what the user stated* and never *which slot it fills*; with it go §2's depth-one
  clause, its no-two-members-name-one-argument rule (which becomes **one member per kind**), its
  `currency_argument` field on a `MONEY` bound, and `maximum`'s requiredness (a stated **floor**
  mints a `minimum` and no `maximum`), while each endpoint gains an **exclusivity flag** so that a
  strictly stated bound stops being recorded as an inclusive one. **§3's condition 6 and its field count**: the set equality
  over argument **keys** and the per-argument rule that reads a member *"naming it"* are replaced
  by **two routes** — a member is met against the **quote recorded for the step's intended
  action**, or, where the declaration declares an argument at the member's kind, against that
  argument — and each endpoint names exactly one: a `MONEY` **`maximum`** needs the quote, and the
  declared argument **as well** where one exists, while a `MONEY` **`minimum`** needs the declared
  argument and is met by no quote; the validator refusing a member
  that names a system-supplied argument goes with the field it read, its rule preserved by a
  refusal on a new declaration field; and `ToolDefinition` gains **one** further field,
  `bounded_arguments`. **§4's `MONEY` reading, in two limbs**: the currency is read off the
  **quote** on the evidence route and off the **declaration** on the argument route, never off the
  bound; and its two inequalities are read strictly where the bound's own flag is set. **§9 clause
  (ii)**: *"an argument the act's own words bear on"* is given its mechanical test — agreement
  between the constraint's kind and the kind of the thing it is proved against, never numeric fit
  and never a model's nomination. **§8's and §10's resolution enumeration, in the closure at three
  alone**: a fourth `ResolutionRule`, **`STATED_BOUND`**, which §19 books by name. Every other
  clause of all seven sections binds entire, several load-bearing here: §1's three write paths,
  its write-before-the-question rule and its other three proposal conditions; §2's
  two-shapes-and-no-third rule and its `BoundKind` vocabulary; §3's conditions 1-5, its
  user-facing classification, its no-omission-reads-as-consent rule and its canonical encoding;
  §4's totality and its three readings; §8's basis; §9's clauses (i) and (iii) and its discard
  rule; §10's three ratified resolutions; §13's recheck-at-`decide` and its no-cached-verdict
  rule, which §7 below is taken under; and §15's writer clauses.
- **Partially supersedes** [ADR-0016](0016-tool-definition-and-registry.md)
  — **one scope, in §1, and it is the scope already recorded there reaching two further fields**:
  the `ToolDefinition` model declaration and the required-field clause in the application to
  `bounded_arguments` and `quoted_outputs` alone. A reader holding only §1 authors a definition
  that declares no argument's kind and no output a quote may be read at, so no member can meet any
  argument of it on the argument route and no completed read of it becomes a quote. The
  empty-tuple default is an exception to *"Every field that a permission decision depends on is
  required"* on the same grounds already recorded for `system_supplied` — it makes the
  **opposite** claim to the one §1 refuses, since a declaration that declares nothing is met on
  that route nowhere. **The exception is this one further field on this one argument**, and no
  lane reads the two records together as licence to default a third safety field.
- **Partially supersedes** [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md)
  — **one scope, in §1's `Goal` declaration alone**, and it is the scope the intended-action
  decision already took there reaching two further fields: `Goal` gains **`quotes`** and
  **`quotes_elided`** (§6). A reader holding only §1 authors a goal with no place for a quote, so
  §7's evidence route has no operand and a `MONEY` member is met nowhere. Every other clause binds
  entire, and §2's bounded-history construction is the one §6's elision reuses.
- **Partially supersedes** [ADR-0255](0255-the-driver-walks-a-plan-in-dependency-order-claims-each-step-under-its-attempt-and-stops-rather-than-acting-under-an-unfinished-one.md)
  — **one scope, and it is a count.** §15 item 19 enumerates what §13's rule requires before a
  consequential capability is wired and closes that enumeration in terms, at six conditions. §11
  adds a **seventh**, binding a capability whose authorisation can be reached through the evidence
  route: a quote's freshness at the moment of dispatch, and a classification telling a per-call
  identity key from a system-supplied input a price depends on. A reader holding only item 19
  wires an integration after six and is wrong — a quote true when it was read and false when the
  call was made authorises an over-bound charge, and **the gate's existing guarantees do not reach
  it**, because verification reports the completed overcharge and cancellation compensates the
  attempt while neither makes the pre-execution permission decision valid. §13's rule itself binds
  verbatim and its own contribution to the gate is unchanged; what grows is the gate's total.
- Date: 2026-09-15
## Context

### Where this comes from

Issue **#2373**, found in the pre-flight of ADR-0254 §20's **Lane 2** — the lane that makes
`orchestration` propose an `Authorization` on a `CONFIRM` and write path-(ii) corrections and
path-(iii) opening acts. That lane stopped before writing code: ADR-0254 states that
`orchestration` mints a `CoverageMember` from a recorded act and states exactly what a member must
contain, but **no clause states how a recorded span is associated with an argument key, nor how
the member's shape is chosen**. The owner's Q1 ruling of 2026-09-12, which ADR-0254 records whole,
is what the answer has to serve: *"Bind authorization to explicitly fixed values and explicitly
permitted ranges. A price change within an approved limit should remain covered. A clear later
instruction such as 'make it Sunday' can supply authorization for that change … Ask only when the
concrete action introduces something not already covered."*

**The owner's ruling of 2026-09-14 decides where the bound is compared, and it is the frame of
this document.** *"The tool takes what the action needs (site, dates, party size). The price is
usually a consequence of those choices, not an argument the assistant supplies."* So the
investigation phase records the quote for the intended action, the authorisation phase compares
the bound against that quote before execution, and **nothing about the price is compared against
an argument of the call**. A tool *may* declare a money-kind argument — a transfer amount, or a
`max_price` filter — and then the argument comparison applies **as well**; *"a filter is not a
charge"*, so it never stands in for the quote. Where no quote covers the act, the system
investigates or asks, which is a feasibility answer rather than a restriction on the tool. And the
evidence covers a step **only where the step's arguments are the ones that were quoted**: any
difference, extras filled in after quoting included, means re-quote or ask.

### The gap this closes, stated as the failure the corpus has today

Without the rule, **none of ADR-0254 §1's three write paths can write a row carrying a non-empty
`coverage`**, and §1's path-(i) completeness condition holds only **vacuously**. Four ratified
clauses each come close and none closes it. **§10** states three resolutions, each *"a total
function of recorded inputs"*, and every one turns **a span into a value**: none selects the span
and none names what the value is for. **§9 clause (ii)** states the **property** the association
must have — a value *"for an argument the act's own words bear on"* — and then what it may not do;
a property is not a procedure. **§8** closes `AuthorizationBasis` at `act`, `span` and
`resolution`, and nothing on it names an argument. And **§1's path (iii)** points at the goal's
interpretation, but `GoalElement` carries **no typed value and no argument key**.

And **§9's no-model clause forecloses the obvious source**: a planner envelope carrying *"a
coverage member, a bound, a basis"* has those values *"discarded silently"*. **§19 books what that
decision does not settle, each with what fires it** — a fourth `ResolutionRule` among them, which
§4 below fires — **but the association is not among its bookings**, so that silence is a gap and
not a reservation.

**Why a lane must not simply invent the rule.** §9 clause (ii) forbids adding *"a member for an
argument the act never mentioned"*, but only path (ii)'s widening is a store-enforced refusal: a
freshly minted path-(i) or path-(iii) member is checked by nothing. A wrong association is
therefore a **standing authority the user never gave**, and route (d) then `ALLOW`s inside it with
no `CONFIRM` — the failure direction §9's three clauses exist to close, and #2096 item 8's ruled
asymmetry (*"a model is a safe denier and an unsafe allower"*) is the corpus's own statement of
why a guess is not available here.


### The tree, read rather than assumed, at `origin/main` `32968830`

ADR-0254's Lane 1 has landed. `core/types.py` carries `Authorization`, `CoverageMember`,
`ValueBound`, `BoundKind`, `AuthorizationBasis`, `ValueResolution`, `ResolutionRule` and
`ToolDefinition.system_supplied`; `CoverageMember` carries `argument` and `ValueBound`'s `MONEY`
arm carries `currency_argument` and a **required** `maximum`, all three of which this decision
changes; `canonical_json_bytes` is public and is the one encoding; `Sha256Hex` is the digest shape
and `ActionRequest.parameters_digest` is computed rather than supplied;
`permissions/_coverage.py` carries `covers`, `covers_arguments` and a private
`_argument_is_covered` with `_satisfies`, `_satisfies_money`, `_satisfies_period` beside it;
`InterpretedOutput` carries `execution_id`, `step_id` and `field`; `GoalInterpretation` carries
`raised_by`; and `ActionPlan`'s `_step_ids_are_unique` raises *"plan step ids must be unique
within a plan"*. Nothing in the tree mints a `CoverageMember`, nothing records a quote, and
`ToolDefinition` declares nothing about what kind of value an argument takes.

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

**`FROM_EVIDENCE` names a record and `INFERRED` names the system's own judgement**; neither is
the user's words, and §9 clause (i) makes *"the authority is the act"* a property of the type.

> **Normative — the three other exclusions, each a consequence of a ratified clause rather than a
> new refusal.** **`criteria` and `conditions` mint nothing**: ADR-0249 §1 makes the three tuples
> *"its constraints, its success criteria and its conditions"* and ADR-0253 §7 gives a condition
> the applicability a step's own condition is evaluated over, so a criterion states what success
> would be and a condition states when a step may run — and ADR-0254 §1's path (iii) says where a
> bound lives in terms, *"the bound is an element of its `constraints`"*. **The interpretation's
> own `outcome` mints nothing**, because it carries no identity: ADR-0249 §7 retains it by copying
> `outcome`, `outcome_ground` and `outcome_span` forward byte for byte, so two revisions carrying
> one outcome are indistinguishable from two that restated it and §2's act could not be named.
> **And the *current* interpretation alone**: an element a later revision neither retained nor
> replaced is not in it (*"omission is removal"*), and minting from an earlier revision's tuple
> would restore a constraint the user's own later words removed. The history is walked **only** to
> find the act (§2), never to find a candidate.

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
> absent** — ADR-0254 §10's own sentence, *"A resolution the loop cannot take is not taken, and no
> member is minted"*.

> **Normative — an elided history refuses too, and the test is exact rather than approximate.**
> Where the earliest retained revision carrying the element's `id` is the **oldest retained
> revision** and `Goal.interpretation_elided` is **not 0**, no member is minted from that element:
> ADR-0249 §2 drops the **oldest** revisions, so a dropped one may have carried the element first
> and the act would name the wrong turn. Where the carrying revision has a retained predecessor
> that does **not** carry the id it is the first, and where nothing was elided the oldest retained
> revision is the first. Both are decided from values on the goal, with **no store read**.

**A wrong act is not a small error.** The basis is what an auditor reads to see *whose words
these were*, and a basis naming a turn whose utterance does not contain the span would be refused
at the write by ADR-0254 §1's own check — so the alternative to refusing here is a row that fails
to construct at the moment a call needed it.

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

> **Normative — `ValueBound` changes in two respects and no others.** A **`MONEY`** bound gains
> **`maximum_exclusive`, a `bool` defaulting to `False`**, `MONEY`-only, **so a ceiling the user
> stated strictly is representable as one**: *"under 100"* excludes `100` and *"at most 100"*
> includes it, and the two stop being one value. And **`currency_argument` is removed**: the key
> carrying an amount's currency is a fact about a **declaration**, not about an act, and §7 reads
> it there. **`maximum` stays required and `minimum` stays optional, exactly as ratified**;
> nothing in this decision mints a `MONEY` `minimum` (§4), so no floor is representable through
> it. `PERIOD` and `TERMS` are unchanged.

> **Normative — ADR-0254 §4's `MONEY` comparison is restated over the one flag and in no other
> respect.** The amount satisfies the bound where it is **less than** `maximum` if
> `maximum_exclusive` and **less than or equal to** it otherwise; the `minimum` conjunct is
> unmoved. Every other conjunct of that reading is unmoved — the `Decimal`-accepting shapes, the finite-and-not-negative refusal,
> the no-float rule and the currency conjunct §7 relocates — and **`PERIOD` stays half-open and
> `TERMS` stays equality of stated characters**, neither flag reaching either.

**Why the argument key was the defect rather than the rule that chose it.** A value that *fits*
an argument is not a value the act's words *bear on*, so no rule selecting an argument at the mint
could satisfy ADR-0254 §9 clause (ii): a constraint about a hotel's star rating has a number in it
and would fit a price. **Bearing is established by kind agreement between the constraint and the
thing it is proved against, and by nothing else** — *"four stars"* has no `MONEY` reading (§4), so
it is proved against no price — and on the evidence route the thing compared is the quote **for
the very act this goal intends**, a tighter tie than any argument key was.

**It does not follow that a member is portable across tools.** ADR-0254 §3's condition 3 compares
the request's `tool` against the row's **by value** and this decision leaves it entire, so a row
established about one declaration covers a call made under another in no case — the rebinding #54
closed, unweakened. What a member survives is an argument renamed inside one declaration. And §1's
write-before-the-question rule is untouched, a member needing **no argument when it is
written**.
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
>
> - **exclusive** — `under <amount>`, `below <amount>`;
> - **inclusive** — `<not> over <amount>`, `<not> above <amount>`, `<not> more than <amount>`,
>   `at most <amount>`, `no more than <amount>`, `up to <amount>`.
>
> **Every form mints a `maximum` and the table states no other direction.** *"at least 150
> euros"*, *"more than 150 euros"* and *"over 150 euros"* are **not forms of this table** and mint
> nothing at all. **Each negated row is the positive comparator inverted, endpoint included**,
> which is the arithmetic and not a choice: *"not over 100"* admits exactly `100` because *"over
> 100"* excludes it.
>
> The currency table is `euro`/`euros`/`eur`/`€` → `EUR`, `dollar`/`dollars`/`usd`/`$` → `USD`,
> `pound`/`pounds`/`gbp`/`£` → `GBP`. **A span matching no form mints no member**, and no lane
> adds a form, a currency or a language without its own ratified decision.

**Reading only ceilings is what makes a model-chosen span safe in the direction that matters, and
it is the whole answer to a defect four review rounds kept finding.** A planner selects the span,
and a proper substring can carry a different comparator from the sentence it was taken out of:
*"not under 100 euros"* yields *"under 100 euros"*, *"under no circumstances spend over 100
euros"* yields *"over 100 euros"*, *"avoid spending over 100 euros"* the same — and no rule over a
closed vocabulary can recognise *avoid*. What **can** be made total is the **direction**: where the
only bound this reading mints is a ceiling, every one of those truncations either mints nothing or
mints a **restriction bounded by a figure the user themselves uttered**, and none of them mints an
authority to spend where the user set a floor. **A floor is not a spending protection** in any
case — it constrains what the user receives, which §7 shows this system cannot tell from what it
pays — so removing the capability costs a question and closes a class of inversion that adding
rules did not. §10 books the floor with what fires it.

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
> spending word (*"never spending over 100 euros"*) is not a member of the closed set.
>
> **And a negation anywhere before the span refuses the reading**, because a truncation can drop
> one: a `STATED_BOUND` reading is refused where **any token of the negation vocabulary occurs in
> the act's own recorded utterance before the span begins**, folded and tokenised as above, so
> *"do not spend under 100 euros"* mints nothing from the span *"under 100 euros"*. That is
> deliberately blunt and refuses *"I'm not fussy — spend under 100 euros"* too, which costs a
> question. The negated rows still read, their own negation being **inside** the span they
> match.

> **Normative — a strict word mints a strict bound, and the endpoint is never widened.**
> *"under 100 euros"* mints `maximum` `100` with `maximum_exclusive`, so a call at exactly `100`
> is **not** covered; *"at most 100 euros"* mints the same `maximum` without it, and a call at
> `100` is. **No reading rounds, quantises, nudges or relaxes an endpoint in either direction**,
> and no lane reads a strict word as an inclusive bound *"because the difference is a cent"* —
> ADR-0254 §2's asymmetry is the reason, since the difference is a cent in the direction that
> authorises a call the user did not authorise.

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

> **Normative — `FROM_SHOWN_RECORD` mints nothing from an element.** ADR-0249 §1's validator gives
> a `USER_STATED` element a span and **no** `evidence_id`, so no element carries both a span and
> the record its reference resolved to; re-resolving the words at minting time would be a fresh
> interpretation of the user's language, at the one moment §9 clause (i) reserves to code.

> **Normative — the readings are attempted in one order and the first total one is taken**:
> `STATED_BOUND`, then `DATE_FROM_CONTEXT`, then `AS_STATED`, so that a span which is both a bound
> phrase and a term is a bound. It is the only ordering here, and **what makes a
> `DATE_FROM_CONTEXT` resolution total over a span is not decided here** (§10).

### 5. One member per kind, and the mint reads the goal and nothing else

> **Normative — where two candidate elements of one goal would mint members of one `kind`,
> neither is minted.** No precedence, no ordering, no most-recent rule and no narrowest-wins
> rule: ADR-0254 §2 refuses a row that carries two members about one thing, and choosing between
> two constraints the user stated is an interpretation of which one they meant. A later
> constraint that **replaces** an earlier one is ADR-0254 §1's path (ii) and supersedes the row;
> two standing at once is an ambiguity, and ADR-0254 §9 clause (iii)'s answer to an ambiguity is
> that the user is asked.

> **Normative — the mint reads the goal's own current interpretation, its retained history and,
> for §4's truncation test alone, the act's own recorded utterance — and nothing else.** **No
> request, no plan, no step, no declaration, no registry, no quote and no clock**, and no turn but
> the one the basis already names, which ADR-0254 §1 re-reads at the write in any case. A member is therefore the same value whatever call was
> being built when the row was written, which is what makes *"the authorization records the
> constraint as the user stated it"* true of the record and not merely of its intent — and it is
> why no plan a model produced can shape the **content** of an authority, at any path, by any
> route.

### 6. The quote: what the investigation records, and how one is minted

> **Normative.** `core/types.py` gains **`ActionQuote`**, a frozen model with `extra="forbid"`
> whose fields are exactly seven: **`intended_action`**, an `Identifier`, the `IntendedAction`
> (ADR-0265 §1) this quote is for; **`attempt_id`**, an `Identifier` naming the attempt that
> recorded it, which is `GoalEvidence.attempt_id`'s field one record over and for its reason;
> **`arguments_digest`**, a `Sha256Hex`, the arguments it was quoted over; **`kind`**, a
> `BoundKind`; **`value`**, a `FrozenJsonValue`, the quoted value in the **same** form an
> argument of a request carries it in; **`currency`**, an `EncodableText | None`; and
> **`read_from`**, an `InterpretedOutput` naming the step output the value was taken from. A **model validator** admits `currency` on `MONEY` alone — required
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

**The bound elides where ADR-0265 §1's refuses, because a dropped quote fails nothing silently:**
§7's route finds none, the member is met by nothing and **the user is asked**.

> **Normative — the *declaration* says where a quoted value is in its own output, and no plan
> does.** `core/types.py` gains **`QuotedOutput`**, a frozen model with `extra="forbid"` carrying
> exactly **`kind`** (a `BoundKind`), **`field`** (an `EncodableText | None`, a key of that tool's
> output at depth one, absent meaning the whole output) and **`currency_field`** (an
> `EncodableText | None`, `MONEY` only, required there and absent otherwise). **`ToolDefinition`
> gains `quoted_outputs: tuple[QuotedOutput, ...]`**, possibly empty, defaulting to the empty
> tuple, carrying **at most one member per `kind`** — refused at construction otherwise. This is
> a **BREAKING** contract change to a `core` type under golden rule 5 and is flagged as one.

> **Normative — `orchestration` mints the quote from a completed step's own output, and no model
> contributes any part of it.** After a step completes whose **declaration** carries a
> `QuotedOutput` and whose `PlanStep` names an **`intended_action`**, `orchestration` mints one
> `ActionQuote` per declared member: `intended_action` the step's, `attempt_id` the attempt the
> step ran under, `kind` the `QuotedOutput`'s, **`value` read at its `field` of that step's stored
> output** and `currency` at its `currency_field`, `read_from` composed exactly as ADR-0253 §8
> composes an `InterpretedOutput` — `execution_id` from the execution it read, `step_id` and
> `field` from the step and the declaration — and **`arguments_digest` taken over that step's own
> request's user-facing arguments**. **A step naming no `intended_action` mints nothing**, and so
> does a declaration carrying no `quoted_outputs`. **Where the field is absent from the output,
> where the value there is JSON `null`, where a `MONEY` quote has no value at `currency_field` or
> the value there is not a JSON string, or where the value at `field` is not a shape §4's reading
> of that kind accepts, no quote is minted** and nothing is recorded.

**Which output carries a price is a fact about the tool, and putting it on the declaration is what
takes the model out of the quote entirely.** An earlier draft let the **plan** name the field, and
round 6 showed what that buys: against an output `{"price": "200", "stars": 4, "currency":
"EUR"}`, a planner naming `stars` produces a quote of `4`, which satisfies a `150` ceiling and
authorises the `200` purchase — a number of the right *shape* in the wrong *slot*, which no
validator of shape can catch and which ADR-0254 §3's *"can satisfy … and can never supply"* arm
does **not** cover, because the harm is a too-small value rather than a too-large one. The
declaration is where every other such fact already lives (`system_supplied`, `bounded_arguments`),
it is authored by the integration rather than proposed per turn, and with it §8's writer clause is
absolute again: **no model output reaches any input of a quote**.


> **Normative — the digest is one encoding restricted to one key set, and not a second
> canonicalisation.** `arguments_digest` is `sha256` over the canonical JSON encoding
> `ActionRequest.parameters_digest` is taken over, **restricted to the keys the declaration
> classifies user-facing** (ADR-0254 §3). System-supplied keys are excluded because
> `orchestration` fills them **per call** — an idempotency key differs between the quoting read
> and the booking by construction — so a digest over every argument could never match and the
> route would be inert. Nothing else is excluded: **an extra user-facing argument, a missing one
> and a changed one each change the digest**, which is the owner's rule that the quote covers the
> booking only where *"the step's arguments are the ones that were quoted"*.

> **Normative.** `PlanStore` gains **one** member, `async` and returning a detached snapshot like
> every other, and this is a **BREAKING** contract change under golden rule 5:
> **`record_quotes(minting: ActionQuoteMinting) -> Goal`** — appends one or more quotes to the
> named goal's `quotes`, performs the elision above, advances `version`, and returns the stored
> goal. `core/types.py` gains **`ActionQuoteMinting`**, a frozen command carrying exactly
> `goal_id`, `quotes` (a **non-empty** `tuple[ActionQuote, ...]`) and the `expected_version` it
> was computed against; the write is **compare-and-swap** and the store takes a command and never
> a snapshot, which is ADR-0014 §5's discipline and ADR-0265 §5's statement of it unaltered.
> **It refuses a command naming a goal the store does not hold, one whose `intended_action` is
> not the `id` of a member of that goal's own `intended_actions`, one whose `attempt_id` is not an
> attempt of that goal, and one whose `read_from` does not resolve to a completed step execution
> of the named `attempt_id` itself — `execution_id` a member of that attempt's own
> `execution_ids` (ADR-0255 §3) and `step_id` a step of it — **and one whose `read_from` names a
> step whose own `intended_action` is not the quote's, or whose declaration carries no
> `QuotedOutput` at the quote's `kind` naming `read_from.field`, so a quote can never be read
> under one act and offered under another, nor read from a field the tool never declared** — the window ADR-0265 §4 closes at the store for a plan, closed here for
> every reference the quote carries and with the same error class. **That is what makes the export
> closure and the deletion cascade true rather than asserted**: every identifier on a quote
> resolves inside the goal the quote rides in, so ADR-0014 §5's rule is satisfied by construction
> and `delete_goal` leaves nothing dangling.

> **Normative — the wire, the export, the stored shapes and the migration, and it is ADR-0265
> §5's clause one record over.** **`PROTOCOL_VERSION` moves by exactly one, in the lane that lands
> the `core` surface**, and `wire/envelope.py`'s log gains an entry naming this ADR and the
> reason: `Goal` gains two fields and `ToolDefinition` gains one, `Goal` is carried on
> `TurnResult.goal`, both set `extra="forbid"`, and `wire/codec.py` renders a model by
> `model_dump()`, so the shape change makes a hub's turn undecodable by a client at the previous
> version. **`PlanExport` gains no member and
> `schema_version` moves for the record's shape alone**, on ADR-0039 §10's own mechanism, because
> a quote rides **inside `Goal`** which `PlanExport.goals` already carries — so ADR-0014 §5's
> closure rule is satisfied by construction and `delete_goal`'s cascade reaches a quote because it
> is inside the goal. **Every stored row stays readable and the migration is an addition with a
> total default**: a `Goal` written before this decision decodes with `quotes` empty and
> `quotes_elided` `0`, and a `ToolDefinition` with `quoted_outputs` empty, which is a conforming
> declaration rather than a degraded one. **No lane invents a quote for a stored goal**, because a price nothing read
> is a price no record holds.

**A quote is a record of its own rather than a field of a `GoalEvidence` row, and the reason is
that decision's own text.** ADR-0252 §1 rules that *"A `GoalEvidence` carries no content"* and is
*"never a second copy of what was read"*, closes `EvidenceBasis` at **two** members neither of
which admits a typed value read from a step's output, and fixes a `verdict` vocabulary per basis.
A quote is exactly a second copy of what was read, deliberately, because a comparison cannot be
taken against a count — and carrying it there would supersede four limbs of one ratified section
to reuse sufficiency, conflict and digest machinery that is about **propositions**, which a price
is not. What the quote takes from that decision is its **principle**, in §7's last-governs rule:
*"a refresh supersedes the row it displaces"*.
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
> **`async for_action(goal: Identifier, intended_action: Identifier, attempt: Identifier) ->
> tuple[ActionQuote, ...]`** and nothing else — the face a policy holds, returning the quotes of
> that goal naming that action **and recorded under that attempt**, in `Goal.quotes`'s own order,
> and the empty tuple where there are none. It is `async` and returns a **detached snapshot**,
> which is ADR-0097 §3's discipline every member of `GoalAuthorizations` and `PlanStore` already
> keeps, and it is `GoalAuthorizations`' construction one record over (ADR-0254 §16, ADR-0193
> §1): a narrow face the composition root wires, so the policy names a Protocol and never a
> store. **`ActionRequest` gains `intended_action` and `attempt`, each an `Identifier | None`
> defaulting to `None`** — the step's own and the attempt it is dispatched under, which is
> `ActionRequest.goal`'s shape two fields over.
>
> **A fault is never an absence.** The member **raises `AuthorizationError`** where its backing
> read fails and returns the empty tuple **only** where the goal holds no matching quote, and
> **no implementation converts a fault into an empty tuple**; a cancellation propagates as it
> does through every other member. A policy that meets the fault treats the request as **not
> covered** and reports the fault rather than falling through to the argument route — the same
> distinction ADR-0254 draws between `AuthorizationError` and absence, which is what lets a
> ruling say *no record* rather than *a record that did not cover*.

> **Normative — the evidence route, and a member is met by it where all five hold.** The request
> carries an `intended_action` and an `attempt`; a quote of the row's `goal` names **that** action
> and carries **that** `attempt_id`; the quote's `kind` equals the member's; the quote's
> `arguments_digest` equals the digest of **this request's** user-facing arguments, taken exactly
> as §6 takes it; and the quote's `value` satisfies the member under ADR-0254 §3's fixed
> comparison or §4's bounded readings, with a `MONEY` bound's **currency conjunct taken at the
> quote's own `currency`** and at no key of the request. **Where two quotes match on action, kind and digest, the one latest in `Goal.quotes`
> governs** — a re-quote is a refresh of one fact and the later reading is the current price,
> which is ADR-0252 §8's principle and is not a precedence rule between two acts of the user.
>
> **The attempt conjunct is what bounds a quote's age, and there is no figure.** A quote recorded
> under an earlier attempt satisfies nothing, however recent it looks: an attempt is one unit of
> work with its own investigation, so a price read under a previous one is a price this attempt
> has not read. **No clause invents a duration, a `Settings` field or a per-request freshness
> parameter** — ADR-0252 §6 refuses to invent one for evidence and ADR-0096 §3 states why — and
> what remains inside one attempt is the residual §10 books.
>
> **A quote states what the act will cost, and nothing this decision mints states what the user
> will receive.** §4 reads only ceilings, for exactly that reason: kind agreement cannot tell a
> price the user pays from one they are paid, and a charge satisfying a floor would be the
> permissive direction — *"receive at least 150"* admitting a charge of 200.

> **Normative — the argument route, and it is available only where the declaration declares.** A
> member of kind *k* is met by it where the declaration carries **exactly one** `BoundedArgument`
> at *k*, the request carries a value at that argument, and the value satisfies the member under
> the same comparisons, with a `MONEY` bound's currency conjunct taken at that
> `BoundedArgument`'s **`currency_argument`** in the concrete request — which is what makes that
> currency key **covered** rather than unexamined. **Where the declaration declares no argument at
> *k*, or declares more than one, no member of kind *k* is met by this route** and nothing about
> that kind is compared here.

> **Normative — which route each member needs, stated exhaustively, because a filter is not a
> charge.** A **`PERIOD`** or **`TERMS`** member is met by **either** route. A **`MONEY`** member
> needs the **evidence** route, and needs the **argument** route **as well** where the declaration
> declares an argument at `MONEY`, both holding. **A declared money argument never stands in for a
> quote**: a `max_price` constrains what a search returns and a transfer amount is one leg of a
> call, and neither is the charge. **Where a value is supplied into a declared money argument as a
> safeguard, its source is the member's own `maximum` and there is no other source**; which
> declarations admit such a fill is booked (§10), and until that decision lands the two
> declarations are disjoint by the refusal above.

> **Normative — ADR-0254 §3's condition 6 is restated, and it keeps both its directions.** An
> `Authorization` satisfies condition 6 for an `ActionRequest` where **all three** hold: **every
> member of the row is met**, by the routes above; **every user-facing argument of the request
> that the declaration declares in a `BoundedArgument` is covered** by the member of that
> argument's kind, a request carrying no member of that kind being **uncovered**; and — where the
> request carries **any** user-facing argument the declaration declares at no kind — **at least
> one member of the row is met through the evidence route**, whose digest pins every user-facing
> argument the request carries. **A key a `BoundedArgument` names as its `currency_argument` is
> not such an argument**: it is consumed by that declaration's own `MONEY` member, whose §4
> comparison reads the request's value there, so a declaration carrying an amount and its currency
> is covered without a quote being needed for the currency key alone. A member met by no route leaves the request uncovered, which is
> §3's second direction — *"an act that fixed `refundable_only` to `true` authorised a call
> **carrying** that value"* — and an argument the row cannot meet leaves it uncovered, which is
> §3's first. **There is no default, no wildcard and no omission that reads as consent.**
>
> **The third conjunct is what keeps an undeclared argument from going unexamined**, and it is
> §3's first direction preserved rather than relaxed. Without it a row fixing `subject` to
> *"urgent"* would cover a later `send_message` carrying an entirely different `body`, because the
> argument route examines declared arguments alone. With it, an undeclared argument is pinned by
> the quote's digest or the request is not covered — so the owner's booking case, whose `site`,
> `dates` and `party` are declared nowhere, is covered through its quote, and a tool with no quote
> and undeclared arguments asks.
>
> **And ADR-0254 §1's completeness condition is restated over condition 6 alone.** That condition
> reads that the coverage a proposed row would carry is complete where *"every **user-facing**
> argument of the request … is named by a member"*, which no member can satisfy once a member
> names no argument; it is restated as **the row the proposal would write satisfies condition 6
> for this request**. It is **condition 6 and not `covers`**, because a proposal is written
> `PROPOSED` and condition 1 asks for a live row, so a test over the whole of §3 could never pass
> at a proposal. Its purpose is unchanged and is §1's own: a proposal is made only where answering
> would establish an authority that can cover a later call. **Where it fails, no row is
> proposed**, `Confirmation.authorization` is absent and the one call is authorised by route (a)
> — §1's own disposition, unweakened.

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
`maximum` `150`, `EUR`, inclusive — and nothing else; the goal holds one intended action. The
investigation quotes the site for Saturday and the quoting step declares its `quotes`, so a quote
is recorded: that action, that attempt, `MONEY`, `120`, `EUR`, over the digest of *(site, dates,
party)*. At authorisation the booking request carries the same action, the same attempt and the
same three arguments, the digest matches, and `120 ≤ 150` — the request is covered, route (d)
`ALLOW`s, and **no question is put**. The verification phase confirms the charge afterwards and a
mismatch is a reported finding, which is A10's (§10). *"Make it Sunday"* replans, the
investigation re-quotes at `135`, and the new quote's digest is the Sunday arguments': the
Saturday quote covers nothing now, the Sunday one does, and **still no question is put** — the
owner's *"a clear later instruction … can supply authorization for that change"*. A site whose
Sunday price is `170` is covered by nothing, and the user is asked about that concrete call.

### 8. Writer clauses, and what no model does

> **Normative.** **`orchestration` mints every coverage member and every quote, and nothing else
> does.** No `ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter, no tool
> and no model **mints, writes, repairs or supplies the recorded value of** one. The exclusivity
> is over the **mint and the durable provenance**: a planner supplies validated selectors that
> **influence** which output field a quote is read at (§6) and supplies no recorded value, and no
> other component does even that. This is ADR-0254 §15's writer clause reaching the values §5 and
> §6 add.

> **Normative — no durable value of this decision is ever taken from a model, and the list is
> exact.** A planner envelope carrying a **`CoverageMember`**, a **`ValueBound`**, an
> **`AuthorizationBasis`**, a `BoundKind`, an argument key, a **`BoundedArgument`**, a
> **`QuotedOutput`**, an **`ActionQuote`**, an `arguments_digest`, an `attempt_id` or an
> **`InterpretedOutput`** has those values **discarded silently** — not an error, not a park, not
> a degradation of the turn — which is ADR-0254 §9's posture extended to exactly the values this
> decision adds, and for its stated reason: a value a model wrote into a durable audit chain is
> unprovenanced.

> **Normative — a model contributes exactly one thing to this decision, and it is the span.** An
> interpretation element's span is checked against that turn's own utterance by ADR-0249 §7 and
> read only through §4's closed table, which mints a **ceiling or nothing**, so a differently
> chosen span yields a different or no member and never an authority in the direction the user did
> not give. **Nothing else a model produces reaches any input of §4, §5, §6 or §7**: the field a
> quote is read at is the **declaration's** (§6), the argument a member meets is the
> declaration's (§7), and the identifiers are the loop's. **A model names no argument key, no
> output field, no currency key and no identifier anywhere in this decision.**

### 9. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text** and is shown rather than asserted:
*"Would a reader holding only the earlier ADR now act differently, or read one of its clauses more
widely than it now holds?"* **Four documents come out yes** — ADR-0254 in seven scopes, ADR-0016
in one, ADR-0249 in one and ADR-0255 in one count; every other ADR cited comes out **no** and
takes none, which ADR-0082 §1 requires as firmly.

**ADR-0254 §1 — in the proposal's completeness condition alone.** It reads that the coverage a
proposed row would carry is *"**complete for this request**: every **user-facing** argument of the
request (§3) is named by a member … **or** the request carries no user-facing argument at all"*.
A member names no argument once §3 below lands, so it would be satisfiable only by its second limb
and **no row carrying a non-empty coverage could ever be proposed** — the inert outcome this
decision exists to remove. §7 restates it as *the row the proposal would write satisfies condition
6 for this request*: **condition 6 and not the whole of `covers`**, because a proposal is written
`PROPOSED` and §3's condition 1 asks for a **live** row, so a test over the whole could never pass
at a proposal. Its purpose, disposition and cost are unchanged. **Every other clause of §1 binds
entire** — the three write paths, the row written before the question is put, the never-edited
coverage, the path-(iii) recipient precondition and the other three proposal conditions.

**ADR-0254 §2 — in the member's shape.** §2 declares `CoverageMember`'s fields *"exactly:
`argument`, an `EncodableText`; `fixed`; `bound`; and `basis`"*, states *"`argument` is a key name
and never a path"*, rules that *"No two members of one `Authorization` name the same `argument`"*,
gives a `MONEY` bound a `currency_argument` as *"the whole of the association between an amount
and the currency it is denominated in"*, and makes `maximum` required. §3 above replaces
`argument` with `kind`, restates the no-two-members rule over the kind, moves the currency key to
the declaration and the quote, makes both endpoints optional with one present, and gives each an
**exclusivity flag**. A reader holding only §2 authors a member that claims to know which slot it
fills, cannot represent a floor at all, and records *"under 100"* as a bound a call at exactly 100
satisfies. **Every other clause binds entire**: the two-shapes validator, `BoundKind`'s members
and their vocabulary rule, the three kinds' own fields and refusals, the
every-other-argument-is-fixed-only default, and the asymmetry argument that *"A comparison the
system gets wrong in the permissive direction authorises a call the user did not authorise"* —
which §§3, 4 and 7 are written to serve rather than to weaken.

**ADR-0254 §3 — in condition 6 and in the field count.** Condition 6 reads that *"the request's
user-facing arguments and the row's coverage name the same set of keys"* and the per-argument rule
that an argument is covered *"where the row carries a member naming it"*; §3 ties the two —
*"The set comparison is over **keys** and the per-argument rule is over values, and together they
are the whole of condition 6."* §7 replaces that whole with two routes and three conjuncts,
keeping both of condition 6's directions in substance. A reader holding only §3 builds a
comparison in which a price must be an argument of the call, and refuses every booking whose price
is a consequence of the site and the dates — the failure the owner's ruling of 2026-09-14 names.
With the `argument` field goes the validator making a row whose coverage names a system-supplied
argument not constructible; **its rule is preserved** by §7's refusal on `bounded_arguments`. And
`ToolDefinition` gains **one** further field, so *"`ToolDefinition` gains **one** field"* is
over-narrow by one. **Every other clause binds entire**: conditions 1-5 — condition 3's by-value
declaration comparison conspicuously so — the user-facing classification and its empty default,
the fill-before-the-fit-test and `parameters_digest` clauses, the bar-stays-monotone clause, the
seam/policy split, the coverage-never-widens rule, the ADR-0021 §5 monotonicity clauses, the
resolved-reference clause with its *"can satisfy … and can never supply"* arm, and the canonical
encoding §6 and §7 compare by.

**ADR-0254 §4 — in two limbs of the `MONEY` reading.** Its **currency conjunct** reads *"the
request carries, at the bound's `currency_argument`, a JSON string equal to the bound's
`currency`"*, and the bound no longer carries that key; §7 takes it at the `BoundedArgument`'s
`currency_argument` or at the quote's own `currency`, its force unchanged. And its **two
inequalities** are read strictly where the bound's exclusivity flag is set, a reader holding only
§4 otherwise covering a call at exactly the endpoint the user excluded. **Every other clause binds
entire**: the `MONEY` reading in every other conjunct, `PERIOD` and `TERMS` whole, the no-float
and no-naive-instant rules, the totality-and-refusal clause, the `reason` discipline, and the
no-schema clause, which §7 cites as binding it.

**ADR-0254 §9 clause (ii) — in the test of *"bear on"* alone.** The clause states the property and
no procedure, so a reader holding only §9 has an obligation with no mechanical test and either
invents one or, as #2373 did, stops. **Its test is kind agreement between the constraint and the
thing the member is proved against** — the quote's `kind`, or the `BoundedArgument`'s — and never
numeric fit, a model's nomination or a schema. **The clause's prohibitions bind entire and are not
narrowed**, and so do clauses (i) and (iii) and §9's discard rule.

**ADR-0254 §8 and §10 — in the resolution enumeration's closure alone.** Both state
`ResolutionRule` *"closed at exactly three members"*; §4 adds `STATED_BOUND`. **This is the
supersession §19 books by name** — *"A fourth `ResolutionRule`. Fired the same way, and never by a
resolution whose inputs are not on the turn it names"* — and the new rule honours that condition:
its inputs are the span and the utterance the basis already names. **Every other clause binds
entire**: §8's basis fields, its span check and its two-zones clause; §10's three ratified
resolutions, its no-memory-no-preference rule, its normalisation-at-the-mint rule and its *"A
resolution the loop cannot take is not taken, and no member is minted"*.

**ADR-0016 §1 — in one scope**, and it is the scope ADR-0254 §18 already took there reaching two
further fields: the model declaration, and the required-field clause applied to
`bounded_arguments` and `quoted_outputs`. The grounds are the clause's own reason, which does not reach this default —
the empty tuple makes the **opposite** claim to the one §1 refuses. **The exception is these two
further fields on this one argument**, and no lane reads the records together as licence to default
a further safety field. Every other clause of §1 binds entire.

**ADR-0255 §15 item 19 — and it is a count.** That item enumerates what §13's rule requires before
a consequential capability is wired and closes the enumeration in terms, at **six** since ADR-0265
§6 added the sixth. §11 adds a **seventh** — an enforceable provider-side hold or a provider-side
conditional execution that validates the quoted amount atomically with the act, together with the
identity/price-affecting split of a system-supplied key — and a reader holding only item 19 wires
an integration after six and is wrong: the residual is a **quote that was true when it was read
and false when the act was performed**, so route (d) authorises an over-bound charge. **The gate's
existing guarantees do not reach it** — verification reports the completed overcharge and
cancellation compensates the attempt, and **neither makes the pre-execution permission decision
valid**, which is §13's own test. §13's rule binds verbatim and its own contribution is unchanged;
what grows is the gate's total.

**ADR-0249 §1 — in the `Goal` declaration alone.** ADR-0265 §8 already recorded a scope there for
`intended_actions`; this decision reaches it again for `quotes` and `quotes_elided`, and ADR-0070
§4's precedence rule makes the later record govern the overlap. A reader holding only §1 authors a
goal with no place for a quote, so §7's evidence route has no operand and a `MONEY` `maximum` is
met nowhere. **Every other clause of §1 binds entire**, and §2's bounded-history construction is
reused by §6's elision rather than restated.

**And the ones that come out no.** **ADR-0254 §13** is the clause §7 is taken under — the recheck
at `decide`, the no-cached-verdict rule and *"Coverage and sufficiency are two tests and neither
clears the other"*, which stays true. **ADR-0252** is read and **not moved**: §1's no-content rule,
its two bases and per-basis verdict vocabularies, §6's four tests, §7's conflict rule, §11's digest
and §§12-13's store, retention and export are untouched, and §6 states why a quote is a record of
its own instead. **ADR-0253** is superseded in nothing: §8's `InterpretedOutput` is reused
**unaltered**, composed by the loop from a plan-carried selector exactly as that section composes
it from a `StepOutputRef`, so its *"No model supplies any of the three"* is honoured by the same
construction, and this decision now adds **no** field to `PlanStep` at all, so §9's label-space
count and resolve-once discipline are untouched and nothing of that ADR is reached.
**ADR-0249 §7** is relied on and not narrowed: its span check is a containment test, and §4's
truncation refusal is a further refusal of this decision's own reading rather than a change to it.
**ADR-0265** is relied on entire. **ADR-0014 §5, ADR-0249 §12, ADR-0250 §9, ADR-0252 §12 and
ADR-0265 §5** each widened `PlanStore` without enumerating it closed, so §6's member is a
**stacked addition**, and §5's closure rule is satisfied by §6's reference refusals with
`schema_version` moving on **ADR-0039 §10**'s own mechanism. **ADR-0021 §1** is relied on for the
one canonical encoding; **ADR-0145 §2 and §9** for the hazards §6 and §7 avoid; **ADR-0029 §5** is
relied on rather than superseded.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **Who supplies the value of a system-supplied argument.** ADR-0254 §3 requires `orchestration`
  to supply one and names an idempotency key, a client reference and a locale. **This decision
  states one source and lands no filler**: a value supplied into an argument as a spending
  safeguard is the member's own `maximum` (§7), and today `bounded_arguments` and
  `system_supplied` are disjoint, so no such fill is constructible. `PlanStep.id` is **refused
  here** as the client reference — `_step_ids_are_unique` guarantees uniqueness *"within a plan"*
  alone and `Identifier` guarantees no opacity. Fired by the decision that mints a dedicated
  opaque per-call reference.
- **Whether a quote is still true when the act is performed.** §7 bounds a quote to the attempt
  that recorded it and invents no duration; a provider may move a price with no newer quote
  appended, and the detached read leaves a newer appended quote unseen — the **quote-to-claim
  window**, the shape ADR-0255 §13 already names for an evidence refresh. Neither is closable from
  inside this system, so **§11 makes closing the first a prerequisite of the gate** and names the
  local claim-time revalidation that closes the second. Fired by the decision that gives an
  integration a hold or a conditional execution, and by the one that closes §13's window.
- **A stated floor.** §4 reads only ceilings, so *"at least 150 euros"* mints nothing and the act
  asks. Fired by a decision that can tell a bound on what the user **pays** from one on what they
  **receive** — which needs a fact neither the span nor the kind carries — and which then states
  what a floor is proved against.
- **A declaration whose `quoted_outputs` names the wrong field.** §6 takes the field from the
  declaration precisely so that no per-turn value chooses it, but an integration author who names
  a discount where the price is will mint quotes of the discount. That is an integration defect of
  the same class as a wrong `system_supplied` or a wrong `risk_level`, and this decision adds no
  mechanism against it. Fired by whatever the corpus decides about verifying a declaration's own
  claims.
- **Which system-supplied keys a price depends on.** §6 takes the digest over the **user-facing**
  arguments alone, because a system-supplied key is filled per call and a digest over an
  idempotency key could never match twice. ADR-0254 §3's three examples are not one kind: an
  idempotency key and a client reference are per-call identity, and a **locale** is an input a
  price can depend on. **This decision draws no line between them, and §11 makes drawing it a
  prerequisite of the gate.** Fired by the decision that classifies a system-supplied key.
- **A wider class of model-chosen span than §4's truncation test closes.** That test refuses a
  span the table's own negation grammar would have extended; a negation the vocabulary does not
  carry leaves a truncation readable. **ADR-0249 §7 owns that question** — its span check is a
  containment test, never a check of what the model meant. Fired by the decision that constrains
  how a span is chosen.
- **What makes a `DATE_FROM_CONTEXT` resolution total over a span** — the reader that turns
  *"Sunday"* into a half-open interval in a zone. §4 states what such a resolution **mints** and
  not how it is **taken**. **Until it lands, the only readings an element takes are
  `STATED_BOUND` and `AS_STATED`, and no `PERIOD` member is minted by any live path.** Fired by
  the decision that lands the reader, with its own totality argument and arms.
- **Any widening of §4's table** — a form it does not list (bare *"less than"* among them), a
  currency it does not name, a language other than English, a figure written in words, a bound on
  a count. It refuses rather than guessing. Fired by a decision stating the wider reading and its
  own totality argument.
- **A fourth `BoundKind`**, so that an argument which is neither an amount, a period nor a named
  term can be declared and met on the argument route; **a `FROM_SHOWN_RECORD` basis**, which needs
  an element carrying both a span and the record its reference resolved to, and ADR-0249 §1 admits
  none; and **which of two constraints of one kind the user meant**, which §5 refuses rather than
  choosing. Each fired by the decision that supplies what it names.
- **What the verification phase does with a quote.** The owner's ruling makes the actual charge
  confirmed after the act and a mismatch *"a reported finding"*; **no clause here verifies
  anything, compares a charge, or writes a finding**, and `AttemptPhase.VERIFY` is A10's by
  ADR-0255 §17's assignment. Fired by that decision, which this one gives a typed quoted value to
  compare against.
- **Coverage's other conditions, expiry and every surface.** ADR-0254 §3's conditions 1-5, §§5-7,
  §12's ladder as ADR-0256 §1 leaves it, and §11's projection: untouched, and this decision adds
  no field any of them renders.


### 11. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **four lanes**, in this order, **each one
> subsystem plus its tests**, and **no lane wires a consequential capability** or enables anything
> in a production deployment — ADR-0254 §17's rule as ADR-0255 §13 leaves it binds all four.
> **No lane writes an `Authorization`**: ADR-0254 §20's Lane 2 does that, is briefed after all
> four merge, and is what #2373 unblocks.

> **Normative — this decision adds a seventh prerequisite to the production-deployment gate, so
> that a reader does not take ADR-0255 §15 item 19's six for the whole.** **No consequential
> capability whose authorisation can be reached through §7's evidence route is wired until two
> things are implemented and demonstrated**: a quote's **validity at the moment the act is
> performed** — an **enforceable provider-side hold**, or a **provider-side conditional execution
> that validates the quoted amount atomically with the act itself**, and nothing weaker. **A local
> compare-and-swap is not one of them**, and the distinction is what round 6 found: a store
> transaction observes only stored values, so a provider price that moved without a newer quote
> being appended leaves the local check passing and the over-bound charge made. A claim-time
> revalidation of the selected quote inside `PlanStore`'s own step **does** close the stored
> quote-to-claim race §10 books, and is worth taking for that, but it is **not** a proof of the
> quote's current validity and no lane may offer it as one; elapsed-time proximity and an
> unenforced expiry are neither. And a **classification telling a per-call identity key from a
> system-supplied input a price depends on**, the latter bound into §6's digest. **The gate's existing guarantees do not reach either**: verification reports a
> completed overcharge and cancellation compensates an attempt, and **neither makes the
> pre-execution permission decision valid**, which is §13's own test.

- **L1 — the contract, in `core` alone**, and it is a **triad**: `CoverageMember`'s `kind` and
  the removal of `argument`; `ValueBound`'s `MONEY` reshape and the removal of
  `currency_argument`; `ResolutionRule.STATED_BOUND`; `BoundedArgument` and
  `ToolDefinition.bounded_arguments`; `QuotedOutput` and `ToolDefinition.quoted_outputs`;
  `ActionQuote`, `Goal.quotes`, `Goal.quotes_elided`, `MAX_ACTION_QUOTES`, `ActionQuoteMinting`,
  `ActionRequest.intended_action` and `ActionRequest.attempt`; the **`GoalQuotes` Protocol with
  its shared conformance suite and its canonical fake in `ai_assistant.testing`**, which
  `CONTRIBUTING.md` makes one unit of work; and **`PROTOCOL_VERSION`, `wire/envelope.py`'s log
  entry and `PlanExport.schema_version`** (§6), this being the one lane that is that ground.
  Arms 4(a), 5(a) and 7(b).
- **L2 — the store, in the plan-store implementations and their conformance suites alone.**
  `PlanStore.record_quotes`, its compare-and-swap, its four refusals and §6's elision; the
  stored-shape migration; and the **production `GoalQuotes` implementation**, whose rows are the
  `quotes` of the goal the store already holds, with its conformance suite run against it — so the
  composition root has a concrete to inject and the policy names only the Protocol. Arm 5(b).
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
> **subsequent turn**, on the owner's sequencing ruling of 2026-09-13, and none is demonstrated
> against a live integration.

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
3. **A stated floor, the endpoints, and the negation rule at its edges.** **3(a):** span
   `"at least 150 euros"` mints `minimum` `Decimal("150")`, **no** `maximum` and **no**
   `minimum_exclusive`; `"more than 150 euros"` mints the same `minimum` **with** it;
   `"under 100 euros"` mints `maximum` `100` **with** `maximum_exclusive` and `"at most 100
   euros"` mints it without; `"never spend over 100 euros"` mints an **inclusive** `maximum` of
   `100`; `"never notify me about charges over 100 euros"`, `"not exactly 100 euros"` and
   `"never spending over 100 euros"` each mint **nothing**; and the span `"under 100 euros"` taken
   from the utterance `"not under 100 euros"`, and the span `"over 100 euros"` taken from
   `"under no circumstances spend over 100 euros"`, each mint **nothing**, a negation standing
   before the span in both.
   **3(b):** against an exclusive `maximum` of `100` a value of exactly `"100"` does **not**
   satisfy and against an inclusive one
   it does, and the same both ways at a `minimum`; and a `MONEY` member carrying a `minimum` is
   met by **no quote** however large, and is met at a declared money argument.
4. **One member per kind.** **4(a):** an `Authorization` carrying two `MONEY` members is not
   constructible. **4(b):** a goal carrying two `USER_STATED` constraints that each read as
   `MONEY` mints **neither**, and a `PERIOD` constraint beside them still mints its own — with
   its `timezone` read from the same input the resolution records and **not** read back off the
   resolution's own record of it.
5. **The quote, minted from a step's own output and from nothing else.** **5(a):** a
   `ToolDefinition` carrying two `quoted_outputs` of one `kind` is not constructible, one carrying
   a `MONEY` member with no `currency_field` is not constructible, and an `ActionQuote` whose
   `value` is JSON `null` is not constructible. **5(b):** `record_quotes` appends, advances
   `version`, elides the oldest past `MAX_ACTION_QUOTES` while advancing `quotes_elided`, and
   **refuses whole** a stale `expected_version`, an unknown goal, a quote naming an action the
   goal does not hold, one whose `attempt_id` is an attempt of another goal, one whose
   `read_from` names an execution or step that is not a completed one, and one whose `read_from`
   names a completed execution of **another attempt of the same goal**, of a step whose own
   `intended_action` differs from the quote's, or of a field the step's declaration names in no
   `QuotedOutput` at that kind.
   **5(c):** after a step whose declaration carries a `QuotedOutput` completes, the minted quote
   carries the step's `intended_action`, the attempt it ran under, the value at the **declared**
   field of that step's stored output, the currency at `currency_field`, a `read_from` naming that
   execution and step, and an `arguments_digest` over that step's **user-facing** arguments alone.
   **No quote is minted** where the step names no `intended_action`, where the declaration carries
   no `quoted_outputs`, where the declared field is **absent** from the output, where its value is
   JSON `null`, where a `MONEY` quote's `currency_field` value is absent or not a JSON string, or
   where the value at `field` is a shape §4's reading of that kind refuses.
6. **The arguments are the ones quoted, and the worked case.** A request whose user-facing
   arguments equal the quoted ones is covered; one carrying **one extra** user-facing argument,
   one **missing** one, and one whose value differs are each **not** covered though the price is
   unchanged; a request whose `intended_action` names a different action is not covered; and the
   Sunday re-quote covers the Sunday arguments while the Saturday quote covers neither. Where two
   quotes match on action, kind and digest, **the later in `Goal.quotes` governs**. A quote
   recorded under an **earlier attempt** covers nothing, and a request carrying no `attempt` or no
   `intended_action` is covered by no quote.
7. **A filter is not a charge, and an undeclared argument needs no declaration.** **7(a):**
   against a declaration declaring `price` `MONEY` with `currency_argument` `"currency"`, a
   request satisfying that argument but covered by **no quote** is **not** covered; with a quote
   it is; and a request whose declared argument exceeds the bound is not covered though the quote
   is inside it. A declaration declaring **two** `MONEY` arguments meets no `MONEY` member on that
   route, and one declaring **none** is covered through the evidence route with its site and date
   arguments declared nowhere. A row whose every member is met on the **argument** route does
   **not** cover a request carrying a user-facing argument the declaration declares at no kind —
   the `send_message` case, where a fixed `subject` must not cover a changed `body` — and a
   `GoalQuotes` read that **raises** leaves the request not covered and the fault reported, never
   an empty tuple. **7(b):** a declaration is **not constructible** where a
   `BoundedArgument` names a key of its own `system_supplied`, where two name one `argument`,
   where a `MONEY` one carries no `currency_argument`, where a `PERIOD` or `TERMS` one carries
   one, and where `argument` equals `currency_argument`; and a `ValueBound` is not constructible
   where an exclusivity flag is set beside an absent endpoint.
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
authorises — the standing authority §9 clause (ii) exists to prevent (ADR-0070 §1).

**It is a partial supersession of exactly four documents** (ADR-0070 §3) — ADR-0254 in **seven**
scopes, ADR-0016 in **one**, ADR-0249 in **one** and ADR-0255 in **one count** — and the `Status`
line of each names its scopes **without an `ADR-NNNN` token inside the parentheses**, so ADR-0070
§4's extraction invariant holds. Against every other ADR it cites it is a **stacked addition**.
**The records land in the same change as this document** (ADR-0082 §7), and nothing else in any of
the four is edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

**This ADR is marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
blockquote at column 0, unmarked text beside a mark supplies no obligation of its own, and quoted
marks from other ADRs appear inside quotation marks in running prose. **It is a contract-surface
change** — two `core` types change shape, an enumeration gains a member, four types are added and
three Protocols move (`ToolDefinition` gains two fields, `Goal` two, `ActionRequest` two) — so it owes **both** review lenses on one tree, which ADR-0015 §1 makes true
of a prose-only PR. **It merges as its own PR, ratified, before anything implements against it**
(golden rule 5); §11's lanes are briefed after it merges, and the ratification flip is one line
and no other byte (ADR-0165).
## Consequences

**What becomes possible.** ADR-0254 §20's Lane 2 can be briefed: a row can carry a non-empty
`coverage`, so route (d) has something to compare and the owner's *"a price change within an
approved limit should remain covered"* has a mechanism. A ceiling the user stated once covers
every later call whose quote sits under it, **at a tool that declares nothing about money at
all**, and *"make it Sunday"* is answered by a re-quote rather than by a second question. A
declared money argument is an **additional** comparison and never a substitute, because a
`max_price` filter says nothing about the charge; the cost is that **an act with no quote is not
covered and the user is asked**, which the owner names as feasibility rather than restriction and
which is the fail-closed direction.

**What becomes harder, and it is the honest cost.** A request carrying any argument the
declaration declares at no kind is covered only where a member is met through the **evidence**
route, so a tool with undeclared arguments and no quote asks on every call — the price of keeping
*"no omission reads as consent"* once arguments stop being named by members. And the digest is
exact, so a quoting read and a booking that spell one fact under two keys never match.

**Two residuals are stated rather than closed, and §11 makes closing both a condition of wiring
anything consequential through this route.** A quote is bound to the attempt that recorded it and
to nothing finer, so a price that **moves inside one attempt** — or a newer quote appended between
the policy's read and the claim — can leave a dispatch resting on a figure that is no longer true.
And the digest binds the **user-facing** arguments alone, so a system-supplied input a price
depends on, a **locale** where an idempotency key is per-call identity, leaves the digest equal
though the price moved. Verification and cancellation do not answer either: they report and
compensate afterwards, and **neither makes the permission decision valid when it is taken**.

**The reading is the narrow part.** §4's table has sixteen forms and three currencies: *"under 100
euros"* reads, and so does the owner's own *"never spend over 100 euros"*; *"under a hundred
euros"*, *"unter 100 Euro"* and *"max €100"* do not. **The negation is adjacent**, so *"never
notify me about charges over 100 euros"* mints nothing; **a truncation of a negated form mints
nothing**, so a planner cannot turn *"not under 100 euros"* into a ceiling; **the table is
asymmetric on purpose**, bare *"less than 100 euros"* minting nothing; and **a strict word mints a
strict bound**, which is why `ValueBound` gains the two flags.

**These are the cases that would falsify the design.** A deployment where users state bounds the
table does not carry, so route (d) is never reached. A quoting read and a booking whose argument
sets differ by a key, so the digest never matches and every act asks — the practical falsifier,
and the one to measure first. A goal whose investigation and whose act fall in **different
attempts** as a matter of course, so the attempt conjunct refuses every quote. A declaration whose
sole `MONEY` argument is an amount the user **receives**, where a ceiling stated about spending
meets it on the argument route — which is why §7 refuses to prove a **floor** against a quote at
all, and why the remaining case is the declaration author's. And a planner naming the wrong output
declaration whose `quoted_outputs` names the wrong field, which is an integration defect rather
than a per-turn one and which the tool's own author is the only party able to make.


## Alternatives considered

**Keeping the argument key on the member, and then deciding the argument at the comparison.**
The first two drafts. Round 1 blocked the first on both lenses and correctly: a value that
**fits** an argument is not a value the act's words **bear on**, so *"4 stars"* minted a price
ceiling, and no selection rule available at the mint could satisfy ADR-0254 §9 clause (ii). Round
2 blocked the second, and the owner's ruling says why in one sentence — *"the price is usually a
consequence of the chosen params, not an argument"* — so a design that could only compare
arguments refused every booking whose price is not a parameter, which is most of them. The
kind-typed member with no argument key survives; what is added is the route that proves the bound
against what the act was quoted at.

**Carrying the quote on a `GoalEvidence` row.** The shape the owner's ruling names, declined on
ADR-0252's own text: that row *"carries no content"*, its `EvidenceBasis` is closed at two members
neither of which admits a typed value read from a step's output, and its `verdict` vocabulary is
fixed per basis — so carrying a quote there would supersede four limbs of one ratified section to
reuse machinery a price has no use for. The quote is recorded where the ruling puts it — **by the
investigation, for the intended action, before the authorisation phase compares it**.

**A planner nomination of the (element, argument) pair, verified by code.** Sound, and the
direction four of round 1's nine findings pointed at. Declined because the pairing is per
*(element, declaration)*, so it cannot live on `GoalElement` and would have to live on
`PlanStep`, superseding ADR-0253's step enumeration and its seam and wire, ADR-0249 §7's
envelope. **Asking the user to confirm the association** is foreclosed by ADR-0254 §1, which
writes the path-(i) row **before** the question is put, so no member can rest on the answer.
**Minting a `MONEY` bound from a bare figure**, with the direction fixed by the kind, was the
first draft's rule and round 1 refuted it twice: the direction is in the user's words or it is
nowhere. And **giving `PlanStep.id` as the client reference** is declined in §10 on the tree's own
text: step ids are unique *"within a plan"* and `Identifier` promises no opacity.
