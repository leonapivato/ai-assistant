# 266. A coverage member records the constraint the user stated, and the argument it meets is decided at the comparison

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **five narrowly stated scopes, and §8 shows the working for each. §2's member shape**: a
  `CoverageMember` stops carrying an `argument` and carries a **`kind`** instead, so a member
  records *what the user stated* and never *which slot it fills*; with it go §2's depth-one
  clause, its no-two-members-name-one-argument rule (which becomes **one member per kind**), its
  `currency_argument` field on a `MONEY` bound (which moves to the declaration), and `maximum`'s
  requiredness (a stated **floor** mints a `minimum` and no `maximum`). **§3's comparison**: the
  set equality over argument **keys** and the per-argument rule that reads a member *"naming
  it"* become one rule stated over the **declaration** — an argument is covered where its
  declaration declares it at a `BoundKind`, the row carries exactly one member of that kind, and
  the argument satisfies it; the validator refusing a member that names a system-supplied
  argument goes with the field it read, its rule preserved by a refusal on the new declaration
  field instead; and `ToolDefinition` gains **one** further field, `bounded_arguments`.
  **§4's `MONEY` conjunct**: the currency key is read off the **declaration** rather than off
  the bound. **§8's and §10's resolution enumeration, in the closure at three alone**: a fourth
  `ResolutionRule`, **`STATED_BOUND`**, reads a bound off the span by a closed table — which
  §19 books by name and this decision fires. Every other clause of all five sections binds
  entire, several of them load-bearing here: §1's three write paths and its
  write-before-the-question rule, untouched because a member now needs **no argument at write
  time**; §2's two-shapes-and-no-third rule and its `BoundKind` vocabulary; §3's conditions 1-5,
  its user-facing classification, its no-omission-reads-as-consent rule and its canonical
  encoding; §4's totality and its three readings; §8's basis, its two-zones clause and its
  per-member rule; §9 entire; §10's three ratified resolutions and its
  no-member-where-a-resolution-cannot-be-taken sentence; and §15's writer clauses.
- **Partially supersedes** [ADR-0016](0016-tool-definition-and-registry.md)
  — **one scope, in §1, and it is the scope already recorded there reaching one further field**:
  the `ToolDefinition` model declaration and the required-field clause in the application to
  `bounded_arguments` alone. A reader holding only §1 authors a definition that declares no
  argument's kind, and no coverage member can then meet any argument of it. The empty-tuple
  default is an exception to *"Every field that a permission decision depends on is required"*
  on the same grounds already recorded for `system_supplied` — it makes the **opposite** claim
  to the one §1 refuses, since a declaration that declares nothing is covered nowhere and asks
  on every call. **The exception is this one further field on this one argument**, and no lane
  reads the two records together as licence to default a third safety field.
- Date: 2026-09-13
## Context

### Where this comes from

Issue **#2373**, found in the pre-flight of ADR-0254 §20's **Lane 2** — the lane that makes
`orchestration` propose an `Authorization` on a `CONFIRM`, settle it on the answer, and write
path-(ii) corrections and path-(iii) opening acts. That lane stopped before writing code, and
this is what it stopped on.

ADR-0254 states that `orchestration` mints a `CoverageMember` from a recorded act, and states
exactly what a member must contain, but **no clause states how a recorded span is associated
with an argument key of a declaration, nor how the member's shape is chosen** — a `fixed` value,
or a `ValueBound` of kind `MONEY`, `PERIOD` or `TERMS` with its `maximum`, `minimum`,
`currency`, `currency_argument`, `starts_at`, `ends_at`, `timezone` or `terms`.

The owner's Q1 ruling of 2026-09-12, which ADR-0254 records whole, is what the answer has to
serve: *"Bind authorization to explicitly fixed values and explicitly permitted ranges. A price
change within an approved limit should remain covered. A clear later instruction such as 'make
it Sunday' can supply authorization for that change; do not automatically ask the user to repeat
it. Ask only when the concrete action introduces something not already covered, such as
additional costs or materially different terms."*

### The gap this closes, stated as the failure the corpus has today

Without the rule, **none of ADR-0254 §1's three write paths can write a row carrying a non-empty
`coverage`**, and §1's path-(i) completeness condition holds only **vacuously**, on a request
carrying no user-facing argument. Four ratified clauses each come close and none closes it:

- **§10** states three resolutions — `AS_STATED`, `DATE_FROM_CONTEXT`, `FROM_SHOWN_RECORD` —
  each *"a total function of recorded inputs"*. Every one turns **a span into a value**. None
  selects the span and none names the argument the value is for.
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
as a writer clause. **§19 books what that decision does not settle, by name, each with what fires it** — a fourth
`ResolutionRule` among them, which §4 below fires — **but the association is not among its
bookings**, so that silence is a gap and not a reservation.

**Why a lane must not simply invent the rule.** §9 clause (ii) forbids adding *"a member for an
argument the act never mentioned"*, but only path (ii)'s widening is a store-enforced refusal:
a freshly minted path-(i) or path-(iii) member is checked by nothing. A wrong association is
therefore a **standing authority over an argument the user never bounded**, and route (d) then
`ALLOW`s inside it with no `CONFIRM` — the failure direction §9's three clauses exist to close,
and #2096 item 8's ruled asymmetry (*"a model is a safe denier and an unsafe allower"*) is the
corpus's own statement of why a guess is not available here.

### What is already ratified and is consumed rather than rebuilt

- **ADR-0254 §3's fixed and bounded comparisons and §4's three readings.** §6 restates which
  argument they are taken over and changes neither comparison, and the canonical encoding they
  compare by is untouched — *"one canonical form in this system and not a second"*.
- **ADR-0254 §1's write paths, their timing and their refusals**, including the row written
  before the question is put and the coverage never edited afterwards.
- **ADR-0249 §7's ground resolution.** A `USER_STATED` element's span *"is resolved by checking
  it is a span of the turn's own request (`TurnResult.utterance`, ADR-0248 §1)"*, by
  `orchestration` and never by a model, and retention copies it forward *"whole and
  unchanged"*. That check is the one ADR-0254 §8 needs, already taken.
- **ADR-0253 §7's element identity.** An element's `id` is minted once and survives retention,
  which is what lets the revision that first recorded it be found.
- **ADR-0249 §2's bounded history and `Goal.interpretation_elided`**, which is what makes the
  refusal below exact rather than approximate.

### The tree, read rather than assumed, at `origin/main` `32968830`

ADR-0254's Lane 1 has landed. `core/types.py` carries `Authorization`, `CoverageMember`,
`ValueBound`, `BoundKind`, `AuthorizationBasis`, `ValueResolution`, `ResolutionRule` and
`ToolDefinition.system_supplied`; `CoverageMember` carries `argument` and `ValueBound`'s
`MONEY` arm carries `currency_argument` and a **required** `maximum`, all three of which this
decision changes; `canonical_json_bytes` is public and is the one encoding;
`permissions/_coverage.py` carries `covers`, `covers_arguments` and a private
`_argument_is_covered` with `_satisfies`, `_satisfies_money`, `_satisfies_period` beside it.
`GoalElement` carries `id`, `text`, `ground`, `applicability`, `evidence_id`, `evidence_row_id`
and `span`; `GoalInterpretation` carries `raised_by`; `ActionPlan`'s `_step_ids_are_unique`
raises *"plan step ids must be unique within a plan"*. Nothing in the tree mints a
`CoverageMember`, and `ToolDefinition` declares nothing about what kind of value an argument
takes.

### What this ADR is not allowed to settle

It decides what a member **records**, how a span **becomes** one, and what a member **meets** at
the comparison — and nothing beyond that. It leaves ADR-0254 §3's conditions 1-5 and §§5, §6,
§7 exactly as they stand, §12's expiry as ADR-0256 §1 leaves it, and §11's projection and every
surface untouched; it opens no route, relaxes no floor, lowers no threshold and moves no
ruling.

## Decision

### 1. The candidate act is a `USER_STATED` constraint of the goal, and there is no second source

> **Normative.** A coverage member is minted from a **`GoalElement` of the goal's *current*
> interpretation's `constraints` whose `ground` is `USER_STATED`**, and from nothing else. Its
> `span` is the member's `span`; the act and the resolution are §2's. **No other value of this
> system mints one** — not a `criteria` or a `conditions` element, not the interpretation's
> `outcome`, not a plan step, not an evidence row, not a memory, not a preference and not a
> prior goal.

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
> amount's currency is a fact about a **declaration**, not about an act, and §6 reads it there.
> `PERIOD` and `TERMS` are unchanged.

