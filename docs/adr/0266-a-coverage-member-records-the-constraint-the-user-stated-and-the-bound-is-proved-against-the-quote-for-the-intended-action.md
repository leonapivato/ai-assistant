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
  fourth `ResolutionRule`, **`STATED_BOUND`**, which §19 books by name. Every other clause of all
  seven sections binds entire, several load-bearing here: §1's three write paths, its
  write-before-the-question rule and its other three proposal conditions; §2's
  two-shapes-and-no-third rule and its `BoundKind` vocabulary; §3's conditions 1-5, its
  user-facing classification, its no-omission-reads-as-consent rule and its canonical encoding;
  §4's totality and its three readings; §8's basis; §9's clauses (i) and (iii) and its discard
  rule; §10's three ratified resolutions; §13's recheck-at-`decide` and its no-cached-verdict
  rule, which §7 below is taken under; and §15's writer clauses.
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

**`Authorization` rows are written today, and every one of them carries an empty `coverage` — the
fact §6's migration clause rests on, re-read at this base rather than carried forward.**
`orchestration/runner.py` calls `proposed_authorization` and records what it returns, and
`app/composition.py` constructs the `SqliteGoalAuthorizationStore`, so a deployment does hold
rows. But `orchestration/authorizing.py` builds every one of them with `coverage=()` and returns
`None` for any request carrying a user-facing argument — the vacuous-completeness gate #2373
names — and **no `CoverageMember` is constructed anywhere in `src/` outside the canonical fake**
(`testing/goal_authorizations.py`). So no stored row holds a member of any shape, and nothing
records a quote.

### What this ADR is not allowed to settle

It decides what a member **records**, how a span **becomes** one, and **what a member is proved
against** — and nothing beyond that. It leaves ADR-0254 §3's conditions 1-5 and §§5, §6, §7
exactly as they stand, §12's expiry as ADR-0256 §1 leaves it, and §11's projection and every
surface untouched; it opens no route, relaxes no floor, lowers no threshold and moves no ruling.

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

> **Normative — a negation standing before the span refuses every reading, not only this table's,
> and the test is determinable on one occurrence or it refuses.** Take the act's own recorded
> utterance and the element's `span`, both folded and tokenised as above. **Where the span's token
> sequence occurs in that utterance more than once, no member of any kind is minted** — two
> occurrences admit two conforming answers, one negated and one not, and `GoalElement.span` is
> **text and not an offset**, so nothing on the record says which occurrence the model meant.
> **Where it occurs exactly once, no member of any kind is minted if any token preceding that
> occurrence is a token of the negation vocabulary.** Where it occurs not at all the element mints
> nothing in any case, ADR-0254 §8 requiring a span *"inside that turn's stored utterance"*.
>
> A model chooses the span and a truncation can drop the word that reverses it: *"do not spend
> under 100 euros"* would otherwise mint a ceiling from *"under 100 euros"*. **The bar is over
> every reading of this section** — which matters for the readings §10 books as much as for this
> one — it is deliberately blunt, and it refuses *"I'm not fussy — spend under 100 euros"* along
> with them, which costs a question. **It closes only what this vocabulary can see**: a refusal
> spelled *avoid*, *skip* or *rather not* leaves the truncation readable, which is why this
> section mints only a ceiling and why §10 books what a ceiling's own direction cannot protect.

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

