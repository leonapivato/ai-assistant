# 266. A coverage member records the constraint the user stated, and the bound is proved against the quote for the intended action

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **seven narrowly stated scopes, and §9 shows the working for each. §1's proposal
  completeness**: the condition that a proposed row's coverage *"is complete for this request"* is
  restated over §7's test — the row the proposal would write satisfies **condition 6** for this
  request, condition 6 alone because a proposal is written `PROPOSED` and §3's condition 1 asks
  for a live row — because the ratified wording is stated over *"every user-facing argument …
  named by a member"* and a member names none, so no row carrying a non-empty coverage could
  otherwise be proposed at all; its purpose, its disposition and its cost are unchanged. **§2's
  member shape**: a `CoverageMember` stops carrying an `argument` and carries a **`kind`**
  instead, so a member records *what the user stated* and never *which slot it fills*; with it go
  §2's depth-one clause, its no-two-members-name-one-argument rule (which becomes **one member per
  kind**) and its `currency_argument` field on a `MONEY` bound, while the bound gains
  **`maximum_exclusive`** so that a ceiling the user stated strictly stops being recorded as an
  inclusive one. **`maximum` stays required and `minimum` stays optional**, exactly as ratified:
  §4 mints only ceilings, so no floor is minted through this decision at all. **§3's condition 6
  and its field count**: the set equality over argument **keys** and the per-argument rule that
  reads a member *"naming it"* are replaced by **two routes** — a member is met against the
  **quote taken for the step's intended action**, or, where the declaration declares an argument
  at the member's kind, against that argument — and each endpoint names exactly one: a `MONEY`
  **`maximum`** needs the quote, and the declared argument **as well** where one exists; the
  validator refusing a member that names a system-supplied argument goes with the field it read,
  its rule preserved by a refusal on a new declaration field; and `ToolDefinition` gains **one**
  further field, `bounded_arguments`, so §3's *"`ToolDefinition` gains one field"* is over-narrow
  by one. **§4's `MONEY` reading, in two limbs**: the currency is read off the **quote** on the
  evidence route and off the **declaration** on the argument route, never off the bound; and its
  `maximum` inequality is read strictly where `maximum_exclusive` is set. **§9 clause (ii)**:
  *"an argument the act's own words bear on"* is given its mechanical test — agreement between the
  constraint's kind and the kind of the thing it is proved against, never numeric fit and never a
  model's nomination. **§8's and §10's resolution enumeration, in the closure at three alone**: a
  fourth `ResolutionRule`, **`STATED_BOUND`**, which §19 books by name. **Every other clause of all
  seven sections binds entire**, §9 naming them section by section — §1's three write paths and
  write-before-the-question rule, §2's two-shapes validator and `BoundKind` vocabulary, §3's
  conditions 1-5 and its no-omission-reads-as-consent rule, §4's totality, §8's basis, §9's
  clauses (i) and (iii), §10's three ratified resolutions, §13's recheck-at-`decide` under which
  §7 below is taken, and §15's writer clauses among them.
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
investigation records the quote for the intended action, the authorisation phase compares the
bound against it before execution, and **nothing about the price is compared against an argument
of the call**; a declared money argument is compared **as well** where one exists, *"a filter is
not a charge"* keeping it from ever standing in; no quote means investigate or ask, which is
feasibility rather than a restriction; and the evidence covers a step **only where the step's
arguments are the ones that were quoted**, any difference meaning re-quote or ask.

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
argument the act never mentioned"*, but only path (ii)'s widening is a store-enforced refusal, so
a freshly minted path-(i) or path-(iii) member is checked by nothing. A wrong association is a
**standing authority the user never gave**, and route (d) then `ALLOW`s inside it with no
`CONFIRM` — the failure direction §9's three clauses exist to close.

### The tree, read rather than assumed, at `origin/main` `8dbfddf0`

ADR-0254's Lane 1 and Lane 3 have landed and so has ADR-0254 §20's route-(d) wiring. `core/types.py`
carries `Authorization`, `CoverageMember`, `ValueBound`, `BoundKind`, `AuthorizationBasis`,
`ValueResolution`, `ResolutionRule` and `ToolDefinition.system_supplied`; `CoverageMember` carries
`argument` and `ValueBound`'s `MONEY` arm carries `currency_argument` and a **required**
`maximum`, all three of which this decision changes; `canonical_json_bytes` is public and is the
one encoding; `Sha256Hex` is the digest shape and `ActionRequest.parameters_digest` is computed
rather than supplied; `ActionRequest` carries `goal`, `step_id`, `execution_id` and
`egress_binding` and **no `intended_action`**; `permissions/_coverage.py` carries `covers`,
`covers_arguments` and a private `_argument_is_covered`; `ToolDefinition` declares nothing about
what kind of value an argument takes; and **`IntendedAction`, `Goal.intended_actions` and
`PlanStep.intended_action` are ratified in ADR-0265 and are in no lane's tree yet**, so this
decision is written against that contract and not against code.

**`Authorization` rows are written today, and every one of them carries an empty `coverage`.**
`orchestration/runner.py` records what `proposed_authorization` returns and `app/composition.py`
constructs the `SqliteGoalAuthorizationStore`, so a deployment does hold rows; but
`orchestration/authorizing.py` builds every one with `coverage=()` and returns `None` for any
request carrying a user-facing argument — the vacuous-completeness gate #2373 names — and no
`CoverageMember` is constructed in `src/` outside the canonical fake. **§11's migration clause is
written on that reading and on nothing carried forward**, and nothing records a quote.

### What this ADR is not allowed to settle

It decides what a member **records**, how a span **becomes** one, and **what a member is proved
against** — and nothing beyond that. It leaves ADR-0254 §3's conditions 1-5, §§5-7, §12's expiry
as ADR-0256 §1 leaves it and §11's projection untouched; it opens no route, relaxes no floor,
lowers no threshold and moves no ruling.

**And it does not decide where a quote is carried, what records one, or how a policy obtains
one.** §6 states the four facts a quote must supply and reads them from nowhere concrete; the
carrier, the producer and the face a policy holds are the **quote decision**'s, booked in §10 with
what fires it. ADR-0252's `GoalEvidence` is read and is **not** moved: §6 states why, and that
reading is a constraint on the booked decision rather than a choice taken here.

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
> unmoved. Every other conjunct of that reading is unmoved — the `Decimal`-accepting shapes, the
> finite-and-not-negative refusal, the no-float rule and the currency conjunct §7 relocates — and
> **`PERIOD` stays half-open and `TERMS` stays equality of stated characters**, neither flag
> reaching either.

**Why the argument key was the defect rather than the rule that chose it.** A value that *fits*
an argument is not a value the act's words *bear on*, so no rule selecting an argument at the mint
could satisfy ADR-0254 §9 clause (ii): a constraint about a hotel's star rating has a number in it
and would fit a price. **Bearing is established by kind agreement between the constraint and the
thing it is proved against, and by nothing else** — *"four stars"* has no `MONEY` reading (§4), so
it is proved against no price.