**This is the whole of the correction round 1 forced, and it is worth stating why the argument
key was the defect rather than the rule that chose it.** Both review lenses reached the same
place from opposite ends: a value that *fits* an argument is not a value the act's words *bear
on*, so no rule selecting an argument from a request or from a declaration's shape could satisfy
ADR-0254 §9 clause (ii) — *"a value for an argument the act's own words bear on"*. A constraint
about a hotel's star rating has a number in it and would fit a price; a name the user said would
fit any string-valued slot that happened to carry it. **Bearing is established by kind agreement
and by nothing else**: *"four stars"* has no `MONEY` reading (§4), so it mints no money member
and therefore meets no price argument, and the question *"which argument did the user mean"* is
never asked, because the record never claims to answer it.

**And the record is better for it, not merely safer.** One authorization now covers **any**
declaration that declares an argument at the kind, so an authority the user gave once survives a
tool being swapped for another, an argument being renamed, and a declaration being re-issued
with its keys spelled differently — none of which is a change to what the user permitted.
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
> - **a `maximum`** — `under <amount>`, `below <amount>`, `at most <amount>`,
>   `no more than <amount>`, `up to <amount>`;
> - **a `minimum`** — `at least <amount>`, `no less than <amount>`, `more than <amount>`,
>   `over <amount>`, `above <amount>`.
>
> The currency table is `euro`/`euros`/`eur`/`€` → `EUR`, `dollar`/`dollars`/`usd`/`$` → `USD`,
> `pound`/`pounds`/`gbp`/`£` → `GBP`. **A span matching no form mints no member**, and no lane
> adds a form, a currency or a language without its own ratified decision.

> **Normative — a span carrying a negation the matched form does not itself carry mints no
> member.** The negation vocabulary is closed at `not`, `never`, `no`, `n't` and `without`, and
> the test is over the span's own folded tokens. *"no more than"* and *"no less than"* carry
> their own `no` and match; a span that negates a form from outside it does not, and **refuses
> rather than reversing**. This is the one place a reading could invert what the user said, and
> an inversion is a standing authority in the opposite direction from the one they gave.

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
> here** (§9).

### 5. One member per kind, and the mint reads the goal and nothing else

> **Normative — where two candidate elements of one goal would mint members of one `kind`,
> **neither** is minted.** No precedence, no ordering, no most-recent rule and no narrowest-wins
> rule: ADR-0254 §2 refuses a row that carries two members about one thing, and choosing between
> two constraints the user stated is an interpretation of which one they meant. A later
> constraint that **replaces** an earlier one is ADR-0254 §1's path (ii) and supersedes the row;
> two standing at once is an ambiguity, and ADR-0254 §9 clause (iii)'s answer to an ambiguity is
> that the user is asked.

> **Normative — the mint reads the goal's own current interpretation and its retained history,
> and it reads nothing else.** **No request, no plan, no step, no declaration, no registry, no
> store of turns and no clock.** A member is therefore the same value whatever call was being
> built when the row was written, which is what makes *"the authorization records the constraint
> as the user stated it"* true of the record and not merely of its intent — and it is why no
> plan a model produced can shape an authority, at any path, by any route.

**This is what round 1's central finding costs, paid in the right place.** The old rule minted
against the request being built, so a model that arranged a request could arrange which slot an
authority landed in. Reading only the goal removes the input rather than bounding it: there is
no request at the mint for a plan to have shaped.

### 6. What the declaration declares, and where the argument is decided

> **Normative.** `core/types.py` gains **`BoundedArgument`**, a frozen model with
> `extra="forbid"` whose fields are exactly three: **`argument`**, an `EncodableText` naming a
> key of `parameters` at depth **one**; **`kind`**, a `BoundKind`; and **`currency_argument`**,
> an `EncodableText | None` naming the key that carries this amount's currency. A **model
> validator** admits exactly two shapes — `MONEY` with a `currency_argument`, or `PERIOD` or
> `TERMS` with none — and refuses `argument` equal to `currency_argument`.

> **Normative.** `ToolDefinition` gains **one** field, **`bounded_arguments:
> tuple[BoundedArgument, ...]`**, possibly empty, **defaulting to the empty tuple**,
> duplicate-free on `argument`, and naming **no key of that declaration's own
> `system_supplied`** — refused at construction. This is a **BREAKING** contract change to a
> `core` type under golden rule 5 and is flagged as one.

