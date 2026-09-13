# 266. A coverage member is minted from a user-stated constraint, and its argument is named by the declaration or by the value

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **two narrowly stated scopes, both in §3, and §9 shows the working for each. Its
  `ToolDefinition` field clause, in the field count alone**: *"`ToolDefinition` gains **one**
  field"* becomes two, the second being `bounded_arguments`, because the association between a
  recorded span and an argument that takes a **range** has no other declared source and §4
  forbids reading one out of a schema. **And its `system_supplied` member type, together with
  the three examples that clause names**: the members become `SystemSuppliedArgument`s carrying
  a `SystemSuppliedKind`, because a tuple of bare key names leaves the fill half of that clause
  unimplementable, and the **idempotency key is retired as one of its examples** — ADR-0029 §5
  already carries that value on `ToolCall.idempotency_key`, derived from a ruling that does not
  exist at the moment §3 requires the fill to happen. Every other clause of §3 binds entire and
  several are what this decision rests on: the user-facing/system-supplied classification
  itself, the empty default and its argument, the no-member-for-a-system-supplied-argument
  validator, the refusal of a plan step whose own arguments name such a key, the fill-before-the-fit-test
  clause, the digest clause and the no-schema clause. §§1, 2, 4–22 stand as they are.
- **Partially supersedes** [ADR-0016](0016-tool-definition-and-registry.md)
  — **one scope, in §1, and it is the scope ADR-0254 already took there, reaching one further
  field**: the `ToolDefinition` model declaration and the required-field clause in the
  application to `bounded_arguments` alone. A reader holding only §1 authors a definition that
  never carries one and does not conform, and the empty-tuple default is an exception to
  *"Every field that a permission decision depends on is required"* on the same grounds
  ADR-0254 §18 records for `system_supplied` — the default makes the **opposite** claim to the
  one §1 refuses, so a declaration that says nothing mints no bound, needs an exact value for
  every argument and asks where it has none. **The exception is this one further field on this
  one argument**, and no lane reads either record as licence to default a third safety field.
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
as a writer clause. **§19 books what this decision does not settle, by name, each with what fires it, and this
is not among them** — so the silence is a gap and not a reservation.

**Why a lane must not simply invent the rule.** §9 clause (ii) forbids adding *"a member for an
argument the act never mentioned"*, but only path (ii)'s widening is a store-enforced refusal:
a freshly minted path-(i) or path-(iii) member is checked by nothing. A wrong association is
therefore a **standing authority over an argument the user never bounded**, and route (d) then
`ALLOW`s inside it with no `CONFIRM` — the failure direction §9's three clauses exist to close,
and #2096 item 8's ruled asymmetry (*"a model is a safe denier and an unsafe allower"*) is the
corpus's own statement of why a guess is not available here.

### What is already ratified and is consumed rather than rebuilt

- **ADR-0254 §3's per-argument rule and §4's three readings.** This decision runs them and
  writes no second comparison, which is §3's own *"one canonical form in this system and not a
  second"* read onto the predicate rather than onto the encoding.
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
- **ADR-0029 §5's derived idempotency key**, carried on `ToolCall.idempotency_key` and not in
  `parameters`.

### The tree, read rather than assumed, at `origin/main` `32968830`

ADR-0254's Lane 1 has landed. `core/types.py` carries `Authorization`, `CoverageMember`,
`ValueBound`, `BoundKind`, `AuthorizationBasis`, `ValueResolution`, `ResolutionRule` and
`ToolDefinition.system_supplied`; `canonical_json_bytes` is public and is the one encoding;
`permissions/_coverage.py` carries `covers`, `covers_arguments` and a private
`_argument_is_covered` with `_satisfies`, `_satisfies_money`, `_satisfies_period` beside it.
`GoalElement` carries `id`, `text`, `ground`, `applicability`, `evidence_id`, `evidence_row_id`
and `span`; `GoalInterpretation` carries `raised_by`; `PlanStep` carries `id`. Nothing in the
tree mints a `CoverageMember`, and `ToolDefinition` declares nothing about what kind of value an
argument takes.

### What this ADR is not allowed to settle

It decides the **association** and the **shape**, and nothing beyond them. It does not touch
ADR-0254 §§3–§6's coverage comparison, §12's expiry as ADR-0256 §1 leaves it, §11's projection
or any surface, and it opens no route, relaxes no floor and moves no ruling.

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
> carry. A bound read off one would authorise an argument value on the strength of a sentence
> about when to act. A user whose words bound the action states a **constraint** — ADR-0254 §1's
> path (iii) in terms, *"the bound is an element of its `constraints`"*.

> **Normative — the interpretation's own `outcome` mints nothing, and the reason is that it
> carries no identity.** §2's act is found by walking the retained history for the revision that
> **first** recorded an element, which ADR-0253 §7's minted-once `id` makes exact. The outcome
> has no such id: ADR-0249 §7 retains it by copying `outcome`, `outcome_ground` and
> `outcome_span` forward byte for byte, so two revisions carrying one outcome are
> indistinguishable from two that restated it, and the act a member rested on could not be
> named. Taking the current revision's `raised_by` instead would name a turn the span need not
> be a span of, which is the one thing ADR-0254 §8 refuses at construction.