**It does not follow that a member is portable across tools.** ADR-0254 §3's condition 3 compares
the request's `tool` against the row's **by value** and this decision leaves it entire, so a row
established about one declaration covers a call made under another in no case — the rebinding #54
closed, unweakened. What a member survives is an argument renamed inside one declaration, and §1's
write-before-the-question rule is untouched, a member needing **no argument when it is written**.
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
>   `at most <amount>`, `up to <amount>`.
>
> **Seven forms and no eighth**: *"no more than 100 euros"* is not a row of its own, `no` being a
> token of the negation vocabulary below, so it reads as `<not> more than <amount>`.
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

> **Normative — `<not>` is adjacent to its comparator, and the admitted prefix is closed at two
> tokens.** `<not>` is **one** token of the negation vocabulary — closed at `not`, `never`, `no`,
> `without`, `don't`, `doesn't`, `didn't`, `won't` and `can't` — optionally followed by **exactly
> one** token of the spending vocabulary — closed at `spend`, `pay`, `go`, `charge` and `cost` —
> and by **nothing else** before the comparator. **Every member of both vocabularies is a whole
> token under the normalisation stated above**, which folds case and collapses whitespace and
> splits nowhere else, so the contractions are listed as the words they are and no clause asks a
> reader to find `n't` inside `don't`. So *"never spend over 100 euros"* matches `<not> over
> <amount>` and mints a **`maximum`** of `100`, which is the owner's own illustration of this
> rule, and the inversion is the user's own arithmetic rather than a direction read into words
> that do not carry one. **Everything else the negation might govern mints nothing**: *"never
> notify me about charges over 100 euros"* carries four tokens between the negation and the
> comparator and is not a spending ceiling; *"not 100 euros"* and *"not exactly 100 euros"* state
> no direction at all; a **second** negation token inside the prefix takes the span out of every
> form; and an inflected spending word (*"never spending over 100 euros"*) is not a member of the
> closed set.
>
> **The negated rows read because their own negation is inside the span they match**, which the
> clause below is stated over.

> **Normative — the span must be a whole clause of the act's utterance, and a proper part of one
> mints nothing.** Fold and tokenise the act's own recorded utterance as above, then split it into
> **clauses** at every `,`, `;`, `.`, `!`, `?` and at an em or en dash, discarding empty segments
> and trimming each. **No member of any kind is minted unless the element's `span`, folded the
> same way, is equal to exactly one of those clauses** — equal as a whole string, not contained in
> one — **and that clause occurs exactly once in the utterance.** Two equal clauses admit two
> conforming answers and `GoalElement.span` is **text and not an offset**, so nothing on the
> record says which the model meant; a span equal to no clause is a **proper part** of one, and a
> proper part carries whatever polarity the rest of its clause supplies.

**This is what closes the truncation class by construction, and it replaces an argument that was
false.** An earlier draft refused only the truncations a closed negation vocabulary could see, and
argued that whatever survived was harmless *because a ceiling can only restrict*. **That argument
does not hold.** *"Avoid booking hotels under 100 euros"* is a **floor**, stated in a word no
vocabulary recognises; its substring *"under 100 euros"* reads as a ceiling of `100`, and the
authority minted is standing permission to spend in exactly the region the user excluded. A
ceiling is safe only where the clause it came from was itself about a ceiling, and **that is a
property of the clause, not of the substring**. Requiring the span to *be* a clause makes the
polarity a rule reads the polarity of the whole text the user wrote there — so that case, *"avoid
spending over 100 euros"*, *"not under 100 euros"* and *"under no circumstances spend over 100
euros"* each mint **nothing**, whatever substring was chosen. What survives is not a rule about
*avoid*: it is that the word can no longer be left outside the text the rule reads. The cost is
that a bound stated inside a longer clause mints nothing and the act asks — *"I want somewhere
nice and under 150 euros please"* is one clause and matches no form — while the owner's own
*"Book Riverside if it is dry Saturday, up to 150 euros"* still reads, its second clause being
*"up to 150 euros"*.

> **Normative — a negation standing before the span's clause refuses every reading, not only this
> table's.** **No member of any kind is minted where any token of the negation vocabulary appears
> anywhere in the utterance before the clause the span is equal to**, folded and tokenised as
> above. The clause rule already makes a span carry its own clause's polarity; this refuses the
> case where an earlier clause governs a later one, and it is deliberately blunt — it refuses
> *"I'm not fussy — spend under 100 euros"* along with the rest, which costs a question. **The
> bar is over every reading of this section**, which matters for the readings §10 books as much
> as for this one.

> **Normative — a strict word mints a strict bound, and the endpoint is never widened.**
> *"under 100 euros"* mints `maximum` `100` with `maximum_exclusive`, so a call at exactly `100`
> is **not** covered; *"at most 100 euros"* mints the same `maximum` without it, and a call at
> `100` is. **No reading rounds, quantises, nudges or relaxes an endpoint in either direction**,
> and no lane reads a strict word as an inclusive bound *"because the difference is a cent"* —
> ADR-0254 §2's asymmetry is the reason, since the difference is a cent in the direction that
> authorises a call the user did not authorise.

> **Normative — `STATED_BOUND` is the only reading that mints a member, and the other three mint
> nothing.** **`AS_STATED` mints no member from an element**, **`DATE_FROM_CONTEXT` mints none**,
> and **`FROM_SHOWN_RECORD` mints none** — so the only member this decision mints is a **`MONEY`
> ceiling**, and there is no ordering between readings to state. `FROM_SHOWN_RECORD` could not
> reach an element in any case: ADR-0249 §1's validator gives a `USER_STATED` element a span and
> **no** `evidence_id`, so none carries both a span and the record its reference resolved to. §10
> books the other two with what fires each.

**Minting only a ceiling is the second narrowing, and it is about what a *whole clause* can do
rather than about what a substring can.** Even read clause by clause, a floor and a term are the
readings a wrong one is dangerous in: *"avoid sending to Alice"* is one clause, and an `AS_STATED`
`TERMS` member fixing *"Alice"* would cover a declaration at exactly the recipient the user
forbade — the clause rule cannot help, because the clause itself says *avoid*. **A ceiling
minted from a clause that matches one of §4's forms carries that form's own direction**, which is
why the table is the whole reading and why nothing outside it mints anything. What that costs is
stated rather than hidden: a term the user named, a period they gave and a floor they set each
mint nothing, and every act resting on one asks. §10 books all three with what fires each.

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
> the one the basis already names, which ADR-0254 §1 re-reads at the write in any case. A member
> is therefore the same value whatever call was being built when the row was written, which is
> what makes *"the authorization records the constraint as the user stated it"* true of the record
> and not merely of its intent — and it is
> why no plan a model produced can shape the **content** of an authority, at any path, by any
> route.