**Minting only a ceiling is what makes a model-chosen span safe, and it is the whole answer to a
class five review rounds kept finding.** A planner selects the span, and a proper substring can
carry a different polarity from the sentence it came out of: *"not under 100 euros"* yields
*"under 100 euros"*, *"under no circumstances spend over 100 euros"* yields *"over 100 euros"*,
and *"avoid spending over 100 euros"* the same — the first two caught by the negation bar above,
the third by nothing, because *avoid* is semantic and no rule over a closed vocabulary recognises
it. What **can** be made total is the **direction**. Had this section read every kind, *"avoid
sending to Alice"* would have yielded the span *"Alice"*, an `AS_STATED` `TERMS` member fixing it,
and a declaration whose sole `TERMS` argument is its recipient covered at exactly the recipient
the user forbade; the same span in *"avoid Sunday"* would have yielded a `PERIOD` member
authorising Sunday. **A ceiling has no such reading**: whatever substring is chosen, a `maximum`
bounded by a figure the user themselves uttered can only restrict what a call may cost, and none
of these truncations mints an authority to spend where the user set a floor. **A floor is not a
spending protection** in any case — it constrains what the user *receives*, which §7 shows this
system cannot tell from what it *pays*. So removing the capability costs a question and closes a
class of inversion that adding rules did not, and what it costs is stated rather than hidden: a
term the user named and a period they gave mint nothing, and every act resting on one asks. §10
books the floor, the period and the term, each with what fires it.

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

> **Normative — a quote supplies exactly four facts, and this decision states no carrier for
> them.** A **quote** is a record of a price this system read, and §7 is written over four facts
> alone: the **`IntendedAction`** (ADR-0265 §1) it was taken for, by `id`; the **arguments it was
> quoted over**, as the digest §7 compares; an **amount** and its **currency**, the amount in the
> form ADR-0254 §4's `MONEY` reading accepts and the currency as that reading's ISO-4217 code;
> and the **step output it was read from**, which is provenance and is compared by nothing. The
> quotes of one goal are **totally ordered**, so that a second reading of one price is legible as
> a **refresh** of the first rather than as a second act of the user — ADR-0252 §7's *"a refresh
> supersedes the row it displaces"*, which §7's last-governs rule is taken under. **This decision
> states that interface and nothing else about a quote**: no type, no field of any existing model,
> no store member, no Protocol, no bound on how many a goal holds, no rule about which component
> records one, no expiry and no face by which a policy obtains one. Those are the **quote
> decision**'s, booked in §10 with what fires it, and **no lane of this decision authors any of
> them**.

**Why the carrier is booked rather than decided here.** The owner's ruling of 2026-09-14 names
`GoalEvidence` as the quote's carrier, and ADR-0252 §1 makes that hard: such a row *"carries no
content"*, its `EvidenceBasis` is closed at two members neither of which admits a typed value read
from a step's output, and its `verdict` vocabulary is fixed per basis, while a quote is exactly a
second copy of what was read. **That is a finding about the carrier, not about the proof**, so it
is handed to the booked decision as a constraint rather than answered here — which is the whole
reason the two are separated. The Alternatives record what the separation cost and bought.

### 7. The two routes, and what covers a request

> **Normative.** `core/types.py` gains **`BoundedArgument`**, a frozen model with
> `extra="forbid"` whose fields are exactly three: **`argument`**, an `EncodableText` naming a
> key of `parameters` at depth **one**; **`kind`**, a `BoundKind`; and **`currency_argument`**,
> an `EncodableText | None` naming the key that carries this amount's currency. A **model
> validator** admits exactly two shapes — `MONEY` with a `currency_argument`, or `PERIOD` or
> `TERMS` with none — and refuses `argument` equal to `currency_argument`. **`ToolDefinition`
> gains one field, `bounded_arguments: tuple[BoundedArgument, ...]`**, possibly empty,
> **defaulting to the empty tuple**, duplicate-free on `argument`, and naming **no key of that
> declaration's own `system_supplied`** — refused at construction. **`ActionRequest` gains
> `intended_action`, an `Identifier | None` defaulting to `None`** — the step's own, which is
> `ActionRequest.goal`'s shape one field over and is how a request says which act it is an attempt
> at. Both are **BREAKING** contract changes to `core` types under golden rule 5 and are flagged
> as such.