> **Normative — the *current* interpretation and no earlier one.** An element a later revision
> neither retained nor replaced is **not** in the current interpretation (ADR-0249 §7,
> *"omission is removal"*), and minting from an earlier revision's tuple would restore a
> constraint the user's own later words removed. The history is walked **only** to find the act
> (§2), never to find a candidate.

### 2. The act, the span and the resolution: what the basis is filled from, and when it refuses

> **Normative.** A member minted from an element carries an `AuthorizationBasis` whose **`span`
> is that element's `span` byte for byte**, whose **`act` is the `raised_by` of the earliest
> revision of the goal's retained `interpretation` that carries an element with that element's
> `id`**, and whose `resolution` is §5's. Nothing is re-resolved, re-normalised or re-checked
> against a model: ADR-0249 §7 already checked that span against that turn's own
> `TurnResult.utterance` when the revision was recorded, which is exactly the check ADR-0254 §8
> requires, and ADR-0254 §1 re-takes it against the store before the row is built.

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

### 3. The association: two rules, in one order, and no third

> **Normative — the association is decided by code, from two values and no others: the
> **declaration** the row is about, and the **request** being built.** No model proposes it, no
> model verifies it, and no envelope carries it. ADR-0254 §9's discard clause and §15's writer
> clause bind it entire, and a lane that finds itself reading a planner value to decide which
> argument a span is for has left this decision.

> **Normative — rule 1, the declared kind, and it is tried first.** A member whose shape is a
> **`ValueBound`** (§5) is minted at the **one user-facing argument the declaration declares at
> that bound's `BoundKind`** (§4), and at no other. **Where the declaration declares no argument
> at that kind, or declares more than one, no bound is minted from that span** — for any of
> them — and the span falls to rule 2.

> **Normative — rule 2, the value trace.** A member whose shape is **`fixed`** is minted at the
> user-facing argument of the request whose value's **canonical JSON encoding equals the
> canonical JSON encoding of the resolution's own value**, byte for byte — `canonical_json_bytes`,
> the encoding `ActionRequest.parameters_digest` is taken over, and not a second one.
> **Where exactly one user-facing argument matches, that argument is the member's; where two or
> more match, or none does, no member is minted from that span.**

> **Normative — the two rules are ordered and never combined.** Rule 1 decides a bound and rule
> 2 decides a fixed value; neither is consulted about the other's shape, and no member is minted
> by agreement of the two. A span that rule 1 refuses is offered to rule 2 with its resolution
> unchanged, and a span both refuse mints nothing.

> **Normative — the refusals above are not ambiguity reports and nothing downstream repairs
> them.** An argument that receives no member is **uncovered**, ADR-0254 §3's condition 6 is
> unsatisfied, the request reaches no standing route, and the user is asked about the concrete
> call — which is §9 clause (iii)'s own outcome for *"an argument no member names"* and §4's
> *"the ruling is the one the policy's table reached without it"*. **No default, no wildcard, no
> nearest match and no second attempt.**

**Why the two rules are asymmetric, stated because the asymmetry is the whole design.** A
**fixed** member pins one value: the worst a mis-traced one can do is authorise a later call
carrying **the user's own word** in a slot the user did not choose, and every other argument
still needs its own member for condition 6 to hold. A **bound** is a range, and a mis-associated
one authorises a whole interval of values the user never spoke about — *"under 150 euros"*
landing on a deposit argument would stand for every deposit up to 150. So the range gets the
strict rule, which asks the **declaration** rather than inferring, and refuses outright where the
declaration does not distinguish; and the exact value gets the cheap rule, which can only ever
pin what the user said. #2373 names both hazards by name — matching against rendered values
*"mis-fires where two arguments carry one value"*, and picking *"the money argument"* of a
declaration *"has no declared source"* — and the uniqueness refusal closes the first while §4
supplies the second.

**This is why the planner is not asked, and the alternative is named rather than left implicit.**
A planner could nominate the pair (element, argument) as a label, exactly as ADR-0249 §7
nominates a retention and ADR-0265 §2 nominates an action, and `orchestration` could verify it.
But verify it **against what**? The only mechanical tests available are the two above; a
nomination that passes them adds nothing, and one that fails them is refused — so the nomination
buys no association code could not already make, while adding a seam field, a label space and a
value a model authored to the inputs of the one comparison that decides whether a call is
authorised. ADR-0249 §7's line is the reason it stays out: *"A model may never clear a
permission, a coverage test, a prerequisite or a dependency."*

### 4. What the declaration must declare, and it is a typed field beside the schema

> **Normative.** `core/types.py` gains **`BoundedArgument`**, a frozen model with
> `extra="forbid"` whose fields are exactly three: **`argument`**, an `EncodableText` naming a
> key of `parameters` at depth **one**, exactly as `CoverageMember.argument` is;
> **`kind`**, a `BoundKind`; and **`currency_argument`**, an `EncodableText | None` naming the
> key that carries this amount's currency. A **model validator** admits exactly two shapes —
> `MONEY` with a `currency_argument`, or `PERIOD` or `TERMS` with none — so a money argument
> that declares no currency key, and a period that declares one, are each **not constructible**.
> `argument` and `currency_argument` are refused equal.

