# 266. A coverage member records the constraint the user stated, and the bound is proved against the quote for the intended action

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **seven narrowly stated scopes, and §9 shows the working for each. §1's proposal
  completeness**: the condition that a proposed row's coverage *"is complete for this request"*
  is restated over §7's test — the row the proposal would write **covers** this request — because
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
  argument; **a `MONEY` member is met through the quote alone**; the validator refusing a member
  that names a system-supplied argument goes with the field it read, its rule preserved by a
  refusal on a new declaration field; and `ToolDefinition` gains **one** further field,
  `bounded_arguments`. **§4's `MONEY` reading, in two limbs**: the currency is read off the
  **quote** on the evidence route and off the **declaration** on the argument route, never off
  the bound; and its two inequalities are read strictly where the bound's own flag is set.
  **§9 clause (ii)**: *"an argument the act's own words bear on"* is given its mechanical test —
  agreement between the constraint's kind and the kind of the thing it is compared against, and
  never numeric fit, never a model's nomination. **§8's and §10's resolution enumeration, in the
  closure at three alone**: a fourth `ResolutionRule`, **`STATED_BOUND`**, reads a bound off the
  span by a closed table — which §19 books by name and this decision fires. Every other clause of
  all seven sections binds entire, several of them load-bearing here: §1's three write paths, its
  write-before-the-question rule and its other three proposal conditions, untouched because a
  member now needs **no argument at write time**; §2's two-shapes-and-no-third rule and its `BoundKind` vocabulary; §3's conditions 1-5,
  its user-facing classification, its no-omission-reads-as-consent rule and its canonical
  encoding; §4's totality and its three readings; §8's basis and its two-zones clause; §9's
  clauses (i) and (iii) and its discard rule; §10's three ratified resolutions and its
  no-member-where-a-resolution-cannot-be-taken sentence; §13's recheck-at-`decide` and its
  no-cached-verdict rule, which §7 below is taken under; and §15's writer clauses.
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
  §7's evidence route has no operand and a `MONEY` member is met nowhere. Every other clause binds
  entire, and §2's bounded-history construction is the one §6's elision reuses.
- Date: 2026-09-15
## Context

### Where this comes from

Issue **#2373**, found in the pre-flight of ADR-0254 §20's **Lane 2** — the lane that makes
`orchestration` propose an `Authorization` on a `CONFIRM` and write path-(ii) corrections and
path-(iii) opening acts. That lane stopped before writing code: ADR-0254 states that
`orchestration` mints a `CoverageMember` from a recorded act and states exactly what a member must
contain, but **no clause states how a recorded span is associated with an argument key, nor how
the member's shape is chosen**.

The owner's Q1 ruling of 2026-09-12, which ADR-0254 records whole, is what the answer has to
serve: *"Bind authorization to explicitly fixed values and explicitly permitted ranges. A price
change within an approved limit should remain covered. A clear later instruction such as 'make it
Sunday' can supply authorization for that change … Ask only when the concrete action introduces
something not already covered."*

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

- **§10** states three resolutions, each *"a total function of recorded inputs"*, and every one
  turns **a span into a value**: none selects the span and none names what the value is for.
- **§9 clause (ii)** states the **property** the association must have — a value *"for an argument
  the act's own words bear on"* — and then what it may not do. A property is not a procedure.
- **§8** closes `AuthorizationBasis` at `act`, `span` and `resolution`; nothing on it names an
  argument. And **§1's path (iii)** points at the goal's interpretation, but `GoalElement`
  (ADR-0249 §1, ADR-0253 §7) carries **no typed value and no argument key**.

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

