# 254. Phase 4 validates the plan in code, and route (d) authorises a concrete call against fixed values and permitted ranges from recorded acts

- Status: Proposed
- Date: 2026-09-12

## Context

### Where this comes from

Lane **A6** of #2255, the fourth phase of the task lifecycle — *validate / authorize*. Three
earlier decisions of that batch name this one by number and defer to it in terms:

- ADR-0249 §13 — *"**Authorization: fixed values, permitted ranges, the basis triple, and
  coverage from several acts.** A6."*
- ADR-0252 §15 — *"**Authorization coverage.** **A6**. A dispatch needs both, they are two
  tests, and nothing in"* this decision clears an authorization or is cleared by one.
- ADR-0253 §5 — *"is A6's** and is a second test a dispatch must pass (ADR-0252 §15)"*, and
  §11's *"A6's"* again.

The owner's rulings of 2026-09-12 on revision 1 of the report on #2255 are what it records, and
the two that shape it are quoted whole rather than paraphrased.

**Q1 — authorization scope.** *"Bind authorization to explicitly fixed values and explicitly
permitted ranges. A price change within an approved limit should remain covered. A clear later
instruction such as 'make it Sunday' can supply authorization for that change; do not
automatically ask the user to repeat it. Ask only when the concrete action introduces something
not already covered, such as additional costs or materially different terms."* And its
clarification: *"Authorization must trace to a recorded user act, but resolved values need not
appear literally in the message. Support contextual reference resolution and normalization,
preserving both the instruction and its interpretation. Ask about material ambiguity or
consequences outside the authorized scope."*

**Decision 7 — expiry.** *"Workflow-specific authorization carries a justified, visible expiry.
This does not apply indiscriminately to existing standing permissions or to configured-provider
authority (ADR-0247)."*

**Q4 — what a production deployment may be given.** *"No consequential capability is wired into
a production deployment until the verification, uncertain-outcome and cancellation guarantees
for its class are implemented and demonstrated. A milestone may demonstrate dependent execution
against controlled integrations with no such capability wired; wiring one is what this rule
binds."* §16 carries that rule and this ADR dispatches nothing under it.

### The gap this closes

ADR-0021 §5 sends every transmitting tool to `CONFIRM` — *"A definition with a **non-empty
`discloses`** … may not receive `ALLOW` with `authorised_by` unset"* — and §6 names the relief
valve: *"the standing grant is the only sanctioned way to stop asking. Until it lands, a
disclosing tool prompts every time, which is the correct default and a poor steady state."*

Two standing routes have since landed and neither reaches the act this milestone is about.
ADR-0193 built **route (b)** over a *canonical destination set*: its five comparisons are *"the
request's `tool` equals the grant's `ToolDefinition` by value; the request's binding's `account`
equals the grant's `BoundAccount` by value … **every** member of the request's canonical
destination set is a member of the grant's"*. ADR-0247 added **route (c)** over the
deployment's own configuration, for `WEB_SEARCH` and nothing else.

Neither is a bound on an **argument value**. A user who says *"book that campsite for the
weekend, under sixty pounds"* has fixed some arguments and bounded another, about one objective,
and has authorised nothing a destination set can express. So today the workflow #2255 exists to
build asks once per step; and a user who then says *"actually, make it Sunday"* is asked to
repeat, as a confirmation, the instruction they just gave — which is the interruption the owner
ruled against.

### What is already ratified and is consumed rather than rebuilt

- **The request already carries the arguments, and was given them for this.** ADR-0021 §3
  carries `parameters` on `ActionRequest` while *"no rule in this ADR reads it"*, deliberately:
  *"ADR-0017 §3 makes per-call gating a condition on designating the tool egress seam — 'per-call
  gating that runs before transmission, not merely a declared ceiling' — so the invocation ADR
  must give the policy the arguments. Carrying an unread field costs a line; adding one to a
  ratified cross-subsystem contract later is a breaking change."* This decision is the first
  rule that reads it.
- **The route pattern.** ADR-0247 §2 is the worked model for adding a route to ADR-0148 §3 with
  its own derived fact, its own `authorised_by`, its own trail invariant and a discriminator
  readable from the row alone.
- **The reservation that governs how a second standing source is told apart.** ADR-0193 §6:
  *"A later ADR that wants a *different* standing source for egress is making a **contract
  change** to how a row in this scope is read — it decides how the reference is told apart,
  whether by tagging it, by a second field, or by narrowing this scope — and it does not inherit
  an 'add your own arm' permission from this ADR."* §6 of this ADR is that decision.
- **The recheck machinery.** ADR-0152 §7's `rebind` *"derives the binding afresh from `tool` and
  `parameters` … and **refuses** unless the binding it derived is **equal** to `approved`"*, and
  ADR-0247 §8(b′) demonstrates it end to end. ADR-0037 §2 fixes the sequence — *"decide → record
  → read back → claim"* — and ADR-0058 declined to put a check in the executor: *"`StepExecutor`
  does not validate trail presence, and #259 is resolved as WONTFIX."*
- **The attempt already has the field this record is appended to.** ADR-0249 §5 gives
  `GoalAttempt` *"`plan_ids`, `execution_ids` and `authorization_ids`, each a possibly-empty
  `tuple[Identifier, ...]`"*, with *"Plans, executions and authorizations … referenced by id and
  never inlined"*. This decision is that field's first producer.
- **The state the attempt stops in already exists.** `AttemptState.AWAITING_AUTHORIZATION`
  (ADR-0249 §5) is one of seven closed members and has no producer at `origin/main`. This
  decision is its first.

### The tree, read rather than assumed, at `origin/main` `f6a22821`

- `permissions/policy.py` — `ThresholdActionPolicy.decide` builds `fired`/`grounds`, computes
  `at_configured` through `_at_configured_provider`, and consults `_only_the_disclosure_floor`'s
  five conditions before either standing route. Route (c) answers first and `_covering` is then
  called zero times. `ConfiguredSearchDestination` is two recorded values and no store handle.
- `permissions/audit.py` — `_check_standing_shape` classifies a standing row by
  `ruling.authorised_subject`: set, and ADR-0193 §6's eight checks apply; unset, and
  `_check_configuration_authority` admits it on `binding.closed_loop` and pointer equality.
- `permissions/recipient_grants.py` is the `RecipientGrantStore`, satisfying `RecipientGrants`
  and `RecipientGrantResolution` structurally. **`permissions/grants.py` is the
  `SqliteSourceGrantStore`** (ADR-0097 §4) — a different store, and the one ADR-0148 §3's fourth
  clause forbids as limb (b).
- `orchestration/runner.py` — `StepRunner._run` binds, builds the `ActionRequest`, calls
  `decide` on a detached copy, records, reads back, and only then `_execute` hands the executor a
  call whose claim is the executor's. A `CONFIRM` commits `PENDING → AWAITING_APPROVAL`.
  `_rebound` is the resuming path's `rebind`.
- `core/types.py` — `ActionRequest.parameters` is a `FrozenJsonMapping` and
  `parameters_digest` is `sha256(_canonical_json(self.parameters))`; `PermissionRuling` carries
  `authorised_by` and `authorised_subject` and nothing else about authority; `ToolCost` is the
  corpus's money shape, a `Decimal` `amount` beside a shape-validated ISO-4217 `currency`;
  `GoalAttempt.authorization_ids` is present and unwritten.
- `wire/envelope.py` — `PROTOCOL_VERSION` is **38**.
- **ADR-0249's lanes L1 and L2 have landed**: `Goal`, `AttemptPhase`, `AttemptState`,
  `AttemptOutcome`, `AttemptEffort`, `GoalAttempt` and `GoalBrief` are on the tree. **ADR-0250,
  ADR-0251, ADR-0252 and ADR-0253 are ratified and not implemented**: every type this decision
  cites from them — `GoalQuestion`, `GoalEvidence`, `StepCondition`, `PlanStep.depends_on`,
  `PlanStep.when`, `PlanStep.verifies` and the engine-resolved result reference — is read from
  those ADRs and is **not** a shape this decision found in the tree. Where a clause below rests
  on one, it says so.

### What this ADR is not allowed to settle

The plan-driving stage and the claim's second conjunct (A7); retry, reconciliation and
`EFFECT_UNRESOLVED` (A8); the cancellation boundary and what a cancellation racing a dispatch
does (A9); verification and which `AttemptOutcome` an attempt earns (A10); `GoalEvidence`, its
verdicts and its invalidation (A4); the plan's own step fields (A5); which user acts open an
attempt (A2 and A3, by ADR-0249 §5). §16 lists what it declines, each with what fires it.

## Decision

### 1. `Authorization`: a durable row proposed before the question and settled by the answer

> **Normative.** `core/types.py` gains **`Authorization`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `id`, a `DurableIdentifier`; `goal`, an
> `Identifier`; `tool`, a `ToolDefinition`; `account`, a `BoundAccount`; `destinations`, a
> non-empty, duplicate-free `tuple[CanonicalDestination, ...]` in
> `EgressBinding.canonical_destination_set`'s one canonical order; `coverage`, a possibly-empty
> `tuple[CoverageMember, ...]`; `proposed_at`, a `UtcInstant`; `expires_at`, a `UtcInstant`
> **strictly after** it; `confirmation`, a `DurableIdentifier | None`; `supersedes`, a
> `DurableIdentifier | None`; `disposition`, an **`AuthorizationDisposition`**; and
> `settled_at`, a `UtcInstant | None`. The field list is **closed**, and a lane adding a member
> is changing this decision rather than implementing it.

> **Normative.** **`AuthorizationDisposition` is a `StrEnum` valued by lower-cased member name
> and closed at exactly six members**: `PROPOSED`, `ESTABLISHED`, `DECLINED`, `EXPIRED`,
> `REVOKED` and `SUPERSEDED`. The vocabulary is added to and never renamed.

> **Normative — the transition graph, stated whole, and there are exactly five edges.**
>
> - `PROPOSED → ESTABLISHED` — the user approved;
> - `PROPOSED → DECLINED` — the user refused;
> - `PROPOSED → EXPIRED` — the deadline passed before an answer;
> - `ESTABLISHED → REVOKED` — the user withdrew the authority;
> - `ESTABLISHED → SUPERSEDED` — a later row replaced it (§5).
>
> **`DECLINED`, `EXPIRED`, `REVOKED` and `SUPERSEDED` are *retired*: no edge leaves them**, and
> `settle` refuses a row already in one. `PROPOSED` and `ESTABLISHED` are the two members an
> edge leaves, and no other edge exists — there is no `DECLINED → ESTABLISHED`, no
> `EXPIRED → ESTABLISHED`, no `SUPERSEDED → ESTABLISHED` and no `REVOKED → ESTABLISHED`.

> **Normative.** **`settled_at` is present exactly on a row whose disposition is not
> `PROPOSED`, and it is the instant of that row's most recent settlement.** On an `ESTABLISHED`
> row it is therefore the instant the authority came into being, because no edge has left
> `ESTABLISHED` — which is what §7's trail check compares against and why that check reads the
> disposition first.

> **Normative — the record is written before the question is put, not after the answer.** This
> is ADR-0244's ratified shape for exactly this problem — a durable row carrying what is put to
> the user, settled by a later answer, surviving a restart, with its deadline *"computed …
> once, at the instant the park is written"* — adopted rather than re-derived. **The
> confirmation's projection (§11) is rendered from this row**, so the coverage and the expiry a
> user is shown are read from a durable record rather than recomputed from a configuration that
> may have moved, and a restart between the question and the answer changes neither.

> **Normative — the settlement, and it is the store's single operation.**
> `GoalAuthorizationStore` gains **`settle(id, to: AuthorizationDisposition, *, settled_at)`**,
> which moves a row along one of §1's five edges under compare-and-swap and **refuses every
> move that is not an edge** — including any move out of a retired disposition. **The
> compare-and-swap is on the `disposition` itself** — the move succeeds only where the row
> currently stands at that edge's source — so **no version token is added to the type** and two
> racing settlements cannot both win: the second finds a disposition the edge does not leave and
> is refused. That is `PlanStore`'s compare-and-swap argument (ADR-0014 §5) taken over a field
> that already carries the state. An approval settles `ESTABLISHED`; a refusal settles `DECLINED`; an
> answer arriving at or after `expires_at` settles `EXPIRED` and **establishes nothing**; a
> user withdrawal settles `REVOKED`; and a superseding write settles the row it supersedes
> `SUPERSEDED`. **There is no other mutation and no `update`**: a settlement moves one field
> and its instant, exactly as `ParkedRead`'s does, and the record's coverage, basis, account,
> destinations and expiry are never edited.

> **Normative.** **An expiry is settled and is never inferred**, which is ADR-0244 §10's
> mechanism: a `PROPOSED` row whose `expires_at` is at or before the clock's reading is settled
> `EXPIRED` by the **first operation that reads it**, and there are exactly two — a `covering`
> read, and the answer that names it. That is safe for ADR-0244 §10's own reason, since an
> expired proposal is refused as an establishment at all and there is no live answerer for the
> settlement to race. **`standing`, `resolve`, `recent` and `export` settle nothing**, because
> `standing` returns only `ESTABLISHED` rows and the other three are history reads.

> **Normative — and a `PROPOSED` row neither operation reads again stays `PROPOSED`, which is
> stated rather than swept.** It is never live, so it authorises nothing and appears in no
> listing; it is visible in `export` and `recent` as what it is, a question that was put and
> never answered. **No sweep, no timer, no reclaim and no start-up scan settles it**, which is
> ADR-0250 §12's posture for a question's disposition read onto this row: nothing infers a
> terminal state from silence, and the cost of leaving one is a row nobody can act on.

> **Normative — a record is `live` when its `disposition` is `ESTABLISHED` and the clock stands
> strictly before its `expires_at`.** `PROPOSED` is **never** live, and no clause of this
> decision reads a proposal as an authority: a row the user has not answered authorises nothing
> whatever else is true of it. Every retired disposition is never live, and an `ESTABLISHED`
> row past its `expires_at` is **not live**. **It is not settled `EXPIRED`** — that member is
> the answer a question never got, and re-using it for a lapsed authority would make the two
> indistinguishable in a listing — but it is still `REVOKED` by a withdrawal and still
> `SUPERSEDED` by a renewal (§5), so a lapsed row never becomes an obstacle.

> **Normative.** **The declaration is embedded by value and the capability is never the
> subject.** ADR-0021 §1 closed #54 by embedding the whole `ToolDefinition` — *"there is no
> name left to rebind"* — and ADR-0193 §1 read that forward onto a record that outlives the
> call. A `PlanStep.capability` is an `Identifier` a registry resolves at selection time, so an
> authorization keyed on one would authorise whatever that name means when the step is
> dispatched. Coverage compares the declaration **whole and by value**, so any edit to a
> registered declaration leaves every authorization established about the previous one covering
> nothing and the user is asked again — the cost accepted in the safe direction, exactly as
> ADR-0193 §1 accepts it.