> **Normative — that refusal is what preserves ADR-0254 §3's system-supplied protection after
> the validator that stated it is gone.** That section makes a row whose coverage names a
> system-supplied argument not constructible, and it read `CoverageMember.argument`, which no
> longer exists. A system-supplied key is now declared at no kind, so **no member can ever meet
> it on the argument route**, and *"a user is never asked to approve an idempotency key"* holds
> by construction one field over.

> **Normative — the evidence route, and a member is met by it where all four hold.** The request
> carries an `intended_action`; a quote available to the policy (§6) names **that** action and
> carries the member's **kind**; the quote's quoted arguments are **this request's** user-facing
> arguments, compared by the digest below; and the quote's amount satisfies the member under
> ADR-0254 §3's fixed comparison or §4's bounded readings, with a `MONEY` bound's **currency
> conjunct taken at the quote's own currency** and at no key of the request. **Where more than one
> quote satisfies the first three, the one latest in §6's order governs** — a re-quote is a
> refresh of one fact and the later reading is the current price, which is not a precedence rule
> between two acts of the user. **Where no quote satisfies them the member is not met**, the
> request is uncovered, and the user is asked or the act is investigated first — the owner's
> *"no quote → cannot prove the price"*, which is feasibility rather than a restriction on the
> tool.
>
> **A fault is never an absence.** Where the read behind §6's quotes fails, the request is treated
> as **not covered** and the fault is reported; **no implementation converts a fault into an
> absence of quotes** and none falls through to the argument route, which is the distinction
> ADR-0254 already draws between `AuthorizationError` and absence and is what lets a ruling say
> *no record* rather than *a record that did not cover*.
>
> **A quote states what the act will cost, and nothing this decision mints states what the user
> will receive.** §4 reads only ceilings, for exactly that reason: kind agreement cannot tell a
> price the user pays from one they are paid, and a charge satisfying a floor would be the
> permissive direction — *"receive at least 150"* admitting a charge of 200.

> **Normative — the digest is one encoding restricted to one key set, and not a second
> canonicalisation.** The arguments a quote was taken over are compared as `sha256` over the
> canonical JSON encoding `ActionRequest.parameters_digest` is taken over, **restricted to the
> keys the declaration classifies user-facing** (ADR-0254 §3), on both sides of the comparison.
> System-supplied keys are excluded because `orchestration` fills them **per call** — an
> idempotency key differs between the quoting read and the booking by construction — so a digest
> over every argument could never match and the route would be inert. Nothing else is excluded:
> **an extra user-facing argument, a missing one and a changed one each change the digest**, which
> is the owner's rule that the quote covers the booking only where *"the step's arguments are the
> ones that were quoted"*.

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
> is covered without a quote being needed for the currency key alone. A member met by no route
> leaves the request uncovered, which is §3's second direction — *"an act that fixed
> `refundable_only` to `true` authorised a call **carrying** that value"* — and an argument the
> row cannot meet leaves it uncovered, which is §3's first. **There is no default, no wildcard and
> no omission that reads as consent.**
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

**The worked case, because the rule is easier to check against one.** *"Book Riverside if it is
dry Saturday, up to 150 euros."* The constraint mints one member — `MONEY`, `maximum` `150`,
`EUR`, inclusive — and nothing else. The investigation quotes the site for Saturday, so a quote
for the goal's intended action is available at `120`/`EUR` over the arguments *(site, dates,
party)*; the booking request carries the same action and the same three arguments, the digest
matches, `120 ≤ 150`, route (d) `ALLOW`s and **no question is put**. Verification confirms the
charge afterwards and a mismatch is a reported finding, which is A10's (§10). *"Make it Sunday"*
replans and the re-quote is `135` over the Sunday arguments: the Saturday quote covers nothing
now, the Sunday one does, and **still no question is put**. A site whose Sunday price is `170` is
covered by nothing, and the user is asked about that concrete call.

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
> §4 bounds what a differently chosen one can do in three ways: **its table mints a ceiling or
> nothing**, so no truncation yields an authority in the direction the user did not give; **no
> reading is taken at all where a negation stands before the span**; and **no reading is taken
> where the span occurs in the utterance more than once**, so the test that decides the second is
> never taken over an occurrence nobody named. None of the three closes the class whole, and §10
> books what remains. **Nothing else a model produces reaches any input of §§1-5 or §7** as a
> selector or a written value: the argument a member meets is the **declaration's** (§7) and the
> identifiers are the loop's. **A model names no argument key, no currency key and no identifier
> anywhere in this decision.**

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

