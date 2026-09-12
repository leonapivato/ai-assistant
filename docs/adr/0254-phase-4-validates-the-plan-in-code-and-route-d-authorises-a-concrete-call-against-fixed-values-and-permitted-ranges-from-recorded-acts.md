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
binds."* §17 carries that rule and this ADR dispatches nothing under it.

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
- **The attempt already records what authorised it, and this decision adds no second kind of
  id to that tuple.** ADR-0249 §5 gives `GoalAttempt` *"`plan_ids`, `execution_ids` and
  `authorization_ids`"*, and ADR-0249's third lane **has landed a producer**:
  `orchestration/engine.py` appends *"the decision it was allowed by"* — a `PermissionDecision`
  id — through `AttemptTransition.add_authorization_id`. §14 relies on that and appends nothing
  of its own kind, so the tuple stays one namespace.
- **The state the attempt stops in already exists and already has its producer.**
  `AttemptState.AWAITING_AUTHORIZATION` (ADR-0249 §5) is written by `orchestration/engine.py`
  the moment a `CONFIRM` is recorded at dispatch. §14 relies on that and adds no second
  writer.

### The tree, read rather than assumed, at `origin/main` `acfe9d0c`

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
  `GoalAttempt.authorization_ids` is written with `PermissionDecision` ids.
- `wire/envelope.py` — `PROTOCOL_VERSION` is **39**.
- **ADR-0249's lanes have landed, L3 included**: `Goal`, `AttemptPhase`, `AttemptState`,
  `AttemptOutcome`, `AttemptEffort`, `GoalAttempt` and `GoalBrief` are on the tree.
  **ADR-0251's first lane has landed too**: `ReadAskOutcome`, `ReadOutcomeKind` and
  `AttemptKind` are on `core/types.py`, `AttemptEffort` carries a `kind`, `Planner.plan` takes
  `read_outcomes`, and `PROTOCOL_VERSION` moved for it. **No clause of this decision reads any
  of those**: it names `Planner.plan` once, in §13, for the fact that a late answer takes its
  own planning call (ADR-0250 §11) and not for that method's arguments; and it names
  `AttemptEffort` once, in §14, for the ledger ADR-0249 §5 states and not for its fields.
  **ADR-0250, ADR-0252 and ADR-0253 are ratified and not implemented**: every type this decision
  cites from them — `GoalQuestion`, `GoalEvidence`, `StepCondition`, `PlanStep.depends_on`,
  `PlanStep.when`, `PlanStep.verifies` and the engine-resolved result reference — is read from
  those ADRs and is **not** a shape this decision found in the tree. Where a clause below rests
  on one, it says so.

### What this ADR is not allowed to settle

The plan-driving stage and the claim's second conjunct (A7); retry, reconciliation and
`EFFECT_UNRESOLVED` (A8); the cancellation boundary and what a cancellation racing a dispatch
does (A9); verification and which `AttemptOutcome` an attempt earns (A10); `GoalEvidence`, its
verdicts and its invalidation (A4); the plan's own step fields (A5); which user acts open an
attempt (A2 and A3, by ADR-0249 §5). §19 lists what it declines, each with what fires it.

## Decision

### 1. `Authorization`: a durable row proposed before the question and settled by the answer

> **Normative.** `core/types.py` gains **`Authorization`**, a frozen model with
> `extra="forbid"` whose fields are exactly: `id`, a `DurableIdentifier`; `goal`, an
> `Identifier`; `tool`, a `ToolDefinition`; `account`, a `BoundAccount`; `destinations`, a
> non-empty, duplicate-free `tuple[CanonicalDestination, ...]` in
> `EgressBinding.canonical_destination_set`'s one canonical order; `origin`, an
> **`AuthorizationOrigin`**; `coverage`, a possibly-empty
> `tuple[CoverageMember, ...]`; `proposed_at`, a `UtcInstant`; `expires_at`, a `UtcInstant`
> **strictly after** it; `confirmation`, a `DurableIdentifier | None`; `supersedes`, a
> `DurableIdentifier | None`; `disposition`, an **`AuthorizationDisposition`**; and
> `settled_at`, a `UtcInstant | None`. The field list is **closed**, and a lane adding a member
> is changing this decision rather than implementing it.