> **Normative.** **One record is about one declaration**, and a plan whose steps reach two
> declarations needs two. A `CONFIRM` is about one request and one declaration (ADR-0021 §1),
> and **no lane widens a single answer across declarations it did not name**.

> **Normative — there are exactly two ways a row is written and no third.**
>
> - **(i) Proposed against a `CONFIRM`.** `confirmation` names the recorded `CONFIRM` the
>   question rode, `disposition` is `PROPOSED`, `proposed_at` is that decision's `decided_at`,
>   and the row is settled by the answer. **This is the only path that may create a member,
>   widen a bound, set `destinations`, set `account`, set `tool` or set `expires_at`**, because
>   it is the only one on which the user is shown what they are being asked (§11). It **may**
>   carry `supersedes`, naming **any `ESTABLISHED` row of the same `goal` and `tool`, live or
>   expired**, which is settled `SUPERSEDED` in the same write as this row's `ESTABLISHED`
>   settlement. **That is what renews an authority whose expiry has passed** as well as what
>   widens a live one: the predecessor is retired and the replacement established in one write,
>   so the uniqueness rule below is never momentarily false and no authority has to be cleared
>   out of the store by hand.
> - **(ii) A correcting instruction.** A later recorded turn of the same goal whose span names
>   an argument a **live** row of that goal already carries a member for — live, because a
>   correction transcribes the predecessor's `expires_at` and correcting an authority that has
>   already lapsed would produce a row born expired. It writes a row with
>   `confirmation` **unset**, `supersedes` naming that row, `disposition` **`ESTABLISHED`**
>   directly and `settled_at` equal to `proposed_at` — the recorded turn's instant — and
>   settles the superseded row `SUPERSEDED` **in the same write**. **Every member of the
>   superseded row that the correction does not replace is carried forward byte for byte, with
>   its own basis** (§8), and `goal`, `tool`, `account`, `destinations` and `expires_at` are
>   **transcribed unchanged**.
>
> A row carrying `confirmation` unset **and** `supersedes` unset is **not constructible**. A
> row carrying `confirmation` is **written** `PROPOSED` and reaches every later disposition
> through `settle` alone — a rule of the write path and not of the type, for the reason below.

> **Normative — what path (ii) may change, and what it may never touch.** It may **replace a
> fixed value** for an argument the superseded row already fixed, and **narrow a bound** for an
> argument it already bounded. It may **never** add a member for an argument the superseded row
> does not name, **widen** a bound — a raised `maximum`, a lowered `minimum`, an added term, a
> longer period — change `goal`, `tool`, `account` or `destinations`, or move `expires_at`.
> **A change to a destination-bearing argument takes path (i)**, because the canonical
> destination set is what ADR-0148 §3's first clause is stated over and a correction must not
> move it. **A widening of any kind takes path (i) and is confirmed.**

> **Normative — where each of those refusals lives, because they are not all the same kind,
> and the division is stated because getting it wrong makes a valid stored row unreadable.**
>
> - A rule true of **every state a row is ever persisted in** is a **model validator** on the
>   type: the `settled_at`/disposition pairing, `expires_at` strictly after `proposed_at`, the
>   rule that `confirmation` and `supersedes` are not both unset, a `CoverageMember`'s two
>   shapes, a `ValueBound`'s three, a `ValueResolution`'s three, and the agreement between a
>   `MONEY` bound and a fixed currency member of the same row.
> - A rule about the state a row may be **first written in** is the **store's**, at `record`:
>   a row carrying `confirmation` is written `PROPOSED`, and a path-(ii) row is written
>   `ESTABLISHED` with `settled_at` equal to `proposed_at`. **It is not a model validator**,
>   because the same row is later persisted `ESTABLISHED` with that same `confirmation` — a
>   validator stating it would refuse to decode the row it had just written, and `resolve`,
>   `recent` and `export` must return every row whatever its disposition (§16).
> - A rule comparing **two rows** is the **store's** too, at the write, where both are in hand:
>   the transcription check, the non-widening check, the uniqueness check and the atomic
>   settlement of the superseded row. So is the transition graph, enforced by `settle`. And a rule comparing a basis against a **recorded turn** is
> **`orchestration`'s**, resolved exactly as ADR-0249 §7 resolves a `USER_STATED` ground — *"A
> `USER_STATED` element's `span` is resolved by checking it is a span of the turn's own request
> (`TurnResult.utterance`, ADR-0248 §1)"* — before the row is built. **No `core` type reads a
> store, a trail or a turn**, which is golden rule 2, and no lane closes a two-record window
> with a validator that cannot see the second record.

> **Normative.** **Coverage is always taken over one row** (§3). Superseding at the moment of
> the act, rather than composing at the moment of the ruling, is what keeps that true: the
> policy reads one row, `authorised_by` names one row, the trail resolves one row, and a
> revocation of the authority behind **any** argument is a revocation of the row the ruling
> would cite. **No component composes coverage across two rows**, at ruling time or at any
> other.

> **Normative.** **Supersession is permanent and does not depend on the superseding row's own
> fate.** Revoking a superseding row leaves **neither** live: `SUPERSEDED` is retired and no
> edge leaves it, so nothing un-supersedes one. That is the
> fail-closed direction, and the one that refuses to resurrect a broader authority the user has
> already moved on from. Both rows stay in the store, both appear in `export`, and neither is
> deleted but by `clear`.

> **Normative — at most one `ESTABLISHED` row per goal and declaration, enforced without a
> clock.** `record` **refuses** a write that would leave two rows of one `goal` and one `tool`
> both `ESTABLISHED`. The refusal is stated over the **disposition** rather than over liveness,
> so the write path reads no clock, which is ADR-0193 §1's duplicate-refusal discipline. **And
> `covering` returns `None` where more than one live row of that goal and declaration would
> answer** — a state this refusal makes unreachable, and refused at the read as well because a
> query that chose between two would be the composition §5 declines.

> **Normative.** **The goal is a field and the scope is never the conversation.** An
> authorization of goal A covers no request of goal B, however adjacent, however recent and
> whatever the conversation. A conversation-scoped record would make an act about a campsite
> authorise a call about a flight the same afternoon, which is exactly the *tool*-keyed
> standing authorisation ADR-0193 §3 names as the shape to avoid — *"a grant keyed on the tool
> covers every recipient of every later call, which is what OpenAI's `always_approve` does
> today and what #1548 names as the shape to avoid"* — one axis over.

> **Normative.** **`coverage` may be empty, and an empty `coverage` covers no request whose
> `parameters` are non-empty.** §3's rule is stated per argument over the request's own
> arguments, so emptiness is not a wildcard; it is the record of an act that fixed nothing, and
> the only request it covers is one carrying no arguments at all.

**A settled disposition rather than an appended revoking record, and the reason is that this row
is a question before it is an authority.** ADR-0193's store appends a revoking record because a
recipient grant is a preference the user states once and later withdraws, and *"a revocation **is**
an append"*. An authorization is put to the user as a question about a concrete call and is
answered — which is `ParkedRead`'s shape, not `RecipientGrant`'s, and ADR-0244 already solved the
whole of it: a durable row written when the question is put, a deadline computed once at that
instant, a settlement by whatever operation next reads an expired one, and a disposition that
tells an answered question from an abandoned one. Appending a revoking record would also have
forced a transcription of every field including `supersedes`, which is a shape a revoking record
cannot carry and an exception list a lane would have to remember.