**ADR-0254 §9 clause (ii) — in the test of *"bear on"* alone.** The clause states the property and
no procedure, so a reader holding only §9 has an obligation with no mechanical test and either
invents one or, as #2373 did, stops. **Its test is kind agreement between the constraint and the
thing the member is proved against** — the quote's kind, or the `BoundedArgument`'s — and never
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

**ADR-0016 §1 — in one scope**, and it is the scope ADR-0254 §18 already took there reaching one
further field: the model declaration, and the required-field clause applied to
`bounded_arguments` alone. The grounds are the clause's own reason, which does not reach this
default — the empty tuple makes the **opposite** claim to the one §1 refuses. **The exception is
this one further field on this one argument**, and no lane reads the records together as licence
to default a further safety field. Every other clause of §1 binds entire.

**And the ones that come out no, several of them deliberately.** **ADR-0249** takes **no** record:
this decision adds no field to `Goal` and none to `GoalElement`, and §7 is relied on rather than
narrowed — its span check is a containment test, and §4's occurrence and negation refusals are
further refusals of **this** decision's own reading rather than changes to it. **ADR-0255** takes
**no** record: §15 item 19's gate enumeration is untouched, because every prerequisite the quote
raises belongs to the decision that lands the quote (§10) and this one adds none. **ADR-0252** is
read and **not moved**: §1's no-content rule, its two bases and per-basis verdict vocabularies,
§6's four tests, §7's conflict rule, §11's digest and §§12-13's store, retention and export are
untouched, and §6 records why the carrier question is the booked decision's rather than answered
here. **ADR-0253** is superseded in nothing: this decision adds no field to `PlanStep`, so §7's
enumeration, §9's label-space count and the resolve-once discipline are untouched. **ADR-0265** is
relied on entire — `IntendedAction` and its `id` are read as that decision leaves them and nothing
of it is narrowed. **ADR-0254 §13** is the clause §7 is taken under — the recheck at `decide`, the
no-cached-verdict rule and *"Coverage and sufficiency are two tests and neither clears the
other"*, which stays true. **ADR-0021 §1** is relied on for the one canonical encoding; **ADR-0145
§2 and §9** for the hazards §7 avoids; **ADR-0029 §5** is relied on rather than superseded.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **Where a quote is carried, what records one, and how a policy obtains one — the whole of the
  quote's machinery.** §6 states the four facts §7 reads and states no carrier: no type, no field
  of `Goal` or of any other model, no store member, no Protocol, no bound on how many a goal
  holds, no expiry, and no rule about which component mints one or from what. **Nor whether a
  quote is still true when the act is performed** — a provider may move a price with no newer
  reading taken, and a quote that was true when it was read and false when the call was made
  authorises an over-bound charge — **nor what freshness the wiring of a consequential capability
  through this route therefore requires**, which is that decision's prerequisite to state and not
  this one's. §6 records one constraint that decision inherits: a quote is *"a second copy of what
  was read"*, which ADR-0252 §1 refuses of a `GoalEvidence` row. **This is the largest thing this
  decision does not settle**, and until it lands §7's evidence route has no operand, so no
  `Authorization` this decision's members ride in covers a call. Fired by **the quote decision**,
  tracked as issue **#2387**.