> **Normative — `ValueBound` changes in three respects and no others.** A **`MONEY`** bound
> carries `currency`, and **`maximum` and `minimum` each optional with at least one present**,
> refused at construction where both are absent and where a `minimum` present beside a `maximum`
> exceeds it — so a stated **ceiling** and a stated **floor** are each representable. It also
> carries **`maximum_exclusive` and `minimum_exclusive`, each a `bool` defaulting to `False`**,
> `MONEY`-only and each refused where its own endpoint is absent, **so a bound the user stated
> strictly is representable as one**: *"under 100"* excludes `100` and *"at most 100"* includes
> it, and the two stop being one value. And **`currency_argument` is removed**: the key carrying
> an amount's currency is a fact about a **declaration**, not about an act, and §7 reads it
> there. `PERIOD` and `TERMS` are unchanged.

> **Normative — ADR-0254 §4's `MONEY` comparison is restated over the two flags and in no other
> respect.** The amount satisfies the bound where it is **less than** `maximum` if
> `maximum_exclusive` and **less than or equal to** it otherwise, and **greater than** `minimum`
> if `minimum_exclusive` and **greater than or equal to** it otherwise. Every other conjunct of
> that reading is unmoved — the `Decimal`-accepting shapes, the finite-and-not-negative refusal,
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
> - **a `maximum`**, **exclusive** — `under <amount>`, `below <amount>`;
> - **a `maximum`**, **inclusive** — `<not> over <amount>`, `<not> above <amount>`,
>   `<not> more than <amount>`, `at most <amount>`, `no more than <amount>`, `up to <amount>`;
> - **a `minimum`**, **exclusive** — `more than <amount>`, `over <amount>`, `above <amount>`;
> - **a `minimum`**, **inclusive** — `<not> under <amount>`, `<not> below <amount>`,
>   `<not> less than <amount>`, `at least <amount>`, `no less than <amount>`.
>
> **Each negated row is the positive comparator inverted, endpoint included**, which is the
> arithmetic and not a choice: *"not over 100"* admits exactly `100` because *"over 100"* excludes
> it. *"no more than"* and *"no less than"* are the case where the negation sits directly against
> the comparator; they are listed in their own right so the table reads whole, and both routes to
> them give one answer.
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

> **Normative — the mint reads the goal's own current interpretation and its retained history,
> and it reads nothing else.** **No request, no plan, no step, no declaration, no registry, no
> quote, no store of turns and no clock.** A member is therefore the same value whatever call was
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

> **Normative — a step declares the output its quote is read from, and `core/types.py` gains
> `StepQuote`**, a frozen model with `extra="forbid"` carrying exactly **`kind`** (a
> `BoundKind`), **`field`** (an `EncodableText | None`, a key of **that step's own** output at
> depth one, absent meaning the whole output) and **`currency_field`** (an `EncodableText | None`,
> `MONEY` only, required there and absent otherwise). **`PlanStep` gains `quotes`, a
> `StepQuote | None` defaulting to `None`**, and **a `PlanStep` carrying `quotes` and no
> `intended_action` is not constructible** — a quote with no act to be for is a value nothing can
> ever be proved against, and the refusal is at the type rather than at the mint.

> **Normative — `orchestration` mints the quote from the completed step's own output, and the
> planner's contribution is a selector the loop resolves.** After a step carrying `quotes`
> completes, `orchestration` mints an `ActionQuote` whose `intended_action` is that step's, whose
> `attempt_id` is the attempt that step ran under, whose `kind` is the `StepQuote`'s, whose
> **`value` is read at `field` of that step's stored output** and whose `currency` is read at
> `currency_field`, whose `read_from` is composed exactly as ADR-0253 §8 composes an
> `InterpretedOutput` — `execution_id` from the execution it read, `step_id` and `field` from the
> step — and whose **`arguments_digest` is taken over that step's own request's user-facing
> arguments**. **Where the field is absent from the output, where the value there is JSON `null`,
> where a `MONEY` quote has no value at `currency_field` or the value there is not a JSON string,
> or where the value at `field` is not a shape §4's reading of that kind accepts, no quote is
> minted** and nothing is recorded.


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
> **It refuses a command naming a goal the store does not hold, and one whose `intended_action`
> is not the `id` of a member of that goal's own `intended_actions`** — the window ADR-0265 §4
> closes at the store for a plan, closed here with the same error class.