**Why a record of its own rather than a member on `RecipientGrants`.** ADR-0193 §6 forecloses
the cheap answer in terms: a second egress standing source *"is making a **contract change** to
how a row in this scope is read"*, and the round-12 finding behind that sentence is that with
two stores *"a bare `DurableIdentifier` and a bare `Sha256Hex` do not say which seam `record`
should ask"*. Putting coverage members on `RecipientGrant` would not avoid that — it would make
one store hold two kinds of record with two different covering rules and one `covering` member
that has to choose between them, and it would put a goal id, an argument key and a money bound
on a type ADR-0193 §1 closed by name (*"the field list is closed: ADR-0193 §1 states the
record's members exactly, and a lane adding one is changing that decision rather than
implementing it"*). A second store with a second seam, told apart by §6's own discriminator, is
the shape that reservation asks for.

### 2. A coverage member is a fixed value or a permitted range, and there is no third kind

> **Normative.** `core/types.py` gains **`CoverageMember`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `argument`, an `EncodableText`; `fixed`, a
> `FrozenJsonValue | None`; `bound`, a `ValueBound | None`; and `basis`, an
> `AuthorizationBasis` (§7), **required**. A **model validator** admits exactly two shapes — a
> `fixed` and no `bound`, or a `bound` and no `fixed` — so a member of any third kind is **not
> constructible**.

> **Normative.** **`argument` is a key name and never a path.** The depth is **one**: never a
> dotted expression, an index, a wildcard or a selector, and no lane adds an addressing syntax.
> This is ADR-0253 §6's rule for a `StepOutputRef.field` — *"The depth is **one** … and no lane
> adds an addressing syntax"* — stated once more rather than re-derived, and for its reason: a
> path language is a second thing to get wrong at the one comparison that decides whether a
> call is authorised.

> **Normative.** **A `MONEY` bound names its own currency argument, and no schema is
> consulted to find one.** `currency_argument` is a key of `parameters` like any other
> `argument` (depth one), and it is the whole of the association between an amount and the
> currency it is denominated in. **Where a record carries a `MONEY` bound and also a `fixed`
> member naming that same `currency_argument`, the fixed value equals the bound's `currency`**,
> refused at construction otherwise: a row that bounds sixty pounds and fixes the currency to
> something else is not a record of anything the user said. **A call whose declaration carries
> no currency argument takes no `MONEY` bound** — it takes a fixed value for its amount, which
> is §2's fixed-only default — and no lane infers an association from a field name, a type, a
> schema keyword or a neighbouring argument.

> **Normative.** **No two members of one `Authorization` name the same `argument`**, refused at
> construction. A precedence rule between two members about one argument is a rule somebody
> would have to remember at the comparison, and it is better not to have one.

> **Normative.** `core/types.py` gains **`ValueBound`**, a frozen model with `extra="forbid"`
> carrying `kind`, a **`BoundKind`**, and the arguments that kind takes. **`BoundKind` is a
> `StrEnum` valued by lower-cased member name and closed at exactly three members**: `MONEY`,
> `PERIOD` and `TERMS`. The vocabulary is added to and never renamed.

> **Normative — the three kinds, and a model validator refuses every other shape.**
>
> - **`MONEY`** carries `currency`, three uppercase ASCII letters validated for shape and not
>   against a register; `currency_argument`, an `EncodableText` naming the key of `parameters`
>   that carries the currency for this amount; and `maximum`, a `Decimal` that is finite and not
>   negative; and optionally `minimum`, under the same two refusals and less than or equal to
>   `maximum`.
>   Both refusals and the shape rule are `ToolCost`'s, reused rather than restated, and for its
>   stated reason: *"`Decimal` admits `Infinity` and `NaN`, neither of which has a JSON
>   representation or survives arithmetic in a running total, and comparing `NaN` with `<`
>   raises rather than answering."*
> - **`PERIOD`** carries `starts_at` and `ends_at`, both `UtcInstant`, with `ends_at` strictly
>   after `starts_at`; and `timezone`, the IANA zone name in which a calendar date argument is
>   read. The interval is **half-open**, `[starts_at, ends_at)`, which is ADR-0194 §1's own
>   convention for a period and is adopted so the corpus has one.
> - **`TERMS`** carries `terms`, a non-empty, duplicate-free, ordered `tuple[EncodableText,
>   ...]`. Membership is **equality of the stored characters and nothing else**, which is
>   ADR-0237 §3's rule for a `TopicLabel` — *"No fold is applied and none is needed"* — read
>   onto a set the user named.

> **Normative.** **Every other argument is fixed-only.** An argument whose bound would be of
> any other kind — a count, a distance, a free-text field, a nested object, a list, a boolean —
> **takes a fixed value or no member at all**, and no lane adds a fourth `BoundKind` without
> its own ratified decision. This is ADR-0148 §2's exactness default applied one axis over:
> where the corpus does not establish a total, exact ordering over an argument's values, a
> range over it is a comparison it cannot prove, and the answer to an unproven comparison is
> the supplied form unchanged and byte-exact.

**Three kinds and not a general expression language, because the failure modes are asymmetric.**
A comparison the system gets wrong in the permissive direction authorises a call the user did
not authorise, and that is undetectable afterwards; a comparison it gets wrong in the
restrictive direction costs a question. The three kinds above are the three the owner's
direction names — *"additional costs"*, *"make it Sunday"*, *"materially different terms"* —
each has a total order or a membership relation the corpus already states somewhere, and each
can be compared without parsing anything the user wrote. A fourth kind arrives with a fourth
argument that actually needs one.

### 3. Coverage: six conditions, three of them ADR-0193's and three new

> **Normative.** An `Authorization` **covers** an `ActionRequest` when **all six** hold:
>
> 1. the row is **live** (§1);
> 2. the request's `goal` (§6) equals the row's `goal`;
> 3. the request's `tool` equals the row's `tool` **by value**;
> 4. the request's binding's `account` equals the row's `account` **by value**, both facts and
>    never one;
> 5. **every** member of the request's canonical destination set is a member of the row's,
>    compared as `CanonicalDestination` compares — every field, never across protocols;
> 6. and **every argument of the request is covered** by the per-argument rule below.
>
> A row that fails any of them covers nothing about that request.

> **Normative.** **Conditions 3, 4 and 5 are ADR-0193 §3's, taken over recorded values and
> never inferred; conditions 1, 2 and 6 are this decision's.** ADR-0193 §3's liveness condition
> is not condition 1 — that section's liveness is its own store's and §1 defines this one — and
> its fifth comparison, the external-content bar, is not a coverage condition here but a
> reachability condition on route (d) (§6), which is stricter rather than weaker. No component widens an authorization by folding case, by matching a domain, by
> treating an account member as covering a recipient member or the reverse, by treating a
> row's larger destination set as covering a request's under any relation other than
> membership, or by re-canonicalising either side. **A canonicaliser is ADR-0148 §2's, at the
> seam, and there is not a second one here.**

> **Normative — the per-argument rule.** An argument of the request is **covered** where the
> row carries a member naming it and:
>
> - the member is **fixed**, and the **canonical JSON encoding** of the argument's value equals
>   the canonical JSON encoding of `fixed`, byte for byte — the encoding
>   `ActionRequest.parameters_digest` is taken over, so there is one canonical form in this
>   system and not a second; or
> - the member is **bounded**, and the argument satisfies the bound under §4's total,
>   fail-closed reading of that argument's value.
>
> **An argument the row names in no member is not covered**, and an argument the row names in a
> member whose comparison is **unproven** is not covered. There is no default, no
> wildcard, no "not mentioned therefore unconstrained" and no omission that reads as consent.

> **Normative.** **Coverage never widens what a declaration reaches and never lowers a
> threshold.** An `Authorization`'s only effect on an outcome is to discharge the
> recipient-authorisation ground of ADR-0148 §3's first clause and ADR-0148 §8's third clause,
> for a request it covers wholly. It does not widen `discloses`, does not raise or lower any
> ceiling ADR-0016 §3 states, does not satisfy ADR-0148 §8's third clause's second limb about
> the payload description, does not exempt a call from any other floor a policy owes, never
> converts a `DENY` into anything, and never affects a request it does not cover. That is
> ADR-0193 §3's clause read onto this row, and it is read whole.

> **Normative.** **ADR-0021 §5's monotonicity obligation is unchanged and is not stated over
> this.** An authorization is *"an input the policy was given, not a severity axis"*, so
> monotonicity continues to compare requests equal in every other respect including that one,
> **with the records in the store held equal**.

> **Normative.** **A resolved result reference is compared over its resolved value, exactly as
> a literal is, and its origin is no further input to the ruling** — the question ADR-0253 §6
> and §11 push here by name. ADR-0253 §6 places the resolution *"before the `ActionRequest` for
> a step is built"* and states the consequence: *"a value a tool produced is in the arguments
> the policy rules on, in the digest ADR-0021 §1 pins … **No value a tool produced is ever
> authorised unseen.**"* So the comparison needs nothing new and reads nothing about where the
> value came from. **The negative arm is what makes that safe**: a value a tool produced can
> **satisfy** a bound the user set and can never **supply** one — no coverage member, no
> destination, no expiry and no goal is ever derived from a step's output — so a hostile
> upstream can at most produce a value the user's own bound already permits.

> **Normative.** **`CarriedProvenance.planned_with_external_content` is not widened here
> either.** ADR-0253 §6 refuses to read a resolved reference into it and this decision adds no
> second reading. §6 of that ADR and ADR-0181 §2's marked limit bind entire.

**One canonical JSON encoding, and the reason is #1548's and ADR-0150's at once.** A fixed-value
comparison written by hand would be a second canonicalisation of a payload, and two
canonicalisations that disagree produce a false mismatch at one end and a false match at the
other — which is `ActionRequest.parameters_digest`'s own stated reason for computing the form
*"**here** rather than supplied by a caller … a canonicalisation per caller, and two that
disagreed would produce a false mismatch at execution — which reads as an attack rather than as
a bug."* Using the encoding the digest is already taken over means the coverage comparison and
the binding comparison cannot come apart.

### 4. Reading an argument for a bound: total, and fail-closed at every step

> **Normative — `MONEY`.** The argument satisfies a `MONEY` bound only where **all** hold: the
> argument's value is a JSON **string** that `Decimal` accepts, or a JSON **integer**; the
> resulting `Decimal` is finite and not negative; it is less than or equal to `maximum` and,
> where a `minimum` is carried, greater than or equal to it; **and the request carries, at the
> bound's `currency_argument`, a JSON string equal to the bound's `currency` byte for byte**.
> The last conjunct is stated over the **concrete request** rather than over the row, so a row
> whose currency member says one thing and whose request says another covers nothing rather
> than covering the wrong amount of the wrong money; and a request carrying no value at that key
> is **not covered**. **A JSON floating-point value
> never satisfies a `MONEY` bound.** A binary float is not a price, and comparing one against a
> decimal bound is precisely the unproven comparison ADR-0148 §2 refuses by default: the answer
> is not to round, to quantise or to pick a tolerance, it is to refuse and ask.

> **Normative — `PERIOD`.** The argument satisfies a `PERIOD` bound only where its value is a
> JSON **string** that parses as **either** an RFC 3339 date-time carrying an offset, **or** a
> calendar date, and the instant it denotes lies in `[starts_at, ends_at)`. A calendar date
> denotes the **start of that day in the bound's own `timezone`**, and the zone is read off the
> bound rather than off `Settings`, so the comparison is over two recorded values and reads no
> configuration at the moment it is taken — ADR-0247 §2's posture for a policy, kept. **A
> date-time carrying no offset never satisfies a `PERIOD` bound**: a naive instant is an
> unproven comparison and there is no zone this system is entitled to supply for it at ruling
> time.

> **Normative — `TERMS`.** The argument satisfies a `TERMS` bound only where its value is a
> JSON **string** and equals a member of `terms` by **equality of the stored characters**. No
> fold, no strip, no case-insensitive match, no prefix and no substring.

> **Normative.** **Every reading above is total and every failure of it is a refusal to
> cover**, never an exception out of `decide`, never a `DENY`, and never a value substituted,
> coerced, clamped, defaulted or repaired into range. A request whose argument the reading
> refuses is a request the authorization does not cover, and the ruling is the one the policy's
> table reached without it — which for a transmitting tool is `CONFIRM`, and the user is asked.

> **Normative.** **No reading consults a schema to decide what an argument means, and there is
> no exception.** Every fact a comparison needs is on the row or in the request: which key holds
> an amount, which key holds its currency, which zone a date is read in, which strings a term
> may take. ADR-0145 §1's schema check runs at construction over the arguments and decides
> whether the call is well-formed; it decides nothing about coverage, and no lane reads a
> `parameters_schema` keyword to establish an association this decision requires a row to
> name.

### 5. A correction supersedes, and the record it leaves covers the whole request

> **Normative.** **A later act of one goal supersedes rather than composes.** Where a live
> record of a goal already carries a member for an argument and the user's later words replace
> it, `orchestration` writes a superseding record under §1's path (ii): the replaced member
> takes its value and its basis from the new act, **every other member is carried forward byte
> for byte with the basis it already had**, and the superseded record stops being live in the
> same act. The result is **one** record that covers the whole request.

> **Normative.** **The user is not asked to repeat what they have just said.** Path (ii)
> requires no confirmation, because the values it carries forward were confirmed once and the
> value it replaces is the user's own recorded words about an argument the earlier act already
> named. That is the owner's direction implemented: *"A clear later instruction such as 'make
> it Sunday' can supply authorization for that change; do not automatically ask the user to
> repeat it."*

> **Normative.** **A correction that would widen takes path (i) and asks.** An instruction
> raising a ceiling, adding a term, lengthening a period, naming a destination the row does not
> carry, or naming an argument no member covers is **not** a correction path (ii) can write:
> the store refuses it, no row is written, and the concrete action reaches no route (d) and is
> confirmed. That is the owner's *"Ask only when the concrete action introduces something not
> already covered, such as additional costs or materially different terms"*, and it is that
> sentence read as a refusal at the write rather than as advice at the prompt.

> **Normative — and a widening the user then confirms is established, by path (i) carrying
> `supersedes`.** The confirmation that asks about the wider action proposes a row naming the
> live row in `supersedes`; approving it settles the new row `ESTABLISHED` and the old one
> `SUPERSEDED` **in one write**, so the uniqueness rule (§1) is satisfied without a separate
> retirement step and there is never an instant in which two rows of one goal and declaration
> are both established. **Declining it settles the new row `DECLINED` and leaves the old one
> exactly as it was** — a refused widening is not a revocation of what the user already
> authorised.

> **Normative.** **A path-(ii) correction never extends authority in time.** `expires_at` is
> transcribed from the row it supersedes (§1, §12), so a chain of corrections expires when the
> first act's authority would have expired. **No sequence of corrections outlives the
> confirmation that began it.** A path-(i) supersession computes a fresh `expires_at`, because
> the user was asked again and the instant is in front of them (§11).

> **Normative.** **No record of one goal is superseded by, or contributes to, a request of
> another**, and no implementation composes coverage across goals, across conversations, across
> users or across declarations. §1's `goal` field and §3's `tool` comparison are each
> independently sufficient to refuse that, and both are stated so that removing one does not
> open it.

> **Normative.** **`PermissionRuling.authorised_by` names the one record coverage was taken
> over**, and there is never a second contributor for it to omit. §7 states what the recorded
> row then does and does not assert.

**This is the owner's *"make it Sunday"* case, and superseding is what makes it safe as well as
quiet.** The first act fixed the site, the party size and the terms and bounded the price; the
correction is itself a recorded act and replaces the date alone. The record it leaves carries
the new date with the correction's basis and every other member with the first act's, so the
policy compares one record, the trail resolves one record, and **a revocation of the authority
behind any argument at all is a revocation of the record the ruling would cite**. A Sunday rate
above the bound, or a term outside the named set, is covered by that record either — it asks,
on that ground and that ground alone.

**Composing at ruling time was the first design and it was wrong, for a reason worth keeping.**
If several records contribute and the ruling names one, then revoking a *contributing* record
that is not the named one leaves every check the trail can make passing — §13's promise that
revocation bites again at `record`'s resolution read would be true of one record and false of
the others, and an auditor reading the row would see an authority that no longer stands behind
half the call. Carrying every contributor on the ruling would put an unbounded tuple and an
unbounded set of digests on a type ADR-0193 §6 deliberately kept to one pointer and one
fingerprint. Superseding moves the composition to the moment of the act, where the store can
verify the transcription and where one record is the honest answer to *"what authorised this"*.
It is ADR-0249 §7's own construction for an interpretation revision — *"A revision states its
elements in full, and omission is removal … a patch would make two revisions unreadable without
replaying every one between them"* — applied to an authority rather than to an understanding.

### 6. Route (d) on ADR-0148 §3, and the five conditions it does not relax

> **Normative.** **ADR-0148 §3's first clause gains a fourth route.** §3 rules that an `ALLOW`
> on an egress request requires every member of its canonical destination set to be covered by
> **(a)** a recorded resolution of a `CONFIRM` about this request or **(b)** a standing user
> policy established by a recorded act of the user; ADR-0247 §2 added **(c)**, the request is a
> `WEB_SEARCH` at the configured provider. **This adds (d): a live `Authorization` of the
> request's own goal covers the request under §3.** ADR-0148 §3's second clause binds entire in
> every limb — a tool's own declaration, the scope or audience of a credential, a configured
> base URL or host, an allowlist the system assembled, a recipient appearing in a prior call, a
> destination extracted from a span — and route (d) is none of them: it is *"a recorded act of
> the user"* in limb (b)'s own words, scoped to a goal and to argument values rather than to a
> destination set.

> **Normative.** **ADR-0148 §1 is relied on exactly as written and nothing about it moves.**
> The request is still built **complete** before the ruling; *"Nothing in it is resolved,
> canonicalised, defaulted, expanded or added after `ActionPolicy.decide` has been reached"*
> binds this route as it binds every other; and a request that cannot be completed is still
> refused **before** the ruling with no ruling sought. Route (d) reads the completed request
> and changes nothing about how it was built.

> **Normative.** `ActionRequest` gains **one** field, **`goal: Identifier | None`, defaulting
> to `None`**, naming the goal the step this request performs belongs to. **`orchestration`
> sets it** from the plan the execution names; no policy, no seam, no interface adapter and no
> model output writes it. **A request carrying `None` reaches route (d) in no case** — the
> fail-closed direction, and the same shape ADR-0021 §3 gives a policy with no authorisation
> source. This is a **BREAKING** contract change to a `core` type under golden rule 5 and is
> flagged as one.

> **Normative.** `ThresholdActionPolicy` gains **one constructor argument**, a
> `GoalAuthorizations` (§15), beside the `RecipientGrants` and the `ConfiguredSearchDestination`
> it already takes. **A policy constructed without one takes route (d) as unreachable for every
> request** and leaves `authorised_by` and `authorised_goal` unset, which is ADR-0021 §3's rule
> unamended in this limb. **ADR-0247 §2's supersession of that rule is not inherited**: it is
> stated *"in the limb that reaches a request carrying `closed_loop`, and in no other"*, and
> route (d) is not that limb.

> **Normative — route (d) is reachable on `_only_the_disclosure_floor`'s five conditions and
> relaxes none of them.** Concretely, and each is stated because a reader could otherwise
> expect the route (c) treatment:
>
> 1. the policy holds a `GoalAuthorizations`;
> 2. the request is an egress call — its `egress_binding` is not `None`;
> 3. its binding does **not** carry `planned_with_external_content`. **ADR-0193 §4's floor and
>    ADR-0181 §5's clause bind route (d) entire, unrelaxed**;
> 4. its binding's `coverage` is `SpanCoverage.NOT_COVERED`. **ADR-0233 §9's second clause
>    binds route (d) entire, unrelaxed**;
> 5. the outcome the table reached is `CONFIRM` and the **only** clause that fired is the
>    disclosure floor. An `UNKNOWN` cost still draws `CONFIRM`; so does a `risk_level` or a
>    `reversibility` at the policy's own threshold; and a threshold `DENY` still stands and
>    reaches no route at all.

> **Normative — the order of the four routes is total, and each answers before the next seam is
> consulted.** Route (a) is `resolve`'s and is reached by a different method. Within `decide`:
> **route (c) first** (ADR-0247 §2, unmoved), then **route (d)**, then **route (b)**. Where
> route (d) answers, `RecipientGrants.covering` is called **zero** times; where route (c)
> answers, neither of the other two seams is consulted. **At most one durable read per seam per
> ruling and never a cached answer**, which is ADR-0193 §7's rule read onto the second seam.

> **Normative — why (d) precedes (b), stated so it is a decision and not an accident.** A
> record that covers a request under both routes is a record the user made about **this goal**,
> with a basis naming the turn and the span, an expiry measured in hours and a coverage that
> names the arguments; the grant that would also cover it is a standing preference about a
> destination set, made about something else, with no basis and a longer life. Citing the
> narrower and better-evidenced authority records more and asserts less. **Neither route is
> made reachable or unreachable by the order**: a request route (b) covers and route (d) does
> not is still route (b)'s, and the reverse.

> **Normative.** **Route (d) is an egress route and opens nothing else.** ADR-0021 §6's
> standing grants *"for other actions"* stay deferred and unnarrowed: a decision carrying no
> `egress_binding` falls outside every clause of this ADR rather than needing an exception
> inside it, and the ADR that opens that space states its own scope beside this one. §18 names
> it with what fires it.

**What genuinely widens, flagged as such and not smuggled.** ADR-0193 §3 states five
comparisons, all over a canonical **destination set**, the declaration and the account. §3
above keeps the three that transfer and adds a kind of comparison the corpus has not had
before — over an **argument value**. That is a
real extension of what a standing authority may decide, and the three things that keep it
fail-closed are stated rather than assumed: the reading of every argument is total and refuses
what it cannot prove (§4); the route relaxes none of the floors route (c) relaxes (above); and
the interpretation that produced a bound may narrow what the act covers and may never widen it
(§8).

**Route (d) is not reachable for the workflow's search-shaped steps, and that is a limitation
rather than an oversight.** Conditions 3 and 4 mean a request whose arguments were composed over
a supply carrying a record marked as resting on recorded external content, or over covered
content, reaches no route (d) and the user is asked — even where an authorization covers every
argument. ADR-0233 §9's second clause is absolute about that class — *"**no** standing
authorisation, standing policy, standing recipient grant, configuration, connected account, tool
declaration or approved payload description covers such a call, **ever**"* — and ADR-0238 §7 and
ADR-0247 §3 opened the **one** exception this corpus admits, for the configured search provider
and nothing else. Opening a second is a decision with its own argument and its own arms, and it
is not this one. §18 books it with what fires it.

### 7. The discriminator, and what the trail checks and cannot check

> **Normative.** `PermissionRuling` gains **one** field, **`authorised_goal: Identifier | None`,
> defaulting to `None`**, carrying the `goal` of the `Authorization` a route-(d) `ALLOW` rests
> on. A **validator** refuses it where `authorised_by` is unset — the same shape and the same
> reason as `authorised_subject`'s refusal (ADR-0193 §6): a scope for an authorisation the row
> names none of is incoherent. It is set **only** on a route-(d) `ALLOW`, and a policy sets it
> **only** to the `goal` of the record `covering` returned, read off that record and carried
> from nowhere else.

> **Normative — the four routes are told apart from the row alone, and the partition is
> total.** For an `ALLOW`:
>
> - **route (a)** — `resolves` set, `authorised_by` equal to it;
> - **route (b)** — `resolves` unset, `authorised_by` set, `authorised_subject` set,
>   `authorised_goal` **unset**;
> - **route (c)** — `resolves` unset, `authorised_by` set, `authorised_subject` unset,
>   `authorised_goal` unset;
> - **route (d)** — `resolves` unset, `authorised_by` set, `authorised_subject` set,
>   `authorised_goal` **set**;
>
> and an `ALLOW` with `authorised_by` unset is the policy's own rules (ADR-0193 §11's third
> state). **This narrows ADR-0247 §2's discriminator in its route-(b) limb alone, by one
> conjunct, and breaks none of it**: that section's *"route (b) where `authorised_subject` is
> set and route (c) where it is not"* becomes route (b) where the digest is set **and
> `authorised_goal` is unset**, and route (c)'s digest-free limb is untouched. It reads
> **nothing but the row**, needs **no store read**, and rests on **no assumption that two
> identifier namespaces are disjoint** — the two defects ADR-0247 §2 states its own
> discriminator against.