- **Who supplies the value of a system-supplied argument.** ADR-0254 §3 requires `orchestration`
  to supply one and names an idempotency key, a client reference and a locale. **This decision
  states one source and lands no filler**: a value supplied into an argument as a spending
  safeguard is the member's own `maximum` (§7), and today `bounded_arguments` and
  `system_supplied` are disjoint, so no such fill is constructible. `PlanStep.id` is **refused
  here** as the client reference — `_step_ids_are_unique` guarantees uniqueness *"within a plan"*
  alone and `Identifier` guarantees no opacity. Fired by the decision that mints a dedicated
  opaque per-call reference.
- **Which system-supplied keys a price depends on.** §7 takes the digest over the **user-facing**
  arguments alone, because a system-supplied key is filled per call and a digest over an
  idempotency key could never match twice. ADR-0254 §3's three examples are not one kind: an
  idempotency key and a client reference are per-call identity, and a **locale** is an input a
  price can depend on, so a digest that ignores it can match across two prices. **This decision
  draws no line between them.** Fired by the decision that classifies a system-supplied key.
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
- **Any widening of §4's table** — a form it does not list (bare *"less than"* among them), a
  currency it does not name, a language other than English, a figure written in words, a bound on
  a count; and **a fourth `BoundKind`**, so that an argument which is neither an amount, a period
  nor a named term can be declared and met on the argument route; and **which of two constraints
  of one kind the user meant**, which §5 refuses rather than choosing. It refuses rather than
  guessing in every case. Each fired by the decision stating the wider reading and its own
  totality argument.
- **What the verification phase does with a quote, and coverage's other conditions.** The owner's
  ruling makes the actual charge confirmed after the act and a mismatch *"a reported finding"*;
  **no clause here verifies anything, compares a charge, or writes a finding**, and
  `AttemptPhase.VERIFY` is A10's by ADR-0255 §17's assignment. ADR-0254 §3's conditions 1-5, §§5-7,
  §12's ladder as ADR-0256 §1 leaves it, and §11's projection are likewise untouched, and this
  decision adds no field any of them renders. Fired by A10, and by the decisions those clauses
  already name.

### 11. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **three lanes**, **each one subsystem plus its
> tests**, and **no lane wires a consequential capability** or enables anything in a production
> deployment — ADR-0254 §17's rule as ADR-0255 §13 leaves it binds all three. **No lane writes an
> `Authorization`**: ADR-0254 §20's Lane 2 does that, is briefed after L1 and L2 merge, and is
> what #2373 unblocks.