### 6. What a `MONEY` ceiling is proved against: the quote, stated as an interface and read from nowhere concrete

> **Normative — a quote is a record of a price, it supplies exactly four facts, and it carries no
> kind.** §7 is written over four facts alone: the **`IntendedAction`** (ADR-0265 §1) it was taken
> for, by `id`; the **arguments it was quoted over**, as the digest below compares; an **amount**
> and its **currency**, the amount in the form ADR-0254 §4's `MONEY` reading accepts and the
> currency as that reading's ISO-4217 code; and the **step output it was read from**, which is
> provenance and is compared by nothing. **A quote states a price and states nothing of any other
> kind**, so it carries no `BoundKind` and needs none: §7's evidence route is `MONEY`-only for
> that reason, and a carrier that generalised a quote to a kind-tagged value would be answering a
> question this decision does not ask. The quotes of one goal are **totally ordered**, so that a
> second reading of one price is legible as a **refresh** of the first rather than as a second act
> of the user — ADR-0252 §7's *"a refresh supersedes the row it displaces"*, which §7's
> last-governs rule is taken under.

> **Normative — this decision states that interface and nothing else about a quote.** No type, no
> field of any existing model, no store member, no Protocol, no bound on how many a goal holds, no
> rule about which component records one, no expiry and no face by which a policy obtains one.
> Those are the **quote decision**'s, booked in §10 with what fires it, and **no lane of this
> decision authors any of them**.

> **Normative — the arguments a quote was taken over are compared by one digest, over one key set,
> and it is not a second canonicalisation.** The digest is `sha256` over the canonical JSON
> encoding `ActionRequest.parameters_digest` is taken over (ADR-0021 §1), taken on both sides over
> **every argument of the call except those the declaration classifies as a per-call identity**.
> **No declaration classifies any today**: `ToolDefinition.system_supplied` names keys
> `orchestration` fills and says nothing about which of them a price depends on, so **every**
> system-supplied key is inside the digest until the decision §10 books draws that line. **An
> extra argument, a missing one and a changed one each change the digest**, which is the owner's
> rule that the quote covers the booking only where *"the step's arguments are the ones that were
> quoted"*.
>
> **The cost is stated rather than hidden.** `orchestration` fills a system-supplied key **per
> call**, so a declaration that fills one is covered by **no** quote and every act under it asks.
> The permissive spelling is the defect: excluding such keys by kind would let a quote taken under
> one **locale** authorise a charge priced under another, with the digest matching throughout.
> §10 books the classification that makes the route live for such declarations.

**Why the carrier is booked rather than decided here.** The owner's ruling of 2026-09-14 names
`GoalEvidence`, and ADR-0252 §1 makes that hard: such a row *"carries no content"*, its
`EvidenceBasis` admits no typed value read from a step's output, and a quote is exactly a second
copy of what was read. **That is a finding about the carrier, not about the proof**, so it is
handed to the booked decision as a constraint rather than answered here — which is the whole
reason the two are separated, and what the Alternatives record.

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
> naming **no key of that declaration's own `system_supplied`** — refused at construction. It is
> the whole of what a declaration says about which of its arguments takes an amount, a period or
> a named term. This is a **BREAKING** contract change to `core/types.py` under golden rule 5 and
> is flagged as one.

> **Normative.** **`ActionRequest` gains `intended_action`, an `Identifier | None` defaulting to
> `None`** — the `IntendedAction` (ADR-0265 §1) the step this request serves is an attempt at,
> which is `ActionRequest.goal`'s shape one field over and is how a request says which act it is.
> A request carrying `None` is met by the evidence route in no case. This is a **BREAKING**
> contract change to `core/types.py` under golden rule 5 and is flagged as one.

> **Normative — `bounded_arguments`' refusal is what preserves ADR-0254 §3's system-supplied
> protection after the validator that stated it is gone.** That section makes a row whose coverage
> names a system-supplied argument not constructible, and it read `CoverageMember.argument`, which
> no longer exists. A system-supplied key is now declared at no kind, so **no member can ever meet
> it on the argument route**, and *"a user is never asked to approve an idempotency key"* holds by
> construction one field over.

> **Normative — the evidence route is `MONEY`-only, and a `MONEY` member is met by it where all
> three hold.** The request carries an `intended_action`; a quote available to the policy (§6)
> names **that** action and its arguments-digest equals the digest of **this request's**
> arguments, taken exactly as §6 takes it; and the quote's amount satisfies the member under
> ADR-0254 §3's fixed comparison or §4's `MONEY` reading, with that reading's **currency conjunct
> taken at the quote's own currency** and at no key of the request. **No member of any other kind
> is met by this route in any case** — a quote states a price and carries no other value (§6), so
> there is nothing for a `PERIOD` or a `TERMS` member to be compared against, and §4 mints no
> member of either kind for this decision to need one for. **Where more than one quote satisfies
> the first two, the one latest in §6's order governs** — a re-quote is a refresh of one fact and
> the later reading is the current price, which is not a precedence rule between two acts of the
> user. **Where no quote satisfies them the member is not met**, the request is uncovered, and the
> user is asked or the act is investigated first — the owner's *"no quote → cannot prove the
> price"*, which is feasibility rather than a restriction on the tool.
>
> **A fault is never an absence.** Where the read behind §6's quotes fails, the request is treated
> as **not covered** and the fault is reported; **no implementation converts a fault into an
> absence of quotes** and none falls through to the argument route, which is the distinction
> ADR-0254 already draws between `AuthorizationError` and absence and is what lets a ruling say
> *no record* rather than *a record that did not cover*.

> **Normative — the argument route, available only where the declaration declares, and it never
> stands in for a quote.** A member of kind *k* is met by it where the declaration carries
> **exactly one** `BoundedArgument` at *k*, the request carries a value at that argument, and the
> value satisfies the member under ADR-0254 §3's and §4's readings, with a `MONEY` bound's
> currency conjunct taken at that `BoundedArgument`'s **`currency_argument`** in the concrete
> request — which is what makes that currency key **covered** rather than unexamined. **Where the
> declaration declares no argument at *k*, or declares more than one, no member of kind *k* is met
> by this route.** **A `MONEY` member needs the evidence route in every case, and the argument
> route as well where the declaration declares an argument at `MONEY`** — both holding, because a
> `max_price` constrains what a search returns and a transfer amount is one leg of a call, and
> *"a filter is not a charge"*. A `PERIOD` or a `TERMS` member — which §4 mints none of — is met
> by this route alone. **Where a value is supplied into a declared money argument as a safeguard,
> its source is the member's own `maximum` and there is no other source**; which declarations
> admit such a fill is booked (§10), and until that decision lands the two declarations are
> disjoint by the refusal above.