> **Normative.** `ToolDefinition` gains **one** field, **`bounded_arguments: tuple[BoundedArgument,
> ...]`**, possibly empty, **defaulting to the empty tuple**, duplicate-free on `argument`, and
> naming **no key of that declaration's own `system_supplied`** — refused at construction, on
> ADR-0254 §3's rule that a system-supplied argument takes no member at all. This is a
> **BREAKING** contract change to a `core` type under golden rule 5 and is flagged as one.

> **Normative — the empty default is fail-closed and is the whole of its justification.** A
> declaration that declares nothing has **no** user-facing argument at any `BoundKind`, so rule
> 1 refuses every bound and every member it can ever carry is an exact value. **It costs a
> question and can never authorise a call**, which is the direction ADR-0016 §1 exists to
> protect and the same argument ADR-0254 §3 makes for `system_supplied`'s default. Requiring the
> field would oblige every declaration and every fixture in the tree to write `()` for a fact
> empty on almost all of them, with no return in that direction.

> **Normative — the declaration is read for the *kind* and never for the *bound*.** No operand
> of a `ValueBound` comes from `bounded_arguments`: not a `maximum`, not a `minimum`, not a
> `currency`, not an instant, not a zone and not a term. What the declaration states is **which
> argument takes a range of which kind**, which is a fact about the tool; what the bound states
> is **what the user permitted**, which is a fact about an act. Two facts, two carriers, and
> ADR-0150's hazard avoided by never letting one supply the other.

> **Normative — `currency_argument` is the declaration's and is never inferred.** ADR-0254 §2
> makes the bound's `currency_argument` *"the whole of the association between an amount and the
> currency it is denominated in"* and forbids inferring it *"from a field name, a type, a schema
> keyword or a neighbouring argument"*. §5 copies it from the declaration's own
> `BoundedArgument` and from nowhere else. It **may** itself be user-facing or system-supplied:
> ADR-0254 §4 reads it off the **request** at the comparison, and no member is ever minted for
> it here.

**A field beside `parameters_schema` and not a keyword inside it, and the reason is ADR-0254
§3's own, restated for one more field rather than re-argued.** ADR-0145 §5 states the hazard in
terms — 2020-12 *"ignores keywords it does not know"*, so a declaration carried as an `x-`
keyword is *"silently dropped"* — and here the drop would be in the permissive direction for one
spelling of the mistake and undetectable for the other. ADR-0254 §4's closing clause forbids the
alternative outright: *"no lane reads a `parameters_schema` keyword to establish an association
this decision requires a row to name."* A typed field states the fact where every other declared
safety fact of a tool already lives.

### 5. The shape: a total function of the resolution's rule and the declaration

> **Normative — which resolution a span takes, in one order, and the first total one is taken.**
> For one candidate element the loop attempts **`DATE_FROM_CONTEXT`** and then **`AS_STATED`**,
> and takes the first that is total over that span. **`FROM_SHOWN_RECORD` is not attempted**: a
> `GoalElement` carries no reference to a record the loop showed, ADR-0249 §1's validator gives
> a `USER_STATED` element a span and **no** `evidence_id`, and re-resolving the words against
> that turn's shown set at minting time would be a fresh interpretation of the user's language
> — a model act at the one moment §9 clause (i) reserves to code. **What makes a
> `DATE_FROM_CONTEXT` resolution total over a span is not decided here** (§10).

> **Normative — `DATE_FROM_CONTEXT` mints a `PERIOD` bound and never a `fixed` member.** Its
> `starts_at` and `ends_at` are the half-open interval the resolution yielded, and its
> `timezone` is the **resolution's own** `timezone` — the configured zone as that turn read it,
> which ADR-0254 §8 makes a different fact from the bound's and forbids deriving either from the
> other. The argument is §3 rule 1's: the one user-facing argument the declaration declares
> `PERIOD`, and where it declares none or more than one, **no member**.

> **Normative — `AS_STATED` mints a `MONEY` bound where, and only where, all five hold.** The
> declaration declares **exactly one** user-facing argument `MONEY` (§3 rule 1); that
> `BoundedArgument` names a `currency_argument`; the **span** is accepted by ADR-0254 §4's
> `MONEY` reading as a `Decimal` that is finite and not negative; the request carries at that
> `currency_argument` a JSON **string of three uppercase ASCII letters**; and §6's satisfaction
> test passes. The bound is then `MONEY` with `maximum` the span's own figure, **no `minimum`**,
> `currency_argument` the declaration's and `currency` **the request's own value there**. Where
> any of the five fails, no `MONEY` bound is minted and the span falls to §3 rule 2.