> **Normative — the wire, the export, the stored shapes and the migration, and it is ADR-0265
> §5's clause one record over.** **`PROTOCOL_VERSION` moves by exactly one, in the lane that lands
> the `core` surface**, and `wire/envelope.py`'s log gains an entry naming this ADR and the
> reason: `Goal` gains two fields and `PlanStep` gains one, `Goal` is carried on
> `TurnResult.goal` and `PlanStep` inside `ActionPlan`, both set `extra="forbid"`, and
> `wire/codec.py` renders a model by `model_dump()`, so each on its own makes a hub's turn
> undecodable by a client at the previous version. **`PlanExport` gains no member and
> `schema_version` moves for the record's shape alone**, on ADR-0039 §10's own mechanism, because
> a quote rides **inside `Goal`** which `PlanExport.goals` already carries — so ADR-0014 §5's
> closure rule is satisfied by construction and `delete_goal`'s cascade reaches a quote because it
> is inside the goal. **Every stored row stays readable and the migration is an addition with a
> total default**: a `Goal` written before this decision decodes with `quotes` empty and
> `quotes_elided` `0`, and a `PlanStep` with `quotes` absent, which is a conforming plan rather
> than a degraded one. **No lane invents a quote for a stored goal**, because a price nothing read
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

> **Normative — the evidence route, and a member is met by it where all six hold.** The request
> carries an `intended_action` and an `attempt`; a quote of the row's `goal` names **that** action
> and carries **that** `attempt_id`; the quote's `kind` equals the member's; the quote's
> `arguments_digest` equals the digest of **this request's** user-facing arguments, taken exactly
> as §6 takes it; the member is **not** a `MONEY` bound carrying a `minimum`; and the quote's
> `value` satisfies the member under ADR-0254 §3's fixed comparison or §4's bounded readings, with
> a `MONEY` bound's **currency conjunct taken at the quote's own `currency`** and at no key of the
> request. **Where two quotes match on action, kind and digest, the one latest in `Goal.quotes`
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
> **The evidence route proves a ceiling and never a floor.** A quote states what the
> act will **cost**, and a `MONEY` `minimum` may be a statement about what the user will
> **receive**; kind agreement cannot tell the two apart, and a charge satisfying a floor is the
> permissive direction — *"receive at least 150"* would admit a charge of 200. So a `MONEY`
> member carrying a `minimum` is met **only** through the argument route, where the declaration's
> author has said which key is that amount, and a member carrying both is met only where that
> route meets it. **A floor the declaration does not declare is met by nothing and the user is
> asked**, which costs a question and never an authority.

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
>
> **And ADR-0254 §1's completeness condition is restated over the same test.** That condition
> reads that the coverage a proposed row would carry is complete where *"every **user-facing**
> argument of the request … is named by a member"*, which no member can satisfy once a member
> names no argument; it is restated as **the row the proposal would write covers this request
> above**. Its purpose is unchanged and is §1's own: a proposal is made only where answering the
> question would establish an authority that can cover a later call, so that §11's projection is
> honest. **Where it fails, no row is proposed**, `Confirmation.authorization` is absent and the
> one call is authorised by route (a) — §1's own disposition, unweakened. That is why a goal with
> no quote for the act proposes no money-bounded row rather than proposing an inert one.

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
> does.** No `ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter, no
> tool and no model output mints, reads, shapes or repairs one. This is ADR-0254 §15's writer
> clause reaching the values §5 and §6 add.

> **Normative — no durable value of this decision is ever taken from a model, and the list is
> exact.** A planner envelope carrying a **`CoverageMember`**, a **`ValueBound`**, an
> **`AuthorizationBasis`**, a `BoundKind` outside a `StepQuote`, an argument key, a
> **`BoundedArgument`**, an **`ActionQuote`**, an `arguments_digest`, an `attempt_id` or an
> **`InterpretedOutput`** has those values **discarded silently** — not an error, not a park, not
> a degradation of the turn — which is ADR-0254 §9's posture extended to exactly the values this
> decision adds, and for its stated reason: a value a model wrote into a durable audit chain is
> unprovenanced.

> **Normative — what a plan may carry is a selector, and what the loop composes from it is not a
> model's value.** A planner contributes exactly two things here and no third: **the span** an
> interpretation element carries, checked against that turn's own utterance by ADR-0249 §7 and
> read only through §4's closed table; and, on a quoting step, the **`StepQuote`** — a `kind` and
> the names of fields of **that step's own output** — which the loop resolves and from which the
> loop composes the `InterpretedOutput` and mints the `ActionQuote`. That is ADR-0253 §8's
> construction reused rather than an exception to it: that section composes an `InterpretedOutput`
> from the plan's own `StepOutputRef` and holds in the same breath that *"No model supplies any of
> the three"*, because a planner writes a selector and what exists afterwards is a value the loop
> read. **Neither contribution can widen an authority**: a differently chosen span mints a
> different or no member, bounded by the user's own words on both sides; and a `StepQuote` naming
> the wrong field yields a value §6 refuses unless it is a shape §4's reading of that kind
> accepts and which must still satisfy the user's own bound — ADR-0254 §3's *"can satisfy … and
> can never supply"* arm. **A model names no argument key, no currency key and no identifier
> anywhere in this decision.**

### 9. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text**, and it is shown rather than
asserted: *"Would a reader holding only the earlier ADR now act differently, or read one of its
clauses more widely than it now holds?"* **Three documents come out yes** — ADR-0254 in seven
scopes, ADR-0016 in one and ADR-0249 in one; every other ADR this decision cites comes out **no**
and takes none, which ADR-0082 §1 requires as firmly — *"Absent a clause that fails §1's test,
there is nothing to record."*

**ADR-0254 §1 — partially superseded, in the proposal's completeness condition alone.** That
condition reads that the coverage a proposed row would carry is *"**complete for this request**:
every **user-facing** argument of the request (§3) is named by a member … **or** the request
carries no user-facing argument at all"*. A member names no argument once §3 above lands, so it
would be satisfiable only by its second limb and **no row carrying a non-empty coverage could ever
be proposed** — the inert outcome this decision exists to remove. §7 restates it as *the row the
proposal would write covers this request*: the same condition over the test that replaced §3's,
with its purpose, its disposition and its cost unchanged. **Every other clause of §1 binds
entire**, the three write paths, the row written before the question is put, the never-edited
coverage, the path-(iii) recipient precondition and the other three proposal conditions
included.

**ADR-0254 §2 — partially superseded, in the member's shape.** §2 declares `CoverageMember`'s
fields *"exactly: `argument`, an `EncodableText`; `fixed`; `bound`; and `basis`"*, states
*"`argument` is a key name and never a path"*, rules that *"No two members of one
`Authorization` name the same `argument`"*, gives a `MONEY` bound a `currency_argument` as
*"the whole of the association between an amount and the currency it is denominated in"*, and
makes `maximum` required with `minimum` optional. §3 above replaces `argument` with `kind`,
restates the no-two-members rule over the kind, moves the currency key to the declaration and the
quote, makes `maximum` and `minimum` each optional with at least one present, and gives each an
**exclusivity flag** so that a strictly stated bound stops being recorded as an inclusive one. A reader
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

**ADR-0254 §4 — partially superseded, in two limbs of the `MONEY` reading and in no other.**
Its **currency conjunct** reads *"the request carries, at the bound's `currency_argument`, a JSON
string equal to the bound's `currency` byte for byte"*, and the bound no longer carries that key;
§7 takes it at the `BoundedArgument`'s `currency_argument` on the argument route and at the
quote's own `currency` on the evidence route, its force unchanged — an amount is never compared
without the currency it is denominated in. And its **two inequalities**, *"less than or equal to
`maximum`"* and *"greater than or equal to"* a `minimum`, are read strictly where the bound's own
exclusivity flag is set (§3). A reader holding only §4 compares a strictly stated bound
inclusively and covers a call at exactly the endpoint the user excluded — the permissive
direction §2's asymmetry names. **Every other clause of §4 binds entire**: the `MONEY` reading in
every other conjunct, the `PERIOD` and `TERMS` readings whole, the no-float rule, the
no-naive-instant rule, the totality-and-refusal clause, the `reason` discipline, the three
failures told apart, and the no-schema clause, which §7 cites as binding it.

**ADR-0254 §9 clause (ii) — partially superseded, in the test of *"bear on"* alone.** The clause
states the property — a resolution turns a span into a value *"for an argument the act's own
words bear on"* — and states no procedure, so a reader holding only §9 has an obligation with no
mechanical test and either invents one or, as #2373 did, stops. **Its mechanical test is kind
agreement between the constraint and the thing the member is proved against**: the quote's `kind`
on the evidence route, the `BoundedArgument`'s on the argument route, and never numeric fit,
never a model's nomination, never a schema. **The clause's prohibitions bind entire and are not
narrowed** — no member for an argument the act never mentioned, no raised `maximum`, no lowered
`minimum`, no added term, no widened `destinations`, no moved `expires_at` — and **clauses (i)
and (iii) and §9's discard rule bind entire**.

**ADR-0254 §8 and §10 — partially superseded, in the resolution enumeration's closure alone.**
Both state `ResolutionRule` *"closed at exactly three members"* and §10 adds *"Exactly three
resolutions exist and there is no fourth"*. §4 above adds `STATED_BOUND`. **This is the
supersession §19 books by name** — *"A fourth `ResolutionRule`. Fired the same way, and never by
a resolution whose inputs are not on the turn it names"* — and the new rule honours that
condition exactly: its only input is the span, which is on the turn the basis names. **Every
other clause of both sections binds entire**: §8's basis fields, its span check, its
both-halves-survive and two-zones clauses and its per-member rule; §10's three ratified
resolutions in every limb, its no-memory-no-preference rule, its normalisation-at-the-mint rule,
and its *"A resolution the loop cannot take is not taken, and no member is minted"*.

**ADR-0016 §1 — partially superseded, in one scope**, and it is the scope ADR-0254 §18 already
took there reaching one further field: the model declaration, and the required-field clause in
the application to `bounded_arguments` alone. The grounds are the clause's own reason, which does
not reach this default — the empty tuple makes the **opposite** claim to the one §1 refuses.
**The exception is this one further field on this argument**, and no lane reads the two records
together as licence to default a third safety field. Every other clause of §1 binds entire.

**ADR-0249 §1 — partially superseded, in the `Goal` declaration alone.** ADR-0265 §8 already
recorded a scope there for `intended_actions`; this decision reaches it again for `quotes` and
`quotes_elided`, and ADR-0070 §4's precedence rule makes the later record govern the overlap. A
reader holding only §1 authors a goal with no place for a quote, so §7's evidence route has no
operand and a `MONEY` member is met nowhere. **Every other clause of §1 binds entire**, and §2's
bounded-history construction is reused by §6's elision rather than restated.

**And the ones that come out no, shown rather than left to a reader to check.** **ADR-0254 §1**
is otherwise relied on entire — the write-before-the-question rule, the never-edited coverage and
all three paths stand exactly as ratified — and **§13** is the clause §7 is taken under: the
recheck at `decide`, the no-cached-verdict rule, and *"Coverage and sufficiency are two tests and
neither clears the other"*, which stays true, a standing quote satisfying no condition of a step.
**ADR-0252** is read and **not moved**: §1's no-content rule, its two bases and per-basis verdict
vocabularies, §6's four tests, §7's conflict rule, §11's digest and §§12-13's store, retention and
export are each untouched, and §6 above states why a quote is a record of its own instead.
**ADR-0253** is superseded in nothing: §8's `InterpretedOutput` is reused **unaltered**, composed
by the loop from a plan-carried selector exactly as that section composes it from a
`StepOutputRef`, so its *"No model supplies any of the three"* is honoured by the same
construction; and its `PlanStep` fields are added to rather than enumerated closed — a **stacked
addition**, and `quotes` carries no label, so §9's label-space count and its resolve-once
discipline are untouched. **ADR-0265** is relied on entire: §1's identity is what a quote names,
and §4's *"a step naming no intended action is held to nothing by this decision"* is joined by an
obligation stated elsewhere rather than contradicted — such a step is simply met by no quote and
the user is asked. **ADR-0014 §5, ADR-0249 §12, ADR-0250 §9, ADR-0252 §12 and ADR-0265 §5** each
widened `PlanStore` without enumerating it closed, so §6's member is a **stacked addition**, and
§5's closure rule is satisfied by a quote riding inside `Goal` with `schema_version` moving on
**ADR-0039 §10**'s own mechanism. **ADR-0255 §13 and §15 item 19** are **not** moved: the residual
§10 books is an **overcharge the verification guarantee detects and the cancellation guarantee
remedies**, so it falls inside the three guarantees that rule already requires and no further
prerequisite is owed — the test ADR-0265 §6 applies, coming out the other way there because its
duplicate is *"correctly claimed, correctly authorised, correctly verified"*. **ADR-0021 §1** is
relied on for the one canonical encoding; **ADR-0145 §2 and §9** are cited for the hazards §6 and
§7 avoid; **ADR-0029 §5** is relied on rather than superseded.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling,
> and each carries the condition that fires it.

- **Who supplies the value of a system-supplied argument.** ADR-0254 §3 requires
  `orchestration` to supply one and names an idempotency key, a client reference and a locale.
  **This decision states one source and lands no filler**: a value supplied into an argument as a
  spending safeguard is the member's own `maximum` (§7), and today `bounded_arguments` and
  `system_supplied` are disjoint, so no such fill is constructible. `PlanStep.id` is **refused
  here** as the client reference — `_step_ids_are_unique` guarantees uniqueness *"within a plan"*
  alone and `Identifier` guarantees no opacity — and ADR-0029 §5's derived key is computed from
  the ruling's id, which does not exist when the fill must happen. Fired by the decision that
  mints a dedicated opaque per-call reference, and by the one that classifies an argument as both
  declared and filled.
- **What makes a `DATE_FROM_CONTEXT` resolution total over a span** — the reader that turns
  *"Sunday"* or *"that weekend"* into a half-open interval in a zone. §4 states what such a
  resolution **mints** and not how it is **taken**. **Until that decision lands, the only
  readings an element takes are `STATED_BOUND` and `AS_STATED`, and no `PERIOD` member is minted
  by any live path.** Fired by the decision that lands the reader, with its own totality
  argument and its own arms.
- **Any widening of §4's table** — a form it does not list (bare *"less than"* among them), a
  currency it does not name, a language other than English, a figure written in words, a bound on
  a count. It is deliberately narrow and refuses rather than guessing. Fired by a decision that
  states the wider reading and its own totality argument.
- **How stale a quote may be inside one attempt.** §7 bounds a quote to the attempt that recorded
  it and invents no duration, so a price that moves **within** one attempt after its quote was
  read can be dispatched under a bound the new price breaks. **This decision does not close that,
  and no clause here should be read as closing it**: what closes it is a provider-enforced quote
  hold, or a re-quote taken immediately before dispatch, both properties of an integration that
  this document may not state for one. The interval is an **overcharge**, the class ADR-0255 §13's
  verification guarantee detects and its cancellation guarantee remedies before any consequential
  capability is wired. Fired by the decision that gives an integration a quote hold, and by A10.
- **Which system-supplied keys a price depends on.** §6 takes the digest over the **user-facing**
  arguments alone, because a system-supplied key is filled per call and a digest over an
  idempotency key could never match twice. ADR-0254 §3's three examples are not one kind: an
  idempotency key and a client reference are per-call identity, and a **locale** is an input a
  price can depend on. **This decision draws no line between them.** Fired by the decision that
  classifies a system-supplied key, which then decides which of them the digest binds.
- **A fourth `BoundKind`**, so that an argument which is neither an amount, a period nor a named
  term can be declared and met on the argument route. Fired by an argument that needs one, with a
  total exact ordering the corpus can state — ADR-0254 §2's own condition.
- **A `FROM_SHOWN_RECORD` basis for a coverage member**, which needs an element carrying both a
  span and the record its reference resolved to, and ADR-0249 §1 admits none. Fired by the
  decision that gives an element that shape. **And which of two constraints of one kind the user
  meant**, which §5 refuses rather than choosing — fired by a decision stating how two acts
  compose one member, or by a surface that asks.
- **What the verification phase does with a quote.** The owner's ruling makes the actual charge
  confirmed after the act and a quote-to-charge mismatch *"a reported finding"*; **no clause here
  verifies anything, compares a charge, or writes a finding**, and `AttemptPhase.VERIFY` is
  A10's by ADR-0255 §17's own assignment. Fired by that decision, which this one gives a typed
  quoted value to compare against.
- **Coverage's other conditions, expiry and every surface.** ADR-0254 §3's conditions 1-5, §§5-7,
  §12's ladder as ADR-0256 §1 leaves it, and §11's projection: untouched, and this decision adds
  no field any of them renders.

### 11. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **four lanes**, in this order, **each one
> subsystem plus its tests**, and **no lane wires a consequential capability** or enables anything
> in a production deployment — ADR-0254 §17's rule as ADR-0255 §13 leaves it binds all four.
> **No lane writes an `Authorization`**: ADR-0254 §20's Lane 2 does that, is briefed after all
> four merge, and is what #2373 unblocks.

- **L1 — the contract, in `core` alone**, and it is a **triad**: `CoverageMember`'s `kind` and
  the removal of `argument`; `ValueBound`'s `MONEY` reshape and the removal of
  `currency_argument`; `ResolutionRule.STATED_BOUND`; `BoundedArgument` and
  `ToolDefinition.bounded_arguments`; `ActionQuote`, `StepQuote`, `PlanStep.quotes`,
  `Goal.quotes`, `Goal.quotes_elided`, `MAX_ACTION_QUOTES`, `ActionQuoteMinting`,
  `ActionRequest.intended_action` and `ActionRequest.attempt`; the **`GoalQuotes` Protocol with
  its shared conformance suite and its canonical fake in `ai_assistant.testing`**, which
  `CONTRIBUTING.md` makes one unit of work; and **`PROTOCOL_VERSION`, `wire/envelope.py`'s log
  entry and `PlanExport.schema_version`** (§6), this being the one lane that is that ground.
  Arms 4(a), 5(a) and 7(b).
- **L2 — the store, in the plan-store implementations and their shared conformance suites
  alone.** `PlanStore.record_quotes`, its compare-and-swap, its two refusals and §6's elision;
  the stored-shape migration §6 states; and the **production `GoalQuotes` implementation**, whose
  rows are the `quotes` of the goal the store already holds, with its conformance suite run
  against it — so the composition root has a concrete to inject and the policy still names only
  the Protocol (golden rule 1). Arm 5(b).
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
   `"never spending over 100 euros"` each mint **nothing**. **3(b):** against an exclusive
   `maximum` of `100` a value of exactly `"100"` does **not** satisfy and against an inclusive one
   it does, and the same both ways at a `minimum`; and a `MONEY` member carrying a `minimum` is
   met by **no quote** however large, and is met at a declared money argument.
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
   `intended_action`, the attempt it ran under, the value at the declared field of that step's
   stored output, the currency at `currency_field`, a `read_from` naming that execution and step,
   and an `arguments_digest` over that step's **user-facing** arguments alone — and where the
   field is **absent** from the output, where its value is JSON `null`, where a `MONEY` quote's
   `currency_field` is **absent or not a JSON string**, and where the value at `field` is a shape
   §4's reading of that kind refuses, **no quote is minted** in any of the four.
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
   arguments declared nowhere. **7(b):** a declaration is **not constructible** where a
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

**It is a partial supersession of exactly three documents** (ADR-0070 §3) — ADR-0254 in **seven**
scopes, ADR-0016 in **one** and ADR-0249 in **one** — and the `Status` line of each names its
scopes **without an `ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction
invariant holds. Against every other ADR it cites it is a **stacked addition**. **The records land
in the same change as this document** (ADR-0082 §7), and nothing else in any of the three is
edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