> **Normative — that refusal is what preserves ADR-0254 §3's system-supplied protection after
> the validator that stated it is gone.** That section makes a row whose coverage names a
> system-supplied argument not constructible, and it read `CoverageMember.argument`, which no
> longer exists. A system-supplied key is now declared at no kind, so **no member can ever meet
> it**, and *"a user is never asked to approve an idempotency key"* holds by construction one
> field over.

> **Normative — the argument a member meets, and it is decided here and at no earlier moment.**
> A user-facing argument of the request is **covered** where **all three** hold: its declaration
> carries a `BoundedArgument` naming it; the row carries **exactly one** member of that
> `BoundedArgument`'s `kind`; and the argument satisfies that member under ADR-0254 §3's fixed
> and bounded comparisons and §4's readings, with a `MONEY` bound's currency conjunct taken at
> **the `BoundedArgument`'s own `currency_argument`**. **Where the declaration declares no
> argument at a member's kind, or declares more than one, that member covers nothing** and every
> argument at that kind is uncovered.

> **Normative — an argument the declaration declares at no kind is not covered, ever.** There is
> no default kind, no inference from a value's JSON type, no schema keyword and no fallback to
> an exact comparison: ADR-0254 §4's *"No reading consults a schema to decide what an argument
> means, and there is no exception"* binds this rule as it binds every other.

> **Normative — ADR-0254 §3's condition 6 is restated over this and keeps both its
> directions.** The request is covered where **every user-facing argument it carries** is
> covered above, **and** every member of the row covers at least one of them. An argument the
> row cannot cover leaves the request uncovered, which is §3's first direction; a member that
> meets nothing the request carries leaves it uncovered too, which is §3's second — *"an act
> that fixed `refundable_only` to `true` authorised a call **carrying** that value"*. **There is
> no default, no wildcard, no "not sent therefore unconstrained" and no omission that reads as
> consent**, which is that clause's own sentence and is not weakened here.

> **Normative — one implementation, in `permissions`, and the mint runs none of it.** §5's mint
> takes no declaration, so nothing about this comparison is evaluated twice, and
> `permissions/_coverage.py` stays the only place it lives. **No component composes a member
> across two declarations in one ruling**, and ADR-0254 §3's split between the seam and the
> policy is untouched.

### 7. Writer clauses, and what no model does

> **Normative.** **`orchestration` mints every coverage member and nothing else does.** No
> `ActionPolicy`, no `ToolRegistry`, no store, no reader, no interface adapter, no tool and no
> model output mints, reads, shapes or repairs one. This is ADR-0254 §15's writer clause
> reaching the values §15 could not name.

> **Normative.** **No model output reaches any input of §4, §5 or §6.** A planner envelope
> carrying a coverage member, a bound, a basis, a kind, an argument key or a `BoundedArgument`
> has those values **discarded silently** — not an error, not a park, not a degradation of the
> turn — which is ADR-0254 §9's posture extended to exactly the fields this decision adds, and
> for its stated reason: a value a model wrote into a durable audit chain is unprovenanced.

> **Normative — a model's one contribution is the span, and it can no longer choose a slot.** A
> differently-chosen span mints a **different or no** member, bounded by the user's own words on
> both sides and by §4's closed table; the kind is the reading's, the argument is the
> declaration's at the comparison, and the mint sees no request at all.

### 8. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text**, and it is shown rather than
asserted: *"Would a reader holding only the earlier ADR now act differently, or read one of its
clauses more widely than it now holds?"* **Two documents come out yes**, ADR-0254 in five
scopes and ADR-0016 in one; every other ADR this decision cites comes out **no** and takes
none, which ADR-0082 §1 requires as firmly — *"Absent a clause that fails §1's test, there is
nothing to record."*

**ADR-0254 §2 — partially superseded, in the member's shape.** §2 declares `CoverageMember`'s
fields *"exactly: `argument`, an `EncodableText`; `fixed`; `bound`; and `basis`"*, states
*"`argument` is a key name and never a path"*, rules that *"No two members of one
`Authorization` name the same `argument`"*, gives a `MONEY` bound a `currency_argument` as
*"the whole of the association between an amount and the currency it is denominated in"*, and
makes `maximum` required with `minimum` optional. §3 above replaces `argument` with `kind`,
restates the no-two-members rule over the kind, moves the currency key to the declaration, and
makes `maximum` and `minimum` each optional with at least one present. A reader holding only §2
authors a member that claims to know which slot it fills — the claim round 1 showed no rule can
make good — and cannot represent a stated floor at all. **Every other clause of §2 binds
entire**: the two-shapes-and-no-third validator, `BoundKind`'s three members and their
vocabulary rule, the three kinds' own fields and refusals, `TERMS`'s equality-of-stated-
characters rule, the every-other-argument-is-fixed-only default, and the asymmetry argument that
*"A comparison the system gets wrong in the permissive direction authorises a call the user did
not authorise"* — which is the argument §3 above is written to serve rather than to weaken.