> **Normative.** **A route-(d) `ALLOW` carries a digest, and it is the record's coverage
> fingerprint.** `PermissionRuling.authorised_subject` on a route-(d) row is a `Sha256Hex` over
> the canonical form of the `Authorization`'s `goal`, `tool`, `account`, `destinations` and
> `coverage` — its **subject**, in `RecipientGrant.subject_digest`'s sense and derived by the
> same discipline: a non-field member of the type, computed from the record and never supplied.
> ADR-0004 §7's minimisation is served exactly as ADR-0193 §6 serves it: sixty-four characters
> whatever the record's size, and **nothing about the authorization travels by value** — not
> the coverage, not the declaration, not the account, not the basis, not the expiry.

> **Normative.** `AuditTrail` implementations are constructed with an
> **`AuthorizationResolution`** (§15) beside the `RecipientGrantResolution` they already take,
> and `record` resolves a route-(d) pointer against it. The trail therefore holds a **read and
> nothing else**: it cannot append an authorization, revoke one, enumerate the user's goals or
> erase the store. `ActionPolicy` is unchanged in signature, `AuditTrail`'s own Protocol gains
> no member, no argument and no widened return, and what ADR-0021 §4 gains is an invariant.

> **Normative — `AuditTrail.record` refuses a route-(d) row unless all eight hold.**
> `resolve(authorised_by)` returns a row; that row's `disposition` is **`ESTABLISHED`** — the
> existence, the kind, the unrevoked, the unsuperseded and the answered check at once, since
> every other disposition is retired and none of them is live; that row's `settled_at` is **at
> or before** the decision's `decided_at`; its `expires_at` is **strictly after** the decision's
> `decided_at`; its `ToolDefinition` equals the decision's `tool` **by value**; its
> `BoundAccount` equals the decision's binding's `account` **by value, both facts and not
> one**; its `destinations` **contain every member** of the decision's binding's canonical
> destination set, compared as `CanonicalDestination` compares — every field, never across
> protocols; its `goal` equals the ruling's `authorised_goal`; and the ruling's
> `authorised_subject` equals that row's subject digest, **recomputed by `record` over the row
> the store returned**. Seven of the eight are ADR-0193 §6's, adopted with its reasoning entire
> — including that equality is permitted at the lower end and that what is refused there is a
> **backdated** authority, and including that the digest *"is never taken on the decision's
> word"*. `record` reads **no clock**: both ends are decided against the decision's own
> `decided_at`.

> **Normative — the account and destination checks are taken because both values are on the
> row and on the decision, and omitting them would leave a gap nothing else closes.** A faulty
> policy citing an established authorization for one recipient while ruling on a send to another
> through the same declaration would otherwise pass every other check — the pointer, the goal,
> the instants and the recomputed digest all hold. This is not the payload comparison the clause
> below says the trail cannot take: it needs no extra data, no seam and no arguments, only the
> binding the decision already carries. **A lane that skipped either has breached this clause.**

> **Normative.** **`settled_at` is the instant compared and `proposed_at` is not.** A row is
> proposed before the user answers and authorises nothing until they do, so the instant a
> decision must not predate is the instant the authority came into being. A row whose
> `settled_at` is after the ruling was taken is the **backdated** case ADR-0193 §6 refuses, one
> field over.

> **Normative — the trail asserts what it can see, and the policy asserts the rest.** What
> remains outside the eight checks is **one** comparison and one join, and both are named. The
> trail **cannot** re-take the per-argument comparison and no lane gives it a way to: a
> `PermissionDecision` carries `parameters_digest` and **not** `parameters`, deliberately —
> *"a durable record holding them verbatim would make the audit trail a second copy of the
> user's most sensitive material"* — so the arguments the coverage rule is stated over are not
> in the trail's hand and putting them there would breach ADR-0021 §1 and ADR-0004 §7 at once.
> It **cannot** check that the request belonged to the goal the ruling names either, because
> `ActionRequest.goal` is not transcribed onto the decision (§15). Both limits are stated here
> rather than implied, exactly as ADR-0247 §2 states its own — *"what the trail can check about
> route (c) is that the pointer matches the binding, and not that any record authorises it.
> That is less than route (b) offers, and it is said rather than implied."* **Neither component
> is offered the other's job**, and a lane that let the policy skip the comparison has breached
> this clause as surely as one that gave the trail the arguments.

> **Normative.** **No stored row is revalidated, rewritten or re-derived.**
> `AuditTrail.record`'s invariants are write-path checks. A decision written before this
> decision keeps its `authorised_by`, its digest and its recorded meaning; no read path applies
> route (d)'s checks to it; and **no row predating this decision can be classified as route
> (d)**, because `authorised_goal` did not exist to be set. ADR-0193 §11's reserved
> digest-free pointer and ADR-0247 §2's exclusion of it are untouched.

### 8. The basis: the act, the span, and the interpretation — all three kept

> **Normative.** `core/types.py` gains **`AuthorizationBasis`**, a frozen model with
> `extra="forbid"` whose fields are exactly: **`act`**, an `Identifier` — the id of the recorded
> conversation turn the coverage member rests on; **`span`**, a `NonBlankEncodableText` — the
> user's own words **inside that turn's stored utterance**; and **`resolution`**, a
> **`ValueResolution`**, required. Every `CoverageMember` carries one (§2), and a member
> without one is not constructible.

> **Normative.** `core/types.py` gains **`ValueResolution`**, a frozen model with
> `extra="forbid"` carrying `rule`, a **`ResolutionRule`**, and the argument that rule takes.
> **`ResolutionRule` is a `StrEnum` valued by lower-cased member name and closed at exactly
> three members**: `AS_STATED`, `DATE_FROM_CONTEXT` and `FROM_SHOWN_RECORD`. A **model
> validator** admits exactly three shapes and refuses every other, which is `GoalElement`'s own
> construction (ADR-0249 §1) applied here for its reason — *"The type is what expresses the
> correspondence rather than a rule to remember"*:
>
> - **`AS_STATED`** — neither argument. The value is the span read as itself, normalised by
>   nothing.
> - **`DATE_FROM_CONTEXT`** — `now`, a `UtcInstant`, and `timezone`, an IANA zone name, **both
>   required and neither absent**. These are the inputs the resolution used: `CurrentContext.now`
>   as that turn read it, and the configured zone as it then stood.
> - **`FROM_SHOWN_RECORD`** — `record`, an `Identifier`, required. The id of a record shown to
>   the user on that turn, which the reference resolved to.

> **Normative.** **`span` is a span of that turn's own `TurnResult.utterance`, and it is checked
> against it at construction.** ADR-0248 §1 puts the user's words on the turn — *"the user's own
> words on the pass, as the pass received them, unrewritten, unrendered and uninterpreted"* —
> and makes it *"computed, derived, reconstructed or defaulted nowhere else"*. A span that is
> not a span of that value **refuses the construction**, exactly as ADR-0249 §7 refuses a
> `USER_STATED` ground whose span is not one.

> **Normative.** **Both halves survive, and neither is derivable from the other.** An auditor
> reading a coverage member sees the words the user actually said and the value the system took
> them to mean, with the rule and the inputs that took it. That answers the owner's
> clarification directly: a resolved value need not appear literally in the message, and the
> message is not thereby lost.

> **Normative.** **A `PERIOD` bound's `timezone` and a `DATE_FROM_CONTEXT` resolution's are
> two facts and neither is derived from the other.** The bound's is the zone §4's comparison
> reads a calendar-date argument in; the resolution's is the zone the act's span was resolved
> under. They are ordinarily equal and nothing requires them to be: a configuration changed
> after the act leaves the record saying what it said, which is ADR-0193 §9's prospectivity in
> the one place a zone could otherwise be re-read.

> **Normative.** **The basis is per member and never per record.** Two members of one record
> may name two different acts, which is how a correction supplies one argument while the first
> act's members are carried forward beside it (§5) — and it is why `Authorization` carries no
> basis of its own.

### 9. Three independent clauses, so that defeating one does not defeat the others

> **Normative — (i) the authority is the act, and the interpretation is never the authority.**
> An `Authorization` is constructible **only** with a basis naming a recorded turn and a span
> inside that turn's stored utterance, on **every** coverage member. **There is no code path
> that builds one from a model output alone**, no constructor, factory, migration, import,
> replay or test helper that admits a member with no basis, and no member whose `act` names
> something other than a recorded turn. ADR-0021 §1's separation is the precedent — the absence
> of a field through which a policy could substitute its subject is *"the security property, not
> an economy"* — and this is that move applied to the authority's source rather than to its
> subject.

> **Normative — (ii) an interpretation fills a slot the act opened and never opens one.** A
> resolution turns a span into a value **for an argument the act's own words bear on**. It may
> not add a member for an argument the act never mentioned, raise a `maximum`, lower a
> `minimum`, add a member to `terms`, widen `destinations`, change `account` or `tool`, or move
> `expires_at`. **The interpretation narrows what the act covers and can never widen it**, and
> §1's path (ii) is where that becomes a construction refusal rather than a rule a lane
> remembers: a superseding record that would do any of those is not constructible. That
> is #2096 item 8's ruled asymmetry — *"A model is a safe denier and an unsafe allower, because
> of who rehearses against it: an attacker who beats a deny-only layer gains a deny"* — applied
> to resolution, and it is ADR-0249 §7's line read one stage on: *"A model may never clear a
> permission, a coverage test, a prerequisite or a dependency."*

> **Normative — (iii) material ambiguity asks, and so does a consequence outside scope.** Where
> the span admits more than one admissible value the resolution is **not taken** and no member
> is minted from it: the user is asked, by **ADR-0250 §6's three conditions and no fewer** — the
> planner reported the interpretation ambiguous, the subject is material by §6's code test, and
> no evidence or established preference resolved it. And where the concrete action introduces
> what the coverage does not hold — a cost above a `maximum`, a term outside a named set, a
> destination outside the set, an argument no member names — **the request reaches no route (d)
> and the user is asked**, whatever the interpretation said.

> **Normative.** **No model output clears a coverage test, and none mints a member.** A planner
> envelope that comes back carrying an authorization, a coverage member, a bound, a basis, an
> expiry or a goal scope has those values **discarded silently** — not an error, not a park, not
> a degradation of the turn — which is ADR-0249 §6's posture for a phase and ADR-0228 §5's for a
> `supersedes`, adopted here for its stated reason: a value a model wrote into a durable audit
> chain is unprovenanced.

**The three are independent by construction, and that is the point of stating them as three.**
Defeating (i) needs a code path that does not exist; defeating (ii) needs a widening a
constructor refuses; defeating (iii) needs both a model that reports no ambiguity and a concrete
action already inside the bound — in which case nothing was widened. A single argument covering
all three would be one thing to be wrong about.

### 10. Resolution and normalisation: what may be resolved, and against what

> **Normative.** **Exactly three resolutions exist and there is no fourth**, each named by a
> `ResolutionRule` member (§8) and each a total function of recorded inputs:
>
> - **A date or a period from the turn's own context.** `CurrentContext.now` as that turn read
>   it and the configured IANA zone, both recorded on the resolution. *"Sunday"* becomes a
>   half-open interval in that zone; *"that weekend"* becomes one; and the recorded `now` is
>   what makes the working checkable afterwards.
> - **A reference to a record shown on that turn.** *"the usual campsite"*, *"the second one"*
>   — resolved to the id of a record the loop itself put in front of the user on that turn, and
>   recorded as that id. **A record whose id resolves in no store is not a resolution here**,
>   exactly as ADR-0249 §7 drops a `FROM_EVIDENCE` ground naming a search-minted record, on
>   ADR-0231 §16's ruling that such an id *"resolves in no store"*.
> - **The span as stated.** A figure the user wrote, a term the user named. Normalised by
>   nothing, which is ADR-0248 §1's discipline: the pass strips once and nothing re-normalises.
>
> **No resolution reads memory, a preference, a prior goal, a prior turn's supply, or a model's
> recollection.** A resolution whose inputs are not on the turn it names is not one.

> **Normative.** **Normalisation is part of the resolution and is recorded with it, never
> applied at the comparison.** §4's readings do not fold, strip, round, quantise, re-zone or
> repair an argument; whatever normalising an act needed happened once, when the member was
> minted, and the record carries both the span and the result. A second normalisation at
> comparison time would be the second shape of one fact ADR-0150 is named after.

> **Normative.** **A resolution the loop cannot take is not taken, and no member is minted.**
> Where the zone is unset, where `now` is unreadable, where the reference names nothing shown,
> or where the span admits two values, the outcome is the same: no member, and the argument is
> uncovered, and the user is asked about the concrete action when it is dispatched. **Nothing
> falls back to a default, to the previous turn's value, or to the model's own reading.**

### 11. What the user is shown, and what the surfaces render afterwards