**This ADR is marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
blockquote at column 0, unmarked text beside a mark supplies no obligation of its own, and quoted
marks from other ADRs appear inside quotation marks in running prose. **It is a contract-surface
change** — two `core` types change shape, an enumeration gains a member, four types are added and
three Protocols move — so it owes **both** review lenses on one tree, which ADR-0015 §1 makes true
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

**What becomes harder, and it is the honest cost.** An argument the declaration declares at no
kind is compared against no member, so where a row's members are all met through the **argument**
route the call's other arguments are pinned by nothing, and only a member met through the
**evidence** route pins them by the quote's digest — a real loosening of ADR-0254 §3's old set
equality, taken deliberately on the owner's ruling. And the digest is exact, so a quoting read and
a booking that spell one fact under two keys never match and every such act asks.

**The reading is the narrow part, and it is where a reader should look first.** §4's table has
sixteen forms and three currencies: *"under 100 euros"* reads, and so does the owner's own
*"never spend over 100 euros"*; *"under a hundred euros"*, *"unter 100 Euro"* and *"max €100"* do
not. **The negation is adjacent**, so *"never notify me about charges over 100 euros"* mints
nothing. **The table is asymmetric on purpose**: *"not less than 100 euros"* mints a floor while
bare *"less than 100 euros"* mints nothing. **And a strict word mints a strict bound**, which is
why `ValueBound` gains the two flags rather than recording both as one.