> **Normative — the wire moves, the export does not, and the stored shapes are read rather than
> assumed.** **`PROTOCOL_VERSION` moves by exactly one, in L1**, and `wire/envelope.py`'s log
> gains an entry naming this ADR and the reason: `ToolDefinition` gains `bounded_arguments` and a
> declaration crosses the promoted surface **inside a `PermissionDecision`**, that model sets
> `extra="forbid"` and `wire/codec.py` renders a model by `model_dump()`, so a defaulted member is
> still a shape change and a hub at the new version fails a client at the old. **`ActionRequest`
> crosses no frame**, which is the ground ADR-0254's own Lane 2 entry states, so
> `intended_action` adds no second reason. **`PlanExport` gains no member and `schema_version`
> does not move**: no record this decision adds rides inside a goal or a plan.
>
> **No stored row is migrated, edited or dropped, and the reason is a fact about the tree rather
> than a claim about the shape.** `CoverageMember` is a **stored** value — it rides inside an
> `Authorization` — so the loss of `argument` would be a breaking decode for any row that held a
> member. **No row holds one.** Every `Authorization` a deployment can hold is written by
> `orchestration/authorizing.py`, which sets `coverage=()` on every row it builds and proposes
> none at all for a request carrying a user-facing argument; no `CoverageMember` is constructed
> anywhere in `src/` outside the canonical fake. An empty tuple decodes identically under the new
> shape, so **L1's change reaches no stored member, and no lane writes a migration, an inert
> representation or a repair.** A `ToolDefinition` stored or transmitted before this decision
> decodes with `bounded_arguments` empty, which is a conforming declaration rather than a degraded
> one. **L1 re-takes that reading at its own base and states what it found**; were a row to hold a
> member by then, the lane stops and the erasure is ADR-0254 §20's Lane 2's to state, not a repair
> invented inside L1.

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
> decision's carrier and are not written against a fake standing in for it. **L1 and L2 are
> briefed on this decision alone** — they mint members from the goal and read no quote — so a row
> carrying a non-empty `coverage` becomes writable as soon as they land, which is what #2373
> asked for.

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
3. **Only ceilings, the endpoints, and the refusals.** **3(a):** span `"under 100 euros"`
   mints `maximum` `100` **with** `maximum_exclusive`, `"at most 100 euros"` mints it without, and
   `"never spend over 100 euros"` and `"don't spend over 100 euros"` each mint an **inclusive**
   `maximum` of `100`. **Nothing at all** is minted by `"at least 150 euros"`, `"more than 150
   euros"` or `"over 150 euros"`, none of which is a form of the table; by `"never notify me about
   charges over 100 euros"`, `"not exactly 100 euros"` or `"never spending over 100 euros"`; by
   the span `"under 100 euros"` taken from the utterance `"not under 100 euros"`, the span `"over
   100 euros"` taken from `"under no circumstances spend over 100 euros"`, the span `"Alice"`
   taken from `"do not send to Alice"` and the span `"Sunday"` taken from `"do not book Sunday"`,
   each refused by the negation standing before the span over **every** reading and not the
   table's alone; or by the span `"under 100 euros"` taken from the utterance `"spend under 100
   euros, and never spend under 100 euros"`, refused because the span occurs **twice** and no
   occurrence is named. **3(b):** against an exclusive `maximum` of `100` a value of exactly
   `"100"` does **not** satisfy and against an inclusive one it does.
4. **One member per kind.** **4(a):** an `Authorization` carrying two `MONEY` members is not
   constructible, and one carrying a `MONEY` and a `TERMS` member is. **4(b):** a goal carrying
   two `USER_STATED` constraints that each read as `MONEY` mints **neither**, and one carrying a
   money ceiling beside a constraint no reading mints still mints the ceiling.
5. **The arguments are the ones quoted, and the worked case.** A request whose user-facing
   arguments equal the quoted ones is covered; one carrying **one extra** user-facing argument,
   one **missing** one, and one whose value differs are each **not** covered though the price is
   unchanged; a request whose `intended_action` names a different action, and one carrying **no**
   `intended_action`, are covered by no quote; a **system-supplied** argument that differs between
   the quoted arguments and the request changes nothing, the digest being taken over the
   user-facing keys alone; and the Sunday re-quote covers the Sunday arguments while the Saturday
   quote covers neither. Where two quotes match on action, kind and digest, **the later in §6's
   order governs**, and a failing read leaves the request **not covered with the fault reported**,
   never treated as an absence of quotes.
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
blockquote at column 0, unmarked text beside a mark supplies no obligation of its own, and quoted
marks from other ADRs appear inside quotation marks in running prose. **It is a contract-surface
change** — `CoverageMember` and `ValueBound` change shape, `ResolutionRule` gains a member,
`BoundedArgument` is added, and `ToolDefinition` and `ActionRequest` each gain a field — so it
owes **both** review lenses on one tree, which ADR-0015 §1 makes true of a prose-only PR.
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
A declared money argument is an **additional** comparison and never a substitute, because a
`max_price` filter says nothing about the charge; the cost is that **an act with no quote is not
covered and the user is asked**, which the owner names as feasibility rather than restriction and
which is the fail-closed direction.