**ADR-0254 §3 — partially superseded, in the comparison and in the field count.** Condition 6
reads that *"the request's user-facing arguments and the row's coverage name the same set of
keys"* and the per-argument rule reads that an argument is covered *"where the row carries a
member naming it"*; §3 itself ties the two — *"The set comparison is over **keys** and the
per-argument rule is over values, and together they are the whole of condition 6."* §6 above
restates that whole over the **declaration**, keeping both of condition 6's directions verbatim
in substance. With the `argument` field goes the validator making a row whose coverage names a
system-supplied argument not constructible; **its rule is preserved** by §6's refusal on
`bounded_arguments`, so *"A user is never asked to approve an idempotency key"* still holds.
And `ToolDefinition` gains **one** further field, `bounded_arguments`, so §3's *"`ToolDefinition`
gains **one** field"* is over-narrow by one. **Every other clause of §3 binds entire**:
conditions 1-5, the user-facing/system-supplied classification and its empty default, the
refusal of a plan step whose own arguments name a system-supplied key, the fill-before-the-fit-
test clause, the `parameters_digest` clause, the bar-stays-monotone clause, the where-each-
condition-is-taken split between the seam and the policy, the coverage-never-widens rule, the
ADR-0021 §5 monotonicity clauses, the resolved-reference clause, and the canonical-encoding
clause §6 above compares by.

**ADR-0254 §4 — partially superseded, in the `MONEY` reading's currency conjunct alone.** That
conjunct reads *"the request carries, at the bound's `currency_argument`, a JSON string equal to
the bound's `currency` byte for byte"*, and the bound no longer carries that key; §6 takes it at
the `BoundedArgument`'s `currency_argument` instead. **The conjunct's force is unchanged** — it
is still stated over the **concrete request**, a request carrying no value at that key is still
not covered, and a declaration naming no currency key for a `MONEY` argument is now
unconstructible rather than merely unbounded. **Every other clause of §4 binds entire**: the
`MONEY`, `PERIOD` and `TERMS` readings in every other limb, the no-float rule, the
no-naive-instant rule, the totality-and-refusal clause, the `reason` discipline, the three
failures told apart, and the no-schema clause, which §6 above cites as binding it.

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
refuses, since a declaration that declares nothing is covered nowhere and asks on every call.
**The exception is this one further field on this argument**, and no lane reads the two records
together as licence to default a third safety field. Every other clause of §1 binds entire.

**And the ones that come out no, shown rather than left to a reader to check.** **ADR-0254 §1**
is relied on entire and is conspicuously untouched: a member needs **no argument at write
time**, so the write-before-the-question rule, the never-edited coverage and all three paths
stand exactly as ratified — which is what lets this decision change what a member *is* without
reaching how a row is *written*. **ADR-0254 §9** is relied on entire and is the clause this
decision exists to satisfy: clause (i)'s basis requirement, clause (ii)'s *"for an argument the
act's own words bear on"* — now true by kind agreement rather than by assertion — clause
(iii)'s ambiguity rule, which §5 above applies, and the discard clause §7 extends. **ADR-0254
§§5, §6, §7, §11-§17 and §19-§22** are untouched; §6's argument-authority bar reads condition 6
and therefore reads §6 above without being restated. **ADR-0249 §1, §2 and §7** and **ADR-0253
§7** are read and not moved. **ADR-0145 §5** and **§9** are cited for the hazard §6 avoids.
**ADR-0029 §5** is relied on rather than superseded: §9 books the system-supplied fill and adds
no second carrier for a derived key.

### 9. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling,
> and each carries the condition that fires it.