**Two residuals are stated rather than closed, and both are booked in §10.** A quote is bound to
the attempt that recorded it and to nothing finer, so a price that **moves inside one attempt**
after its quote was read can be dispatched under a bound the new price breaks; what closes that is
a provider-enforced quote hold or a re-quote taken immediately before dispatch, neither of which
this document may state for an integration, and the interval is an overcharge — the class
ADR-0255 §13's verification and cancellation guarantees reach before any consequential capability
is wired. And the digest binds the **user-facing** arguments alone, so a system-supplied input a
price genuinely depends on — a **locale**, where an idempotency key and a client reference are
per-call identity — leaves the digest equal though the price moved.

**These are the cases that would falsify the design.** A deployment where users state bounds the
table does not carry, so route (d) is never reached. A quoting read and a booking whose argument
sets differ by a key, so the digest never matches and every act asks — the practical falsifier,
and the one to measure first. A goal whose investigation and whose act fall in **different
attempts** as a matter of course, so the attempt conjunct refuses every quote and the route is
inert. A declaration whose sole `MONEY` argument is an amount the user **receives**, where a
ceiling they stated about spending meets it on the argument route — kind agreement is coarser than
intent, which is why §7 refuses to prove a **floor** against a quote at all and why the remaining
case is the declaration author's. And a planner that names the wrong output field in a
`StepQuote`, which yields a value §6 refuses unless it is a shape the kind's reading accepts and
which must still satisfy the user's own bound, but which may satisfy it for the wrong reason:
containment is ADR-0254 §3's *"can satisfy … and can never supply"* arm plus the verification
phase §10 books, and nothing here detects it on its own.

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