> **Normative — the `maximum` is fixed by the kind and is never read off the act's words.** No
> component reads *"under"*, *"up to"*, *"at most"*, *"about"* or *"at least"*, in any language,
> to choose a direction: a figure the user wrote about an amount this system is to **pay** bounds
> it **above**, always, and a call below it introduces no *"additional costs"* — which is the
> only thing the owner's Q1 asks to be asked about. **A `minimum` is never minted by this
> decision**, by any path, from any span.

> **Normative — the `currency` is a narrowing taken from the request, and the record says so
> rather than implying it.** It is **not** a resolution of the act's words; the basis's
> `resolution` records how the **amount** was taken and nothing else, and no member is minted
> for the `currency_argument` itself. Pinning it can only **narrow** — a later call denominated
> in any other currency fails ADR-0254 §4's last conjunct and is not covered — so it adds no
> member for an argument the act never mentioned and raises no maximum, which is the whole of
> what §9 clause (ii) forbids an interpretation to do.

> **Normative — every other `AS_STATED` resolution mints a `fixed` member whose `fixed` is the
> span read as itself**, at the argument §3 rule 2 traces and at no other. Normalised by
> nothing, which is ADR-0254 §10's discipline and ADR-0248 §1's before it: the pass strips once
> and nothing re-normalises.

> **Normative — no `TERMS` bound is minted by this decision, on any path.** `ValueBound.terms`
> is a *set* the user named and one span states **one** member of it; a one-term `TERMS` bound
> and a `fixed` member of that string cover exactly the same requests under ADR-0254 §4's
> equality-of-stored-characters rule, so minting the bound would add a second spelling of one
> authority with no widening to show for it. A term the user named mints a **`fixed`** member.

> **Normative — the shape is decided here and nowhere else, and a member of any other shape is
> not minted.** There is no fourth outcome, no shape chosen from an element's `text`, from a
> schema keyword, from a prior row, from a preference, from a model's reading or from the number
> of words in the span.

**The direction rule is the one place this decision chooses a reading rather than refusing, and
it is worth showing the working.** ADR-0254 §2 makes `maximum` required and `minimum` optional,
so a `MONEY` bound is an upper bound with an optional floor; there is no spelling of *"at
least"* to mint even if a component could read one. The residual risk is a declaration whose
`MONEY` argument is an amount the user **receives** rather than pays, where *"150"* would stand
for every value at or below it — and the damage there is that the system is authorised to accept
**less**, which is not a cost the user did not authorise and which ADR-0254 §6's bar still stops
short of an `ALLOW` on anything else about the call. The alternative — refusing every `MONEY`
bound until a resolution can read a comparative — would make the owner's *"A price change within
an approved limit should remain covered"* unreachable by construction, and is declined for that
reason and named here so a later decision can revisit it with an argument rather than by
surprise.

### 6. One moment, one comparison: a member is minted against the request it would cover

> **Normative — every member this decision mints is minted against a concrete `ActionRequest`
> being built**, which is the one moment all three of ADR-0254 §1's write paths have one: path
> (i) proposes about a concrete call, path (iii) writes *"when the goal's first request reaching
> that declaration is built"*, and path (ii)'s correction is written at the next such build of
> that goal and that declaration. **No row is written and no member is minted at a turn that
> builds no request.**

> **Normative — a candidate member is minted only where the request being built is covered by
> it**, under ADR-0254 §3's per-argument rule and §4's readings, taken over that request's own
> value at that argument. A candidate the request fails is **discarded**, the argument is
> uncovered, and nothing is substituted, clamped or widened to make it fit.

> **Normative — there is exactly one implementation of that rule, and this decision moves it
> rather than writing a second.** `core/types.py` gains **`member_covers(member, parameters)`**,
> ADR-0254 §3's per-argument rule together with §4's three readings, moved **whole and
> unchanged** out of `permissions/_coverage.py`, which then calls it. Two implementations of one
> comparison are what ADR-0254 §3 refuses for the **encoding** — *"two canonicalisations that
> disagree produce a false mismatch at one end and a false match at the other"* — and the
> predicate carries the identical hazard one level up: a mint and a ruling that disagreed would
> write a row that authorises a call the policy then refuses, or worse, the reverse.

**Minting against the request is not letting the plan choose the authority, and the distinction
is exact.** What the request supplies is a **filter**: a candidate whose value the request does
not carry is dropped. What it never supplies is a **value** — every `fixed` is the resolution's
own output and every `maximum` is the span's own figure, so the widest authority a row can carry
is the one the user's own words already state. A model that built a request to attract a member
can at most obtain a member the user's words already licensed, at an argument §3's two rules
allow it to land on, and ADR-0254 §6's bar then refuses a standing route for every argument of
every later call that member does not cover.

### 7. The system-supplied fill: a kind on the declaration, and the idempotency key is not one

> **Normative.** `core/types.py` gains **`SystemSuppliedKind`**, a `StrEnum` valued by
> lower-cased member name and **closed at exactly one member**: **`CLIENT_REFERENCE`** — an
> opaque per-call reference the system supplies so a later reader can recognise the call. The
> vocabulary is **added to and never renamed**, and a member arrives only with a **total,
> code-run source** stated beside it.