> **Normative.** **What is put to the user for a `CONFIRM` whose answer would establish an
> `Authorization` names, in addition to everything ADR-0148 §8's fourth clause already
> requires** — the connected account's identity, the canonical destination set in both forms,
> and the payload description — **every fixed value and every bound the answer would establish,
> and the instant it would expire.** Concretely: the entity the act fixes, the dates or the
> period, the price as a figure or as a bounded limit with its currency, the terms, and the
> expiry. **A confirmation that establishes a bound without naming it is not a confirmation of
> that bound**, which is ADR-0148 §8's fourth clause's own construction — *"A confirmation that
> names the tool and not the recipients is not a confirmation of an egress call"* — read onto
> what the answer would make standing.

> **Normative — the projection is rendered from the proposed row and is not recomputed.** The
> `Authorization` is written `PROPOSED` before the question is put (§1), so what the user is
> shown is a rendering of a durable row: the same coverage, the same bounds and the same
> `expires_at` the row carries. **A restart between the question and the answer recovers the
> row and renders the same projection**, which is ADR-0052 §1's recovery reading a durable
> record rather than reconstructing a proposal nobody stored, and it is why §1 writes the row
> first rather than at the answer.

> **Normative — the carrier, because `Confirmation` forbids extra fields.** `core/types.py`
> gains **`ConfirmationAuthorization`**, a frozen model with `extra="forbid"` carrying exactly
> `coverage`, a non-empty `tuple[ConfirmationCoverage, ...]`, and `expires_at`, a `UtcInstant`;
> and **`ConfirmationCoverage`**, a frozen model carrying exactly `argument`, an
> `EncodableText`, and one of `fixed`, a `FrozenJsonValue | None`, or `bound`, a `ValueBound |
> None`, under `CoverageMember`'s own two-shape validator. `Confirmation` gains **one** member,
> **`authorization: ConfirmationAuthorization | None`, required with no default**, and it is
> **absent** — not empty — on a `CONFIRM` whose answer would establish nothing.
>
> **One nested value rather than several flat members**, which is `ConfirmationEgress`'s own
> construction and its reason: *"four independent optional members admit fifteen partial states
> … One value is either whole or absent."* **Absence is the discriminator** in `egress`'s and
> `read`'s shape: what it states is that **answering this question would establish a standing
> authority**, and nothing more — no lane reads its absence as a warrant that the call
> establishes nothing else, and a surface that cannot render it may refuse *that* confirmation
> rather than every confirmation (ADR-0178 §4).
>
> **The engine assembles it**, because an adapter may read neither the audit trail nor a
> `PermissionDecision` (ADR-0042 §6), and it carries **the recorded values by transcription and
> not a second derivation of them** (ADR-0178 §5, ADR-0150 §10). It carries **no** goal id, no
> authorization id, no `BoundAccount`, no connection reference, no `SecretName` and no
> transport endpoint. **`ConfirmationEgress` is untouched** — ADR-0178 §10's roster test over
> *that* type keeps both its subject and its entry count — and the new types get a roster test
> of their own in its shape (§20).
>
> **A client reading it can tell a fixed value from a bound**, which is the whole reason it is a
> projection of the coverage rather than the concrete parameters: a confirmation showing a price
> of forty-five pounds and nothing else cannot say whether answering fixes forty-five or permits
> sixty.

> **Normative.** **It names no identifier.** Not the goal's id, not the authorization's id, not
> the connection reference, not a credential slot and not a `Settings` field.
> `BoundAccount.reference` is *"never shown to the user"* (ADR-0148 §6, §8) and this decision
> does not move that; ADR-0193 §11's bar on what an audit surface renders binds here entire;
> and ADR-0228 §8's namer rule binds every prompt this decision builds.

> **Normative.** **The surfaces this decision owes are a listing and a revocation**, and they
> render, per record: the goal's **statement** (never its id), the declaration's human-readable
> name and description, each coverage member as *this argument is fixed at that value* or *this
> argument is bounded by that limit* **together with the span the user said**, the expiry, and
> whether the row is still live or has lapsed. It renders a `PROPOSED` row not at all — that is
> the confirmation's question and not an authority the user holds — and §16's `standing(goal)`
> is what makes that a fact about the read rather than a filter a renderer applies. They render **no** internal identifier, **no** subject digest and
> **no** account reference. A revocation names the record by the same rendering the listing
> gave it.

> **Normative.** **The listing renders the span; `export` carries the basis whole.** A
> surface shows the user's own words because that is what they can recognise; the resolution —
> the rule, the `now` it read, the zone, the record it resolved to — is provenance for an
> auditor and reaches them through `export` (§16), not through a rendering. **No surface
> renders a resolution as a justification, a confidence, an assurance or a reason to trust the
> value more**, which is ADR-0193 §11's opaque-digest discipline read onto a second field.

> **Normative.** **A decision surface asserts exactly what the row says and nothing more.** A
> route-(d) row is ADR-0193 §11's **second** state — *"a standing authorisation this row
> names"* — and every clause of §11 binds it: no surface states or implies that the named
> record exists, is held by the store, is live, is unrevoked, has not expired, was validated, or
> covers anything now; none decodes the digest, presents it as a verification or renders a
> route-(d) row as more trustworthy than a route-(a) row; and none renders the basis as an
> approval control, an assurance or a reason to suppress or reorder anything ADR-0186 §7
> requires. **What §11's second state now covers is two kinds of row rather than one**, and §17
> records that against it.

### 12. Expiry: justified, visible, with no disable spelling, and for this record alone

> **Normative.** **Every `Authorization` carries an `expires_at` and there is no spelling for
> one without it** — no null, no sentinel, no "forever" — and it is **strictly after**
> `proposed_at`, refused at construction otherwise. That is ADR-0193 §9's clause and its reason
> adopted whole: a record expiring at or before the instant it was proposed *"is a grant in
> shape and nothing in effect"*.

> **Normative.** `core.config.Settings` gains **exactly one field**,
> **`workflow_authorization_ttl: timedelta`**, required, defaulting to **PT12H**, and refused at
> load where it is zero or negative. **It admits no disable sentinel**, which is ADR-0244 §3's
> shape and its stated reason one record over: an authority nothing can free is a durable row
> that keeps authorising after everyone has forgotten it exists.

> **Normative — the expiry is computed once, when the row is proposed, and is never
> recomputed.** On path (i), `proposed_at` is the recorded `CONFIRM`'s `decided_at` and
> `expires_at` is that instant plus `workflow_authorization_ttl` as the deployment holds it at
> the moment of the write. **Both are durable before the user is shown anything**, so the
> instant §11 names in the prompt is read off the row and is the instant the row carries — a
> restart between the question and the answer recovers it, and a change to
> `workflow_authorization_ttl` in that interval **does not move it**. This is ADR-0244 §3's
> clause one record over: *"both computed from it, once, at the instant the park is written"*.
> **No lane recomputes either instant at the answer**, and a changed setting is prospective on
> ADR-0247 §8(b)'s shape — it governs the next row proposed and no row already written.

> **Normative — an answer arriving at or after `expires_at` establishes nothing.** The row is
> settled **`EXPIRED`** (§1), not `ESTABLISHED`. The `CONFIRM` may still be resolved and the
> concrete call may still be authorised by ADR-0148 §3's route (a) — a decision of the user
> about *that* request — but **no standing authority comes into being**. The user is asked
> again the next time the goal needs one, which is the fail-closed direction and the only one
> that keeps the displayed instant true.

> **Normative — on path (ii) the expiry is transcribed and only the new row's own instants
> move.** A superseding row carries the superseded row's `expires_at` unchanged (§1, §5); its
> `proposed_at` and `settled_at` are both the recorded turn the correction rode. A correction
> recorded at or after `expires_at` finds no live row to supersede and writes nothing.

> **Normative.** **The expiry is visible at the moment of the act and in every listing** (§11).
> That is the whole of decision 7's *"justified, visible"*: justified because it is stated with
> the act, and visible because the user reads it before answering and can read it again
> afterwards.

> **Normative — the justification, stated in the ADR so a lane need not invent one.** An
> `Authorization` bounds **argument values of a goal in progress**. A goal in progress is
> measured in hours: the campsite is booked this afternoon or the plan is replanned. A standing
> recipient grant is a different thing — a preference about who the user is willing to reach,
> which they expressed once and expect to hold — and a configured provider is not a user act at
> all. **That difference is the reason the ceiling is short here and is not imposed there.**

> **Normative — decision 7's second sentence, as a negative clause naming both records.**
> **`RecipientGrant.expires_at` is untouched**: ADR-0193 §9's rule that *"The user chooses the
> instant in the establishing act"* stands, no `Settings` figure bounds it, and no clause of
> this decision shortens, defaults or re-computes one. **ADR-0247's configured-provider
> authority is untouched**: it has no record, no instant and no expiry, §8(b)'s prospectivity is
> its whole lifecycle, and nothing here gives it one. A lane that applied this ceiling to either
> has breached this clause.

> **Normative.** **No row is deleted** — not by expiry, not by a settlement, not by
> supersession, not by revocation, and by no operation but `clear` — so a user can see what they
> once authorised, what they declined and what lapsed, and `export` carries every row whatever
> its disposition. ADR-0193 §9's no-deletion clause, adopted.

### 13. The recheck at dispatch: `decide` is the recheck, and there is no cached verdict

> **Normative.** **The coverage comparison is taken at `ActionPolicy.decide`, on the concrete
> request, at every dispatch.** There is **no cached coverage verdict anywhere**: not on the
> step, not on the attempt, not on the plan, not on the execution, not in the policy and not in
> the store's answer. A verdict taken for one dispatch answers that dispatch and is discarded,
> which is ADR-0193 §7's rule for the grant seam read onto this one — an implementation reusing
> the last successful lookup *"would go on authorising sends after its authorisation stopped
> being checkable"*.

> **Normative.** **That comparison sits where ADR-0037 §2 already puts every pre-claim check**,
> at the runner, **before** the claim: *"decide → record → read back → claim"*, with the claim
> the executor's and the decision existing first. **No collaborator is added to
> `StepExecutor`** — ADR-0058's ruling that *"`StepExecutor` does not validate trail presence,
> and #259 is resolved as WONTFIX"* is untouched, its four-collaborator construction contract
> stands, and no lane gives it an `AuthorizationResolution` either.

> **Normative.** **`EgressBinder.rebind` is untouched and gains nothing.** ADR-0152 §7 takes
> from `approved` *"**exactly one** thing: each span's `provenance`"*, narrowed to two by
> ADR-0181 §3, and **no lane makes coverage a third**. The coverage comparison is the policy's
> and runs where the policy runs; `rebind` re-derives the binding and refuses what the approval
> did not cover, and the two checks sit beside each other rather than inside each other.

> **Normative.** **What a changed argument outside coverage does.** The request is rebuilt from
> the stored step and the resolved references (ADR-0253 §6), `decide` takes the comparison
> afresh, no route (d) is reached, and the ruling is what the table alone produced — `CONFIRM`
> for a transmitting tool. The step is committed `PENDING → AWAITING_APPROVAL` (ADR-0037 §4).
> **Nothing is dispatched, no claim is made, no effect occurs**, and the attempt's state is
> committed `AWAITING_AUTHORIZATION` (§14).

> **Normative.** **A revocation is prospective, and it bites twice.** It governs every
> `covering` read that begins after it is recorded, and it refuses the write of any route-(d)
> `ALLOW` whose resolution read inside `record` begins after it is recorded. **It retracts no
> decision already recorded and stops no request already claimed.** The residual window runs
> from `record`'s resolution read to the execution; it is not zero and no clause here rounds it
> to zero. **What happens to a call already in flight is A9's** and is not decided here — that
> is §H's boundary in the report's terms, and ADR-0193 §9's own refusal to claim a cross-store
> linearisation binds this decision in exactly the same words.

> **Normative — what "recheck authorization" means, discharging ADR-0250 §11.** That section
> states the answer *"before A4 and A6 land"* and reserves this half: *"A4 gives 'recheck' an
> evidence standing to read and **A6 gives it an authorization coverage to compare**; until then
> this clause is the whole of it."* It now compares: on a late answer the turn takes its own
> `Planner.plan` call as §11 already requires, and **each side-effecting step of the resulting
> plan has its coverage compared afresh at its own dispatch, against the records as they then
> stand, with nothing carried over from the paused turn.** A record that expired while the turn
> waited covers nothing, and the user is asked — **the age of the pause is authority for
> nothing**, which is §11's own sentence and is not weakened here.

> **Normative.** **Coverage and sufficiency are two tests and neither clears the other.** A
> dispatch needs both: ADR-0252 §6's four tests over the goal's evidence, and this decision's
> coverage. **Nothing here satisfies, weakens or substitutes for a `when` condition**, and
> nothing a plan declares clears an authorization — ADR-0253 §5's clause stated from the other
> side. Where either fails, the step is not dispatched, and which one failed is what the turn
> reports.

### 14. Validation in code: what phase 4 evaluates, what it adds, and where it leaves an attempt

> **Normative — what phase 4 does.** Before any step of a plan is dispatched, `orchestration`
> evaluates, deterministically and over stored values alone:
>
> 1. **Dependency validity** — `depends_on` over the stored steps' status and `verifies`
>    (ADR-0253 §1, §2). A reference that cannot resolve is `UNMET_DEPENDENCY` by that section's
>    six cases, *"and never a default, a blank, an omission or a `null`"*.
> 2. **Arguments present or referenced** — every argument the declaration's schema requires is
>    either a literal on the step or filled by a `ResultReference` (ADR-0253 §6). The schema
>    check itself is ADR-0145 §1's, at construction, and is neither moved nor duplicated.
> 3. **Sufficiency to act** — every member of the step's `when`, by ADR-0252 §6's four tests,
>    evaluated at the moment of dispatch.
> 4. **Coverage** — §3's comparison. **This is the one check this decision adds**; the other
>    three are other decisions' predicates evaluated here rather than restated here.
>
> **Phase 4 adds no fifth check of its own**, and a lane that adds one is changing this decision.

> **Normative — phase 4 adds no capability-vocabulary check, and ADR-0211 §6 is why.** That
> section rules that *"Neither the planner nor any later stage rejects a plan envelope, or a
> step of one, on the ground that its capability is outside the stated vocabulary. The
> implementing lane adds no post-parse vocabulary check anywhere"*. An emitted name is resolved
> exactly as it is today — through ADR-0053's alias layer at selection, and failing that through
> ADR-0037 §1's `NO_CAPABLE_TOOL`. **No clause of this decision, and no lane implementing it,
> adds such a check at phase 4 or anywhere else.**

> **Normative — phase 4 does not evaluate the world-spend ceiling, and nothing here is a second
> statement of it.** ADR-0194 §3 evaluates the admission *"inside `ToolInvoker.invoke`,
> **before** ADR-0192's claim is appended"*, after all three of ADR-0029 §2's checks, and §3
> forbids moving it: *"no lane may move the admission earlier to save a store read"*, and the
> enumeration *"stays exhaustive at three … no lane may read this clause as licence to add a
> fifth."* Phase 4 reads no total, holds no ledger and takes no admission.