> **Normative — ADR-0254 §3's condition 6 is restated, and it keeps both its directions.** An
> `Authorization` satisfies condition 6 for an `ActionRequest` where **all three** hold: **every
> member of the row is met**, by the routes above; **every user-facing argument of the request
> that the declaration declares in a `BoundedArgument` is covered** by the member of that
> argument's kind, a request carrying no member of that kind being **uncovered**; and — where the
> request carries **any** user-facing argument the declaration declares at no kind — **at least
> one member of the row is met through the evidence route**, whose digest pins every argument the
> request carries. **A key a `BoundedArgument` names as its `currency_argument` is not such an
> argument**: it is consumed by that declaration's own `MONEY` member, whose §4 comparison reads
> the request's value there, so a declaration carrying an amount and its currency is covered
> without a quote being needed for the currency key alone. A member met by no route leaves the
> request uncovered, which is §3's second direction — *"an act that fixed `refundable_only` to
> `true` authorised a call **carrying** that value"* — and an argument the row cannot meet leaves
> it uncovered, which is §3's first. **There is no default, no wildcard and no omission that reads
> as consent.**
>
> **The third conjunct is what keeps an undeclared argument from going unexamined**, and it is
> §3's first direction preserved rather than relaxed. Without it a row fixing `subject` to
> *"urgent"* would cover a later `send_message` carrying an entirely different `body`. With it,
> an undeclared argument is pinned by the quote's digest or the request is not covered — so the
> owner's booking case, whose `site`, `dates` and `party` are declared nowhere, is covered through
> its quote, and a tool with no quote and undeclared arguments asks. **What the digest pins is
> that the call is the call that was quoted, and not that the user chose each of its arguments**
> — the cost §10 books.
>
> **And ADR-0254 §1's completeness condition is restated over condition 6 alone**, as *the row the
> proposal would write satisfies condition 6 for this request* — condition 6 and not `covers`,
> because a proposal is written `PROPOSED` and condition 1 asks for a live row. §9 shows the
> working. **Where it fails, no row is proposed**, `Confirmation.authorization` is absent and the
> one call is authorised by route (a) — §1's own disposition, unweakened.

> **Normative — an argument the declaration declares at no kind is compared against no member,
> and where a member is met through the evidence route it is the digest that pins it.** There is
> no default kind, no inference from a value's JSON type, no schema keyword and no fallback to an
> exact comparison: ADR-0254 §4's *"No reading consults a schema to decide what an argument
> means, and there is no exception"* binds this rule as it binds every other. **The comparison is
> taken where ADR-0254 §13 puts it** — at `ActionPolicy.decide`, on the concrete request, at every
> dispatch, with no cached verdict anywhere — and *"nothing is compared at dispatch"* in the
> owner's ruling names the **price**, which is proved against the quote and against no argument of
> the call. **One implementation, in `permissions`**, and §5's mint runs none of it.

**The worked case, because the rule is easier to check against one.** *"Book Riverside if it is
dry Saturday, up to 150 euros."* The constraint's second clause is *"up to 150 euros"* and mints
one member — `MONEY`, `maximum` `150`, `EUR`, inclusive — and nothing else. The investigation
quotes the site for Saturday, so a quote for the goal's intended action is available at
`120`/`EUR` over the arguments *(site, dates, party)*; the booking request carries the same action
and the same three arguments, the digest matches, `120 ≤ 150`, route (d) `ALLOW`s and **no
question is put**. Verification confirms the charge afterwards and a mismatch is a reported
finding, which is A10's (§10). *"Make it Sunday"* replans and the re-quote is `135` over the
Sunday arguments: the Saturday quote covers nothing now, the Sunday one does, and **still no
question is put**. A site whose Sunday price is `170` is covered by nothing, and the user is asked
about that concrete call.

### 8. Writer clauses, and what no model does