> **Normative.** `core/types.py` gains **`SystemSuppliedArgument`**, a frozen model with
> `extra="forbid"` whose fields are exactly two: **`argument`**, an `EncodableText` naming a key
> of `parameters` at depth one; and **`kind`**, a `SystemSuppliedKind`. **`ToolDefinition.system_supplied`
> becomes a `tuple[SystemSuppliedArgument, ...]`**, duplicate-free on `argument` and still
> defaulting to the empty tuple. This is a **BREAKING** contract change to a `core` type under
> golden rule 5 and is flagged as one.

> **Normative — `CLIENT_REFERENCE` is filled with the `PlanStep.id` of the step the request
> performs, and with nothing else.** It is minted once per step by `orchestration`, is stable
> across every retry and every rebind of that step, is distinct across steps and across plans,
> carries no user content, and exists before the candidate fit test — which is where ADR-0254 §3
> requires the fill to happen. It is in `ActionRequest.parameters_digest` like every other
> argument, so it cannot move between the ruling and the dispatch.

> **Normative — no declaration classifies an idempotency key system-supplied, and a
> `SystemSuppliedKind` for one is not minted.** ADR-0029 §5 already derives that value and
> carries it on **`ToolCall.idempotency_key`**, outside `parameters`, from the ruling's own id —
> a value that does not exist at the moment ADR-0254 §3 requires the fill to happen, since the
> fill precedes the fit test and the fit test precedes the request and the ruling. A second copy
> inside `parameters`, computed from something else, would be two shapes of one fact and the two
> would differ. **A tool whose upstream wants the key in its payload maps it inside the
> integration**, which ADR-0029's `ToolImplementation` contract already requires of a key format
> — *"that mapping must be deterministic"*.

> **Normative — a key whose value has no stated source is not classified system-supplied, and
> the consequence is stated rather than discovered.** Such a key stays **user-facing**, needs a
> coverage member like any other, and asks where it has none (ADR-0254 §3). This is the
> fail-closed direction: an unclassified argument costs a question, and a classified one with no
> source would cost a value nobody could account for in the digest the ruling is pinned on.

### 8. Writer clauses, gathered in one place

> **Normative.** **`orchestration` mints every coverage member and fills every system-supplied
> argument, and nothing else does.** No `ActionPolicy`, no `ToolRegistry`, no store, no reader,
> no interface adapter, no tool and no model output mints, associates, shapes or repairs one.
> This is ADR-0254 §15's writer clause reaching the values §15 could not name.

> **Normative.** **No model output reaches any input of §3, §5 or §7.** A planner envelope
> carrying a coverage member, a bound, a basis, an argument key, an association, a
> `BoundedArgument` or a system-supplied value has those values **discarded silently** — not an
> error, not a park, not a degradation of the turn — which is ADR-0254 §9's posture extended to
> exactly the fields this decision adds, and for its stated reason: a value a model wrote into a
> durable audit chain is unprovenanced.

> **Normative.** **A model's one contribution is the span, and it is contribution to a value
> already constrained.** ADR-0249 §7 has the planner propose a `USER_STATED` element's `span`
> and `orchestration` refuse any span that is not a span of that turn's own utterance. A
> differently-chosen span mints a **different or no** member and never a **wider** one: it is
> bounded by the user's own words on both sides, and every other input to a member — the act,
> the argument, the shape, the maximum, the currency and the zone — is read off the goal, the
> declaration or the request.

### 9. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text**, and it is shown rather than
asserted: *"Would a reader holding only the earlier ADR now act differently, or read one of its
clauses more widely than it now holds?"* **Two come out yes** and take a record; every other ADR
this decision cites comes out **no** and takes none, which ADR-0082 §1 requires as firmly —
*"Absent a clause that fails §1's test, there is nothing to record."*

**ADR-0254 §3 — partially superseded, in two scopes.** The first is its **`ToolDefinition` field
clause in the field count alone**: *"`ToolDefinition` gains **one** field"* becomes two, the
second being `bounded_arguments` (§4). A reader holding only §3 authors a declaration that
declares no argument's kind, and §3 rule 1 then mints no bound for any tool in the tree — the
owner's *"explicitly permitted ranges"* unreachable by construction. The second is its
**`system_supplied` member type and the three examples that clause names**: the members become
`SystemSuppliedArgument`s carrying a `SystemSuppliedKind` (§7), and the **idempotency key ceases
to be one of the examples**, because ADR-0029 §5 derives that value from a ruling that does not
exist at the moment §3 requires the fill to happen. A reader holding only §3 would implement a
fill with nothing to switch on, which is the half of that clause #2373 records as
unimplementable.

**Every other clause of §3 binds entire, and most of this decision rests on them**: the
user-facing/system-supplied classification and its *"Every key it does not name is
user-facing"*; the empty default and the argument for it; the validator making a row whose
coverage names a system-supplied argument not constructible, which now reads over each member's
own `argument`; the refusal to build a request whose plan step's arguments name such a key; the
fill-before-the-fit-test clause and ADR-0144 §7's merged evaluation; the digest clause; the
bar-stays-monotone clause; and the no-schema-keyword clause, which §4 above is written to obey.