> **Normative — a `MONEY` bound is not a spend ceiling and neither relaxes the other.**
> ADR-0194 §1 bounds *"the sum over tool invocations, across every registered tool"* over a
> calendar period, and §8 rules that **money a tool moves** is *"not decided and no ceiling here
> bounds it … the price of a flight lives in a call's parameters"*. A `MONEY` bound is a
> comparison over **that** figure — one argument of one call — and is not a per-tool,
> per-capability or per-protocol ceiling, which §8 also forbids adding. **The two compose by
> both binding and neither lifting the other**: a call inside its bound and over the ceiling is
> refused with `SpendCeilingError`, because *"nothing a turn can reach lifts a refusal"*; a call
> under the ceiling and outside its bound reaches no route (d) and is confirmed. **No lane reads
> a bound as raising, lowering, satisfying or standing in for a ceiling**, and none reads a
> ceiling as covering an argument.

> **Normative — the optional intent-match assessment is advisory in one direction only.** A
> phase-4 model call, where a deployment makes one, is given the plan and the `GoalBrief` and
> returns one member of a closed typed vocabulary. **It may raise a question and it may never
> clear a check, a prerequisite, a dependency, a sufficiency test or a coverage test.** Its
> verdict is a rationale-class value in ADR-0228 §11's sense — *"a model completion with no
> recorded origin"* — is never rendered as evidence, and can enable only a branch the plan
> declared before it ran. **This decision lands no such call, no vocabulary for it and no
> seam**; it fixes that if one is landed it is bound by the sentence above. ADR-0249 §7's
> asymmetry is the authority and it is not restated as a new rule.

> **Normative — where phase 4 leaves an attempt, over vocabularies that already exist.** No new
> enumeration is minted for this.
>
> - **Every check passed** — the attempt's `phase` advances to `AttemptPhase.EXECUTE` and its
>   `state` stays `RUNNING`.
> - **A step's arguments are not covered** — the attempt's `state` is committed
>   `AttemptState.AWAITING_AUTHORIZATION`, its `phase` stays `AUTHORIZE`, and the user is asked
>   through the ordinary `CONFIRM` park (ADR-0037 §4). **This decision is that member's first
>   producer.** No second asking mechanism is built.
> - **A deterministic check failed on the plan** — the attempt stays `RUNNING` and the plan is
>   replanned within the attempt, which consumes from the same `AttemptEffort` ledger
>   (ADR-0249 §5: *"no replan, branch, recovery or phase transition resets either"*). Where no
>   replan can satisfy the check, the attempt is left for A3's `BLOCKED` producer and this
>   decision writes none.

> **Normative — no phase moves backwards, and this decision mints no mechanism for one.**
> ADR-0249 §6 rules that within one attempt `phase` *"advances in that order and never moves
> backwards"*. So an attempt that has reached `EXECUTE` and finds an argument uncovered does
> **not** return to `AUTHORIZE`: it stops, its `state` becomes `AWAITING_AUTHORIZATION`, and the
> phase is left where it stood. **The mechanism by which an attempt re-enters an earlier phase
> is A7's** (ADR-0253 §9), and no clause here supplies one.

> **Normative — supplying an authorization opens no attempt.** ADR-0250 §12 closes the
> enumeration at exactly three user acts and rules that *"An answer to a clarification opens
> none"*; nothing here adds a fourth, which that section reserves to A3 and to acts of the
> investigation loop. An answer that establishes an `Authorization` **resumes the attempt it
> paused**: `commit_attempt` takes its `state` from `AWAITING_AUTHORIZATION` back to `RUNNING`
> at the phase it stood, which is ADR-0250 §11's shape for a clarification stated here for this
> state, and the new record's id is appended through `AttemptTransition.add_authorization_id`.

### 15. Writer clauses, gathered in one place

> **Normative.** **An `Authorization` is written and settled by `orchestration` and by nothing
> else** — proposed on §1's path (i) when a `CONFIRM` is put, settled by the answer to it, and
> written already `ESTABLISHED` on §1's path (ii) from a recorded turn whose span names an
> argument a live row already carries. No `ActionPolicy`, no `AuditTrail`, no interface
> adapter, no reader, no tool and no model output writes or settles one, and there is no third
> path. **The one exception is the expiry settlement**, which any read of an expired `PROPOSED`
> row performs inside the store (§1) — ADR-0244 §10's mechanism, which is the store settling a
> deadline it can see rather than a component deciding anything.

> **Normative.** **The policy sets `authorised_by`, `authorised_subject` and `authorised_goal`,
> and sets each only from the record `covering` returned.** It carries no value from a previous
> ruling, from a request, from a step, from a plan or from anywhere but that record, and it
> recomputes the digest from that record rather than reading one off anything.

> **Normative.** **`orchestration` sets `ActionRequest.goal`**, from the plan the execution
> names. No policy, no seam, no adapter and no model output writes it, and no component infers
> it at read time.

> **Normative.** **`orchestration` stamps the attempt's phase and state**, which is ADR-0249
> §6's writer clause binding entire and not restated as a new rule.

> **Normative.** **No model output writes any of the above, and none clears a coverage test.**
> A planner envelope carrying an authorization, a member, a bound, a basis, an expiry, a goal
> scope, an `authorised_by`, an `authorised_goal` or a phase has those values discarded silently
> (§9).

### 16. The `core` surface, the store, the wire, and the data rights

> **Normative — the `core` surface this decision adds, in full.** `core/types.py` gains
> `Authorization`, `CoverageMember`, `ValueBound`, `BoundKind`, `AuthorizationBasis`,
> `ValueResolution`, `ResolutionRule`, `AuthorizationDisposition`, `ConfirmationAuthorization`
> and `ConfirmationCoverage`;
> `PermissionRuling` gains `authorised_goal`; `ActionRequest` gains `goal`; `Confirmation`
> gains `authorization`. `core/protocols.py` gains **`GoalAuthorizations`**,
> **`AuthorizationResolution`** and **`GoalAuthorizationStore`**. `core/errors.py` gains
> **`AuthorizationError`**, the class a store fault raises. `core/config.py` gains
> `Settings.workflow_authorization_ttl` (§12) and no other field. **Every one of these is a BREAKING
> contract change under golden rule 5 and is flagged as one**; the ADR merges before anything
> implements against it (ADR-0015).

> **Normative — three faces, one object** (ADR-0193 §1's construction, and ADR-0097 §3's split
> behind it). `GoalAuthorizations` carries **`covering(request) -> Authorization | None`** and
> nothing else — the face a policy holds. `AuthorizationResolution` carries
> **`resolve(id) -> Authorization | None`** and nothing else — the face a trail holds, and it
> returns the row whatever its disposition, because the trail's own check reads that field (§7).
> `GoalAuthorizationStore` carries both plus **`record`**, **`settle`**, **`standing(goal)`**,
> **`recent`**, **`export`** and **`clear`** — the face a composition root holds. **Structural typing is what
> makes that sound**: a policy cannot name `record`, and a trail can name neither `record` nor
> `covering`, because `mypy --strict` runs over `src` and `tests` and those attributes are not
> on the annotated types.

> **Normative — the clock disciplines are ADR-0193 §9's and are not re-derived.** `covering` and
> **`covering` is the only query that evaluates liveness**, and it reads the clock **exactly
> once per call**, measuring every row it considers against that one instant — ADR-0193 §9's
> rule and its reason, since a query reading an advancing clock per row could answer over a set
> true at no real instant. It settles an expired `PROPOSED` row it reads (§1), and it is the
> **only** query that reads a clock. **`standing` evaluates no liveness, reports none and reads
> none**: it returns the rows, each carrying its own `expires_at`, and **the caller compares**.
> `resolve`, `recent`, `export`, `record` and `settle` evaluate no liveness
> — `settle` takes its `settled_at` from the caller, as `record` takes its instants, because a
> store neither mints ids nor reads a clock (ADR-0021 §3). The policy reads
> no clock at all (ADR-0021 §3, ADR-0036 §1), and `AuditTrail.record` decides both ends against
> the decision's own `decided_at`.

> **Normative — `standing(goal)` returns the `ESTABLISHED` rows of that goal and nothing
> else**, live **and** lapsed. **It reports no liveness and carries no evaluation instant**,
> because `Authorization`'s field list is closed and a result type wrapping one would be a
> second carrier for a fact the row already determines: each row carries its own `expires_at`,
> and **whether it has passed is the caller's comparison against one reading of the injected
> clock** (ADR-0026). The engine takes that reading when it assembles the listing and hands the
> surface the answer as data, which is ADR-0042 §6's division — an adapter reads no store and
> holds no clock. It never returns a `PROPOSED` row, so the listing §11 fixes never renders a
> question the user has not answered as an authority they hold; and it does return a lapsed
> one, so a user can see and revoke what they once authorised — which is ADR-0193 §9's own
> reason for keeping an expired grant visible and revocable, one store over, and it is why the
> withdrawal path needs no history query. `recent` and `export` carry every row whatever its
> disposition, which is where a declined and a superseded one are read.

> **Normative — a store fault is not a record.** An `AuthorizationError` out of `covering` is
> logged and answered `None`, so the ruling proceeds to the `CONFIRM` the request would have
> drawn with no store at all — the fail-closed direction, and the reason the user sees is
> unchanged, because *"a store fault is an operator's fact and not something to put in front of
> someone deciding about a call."* **The log line names the class and no value**, and the
> declaration's id is read **before** the await, both of which are
> `ThresholdActionPolicy._covering`'s existing discipline adopted rather than reinvented.

> **Normative — the triad rides with its primary consumer.** `GoalAuthorizations`,
> `AuthorizationResolution` and `GoalAuthorizationStore` are **new** Protocols, so each ships as
> a triad — the Protocol, a shared conformance suite, and a canonical fake in
> `ai_assistant.testing` — **in one change and never deferred**. ADR-0137 §2 permits that triad
> to ride with the primary production implementation whose demands shape the contract, and here
> that is `ThresholdActionPolicy`'s route (d); §20 cuts the lanes on that seam.

> **Normative — the store is Tier 1 and carries the data rights.** Its records are Tier 1
> (ADR-0004 §1): a goal statement, an argument value and a span of the user's words are the
> user's personal data. It persists **locally only**, under `Settings.data_dir` (ADR-0155 §1's
> surviving residency clause), with owner-only file permissions. **`export` returns a portable
> snapshot of every row** — proposed, established, declined, expired, revoked and superseded —
> and **`clear` erases the store wholesale and returns the count**. **There is no `delete(id)`**, exactly as there is
> none on the recipient-grant store and for its reason: a store from which a row can be removed
> is one whose history can be rewritten.

> **Normative — what `clear` does not do.** It retracts, invalidates and re-opens nothing. A
> recorded `ALLOW` stays recorded, stays true about the moment it was made, and still names the
> record it rested on; the row's rendering under ADR-0193 §11 does not change. What is lost is
> the record's **own** text — its coverage, its basis, its expiry — because the decision carries
> a pointer and a digest and never the record by value.

> **Normative — what crosses the wire, and what does not.** Three things cross: the
> **listing**, the **revocation** and **`Confirmation.authorization`** (§11). **No
> `Authorization` crosses whole**: the confirmation carries a **projection** of the coverage
> the answer would establish, not the record — there is no record yet — and the listing carries
> the rendering §11 fixes rather than the stored value, so no client holds a record's basis, its
> digest or its account. That is `ConfirmationEgress`'s discipline, which carries *"the recorded
> decision's own value, reaching a surface by ADR-0178 §5's transcription rather than as a
> second carriage of it"*.

> **Normative — `PROTOCOL_VERSION` moves in every change that makes a wire-carried value one
> peer emits invalid for the other, and `wire/envelope.py`'s log gains an entry per bump naming
> this ADR and the ground.** ADR-0124 §9 requires the bump *"in the same change"*, and §20 cuts
> the lanes so that **two** of them carry one: Lane 1 under §9's second limb (`PermissionRuling`
> gains a field and is carried inside a `PermissionDecision` a client decodes), and Lane 3 under
> its first (the promoted surface gains methods) and its second (`Confirmation` gains a member).
> **No lane defers its own bump to a later one**, which is the defect this clause is stated
> against. **No integer is fixed here**: ADR-0249 §12 already schedules a bump and other lanes
> of this batch may land before or after, so a number written in this document would be a claim
> about an order nobody controls. **No lane adds a compatibility shim, an optional-member
> negotiation, a per-member capability flag or a lenient decode**; ADR-0084 §3's exact-match
> handshake is the mechanism and the refusal naming both versions is the intended outcome.

> **Normative — `PermissionDecision` gains no field.** `from_request` transcribes the ruling
> whole (`ruling.model_copy(deep=True)`), so `authorised_goal` reaches the durable record along
> the path that exists today — no reconstruction by the caller, no second lookup, no parameter
> added to `from_request` and no widened `ActionPolicy` return. **`ActionRequest.goal` is
> deliberately not transcribed**: the trail has no use for a value it cannot compare against the
> arguments (§7), and a decision carrying a goal id would put a second, unvalidated assertion of
> the same fact on the durable record.

### 17. Q4's rule, carried and not discharged

> **Normative.** **No consequential capability is wired into a production deployment until the
> verification, uncertain-outcome and cancellation guarantees for its class are implemented and
> demonstrated.** A milestone may demonstrate dependent execution against controlled
> integrations with no such capability wired; **wiring one is what this rule binds.** This is
> the owner's ruling of 2026-09-12 recorded verbatim, and it is carried by A5, A6 and A7 and
> discharged by A8, A9 and A10.

> **Normative.** **This decision dispatches nothing.** It lands a contract, and the lane that
> implements it wires no consequential capability, registers no booking integration, and
> enables nothing in a production deployment. The shape is the corpus's own for exactly this
> problem — ADR-0188 gates a capability on a record existing, ADR-0236 fails closed on a missing
> declaration — and it is stated here so that a lane cannot read a landed authorization
> mechanism as permission to wire the thing it was built for.

### 18. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is applied to the earlier ADR's **text**, and it is shown rather than
asserted: *"Would a reader holding only the earlier ADR now act differently, or read one of its
clauses more widely than it now holds?"* Three come out yes and take a record; the rest come out
no and take none, which ADR-0082 §1 requires as firmly — *"Absent a clause that fails §1's test,
there is nothing to record."*

**ADR-0148 §3 — partially superseded, in the route enumeration of its first clause alone.** The
clause reads that an `ALLOW` is available *"only where every member of its canonical destination
set is covered by one of two things"*, which ADR-0247 §2 already made three. A reader holding it
would read the enumeration as closed and would refuse a call route (d) covers. That is the test
met, and the record is the same shape and the same scope ADR-0247 §2 took. **Every other clause
of §3 binds entire** — its second clause's limbs, its `SourceGrant` refusal and its clause
reserving three questions to the standing-grant ADR — and **§1, §2, §4–§9 are relied on as
written**, §1 conspicuously so (§6 above).