**What this decision is worth without the other one, stated rather than assumed.** The member,
the mint and the proof rule are decided here and are independently implementable: L1 and L2 need
no quote, and route (d) gains a record that says what the user's own words fixed. What it does not
yet gain is the ability to **prove** a money ceiling, because §7's primary route has no operand
until the quote decision lands — so between these lanes and that one, a row carrying a `MONEY`
member covers nothing and every such act asks. **That is the fail-closed direction and it is the
honest cost of the split**: the alternative was one document carrying both, which is what §10's
first booking records.

**What becomes harder.** A request carrying any argument the declaration declares at no kind is
covered only where a member is met through the **evidence** route, so a tool with undeclared
arguments and no quote asks on every call — the price of keeping *"no omission reads as consent"*
once arguments stop being named by members. And the digest is exact, so a quoting read and a
booking that spell one fact under two keys never match.

**Two residuals are stated rather than closed, and both are booked in §10.** The digest binds the
**user-facing** arguments alone, so a system-supplied input a price depends on — a **locale**,
where an idempotency key is per-call identity — leaves the digest equal though the price moved.
And a model chooses the span: §4 bars only the refusals its negation vocabulary carries, so
*"avoid spending over 100 euros"* still yields a ceiling of `100` rather than nothing. The
ceiling-only table makes that second residual **restrictive in every instance** — the worst a
truncation can do is bind the user to a figure they themselves uttered — which is why no `TERMS`
or `PERIOD` member is minted by any path in this decision, and ADR-0249 §7 owns what is left.

**The reading is the narrow part, and every narrowing is a question asked rather than a call
authorised.** §4's table carries three currencies and one language, so *"under a hundred euros"*,
*"unter 100 Euro"* and *"max €100"* mint nothing; the negation must be adjacent, so *"never notify
me about charges over 100 euros"* mints nothing; a truncation of a negated form and a span the
utterance carries twice each mint nothing; the table is asymmetric on purpose, bare *"less than
100 euros"* minting nothing; and a strict word mints a strict bound, which is why `ValueBound`
gains `maximum_exclusive`.

**These are the cases that would falsify the design.** A deployment where users state bounds the
table does not carry, so route (d) is never reached. A quoting read and a booking whose argument
sets differ by a key, so the digest never matches and every act asks — the practical falsifier,
and the one to measure first. A declaration whose sole `MONEY` argument is an amount the user
**receives**, where a ceiling stated about spending meets it on the argument route — which is why
§4 mints no floor at all, and why the remaining case is the declaration author's. And a corpus in
which the quote decision settles on a carrier this decision's four facts cannot be read off,
which would make §7's evidence route unimplementable as written.

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

**Carrying the quote on a `GoalEvidence` row.** The shape the owner's ruling names. It is not
declined here — it is **not decided here**: §6 records the reading that makes it hard (that row
*"carries no content"*, its `EvidenceBasis` is closed at two members neither of which admits a
typed value read from a step's output, and its `verdict` vocabulary is fixed per basis) and hands
it to the booked decision as a constraint. What this decision fixes is the owner's substance —
the quote is recorded **by the investigation, for the intended action, before the authorisation
phase compares it** — which holds whichever carrier that decision picks.

**A planner nomination of the (element, argument) pair, verified by code.** Sound, and the
direction four of round 1's nine findings pointed at. Declined because the pairing is per
*(element, declaration)*, so it cannot live on `GoalElement` and would have to live on
`PlanStep`, superseding ADR-0253's step enumeration and its seam and wire, and ADR-0249 §7's
envelope. **Asking the user to confirm the association** is foreclosed by ADR-0254 §1, which
writes the path-(i) row **before** the question is put, so no member can rest on the answer.
**Minting a `MONEY` bound from a bare figure**, with the direction fixed by the kind, was the
first draft's rule and round 1 refuted it twice: the direction is in the user's words or it is
nowhere. And **giving `PlanStep.id` as the client reference** is declined in §10 on the tree's own
text: step ids are unique *"within a plan"* and `Identifier` promises no opacity.