**ADR-0016 §1 — partially superseded, in one scope, and it is the scope ADR-0254 §18 already
took there reaching one further field.** `ToolDefinition` gains `bounded_arguments` defaulting
to the empty tuple, so §1's model declaration is over-narrow by one field and its unconditional
*"Every field that a permission decision depends on is required"* takes a **second** recorded
exception — a permission decision does depend on this one, since it decides whether a member is
a range. **The grounds are the clause's own reason, which does not reach this default**: §1
forbids a default because *"A default is a claim"*, and the empty tuple here makes the
**opposite** claim — no argument takes a range, so every member is an exact value and a
declaration that says nothing asks more often rather than less. **The exception is this one
field on this argument**, and no lane reads the two records together as licence to default a
third safety field. Every other clause of §1 binds entire, `frozen=True` and its audit argument
included, and §4's `parameters_schema` declaration is relied on rather than moved.

**And the ones that come out no, shown rather than left to a reader to check.** **ADR-0254 §§1,
2, 8, 9, 10, 15 and 19** are **relied on as written** and are each joined by an obligation
stated here rather than narrowed: §1's three paths, its write-before-the-question rule and its
never-edited coverage (§6 above rests on all three); §2's two shapes, its depth-one rule, its
`currency_argument` clause and its every-other-argument-is-fixed-only default; §8's basis and
its two-zones clause; §9's three clauses and its discard clause, which §8 above extends to new
fields without reading any of them more narrowly; §10's three resolutions and its
no-member-where-a-resolution-cannot-be-taken sentence, which this decision applies and does not
move — a `FROM_SHOWN_RECORD` resolution stays available to anything that can supply a record
reference, and what §5 states is that a `GoalElement` cannot; §15's writer clauses; and §19's
bookings, none of which this decision discharges. **ADR-0249 §1 and §7** are relied on
entire — the element validator, the span check, retention and the ground-resolution refusals —
and nothing here changes what crosses the planning seam. **ADR-0253 §7**'s minted-once element
`id` is read and not moved. **ADR-0029 §5** is relied on rather than superseded: §7 above
declines to duplicate its derivation and adds no second carrier for it. **ADR-0145 §5** and
**§9** are cited for the hazard §4 avoids. And **moving `_argument_is_covered` into `core` as
`member_covers` (§6) supersedes nothing**: ADR-0254 §3 states the rule and names no module for
it, §16's roster is an inventory of that decision's own additions and not a closed statement
about `core`, and golden rule 2 is satisfied because the predicate reads two values and no
store.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling,
> and each carries the condition that fires it.

- **What makes a `DATE_FROM_CONTEXT` resolution total over a span** — the reader that turns
  *"Sunday"* or *"that weekend"* into a half-open interval in a zone. §5 states what such a
  resolution **mints** and not how it is **taken**, which is ADR-0254 §10's and is stated there
  in prose and in no component. **Until that decision lands, the only resolution an element
  takes is `AS_STATED`, and no `PERIOD` bound is minted by any live path** — so the owner's
  *"make it Sunday"* case is expressible, is arm 6, and is not yet reachable end to end. Fired
  by the decision that lands the reader, with its own totality argument and its own arms.
- **A coverage member grounded in the user's answer to the question itself.** ADR-0254 §1 writes
  a path-(i) row **before** the question is put and its settlement *"moves one field and its
  instant"*, so no member can rest on the answer and every argument of a confirmed call still
  needs the user's own earlier words to bear on it. Fired by a decision that lets a proposal's
  coverage be completed at settlement, which is a change to that section's shape and not to this
  one's.
- **A `FROM_SHOWN_RECORD` basis for a coverage member.** It needs a value carrying **both** a
  span of the user's utterance and the record the reference resolved to, and ADR-0249 §1's
  validator admits no `GoalElement` of that shape. Fired by the decision that gives an element
  that shape, which is the same decision ADR-0249 §7 books for how a search finding grounds an
  element.
- **A `TERMS` bound's producer, and a `minimum`'s.** One span states one term and one figure;
  composing a set or a floor from several acts is a rule about how two acts compose one member,
  which no clause of ADR-0254 states. Fired by a decision that states it.
- **A second `SystemSuppliedKind`.** A **locale** is ADR-0254 §3's third example and has no
  source in this deployment: `Settings` carries `timezone` and no locale, and adding one is a
  configuration question with its own answer. Fired by the decision that lands a configured
  locale; until then such a key stays user-facing and asks.
- **Whether route (d) is reachable where the user's own words do not bear on every user-facing
  argument of the call.** ADR-0254 §3's condition 6 requires the request's user-facing arguments
  and the row's coverage to *"name the same set of keys"*, and this decision relaxes nothing:
  where one argument mints no member the row covers nothing and every call asks. Fired by a
  decision that takes condition 6 head-on, with its own argument and its own arms.
- **Coverage comparison, expiry and every surface.** ADR-0254 §§3–§6 as they stand, §12's ladder
  as ADR-0256 §1 leaves it, and §11's projection and the listings: untouched, and this decision
  adds no field any of them renders.