- **Where the value of a system-supplied argument comes from.** ADR-0254 §3 requires
  `orchestration` to supply one and names an idempotency key, a client reference and a locale;
  this decision states only that such a key is declared at no kind and is therefore covered by
  nothing. `PlanStep.id` was the candidate source for a client reference and is **refused
  here**: `core/types.py`'s `_step_ids_are_unique` guarantees uniqueness *"within a plan"* alone
  and `Identifier` guarantees no opacity, so it supports neither the cross-plan distinctness nor
  the no-user-content that value needs. ADR-0029 §5's derived key is not available either — it
  is computed from the ruling's id, which does not exist at the moment the fill must happen.
  Fired by the decision that mints a dedicated opaque per-call reference with its own uniqueness
  contract, and by the decision that gives this deployment a configured locale.
- **What makes a `DATE_FROM_CONTEXT` resolution total over a span** — the reader that turns
  *"Sunday"* or *"that weekend"* into a half-open interval in a zone. §4 states what such a
  resolution **mints** and not how it is **taken**, which ADR-0254 §10 states in prose and in no
  component. **Until that decision lands, the only readings an element takes are `STATED_BOUND`
  and `AS_STATED`, and no `PERIOD` member is minted by any live path.** Fired by the decision
  that lands the reader, with its own totality argument and its own arms.
- **Any widening of §4's table** — a form it does not list, a currency it does not name, a
  language other than English, a figure written in words, a bound on a count or a distance.
  The table is deliberately narrow and refuses rather than guessing. Fired by a decision that
  states the wider reading and its own totality argument. **This is the residual a reader should
  weigh most carefully**, and the Consequences name the case it costs.
- **A fourth `BoundKind`** — so that an argument which is neither an amount, a period nor a
  named term can be declared and therefore covered. Today such an argument is covered by
  nothing and every call carrying one asks. Fired by an argument that needs one, with a total
  exact ordering or membership relation the corpus can state — ADR-0254 §2's own condition.
- **A `FROM_SHOWN_RECORD` basis for a coverage member.** It needs a value carrying **both** a
  span of the user's utterance and the record the reference resolved to, and ADR-0249 §1's
  validator admits no `GoalElement` of that shape. Fired by the decision that gives an element
  that shape, which is the same decision ADR-0249 §7 books for how a search finding grounds an
  element.
- **Which of two constraints of one kind the user meant.** §5 refuses both rather than choosing.
  Fired by a decision that states how two acts compose one member, or by a surface that asks.
- **Coverage's other conditions, expiry and every surface.** ADR-0254 §3's conditions 1-5, §§5-7,
  §12's ladder as ADR-0256 §1 leaves it, and §11's projection and the listings: untouched, and
  this decision adds no field any of them renders.

### 10. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **three lanes**, in this order, **each one
> subsystem plus its tests**, and **no lane of this decision wires a consequential capability**
> or enables anything in a production deployment. ADR-0254 §17's rule as ADR-0255 §13 leaves it
> binds all three.

- **L1 — the contract, in `core` alone.** `CoverageMember`'s `kind` and the removal of
  `argument`; `ValueBound`'s `MONEY` reshape and the removal of `currency_argument`;
  `ResolutionRule.STATED_BOUND`; `BoundedArgument`; `ToolDefinition.bounded_arguments` with its
  two refusals. Arms 4(a) and 7(a).
- **L2 — the comparison, in `permissions` alone.** §6's three-part rule and its restatement of
  condition 6 in `permissions/_coverage.py`, with the currency conjunct read off the
  declaration. Arms 1(b), 2(b), 3(b), 5 and 6(b).
- **L3 — the mint, in `orchestration` alone.** §1's candidate selection, §2's act and its four
  refusals, §4's readings and their order, and §5's one-per-kind refusal and goal-only read.
  Arms 1(a), 2(a), 3(a), 4(b), 6(a), 7(b) and 8.

> **Normative — L1 lands before L2 and L2 before L3**, and no later lane's arm is demonstrated
> against an earlier lane's absence. **No lane writes an `Authorization`**: ADR-0254 §20's Lane
> 2 does that, is briefed after all three merge, and is what #2373 unblocks.

> **Normative.** **The three lanes ship the eight arms below, each over controlled fakes, and no
> lane is complete without the arms it is assigned.** Every arm states a correction as a
> **subsequent turn**, on the owner's sequencing ruling of 2026-09-13; **no arm drives a message
> into a running turn**, and none is demonstrated against a live integration.