> **Normative.** **`orchestration` mints every coverage member, and nothing else does.** No
> `ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter, no tool and no
> model **constructs, writes or repairs** one. This is ADR-0254 §15's writer clause reaching the
> values §§1-5 add, and it is unqualified because every input the mint reads is on the goal
> already (§5).

> **Normative — no durable value of this decision is ever taken from a model, and the list is
> exact.** A planner envelope carrying a **`CoverageMember`**, a **`ValueBound`**, an
> **`AuthorizationBasis`**, a `BoundKind`, an argument key or a **`BoundedArgument`** has those
> values **discarded silently** — not an error, not a park, not a degradation of the turn — which
> is ADR-0254 §9's posture extended to exactly the values this decision adds, and for its stated
> reason: a value a model wrote into a durable audit chain is unprovenanced.

> **Normative — a model contributes exactly one thing to this decision, and it is the span.** An
> interpretation element's span is checked against that turn's own utterance by ADR-0249 §7, and
> §4 bounds what a differently chosen one can do in three ways: **the span must equal a whole
> clause of that utterance**, so its polarity is the clause's rather than a substring's; **no
> reading is taken where a negation stands in an earlier clause**; and **the table mints a ceiling
> or nothing**. §10 books what remains. **Nothing else a model produces reaches any input of
> §§1-5 or §7** as a selector or a written value: the argument a member meets is the
> **declaration's** (§7) and the identifiers are the loop's. **A model names no argument key, no
> currency key and no identifier anywhere in this decision.**

### 9. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text** and is shown rather than asserted:
*"Would a reader holding only the earlier ADR now act differently, or read one of its clauses more
widely than it now holds?"* **Two documents come out yes** — ADR-0254 in seven scopes and
ADR-0016 in one; every other ADR cited comes out **no** and takes none, which ADR-0082 §1 requires
as firmly.

**ADR-0254 §1 — in the proposal's completeness condition alone.** It reads that the coverage a
proposed row would carry is *"**complete for this request**: every **user-facing** argument of the
request (§3) is named by a member … **or** the request carries no user-facing argument at all"*.
A member names no argument once §3 below lands, so it would be satisfiable only by its second limb
and **no row carrying a non-empty coverage could ever be proposed** — the inert outcome this
decision exists to remove, and the one the tree is in today (§Context). §7 restates it as *the row
the proposal would write satisfies condition 6 for this request*: **condition 6 and not the whole
of `covers`**, because a proposal is written `PROPOSED` and §3's condition 1 asks for a **live**
row, so a test over the whole could never pass at a proposal. Its purpose, disposition and cost
are unchanged. **Every other clause of §1 binds entire** — the three write paths, the row written
before the question is put, the never-edited coverage, the path-(iii) recipient precondition and
the other three proposal conditions.

**ADR-0254 §2 — in the member's shape.** §2 declares `CoverageMember`'s fields *"exactly:
`argument`, an `EncodableText`; `fixed`; `bound`; and `basis`"*, states *"`argument` is a key name
and never a path"*, rules that *"No two members of one `Authorization` name the same `argument`"*,
gives a `MONEY` bound a `currency_argument` as *"the whole of the association between an amount
and the currency it is denominated in"*, and makes `maximum` required. §3 above replaces
`argument` with `kind`, restates the no-two-members rule over the kind, moves the currency key to
the declaration and the quote, and gives `maximum` an **exclusivity flag**; `maximum` stays
required and `minimum` stays optional, exactly as ratified, §4 minting no floor at all. A reader
holding only §2 authors a member that claims to know which slot it fills and records *"under
100"* as a bound a call at exactly 100 satisfies. **Every other clause binds entire**: the
two-shapes validator, `BoundKind`'s members and their vocabulary rule, the three kinds' own fields
and refusals, the every-other-argument-is-fixed-only default, and the asymmetry argument that *"A
comparison the system gets wrong in the permissive direction authorises a call the user did not
authorise"* — which §§3, 4 and 7 are written to serve rather than to weaken.

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
`ToolDefinition` gains **one** further field, `bounded_arguments` (§7), so *"`ToolDefinition`
gains **one** field"* is over-narrow by one, and a reader implementing from §3's inventory alone
authors a declaration no member can ever be held against. **Every other clause binds entire**:
conditions 1-5 — condition 3's by-value declaration comparison conspicuously so — the user-facing
classification and its empty default, the fill-before-the-fit-test and `parameters_digest`
clauses, the bar-stays-monotone clause, the seam/policy split, the coverage-never-widens rule, the
ADR-0021 §5 monotonicity clauses, the resolved-reference clause with its *"a value a tool produced can
satisfy a bound and can never supply one"* arm, and the canonical encoding §7 compares by.

**ADR-0254 §4 — in two limbs of the `MONEY` reading.** Its **currency conjunct** reads *"the
request carries, at the bound's `currency_argument`, a JSON string equal to the bound's
`currency`"*, and the bound no longer carries that key; §7 takes it at the `BoundedArgument`'s
`currency_argument` or at the quote's own currency, its force unchanged. And its **two `maximum`
inequality** is read strictly where `maximum_exclusive` is set — **its `minimum` conjunct is
unmoved and binds entire** — a reader holding only §4 otherwise covering a call at exactly the
endpoint the user excluded. **Every other clause binds entire**: the `MONEY` reading in every
other conjunct, `PERIOD` and `TERMS` whole, the no-float and no-naive-instant rules, the
totality-and-refusal clause, the `reason` discipline, and the no-schema clause, which §7 cites as
binding it.

**ADR-0254 §9 clause (ii) — in the test of *"bear on"* alone.** The clause states the property
and no procedure, so a reader holding only §9 either invents a test or, as #2373 did, stops. **Its test is kind agreement between the constraint and the
thing the member is proved against** — a quote, which is a price and so meets a `MONEY` member
and no other, or a `BoundedArgument` at the member's own kind — and never numeric fit, a model's
nomination or a schema. **The clause's prohibitions bind entire and are not
narrowed**, and so do clauses (i) and (iii) and §9's discard rule.

**ADR-0254 §8 and §10 — in the resolution enumeration's closure alone.** Both state
`ResolutionRule` *"closed at exactly three members"*; §4 adds `STATED_BOUND`. **This is the
supersession §19 books by name** — *"A fourth `ResolutionRule`. Fired the same way, and never by a
resolution whose inputs are not on the turn it names"* — and the new rule honours that condition:
its inputs are the span and the utterance the basis already names. **Every other clause binds
entire**: §8's basis fields, its span check and its two-zones clause; §10's three ratified
resolutions, its no-memory-no-preference rule, its normalisation-at-the-mint rule and its *"A
resolution the loop cannot take is not taken, and no member is minted"*.

**ADR-0016 §1 — in one scope**, and it is the scope ADR-0254 §18 already took there reaching one
further field: the model declaration, and the required-field clause applied to `bounded_arguments`
alone. The grounds are that clause's own reason, which does not reach this default — the empty
tuple makes the **opposite** claim to the one §1 refuses. **The exception is this one further
field on this one argument**, no lane reading the two records together as licence to default a
third, and every other clause of §1 binds entire.

**And the ones that come out no, several of them deliberately.** **ADR-0249** takes **no** record:
this decision adds no field to `Goal` and none to `GoalElement`, and §7 is relied on rather than
narrowed — its span check is a containment test, and §4's clause and negation refusals are
further refusals of **this** decision's own reading rather than changes to it. **ADR-0255** takes
**no** record: §15 item 19's gate enumeration is untouched, because every prerequisite the quote
raises belongs to the decision that lands the quote (§10) and this one adds none. **ADR-0252** is
read and **not moved**: §1's no-content rule, its two bases and verdict vocabularies, §6's four
tests, §7's conflict rule, §11's digest and §§12-13 are untouched, and §6 records why the carrier
question is the booked decision's. **ADR-0253** is superseded in nothing: this decision adds no
field to `PlanStep`. **ADR-0265** is relied on entire — `IntendedAction` and its `id` are read as
that decision leaves them, its *"no fourth field"* closure included. **ADR-0254 §13** is the
clause §7 is taken under, its *"Coverage and sufficiency are two tests and neither clears the
other"* staying true. **ADR-0021 §1** is relied on for the one canonical encoding; **ADR-0145 §2
and §9** for the hazards §7 avoids; **ADR-0029 §5** is relied on rather than superseded.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **Where a quote is carried, what records one, and how a policy obtains one — the whole of the
  quote's machinery.** §6 states the four facts §7 reads and states no carrier: no type, no field
  of any model, no store member, no Protocol, no bound on how many a goal holds, no expiry, and no
  rule about which component mints one or from what. **Nor whether a quote is still true when the
  act is performed** — a quote true when read and false when the call was made authorises an
  over-bound charge — **nor what freshness the wiring of a consequential capability through this
  route therefore requires**, which is that decision's prerequisite to state and not this one's.
  **This is the largest thing this decision does not settle**, and until it lands §7's evidence
  route has no operand, so no `Authorization` this decision's members ride in covers a call. Fired
  by **the quote decision**, tracked as issue **#2387**, which carries §6's constraint that a
  quote is *"a second copy of what was read"* — what ADR-0252 §1 refuses of a `GoalEvidence` row.
- **Who supplies the value of a system-supplied argument.** ADR-0254 §3 requires `orchestration`
  to supply one and names an idempotency key, a client reference and a locale. **This decision
  states one source and lands no filler**: a value supplied into an argument as a spending
  safeguard is the member's own `maximum` (§7), and today `bounded_arguments` and
  `system_supplied` are disjoint, so no such fill is constructible. `PlanStep.id` is **refused
  here** as the client reference — `_step_ids_are_unique` guarantees uniqueness *"within a plan"*
  alone and `Identifier` guarantees no opacity. Fired by the decision that mints a dedicated
  opaque per-call reference.
- **Which system-supplied keys are per-call identity and which are inputs a price depends on.**
  ADR-0254 §3's three examples are not one kind: an idempotency key and a client reference are
  per-call identity, and a **locale** is an input a price can depend on. **This decision draws no
  line between them, and §6 therefore excludes nothing from the digest** — the fail-closed
  spelling, whose cost is that a declaration filling **any** system-supplied argument is covered by
  no quote and asks on every call. The permissive spelling is the defect: excluding every such key
  by kind would let a quote taken under one locale authorise a charge priced under another, with
  the digest matching throughout. Fired by the decision that classifies a system-supplied key,
  which is what makes the evidence route live for such declarations.
- **What pins an *undeclared* user-facing argument to the user's own act, beyond the quote's
  digest.** §7's third conjunct proves that the call is the call that was **quoted**; it does not
  prove that the user chose each of the quoted arguments, and `IntendedAction` cannot close the
  gap because ADR-0265 §1 gives it *"no fourth field"* and so no parameters. So a replan that
  changes an undeclared argument the user never spoke to — a party size beside the Sunday date —
  is covered where its re-quote is inside the ceiling, and no question is put. **That is the
  owner's ruling of 2026-09-14 applied rather than a slip in it**: *"Location/time arguments need
  no declaration"*, and *"make it Sunday" → re-quote 135 → inside bound → no new prompt*. This
  decision lands that ruling and states its reach here rather than widening it silently; the
  ceiling still binds what any such call may cost, and an act whose re-quote is outside it asks.
  Fired by the decision that gives an intended action a parameter identity, or that states what
  else an undeclared argument is proved against.
- **A stated floor.** §4 reads only ceilings, so *"at least 150 euros"* mints nothing and the act
  asks. Fired by a decision that can tell a bound on what the user **pays** from one on what they
  **receive** — which needs a fact neither the span nor the kind carries — and which then states
  what a floor is proved against.
- **Minting a `TERMS` member from an act, and minting a `PERIOD` one.** §4 mints neither, so a
  term the user named and a period they gave are covered by nothing and every call resting on one
  asks. What stops both is the same thing: a span a model chose carries no polarity a rule can
  read, and *"avoid sending to Alice"* would otherwise mint an authority to send to Alice.
  **ADR-0249 §7 owns that question** — its span check is a containment test, never a check of what
  the model meant. Fired by the decision that gives an element a polarity the loop can read, or
  that constrains how a span is chosen; and for `PERIOD`, additionally by the reader that turns
  *"Sunday"* into a half-open interval, which **owes ADR-0254 §8's two-zones rule**: such a
  member's `timezone` is the configured zone as the act's turn read it, read from that input and
  never from the resolution's own record of it.
- **A `FROM_SHOWN_RECORD` basis for a coverage member**, which needs an element carrying both a
  span and the record its reference resolved to, and ADR-0249 §1 admits none. Fired by the
  decision that gives an element that shape.
- **Any widening of §4's reading** — a form the table does not list (bare *"less than"* among
  them), a currency it does not name, another language, a figure written in words, a bound on a
  count, **or a bound stated inside a longer clause**; and **a fourth `BoundKind`**; and **which
  of two constraints of one kind the user meant**, which §5 refuses rather than choosing. It
  refuses rather than guessing in every case. Each fired by the decision stating the wider reading
  and its own totality argument.
- **What the verification phase does with a quote, and coverage's other conditions.** The owner's
  ruling makes the actual charge confirmed after the act and a mismatch *"a reported finding"*;
  **no clause here verifies anything, compares a charge, or writes a finding**, and
  `AttemptPhase.VERIFY` is A10's by ADR-0255 §17's assignment. ADR-0254 §3's conditions 1-5, §§5-7,
  §12's ladder as ADR-0256 §1 leaves it, and §11's projection are likewise untouched, and this
  decision adds no field any of them renders. Fired by A10, and by the decisions those clauses
  already name.

### 11. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **three lanes and no fourth**, **each one
> subsystem plus its tests**: **L1**, the contract in `core/types.py` with the wire bump; **L2**,
> the mint in `orchestration`; **L3**, the comparison in `permissions`. **No lane wires a
> consequential capability** or enables anything in a production deployment — ADR-0254 §17's rule
> as ADR-0255 §13 leaves it binds all three — and **no lane writes an `Authorization`**: ADR-0254
> §20's Lane 2 does that, is briefed after L1 and L2 merge, and is what #2373 unblocks. **The
> bullets below assign each lane its surface and its arms, and no lane is complete without what
> it is assigned there.**

> **Normative — the wire moves, the export does not, and the stored shapes are read rather than
> assumed.** **`PROTOCOL_VERSION` moves by exactly one, in L1**, and `wire/envelope.py`'s log
> gains an entry naming this ADR and the reason: `ToolDefinition` gains `bounded_arguments` and a
> declaration crosses the promoted surface **inside a `PermissionDecision`**, that model sets
> `extra="forbid"` and `wire/codec.py` renders a model by `model_dump()`, so a defaulted member is
> still a shape change. **`ActionRequest` crosses no frame**, which is the ground ADR-0254's own
> Lane 2 entry states, so `intended_action` adds no second reason; and **`PlanExport` gains no
> member and `schema_version` does not move**, no record this decision adds riding inside a goal
> or a plan.
>
> **No stored row is migrated, edited or dropped, and the reason is a fact about the tree rather
> than a claim about the shape.** `CoverageMember` is a **stored** value — it rides inside an
> `Authorization` — so the loss of `argument` would be a breaking decode for any row that held a
> member. **No row holds one.** Every `Authorization` a deployment can hold is written by
> `orchestration/authorizing.py`, which sets `coverage=()` on every row it builds and proposes
> none at all for a request carrying a user-facing argument; no `CoverageMember` is constructed
> anywhere in `src/` outside the canonical fake. An empty tuple decodes identically under the new
> shape, so **L1's change reaches no stored member and no lane writes a migration, an inert
> representation or a repair**, and a `ToolDefinition` written before this decision decodes with
> `bounded_arguments` empty, conforming rather than degraded. **L1 re-takes that reading at its
> own base and states what it found**; were a row to hold a member by then, the lane stops and the
> erasure is ADR-0254 §20's Lane 2's to state, not a repair invented inside L1.

- **L1 — the contract, in `core/types.py` alone.** `CoverageMember`'s `kind` and the removal of
  `argument`; `ValueBound`'s `maximum_exclusive` and the removal of `currency_argument`;
  `ResolutionRule.STATED_BOUND`; `BoundedArgument` and `ToolDefinition.bounded_arguments`;
  `ActionRequest.intended_action`; and `PROTOCOL_VERSION` with `wire/envelope.py`'s log entry.
  **`core/protocols.py` is not touched and no Protocol changes**, so no triad is owed and none is
  invented. Arms 4(a) and 6(b).
- **L2 — the mint, in `orchestration` alone.** §1's candidate selection, §2's act and its four
  refusals, §4's reading and its refusals, and §5's one-per-kind refusal and goal-only read. Arms
  1(a), 2(a), 3(a), 4(b) and 7.
- **L3 — the comparison, in `permissions` alone.** §7's two routes, its digest, and its
  restatement of condition 6 in `permissions/_coverage.py`, with each currency conjunct read where
  §7 puts it. Arms 1(b), 2(b), 3(b), 5 and 6(a).

> **Normative — L1 lands before L2 and before L3, and L3 is briefed only after the quote decision
> (§10) has landed a carrier.** §7's primary route reads a quote, and a lane cannot demonstrate a
> comparison whose principal operand no type carries; L3's arms are written against that
> decision's carrier, never against a fake standing in for it. **L1 and L2 are briefed on this
> decision alone** — they mint members from the goal and read no quote — so a row carrying a
> non-empty `coverage` becomes writable as soon as they land, which is what #2373 asked for.

> **Normative.** **The three lanes ship the seven arms below, each over controlled fakes, and no
> lane is complete without the arms it is assigned.** Every arm states a correction as a
> **subsequent turn**, on the owner's sequencing ruling of 2026-09-13, and none is demonstrated
> against a live integration.

1. **A stated ceiling, end to end.** **1(a):** a goal whose current interpretation carries a
   `USER_STATED` constraint with span `"up to 150 euros"` mints exactly one member — `kind`
   `MONEY`, `maximum` `Decimal("150")`, no `minimum`, `currency` `"EUR"`, `resolution`
   `STATED_BOUND`, basis naming the revision's `raised_by` and that span — and **no second member
   of any kind**. **1(b):** against a quote for the request's `intended_action` at `"120"`/`"EUR"`
   over the request's own arguments, the request is covered; at `"170"` it is not; and with **no**
   quote for that action it is not covered however small the declared arguments are.
2. **Kind agreement and not numeric fit — the review's own case.** **2(a):** a constraint with
   span `"4 stars"` mints **no member at all**: it matches no form of §4's table, and no other
   reading mints one. **2(b):** a `TERMS` member constructed directly — the shape a later decision
   will mint — is met by a `MONEY` quote in no case and by a `MONEY`-declared argument in none,
   whatever number either carries, and a `MONEY` member is met at a `TERMS`-declared argument in
   none.
3. **Only ceilings, the endpoints, and the refusals — and the span is a whole clause or it mints
   nothing.** **3(a):** as a whole utterance, `"under 100 euros"` mints `maximum` `100` **with**
   `maximum_exclusive`, `"at most 100 euros"` mints it without, and `"never spend over 100 euros"`
   and `"don't spend over 100 euros"` each mint an **inclusive** `maximum` of `100`; and the span
   `"up to 150 euros"` taken from `"Book Riverside if it is dry Saturday, up to 150 euros"` mints
   an inclusive `maximum` of `150`, that span being a whole clause. **Nothing at all** is minted
   by `"at least 150 euros"`, `"more than 150 euros"` or `"over 150 euros"`, none of which is a
   form of the table; by `"never notify me about charges over 100 euros"`, `"not exactly 100
   euros"` or `"never spending over 100 euros"`; **by the span `"under 100 euros"` taken from the
   utterance `"avoid booking hotels under 100 euros"`** — the case that refutes any
   a-ceiling-can-only-restrict argument, the user having stated a **floor** — or by the span
   `"over 100 euros"` taken from `"avoid spending over 100 euros"`, the span `"under 100 euros"`
   taken from `"not under 100 euros"`, the span `"over 100 euros"` taken from `"under no
   circumstances spend over 100 euros"`, the span `"Alice"` taken from `"do not send to Alice"`
   and the span `"Sunday"` taken from `"do not book Sunday"`, **each refused because the span is a
   proper part of its clause rather than equal to one**, over **every** reading and not the
   table's alone; by the span `"spend under 100 euros"` taken from `"I'm not fussy, spend under
   100 euros"`, which **is** a whole clause and is refused by the negation in the clause before
   it; and by the span `"under 100 euros"` taken from `"under 100 euros, under 100 euros"`,
   refused because that clause occurs **twice** and no occurrence is named. **3(b):** against an
   exclusive `maximum` of `100` a value of exactly `"100"` does **not** satisfy and against an
   inclusive one it does.