- **Whether a declaration may distinguish two arguments of one `BoundKind`.** §3 rule 1 refuses
  both rather than choosing, and no ordering, priority, label or tie-break is minted here. Fired
  by an argument that actually needs one, with a discriminator the act itself carries.

### 11. The lane cut, and the arms this decision owes

> **Normative.** This decision is implemented in **two lanes**, in this order, and **no lane of
> this decision wires a consequential capability** or enables anything in a production
> deployment. ADR-0254 §17's rule as ADR-0255 §13 leaves it binds both.

- **L1 — the contract.** `core/types.py`'s `BoundedArgument`, `SystemSuppliedKind`,
  `SystemSuppliedArgument` and `member_covers`; `ToolDefinition.bounded_arguments` and the new
  member type of `ToolDefinition.system_supplied`; and the **one call site in
  `permissions/_coverage.py`** the move of `_argument_is_covered` leaves behind. **The call site
  is part of the same change and not a second one**: a predicate that moves has one caller, and
  leaving it unchanged would leave the two implementations the move exists to prevent. Arms 2,
  3, 7 and 8(a).
- **L2 — the mint, in `orchestration` alone.** §1's candidate selection, §2's act and its three
  refusals, §3's two rules, §5's shapes, §6's moment and satisfaction test, and §7's
  `CLIENT_REFERENCE` fill. Arms 1, 4, 5, 6 and 8(b).

> **Normative — L1 lands before L2**, and no arm of L2 is demonstrated against L1's absence.
> **Neither lane writes an `Authorization`**: ADR-0254 §20's Lane 2 does that, is briefed after
> both of these merge, and is what #2373 unblocks.

> **Normative.** **The two lanes ship the eight arms below, each over controlled fakes, and no
> lane is complete without the arms it is assigned.** Every arm states a correction as a
> **subsequent turn**, on the owner's sequencing ruling of 2026-09-13; **no arm drives a message
> into a running turn**, and none is demonstrated against a live integration.

1. **The campsite's *"under 150 euros"* becomes a `MONEY` bound on the booking's price argument
   and nothing else.** A goal whose current interpretation carries a `USER_STATED` constraint
   with span `"150"`, against a declaration declaring `price` `MONEY` with `currency_argument`
   `"currency"`, and a request carrying `price` `"140"` and `currency` `"EUR"`: one member, at
   `price`, `maximum` `Decimal("150")`, no `minimum`, `currency` `"EUR"`, basis naming the
   revision's `raised_by` and that span. **No member at `currency`**, and none at any other
   argument.
2. **Two declared `MONEY` arguments and one span mint nothing.** The same goal against a
   declaration declaring both `price` and `deposit` `MONEY`: **no bound at either**, the span
   falls to §3 rule 2, `"150"` matches no argument's canonical encoding, and the row's coverage
   is empty — so the request reaches no standing route and the user is asked.
3. **A `FROM_EVIDENCE` element and an `INFERRED` element mint nothing, and the type is why.**
   Constructing an `AuthorizationBasis` from either is impossible before the mint is reached,
   because neither carries a span; the arm asserts the refusal at the type and at the mint, and
   asserts that a `USER_STATED` element beside them still mints its own member.
4. **A planner-carried member and a planner-carried association are both discarded silently.** A
   `PlannerOutput` whose envelope carries a coverage member, a bound, an argument key and a
   `BoundedArgument` leaves the recorded revision, the minted coverage and the turn's outcome
   byte-identical to the same envelope without them, and the turn does not fail.
5. **The value trace, in both directions.** One `AS_STATED` span `"Riverside"`: where exactly one
   user-facing argument carries that string, one `fixed` member at it; where two do, **no
   member**; where none does, **no member** — and in every case no member at any argument the
   span did not match.
6. **A `DATE_FROM_CONTEXT` resolution mints a `PERIOD` bound at the uniquely declared argument,
   and a correction replaces the member at that argument.** Given such a resolution supplied by a
   controlled fake, the bound carries the resolution's interval and the resolution's own
   `timezone`; and on ADR-0254 §1's path (ii), on a **subsequent turn**, the new member replaces
   the superseded row's member at that same argument while every other member is carried forward
   byte for byte.
7. **The elided-history refusal.** A goal whose `interpretation_elided` is non-zero and whose
   oldest **retained** revision is the earliest one carrying the element's `id` mints **no**
   member from it; the same goal with `interpretation_elided` at 0 mints one; and an element
   whose `id` is `None`, and one whose carrying revision's `raised_by` is `None`, each mint none.
8. **The system-supplied fill.** **8(a), L1:** a `ToolDefinition` declaring an argument
   `CLIENT_REFERENCE` constructs, one declaring a `bounded_arguments` member naming a
   system-supplied key does not, and a `MONEY` `BoundedArgument` with no `currency_argument`
   does not. **8(b), L2:** the value filled at that key is the step's own `PlanStep.id`, it is
   identical across two builds of the same step and different across two steps, and a plan step
   whose own arguments name that key is refused before any request is built — ADR-0254 §3's
   refusal, unchanged and re-asserted here because this lane is the first that could have
   weakened it.