> **Normative.** **`AuthorizationOrigin` is a `StrEnum` valued by lower-cased member name and
> closed at exactly two members**: **`CONFIRMED`** — the authority was put to the user as a
> question about a concrete call and answered (§1's path (i)) — and **`OPENING_ACT`** — the
> authority was opened by a recorded instruction with no question put (path (iii)). **A
> correction transcribes it unchanged** (path (ii)), so the fact survives any chain of
> corrections, and **§6's recipient recheck is stated over it** rather than over a shape a
> correction changes. The vocabulary is added to and never renamed.

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
> `SUPERSEDED` where that row still stands `ESTABLISHED` at that instant (below). **There is no other mutation and no `update`**: a settlement moves one field
> and its instant, exactly as `ParkedRead`'s does, and the record's coverage, basis, account,
> destinations and expiry are never edited.

> **Normative.** **An expiry is settled and is never inferred**, which is ADR-0244 §10's
> mechanism: a `PROPOSED` row whose `expires_at` is at or before the clock's reading is settled
> `EXPIRED` by the **first operation that reads it**, and there are exactly two — a `live_for`
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
> at or after its `settled_at` and strictly before its `expires_at`.** **The lower end is stated
> because the clock can move backwards** — an operator correction, an NTP step — and a record
> the store called live but whose `settled_at` is after the ruling's `decided_at` is one §7's
> trail then **refuses as backdated**, so the policy would report an authority the dispatch
> could not use and the step would die at the write rather than at the ruling. Equality is
> permitted at the lower end, which is §7's own discipline for the same comparison one component
> over. **The listing's `live` (§11) is the same predicate**, taken against the one clock reading
> the engine makes. `PROPOSED` is **never** live, and no clause of this
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

> **Normative — there are exactly three ways a row is written and no fourth.**
>
> - **(i) Proposed against a `CONFIRM`.** `confirmation` names the recorded `CONFIRM` the
>   question rode, `disposition` is `PROPOSED`, `proposed_at` is that decision's `decided_at`,
>   and the row is settled by the answer; `origin` is **`CONFIRMED`**, because the destination
>   set is named in the question the user answers (ADR-0148 §8's fourth clause). **This is the
>   only path that may create a member,
>   widen a bound, set `destinations`, set `account`, set `tool` or set `expires_at`**, because
>   it is the only one on which the user is shown what they are being asked (§11). It **may**
>   carry `supersedes`, naming **any `ESTABLISHED` row of the same `goal` and the same
>   declaration `id`, live or expired**. **The proposal retires nothing**: the named row is
>   settled `SUPERSEDED` in the same write as this row's `ESTABLISHED` settlement **where it
>   still stands `ESTABLISHED` at that instant**, and is left exactly as it stands where it
>   does not (the conditional-supersession clause below). **That is what renews an authority
>   whose expiry has passed** as well as what widens a live one: the predecessor is retired and
>   the replacement established in one write, so the uniqueness rule below is never momentarily
>   false and no authority has to be cleared out of the store by hand.
> - **(ii) A correcting instruction.** A later recorded turn of the same goal whose span names
>   an argument a **live** row of that goal already carries a member for — live, because a
>   correction transcribes the predecessor's `expires_at` and correcting an authority that has
>   already lapsed would produce a row born expired. It writes a row with
>   `confirmation` **unset**, `supersedes` naming that row, `disposition` **`ESTABLISHED`**
>   directly and `settled_at` equal to `proposed_at` — the recorded turn's instant — and
>   settles the superseded row `SUPERSEDED` **in the same write**. **Every member of the
>   superseded row that the correction does not replace is carried forward byte for byte, with
>   its own basis** (§8), and `goal`, `tool`, `account`, `destinations`, `expires_at` **and
>   `origin`** are **transcribed unchanged**. **Transcribing `origin` is what keeps §6's
>   recipient recheck alive through a correction**: a correction supplies no recipient authority
>   of its own — it may not touch `account` or `destinations` at all — so a chain of corrections
>   over an opening act is still an authority resting on someone else's grant, and the row says
>   so.
>
> - **(iii) An opening act.** A recorded turn of the goal whose span states a fixed value or a
>   bound over an argument of the request being built, where **no** row of that goal and that
>   declaration `id` stands `ESTABLISHED`. It writes a row with `confirmation` **unset**,
>   `supersedes` **unset**, `origin` **`OPENING_ACT`**, `disposition` **`ESTABLISHED`** directly
>   and `settled_at` equal to `proposed_at` — the recorded turn's instant — and **retires
>   nothing, there being nothing to retire**. It **may** set `tool`, `account`, `destinations` and `expires_at`, because there
>   is no earlier row to transcribe them from — **but only where the recipient is already
>   authorised by a recorded act of the user** (the clause below), because copying an account
>   and a destination set off the request would let the selection authorise the recipient. Every
>   member it carries is minted by §10's resolutions from that turn's own span under §9's three
>   clauses entire. **A row carries members for the arguments of its *own* declaration that the
>   act's words bear on, and for no others** (§9 clause (ii)) — so one act opening rows for two
>   declarations may leave them carrying **different bounds for an argument of the same name**:
>   *"up to fifty pounds for the train and a hundred for the hotel"* fixes two amounts, and §2's
>   rule that no two members of a record name one argument is what makes two rows the only
>   representable answer. **The row is written
>   by `orchestration` when the goal's first request reaching that declaration is built, before
>   `ActionPolicy.decide` is called and before any `CONFIRM` about a concrete call exists** —
>   the declaration, the account and the destination set are not knowable at the turn itself
>   and `Authorization`'s field list is closed over all three, so the **act** is what
>   authorises and the binding is only what the row is written against.
>
> A row carrying `confirmation` unset **and** `supersedes` unset carries a **non-empty**
> `coverage`, refused at construction otherwise: an opening act that fixed nothing is not an
> act of the user, and an empty `coverage` is only ever a path-(i) proposal about an
> argument-free call (§11). A row carrying `confirmation` is **written** `PROPOSED` and reaches
> every later disposition through `settle` alone; a row carrying `confirmation` **unset** is
> written `ESTABLISHED` with `settled_at` equal to `proposed_at` — each a rule of the write
> path and not of the type, for the reason below.

> **Normative — a path-(iii) row is written only where the **recipient** is already authorised
> by a recorded act of the user, and it never supplies that authority itself.** An opening act
> bounds **argument values**; it says nothing about **who may be reached**, and a row whose
> `account` and `destinations` were copied from the request the system was about to make would
> let the **selection** authorise the recipient — which ADR-0148 §3's second clause forbids in
> terms, in its *"a tool's own declaration"*, *"a configured base URL or host"* and *"an
> allowlist the system assembled"* limbs. So `orchestration` writes a path-(iii) row **only**
> where the request's canonical destination set is covered by a recorded act of the user about
> that recipient, taken over the request being built and read from the seams that already hold
> such acts:
>
> a **live `RecipientGrant`** covering it on ADR-0193 §3's comparisons — the declaration by
> value, the `BoundAccount` by value, and every member of the request's canonical destination
> set a member of the grant's.
>
> **Where none does, no path-(iii) row is written.** The request is ruled with no standing
> route from that act, and the user is asked — by a `CONFIRM` that names the destination set
> (ADR-0148 §8's fourth clause) and whose answer proposes a **path-(i)** row. **That row carries
> the earlier act's bounds**: the completeness condition below is stated over *"the user's own
> recorded words of this goal"* and §8's basis names *"the recorded conversation turn the
> coverage member rests on"* — any turn of the goal and not only this one — so the confirmation
> asks about the **recipient** and never asks the user to repeat the **bound**, which is the
> whole of the owner's Q1 direction.

> **Normative — the write's read is `orchestration`'s.** Whatever writes the row is constructed
> with a `RecipientGrants` beside the store it already holds; **one constructed without it
> writes no path-(iii) row at all**, which is the fail-closed default and the same shape §6
> gives a policy holding no `GoalAuthorizations`. It calls `covering` **once**, over the request
> being built, before the ruling — ADR-0193 §7's at-most-one-read-per-seam-per-ruling is a rule
> about the ruling and this read is before it.

> **Normative — an opening-act row is told apart from the row alone, and it is the one row route
> (d) will not carry by itself.** A row is an **opening-act row** where its `origin` is
> **`OPENING_ACT`** — read off the row, with **no store read and no walk back through a chain**,
> which is §7's own discipline for a discriminator. **The pointer shape is not the test and must
> not be used as one**: a path-(ii) correction of an opening act carries `supersedes`, so a rule
> stated over *"both pointers unset"* would lose the recipient dependency at the first
> correction — an authority resting on someone else's grant would outlive its revocation
> because the user said *"make it Sunday"*. `origin` is transcribed by every correction and is
> changed by exactly one thing: **a path-(i) supersession**, where the user is asked again, is
> shown the destination set, and answers — at which point the replacement is `CONFIRMED` and the
> dependency is genuinely discharged.

> **Normative — the recipient authority an opening act rested on must still stand at every
> dispatch, and route (d) on such a row re-takes it.** On an opening-act row, route (d) covers a
> request only where, **in addition** to §3's six conditions, `RecipientGrants.covering` answers
> a **live** grant covering that request on ADR-0193 §3's comparisons. **Where it does not — the
> grant lapsed, the user revoked it, or it no longer covers this destination set — route (d)
> does not cover**, route (b) does not either (it needs the same grant), and the ruling is the
> `CONFIRM` the table reached. So **withdrawing the recipient grant ends the authority at the
> next dispatch**, exactly as §13 promises of a revocation of the authorization itself, and the
> grant's own expiry bites without being copied anywhere. **An opening act supplies no recipient
> authority and this is what makes that true over time** rather than only at the instant of the
> write — the alternative, a row that outlived the grant that permitted it, would extend the
> user's recipient act beyond what they recorded, which is what ADR-0148 §3's second clause
> forbids.

> **Normative — and the grant's own instant is not copied onto the row.** A path-(iii) row's
> `expires_at` is §12's ladder and nothing else. **The recheck above is what enforces the
> grant's lifetime**, at every dispatch and over the live seam, so a second copy of the grant's
> instant would buy nothing and would go stale the moment the user extends, replaces or widens
> that grant — two shapes of one fact, which is what ADR-0150 is named after. **What the row
> states is the horizon of the *user's own act*, and what the seam decides is whether the
> recipient act still stands**; they are two facts and the row carries only its own.

> **Normative — the grant is a condition on the route and never a second contributor to the
> ruling.** `authorised_by` still names **one** row, `authorised_subject` is still that row's
> subject digest, `authorised_goal` is still its goal, and §7's four-route partition is
> untouched — a route-(d) row reads exactly as it did. **No component composes coverage across
> two records** (§1): the grant decides nothing about an argument and the record decides nothing
> about a recipient. What changes is §6's ordering for this one row shape: the grant seam is
> consulted **once, before route (d) may answer**, and on every other row shape route (d)
> answering still calls it **zero** times.

> **Normative — path (iii) is the owner's upfront permission, and it is what makes the user's
> own instruction sufficient.** *"You may spend up to fifty pounds on this"*, said while the
> goal is being understood and before any concrete call exists, is a recorded act that fixes a
> bound; asking the user to confirm the first call inside it would be asking them to repeat an
> instruction they have just given, which is the interruption the owner's Q1 direction rules
> against and which §5 already refuses for a **correction**. Path (iii) is that same refusal at
> the **opening** of the authority rather than at its revision, and it rests on exactly the same
> three things: the basis triple (§8), the interpretation that may only narrow (§9 clause (ii)),
> and the ambiguity test that asks rather than guesses (§9 clause (iii)).

> **Normative — the two safeguards on path (iii), and neither is new machinery.**
>
> - **What was recorded is restated to the user on the turn that recorded it.** The act is a
>   revision of the goal's interpretation — the bound is an element of its `constraints` — and
>   **§11 gives it a carrier of its own**, `TurnOutcome.authorizations`, composed by
>   `orchestration` from the rows it wrote with no model writing it, carrying one view per
>   authority opened — its declaration, its bounds with the user's own spans, its expiry and its
>   revocation handle. **It does not ride ADR-0250 §5's announcement rule**,
>   which is silent on a grounding-only revision and whose carrier holds neither a coverage nor
>   an expiry — §11 states the whole of it and §18 records the one count that moves. The user
>   reads what was recorded on the turn they said it, which is what makes an authority
>   established without a question visible at the moment it comes into being.
> - **A materially ambiguous bound is asked about and is never guessed.** Where the span admits
>   more than one admissible value the resolution is not taken, **no member is minted and no row
>   is written** (§§9, 10), and the question is put under **ADR-0250 §6's three conditions and
>   no fewer**. A bound that is not material by that section's own code test is not a question
>   this decision invents.
>
> **And the row is revocable and visible from the instant it is written**: it is `ESTABLISHED`,
> so `standing(goal)` returns it, §11's listing renders its coverage, its spans and its expiry,
> and `revoke_authorization` reaches it on §1's one edge out of `ESTABLISHED`. **An authority
> established without a question is one the user can see and withdraw before anything is
> dispatched under it**, which is what makes the absence of the question safe rather than
> merely quiet.

> **Normative — the four conditions below govern path (iii) too, read over the request being
> built rather than over a recorded `CONFIRM`**, with the goal, the egress binding, the
> completeness of the coverage and §12's ladder each taken exactly as stated — **and the
> recipient precondition above beside them**, which path (i) does not need because its own
> confirmation names the destination set. Failing any of the five, **no row is written**, the
> request is ruled with no standing route, and the concrete call is confirmed under route (a) —
> which is the path that exists today and is unchanged.

> **Normative — which `CONFIRM` proposes a row, stated because §11's absence rule needs it and
> because *"when a `CONFIRM` is put"* (§15) is not a rule a lane could apply.** `orchestration`
> writes a path-(i) proposal for a recorded `CONFIRM` where **all four** hold:
>
> - the request carries a `goal` (§6) — a request carrying `None` reaches route (d) in no case,
>   so a row proposed against one could authorise nothing;
> - the request is an **egress call**, its `egress_binding` not `None` — every clause of this
>   decision is scoped to one (§19);
> - and the coverage the row would carry is **complete for this request**: every
>   **user-facing** argument of the request (§3) is named by a member §10's resolutions minted
>   from the user's own recorded words of this goal, **or** the request carries no user-facing
>   argument at all;
> - and **§12's ladder yields an `expires_at`** — the act states an instant, or the goal carries
>   a `deadline` strictly after `proposed_at`. There is no deployment figure to fall back on
>   and none is invented.
>
> Failing any of the four, **no row is proposed**, `Confirmation.authorization` is absent
> (§11), and the answer establishes nothing: the `CONFIRM` is resolved and the one call is
> authorised by ADR-0148 §3's route (a), which is the path that exists today and is unchanged.

> **Normative — the completeness condition is what makes §11's projection honest, and the cost
> it carries is the one the Consequences already state.** §3 requires **every user-facing**
> argument of a request to be covered, so a row naming only some of them could never cover a
> later call of
> that goal and the projection would tell the user their answer established an authority that
> authorises nothing. Proposing only a complete row is what makes *"answering this question
> would establish a standing authority"* true whenever it is shown. The cost is that a
> declaration carrying an argument no act could reasonably have named is one whose calls always
> ask — which is stated rather than hidden, and is the same cost §3's every-argument rule
> already carries.

> **Normative — the proposal reads none of §6's floors, and that is deliberate.** Conditions 3,
> 4 and 5 of route (d)'s reachability are taken over a **concrete request** at every dispatch
> (§6, §13). A row proposed against a request whose binding carried
> `planned_with_external_content` authorises no such dispatch — the floor is unrelaxed and is
> re-taken — and may still cover a later request of that goal that carries none. Putting those
> conditions at the write would refuse an authority on the strength of one call's taint, which
> is a different rule from the one §6 states and a weaker one.

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
>   rule that a row carrying **neither** `confirmation` **nor** `supersedes` carries a
>   **non-empty** `coverage` — path (iii)'s invariant, which replaces the pairing rule an
>   earlier draft stated and which an opening act satisfies — a `CoverageMember`'s two
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

> **Normative — the supersession is conditional on the named row still standing `ESTABLISHED`,
> and the condition is read at the instant of the settlement rather than at the proposal.** A
> path-(i) row's `supersedes` states **what approving it would replace**, and between the
> proposal and the answer the named row may leave `ESTABLISHED` by an act of the user's own — a
> revocation (§11) — or by a third row's supersession. So `settle` reads that row **inside the
> same indivisible step** and takes one of exactly two arms:
>
> - **the named row still stands `ESTABLISHED`** — it is settled `SUPERSEDED` in the same write
>   as this row's `ESTABLISHED` settlement, which is §5's *"in one write"* unchanged;
> - **the named row has already left `ESTABLISHED`** — this row is settled `ESTABLISHED` all
>   the same, and **the named row is left exactly as it stands**, in whatever retired
>   disposition it reached.
>
> **The second arm writes nothing to the named row at all**, so no edge leaves a retired
> disposition, the transition graph above is unamended, and `AuthorizationSettlement` gains no
> member. **The grounds are that the approval is the user's later and more explicit act**, taken
> with §11's full projection in front of them; that the uniqueness rule the supersession exists
> to protect is already satisfied, since the named row is retired and no `ESTABLISHED` row of
> that pair remains; and that refusing the approval instead would let an earlier revocation
> **silently void the answer to a question still standing**, leaving the user with neither
> authority after they approved one — the opposite of §5's supersede-at-the-act reasoning and
> the opposite direction from §5's *"a refused widening is not a revocation of what the user
> already authorised"*. **`WOULD_DUPLICATE` does not fire on this arm** for the same reason: no
> other `ESTABLISHED` row of that goal and declaration id would remain.

> **Normative — and where a *third* row of that pair does stand `ESTABLISHED`, the settlement
> is refused.** A row established after the named one was revoked is a row this write's
> `supersedes` does not name, so the settlement answers **`WOULD_DUPLICATE`**, nothing is
> written, and the user is asked about the concrete call. That is §16's member doing exactly
> what it exists for, and it is why the arm above is stated over *the named row* and never over
> *the pair*.

> **Normative — at most one `ESTABLISHED` row per goal and declaration `id`, enforced without a
> clock.** `record` **refuses** a write that would leave two rows of one `goal` and one
> declaration **`id`** both `ESTABLISHED`. **The key is the id and not the declaration by
> value**, which is *stricter* than a value key — every pair the value key would refuse the id
> key refuses too, and it additionally refuses a second row about an edited declaration of the
> same id. That is what makes §16's `live_for(goal, tool_id)` answer with one row or none, and
> it is what §6's bar rests on; the argument of the clause above is unweakened, because the
> declaration is still embedded whole and coverage is still compared by value (§3). The refusal
> is stated over the **disposition** rather than over liveness, so the write path reads no
> clock, which is ADR-0193 §1's duplicate-refusal discipline. **And `live_for` raises
> `AuthorizationError` where more than one live row of that goal and declaration id would
> answer** — a state this refusal makes unreachable, refused at the read as well because a
> query that chose between two would be the composition §5 declines, and **raised rather than
> answered `None`** because `None` is this seam's word for *"the store holds no live record"*
> and two rows are not none of them. §16's fault clause then takes §6's bar, so an integrity
> failure asks rather than authorising a request neither row covers.

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
> 6. and **the request's user-facing arguments and the row's coverage name the same set of
>    keys**, and every user-facing argument of the request is covered by the per-argument rule
>    below. **A declaration that classifies no argument system-supplied has every argument
>    user-facing**, and condition 6 then reads exactly as it would without the classification.
>
> A row that fails any of them covers nothing about that request.

> **Normative — the declaration classifies each argument, and only a user-facing one needs
> coverage.** `ToolDefinition` gains **one** field: **`system_supplied: tuple[EncodableText,
> ...]`**, possibly empty, duplicate-free, **defaulting to the empty tuple**, naming the keys of
> `parameters` the **system** fills — an idempotency key, a client reference, a locale. Every
> key it does not name is **user-facing**. Each member is a key name at depth one, exactly as
> `CoverageMember.argument` is (§2). This is a **BREAKING** contract change to a `core` type
> under golden rule 5 and is flagged as one.
>
> **This narrows ADR-0016 §1's required-field clause by one field, and the narrowing is stated
> rather than argued around.** That clause is unconditional — *"Every field that a permission
> decision depends on is required"* — and a permission decision does depend on this one, since
> it moves §3's condition 6 and §6's bar. So the exception is **recorded** (§18) rather than
> claimed away. **The grounds are the clause's own reason, which does not reach this default.**
> §1's reason is that *"A default is a claim"* and that the natural-looking one — the empty
> tuple for `reads`/`writes` — is *"exactly the false statement a forgetful integration author
> would ship"*. Here the empty tuple makes the **opposite** claim: an unclassified argument is
> user-facing, so a declaration that says nothing needs coverage for **every** argument and asks
> where it has none. **It costs a question and can never authorise a call**, which is the one
> direction §1 exists to protect. **The alternative was making the field required**, and it is
> declined because it would oblige every declaration in the tree and every fixture to write
> `system_supplied=()` for a fact that is empty on almost all of them, buying nothing in the
> direction §1 cares about — a cost with no safety return is not what an unconditional rule is
> for, and the honest move is the recorded exception rather than a claim that no exception is
> needed.

> **Normative — a row's coverage names no system-supplied argument.** A `CoverageMember` whose
> `argument` is a member of that row's own `tool.system_supplied` makes the row **not
> constructible**. The row embeds the declaration whole (§1), so both facts are on the row and
> this is a rule true of every state the row is ever persisted in — a **model validator**, by
> §1's division of refusals.

> **Normative — a system-supplied argument is filled by the system, never by the model, and one
> the model could influence is refused rather than asked about.** `orchestration` supplies the
> value for every key the declaration classifies system-supplied. **Where a plan step's own
> arguments name such a key at all, the request is not built**: the step does not dispatch, no
> ruling is sought and **no `CONFIRM` is put**, on ADR-0148 §1's rule that a request that cannot
> be completed is refused *"**before** the ruling"* with no ruling sought. **A user is never
> asked to approve an idempotency key**, and a model that reached for one is a fault and not a
> question — ADR-0249 §7's *"A model may never clear a permission, a coverage test, a
> prerequisite or a dependency"* read at the other end, where it may not **supply** one either.

> **Normative — a system-supplied argument is filled before the candidate fit test, so every
> check reads the call that would actually be made.** ADR-0144 §7 decides eligibility by
> evaluating each candidate's schema against **the step's parameters**, before any ordering key
> and before the request is built; a declaration whose schema **requires** a key it classifies
> system-supplied would then be ineligible for every step, because the clause above forbids the
> model naming that key at all. So `orchestration` fills that candidate's system-supplied
> arguments **before** the fit test, and the eligibility evaluation is taken over **the step's
> parameters merged with them**, per candidate. **`core`'s one evaluator is unchanged and no
> second comparison is written** (ADR-0145 §2): what moves is the mapping it is called with, not
> the rule that reads it. The merge is `orchestration`'s alone, it names **only** keys that
> candidate's own declaration classifies system-supplied, and **it overwrites no step
> parameter** — the refusal above makes the two sets disjoint by construction, so there is no
> precedence rule to remember. §18 records what this takes from ADR-0144 §7.

> **Normative — §14's check 2 reads the same way.** Every argument the declaration's schema
> requires is a literal on the step, filled by a `ResultReference` (ADR-0253 §6), **or
> classified system-supplied on that declaration and filled by `orchestration`**. **A key that
> is none of the three is still `UNMET_DEPENDENCY`'s neighbour and still refuses the step**, and
> ADR-0145 §1's construction-time schema check is unmoved: it runs over the **final** arguments,
> where a system-supplied value is present like any other.

> **Normative — the classification narrows what is compared and nothing else.**
> `ActionRequest.parameters_digest` is taken over **every** argument, system-supplied ones
> included (ADR-0021 §1), so a system-supplied value still cannot move between the ruling and
> the dispatch and `rebind` still refuses a binding that changed (ADR-0152 §7). §6's bar takes
> condition 6 and therefore reads user-facing arguments alone — which is the whole of
> *"implementation choices must not become user-facing questions"* — and **the bar stays
> monotone**, because `system_supplied` is a list of key names and no `risk_level`,
> `reversibility` or `discloses` edit moves it. **No comparison consults a schema**: §4's
> no-schema clause binds entire.

**The classification is a field of the declaration beside `parameters_schema` and not a keyword
inside it, and the reason is ADR-0145's own.** §5 of that ADR reads one dialect and states the
hazard in terms — *"2020-12 ignores keywords it does not know"*, so a bound written in a keyword
the reader does not know is *"silently dropped"* and *"the tool receives a payload the author
believed was refused"*. A classification carried as an `x-` keyword would be dropped by exactly
that mechanism, and the failure would be silent and in the permissive direction: an argument the
author marked system-supplied would read as user-facing — which is at least fail-closed — while
the reverse spelling of the same mistake would not be detectable at all. ADR-0145 §9 is the
second reason: *"An absent schema declares no constraint"*, so a tool declaring no schema could
classify nothing, and this decision would have made the classification unavailable to exactly
the declarations that most need it. And §4 above forbids reading a schema keyword to establish
an association a row must name; a typed field states the fact where every other declared safety
fact of a tool already lives.

> **Normative — condition 6 is stated in both directions, because an omission is a change as
> much as an addition is.** A **user-facing** argument the request carries that the row's
> coverage names in no member is not covered, which is the direction §3 has always had. **And an argument the row's
> coverage names that the request does not carry leaves condition 6 unsatisfied too**: an act
> that fixed `refundable_only` to `true` authorised a call *carrying* that value, and a call
> that omits it is a different call — ADR-0145 inserts no schema default, so nothing downstream
> restores it, and the omission would silently buy whatever the service does when the field is
> absent. **There is no default, no wildcard, no "not sent therefore unconstrained" and no
> omission that reads as consent**, which is the per-argument rule's own sentence read from the
> other side. The set comparison is over **keys** and the per-argument rule is over values, and
> together they are the whole of condition 6.
>
> **The empty case stays exactly as §1 permits it**: a row with `coverage=()` and a request
> carrying **no user-facing argument** name the same set — the empty one — so condition 6 holds,
> which is the one request such a row covers. A request carrying system-supplied arguments and
> no others is such a request.

> **Normative — where each of the six is taken, because the seam is keyed rather than asked.**
> `GoalAuthorizations.live_for(goal, tool_id)` (§16) answers conditions **1 and 2** and the
> **id half** of condition 3: it returns the row of that `goal` whose declaration's `id` equals
> `tool_id`, whose `disposition` is `ESTABLISHED` and whose `expires_at` is strictly after the
> one instant it read, and `None` where there is none. The **policy** takes the rest of
> condition 3 — the declaration compared **by value** — and conditions **4, 5 and 6**, over the
> row it returned. **Coverage is still their conjunction and no component treats either half as
> the whole**, which is ADR-0193 §3's own sentence read onto this split; that section splits its
> five the same way, four at the seam and the fifth at the policy. **The split is what lets a
> policy tell *no record* from *a record that did not cover***, which §6's bar needs and which a
> single `covering(request) -> Authorization | None` could not give it: both answers are `None`.
> **§6's bar takes condition 6 and no other**, over that same row: the declaration comparison
> is route (d)'s and is never the bar's, for the monotonicity reason §6 states — a restriction
> whose answer turned on comparing declarations would move with a severity edit in one
> direction or the other, and ADR-0021 §5 forbids both.

> **Normative.** **Conditions 3, 4 and 5 are ADR-0193 §3's, taken over recorded values and
> never inferred; conditions 1, 2 and 6 are this decision's.** ADR-0193 §3's liveness condition
> is not condition 1 — that section's liveness is its own store's and §1 defines this one — and
> its fifth comparison, the external-content bar, is not a coverage condition here but a
> reachability condition on route (d) (§6), which is stricter rather than weaker. No component
> widens an authorization by folding case, by matching a domain, by treating an account member
> as covering a recipient member or the reverse, by treating a row's larger destination set as
> covering a request's under any relation other than membership, or by re-canonicalising either
> side. **A canonicaliser is ADR-0148 §2's, at the
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
> **A user-facing argument the row names in no member is not covered**, and an argument the row names in a
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

> **Normative — what "including that one" excludes, stated because two readings are available
> and the corpus has already chosen one.** ADR-0021 §5's obligation ends: *"Monotonicity is
> stated over the outcome and is unaffected by `authorised_by`: a user authorisation is an input
> the policy was given, not a severity axis, and the comparison holds requests equal in every
> other respect **including that one**."* So a pair of requests differing only in `risk_level`,
> one of which a stored record covers and the other of which it does not, is **outside** the
> comparison: one carries a user authorisation and the other carries none, which is the
> respect §5 names. **That is not a reading this decision invents.** ADR-0193 §3's second
> comparison is *"the request's `tool` equals the grant's `ToolDefinition` by value"*, so route
> (b) has exactly this shape — a grant established about a `MEDIUM`-risk declaration covers no
> `LOW`-risk request of the same tool id and covers the `MEDIUM` one — and that section rules
> the question in terms: *"ADR-0021 §5's monotonicity obligation is unchanged and is not stated
> over this … with the grants in the store held equal."* **Route (d) takes that ruling unchanged
> and adds nothing to it**, and §7 of this decision is why it must: a record established about
> one declaration authorising a call made under another is the rebinding #54 closed, and a
> standing record is exposed to it for as long as it is live.

> **Normative — so no supersession of ADR-0021 §5 is owed, and the alternative is named rather
> than left implicit.** No sentence of §5 is read more widely or more narrowly than it now
> holds; what changes is that a second kind of record can now be the authorisation input §5's
> last sentence holds equal. **The other reading — that the comparison holds only the store
> equal, so a severity edit that moves a request into or out of coverage is in scope — would
> condemn ratified route (b) on the same facts**, and a decision taking it would be amending
> ADR-0193 §3's comparison as well as this one. That is a decision with its own argument and
> its own arms, and it is not this one. **§6's bar is a separate matter and is monotone
> outright**: it reads no field of the declaration, so it stays on the safe side of the
> question whichever reading is right.

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

> **Normative — what the ruling's `reason` says when coverage fails, and it is ADR-0145 §8's
> discipline one clause over.** It **never** reproduces an argument's **value**, the bound, the
> record's id or its digest: a reason is carried on a durable `PermissionDecision` that holds
> `parameters_digest` and not `parameters` (§7), and quoting a value would put into the trail
> exactly what that omission keeps out. **And it names an argument's key only where the
> declaration's `parameters_schema` itself names that key.** ADR-0145 §8 rules that a message
> about arguments *"renders any part of the parameters — neither a value nor a key"* except what
> *"the schema itself names"*, on the ground that *"a key can be data"* — a mapping the schema
> does not describe can be keyed by an address or an identifier — and the same hazard is here,
> because §2's `argument` is a key of `parameters` and nothing requires the schema to declare
> it. So a key the schema declares is named; **a key it does not is described by its kind and
> not quoted**, exactly as ADR-0145 §8 describes an `additionalProperties` violation by keyword
> and location rather than by key. Where several arguments fail, they are named in the
> declaration's own schema order, and an undeclared one is counted rather than listed.
>
> **The three failures are told apart, whichever way the key is rendered**, because they are
> different facts about what the user authorised and §3's condition 6 keeps them apart: an
> argument the record's coverage names in **no** member; an argument a member names that the
> request **omits**; and an argument whose value the member's comparison **refused**.

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
> the store refuses it, no row is written, and the concrete action reaches **no standing route
> at all** and is confirmed. **§6's bar is what makes that true rather than merely intended**:
> the live row still names the argument the request now exceeds, so the bar fires and neither a
> recipient grant nor the configured-provider route discharges it. That is the owner's *"Ask
> only when the concrete action introduces something not already covered, such as additional
> costs or materially different terms"*, and it is that sentence read as a refusal at the write
> **and** as a refusal at the ruling, rather than as advice at the prompt.

> **Normative — and a widening the user then confirms is established, by path (i) carrying
> `supersedes`.** The confirmation that asks about the wider action proposes a row naming the
> live row in `supersedes`; approving it settles the new row `ESTABLISHED` and the old one
> `SUPERSEDED` **in one write**, so the uniqueness rule (§1) is satisfied without a separate
> retirement step and there is never an instant in which two rows of one goal and declaration
> are both established. **Where the named row has already left `ESTABLISHED` before the answer
> — revoked by the user, or superseded by a third row — the approval still establishes the new
> row and leaves the named one exactly as it stands** (§1's conditional-supersession clause),
> because the user's approval is their later act and the uniqueness it protects is already
> satisfied. **Declining it settles the new row `DECLINED` and leaves the old one
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

### 6. Route (d) on ADR-0148 §3, the five conditions it relaxes none of, and the bar before every standing route

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
> `GoalAuthorizations` (§16), beside the `RecipientGrants` and the `ConfiguredSearchDestination`
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
> 3. its binding does **not** carry `planned_with_external_content`, **or** the row the one
>    seam read returned covers the request under §3 **in full** (the lineage-discharge clause
>    below). **ADR-0193 §4's floor is unmoved**: no `RecipientGrant` covers such a call,
>    whatever this discharge does for route (d);
> 4. its binding's `coverage` is `SpanCoverage.NOT_COVERED`. **ADR-0233 §9's second clause
>    binds route (d) entire, unrelaxed**;
> 5. the outcome the table reached is `CONFIRM` and the **only** clause that fired is the
>    disclosure floor. An `UNKNOWN` cost still draws `CONFIRM`; so does a `risk_level` or a
>    `reversibility` at the policy's own threshold; and a threshold `DENY` still stands and
>    reaches no route at all.
>
> **Conditions 3 and 4 are taken over the binding and are never read off
> `_only_the_disclosure_floor`'s answer.** That predicate carries ADR-0247 §3's disjunct — the
> limb reads *"or the request is at the configured provider"* — so it answers `True` for a
> tainted request at the configured provider, and a lane that reused its answer as route (d)'s
> third and fourth conditions would relax on route (d) something this section relaxes only on
> its own terms. **Route (d) re-takes both over the binding**: condition 4 in its strict form,
> and condition 3 with the one limb the clause below states and no other. A request at the
> configured provider carrying covered content reaches route (d) in no case, and one carrying
> `planned_with_external_content` reaches it only where a record covers it in full. **ADR-0247
> §3's retirement is for the configured provider's own route and for nothing else**, which that
> section states in terms, and route (d) inherits none of it.

> **Normative — ADR-0181 §5's lineage floor is discharged for a request a live record covers in
> full, and for no other.** Where §3's **six** conditions all hold over the row the one
> `live_for` read returned, route (d) answers `ALLOW` **despite the binding carrying
> `planned_with_external_content`**. The ground is the owner's, and it is ADR-0247 §3's own
> reasoning one authority over: where **every user-facing argument and every member of the
> request's canonical destination set** are covered by the user's own fixed values and permitted
> ranges, outside content **cannot have steered anything the user did not bound** — it may at
> most have produced a value already inside a bound the user set, which §3's negative arm
> already states (*"a value a tool produced can **satisfy** a bound the user set and can never
> **supply** one"*). **Partial coverage still asks**: a destination outside the row's set, a
> user-facing argument the row names in no member, and an argument whose value the member's
> comparison refused each leave condition 6 or condition 5 unsatisfied, so the row covers
> nothing, the floor binds unrelaxed and the ruling is the `CONFIRM` the table reached.

> **Normative — the coverage limb is not extended to ADR-0233 §9's second clause, and the
> asymmetry is deliberate.** Condition 4 — the binding's `coverage` is
> `SpanCoverage.NOT_COVERED` — binds route (d) **entire and unrelaxed**. ADR-0233 §9's second
> clause is absolute about its class — *"**no** standing authorisation, standing policy,
> standing recipient grant, configuration, connected account, tool declaration or approved
> payload description covers such a call, **ever**"* — and this decision takes it as written;
> the lineage floor carries no such sentence, and ADR-0247 §3 already retired the two
> **separately** and said in terms that retiring one without the other changes nothing for its
> own route. Here they are genuinely separable: covering every argument and every destination
> says something about what outside content could have **steered**, and nothing whatever about
> a span composed over covered content. §19 books the decision that would take the second
> clause head-on, and **this is still not that decision**.

> **Normative — `_only_the_disclosure_floor`'s lineage limb gains a third disjunct, and that
> disjunct admits a request rather than deciding it.** ADR-0247 §3 restated that limb as *"the
> binding does not carry `planned_with_external_content`, **or** the request is at the
> configured provider"*. It becomes *"…, **or** the request carries a `goal` and the policy
> holds a `GoalAuthorizations`"*. **Where the third disjunct is what admitted the request, route
> (d) is the only route that may answer**: route (c) does not, because ADR-0247 §3's retirement
> is for a `WEB_SEARCH` at the configured provider and for nothing else; route (b) does not,
> because ADR-0193 §4 is unmoved and **no** `RecipientGrant` covers a tainted call. So a request
> the goal's record does not cover in full reaches **no** route at all, the `CONFIRM` stands
> with the lineage floor still fired, and `RecipientGrants.covering` is called **zero** times.
> **The coverage limb gains no disjunct**, and the predicate is not made to depend on a seam
> read: it admits, and §3's six conditions decide.

> **Normative — the argument-authority bar, and it precedes every standing route.** Where the
> request carries a `goal` **and** the policy holds a `GoalAuthorizations`, the policy asks that
> seam for the live record of that goal and that declaration's **`id`** (§16), and **a standing
> route is taken only on one of exactly two answers**:
>
> - **no record** — the seam read the store and holds no live row for that goal and that
>   declaration id; or
> - **a record every user-facing argument of the request is covered by** — §3's **condition 6**
>   and that condition alone, taken over the row the seam returned. **A system-supplied argument
>   (§3) is not among them and never fires the bar**, which is what keeps an implementation
>   choice out of a question put to the user.
>
> **On every other answer no standing route is taken at all**: a record some argument of the
> request is not covered by, whether it names that argument in a member the value fails **or
> names it in no member at all**; and **an answer the seam could not give** — it could not read
> the store, or more than one live row would have answered (§16). Route (c) does not answer, the
> recipient-grant seam is consulted **zero** times, route (d) does not cover, and the ruling is
> the one the table reached with no standing route — `CONFIRM` for a transmitting tool, which is
> what §13 and §14 already require of a changed argument outside coverage, what §5 promises of a
> widening the store refused, and what §9's third clause promises of *"an argument no member
> names"*.

> **Normative — the bar is stated over the arguments and over nothing else, and the line is
> ADR-0193 §5's.** It does **not** fire on the declaration, on an account the record does not
> carry, or on a destination outside the record's set. *"A grant states nothing about the
> payload and authorises no content"*, and what §5 permits a grant to authorise is a recipient
> reached through a declaration and an account — *"That is the whole of what it authorises."*
> **So the bar is exactly the conjunct no recipient authority ever reached: the payload.** The
> declaration, the account and the destination set are facts a grant is stated **about**
> (ADR-0193 §3's second, third and fourth comparisons) and a configuration is stated about, so
> a request whose only mismatch is one of those fails route (d) on §3's conditions 3, 4 and 5
> and still reaches route (c) or route (b), exactly as it does today. **A record's arguments are
> the one thing nothing else in this corpus speaks for**, and that is the whole of what the bar
> refuses on.

> **Normative — a seam the policy could not read takes the bar, and that is the one place this
> decision departs from the grant seam's discipline.** `ThresholdActionPolicy._covering`
> answers `None` on a fault because the grant seam discovers **permissions** only, and losing a
> permission can only make a ruling more restrictive. **This seam discovers restrictions as
> well**, so a fault that read as absence would turn a `CONFIRM` the bar owes into a route-(b)
> or route-(c) `ALLOW` — a transient store fault making a call *more* authorised, which is the
> one direction nothing in this corpus may fail in. So an `AuthorizationError` out of `live_for`
> is logged and **takes the bar**: no standing route, and the `CONFIRM` the request would have
> drawn had the user never authorised anything. **The fault reaches only a request carrying a
> `goal` on a policy holding the seam**, because the seam is read on no other (below), so no
> request that could not have been barred is affected by one.

> **Normative — the bar is a floor and is the stricter direction, which is what makes it
> available without relaxing anything.** ADR-0148 §8 states the two refusals every conforming
> policy owes on an egress request and adds: *"A policy may be stricter; it may not be more
> permissive than these."* The bar adds a refusal and removes none, and ADR-0148 §3's first
> clause states a **necessary** condition on an `ALLOW` rather than a sufficient one, so
> nothing about the route enumeration moves for it. §18 records the one clause it does narrow
> and shows the working for the ones it does not.

> **Normative — the bar reads no field of the declaration, and that is what makes it monotone.**
> ADR-0021 §5 obliges a policy never to answer *less* restrictively for a request of higher
> severity, comparing requests *"equal in every other respect"* with the records in the store
> held equal — and `risk_level`, `reversibility` and `discloses` are fields **of the
> declaration**. **Any rule whose answer turns on comparing declarations is non-monotone in one
> direction or the other**: keyed or tested **by value** it vanishes when an edit moves a
> request *out* of equality with the stored row, and it also vanishes when an edit moves one
> *into* equality — a request at `LOW` barred against a stored `MEDIUM` declaration would clear
> the bar on being raised to `MEDIUM`, which is the same violation from the other side. So the
> bar reads **no** declaration field at all: it is keyed on the declaration's **`id`**, which no
> severity edit moves, and its test is §3's condition 6 over the arguments, which no severity
> edit moves either. **Raising `risk_level`, `reversibility` or `discloses` therefore cannot
> change the bar's answer**, and the rest of the policy is monotone already, so ADR-0021 §5
> holds with nothing superseded.

> **Normative — the `id` is a lookup key and is never an authority, and §1's by-value rules do
> not move.** §1 embeds the declaration **whole**, §3's condition 3 compares it **by value**,
> and route (d) covers nothing where that comparison fails — a record established about one
> declaration authorises nothing about an edited one, which is §1's accepted cost in the safe
> direction and is unchanged. The id selects the row the bar tests and nothing more: no coverage
> is taken over it, no `ALLOW` rests on it, and a request whose declaration the record's does
> not equal by value reaches route (d) in no case. **What the id buys is that the bar neither
> appears nor disappears when a declaration is edited** — the row is still found, and whether
> the bar fires is decided by the arguments, exactly as it is on every other request.

> **Normative — where the bar reads, and it is the same read route (d) takes.** The policy
> calls `GoalAuthorizations.live_for(goal, tool_id)` (§16) **at most once per ruling**, and both
> the bar and route (d) are decided from the row it returns: there is no second seam read, no
> second clock reading and no cached answer. It is called **only** where
> `_only_the_disclosure_floor` holds, because where it does not no standing route is taken
> already and the bar could change no outcome; **only** where `request.goal` is set, so a
> request carrying none reads the seam **zero** times and the bar never fires on one; and
> **only** where the policy holds a `GoalAuthorizations`, a policy constructed without one
> taking the bar as never firing exactly as it takes route (d) as unreachable, which the
> constructor clause above already rules. **Those two exclusions are what bound the fault
> clause above**, and they are the same two that bound route (d).

> **Normative — the order is total, and each step answers before the next seam is consulted.**
> Route (a) is `resolve`'s and is reached by a different method. Within `decide`, and only
> where `_only_the_disclosure_floor` holds: **the bar first**, on the one `live_for` read;
> then **route (c)** (ADR-0247 §2's ordering before the grant seam, kept); then **route (d)**,
> decided from the row that same read returned; then **route (b)**. Where the bar fires, no
> route answers and `RecipientGrants.covering` is called **zero** times. Where route (c)
> answers, `RecipientGrants.covering` is called **zero** times and no ruling at the configured
> provider cites a grant, which is ADR-0247 §2's own clause unmoved. Where route (d) answers,
> `RecipientGrants.covering` is called **zero** times — **except on an opening-act row** (§1),
> where it is consulted **once, before route (d) may answer**, because such a row carries no
> recipient authority of its own and the one it rested on must still stand. **At most one
> durable read per seam per ruling and never a cached answer**, which is ADR-0193 §7's rule read
> onto the second seam and holds on both.

> **Normative — why (d) precedes (b), stated so it is a decision and not an accident.** A
> record that covers a request under both routes is a record the user made about **this goal**,
> with a basis naming the turn and the span, an expiry measured in hours and a coverage that
> names the arguments; the grant that would also cover it is a standing preference about a
> destination set, made about something else, with no basis and a longer life. Citing the
> narrower and better-evidenced authority records more and asserts less. **Neither route is
> made reachable or unreachable by the order**: a request route (b) covers and route (d) does
> not is still route (b)'s, and the reverse. **The bar is not an ordering and is not stated as
> one** — it is a refusal taken before any route is tried, and it is the one thing in this
> section that makes a request neither route's.

> **Normative.** **Route (d) is an egress route and opens nothing else.** ADR-0021 §6's
> standing grants *"for other actions"* stay deferred and unnarrowed: a decision carrying no
> `egress_binding` falls outside every clause of this ADR rather than needing an exception
> inside it, and the ADR that opens that space states its own scope beside this one. §19 names
> it with what fires it.

**What genuinely widens, flagged as such and not smuggled.** ADR-0193 §3 states five
comparisons, all over a canonical **destination set**, the declaration and the account. §3
above keeps the three that transfer and adds a kind of comparison the corpus has not had
before — over an **argument value**. That is a real extension of what a standing authority may
decide, and the three things that keep it
fail-closed are stated rather than assumed: the reading of every user-facing argument is total
and refuses
what it cannot prove (§4); the route relaxes none of the floors route (c) relaxes (above); and
the interpretation that produced a bound may narrow what the act covers and may never widen it
(§8).

**What route (d) reaches for the workflow's search-shaped steps, and what it still does not.**
A booking whose arguments were composed on a turn that read external content is now reachable —
that is the discharge above, and it is the case the milestone exists for, admitted exactly where
the user's own act bounds **every** user-facing argument and the destination set. What stays out
of reach is a request whose binding carries **covered content**: condition 4 is unrelaxed, so a
span composed over a covered supply reaches no route (d) and the user is asked, even where an
authorization covers every argument. ADR-0233 §9's second clause is absolute about that class —
*"**no** standing authorisation, standing policy, standing recipient grant, configuration,
connected account, tool declaration or approved payload description covers such a call,
**ever**"* — and ADR-0238 §7 and ADR-0247 §3 opened the **one** exception this corpus admits,
for the configured search provider and nothing else. Opening a second is a decision with its own
argument and its own arms, and it is not this one. §19 books it with what fires it.

### 7. The discriminator, and what the trail checks and cannot check

> **Normative.** `PermissionRuling` gains **one** field, **`authorised_goal: Identifier | None`,
> defaulting to `None`**, carrying the `goal` of the `Authorization` a route-(d) `ALLOW` rests
> on. A **validator** refuses it where `authorised_by` is unset — the same shape and the same
> reason as `authorised_subject`'s refusal (ADR-0193 §6): a scope for an authorisation the row
> names none of is incoherent. It is set **only** on a route-(d) `ALLOW`, and a policy sets it
> **only** to the `goal` of the record `live_for` returned, read off that record and carried
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
> **`AuthorizationResolution`** (§16) beside the `RecipientGrantResolution` they already take,
> and `record` resolves a route-(d) pointer against it. The trail therefore holds a **read and
> nothing else**: it cannot append an authorization, revoke one, enumerate the user's goals or
> erase the store. `ActionPolicy` is unchanged in signature, `AuditTrail`'s own Protocol gains
> no member, no argument and no widened return, and what ADR-0021 §4 gains is an invariant.

> **Normative — `AuditTrail.record` refuses a route-(d) row unless all ten hold.**
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
> the store returned**; and its binding's `coverage` is **`SpanCoverage.NOT_COVERED`**. **Ten,
> because the disposition check, the goal check and the `SpanCoverage` check are this decision's
> own and the other seven are ADR-0193 §6's** — the resolution read, both ends of liveness, tool
> equality, account equality, destination-set containment and the recomputed digest.
> **ADR-0193 §6's origin arm is the one check this invariant does not take**, for the reason the
> limits clause below states. Those eight are adopted with that section's reasoning entire
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

> **Normative — the coverage floor check is taken in its strict form and inherits no
> exception.** §6 states that route (d) relaxes `SpanCoverage.NOT_COVERED` for nothing, and the
> fact is on the decision's own binding, so the trail takes it with no seam, no store read and
> no arguments. **It takes neither ADR-0238's closed-loop disjunct nor ADR-0247 §3's
> retirement**: route (c) retires the coverage exception at the configured provider and **route
> (d) is not route (c)** — it is a goal-scoped authority over argument values, §6's condition 4
> is stated over it unrelaxed, and a row claiming route (d) on a covered binding is refused
> whatever its `closed_loop` says. **A lane that reused route (c)'s eligibility here has
> breached this clause.**

> **Normative — the lineage check is *not* taken, and that is a consequence of §6's discharge
> stated rather than discovered.** §6 discharges ADR-0181 §5's floor exactly where the row
> covers the request **in full**, and whether it does turns on the per-argument comparison the
> trail cannot re-take (below). So a route-(d) row whose binding carries
> `planned_with_external_content` is **admitted**, and what asserts the discharge is the
> policy's own comparison at the one seam read, taken over the concrete request at **every**
> dispatch (§13) and never cached. **That is a real reduction in what the trail can refuse and
> it is said rather than implied**: an earlier draft of this decision refused such a row
> outright, and it could, because the floor then bound route (d) entire. What remains is that
> the row must still be `ESTABLISHED`, live at both ends, about this declaration, this account
> and these destinations, carry the digest `record` recomputes, and sit on a binding whose
> `coverage` is `SpanCoverage.NOT_COVERED`. **ADR-0193 §6's origin arm is untouched on every
> route-(b) row**, where it binds exactly as ratified.

> **Normative.** **`settled_at` is the instant compared and `proposed_at` is not.** A row is
> proposed before the user answers and authorises nothing until they do, so the instant a
> decision must not predate is the instant the authority came into being. A row whose
> `settled_at` is after the ruling was taken is the **backdated** case ADR-0193 §6 refuses, one
> field over.

> **Normative — the trail asserts what it can see, and the policy asserts the rest.** What
> remains outside the ten checks is **two** comparisons and one join, and all three are named. The
> trail **cannot** re-take the per-argument comparison and no lane gives it a way to: a
> `PermissionDecision` carries `parameters_digest` and **not** `parameters`, deliberately —
> *"a durable record holding them verbatim would make the audit trail a second copy of the
> user's most sensitive material"* — so the arguments the coverage rule is stated over are not
> in the trail's hand and putting them there would breach ADR-0021 §1 and ADR-0004 §7 at once.
> It **cannot** re-take the recipient condition on an **opening-act row** (§1): that condition
> is *"a live grant covers this request"*, and the trail holds
> `RecipientGrantResolution.resolve` — a lookup by **id** — while the row names no grant id and
> `resolve` is not a `covering`. **A pointer was considered and refused**: a field naming the
> grant the write rested on would go stale the moment a *different* live grant covered the
> request, so the trail would refuse a ruling the policy took correctly, and it would be a
> second record of a fact the grant seam already answers. So the condition is the policy's,
> taken over the concrete request at **every** dispatch (§13) and never cached — the same
> division, and the same reason, as the two below. It **cannot** decide whether §6's lineage
> discharge held either, because that discharge is
> exactly *"the row covers the request in full"* and full coverage is that same per-argument
> comparison — which is why the clause above drops the origin arm rather than weakening it into
> something the trail could pass without checking anything. It **cannot** check that the request
> belonged to the goal the ruling names either, because
> `ActionRequest.goal` is not transcribed onto the decision (§16). Both limits are stated here
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
> and the user is asked**, whatever the interpretation said. **And where a live row of that
> goal and declaration exists, the request reaches no standing route at all, on §6's bar** —
> for a cost above its `maximum`, a term outside its named set, **and for an argument it names
> in no member** — so the asking never depends on the absence of some other authority.

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
> gains **`CoverageView`**, a frozen model with `extra="forbid"` whose fields are exactly
> `argument`, an `EncodableText`; `fixed`, a `FrozenJsonValue | None`; `bound`, a `ValueBound |
> None`, the two under `CoverageMember`'s own two-shape validator; and `span`, a
> `NonBlankEncodableText`, **required** — the user's own words the member rests on, transcribed
> from its basis (§8). And **`AuthorizationProjection`**, a frozen model with
> `extra="forbid"` carrying exactly `coverage`, a **possibly-empty** `tuple[CoverageView,
> ...]`, and `expires_at`, a `UtcInstant`. **It is named for what it projects rather than for
> the question that carries it**, because what it states — the coverage an answer would
> establish and the instant it would expire — is a fact about an authorization and not about a
> confirmation. `Confirmation` gains **one** member,
> **`authorization: AuthorizationProjection | None`, required with no default**, and it is
> **absent** — not empty — on a `CONFIRM` that proposes no row (§1).
>
> **`coverage` is possibly-empty because §1 permits an empty `coverage` and this section
> requires the projection to transcribe it.** The row a `CONFIRM` about an argument-free egress
> request proposes carries `coverage=()`, and a non-empty projection could not be constructed
> for it at all: omitting the projection would say falsely that answering establishes no
> authority, and minting a member would be an invention where this section requires a
> transcription. An empty projection says what is true — that answering establishes an
> authority over this goal, this declaration, this account and these destinations, fixing no
> argument because the call carries none — and §1's rule that an empty `coverage` covers no
> request whose `parameters` are non-empty is what keeps it narrow. **The other direction was
> considered and rejected**: forbidding an empty-coverage row outright would make an
> argument-free egress call of a goal the one call no act of the user could ever cover, for no
> gain in safety, since such a row bounds exactly the destination set and account it names.
>
> **One `CoverageView` rather than a confirmation projection beside a listing projection.** The
> question and the listing render the same three facts about a member — the argument, the fixed
> value or the bound, and the user's own words — so one carrier serves both, and a second would
> be two shapes of one fact, which ADR-0150 is named after. **The span is on both** because
> §8's *"Both halves survive, and neither is derivable from the other"* is as true at the
> question as it is afterwards: a user reading *"under sixty pounds"* beside a bound of GBP 60
> can check the working before they answer rather than only after.
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

> **Normative — an opening act is announced, on a member of its own, once per row it opens.**
> `TurnOutcome` gains **one** member, **`authorizations: tuple[AuthorizationView, ...]`**,
> possibly empty and **defaulting to empty**, carrying **one view per `Authorization` opened
> under §1's path (iii) during that turn**, in the order the rows were written. It is **empty**
> on every turn that opened none.
>
> **It is a tuple, because one act can open two authorities that are not the same authority.**
> §1 permits a plan reaching two declarations to need two rows, and one instruction — *"up to
> fifty pounds for the train and a hundred for the hotel, until Sunday"* — opens both. Their
> coverage is **not** interchangeable: both declarations may name their price argument `amount`,
> so merging the two would either authorise an eighty-pound train booking or refuse an
> eighty-pound hotel one, and carrying both members in one row is refused outright by §2's rule
> that no two members of a record name one argument. **Each authority is announced as itself**,
> and §1's per-row rule is what it transcribes: a row carries members for the arguments **of its
> own declaration** that the act's words bear on (§9 clause (ii)), so two rows of one act may
> carry different bounds for an argument of the same name.
>
> **It carries `AuthorizationView` and mints no second shape**, which is the carrier §11's
> listing renders below: the declaration's own `VisibleIdentifier` and description, each coverage
> member as a `CoverageView` with the user's own span, the expiry, whether the row is live, and
> **the row's `id` as the revocation handle**. That is what makes two announcements legible — the
> user tells them apart by the declaration each is about — and it puts the withdrawal handle in
> front of them at the moment the authority comes into being rather than only afterwards. **The
> listing's own rendering bar binds here entire**: no subject digest, no `BoundAccount`, no
> account or connection reference, no `confirmation`, no `supersedes`, no resolution and no
> `destinations`.
>
> **The trigger is that the row was written, and the row is what the view is transcribed from**,
> so the value the announcement needs always exists at the instant it is emitted and there is no
> act-time projection to keep in step with a row written later. **A path-(iii) row is therefore
> written only during a turn that produces a `TurnOutcome`** — which is every turn in this
> decision's scope, a step being dispatched inside one. §19 books the case a driver dispatching
> **outside** a turn would open, and that driver is **A7's** and is not decided here. `Confirmation`
> carries the **question's** projection and `TurnOutcome` the **announcement's**, and neither
> mints a shape the other does not already need: a question is about a row that does not exist
> yet and names no identifier, and an announcement is about a row that does, so it carries the
> listing's own view and its revocation handle.
>
> **This does not ride ADR-0250 §5's announcement rule, and the reason it cannot is stated
> rather than discovered.** That rule is about `goal_engagement`, and it is explicitly silent in
> a case this decision reaches: *"A grounding-only revision is recorded and not announced"* — an
> opening instruction can move an existing constraint's ground from inferred to user-stated
> without changing its text, establish an authority on that act, and be a revision §5 requires
> to stay **unannounced**. §5's carrier has no expiry and no coverage to render either. So the
> safeguard is a member of this decision's own, with its own trigger — **the row was
> written** — and no materiality judgement anywhere in it.
>
> **ADR-0250 §5's four members are untouched and this is a fifth beside them**, on ADR-0244 §9's
> shape which §5 itself invokes: *"No member is derived from another and a client renders each
> on its own."* An engagement announcement and an authorization announcement can both be present,
> either alone, or neither. §18 records the one count that moves.
>
> **It is composed by `orchestration` and no model writes it** (§15), which is §5's own division
> — *"The reply is composed by `orchestration` from the typed value, and no model writes it"* —
> and **the one identifier it carries is the row's own `id`**, the withdrawal handle, exactly as
> the listing below carries it and for the listing's own stated reason: a surface that named an
> act without naming what withdraws it would state an act and withhold its remedy. **It carries
> no other identifier**: not the goal's, not the grant's, not a connection reference, not a
> `SecretName` and not a `Settings` field.
>
> **The no-identifier rule below is the *confirmation's* and is not read onto this member.** That
> rule is stated over a projection of a row the user has not yet established — there is nothing
> to withdraw, so there is no handle to carry — which is why the two surfaces differ here and why
> the difference is stated rather than left as an apparent contradiction.
>
> **No `CONFIRM` is drawn for a path-(iii) row**, so `Confirmation.authorization` does not arise
> and §1's absence rule is not engaged. **An authority established without a question is
> therefore announced at the act and revocable at any moment after it** — which is what §1's
> safeguards clause rests on, and is the whole of what this decision offers in place of the
> prompt.

> **Normative.** **The confirmation's projection names no identifier**, and this clause is
> about that projection alone — the listing below, and the announcement above, each carry the
> row's `id` as its revocation handle and are governed by their own clauses. A confirmation is
> about a row the user has not established, so there is nothing yet to withdraw and no handle to
> carry. Not the goal's id, not the authorization's id, not
> the connection reference, not a credential slot and not a `Settings` field.
> `BoundAccount.reference` is *"never shown to the user"* (ADR-0148 §6, §8) and this decision
> does not move that; ADR-0193 §11's bar on what an audit surface renders binds here entire;
> and ADR-0228 §8's namer rule binds every prompt this decision builds.

> **Normative — the listing's `live` reports the row's own liveness and never the standing of
> another act.** A row whose `origin` is `OPENING_ACT` rests on a recipient grant §6 re-takes at
> every dispatch, and that grant may have lapsed or been revoked since. **Such a row still
> appears and still reads `live` where §1's predicate holds**, because it is still an
> `ESTABLISHED` row the user may revoke and hiding it would hide an authority they hold. **The
> listing is a record of what the user authorised and is not a promise that the next call will
> be allowed** — no surface of this decision makes that promise, `decide` is the only thing that
> answers it (§13), and the engine reads no grant seam to assemble a listing.

> **Normative.** **The surfaces this decision owes are a listing and a revocation**, and they
> render, per record: the goal's **statement** (never its id), the declaration's own
> `VisibleIdentifier` and description, each coverage member as *this argument is fixed at that
> value* or *this argument is bounded by that limit* **together with the span the user said**,
> the expiry, and whether the row is still live or has lapsed. It renders a `PROPOSED` row not
> at all — that is the confirmation's
> question and not an authority the user holds — and §16's `standing(goal)` is what makes that
> a fact about the read rather than a filter a renderer applies. They render the row's **`id`**
> and no other internal value: **no** subject digest, **no** `BoundAccount` and no account
> reference, **no** connection reference, **no** basis beyond each member's span and **no**
> `Settings` field. A revocation names the record by that `id`.

> **Normative — the `id` is rendered because it is the revocation handle, and ADR-0193 §11's
> bar is read as it actually stands rather than one conjunct wider.** That bar is on what an
> **audit** surface asserts about a recorded decision, and the ratified grant listing exposes a
> grant id for exactly this reason — `revoke_recipient_grant(grant_id)` could not be reached
> otherwise, and `recent_recipient_grants` exists in terms because *"a user at the ceiling
> could hold an expired grant occupying a slot, see it in no listing, and have no id to pass to
> `revoke_recipient_grant`"*. A listing that named no id would state an act and withhold the
> means to perform it. **What stays barred is every other internal value**, which is the list
> above, and ADR-0193 §11's rendering rules on a decision surface are untouched.

> **Normative — the listing is per goal, and that is a decision rather than an omission.**
> §16's `standing(goal)` is keyed on a goal and this decision adds no goal-free read. A
> goal-free one would return every `ESTABLISHED` row of every goal the user has ever run, live
> **and** lapsed; §1's uniqueness bounds that set per goal and declaration and bounds it not at
> all across goals, and this store carries no outstanding-count ceiling of the kind ADR-0193 §1
> gives the grant store — so a cross-goal read would have to choose between a truncated answer
> and an unbounded one, and `standing_recipient_grants`' own reason forbids the first
> (*"a truncated answer to 'what do I authorise' is a false answer rather than a partial
> one"*). §19 books the cross-goal listing with what fires it.

> **Normative — the two operations, with their signatures and their carriers, because §16
> calls its roster complete and no implementing lane may invent a cross-subsystem contract**
> (golden rule 5, ADR-0015). `AssistantEngine` gains **exactly two** members and
> `core/types.py` the two carriers they need:
>
> - **`standing_authorizations(goal_id: Identifier) -> tuple[AuthorizationView, ...]`** — the
>   `ESTABLISHED` rows of that goal, live and lapsed, read from
>   `GoalAuthorizationStore.standing(goal)` and projected. **It takes no `limit`**, for
>   `standing_recipient_grants`' stated reason quoted above. It composes, filters, enriches and
>   summarises nothing beyond the projection; the goal's statement it renders is read through
>   `PlanStore.get_goal`, and a goal that store does not hold is an **empty answer** rather
>   than a raise. **The liveness is the engine's one clock reading** (§16), taken once for the
>   whole listing, because `standing` reports none.
> - **`revoke_authorization(authorization_id: DurableIdentifier) -> AuthorizationSettlement`**
>   — `settle` to `REVOKED` on §1's one edge out of `ESTABLISHED`, its answer returned
>   **unmapped** (§16). **An unknown id is a result and never a raise**, which is
>   `AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception`'s rule and
>   `revoke_recipient_grant`'s own shape one store over. **Never refused for a ceiling** —
>   there is none — and revocation is **whole**: no operation narrows a record, re-scopes one,
>   extends one or edits one in place (§1).
>
> **`AuthorizationView`** is a frozen model with `extra="forbid"` whose fields are exactly
> `id`, a `DurableIdentifier`; `goal_statement`, a `NonBlankEncodableText`; `tool`, a
> `ToolDefinition` **by value**, as `RecipientGrant` already carries one across this surface;
> `coverage`, a **possibly-empty** `tuple[CoverageView, ...]`; `expires_at`, a `UtcInstant`;
> and `live`, a `bool` the engine set from its one clock reading. It carries **no** `goal` id,
> **no `destinations`**, no `BoundAccount`, no subject digest, no `confirmation`, no
> `supersedes` and no basis beyond each member's span.
>
> **It carries no `destinations` and that is a refusal rather than an omission.**
> `CanonicalDestination`'s connected-account arm carries a whole `BoundAccount`, `reference`
> included, so a record whose destination set is the connected account could not cross this
> surface by value without carrying the connection reference — which `BoundAccount.reference`
> is *"never shown to the user"* (ADR-0148 §6, §8) forbids and which the clause above bars by
> name. Rendering it would need a **destination projection** carrying the account's identity
> and not its reference, and this decision mints none: the destination set is what
> ADR-0148 §8's fourth clause already puts in front of the user **at the question**, in both
> forms, and the listing's subject is what the act fixed about the arguments and when it
> lapses. §19 books the projection with what fires it. **The revocation's carrier is
> `AuthorizationSettlement`** (§16), which `settle` already answers with and which this surface
> returns unmapped: `SETTLED` where the row stood `ESTABLISHED` and now stands `REVOKED`,
> `NOT_AT_SOURCE` where the store holds the row and §1's one edge into `REVOKED` does not leave
> where it stands, and `NO_SUCH_AUTHORIZATION` where it holds no row with that id. **A second
> three-valued vocabulary for the same fact is exactly the second carrier ADR-0150 is named
> after**, so none is minted; the surface renders prose from the member and never the member's
> own spelling.
>
> **A `PROPOSED` row is therefore not revocable**, and that is §1's graph rather than an
> omission here: a question the user has not answered is withdrawn by declining it or by
> letting it lapse, and `standing` never offers one to a listing in the first place. A lapsed
> `ESTABLISHED` row **is** revocable, which is why `standing` returns it (§16).

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
> requires. **What ADR-0193 §11's second state now covers is two kinds of row rather than
> one**, and §18 records that against it.

### 12. Expiry: justified, visible, with no disable spelling, and for this record alone

> **Normative.** **Every `Authorization` carries an `expires_at` and there is no spelling for
> one without it** — no null, no sentinel, no "forever" — and it is **strictly after**
> `proposed_at`, refused at construction otherwise. That is ADR-0193 §9's clause and its reason
> adopted whole: a record expiring at or before the instant it was proposed *"is a grant in
> shape and nothing in effect"*.

> **Normative — there is no deployment-wide expiry, and `core.config.Settings` gains
> nothing.** No field, no default, no ceiling and no sentinel. An operator's figure is **a clock
> the user never saw**, and decision 7's *"justified, visible"* cannot be satisfied by one: a
> long-lived goal whose authority lapsed on a deployment default would lose it for a reason
> nobody stated at the act and nobody could read off the row. The expiry is **per
> `Authorization`**, set when the authority is granted and shown then (§11).

> **Normative — the ladder is taken on the two paths that *set* an expiry, and never on the one
> that transcribes it.** Paths (i) and (iii) set `expires_at` and take the ladder below. **Path
> (ii) takes none of it**: a correction transcribes the superseded row's `expires_at` unchanged
> (§1, §5), so a chain of corrections carries the first act's horizon whatever the goal's
> `deadline` now says and whether or not the correcting act names an instant. **That is the
> clause this ladder must not disturb** — it is what makes *"No sequence of corrections outlives
> the confirmation that began it"* true — and a correction is never refused for want of an
> instant it was never going to set.

> **Normative — the ladder, taken in order at the instant a path-(i) or path-(iii) row is
> written, and it is total.** `expires_at` is:
>
> 1. **the instant the user's own act states**, where the recorded act states one and §10's
>    resolutions take it — *"until Sunday"*, *"for this week"*, *"while I'm away"* — resolved
>    by `DATE_FROM_CONTEXT` or `AS_STATED` under §9's clauses entire, so an instant the user
>    named is carried with the span that named it exactly as a coverage member's value is;
>    otherwise
> 2. **the goal's own `deadline`**, transcribed unchanged. `Goal.deadline` is the horizon the
>    goal itself carries, it was recorded when the objective was, and an authority about that
>    objective outliving it would authorise calls toward a goal whose own moment has passed.
>    **This is decision 4's *no separate arbitrary timer*** — the authority borrows the
>    objective's horizon rather than minting a second one beside it; otherwise
> 3. **no row at all.** Where the act states no instant **and** the goal carries no `deadline`,
>    or carries one at or before `proposed_at`, **no path-(i) proposal and no path-(iii) row is
>    written**, `Confirmation.authorization` is absent (§11), and the concrete call is confirmed
>    under ADR-0148 §3's route (a) exactly as it is today. **A path-(ii) correction of an
>    existing row is unaffected**, transcribing the horizon that row already carries. **Nothing is invented, nothing is defaulted
>    and nothing falls back to a configuration**, which is §10's own discipline for a resolution
>    the loop cannot take, read onto the one instant this record cannot do without.
>
> **The cost of step 3 is stated rather than hidden**: a goal carrying no `deadline` whose user
> stated no horizon has no route (d) at all, and every call of it asks. That is the fail-closed
> direction and the only one compatible with an expiry the user can be said to have seen; the
> repair is a goal with a deadline or a user who names one, both of which are the user's own
> act. §19 books the decision that would ask for the instant instead.

> **Normative — the expiry is taken once, when the row is written, and is never recomputed.**
> On path (i) `proposed_at` is the recorded `CONFIRM`'s `decided_at`; on path (iii) both
> `proposed_at` and `settled_at` are the recorded turn's instant; and in each case `expires_at`
> is the ladder's answer **at that instant**. **Both are durable before the user is shown
> anything**, so the instant §11 names in the prompt is read off the row and is the instant the
> row carries — a restart between the question and the answer recovers it. This is ADR-0244
> §3's clause one record over: *"both computed from it, once, at the instant the park is
> written"*. **No lane recomputes either instant at the answer**, and **a later edit to the
> goal's `deadline` moves no row already written** — a row states the horizon that stood when
> the authority was granted, which is ADR-0247 §8(b)'s prospectivity read onto the one input
> this record takes from outside the act.

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
> `Authorization` bounds **argument values of one goal**, so the honest horizon is that goal's
> own — which is why the ladder reaches for `Goal.deadline` rather than for a figure, and why
> a user who names an instant overrides it. A standing recipient grant is a different thing —
> a preference about who the user is willing to reach, which they expressed once and expect to
> hold — and a configured provider is not a user act at all. **That difference is why neither
> takes this ladder**, and it is the whole of decision 7's *"justified"*: the instant is
> justified by the act or by the objective, and in neither case by a deployment.

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
> afresh, and **no standing route is reached**: route (d) does not cover, and where the changed
> argument is one the live row names, §6's bar refuses route (c) and route (b) as well. The
> ruling is what the table alone produced — `CONFIRM` for a transmitting tool. The step is
> committed `PENDING → AWAITING_APPROVAL` (ADR-0037 §4).
> **Nothing is dispatched, no claim is made, no effect occurs**, and the attempt's state is
> committed `AWAITING_AUTHORIZATION` (§14).

> **Normative.** **A revocation is prospective, and it bites twice.** It governs every
> `live_for` read that begins after it is recorded, and it refuses the write of any route-(d)
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
>    either a literal on the step, filled by a `ResultReference` (ADR-0253 §6), **or classified
>    `system_supplied` on that declaration and filled by `orchestration`** (§3). The schema
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
> under the ceiling and outside its bound reaches no standing route (§6's bar) and is
> confirmed. **No lane reads
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
> - **A step's arguments are not covered** — the user is asked through the ordinary `CONFIRM`
>   park (ADR-0037 §4), and the attempt's move to `AttemptState.AWAITING_AUTHORIZATION` is
>   **the one ADR-0249's own lane already makes** at the instant that `CONFIRM` is recorded.
>   **This decision adds no second writer of that state and no second asking mechanism**: an
>   uncovered argument is a request the policy rules `CONFIRM` on, and everything after that is
>   machinery that exists.
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
> paused by the path that already exists**: ADR-0249's lane commits the attempt out of
> `AWAITING_AUTHORIZATION` to `RUNNING` at `EXECUTE` the moment the resolving ruling reaches
> the trail, in one `commit_attempt` with the decision that answer was recorded under. **This
> decision adds no transition, no second commit and no ordering of its own**, and the
> settlement of the `Authorization` row (§1) is a write to a different store that neither
> precedes nor follows it by any rule stated here.

> **Normative — `GoalAttempt.authorization_ids` keeps one namespace and this decision adds
> nothing to it.** ADR-0249's lane appends the `PermissionDecision` id an attempt was allowed
> by, and **no `Authorization.id` is ever appended there**: the attempt reaches the record
> through the decision, whose `authorised_by` names it (§7), so the join exists without a
> second id kind in one tuple — which is the namespace hazard ADR-0247 §2 names when it refuses
> to rest a discriminator on *"grant ids and connection references"* being drawn from disjoint
> spaces, *"which they are not"*.

### 15. Writer clauses, gathered in one place

> **Normative.** **An `Authorization` is written and settled by `orchestration` and by nothing
> else** — proposed on §1's path (i) when a `CONFIRM` is put and settled by the answer to it;
> written already `ESTABLISHED` on §1's path (ii) from a recorded turn whose span names an
> argument a live row already carries; and written already `ESTABLISHED` on §1's path (iii)
> from a recorded turn whose span opens the authority where no row of that pair stands
> `ESTABLISHED`. No `ActionPolicy`, no `AuditTrail`, no interface adapter, no reader, no tool
> and no model output writes or settles one, and **there is no fourth path**. **The one exception is the expiry settlement**, which any read of an expired `PROPOSED`
> row performs inside the store (§1) — ADR-0244 §10's mechanism, which is the store settling a
> deadline it can see rather than a component deciding anything.

> **Normative.** **The policy sets `authorised_by`, `authorised_subject` and `authorised_goal`,
> and sets each only from the record `live_for` returned.** It carries no value from a previous
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
> (§9). **`orchestration` composes `TurnOutcome.authorizations`** from the rows it wrote (§11),
> by transcription and never by a model. **And `orchestration` fills every system-supplied
> argument itself** (§3): a plan step
> whose own arguments name one is refused before any request is built, so no model supplies a
> value the coverage comparison never reads.

### 16. The `core` surface, the store, the wire, and the data rights

> **Normative — the `core` surface this decision adds, in full, with the lane that lands each
> so that this roster and §20's cut cannot drift apart.** `core/types.py` gains **thirteen**
> types: **ten with Lane 1** — `Authorization`, `AuthorizationDisposition`,
> `AuthorizationSettlement`, `AuthorizationOrigin`, `CoverageMember`, `ValueBound`, `BoundKind`,
> `AuthorizationBasis`, `ValueResolution` and `ResolutionRule`, the settlement vocabulary landing there because
> `GoalAuthorizationStore.settle` is Lane 1's and answers with it — and **three with Lane 3**:
> `CoverageView`, `AuthorizationProjection` and `AuthorizationView`. It gains **five**
> fields: `PermissionRuling.authorised_goal`, `ActionRequest.goal` and
> **`ToolDefinition.system_supplied`** (§3) with Lane 1, each of which route (d) or §6's bar
> reads, and `Confirmation.authorization` and **`TurnOutcome.authorizations`** (§11) with
> Lane 3. `core/protocols.py` gains **`GoalAuthorizations`**,
> **`AuthorizationResolution`** and **`GoalAuthorizationStore`** with Lane 1, and
> **`AssistantEngine` gains `standing_authorizations` and `revoke_authorization`** with Lane 3
> (§11) — two members on an existing Protocol and no other change to it. `core/errors.py` gains
> **`AuthorizationError`** and **`InvalidAuthorizationError`**, the classes a store fault and a
> refused write raise (below), with Lane 1. **`core/config.py` gains nothing at all** (§12):
> there is no deployment-wide expiry and no `Settings` field of any kind. **Every one of these
> is a BREAKING contract change under golden rule 5 and is flagged as one**; the ADR merges
> before anything implements against it (ADR-0015).

> **Normative — three faces, one object** (ADR-0193 §1's construction, and ADR-0097 §3's split
> behind it). `GoalAuthorizations` carries
> **`live_for(goal: Identifier, tool_id: VisibleIdentifier) -> Authorization | None`** and
> nothing else — the face a policy holds. **It is keyed and never asked**: it takes the goal and
> the declaration's **id** and returns the live row of that pair, so the policy holds the record
> itself and takes the declaration-by-value comparison and conditions 4, 5 and 6 over it (§3,
> §6). That is what lets the
> policy distinguish *no record* from *a record that did not cover* — the distinction §6's bar
> is stated over — and it keeps `Authorization`'s only liveness evaluation, and the store's
> only clock reading, in one member. `AuthorizationResolution` carries
> **`resolve(id) -> Authorization | None`** and nothing else — the face a trail holds, and it
> returns the row whatever its disposition, because the trail's own check reads that field (§7).
> `GoalAuthorizationStore` carries both plus `record`, `settle`, `standing`, `recent`, `export`
> and `clear` — the face a composition root holds. **Structural typing is what makes that
> sound**: a policy cannot name `record`, and a trail can name neither `record` nor `live_for`,
> because `mypy --strict` runs over `src` and `tests` and those attributes are not on the
> annotated types.

> **Normative — the eight signatures in full, because a roster of names is not a contract and a
> lane may invent none of this** (ADR-0015, golden rule 5). Every member is `async` and returns
> a **detached snapshot**, which is ADR-0097 §3's discipline for a store and is not restated per
> member:
>
> - `live_for(goal: Identifier, tool_id: VisibleIdentifier) -> Authorization | None`
> - `resolve(authorization_id: DurableIdentifier) -> Authorization | None`
> - `record(authorization: Authorization) -> str` — the id it wrote. **A path-(ii) row — written
>   `ESTABLISHED` directly — settles the row its `supersedes` names `SUPERSEDED` in the same
>   indivisible write** (§1). **A path-(i) row is written `PROPOSED` and retires nothing**: its
>   `supersedes` is a statement about what approving it would replace, and §§1 and 5 put that
>   retirement in the same write as the `ESTABLISHED` settlement, not in the proposal. **A
>   path-(iii) row — an opening act, written `ESTABLISHED` with `confirmation` and `supersedes`
>   both unset — retires nothing, there being nothing to retire**, and the uniqueness refusal
>   below is what holds it to a pair no row is established for. A
>   proposal that retired its predecessor would leave the user with **neither** authority while
>   the question stood, and would leave them with neither after they declined it — which §5
>   rules out in terms (*"a refused widening is not a revocation of what the user already
>   authorised"*) and which §6's bar would then stop refusing, the row it tests having been
>   retired by a question nobody answered.
> - `settle(authorization_id: DurableIdentifier, /, *, to: AuthorizationDisposition,
>   settled_at: UtcInstant) -> AuthorizationSettlement` — **the read, the comparisons and the
>   writes are one indivisible step**, which is `ParkedReadStore.settle`'s own construction and
>   `PlanStore`'s compare-and-swap argument (ADR-0014 §5): no caller reads a row, decides, and
>   writes back. **A settlement to `ESTABLISHED` takes §1's uniqueness check and the
>   supersession inside that same step**: where the row carries `supersedes` naming a row that
>   **still stands `ESTABLISHED`**, that row is settled `SUPERSEDED` in the same write — which
>   is what §5's *"in one write"* means and why there is never an instant at which two rows of
>   one pair are established — and where the named row has already left `ESTABLISHED`, it is
>   **left exactly as it stands** and this row is established all the same (§1). The uniqueness
>   check is then taken over **what would remain after that supersession**: the settlement
>   succeeds only where no other `ESTABLISHED` row of that goal and declaration id survives the
>   step.
> - `standing(goal: Identifier) -> tuple[Authorization, ...]`
> - `recent(*, limit: int = DEFAULT_PAGE_SIZE) -> tuple[Authorization, ...]` — newest first, by
>   `proposed_at` descending with ties broken by `id` ascending, which is
>   `RecipientGrantStore.recent`'s order one store over. A `limit` that is not a strictly
>   positive `int` is refused **locally and before any I/O**, exactly as that member refuses it.
> - `export() -> tuple[Authorization, ...]`
> - `clear() -> int` — the number of rows erased.

> **Normative — `settle`'s four outcomes, and they are what `AuthorizationSettlement` is.**
> `core/types.py` gains **`AuthorizationSettlement`**, a `StrEnum` valued by lower-cased member
> name and **closed at exactly four members**, total over what that indivisible step can answer:
>
> - **`SETTLED`** — the row stood at that edge's source, every check inside the step held, and
>   it now stands at the edge's target.
> - **`NOT_AT_SOURCE`** — the store holds the row and it does not stand at the edge's source, so
>   §1's graph does not admit the move from where it is. **This is one member and not four**,
>   and it covers a `PROPOSED` row asked for an edge that leaves `ESTABLISHED`, a retired row
>   asked for anything, a move that is not an edge at all, **and the loser of two racing
>   settlements of one row** — which §1 makes one fact rather than several, because the row's own
>   `disposition` is the compare-and-swap's token and "it was not there" is the whole of what
>   the store can honestly say.
> - **`WOULD_DUPLICATE`** — the row stands at the edge's source and the move is to
>   `ESTABLISHED`, but another `ESTABLISHED` row of that goal and declaration id would remain
>   **after this step's own supersession** — that is, a row this write does not itself retire,
>   because this row's `supersedes` does not name it or names a row that has already left
>   `ESTABLISHED`. **This member exists because §1's uniqueness
>   is a two-row rule and a settlement is where two rows can meet**: two proposals of one pair
>   may each be recorded — neither write leaves two rows established, so neither is `record`'s
>   to refuse — and approving both is where the invariant would break. Neither of the members
>   above is truthful about it: the row exists and is at its source. **A lane that answered
>   `SETTLED` here has written the state §1 forbids**, and one that raised has made a refusal an
>   exception.
> - **`NO_SUCH_AUTHORIZATION`** — the store holds no row with that id.
>
> **It is the value `AssistantEngine.revoke_authorization` returns as well** (§11), unmapped and
> unrenamed: a second vocabulary for one fact would be the second carrier ADR-0150 is named
> after, and the surface renders prose from the member rather than the member itself.
> **`WOULD_DUPLICATE` is unreachable on that surface** and is not a reason to mint a narrower
> type: it is reachable only on a settlement **to `ESTABLISHED`**, and a revocation settles to
> `REVOKED`, so the member is excluded by the edge rather than by the vocabulary. **A `bool`
> return was considered and refused** — it cannot tell an unknown id from a row that was not at
> the source, which §11's revocation surface must tell apart — and so was raising on any of
> them, because a refusal that is a **result and never an exception** is
> `AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception`'s rule.

> **Normative — the two error classes, and a refusal is not a fault.** `core/errors.py` gains
> **`AuthorizationError`**, raised where the store could not be read or written — and, per §1,
> where `live_for` finds more than one live row of a goal and declaration id, which is an
> integrity failure and not an answer. It gains **`InvalidAuthorizationError`**, a subclass,
> raised by `record` where the write is not one this store admits: a second `ESTABLISHED` row of
> one goal and declaration id, a path-(ii) row that fails the transcription or non-widening
> check, a row carrying `confirmation` written in any disposition but `PROPOSED`, a row
> carrying `confirmation` **unset** written in any disposition but `ESTABLISHED` or with
> `settled_at` unequal to `proposed_at`, a
> `supersedes` that resolves to no `ESTABLISHED` row of that goal and declaration id. **A
> refusal is the caller's error and a fault is the store's**, which is ADR-0193 §1's own split
> between an invalid grant and a store that could not be reached; the subclass relation means a
> caller catching the base class still catches both, and the policy's fault clause below is
> stated over the base class deliberately — a `record` refusal never reaches a policy, which
> writes nothing.

> **Normative — the clock disciplines are ADR-0193 §9's and are not re-derived.** **`live_for`
> is the only query that evaluates liveness**, and it reads the clock **exactly once per
> call**, measuring every row it considers against that one instant — ADR-0193 §9's rule and
> its reason, since a query reading an advancing clock per row could answer over a set true at
> no real instant. It settles an expired `PROPOSED` row it reads (§1), and it is the **only**
> query that reads a clock. **`standing` evaluates no liveness, reports none and reads
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

> **Normative — a fault takes the bar, and is never read as an absence.** An
> `AuthorizationError` out of `live_for` — the store could not be read, **or more than one live
> row of that goal and declaration id would have answered** (§1) — is logged and **takes §6's
> bar**: no route (d), no route (c), no route (b), and the `CONFIRM` the request would have
> drawn had the user authorised nothing. **It is not answered `None`**, because `None` is this
> seam's word for *"the store holds no live record"* and neither a fault nor a duplicate
> establishes that — and this seam
> discovers **restrictions** as well as permissions, so reading a fault as absence would let a
> transient store failure turn a refusal the user's own act earned into an `ALLOW`. **That is
> the one clause where this seam departs from `ThresholdActionPolicy._covering`'s discipline
> and the departure is the whole point**: the grant seam discovers permissions only, so a fault
> there can only make a ruling more restrictive, and here it could make one less. The reason the
> user sees is
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

> **Normative — what crosses the wire, and what does not.** Four things cross: the **listing**
> as a `tuple[AuthorizationView, ...]`, the **revocation** as an `AuthorizationSettlement`, and
> **`Confirmation.authorization`** as an `AuthorizationProjection`, and the **announcement** as
> a `tuple[AuthorizationView, ...]` on `TurnOutcome.authorizations` — the same carrier as the
> listing and not a second shape of it (§11). **No `Authorization`
> crosses whole and no member of `GoalAuthorizations`, `AuthorizationResolution` or
> `GoalAuthorizationStore` is promoted**: the confirmation carries a **projection** of the
> coverage the answer would establish, not the record — there is no record yet — and the
> listing carries the projection §11 fixes rather than the stored value, so no client holds a
> record's basis, its resolution, its digest, its `confirmation`, its `supersedes`, its account
> or its `destinations` — the last because `CanonicalDestination` carries a whole
> `BoundAccount` on its account arm and §11 declines to mint the projection that would drop the
> reference. That is `ConfirmationEgress`'s discipline, which carries *"the recorded
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
there is nothing to record."* **Seven come out yes** once the owner's four restrictions are
carried: the three this decision already recorded, plus ADR-0181 §5's lineage floor, ADR-0016
§1 in two scopes, ADR-0144 §7's parameter-fit eligibility clause and ADR-0250 §5's
`TurnOutcome` member count, each below.

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

**ADR-0247 §2 — partially superseded, in two clauses and no others.**

*Its discriminator clause.* That clause reads *"a non-resolving egress `ALLOW` whose
`authorised_by` is set is **route (b) where `authorised_subject` is set** and **route (c) where
it is not**"*. A reader holding it would classify a route-(d) row as route (b), which is false.
The route-(b) limb takes one further conjunct (§7); **the route-(c) limb of the discriminator
is untouched**.

*Its route-(c) outcome clause, in one limb.* §2 reads that where `_only_the_disclosure_floor`
holds *"**and the request is at the configured provider**, the ruling is an `ALLOW` on route
(c) **without consulting the recipient-grant seam at all**"*. §6's bar makes that false of one
kind of request: one carrying a `goal` for which the goal-authorization seam, asked for the live
record of that goal and that declaration's `id`, answers neither *no record* nor *a record every
argument of the request is covered by*. Such a request draws `CONFIRM` and takes no standing
route. A reader holding §2 would read the outcome as following from the eligibility and would
author an `ALLOW` the policy owes a refusal for, which is ADR-0082 §1's test met. **The scope is
that limb and nothing else**: every other request at the configured provider — one carrying no
goal, one whose goal holds no live record of that declaration id, and one whose record covers
every user-facing argument it carries — reaches the same `ALLOW` on the same pointer with the
recipient-grant seam consulted zero times, exactly as §2 rules.

**Every other clause of §2 binds entire**: the one derived fact and the rule that `closed_loop`
alone is never the condition of any relaxation; the two configured values as a constructor
argument that is not a store handle; route (c) **reachable** exactly where route (b) is and on
the same five conditions, which the bar does not touch — it refuses after reachability rather
than narrowing it; route (c) taken before the grant seam is consulted; a policy with no
`RecipientGrants` reaching route (c); `authorised_by` set to the binding's `account.reference`
with `authorised_subject` unset; the digest-free admission on `closed_loop` and pointer
equality; the eligibility-versus-discriminator division; the clause reserving the
account-and-origin comparison to the policy; and the no-revalidation clause.

**And §3's retirements are untouched.** ADR-0247 §3 retires the lineage floor and the coverage
exception for a request at the configured provider; the bar retires nothing and relaxes
nothing, and a request it does not fire on is ruled exactly as §3 leaves it.

**ADR-0181 §5 — partially superseded, in the second clause's application to a fully covered
request and in no other.** That clause reads that at the egress ruling point *"no ruling an
`ActionPolicy` returns is `ALLOW` on a request whose binding carries
`planned_with_external_content` except under ADR-0148 §3's route (a) … No standing user policy
and no standing grant covers such a call, whatever a later ADR permits for calls that do not
carry it."* §6 above makes that false of one kind of request: one every **user-facing argument**
and every member of whose **canonical destination set** a live `Authorization` of the request's
own goal covers under §3's six conditions. A reader holding §5 would refuse such an `ALLOW`, so
ADR-0082 §1's test is met and the record is the same shape ADR-0238 §5 and ADR-0247 §3 already
took here. **The ground is the owner's and it is ADR-0247 §3's one authority over**: where the
user's own fixed values and permitted ranges bound every argument and every destination, outside
content cannot have steered anything the user did not bound, and §3's negative arm is what makes
that hold — a value a tool produced can satisfy a bound and can never supply one.

**The scope is that limb and nothing else.** **Partial coverage still asks**: a destination
outside the row's set, a user-facing argument the row names in no member, and an argument whose
value the member's comparison refused each leave §3 unsatisfied, the row covers nothing, and §5
binds exactly as ratified. **ADR-0193 §4 is untouched** — no `RecipientGrant` covers a tainted
call, and route (b) reaches none of this. **§5's remaining clauses bind entire**: its
memory-ruling-point clause, its separate-binding clause on `decide` and `resolve`, its
two-comparisons clause, its `authorises` clause, its `ActionPolicy`-contract clause and its
ADR-0154 §4 floor clause. And **ADR-0233 §9's second clause is untouched**: §6's condition 4 is
unrelaxed, so a binding carrying covered content reaches no route (d) whatever its coverage.

**ADR-0247 §3 — partially superseded, in its final clause's reference to ADR-0181 §5 alone.**
That clause reads *"An email, a fetch, a tool call and a search bound anywhere else each keep
ADR-0181 §5's floor, ADR-0193 §3 and §4, ADR-0155 §3 and ADR-0233 §9 **exactly as written**"*. A
reader holding it would read §5 as preserved in full for every such request, which the record
above makes over-wide by one limb. **Its purpose is untouched and is what the scope preserves**:
route (c)'s exception rides nothing but a `WEB_SEARCH` at the configured provider, and route (d)
inherits none of it — the discharge above is this decision's own, stated over full coverage and
not over any configured value. ADR-0247 §3's other clauses, including both of its retirements
and its `SearchSupply` clause, bind entire.

**ADR-0016 §1 — partially superseded, in two scopes: `ToolDefinition`'s field list, and the
required-field clause in the application to that one field.** §1 states the model whole and its
no-default rule alongside. `ToolDefinition` gains
**`system_supplied: tuple[EncodableText, ...]`** defaulting to the empty tuple (§3), so a reader
holding only §1 authors a definition that never carries one and does not conform — that is the
first scope. **The second is the one a reader would otherwise object with.** §1 reads *"Every
field that a permission decision depends on is required"*, unconditionally, and a permission
decision **does** depend on this field: it moves §3's condition 6 and §6's bar. So the default is
an **exception** to that clause and is recorded as one rather than argued away.

**The grounds are the clause's own reason, which does not reach this default.** §1 forbids a
default because *"A default is a claim"*, and the empty tuple for `reads`/`writes` is *"exactly
the false statement a forgetful integration author would ship"*. Here the empty tuple makes the
**opposite** claim — every argument is user-facing, so every argument needs coverage — which
costs a question and can never authorise a call. **The alternative, making the field required, is
named and declined** (§3): it would oblige every declaration in the tree and every fixture to
write `system_supplied=()` for a fact empty on almost all of them, with no return in the
direction §1 protects.

**Every other clause of §1 binds entire**: every **other** field a permission decision depends on
stays required, `frozen=True` and its audit argument stand, `description`'s non-blank refusal
stands, and **no lane reads this record as licence to default a second safety field** — the
exception is this one field, on this argument, and the next one needs its own. §§2-7 are
untouched, and §4's `parameters_schema` declaration is relied on rather than moved — the
classification is a field **beside** the schema and never a keyword inside it (§3).

**ADR-0250 §5 — partially superseded, in `TurnOutcome`'s member count alone.** §5 states that
*"`TurnOutcome` gains **four** `None`-defaulting members, one per fact"* and enumerates them.
§11 above adds a **fifth**, `authorizations`, a possibly-empty `tuple[AuthorizationView, ...]`
carrying one view per authority an opening act established on that turn — so a reader holding
only §5 authors an outcome type that cannot carry the announcement this decision requires. That
is ADR-0082 §1's test met, and the scope is the count and the enumeration and nothing else.
**The member is a tuple defaulting to empty rather than a `None`-defaulting value**, because
absence and *"no authority was opened"* are one fact here and an empty tuple states it; §5's
shape is followed where it applies and not imitated where it does not.

**Every other clause of §5 binds entire, and two of them are what the new member rests on.**
*"No member is derived from another and a client renders each on its own"* is why a fifth sits
beside the four rather than inside one, and *"The reply is composed by `orchestration` from the
typed value, and no model writes it"* is the division this member takes unchanged. **§5's
grounding-only silence rule is untouched and is why the member exists**: *"A grounding-only
revision is recorded and not announced"* leaves an opening act that only re-grounds an existing
constraint unannounced, so the safeguard could not have been inherited from `goal_engagement` and
is stated on a carrier of its own with its own trigger. §5's `GoalDisambiguation` clauses, its
`UNDECIDED` outcome shape and its ADR-0170 §4 count are untouched, as are §§1-4 and §§6-17.

**ADR-0144 §7 — partially superseded, in its parameter-fit eligibility clause alone.** That
clause reads: *"When parameter-schema enforcement lands, a candidate whose schema the step's
parameters do not satisfy is **ineligible** and is removed from the candidate set before any key
of §2 through §4 is applied."* §3 above classifies some arguments **system-supplied**, forbids
the model naming one on a step, and has `orchestration` fill them — so a candidate whose schema
**requires** such a key would be ineligible for every step under that clause as written, and the
call this decision exists to authorise could never be selected. The clause is read over **the
step's parameters merged with the system-supplied arguments `orchestration` fills for that
candidate**, per candidate. **Everything else of §7 binds entire**: the fit predicate is still an
**eligibility** test taken **before any ordering key**, it is still never a key, a penalty or a
tie-break term, and ADR-0128 §1's shape behind it is unmoved — what changes is the mapping the
predicate is evaluated over and not where or how it binds. **ADR-0145 §2 is untouched and is the
reason the change is stated this way**: there is still exactly one evaluator in `core` and no
consumer substitutes its own, so only its argument moves. ADR-0144's other sections and its other
deferrals are untouched.

**ADR-0193 §5 and ADR-0148 §8 — no record owed for §6's bar, and the working is shown because
a reader would expect one.** §5 rules that *"A grant states nothing about the payload and
authorises no content"* and that what a grant may authorise is a recipient — *"That is the
whole of what it authorises."* The bar refuses a standing route on a **payload** fact, so it
takes nothing from a grant that §5 ever gave one: a grant that covers the recipient still
covers the recipient, and ADR-0193 §3's *"only effect"* clause — discharging the
recipient-authorisation ground of ADR-0148 §3's first clause — is discharged exactly as before.
What changes is that a **second** ground must also be satisfied, and ADR-0148 §3's first clause
states a **necessary** condition on an `ALLOW` rather than a sufficient one, so its enumeration
does not move for the bar either. ADR-0148 §8 is the clause that makes the addition available
in terms: *"A policy may be stricter; it may not be more permissive than these."* The bar is
strictly stricter, on every request and in every direction, so no reader of ADR-0193 acts
differently about any grant and no reader of ADR-0148 §3 or §8 reads a clause of theirs more
widely than it now holds.

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

- **How an authority opened outside a turn is announced.** §11 emits the announcement on the
  `TurnOutcome` of the turn during which the row was written, which is every case in this
  decision's scope because a step is dispatched inside a turn. A driver that walks a plan's
  steps **outside** one is **A7's**, as §19 already reserves the plan-driving stage, and the
  decision that lands it states how an authority opened there reaches the user. **No lane reads
  this as licence to write a path-(iii) row where no `TurnOutcome` will carry its announcement.**
- **An opening act for a request whose recipient authority is the configured provider rather
  than a grant.** §1's path (iii) rests on a live `RecipientGrant` and on nothing else, because
  route (d)'s re-check is stated over `RecipientGrants.covering` and the configured-provider
  authority has no record for that seam to answer with. A search at the configured provider is
  ruled by route (c) exactly as it is today, with no argument bound by an opening act. Fired by
  a decision that gives that authority a durable, dated record — **ADR-0247 §13's own
  deferral**, which this ADR does not discharge.
- **Whether a standing authority ever covers a call carrying covered content.** Route (d)
  relaxes ADR-0233 §9's second clause for nothing — condition 4 binds it entire (§6) — and the
  lineage discharge above is stated over the lineage floor alone. Fired by a decision that takes
  ADR-0233 §9's second clause head-on, with its own argument and its own arms, as ADR-0238 §7
  and ADR-0247 §3 did for the one exception this corpus admits. **This ADR is not that
  decision** and no lane reads §6's condition 4 as negotiable.
- **Whether a standing authority ever covers a call planned over external content that it does
  *not* cover in full.** §6 discharges ADR-0181 §5's floor exactly where every user-facing
  argument and every destination are covered, and partial coverage asks. Fired by a decision
  that would discharge it on less than full coverage, which would need an argument this one does
  not make.
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
- **What the user is shown where §12's ladder yields no instant** — a goal carrying no
  `deadline` whose act named no horizon. §12 writes no row at all and every call of that goal
  asks, which is the fail-closed answer and not a question put to the user. Fired by a decision
  that would ask *"until when?"* at the act, which is a second question at the moment this
  design exists to remove one and is not taken here.
- **A durable, dated record of the configuring act** for route (c). ADR-0247 §13's deferral,
  untouched.
- **A rendering of an authorization's destination set after the act.** `CanonicalDestination`
  carries a whole `BoundAccount` on its account arm, so the set cannot cross a client surface
  without a projection that drops the connection reference, and §11 mints none. The set is
  shown at the question under ADR-0148 §8's fourth clause. Fired by the decision that lands a
  destination projection for any audit or listing surface, which the recipient-grant listing
  will want on the same ground.
- **A cross-goal listing of every authorization the user holds.** §11's listing is per goal,
  because `standing(goal)` is keyed on one and the set across goals is bounded by nothing this
  store carries. Fired by the decision that lands a goals listing on the promoted surface —
  **A3**, which ADR-0250 §12 already reserves the user's acts on a goal to — at which point the
  cross-goal read can be stated with whatever bound that surface gives it.
- **Retention for this store beyond `clear`.** Issue #108's shape one store over. Fired by the
  decision that lands retention for the audit trail.

### 20. The lane cut, and the arms this decision owes

> **Normative — the cut, and it agrees with §16's roster member for member.** **Lane 1, the
> contract triad and the policy.** `core/types.py`'s **ten** new types and **three** new
> fields — `PermissionRuling.authorised_goal`, `ActionRequest.goal` and
> `ToolDefinition.system_supplied`, each of which the policy reads — `core/protocols.py`'s three
> Protocols, `core/errors.py`'s two classes,
> **no `Settings` field at all** (§12), the shared conformance suites, the canonical fakes in
> `ai_assistant.testing`, the `SqliteGoalAuthorizationStore` in `permissions/`,
> `ThresholdActionPolicy`'s **route (d) and §6's bar** on the one `live_for` read, and
> `AuditTrail.record`'s route-(d) invariant. ADR-0137 §2's exception is what makes this one
> change: the triad rides with the primary consumer whose demands shape the contract. The
> **eight store signatures**, `AuthorizationSettlement`'s four outcomes and the two error
> classes (§16) are Lane 1's in full, and its conformance suites are what pin them.
> **Lane 2, the proposal, the settlement and the recheck.** `orchestration` proposing the row
> on §1's four conditions when a `CONFIRM` is recorded, settling it on the answer, writing a
> path-(ii) correction **and a path-(iii) opening act** — the last on a `RecipientGrants` and
> the two configured search values it is constructed with beside the store (§1) — taking §12's
> ladder, filling every system-supplied argument **before the candidate fit test** and refusing
> to build a request whose step arguments name one (§3),
> **setting** `ActionRequest.goal`, and phase 4's evaluation. **It adds no
> `core` type and no field**, both being Lane 1's, and **it writes no attempt bookkeeping**: the
> `AWAITING_AUTHORIZATION` commit and the `add_authorization_id` append are ADR-0249's lane's
> and are relied on rather than repeated. **Lane 3, the surfaces.** `core/types.py`'s **three**
> remaining types — `CoverageView`, `AuthorizationProjection` and `AuthorizationView` —
> `Confirmation.authorization` **and `TurnOutcome.authorizations`** (§11),
> `AssistantEngine`'s two members
> `standing_authorizations` and `revoke_authorization` (§11), the engine's assembly of both and
> of the confirmation projection, and the interface adapters that render them.

> **Normative — every lane that changes the wire carries its own bump, and no lane defers
> one.** Lane 1's bump takes a second ground beside the one §16 names: `ToolDefinition` gains
> `system_supplied` and crosses the wire inside a `PermissionDecision` a client decodes.
> ADR-0124 §9 requires the bump *"in the same change"*, and two of these lanes make a
> wire-carried value one peer emits invalid for the other. **Lane 1 bumps**:
> `PermissionRuling` gains a field, `PermissionRuling` is carried inside `PermissionDecision`,
> and a decision crosses the promoted surface today — so an older client decoding one under
> `extra="forbid"` refuses it, which is ADR-0124 §9's second limb exactly. **Lane 3 bumps**:
> it adds methods to the promoted surface and a member to `Confirmation` **and one to
> `TurnOutcome`**, each independently that ground. **Lane 2 changes no `core` type at all** — every type and field this decision
> adds lands with Lane 1 or Lane 3 (§16), and `ActionRequest`, whose `goal` Lane 2 sets,
> crosses no frame in any case — and it bumps nothing. **No integer is fixed here**, because
> other lanes of this batch move the same
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
>    `live_for` answers `None`, **no bar and no route (d)**, `CONFIRM`, and the earlier recorded
>    `ALLOW` is unchanged and
>    still true about the moment it was made. **And after a chain of corrections**: revoke the
>    superseding row and every argument is uncovered, including the ones whose members were
>    carried forward from the first act — there is no contributor left standing that the
>    revocation missed. **And a revoked or superseded row cannot be settled again**: `settle`
>    refuses every move that is not one of §1's five edges, and none leaves `REVOKED` or
>    `SUPERSEDED`.
> 4. **Revocation between `live_for` and `record`.** Settle the row the ruling names `REVOKED`
>    after `live_for` returned and before `AuditTrail.record` begins its resolution read → the
>    write is **refused**, on §7's disposition check, for the row behind **every** argument.
> 5. **Price inside the range.** An argument at, below and above `maximum` → covered, covered,
>    **not covered**; and at `minimum` where one is carried → covered.
> 6. **A price as a JSON float** → **not covered**, on §4's refusal, whatever its magnitude.
> 7. **A fixed value differing by one byte** — a recipient with one changed character, a
>    number rendered as a string where the member holds a number → **not covered** in each, on
>    the canonical JSON comparison and not on a looser one.
> 8. **An argument the record names in no member** → **not covered**, and the reason says which
>    of §4's three failures it is. It **names the key** where the declaration's
>    `parameters_schema` declares it and **does not quote the key** where the schema does not —
>    one test each, the second over a declaration admitting additional properties and a request
>    carrying a data-bearing key such as an address, asserting the key appears nowhere in the
>    recorded `reason` (ADR-0145 §8).
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
>     in between.** A `CONFIRM` recorded at 09:00 for a goal whose `deadline` is 21:00 proposes
>     a row carrying `proposed_at` 09:00 and `expires_at` 21:00; the confirmation names 21:00;
>     answered at 10:00 the row settles `ESTABLISHED` carrying 21:00 — **and the same holds
>     across a process restart, and across the goal's `deadline` edited to any other value in
>     that interval**, because both instants are read from the durable row and neither is
>     recomputed.
> 24. **An answer at or after that instant establishes nothing.** The `CONFIRM` resolves and
>     the one call is authorised by route (a); **no `Authorization` is written**, and the next
>     dispatch of that goal asks.
> 25. **A chain of corrections does not outlive the first act's expiry.** Three successive
>     superseding records carry one `expires_at`; the third covers nothing after it.
> 26. **The expiry touches nothing else.** A `RecipientGrant` established in the same run
>     keeps the instant the user chose; a route-(c) ruling is unaffected by any goal's
>     `deadline` and by any instant an act named.
> 27. **The recheck at dispatch refuses a changed argument before the claim.** A result
>     reference resolving to a value outside the bound → `CONFIRM`, the step parks, **no `→
>     RUNNING` transition is committed**.
> 28. **The route discriminator is total.** Rows of all four routes plus a policy-rules row →
>     each classified from the row alone, with **no store read**, and the route-(b) and
>     route-(c) classifications unchanged from `origin/main`.
> 29. **The trail refuses a route-(d) row** on each of §7's **ten** checks independently — a
>     pointer `resolve` answers `None` for, a disposition other than `ESTABLISHED`, a
>     `settled_at` after the decision's `decided_at` (the backdated case), an `expires_at` at or
>     before it, an unequal declaration, an unequal account, a destination of the binding the
>     row does not carry, an unequal goal, a digest recomputed unequal, and a binding whose
>     `coverage` is not `SpanCoverage.NOT_COVERED`. **The last is submitted directly as a ruling
>     a faulty policy could have authored**, with every other check passing, and is refused
>     **whatever the binding's `closed_loop` says** — including `True`, which is route (b)'s
>     ADR-0238 disjunct and route (c)'s eligibility and is neither of them here. **And the
>     eleventh check is asserted absent**: a route-(d) row whose binding carries
>     `planned_with_external_content`, every other check passing, is **accepted**, because §6's
>     discharge turns on coverage the trail cannot see (§7) — a lane that refused it has
>     restored a check this decision gave up and would refuse every fully covered call the
>     policy allowed.
> 30. **A sourceless policy reaches no route (d)** and leaves `authorised_by` and
>     `authorised_goal` unset, on every request including one at the configured provider.
> 31. **The floor route (d) does not relax, and the one it discharges, taken in both
>     directions.** *(a)* A request of a goal whose binding's `coverage` is not `NOT_COVERED`,
>     **not at the configured provider** and with a record covering every user-facing argument →
>     `CONFIRM`, because condition 4 is unrelaxed; and `_only_the_disclosure_floor`'s coverage
>     limb gains no disjunct, so `live_for` is called **zero** times. *(b)* The same request
>     **at the configured provider**, where that predicate's ADR-0247 §3 disjunct makes the
>     limb hold → **route (d) is still unreachable**, on condition 4 re-taken over the binding
>     in its strict form, and the ruling is route (c)'s `ALLOW` unless §6's bar fires. **A lane
>     that read route (d)'s fourth condition off `_only_the_disclosure_floor`'s answer fails
>     (b).** *(c)* A request whose binding carries `planned_with_external_content`, **not at the
>     configured provider**, whose goal holds a record covering it in **full** → **`ALLOW` on
>     route (d)**, admitted by the lineage limb's third disjunct; the same request with the
>     record covering all but one user-facing argument → **`CONFIRM`**, with `RecipientGrants.
>     covering` called **zero** times and no route answering, because the third disjunct admits
>     and never discharges.
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
> 35. **`Confirmation.authorization` is present exactly where §1's four proposal conditions
>     hold and absent otherwise**, is required with no default, and carries a bound as a bound,
>     a fixed value as a fixed value and the span as the span. A roster test in ADR-0178 §10's
>     shape over `AuthorizationProjection`, `CoverageView` and `AuthorizationView` asserts
>     that no field of any of the three is named or typed for a goal id, an authorization
>     `confirmation` or `supersedes`, a `BoundAccount`, a subject digest, a connection
>     reference, a `SecretName` or a transport endpoint — and that `AuthorizationView` carries
>     the row's `id`, no `destinations`, and `AuthorizationSettlement` nothing at all beyond
>     its four members.
> 36. **The store refuses a second `ESTABLISHED` row for one goal and declaration `id`** — a
>     second row about the *same* declaration and a second about an **edited** declaration of
>     that id, one test each; a superseding write for the same pair is accepted and settles the
>     predecessor in the same write. **And where two live rows are nevertheless present**, put
>     there behind the store's back, `live_for` **raises `AuthorizationError`** rather than
>     answering `None`, so §6's bar is taken: with a recipient grant covering the same
>     declaration, account and destinations, a request neither row covers draws **`CONFIRM`**
>     and `RecipientGrants.covering` is called **zero** times. **A lane that answered `None`
>     fails this arm.**
> 37. **The transition graph, edge by edge and non-edge by non-edge.** Each of the five edges
>     succeeds under compare-and-swap; every other move is **refused**, with one test per
>     retired disposition and one for `PROPOSED → REVOKED`, `PROPOSED → SUPERSEDED` and
>     `ESTABLISHED → DECLINED`/`EXPIRED`. A `PROPOSED` row is **never** live; a row read after
>     its `expires_at` while still `PROPOSED` is settled `EXPIRED` by a `live_for` read and by
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
>     and its own `wire/envelope.py` log entry; Lane 2 changes no `core` type and bumps
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
>     accommodation for a sourced policy. **It exercises the bar's own severity case**: with one
>     live record held fixed, raising a declaration's `risk_level` or `reversibility` below the
>     policy's threshold never produces a less restrictive outcome — the row is still found by
>     its `id`, the arguments are unchanged, and the bar fires where it fired before. **And it
>     pins §3's reading of "including that one" rather than leaving it to an implementation**:
>     the comparison holds the **authorisation input** equal as well as the store, so a pair
>     differing only in severity where one request is covered by a record and the other is not
>     is **outside** it — the suite asserts that pair is not required to order, exactly as it is
>     not required to for route (b) on `origin/main`, and a suite that required it would fail
>     ADR-0193's ratified grant policy too.
> 45. **§6's bar over route (b), which is the case it exists for.** A live record of the goal
>     bounding `amount` at GBP 60, **and** a `RecipientGrant` covering the same declaration,
>     account and destination set. A request of that goal for GBP 80, every other floor
>     satisfied → route (d) does not cover, **the bar fires**, `RecipientGrants.covering` is
>     called **zero** times, the ruling is `CONFIRM`, the step parks, **nothing is dispatched
>     and no claim is made**, and the reason names the argument. The same request at GBP 50 →
>     route (d) `ALLOW`.
> 46. **§6's bar over route (c).** A live record of the goal bounding or fixing an argument of a
>     `WEB_SEARCH` declaration, and a request of that goal at the configured provider whose
>     argument fails that member → **`CONFIRM`**, no route (c) `ALLOW`, and `authorised_by`
>     unset. The same request of a goal holding **no** such record → route (c) `ALLOW` on the
>     binding's `account.reference`, unchanged from `origin/main`.
> 47. **The bar fires on an argument the record names in no member, with the other authority
>     present.** A live record covering every user-facing argument of a booking request that omits an
>     optional one; a recipient grant covering the same declaration, account and destinations;
>     then *"add insurance"*, which path (ii) **refuses at construction** (arm 15). The next
>     dispatch carries `insurance` → **the bar fires**, `RecipientGrants.covering` is called
>     **zero** times, the ruling is `CONFIRM`, and the reason says the record names that
>     argument in no member rather than that a comparison failed (§4). **This is §5's *"reaches
>     no standing route at all"* and §9's *"an argument no member names"* made true of route (b)
>     as well as of route (d).**
> 48. **The bar's answer does not move with severity, in either direction, which is ADR-0021
>     §5's own obligation.** Both cases are taken over route (c), because route (b) compares the
>     declaration itself (ADR-0193 §3) and falls away with it. Confirmation threshold at `HIGH`
>     throughout, every request at the configured provider, so `fired == [_DISCLOSURE_FLOOR]`
>     everywhere and the records in the store are held equal.
>     *(a) Moving out of equality.* A live record **fixing** an argument of a `LOW`-risk
>     declaration; a request whose argument **differs** → **`CONFIRM`** on the bar. Raise only
>     that request's declaration to `MEDIUM` → the row is still found **by its `id`**, the
>     argument still differs, **the bar fires again**, `CONFIRM`. **A lane that keyed the lookup
>     by value fails here**: the row would match nothing and route (c) would answer `ALLOW`.
>     *(b) Moving into equality.* A live record fixing an argument of a `MEDIUM`-risk
>     declaration; a request at `LOW` with the **same declaration id** and the argument the
>     record fixes → the bar does **not** fire and route (c) answers `ALLOW`. Raise only that
>     request's declaration to `MEDIUM` → the bar still does not fire, and the ruling is an
>     `ALLOW` on route (c) or route (d). **A lane that put §3's condition 3 inside the bar fails
>     here**: the `LOW` request would have drawn `CONFIRM` and the `MEDIUM` one `ALLOW`, which
>     is the same violation from the other side.
> 49. **What the bar does not fire on, one test each.** A live record of the goal and
>     declaration id whose **declaration differs by value** from the request's; one whose
>     `account` differs; one whose `destinations` do not contain the request's; and one that has
>     **lapsed**, so `live_for` answers `None` → in each, every user-facing argument being covered, the bar
>     does **not** fire, route (d) does not cover, and route (b) or route (c) rules exactly as it
>     does on `origin/main`. **ADR-0193 §5 is the ground — a grant is about the declaration, the
>     account and the recipient — and the tests are named for it.**
> 50. **The bar reads nothing it need not.** A request carrying `goal` unset; a policy
>     constructed with no `GoalAuthorizations`; and a request on which
>     `_only_the_disclosure_floor` is false → `live_for` is called **zero** times in each, and
>     the ruling is what `origin/main` produces.
> 51. **One seam read per ruling.** A request the bar does not fire on and route (d) covers →
>     `live_for` is called **exactly once**, keyed on the goal and the declaration's `id`, and
>     the row it returned is the row `authorised_by` names; no second call, and no cached answer
>     reused across two `decide` calls.
> 52. **A store fault takes the bar and is never read as an absence.** With a live GBP 60 record
>     of the goal **and** a recipient grant covering the same declaration, account and
>     destinations, a GBP 80 request on which `live_for` raises `AuthorizationError` →
>     logged by class and no value, **no route (d), no route (c), no route (b)**, and the ruling
>     is `CONFIRM`. **The same request with the seam working answers `CONFIRM` too**, so the
>     fault never makes a ruling less restrictive; and a fault on a request carrying `goal`
>     unset is unreachable, because the seam is not read. **A lane that answered `None` on the
>     fault fails this arm**, the grant being enough to reach `ALLOW`.
> 53. **Removing an argument the record fixes is a change, not a licence.** A live record
>     covering `{"site": "A", "refundable_only": true}`; a recipient grant covering the same
>     declaration, account and destinations; then a request of that goal carrying
>     `{"site": "A"}` alone → **condition 6 fails on the key sets**, the bar fires,
>     `RecipientGrants.covering` is called **zero** times, the ruling is `CONFIRM`, and the
>     reason says a member names an argument the request omits. **A lane that read condition 6
>     over the request's keys alone fails this arm**, `ALLOW`ing a call that drops the term the
>     user fixed.
> 54. **An empty-coverage authorization, end to end.** An egress declaration whose call carries
>     `parameters={}`: the `CONFIRM` proposes a row with `coverage=()`, the confirmation carries
>     a **present** `AuthorizationProjection` whose `coverage` is empty and whose `expires_at`
>     is the row's, answering establishes it, and a later argument-free request of that goal is
>     **covered** on §3's conditions 1-5 with condition 6 holding vacuously. **And a later
>     request of that goal and declaration carrying any argument at all draws `CONFIRM` on §6's
>     bar** — the record names that argument in no member, so condition 6 fails — **with a
>     recipient grant covering the same declaration, account and destinations in the store and
>     `RecipientGrants.covering` called zero times.** An empty `coverage` is an authority over
>     an argument-free call and is a wildcard over nothing.
> 55. **`settle`'s four outcomes, over every move §1's graph admits and refuses.** Each of the
>     five edges from its own source → `SETTLED`; the same call repeated → `NOT_AT_SOURCE`; a
>     move asked of a row standing anywhere but that edge's source, one test per retired
>     disposition and one for a `PROPOSED` row asked for `REVOKED` → `NOT_AT_SOURCE`; two
>     settlements raced on one row → one `SETTLED` and one `NOT_AT_SOURCE`, never two winners;
>     an id the store does not hold → `NO_SUCH_AUTHORIZATION`. **No call raises and none returns
>     a `bool`**, and the same values reach the surface through `revoke_authorization` unmapped
>     — with **`WOULD_DUPLICATE` never among them**, asserted over a revocation of a row of a
>     pair another row is established for.
> 56. **Two proposals of one goal and declaration id, which is where uniqueness can break.**
>     Record two `PROPOSED` rows of that pair from two different `CONFIRM`s, neither carrying
>     `supersedes` → **both writes succeed**, because neither leaves two rows `ESTABLISHED` and
>     neither is `record`'s to refuse. Establish the first → `SETTLED`. Establish the second →
>     **`WOULD_DUPLICATE`**, nothing is written, and `standing(goal)` still returns exactly the
>     first. **Run the two settlements concurrently** → exactly one `SETTLED` and one
>     `WOULD_DUPLICATE`, never two winners and never an interleaving that leaves two rows
>     `ESTABLISHED`. And where the second **does** carry `supersedes` naming the first →
>     `SETTLED`, the first settles `SUPERSEDED` **in that same write**, and at no instant are
>     both established.
> 57. **A path-(i) proposal retires nothing until it is answered.** A live row bounding GBP 60;
>     a path-(i) proposal for GBP 80 naming it in `supersedes`; a recipient grant covering the
>     same declaration, account and destinations. **While the question stands**: the GBP 60 row
>     is still `ESTABLISHED` and still live, `standing(goal)` returns it, a GBP 60 request is
>     covered, and a GBP 80 request draws **`CONFIRM`** on §6's bar with
>     `RecipientGrants.covering` called **zero** times. **Declining** settles the proposal
>     `DECLINED` and leaves the GBP 60 row exactly as it was, with the same three results.
>     **A lane whose `record` settled the predecessor at the proposal fails this arm** — the
>     bar would have had no row to test and the declined widening would have dispatched.
> 58. **`record` refuses with `InvalidAuthorizationError` and a fault raises
>     `AuthorizationError`.** A second `ESTABLISHED` row of one goal and declaration id; a
>     path-(ii) row failing the transcription check; one failing the non-widening check; a row
>     carrying `confirmation` written in any disposition but `PROPOSED`; a `supersedes`
>     resolving to no `ESTABLISHED` row of that goal and declaration id → each raises
>     `InvalidAuthorizationError`, one test per ground, and nothing is written. An unreadable
>     store raises `AuthorizationError`, which the subclass relation means a caller catching the
>     base class still catches. **`recent` refuses a `limit` that is not a strictly positive
>     `int` locally and before any I/O.**
> 59. **Which `CONFIRM` proposes a row** (§1). A `CONFIRM` on a request carrying `goal` unset; a
>     `CONFIRM` on a request carrying no `egress_binding`; and a `CONFIRM` on an egress request
>     one of whose arguments no resolution minted a member for → **no row is written** in each,
>     `Confirmation.authorization` is **absent**, and answering resolves the `CONFIRM` and
>     authorises the one call by route (a) and establishes nothing. A `CONFIRM` meeting all
>     four conditions → a row is written `PROPOSED` and the projection is present.
> 60. **The proposal reads no floor of §6's.** A `CONFIRM` on an egress request whose binding's
>     `coverage` is not `NOT_COVERED`, meeting §1's four conditions → a row **is** proposed and
>     answering establishes it; a later request of that goal carrying covered content draws
>     `CONFIRM` on §6's condition 4 all the same, and one carrying none is covered.
> 61. **The listing and the revocation.** `standing_authorizations(goal_id)` returns one
>     `AuthorizationView` per `ESTABLISHED` row of that goal, live and lapsed, never a
>     `PROPOSED`, a `DECLINED`, an `EXPIRED`, a `REVOKED` or a `SUPERSEDED` one and never
>     another goal's; `live` is set from **one** clock reading for the whole listing; the goal's
>     statement comes from `PlanStore.get_goal` and a goal that store does not hold is an
>     **empty answer and not a raise**; each `CoverageView` carries the member's span. Then
>     `revoke_authorization` on a live row → `REVOKED`; on a lapsed `ESTABLISHED` row →
>     `REVOKED`; on a `PROPOSED`, `DECLINED`, `EXPIRED`, `REVOKED` or `SUPERSEDED` row →
>     `NOT_AT_SOURCE`, one test each; on an id the store does not hold →
>     `NO_SUCH_AUTHORIZATION`. **No call raises**, and a revoked row is absent from the next
>     listing.
> 62. **The rendering bar, at the listing.** The view carries the row's `id` and the surface
>     renders it; **no** subject digest, `BoundAccount`, account reference, connection
>     reference, `confirmation`, `supersedes`, resolution **or `destinations`** reaches it, one
>     assertion each, and the goal is rendered by statement and never by id. **The
>     `destinations` assertion is taken over a record whose destination set is the connected
>     account**, which is the case `CanonicalDestination`'s account arm would have carried a
>     `BoundAccount.reference` through.
> 63. **A predecessor that leaves `ESTABLISHED` while the question stands** (§1's
>     conditional-supersession clause). Establish A; record a path-(i) proposal B carrying
>     `supersedes=A`; **revoke A**; then settle B `ESTABLISHED` before its `expires_at` →
>     **`SETTLED`**, A is **still `REVOKED`** and was not written to, B stands `ESTABLISHED`,
>     and `standing(goal)` returns **B alone**. The same with A **superseded by a third row C**
>     instead of revoked, C then revoked → **`SETTLED`**, A still `SUPERSEDED` and C still
>     `REVOKED`. **And where C still stands `ESTABLISHED`** when B is settled →
>     **`WOULD_DUPLICATE`**, nothing is written, B stays `PROPOSED` and `standing(goal)` still
>     returns exactly C. **Both orders of the race are defined**: run the revocation of A and
>     the establishment of B concurrently, and either the revocation wins — `REVOKED` then
>     `SETTLED`, by the first arm — or the establishment does, in which case the revocation
>     answers **`NOT_AT_SOURCE`** because A is by then `SUPERSEDED`; **never two winners and
>     never an interleaving that leaves two rows of that pair `ESTABLISHED`**. **A lane that
>     refused the establishment here fails this arm**, as does one that answered `SETTLED`
>     while moving A out of a retired disposition.
> 64. **An opening act authorises without a question** (§1's path (iii)). A recorded turn of the
>     goal says *"you may spend up to fifty pounds on this"*; no row of that goal and
>     declaration id stands `ESTABLISHED`; the goal carries a `deadline`; **and a live
>     `RecipientGrant` covers the declaration, the account and the whole canonical destination
>     set of the request being built**. The first egress request of that goal reaching that
>     declaration → **a row is written `ESTABLISHED`** with
>     `confirmation` and `supersedes` both unset, `origin` **`OPENING_ACT`**, `settled_at` equal
>     to `proposed_at` equal to the turn's instant, `expires_at` the goal's `deadline`, one
>     member bounding the amount with the turn's own span as its basis — and the request draws
>     **`ALLOW` on route (d)** with **no `CONFIRM` put at all**.
>     **`TurnOutcome.authorizations` on that turn carries exactly one `AuthorizationView`** for
>     the row — its declaration's `VisibleIdentifier` and description, the bound with the user's
>     own span, the expiry, `live` true, and the row's `id` as the revocation handle — and it is
>     **empty** on every turn that opened none, **including a turn that only re-grounds an
>     existing constraint**, which is the case ADR-0250 §5 requires to stay unannounced and is
>     why this member exists. **And an act opening two authorities announces two**: *"up to fifty
>     pounds for the train and a hundred for the hotel"* over two declarations whose price
>     argument is each named `amount` → **two rows, two views, two different bounds**, each
>     naming its own declaration, and neither row carrying the other's member. **A lane that
>     merged them fails this arm**, and so does one that announced only the first.
>     `standing(goal)` returns the row, §11's listing renders its coverage, its span and its
>     expiry, and `revoke_authorization` on it → `REVOKED`, after which the next request of that
>     goal draws `CONFIRM`. **And the safeguards**: where the span admits two admissible values
>     the resolution is not taken, **no row is written**, and the question is put under
>     ADR-0250 §6's three conditions — asserted by driving a turn whose planner raised no
>     `ProposedQuestion`, where no question is put and no row is written either. **A row with
>     `confirmation` and `supersedes` both unset and `coverage=()` is not constructible**, one
>     test, **and one carrying a non-empty `coverage` round-trips through construction and
>     persistence in every disposition it can reach**, `origin` included. **And where a row of that pair already
>     stands `ESTABLISHED`, no path-(iii) row is written** — the act is a correction and takes
>     path (ii), or a widening and takes path (i).
> 65. **An opening act supplies no recipient authority** (§1). The same act and the same goal,
>     with **no** live recipient grant covering the request → **no path-(iii) row is written**, the request draws **`CONFIRM`**, and the
>     confirmation names the canonical destination set. **Answering it proposes a path-(i) row
>     whose amount member carries the *earlier* turn's span and act as its basis**, so the user
>     is asked about the recipient and **never asked to repeat the bound** — asserted by reading
>     the established row's basis and finding the opening turn's id, not the confirmation's.
>     **And the negative arms, one test each**: a grant covering the declaration and account but
>     not every member of the destination set; a grant for a different `BoundAccount`; a grant
>     whose `ToolDefinition` differs by value; an **expired** grant — in each, **no path-(iii)
>     row** and a `CONFIRM`. **And a writer constructed with no `RecipientGrants` and no
>     configured search values writes no path-(iii) row at all**, whatever the act said.
> 66. **A schema-required system-supplied argument is selectable and dispatchable** (§3, §14). A
>     declaration whose `parameters_schema` **requires** `idempotency_key` and whose
>     `system_supplied` names it; a plan step naming every other argument and **not** that one →
>     the candidate is **eligible**, the fit evaluation being taken over the step's parameters
>     merged with the value `orchestration` fills for that candidate; phase 4's check 2 passes;
>     the request is built carrying the key; ADR-0145 §1's construction check passes over the
>     final arguments; and a covering record naming every user-facing argument and **not** that
>     key → **`ALLOW` on route (d)**. **The same step naming the key itself → the request is not
>     built**, no ruling is sought and no `CONFIRM` is put. **And `core`'s evaluator is called
>     unchanged**: one implementation, one signature, and the merged mapping is the only thing
>     that moved — asserted by a test that the merge overwrites no step parameter.
> 67. **Full coverage discharges ADR-0181 §5's floor, and partial coverage does not** (§6). A
>     live record fixing every user-facing argument and carrying the request's whole canonical
>     destination set; the request's binding carries **`planned_with_external_content`** and its
>     `coverage` is `SpanCoverage.NOT_COVERED` → **`ALLOW` on route (d)**, `authorised_goal`
>     set, `RecipientGrants.covering` called **zero** times, and `AuditTrail.record` **accepts**
>     the row on its ten checks. **The negative arms, one test each**: a destination taken from
>     fetched content that the row's set does not contain → **`CONFIRM`**; a user-facing
>     argument taken from fetched content that the row names in no member → **`CONFIRM`** on
>     §6's bar; an argument whose value the member's comparison refused → **`CONFIRM`**. **And
>     the coverage limb is not discharged**: the same fully covered record with the binding's
>     `coverage` at `MODEL_ON_EVERY_PATH` → **`CONFIRM`**, on condition 4, which route (d)
>     relaxes for nothing. **And route (b) inherits none of it**: a recipient grant covering the
>     declaration, account and destinations of a tainted request, with no authorization →
>     **`CONFIRM`**, ADR-0193 §4 unmoved.
> 68. **A system-supplied argument is neither covered nor asked about** (§3). A declaration whose
>     `system_supplied` names an idempotency key and a locale; a record fixing every other
>     argument and naming neither → the request carrying both **is covered**, condition 6 holding
>     over the user-facing arguments alone, and **`ALLOW` on route (d)**; **§6's bar does not
>     fire** on the unnamed system-supplied keys. **A `CoverageMember` naming one of them makes
>     the row not constructible**, one test. **A plan step whose own arguments name one → the
>     request is not built**, the step does not dispatch, **no ruling is sought and no `CONFIRM`
>     is put**. And `parameters_digest` is taken over **every** argument, so moving a
>     system-supplied value between the ruling and the dispatch is still refused by `rebind`.
>     **A declaration classifying none behaves exactly as before**, one test over arm 1's record.
> 69. **The expiry ladder, and there is no `Settings` field to move** (§12). An act naming an
>     instant → `expires_at` is that instant, carried with the span that named it. An act naming
>     none on a goal carrying a `deadline` → `expires_at` is the `deadline`, transcribed. An act
>     naming none on a goal carrying **no** `deadline`, and one carrying a `deadline` at or
>     before `proposed_at` → **no path-(i) proposal and no path-(iii) row is written**,
>     `Confirmation.authorization` is **absent**, and the call is confirmed under route (a), one
>     test each. **And the ladder does not reach path (ii)**: a live row with an explicit future
>     `expires_at` on a goal carrying **no** `deadline`, corrected by *"make it Sunday"* naming
>     no horizon → the correction **is written**, transcribing that `expires_at` unchanged. **A
>     lane that applied the ladder to a correction fails this arm.** **Editing the goal's
>     `deadline` after the row is written moves no `expires_at`.** **`Settings` carries no
>     authorization field**, asserted by a roster test over `Settings` in ADR-0178 §10's shape,
>     and `RecipientGrant.expires_at` and the configured-provider authority are untouched.
> 70. **An opening act's authority ends when the recipient authority behind it does** (§1, §6).
>     Establish an opening-act row over a live grant, then **revoke the grant** → the next
>     request of that goal, every user-facing argument still covered and the row still live,
>     draws **`CONFIRM`**: route (d) does not cover because the grant condition fails, route (b)
>     does not cover because there is no grant, and the bar does not fire because the row
>     covers. **The same with the grant lapsed by its own `expires_at`**, and **the same with a
>     grant narrowed to a destination set the request exceeds**, one test each. **And where a
>     *different* live grant covers the request, route (d) covers** — the condition is *a live
>     grant covers this request* and never *this grant*. **The seam is read over `origin` and
>     never over the pointer shape**: it is consulted exactly **once** on a ruling over any row
>     whose `origin` is `OPENING_ACT`, **including a path-(ii) correction of one**, and **zero**
>     times on a ruling over a row whose `origin` is `CONFIRMED`, whichever path wrote it.
>     **The dependency therefore survives a correction**: open the row, correct it under path
>     (ii) to a narrower bound, **then** revoke the grant → the next request draws **`CONFIRM`**.
>     **And a path-(i) supersession discharges it**: ask the user, who is shown the destination
>     set and approves → the replacement carries `origin` `CONFIRMED`, route (d) covers with the
>     seam consulted **zero** times, and revoking the grant thereafter changes nothing.
>     **And the grant's instant is never copied onto the row**: a goal whose `deadline` falls at
>     18:00 and a grant expiring at 12:00 yield a row carrying **18:00** — §12's ladder and
>     nothing else — and the authority nevertheless stops covering at 12:00, because the recheck
>     and not the field is what enforces it. **A lane that wrote an opening-act row and then let
>     route (d) carry it alone fails this arm**, as does one that stated the discriminator over
>     the pointer shape, and as does one that copied the grant's expiry onto the row.
> 71. **A clock that moves backwards refuses rather than disagreeing** (§1). Establish a row at
>     11:00 with `expires_at` 18:00, then move the clock to 10:00 → `live_for` answers **`None`**
>     because the reading is before `settled_at`, no route (d) is taken, the ruling is
>     `CONFIRM`, and §11's listing reports the row **not live** — the policy and the trail agree,
>     where a liveness stated over the upper end alone would have produced a route-(d) `ALLOW`
>     the trail then refused as backdated. **Equality at the lower end is live**, one test.

### 21. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding
the corpus without it has three routes to an egress `ALLOW`, no record that bounds an argument
value, no seam through which a policy could read one, and no answer to the question ADR-0249
§13, ADR-0250 §11, ADR-0252 §15 and ADR-0253 §11 each defer here by name. They would build a
`PermissionRuling` with two authority fields, an `ActionRequest` with no goal, and a phase 4
that evaluates three predicates and adds none. That is ADR-0070 §1's test met, and a new ADR is
the instrument.

**It is a partial supersession of exactly seven documents** (ADR-0070 §3) — ADR-0148 in one
scope, ADR-0193 in one, ADR-0247 in **three**, ADR-0181 in one, ADR-0016 in **two**, ADR-0144
in one and ADR-0250 in one — and the
`Status` line of each names its scope **without an `ADR-NNNN` token inside the parentheses**, so
ADR-0070 §4's extraction invariant holds. Every other ADR it touches is **relied on**, and §18
shows the working for each rather than leaving a reader to check.

**The records land in the same change as this document** (ADR-0082 §7): ADR-0148's, ADR-0193's,
ADR-0247's, ADR-0181's, ADR-0016's, ADR-0144's and ADR-0250's `Status` qualifiers and dated notes
are written with it and not after it. Nothing else in any of the seven is edited — no Decision
text is rewritten, which ADR-0070 §1 forbids.

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
merely per call. ADR-0021 §3's carried-but-unread `parameters` gets the per-call gating
ADR-0017 §3 made a condition on designating the seam — the first rule in this corpus to read
one — and the attempt bookkeeping ADR-0249's lane already writes needs no addition at all.

**What becomes harder.** There is now a second standing authority for egress, and the trail
tells four routes apart rather than three — a partition that is total today and that every later
standing source must extend rather than join. **And for the first time in this corpus one
standing authority refuses what another would have allowed**: §6's bar is a refusal taken before
any route is tried, so a reader of the policy can no longer answer *"does a standing route cover
this?"* from one seam. That is the cost of the ADR-0193 §5 line being real — a grant reaches the
recipient and never the payload — and it is paid at one store read on every request that reaches
the standing routes carrying a goal, including a search at the configured provider, which read
none before. **And because that seam discovers restrictions as well as permissions, a fault in
it is not free**: it takes the bar rather than answering absence, so a goal whose authorization
store cannot be read asks about every call it would otherwise have dispatched. That is the only
direction a restriction may fail in, and it is a real availability cost this decision accepts
rather than hides. The policy takes a second durable read and a third constructor argument.
`ActionRequest`, `PermissionRuling` and `Confirmation` each gain a field, twelve types and three
Protocols arrive with them, `AssistantEngine` gains two members, and two `PROTOCOL_VERSION`
bumps land at a moment when several lanes of this batch are also moving `core`.

A correction now writes a whole record rather than a delta, so a long chain of corrections
writes a long chain of records — bounded by the expiry, and the store is append-only anyway. And
the per-argument comparison is the first rule in this corpus that reads a payload: everything
about how an argument is read for a bound (§4) is new surface with new ways to be wrong, which
is why every reading refuses what it cannot prove and why the arms above test each refusal
independently.

**A cost this decision does not carry, because the declaration now says which arguments are the
user's.** §3 requires every **user-facing** argument to be covered, and `ToolDefinition.
system_supplied` is what tells those apart from an idempotency key, a client reference or a
locale — so a declaration carrying such an argument is no longer one whose calls always ask, and
an implementation choice never becomes a question put to the user. The cost moves rather than
disappearing: it is now on the **declaration author**, who must classify honestly, and the
default is the strict one, so an author who says nothing gets the old behaviour and asks more
rather than less. **And a system-supplied argument is the system's to fill**: a plan step
reaching for one is refused outright rather than confirmed, because a value the model chose and
the user was asked to approve is neither the system's nor the user's.

**What is deliberately still missing, and stated so nobody reads it as done.** Route (d) reaches
a call planned over external content **only** where the record covers every user-facing argument
and the whole destination set (§6), and it does not reach a call carrying **covered content** at
all — so a booking composed over a covered supply still asks, and §19 books the decision that
would change it. That discharge also costs the audit trail one check: whether the lineage floor
was discharged turns on coverage the trail cannot see, so §7 takes ten checks rather than eleven
and says which one it gave up and why. Nothing here dispatches, drives,
retries, verifies or cancels anything; the owner's Q4 rule (§17) is carried rather than
discharged, and no consequential capability is wired by this decision or by the lanes that
implement it. And phase 4's evaluation reads two contracts — ADR-0252's evidence rows and
ADR-0253's step fields — that are **ratified and not implemented** at `origin/main`, so Lane 2
cannot land before they are.

**What would trigger revisiting this.** A fourth kind of bound an argument actually needs; a
second standing source for egress, which must extend §7's partition; a decision that takes
ADR-0233 §9's second clause head-on; evidence that goals in practice carry no `deadline`, in
which case §12's third rung is doing the work and the repair is to ask the user for the instant
rather than to mint a deployment figure; or evidence that declaration authors classify
`system_supplied` dishonestly, which is a registry-admission question and not a coverage one.

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

**A deployment-wide TTL, with a `Settings` figure and a default.** Rejected in §12, and it was
the first design. A figure an operator set is a clock the user never saw, so it cannot satisfy
decision 7's *"justified"* at all, and a long-lived goal would lose its authority for a reason
nobody stated at the act. What replaced it takes the instant from the act where the user named
one and from the goal's own `deadline` where they did not — decision 4's *no separate arbitrary
timer* — and writes **no row** where neither exists, rather than inventing a horizon. **Asking
"until when?"** was the third option and is still declined: it is a second question at the moment
the design exists to remove one, and §19 books it with what would fire it.

**Carrying the user-facing/system-supplied classification as a JSON Schema keyword.** Rejected in
§3. ADR-0145 §5 reads one dialect and states the hazard in its own words — 2020-12 *"ignores
keywords it does not know"*, so the classification would be *"silently dropped"* by the very
mechanism that ADR exists to close — and ADR-0145 §9's *"An absent schema declares no
constraint"* would leave a schema-less declaration unable to classify anything. A typed field
beside `parameters_schema` states the fact where every other declared safety fact of a tool
already lives, and §4's rule that no comparison consults a schema stays entire.

**Minting a fourth phase-outcome vocabulary** — ready / awaiting / needs-revision. Rejected in
§14. `AttemptPhase` and `AttemptState` already carry every state phase 4 can leave an attempt in,
`AWAITING_AUTHORIZATION` is a closed member whose producer ADR-0249's lane already wrote, and a
second vocabulary would be two authorities that can disagree about one fact — the argument ADR-0249 §5 makes when it
declines a fifth `GoalStatus` member for "paused".