4. **One member per kind.** **4(a):** an `Authorization` carrying two `MONEY` members is not
   constructible, and one carrying a `MONEY` and a `TERMS` member is. **4(b):** a goal carrying
   two `USER_STATED` constraints that each read as `MONEY` mints **neither**, and one carrying a
   money ceiling beside a constraint no reading mints still mints the ceiling.
5. **The arguments are the ones quoted, and the worked case.** A request whose arguments equal
   the quoted ones is covered; one carrying **one extra** argument, one **missing** one, and one
   whose value differs are each **not** covered though the price is unchanged; a request whose
   `intended_action` names a different action, and one carrying **no** `intended_action`, are
   covered by no quote; a **system-supplied** argument whose value differs between the quoted
   arguments and the request leaves the request **not covered**, nothing being excluded from the
   digest today; and the Sunday re-quote covers the Sunday arguments while the Saturday quote
   covers neither. Where two quotes match on action and digest, **the later in §6's order
   governs**; a `PERIOD` and a `TERMS` member are met by **no** quote whatever it carries; and a
   failing read leaves the request **not covered with the fault reported**, never treated as an
   absence of quotes.
6. **A filter is not a charge, and an undeclared argument needs no declaration.** **6(a):**
   against a declaration declaring `price` `MONEY` with `currency_argument` `"currency"`, a
   request satisfying that argument but covered by **no quote** is **not** covered; with a quote
   it is; and a request whose declared argument exceeds the bound is not covered though the quote
   is inside it. A declaration declaring **two** `MONEY` arguments meets no `MONEY` member on that
   route, and one declaring **none** is covered through the evidence route with its site and date
   arguments declared nowhere. A row whose every member is met on the **argument** route does
   **not** cover a request carrying a user-facing argument the declaration declares at no kind —
   the `send_message` case, where a fixed `subject` must not cover a changed `body`. **6(b):** a
   declaration is **not constructible** where a `BoundedArgument` names a key of its own
   `system_supplied`, where two name one `argument`, where a `MONEY` one carries no
   `currency_argument`, where a `PERIOD` or `TERMS` one carries one, and where `argument` equals
   `currency_argument`; and a `ValueBound` is not constructible where `maximum_exclusive` is set
   beside an absent `maximum`.