1. **A stated ceiling, end to end.** **1(a):** a goal whose current interpretation carries a
   `USER_STATED` constraint with span `"under 100 euros"` mints exactly one member — `kind`
   `MONEY`, `maximum` `Decimal("100")`, no `minimum`, `currency` `"EUR"`, `resolution`
   `STATED_BOUND`, basis naming the revision's `raised_by` and that span — and **no second
   member of any kind**. **1(b):** against a declaration declaring `price` `MONEY` with
   `currency_argument` `"currency"`, a request carrying `price="80"` and `currency="EUR"` is
   covered at `price`; one carrying `price="120"` is not; one carrying `currency="USD"` is not.
2. **Kind agreement and not numeric fit — the review's own case.** **2(a):** a constraint with
   span `"4 stars"` mints **no** member: it matches no form of §4's table, `AS_STATED` gives a
   `TERMS` member and never a `MONEY` one. **2(b):** that `TERMS` member meets a price argument
   in **no** request, whatever value it carries, because `price` is declared `MONEY`.
3. **A stated floor mints a `minimum`.** **3(a):** span `"at least 150 euros"` mints `minimum`
   `Decimal("150")` and **no** `maximum`. **3(b):** a request at `"140"` is **not** covered and
   one at `"200"` is. The same arm carries §4's negation guard, in both
   directions: span `"no more than 100 euros"` mints a `maximum`, the matched form carrying its
   own `no`; span `"not under 100 euros"` mints **nothing**, the `not` being a negation the
   matched form does not carry — the reading refuses rather than reversing.
4. **One member per kind.** **4(a):** an `Authorization` carrying two `MONEY` members is not
   constructible. **4(b):** a goal carrying two `USER_STATED` constraints that each read as
   `MONEY` mints **neither**, and a `PERIOD` constraint beside them still mints its own.
5. **The declaration decides, and a renamed argument still meets the member.** A declaration
   declaring **no** argument `MONEY` and one declaring **two** each leave the `MONEY` member
   covering nothing and the call asking; and the **same** member covers a **second** declaration
   that declares its money argument under a **different key**, which is the authority surviving
   a rename.
6. **A `PERIOD` member's zone, and the argument it meets.** **6(a):** given a
   `DATE_FROM_CONTEXT` resolution supplied by a controlled fake, the member's `timezone` is the
   configured zone the act's turn read and is **not** read back off the resolution's own record
   of it. **6(b):** it covers the one argument declared `PERIOD` and no other.
7. **Nothing a model wrote reaches a member.** **7(a):** a member with no basis is not
   constructible. **7(b):** a `FROM_EVIDENCE` element and an `INFERRED` element each mint
   nothing; and a `PlannerOutput` whose envelope carries a coverage member, a bound, a kind and a
   `BoundedArgument` leaves the recorded revision and the minted coverage byte-identical to the
   same envelope without them, with the turn not failing.
8. **The mint reads the goal alone, and the three refusals.** The same goal mints the same
   members against two different requests, two different plans and two different declarations —
   including one declaring nothing; and an element whose `id` is `None`, one whose carrying
   revision's `raised_by` is `None`, and one on a goal whose `interpretation_elided` is non-zero
   and whose oldest **retained** revision is its earliest carrier, each mint nothing.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding
the corpus without it can write no row carrying a non-empty `coverage` at all, and would either
leave ADR-0254 §20's Lane 2 stopped where #2373 stopped it or invent an association no clause
authorises — which is the standing authority over an argument the user never bounded that §9
clause (ii) exists to prevent. That is ADR-0070 §1's test met, and a new ADR is the instrument.