**ADR-0193 §6 — partially superseded, in the scope of its invariant alone.** §6 states the
invariant over *"a non-resolving `ALLOW` whose `egress_binding` is not `None`"*, which ADR-0247
§2 narrowed by *"and whose `authorised_subject` is set"*. A route-(d) row carries a digest, so a
reader holding §6 as ADR-0247 left it would apply the eight checks to one and refuse it — it
resolves against the wrong store. The scope narrows by one further conjunct, **and
`authorised_goal` is unset**, and **the eight checks themselves bind entire on every route-(b)
row**: the outstanding-grant read, both ends of liveness, tool equality, account equality,
destination-set containment, the origin arm and the recomputed `subject_digest`. §6's
**reservation** clause is **discharged rather than superseded** — it asks a later ADR to decide
*"how the reference is told apart, whether by tagging it, by a second field, or by narrowing this
scope"*, and §7 above chooses the second and the third together.

**ADR-0247 §2 — partially superseded, in its discriminator clause alone.** That clause reads
*"a non-resolving egress `ALLOW` whose `authorised_by` is set is **route (b) where
`authorised_subject` is set** and **route (c) where it is not**"*. A reader holding it would
classify a route-(d) row as route (b), which is false. The route-(b) limb takes one further
conjunct (§7); **the route-(c) limb is untouched**, and so is every other clause of §2 — the
derived fact, the two configured values, the ordering before the grant seam, the digest-free
admission on `closed_loop` and pointer equality, the eligibility-versus-discriminator division,
and the clause reserving the account-and-origin comparison to the policy.

**ADR-0021 — no record owed, and the reason is stated because a reader would expect one.** §3's
rule that *"`decide` must return `authorised_by is None` from a policy constructed with no
authorisation source"* stays true of route (d): the `GoalAuthorizations` seam **is** a source, a
policy without one reaches no route (d), and no sourceless policy sets either field (§6). §3's
named precondition — that the second source be *"resolvable to a recorded user decision that
actually covers this call, and where those records live"* — is **discharged a second time**, by
§7 and §16, and a precondition met is not a clause amended. §5's disclosure floor is **satisfied
by setting `authorised_by`, not relaxed**, which is that clause's own construction: *"the floor
is on the policy deciding by itself, not on the outcome, so an `ALLOW` naming the user decision
it rests on is permitted."* §6's standing-grant deferral is a deferral, not a rule this
contradicts.

**ADR-0193 §9 — no record owed, and which of its clauses this store takes.** §9's sentences are
stated over *"a grant"* and stay true of every grant. This store takes over, clause for clause,
its prospective-revocation rule and the two points at which it bites, the residual window from
`record`'s resolution read to the execution, the one-clock-reading discipline for a liveness
query, the no-unbounded-spelling rule for an expiry, the strict ordering of the expiry after the
instant the row was written, and the no-deletion-but-`clear` rule. It does **not** take §9's
append-a-revoking-record mechanism or the `outstanding` relation that rests on it, because §1
settles a durable proposal on ADR-0244's shape instead — which is a different store making a
different choice, not a clause of ADR-0193 becoming false.

**ADR-0193 §3 and §11 — no record owed.** §3's clauses are stated over *"a grant"* and stay true
of every grant; a second standing authority with different comparisons is a stacked addition,
recorded here and nowhere else. §11's three states stay **total** over `ALLOW` rows and a
route-(d) row is the second of them, asserting exactly what it asserts of a route-(b) row —
that this decision **names** a standing authorisation — which §11's own words already cover.
What §11 gains is a second kind of row inside one state, and no sentence of it becomes false or
over-wide.

**ADR-0249, ADR-0250, ADR-0252 and ADR-0253 — deferrals fired, no record owed.** Each names A6
in a clause written to be fired, and each stays true of the state it describes: ADR-0249 §13's
*"**Authorization: fixed values, permitted ranges, the basis triple, and coverage from several
acts.** A6"*; ADR-0250 §11's *"A6 gives it an authorization coverage to compare; **until then**
this clause is the whole of it"*, whose own condition is now satisfied; ADR-0252 §15's
*"**Authorization coverage.** **A6**"*; and ADR-0253 §11's bullet, including the question *"whether
a dependency's own origin is a further input to a ruling"*, answered in §3 above. A clause that
names its own trigger and is triggered has not been amended.

**ADR-0194 — relied on, and §8's deferral is not reopened.** §8 rules that *"**Money a tool
moves** is not decided and no ceiling here bounds it"* and that per-tool, per-capability and
per-protocol ceilings *"are not decided, and no lane adds one under this ADR"*. §14 above adds
none: a `MONEY` bound is not a ceiling, bounds no sum, reads no total and refuses nothing —
it fails to cover, and the consequence of failing to cover is a question.

**ADR-0037, ADR-0058, ADR-0152 and ADR-0211 — relied on, none amended.** The sequence, the
executor's four collaborators, `rebind`'s exactly-two and the absence of a post-parse vocabulary
check are each consumed as written, and §13 and §14 state where.

### 19. What this ADR does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling,
> and each carries the condition that fires it.

- **Whether a standing authority ever covers a call planned over external content or carrying
  covered content.** Route (d) relaxes neither floor (§6). Fired by a decision that takes
  ADR-0233 §9's second clause head-on, with its own argument and its own arms, as ADR-0238 §7
  and ADR-0247 §3 did for the one exception this corpus admits. **This ADR is not that
  decision** and no lane reads §6's conditions 3 and 4 as negotiable.
- **A standing authorization for a side-effecting action that is not an egress call.** Route (d)
  is stated on ADR-0148 §3 and every clause of this ADR is scoped to a decision carrying an
  `egress_binding`. ADR-0021 §6's deferral for other actions stays unnarrowed. Fired by an ADR
  that opens it and states its own scope beside this one.
- **A fourth `BoundKind`** — a count, a distance, a duration, a quantity. Fired by an argument
  that actually needs one, with a total exact ordering the corpus can state.
- **A fourth `ResolutionRule`.** Fired the same way, and never by a resolution whose inputs are
  not on the turn it names (§10).
- **What happens to a call already claimed when a revocation lands.** **A9.** §13 states the
  residual window and claims nothing stronger, on ADR-0193 §9's own refusal of a cross-store
  linearisation.
- **Which `AttemptOutcome` an attempt that stopped for authorization earns, and whether an
  uncovered argument is a `CONDITION_PREVENTED`.** **A10.** ADR-0249 §5 fixes the vocabulary and
  reserves the mapping.
- **The mechanism by which an attempt re-enters an earlier phase.** **A7**, as ADR-0253 §9
  already reserves it. §14 states only that no phase moves backwards and that this decision
  mints no mechanism for one.
- **Which further user acts open an attempt.** **A3**, as ADR-0250 §12 reserves it. §14 states
  only that supplying an authorization opens none.
- **`GoalStatus.BLOCKED`'s producer** (A3) and **`GoalStatus.ACHIEVED`'s** (A10). This decision
  writes neither, which is the owner's correction 2 and ADR-0249 §4.
- **An authorization the user establishes ahead of time**, without a `CONFIRM` about a concrete
  call — *"you may spend up to fifty pounds on this"* said before any request exists.
  path (i) requires a recorded `CONFIRM` and path (ii) requires a live row to supersede (§1),
  so it is unrepresentable here. Fired by
  an ADR that decides what the user is shown when there is no concrete call to show them.
- **A durable, dated record of the configuring act** for route (c). ADR-0247 §13's deferral,
  untouched.
- **Retention for this store beyond `clear`.** Issue #108's shape one store over. Fired by the
  decision that lands retention for the audit trail.

### 20. The lane cut, and the arms this decision owes

> **Normative — the cut.** **Lane 1, the contract triad and the policy.** `core/types.py`'s
> seven new types and two new fields, `core/protocols.py`'s three Protocols, `core/errors.py`'s
> one class, the shared conformance suites, the canonical fakes in `ai_assistant.testing`, the
> `SqliteGoalAuthorizationStore` in `permissions/`, `ThresholdActionPolicy`'s route (d), and
> `AuditTrail.record`'s route-(d) invariant. ADR-0137 §2's exception is what makes this one
> change: the triad rides with the primary consumer whose demands shape the contract.
> **Lane 2, the proposal, the settlement and the recheck.** `orchestration` proposing the row
> when a `CONFIRM` is put, settling it on the answer, writing a path-(ii) correction,
> `ActionRequest.goal`, the attempt's `AWAITING_AUTHORIZATION` commit and the
> `add_authorization_id` append, and phase 4's evaluation. **Lane 3, the surfaces.** The
> listing, the revocation, and `Confirmation.authorization` with its two projection types.

> **Normative — every lane that changes the wire carries its own bump, and no lane defers
> one.** ADR-0124 §9 requires the bump *"in the same change"*, and two of these lanes make a
> wire-carried value one peer emits invalid for the other. **Lane 1 bumps**:
> `PermissionRuling` gains a field, `PermissionRuling` is carried inside `PermissionDecision`,
> and a decision crosses the promoted surface today — so an older client decoding one under
> `extra="forbid"` refuses it, which is ADR-0124 §9's second limb exactly. **Lane 3 bumps**:
> it adds methods to the promoted surface and a member to `Confirmation`, each independently
> that ground. **Lane 2 changes no wire-carried type** — `ActionRequest` crosses no frame — and
> bumps nothing. **No integer is fixed here**, because other lanes of this batch move the same
> constant and a number written in this document would be a claim about an order nobody
> controls.

> **Normative — Lane 2 and Lane 3 depend on A5 and on A7, and no lane of this decision lands
> before the contracts it reads.** Phase 4 evaluates `when` and `depends_on`, which **ADR-0253
> has decided and no lane has implemented** (Context); the driver that walks the steps is A7's.
> Lane 1 depends on neither and may land first.