### 12. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding
the corpus without it can write no row carrying a non-empty `coverage` at all, and would either
leave ADR-0254 §20's Lane 2 stopped where #2373 stopped it or invent an association no clause
authorises — which is the standing authority over an argument the user never bounded that §9
clause (ii) exists to prevent. That is ADR-0070 §1's test met, and a new ADR is the instrument.

**It is a partial supersession of exactly two documents** (ADR-0070 §3) — ADR-0254 in **two**
scopes and ADR-0016 in **one** — and the `Status` line of each names its scope **without an
`ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction invariant holds. Against
every other ADR it cites it is a **stacked addition**, and §9 shows the working for each.

**The records land in the same change as this document** (ADR-0082 §7): ADR-0254's and
ADR-0016's `Status` qualifiers are written with it and not after it. Nothing else in either is
edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

### 13. Marking, review and ratification

**This ADR is marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
blockquote at column 0, and unmarked text beside a mark is read to determine what the mark means
and supplies no obligation of its own. Quoted marks from other ADRs appear inside quotation
marks in running prose rather than as marks of this document.

**It is a contract-surface change** — `ToolDefinition` gains a field and one of its fields
changes type — so it owes **both** review lenses, adversarial and architecture, on one tree, and
ADR-0015 §1 makes that true of a prose-only PR.

**It merges as its own PR, ratified, before anything implements against it** (golden rule 5,
ADR-0015). §11's lanes are briefed after it merges, and the ratification flip is one line and no
other byte (ADR-0165).

## Consequences

**What becomes possible.** ADR-0254 §20's Lane 2 can be briefed: a row can carry a non-empty
`coverage`, so route (d) has something to compare and the owner's *"a price change within an
approved limit should remain covered"* has a mechanism. The `MONEY` case works end to end today;
the `PERIOD` case is expressible and waits on one reader §10 books.

**What becomes harder, and it is the honest cost.** A standing authority now requires the user's
**own recorded words** to bear on **every** user-facing argument of the call, because ADR-0254
§3's condition 6 is a set equality and this decision relaxes nothing. A booking whose
declaration carries a currency argument the user never spoke will mint no member for it and will
ask on every call. That is the fail-closed direction and it is chosen knowingly, but it means
route (d) will be **unreachable for many real declarations** until the decision §10 books for
condition 6 lands — and a deployment that expected standing authority to be the common case will
find it is the rare one.

**Two integration-author obligations arrive with it.** A declaration that wants ranged authority
must say which argument takes which kind, and one that wants an argument filled by the system
must say which kind it is. Both default to empty and both fail closed, so an author who says
nothing gets more questions rather than fewer — which is the right direction and is also a cost
nobody is billed for until they read this ADR.

**These are the cases that would falsify the design.** A declaration with two arguments of one
`BoundKind` that users routinely bound — §3 rule 1 refuses both and every such call asks, and
the fix is a discriminator the act carries, not a tie-break in code. A `MONEY` argument that is
an amount the user **receives**, where §5's always-a-maximum rule stands for an interval the user
did not name. And a deployment where planners select spans loosely — *"under 150 euros"* rather
than *"150"* — where every bound falls to a `fixed` member that matches nothing, and route (d)
becomes inert without anything failing.

## Alternatives considered

**The planner nominates the association and `orchestration` verifies it.** ADR-0249 §7 and
ADR-0265 §2 both have this shape and it is the corpus's usual answer. Declined in §3: code can
verify a nomination only by the two rules stated there, so a nomination that passes them adds
nothing and one that fails them is refused — while the seam field, the label space and the
model-authored value are all real cost at the one comparison that decides whether a call is
authorised.

**The user confirms the association in the confirmation's projection.** ADR-0254 §11 already
shows every value and every bound, so the association is on screen. Declined because it is a
second question at the moment this design exists to remove one, which is ADR-0254 §19's own
ground for not asking *"until when?"* at the act; and because §11's projection is rendered from
a row that must already be constructible, so the association must be decided before it can be
shown.

**A resolution that reads a comparative out of the span** — *"under"*, *"at most"*, *"no more
than"* — so a `MONEY` bound's direction comes from the act's words. Declined because ADR-0254
§10 closes the resolutions at three and a reader of natural-language comparatives is a fourth,
with a totality argument this decision does not have and a failure mode that is silent and
permissive in one spelling. §5 takes the direction from the **kind** instead and says so.

**Minting from the goal's `outcome` as well as its `constraints`**, so that an objective's own
words can cover an identity argument. Declined in §1: the outcome carries no identity, so the
act it rests on cannot be named, and a basis naming the wrong turn is refused at the write with
nothing on the goal to say why.

**Leaving `system_supplied` a tuple of key names and deciding the fill per key by convention.**
Declined in §7: a key named `locale` and a key named `client_reference` are indistinguishable to
a filler, so the convention would be a name match — the inference ADR-0254 §2 forbids one seam
over, reappearing at the one value that enters the digest without a user ever seeing it.