**It is a partial supersession of exactly two documents** (ADR-0070 §3) — ADR-0254 in **five**
scopes and ADR-0016 in **one** — and the `Status` line of each names its scopes **without an
`ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction invariant holds. Against
every other ADR it cites it is a **stacked addition**, and §8 shows the working for each.

**The records land in the same change as this document** (ADR-0082 §7): ADR-0254's and
ADR-0016's `Status` qualifiers and dated notes are written with it and not after it. Nothing
else in either is edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

### 12. Marking, review and ratification

**This ADR is marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
blockquote at column 0, and unmarked text beside a mark is read to determine what the mark means
and supplies no obligation of its own. Quoted marks from other ADRs appear inside quotation
marks in running prose rather than as marks of this document.

**It is a contract-surface change** — two `core` types change shape, an enumeration gains a
member and `ToolDefinition` gains a field — so it owes **both** review lenses, adversarial and
architecture, on one tree, and ADR-0015 §1 makes that true of a prose-only PR.

**It merges as its own PR, ratified, before anything implements against it** (golden rule 5,
ADR-0015). §10's lanes are briefed after it merges, and the ratification flip is one line and no
other byte (ADR-0165).

## Consequences

**What becomes possible.** ADR-0254 §20's Lane 2 can be briefed: a row can carry a non-empty
`coverage`, so route (d) has something to compare and the owner's *"a price change within an
approved limit should remain covered"* has a mechanism — a ceiling the user stated once covers
every later call under it, at any declaration that declares a money argument, with no question
put. And because a member names no slot, an authority survives a tool swap, a renamed argument
and a re-issued declaration, none of which is a change to what the user permitted.

**What becomes harder, and it is the honest cost.** Route (d) reaches a request only where
**every** user-facing argument it carries is declared at a kind — so a declaration with a guest
count, a room type or any argument outside `MONEY`, `PERIOD` and `TERMS` is covered by nothing
and asks on every call until the fourth kind §9 books arrives. Integration authors acquire an
obligation they are not billed for until they read this ADR, and the empty default means a
declaration that says nothing gets more questions rather than fewer.

**The reading is the narrow part, and it is where a reader should look first.** §4's table has
ten forms and three currencies. *"under 100 euros"* reads; *"under a hundred euros"*,
*"unter 100 Euro"*, *"max €100"* and *"never spend over 100 euros"* do not — the last because
the negation guard refuses a form whose polarity a token outside it inverts, which is the
fail-closed half of the one reading that could reverse what the user said. **That is a
deliberate refusal and not an oversight**, and it means the owner's own illustration of the rule
mints nothing until the table is widened by the decision §9 books. Refusing costs a question;
reading *"never … over"* as a floor would cost a standing authority in the opposite direction
from the one the user gave.

**These are the cases that would falsify the design.** A deployment where users routinely state
bounds the table does not carry, so route (d) is never reached and the mechanism is inert. A
declaration whose sole `MONEY` argument is an amount the user **receives**, where a ceiling they
stated about spending meets it — kind agreement is coarser than intent, and this is the case
where that coarseness bites. And a declaration with two money arguments, where §6 refuses both
and every such call asks, which is correct but may prove to be the common shape rather than the
rare one.

## Alternatives considered

**Keeping the argument key on the member and choosing the argument at the mint.** This was the
first draft of this decision, by two rules — a declared-kind rule for ranges and a canonical-
value trace for exact values. Both review lenses blocked it independently and correctly: a value
that **fits** an argument is not a value the act's words **bear on**, so *"4 stars"* minted a
price ceiling and a name the user said minted authority over any slot that happened to carry it.
No selection rule available at the mint could satisfy ADR-0254 §9 clause (ii), and the defect
was the key rather than the rule that chose it.

**A planner nomination of the (element, argument) pair, verified by code.** Sound, and it was
the direction four of round 1's nine findings pointed at. Declined because the pairing is per
*(element, declaration)* — a constraint meets a declaration's **keys** only once a step has
chosen a capability — so it cannot live on `GoalElement` and would have to live on `PlanStep`,
superseding ADR-0253's step enumeration and its seam and wire, ADR-0249 §7's envelope, and
moving `PROTOCOL_VERSION`. Deciding the association at the **comparison** buys the same
correctness with no seam, no label space and no model-authored value.

**Asking the user to confirm the association.** Foreclosed by ADR-0254 §1, which writes the
path-(i) row **before** the question is put and whose `settle` *"moves one field and its
instant"*, so no member can rest on the answer. It is also the second question this design
exists to remove.

**Minting a `MONEY` bound from a bare figure, with the direction fixed by the kind.** The first
draft's rule, and round 1 refuted it twice: *"pay at least 150"* authorised 140, and a quoted
price beside a limit authorised the quote. The direction is in the user's words or it is
nowhere, which is what §4's table is for and why a span carrying no direction mints no bound.

**Leaving `system_supplied` a tuple of key names and giving `PlanStep.id` as the client
reference.** Declined in §9 on the tree's own text: step ids are unique *"within a plan"* and
`Identifier` promises no opacity, so the value supports neither guarantee such a reference needs.
Booking it is better than shipping a source that does not hold.