> **Normative — the arms this decision owes**, each a representative-input test the implementing
> lanes ship:
>
> 1. **Existing authorization covers the concrete action.** A live record fixing the entity,
>    the party size and the terms and bounding the price; a request of that goal inside every
>    member → route (d) `ALLOW`, `authorised_by` the record's id, `authorised_subject` its
>    recomputed digest, `authorised_goal` its goal, `RecipientGrants.covering` called **zero**
>    times, and **no redundant approval**.
> 2. **Permission missing.** No record of that goal → no route (d), `CONFIRM`, the step parks,
>    the attempt commits `AWAITING_AUTHORIZATION`, **nothing dispatched and no claim made**.
> 3. **Permission revoked.** `settle(REVOKED)` between the establishment and the dispatch →
>    `covering` answers `None`, `CONFIRM`, and the earlier recorded `ALLOW` is unchanged and
>    still true about the moment it was made. **And after a chain of corrections**: revoke the
>    superseding row and every argument is uncovered, including the ones whose members were
>    carried forward from the first act — there is no contributor left standing that the
>    revocation missed. **And a revoked or superseded row cannot be settled again**: `settle`
>    refuses every move that is not one of §1's five edges, and none leaves `REVOKED` or
>    `SUPERSEDED`.
> 4. **Revocation between `covering` and `record`.** Settle the row the ruling names `REVOKED`
>    after `covering` returned and before `AuditTrail.record` begins its resolution read → the
>    write is **refused**, on §7's disposition check, for the row behind **every** argument.
> 5. **Price inside the range.** An argument at, below and above `maximum` → covered, covered,
>    **not covered**; and at `minimum` where one is carried → covered.
> 6. **A price as a JSON float** → **not covered**, on §4's refusal, whatever its magnitude.
> 7. **A fixed value differing by one byte** — a recipient with one changed character, a
>    number rendered as a string where the member holds a number → **not covered** in each, on
>    the canonical JSON comparison and not on a looser one.
> 8. **An argument the record names in no member** → **not covered**, and the reason names
>    that argument.
> 9. **A request carrying `goal` unset** → no route (d), on every request including one every
>    other comparison would cover.
> 10. **The `MONEY` bound's currency conjunct, over the concrete request.** A request carrying
>     no value at the bound's `currency_argument`, one carrying a non-string there, and one
>     carrying a string that differs from the bound's `currency` by one byte → **not covered**
>     in each; one carrying that exact string → **covered**, whatever the declaration's schema
>     admits, because no schema is consulted (§4).
> 11. **A `PERIOD` bound's half-open end.** An instant at `starts_at` → covered; one at
>     `ends_at` → **not covered**; a date-time carrying no offset → **not covered**.
> 12. **Terms outside the named set**, and a term differing only by case → **not covered** in
>     both.
> 13. **Destination outside the set**, and the same address through a second connected account
>     → **not covered** in both, the second on `BoundAccount`'s two facts.
> 14. **"Make it Sunday", end to end from the utterance.** Act 1 is an answered `CONFIRM`
>     fixing the entity, the party size, the terms and a Saturday date and bounding the price.
>     Act 2 is a recorded turn carrying *"actually, make it Sunday"* and **no pending
>     confirmation**. The turn writes a superseding record whose date member carries the new
>     basis and whose every other member is byte-identical to act 1's, including its basis;
>     act 1's record stops being live; a Sunday request inside the bound is **covered by the
>     one record**; `authorised_by` names it; **the user is not asked**. A Sunday request
>     above the bound is **not covered** and asks, and the reason names the price and not the
>     date.
> 15. **A correction that would widen takes no path (ii).** *"Make it up to eighty"*, *"add
>     Bob"*, *"make it next month as well"*, and a correction naming an argument no member
>     covers → each **refused at construction**, no record written, and the concrete action
>     confirmed.
> 16. **A correction to a destination-bearing argument takes no path (ii)** → refused at
>     construction, whatever the destination is.
> 17. **A superseding record transcribes what it may not change.** `goal`, `tool`, `account`,
>     `destinations` and `expires_at` altered on an otherwise valid superseding record → the
>     store refuses the transcription, one test per field.
> 18. **A correction changing the currency** — act 1 bounds GBP 60 and fixes `currency` to
>     `"GBP"`; a correction fixing `"KWD"` → **refused at construction**, because the record
>     would carry a `MONEY` bound and a fixed currency member that disagree; and a request
>     carrying `{amount: "60", currency: "KWD"}` against act 1's record is **not covered**, on
>     §4's request-currency conjunct.
> 19. **Supersession is permanent.** Revoking a superseding record does **not** make the
>     record it superseded live again; both stay in the store and both appear in `export`.
> 20. **An interpretation that would widen** — a member for an argument the act never
>     mentioned, a raised `maximum`, an added term, a widened destination set, a moved
>     `expires_at` → each **refused at construction**, and each with its own test.
> 21. **A model-only basis is unconstructible** — a `CoverageMember` with no basis, a basis
>     whose `act` names no recorded turn, and a basis whose `span` is not a span of that
>     turn's `TurnResult.utterance` → each refused.
> 22. **The expiry is shown at the act and enforced at dispatch.** A record whose `expires_at`
>     has passed covers nothing; the `CONFIRM` that would establish one names the instant
>     through `Confirmation.authorization`; the listing names it.
> 23. **The instant shown is the instant written, however late the answer and whatever moves
>     in between.** A `CONFIRM` recorded at 09:00 under a twelve-hour ttl proposes a row
>     carrying `proposed_at` 09:00 and `expires_at` 21:00; the confirmation names 21:00;
>     answered at 10:00 the row settles `ESTABLISHED` carrying 21:00 and **not** 22:00 — **and
>     the same holds across a process restart, and across a `workflow_authorization_ttl`
>     changed to any other value in that interval**, because both instants are read from the
>     durable row and neither is recomputed.
> 24. **An answer at or after that instant establishes nothing.** The `CONFIRM` resolves and
>     the one call is authorised by route (a); **no `Authorization` is written**, and the next
>     dispatch of that goal asks.
> 25. **A chain of corrections does not outlive the first act's expiry.** Three successive
>     superseding records carry one `expires_at`; the third covers nothing after it.
> 26. **The expiry touches nothing else.** A `RecipientGrant` established in the same run
>     keeps the instant the user chose; a route-(c) ruling is unaffected by
>     `workflow_authorization_ttl` at any value.
> 27. **The recheck at dispatch refuses a changed argument before the claim.** A result
>     reference resolving to a value outside the bound → `CONFIRM`, the step parks, **no `→
>     RUNNING` transition is committed**.
> 28. **The route discriminator is total.** Rows of all four routes plus a policy-rules row →
>     each classified from the row alone, with **no store read**, and the route-(b) and
>     route-(c) classifications unchanged from `origin/main`.
> 29. **The trail refuses a route-(d) row** on each of §7's eight checks independently — a
>     disposition other than `ESTABLISHED`, a `settled_at` after the decision's `decided_at`
>     (the backdated case), an `expires_at` at or before it, an unequal declaration, an
>     unequal account, a destination of the binding the row does not carry, an unequal goal,
>     and a digest recomputed unequal.
> 30. **A sourceless policy reaches no route (d)** and leaves `authorised_by` and
>     `authorised_goal` unset, on every request including one at the configured provider.
> 31. **The floors route (d) does not relax.** A request of a goal with a covering record
>     whose binding carries `planned_with_external_content`, and one whose `coverage` is not
>     `NOT_COVERED` → `CONFIRM` in both, and `covering` called **zero** times in both.
> 32. **An `UNKNOWN` cost, a threshold `risk_level` and a threshold `reversibility`** each
>     still draw `CONFIRM` with a covering record in the store.
> 33. **Export, enumeration and erasure.** `export` returns rows of every disposition **with
>     each member's basis whole** — act, span and resolution; `standing(goal)` returns the
>     `ESTABLISHED` rows of that goal, **live and lapsed**, never a `PROPOSED` one and never
>     another goal's, and **returns the same rows immediately before and immediately after an
>     `expires_at`**, the difference being the caller's comparison and not the store's; `clear`
>     returns the count and leaves every recorded `ALLOW` readable as what it was.
> 34. **Each `ResolutionRule` admits its own argument shape and refuses the other two** —
>     `AS_STATED` with either argument, `DATE_FROM_CONTEXT` missing `now` or `timezone`,
>     `FROM_SHOWN_RECORD` missing `record` — each refused at construction.
> 35. **`Confirmation.authorization` is present exactly where an answer would establish a
>     record and absent otherwise**, is required with no default, and carries a bound as a
>     bound and a fixed value as a fixed value. A roster test in ADR-0178 §10's shape over
>     `ConfirmationAuthorization` and `ConfirmationCoverage` asserts that no field of either
>     is named or typed for a goal id, an authorization id, a `BoundAccount`, a connection
>     reference, a `SecretName` or a transport endpoint.
> 36. **The store refuses a second `ESTABLISHED` row for one goal and declaration**, and
>     `covering` answers `None` where two would; a superseding write for the same pair is
>     accepted and settles the predecessor in the same write.
> 37. **The transition graph, edge by edge and non-edge by non-edge.** Each of the five edges
>     succeeds under compare-and-swap; every other move is **refused**, with one test per
>     retired disposition and one for `PROPOSED → REVOKED`, `PROPOSED → SUPERSEDED` and
>     `ESTABLISHED → DECLINED`/`EXPIRED`. A `PROPOSED` row is **never** live; a row read after
>     its `expires_at` while still `PROPOSED` is settled `EXPIRED` by a `covering` read and by
>     the answer that names it, and by no other operation; and an
>     `ESTABLISHED` row past its `expires_at` is **not live**, is **not** settled `EXPIRED`,
>     and is still `REVOKED` by a withdrawal and `SUPERSEDED` by a renewal.
> 38. **Every persisted state decodes.** Approve a proposal, persist, restart, and `resolve`,
>     `recent` and `export` each return the row — an `ESTABLISHED` row still carrying its
>     `confirmation` is valid, and so are the `DECLINED`, `EXPIRED`, `REVOKED` and
>     `SUPERSEDED` rows, one round-trip test each; `standing` returns the `ESTABLISHED` one
>     and none of the other four. **`record` refuses to write a
>     `confirmation`-carrying row in any disposition but `PROPOSED`**, which is the write-path
>     rule the validator deliberately does not state.
> 39. **A confirmed widening.** A live row bounds GBP 60; *"make it up to eighty"* proposes a
>     path-(i) row naming it in `supersedes` and the user is asked. Approving settles the new
>     row `ESTABLISHED` and the old one `SUPERSEDED` **in one write**, with no instant at
>     which both are established; declining settles the new row `DECLINED` and leaves the old
>     one live and unchanged.
> 40. **The proposal survives a restart.** Propose a row and render the confirmation; restart
>     the process; recover the confirmation → the same coverage and the same `expires_at`, and
>     answering then settles that same row.
> 41. **Each lane's wire bump.** Lane 1's and Lane 3's changes each make a value one peer
>     emits invalid for the other, and each lands with its own `PROTOCOL_VERSION` increment
>     and its own `wire/envelope.py` log entry; Lane 2 changes no wire-carried type and bumps
>     nothing.
> 42. **Renewal after expiry.** Establish a row expiring at 21:00; at 22:00 the goal needs
>     authority again. A path-(i) proposal naming that lapsed row in `supersedes` is confirmed
>     → the new row settles `ESTABLISHED` with a fresh `expires_at` and the lapsed one settles
>     `SUPERSEDED` **in one write**, and at no instant are two rows of that goal and
>     declaration both `ESTABLISHED`. **A path-(ii) correction naming a lapsed row is
>     refused**, because it would transcribe an expiry already passed.
> 43. **Withdrawal of an established row.** `settle(REVOKED)` succeeds on an `ESTABLISHED` row
>     whether it is live or lapsed, and is refused on a `PROPOSED` one; the lapsed row is
>     reachable for it because `standing(goal)` returns it.
> 44. **The conformance suites run against the canonical fakes and against the SQLite store**,
>     and the monotonicity suite for `ThresholdActionPolicy` stands up a fake
>     `GoalAuthorizations` and holds its records equal, which is ADR-0193 §12's own
>     accommodation for a sourced policy.

### 21. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding
the corpus without it has three routes to an egress `ALLOW`, no record that bounds an argument
value, no seam through which a policy could read one, and no answer to the question ADR-0249
§13, ADR-0250 §11, ADR-0252 §15 and ADR-0253 §11 each defer here by name. They would build a
`PermissionRuling` with two authority fields, an `ActionRequest` with no goal, and a phase 4
that evaluates three predicates and adds none. That is ADR-0070 §1's test met, and a new ADR is
the instrument.

**It is a partial supersession of exactly three documents** (ADR-0070 §3) — ADR-0148 in one
scope, ADR-0193 in one, and ADR-0247 in one — and the `Status` line of each names its scope
**without an `ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction invariant
holds. Every other ADR it touches is **relied on**, and §18 shows the working for each rather
than leaving a reader to check.

**The records land in the same change as this document** (ADR-0082 §7): ADR-0148's, ADR-0193's
and ADR-0247's `Status` qualifiers and dated notes are written with it and not after it. Nothing
else in any of the three is edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

### 22. Marking, review and ratification

**This ADR is marked** under ADR-0089: every obligation it imposes is a `> **Normative.**`
blockquote at column 0, and unmarked text beside a mark is read to determine what the mark means
and supplies no obligation of its own. Quoted marks from other ADRs appear inside quotation
marks in running prose rather than as marks of this document.

**It is a contract-surface change**, so it owes **both** review lenses — adversarial and
architecture — on one tree, and ADR-0015 §1 makes that true of a prose-only PR.

**It merges as its own PR, ratified, before anything implements against it** (golden rule 5,
ADR-0015). The lanes of §20 are briefed after it merges, and the ratification flip is one line
and no other byte (ADR-0165).

## Consequences

**What becomes easier.** The workflow #2255 exists to build stops asking the user to repeat
themselves: an act that fixes some arguments and bounds another covers every later call of that
goal inside it, a correction **supersedes** it for the one argument it changes and carries the
rest forward, and the system asks exactly where the owner's direction says it should —
*"additional costs or materially different terms"*. The authority is auditable in a way no
previous route is: a row names one record, that record carries a member per argument, and each
member names the turn, the user's own words and the working by which those words became a
value — so *"what authorised this, and who said so"* is answerable per **argument** and not
merely per call. `GoalAttempt.authorization_ids` and `AttemptState.AWAITING_AUTHORIZATION` get
their first producers, and ADR-0021 §3's carried-but-unread `parameters` gets the per-call gating
ADR-0017 §3 made a condition on designating the seam.

**What becomes harder.** There is now a second standing authority for egress, and the trail
tells four routes apart rather than three — a partition that is total today and that every later
standing source must extend rather than join. The policy takes a second durable read and a third
constructor argument. `ActionRequest`, `PermissionRuling` and `Confirmation` each gain a field
and two projection types arrive with the last, which is three breaking `core` changes and two
`PROTOCOL_VERSION` bumps at a moment when several lanes of this batch are also moving `core`.
A correction now writes a whole record rather than a delta, so a long chain of corrections
writes a long chain of records — bounded by the expiry, and the store is append-only anyway. And
the per-argument comparison is the first rule in this corpus that reads a payload: everything
about how an argument is read for a bound (§4) is new surface with new ways to be wrong, which
is why every reading refuses what it cannot prove and why the arms above test each refusal
independently.

**A cost this decision accepts rather than hides.** §3 requires **every** argument of the
request to be covered, so a declaration carrying an argument no act could reasonably have
named — an idempotency key, a client reference, a locale — is one whose calls always ask, until
an act fixes that argument too. The alternative is a rule that lets some arguments go
unmentioned, and there is no way to state which without the system deciding for the user which
of a call's arguments matter. §19 books a fourth `BoundKind` and nothing else; what would
actually change this is a declaration that distinguishes an argument the user chooses from one
the caller supplies, which no ratified decision offers and this one does not invent.

**What is deliberately still missing, and stated so nobody reads it as done.** Route (d) does not
reach a call planned over external content or carrying covered content, so a booking composed
over a search result still asks — the mechanism lands and the most-wanted case is not yet
covered, and §19 books the decision that would change it. Nothing here dispatches, drives,
retries, verifies or cancels anything; the owner's Q4 rule (§17) is carried rather than
discharged, and no consequential capability is wired by this decision or by the lanes that
implement it. And phase 4's evaluation reads two contracts — ADR-0252's evidence rows and
ADR-0253's step fields — that are **ratified and not implemented** at `origin/main`, so Lane 2
cannot land before they are.

**What would trigger revisiting this.** A fourth kind of bound an argument actually needs; a
second standing source for egress, which must extend §7's partition; a decision that takes
ADR-0233 §9's second clause head-on; or evidence that the twelve-hour default is the wrong
shape — in which case the figure moves and the clause that forbids a disable sentinel does not.

## Alternatives considered

**Coverage members on `RecipientGrant`, with a second `covering` rule.** Rejected in §1. It
would put a goal id, an argument key and a money bound on a record ADR-0193 §1 closed by name,
give one store two kinds of row with one query member that has to choose between them, and leave
`AuditTrail.record` unable to say which invariant a row is owed — which is exactly the state
ADR-0193 §6's reservation was written to prevent.

**Keying the authorization on the capability rather than the declaration.** Rejected in §1. A
capability is a name a registry resolves, and #54 is the whole reason ADR-0021 §1 embeds the
declaration by value; a standing record is exposed to rebinding for as long as it is live rather
than for one invocation, so the argument is stronger here than where it was first made.

**A general predicate language for coverage** — comparisons, conjunctions, a small expression
grammar. Rejected in §2. The failure modes are asymmetric: a permissive mistake authorises a
call the user did not authorise and is undetectable afterwards, and an expression language is a
parser at the one comparison that must not be wrong. Three kinds, each with a relation the
corpus already states, is what the owner's direction actually needs.

**Deriving the destination set from the covered arguments** rather than carrying it. Rejected in
§1 and §3. The canonical set is computed by the seam from the arguments under ADR-0148 §2's
per-protocol rules; comparing arguments does not prove the sets equal, and a rule that assumed it
did would be an inference at the seam ADR-0148 §2 exists to make exact.

**Composing coverage across several records at ruling time.** Rejected in §5, and it was the
first design. It cannot keep §13's promise that a revocation bites at `record`'s resolution
read: with two contributors and one pointer, revoking the contributor the ruling does not name
leaves every check the trail can make passing. Carrying every contributor on the ruling would
put an unbounded tuple and an unbounded set of digests on a type ADR-0193 §6 kept to one pointer
and one fingerprint, and would make the route-(d) invariant a loop over an unbounded set of
store reads inside a write path that today performs one.

**Tagging `authorised_by` to say which store it names.** Rejected in §7, on ADR-0193 §6's own
ground for declining it: *"a tag with one value today is a surface with no consumer, and the
second value would arrive with its own ADR anyway."* A second optional field extends the existing
partition without changing how any recorded row reads, and it carries a fact — the goal — that an
auditor wants for its own sake.

**Giving `AuditTrail` the request's arguments so it could re-take the coverage comparison.**
Rejected in §7. `PermissionDecision` carries a digest and not the payload deliberately, because
*"a durable record holding them verbatim would make the audit trail a second copy of the user's
most sensitive material, growing forever"* — and ADR-0004 §7's minimisation says the same. The
honest answer is the one ADR-0247 §2 gives for route (c): state what the trail can check, state
what it cannot, and give neither component the other's job.

**Letting the user choose the expiry, as `RecipientGrant` does.** Rejected in §12. The two
records are asked about different things: a recipient grant is a preference the user expresses
("stop asking me about Alice"), and an authorization is an answer about an action in progress.
Asking "until when?" about the second is a second question at the moment the design exists to
remove one, and decision 7's *"justified, visible"* is satisfied by stating the instant rather
than by negotiating it.

**Minting a fourth phase-outcome vocabulary** — ready / awaiting / needs-revision. Rejected in
§14. `AttemptPhase` and `AttemptState` already carry every state phase 4 can leave an attempt in,
`AWAITING_AUTHORIZATION` is a closed member with no producer, and a second vocabulary would be
two authorities that can disagree about one fact — the argument ADR-0249 §5 makes when it
declines a fifth `GoalStatus` member for "paused".