7. **The mint reads the goal alone, the three refusals, and the discard.** The same goal mints
   the same members against two different requests, two different plans and two different
   declarations — including one declaring nothing; an element whose `id` is `None`, one whose
   carrying revision's `raised_by` is `None`, and one on a goal whose `interpretation_elided` is
   non-zero and whose oldest **retained** revision is its earliest carrier each mint nothing; and
   a `PlannerOutput` whose envelope carries **every value §8's discard list names** — a
   `CoverageMember`, a `ValueBound`, an `AuthorizationBasis`, a `BoundKind`, an argument key and a
   `BoundedArgument` — leaves the recorded revision and the minted coverage **byte-identical** to
   the same envelope without them, with the turn completing and not failing.

### 12. This ADR classified, marked, and how it is ratified

**A reader acts differently, so this is a decision and not a clarification.** A reader holding
the corpus without it can write no row carrying a non-empty `coverage` at all, and would either
leave ADR-0254 §20's Lane 2 stopped where #2373 stopped it or invent an association no clause
authorises — the standing authority §9 clause (ii) exists to prevent (ADR-0070 §1).

**It is a partial supersession of exactly two documents** (ADR-0070 §3) — ADR-0254 in **seven**
scopes and ADR-0016 in **one** — and the `Status` line of each names its scopes **without an
`ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction invariant holds. Against
every other ADR it cites it is a **stacked addition**. **The records land in the same change as
this document** (ADR-0082 §7), and nothing else in either is edited — no Decision text is
rewritten, which ADR-0070 §1 forbids.

**This ADR is marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
blockquote at column 0 stating its own scope, unmarked text beside a mark supplies no obligation
of its own but is read to settle what a mark means (§3), and quoted marks from other ADRs appear
inside quotation marks in running prose. §11's lane bullets and §11's arms are that unmarked
content, read under marks that state the count, the one-subsystem rule and the
no-lane-is-complete-without-what-it-is-assigned rule — ADR-0265 §§9-10's own shape. **It is a
contract-surface change** — `CoverageMember` and `ValueBound` change shape, `ResolutionRule` gains
a member, `BoundedArgument` is added, and `ToolDefinition` and `ActionRequest` each gain a field —
so it owes **both** review lenses on one tree, which ADR-0015 §1 makes true of a prose-only PR.
`core/protocols.py` is **not** reached, so no Protocol triad is owed. **It merges as its own PR,
ratified, before anything implements against it** (golden rule 5); §11's lanes are briefed after
it merges, and the ratification flip is one line and no other byte (ADR-0165).

## Consequences

**What becomes possible.** ADR-0254 §20's Lane 2 can be briefed as soon as L1 and L2 land: a row
can carry a non-empty `coverage`, so the mint that #2373 stopped on exists and the record says
what the user stated. Once the quote decision (§10) lands its carrier and L3 follows, a ceiling
the user stated once covers every later call whose quote sits under it, **at a tool that declares
nothing about money at all**, and *"make it Sunday"* is answered by a re-quote rather than by a
second question — the owner's *"a price change within an approved limit should remain covered"*.
A declared money argument is an **additional** comparison and never a substitute; the cost is that
**an act with no quote is not covered and the user is asked**, which the owner names as
feasibility rather than restriction and which is the fail-closed direction.

**What this decision is worth without the other one, stated rather than assumed.** The member,
the mint and the proof rule are decided here and are independently implementable: L1 and L2 need
no quote, and route (d) gains a record that says what the user's own words fixed. What it does not
yet gain is the ability to **prove** a money ceiling — §7's primary route has no operand until the
quote decision lands, so until then a row carrying a `MONEY` member covers nothing and every such
act asks. **That is the fail-closed direction and the honest cost of the split.**

**What becomes harder, and every part of it is a question asked rather than a call authorised.**
A request carrying any argument the declaration declares at no kind is covered only through the
**evidence** route, so a tool with undeclared arguments and no quote asks on every call — the
price of keeping *"no omission reads as consent"* once arguments stop being named by members. The
digest is exact and excludes nothing, so a quoting read and a booking that differ by any key,
**a system-supplied one included**, never match: a declaration that fills an idempotency key is
covered by no quote at all until §10's classification lands. And §4 reads a **whole clause** and
seven forms in one language, so a bound stated inside a longer clause, in another language or in
words mints nothing.

**One residual is stated rather than closed, and §10 books it.** §7's third conjunct proves that
the call is the one that was **quoted**, not that the user chose each quoted argument: a replan
that changes an undeclared argument beside the one the user spoke to is covered where its re-quote
is inside the ceiling. That is the owner's ruling applied — *"make it Sunday" → re-quote 135 →
inside bound → no new prompt* — and the ceiling still binds what any such call may cost.
**ADR-0249 §7 owns the span, and §4's clause rule is what this decision could do about it**: the
polarity a rule reads is the polarity of a whole clause the user wrote, so *"avoid booking hotels
under 100 euros"* mints nothing where an earlier draft minted a ceiling of `100` — standing
permission to spend in exactly the region that user excluded.

**These are the cases that would falsify the design.** A deployment where users state bounds
inside longer clauses, so route (d) is never reached — the practical falsifier, and the one to
measure first. A quoting read and a booking whose argument sets differ by a key, so the digest
never matches and every act asks. A declaration whose sole `MONEY` argument is an amount the user
**receives**, where a ceiling stated about spending meets it on the argument route — why §4 mints
no floor at all, and why the remaining case is the declaration author's. And a quote decision that
settles on a carrier these four facts cannot be read off, making §7 unimplementable as written.

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

**Deciding the quote's carrier and its producer here, in the same document.** The draft this one
was cut from, and it is declined on cost rather than on correctness. Carrying a quote record, its
place on the `Goal`, its bound and elision, the declaration field naming which output a price is
read at, a plan-store member to append one, a Protocol for the policy to read one and a gate
prerequisite for a quote's freshness made the document supersede **four** documents and maintain
seven synchronised statements of its own contract; ten review rounds at a churn ratio of 5.1 were
spent on the carrier while the rule itself stayed three paragraphs. The
proof rule and the machinery that feeds it are two decisions, they are reviewable separately, and
§6 makes the seam explicit rather than implicit: four facts, an interface, and no carrier.

**Carrying the quote on a `GoalEvidence` row.** The shape the owner's ruling names. It is **not
decided here**: §6 records the reading that makes it hard and hands it to the booked decision as a
constraint. What this decision fixes is the owner's substance — the quote is recorded **by the
investigation, for the intended action, before the authorisation phase compares it** — which
holds whichever carrier that decision picks.

**Refusing only the negations a closed vocabulary spells, and arguing that a ceiling cannot
hurt.** Rounds 4-10's answer, refuted in round 11 on *"avoid booking hotels under 100 euros"*: a
substring reading as a ceiling can be carved out of a clause stating a **floor**, and the
authority minted is permission to spend exactly where the user refused to. §4 answers it by
narrowing the input rather than by widening the vocabulary — the span must **be** a clause —
which is a removal, and removals are what have worked in this loop.

**A planner nomination of the (element, argument) pair, verified by code.** Sound, and the
direction four of round 1's nine findings pointed at. Declined because the pairing is per
*(element, declaration)*, so it cannot live on `GoalElement` and would have to live on
`PlanStep`, superseding ADR-0253's step enumeration and its seam and wire. **Asking the user to
confirm the association** is foreclosed by ADR-0254 §1, which writes the path-(i) row **before**
the question is put. **Minting a `MONEY` bound from a bare figure**, with the direction fixed by
the kind, was the first draft's rule and round 1 refuted it twice: the direction is in the user's
words or it is nowhere.
