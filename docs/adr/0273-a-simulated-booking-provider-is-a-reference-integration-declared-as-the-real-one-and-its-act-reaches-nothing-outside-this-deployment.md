# 273. A simulated booking provider is a reference integration declared as the real one, and its act reaches nothing outside this deployment

- Status: Proposed
- Date: 2026-09-16

## Context

### Where this comes from

The owner ruled on [#2255](https://github.com/leonapivato/ai-assistant/issues/2255)
(2026-09-15) that the M33 campsite walkthrough's **booking is simulated**, that a
mock forecast is fine, and that verification space exists but need not be strong.
The money path the walkthrough drives has landed in declaration form — ADR-0267's
quote and its mint, ADR-0271's `charged_output` and its pin, ADR-0259's effect
claim, ADR-0262's pinned declaration — and every arm of it is asserted today over
controlled fakes. What does not exist is a **component** the walkthrough can drive
those mechanisms through: a thing that quotes a price, books once, charges, and
reports what it charged, behind the same declarations and the same seam a real
provider would sit behind.

ADR-0255 §13 and ADR-0260 §12 each forbid a lane from wiring a consequential
capability on its own authority, and §13's rule is explicitly *"carried and not
discharged"*. **This is the decision those clauses require before one is built.**

### The precedent this follows, and the one respect in which it cannot

ADR-0260 §12 is the shape. That section delivers *"the reference provider, behind
the `Forecaster` contract and bound like every other integration"*, registered
against a connection the user provisioned by ADR-0149 §4's explicit act,
performing *"ADR-0148 §6's four pre-transmit conditions whole"*, and its behaviour
*"honest, because it is the M33 walkthrough's forecast half until a real one
lands"*. Its own limit is stated in the same section: *"What it may not do is
stand in for a clause"*.

The respect in which this decision cannot simply copy it is what makes it worth an
ADR of its own. **A forecast read performs nothing.** A booking **acts**: it is
`side_effecting`, it charges a number a user was quoted, and every guarantee
ADR-0255 §13 gates on — at-most-once, cancellation, verification — has a subject
only because it acts. So the question ADR-0260 never had to ask is the one this
document answers: *what may a reference provider that acts be allowed to do, and
on what ground is building it not the wiring §13 forbids?*

### The tree, read rather than assumed, at `origin/main` `474d0735`

- **`ToolDefinition`** (`core/types.py`) carries `quoted_output: QuotedOutput |
  None = None` and `charged_output: ChargedOutput | None = None`, alongside the
  required `risk_level`, `reversibility`, `side_effecting`, `reads`, `writes`,
  `discloses`, `cost` and `idempotency`. `_effects_are_consistent` refuses three
  shapes: *"a tool that writes is side-effecting"*, *"a tool that discloses data
  off-device is side-effecting"*, and *"a tool with no side effect has nothing to
  reverse, so it is REVERSIBLE"*.
- **There is no effect-key field, and none is declarable.** `ToolCall.effect_key`
  derives it, and is documented as *"Derived rather than minted, supplied,
  configured or carried as a field"*, `None` *"if and only if the tool is not
  `side_effecting`"*.
- **There is no reconciliation-lookup field.** The predicate is
  `_reconcilable` in `orchestration/reconciling.py`, whose body is
  `not decision.tool.side_effecting and decision.egress_binding is None`.
- **`build_forecast_integration` is in `tools/builtin.py`**, not
  `tools/forecast.py`, and returns a `ForecastIntegration` carrying a forecaster
  and an `EgressRegistration`. **It is registered at the egress seam and in no
  `ToolRegistry`** — `build_default_registry` has no forecast parameter at all,
  because *"a registry entry would put its capability in front of the planner"*.
  The **email** integration, by contrast, is in both.
- **`Settings` has no `forecast_enabled` flag.** Four fields default to `None`,
  and `_the_forecast_registration_is_whole_or_absent` refuses a half
  configuration; absent all four, no forecaster object is constructed at all.
- **`OutboundDestination` is closed at two members today** — `SEARCH_PROVIDER`
  and `FORECAST_PROVIDER` — ADR-0260 having added the second to the one ADR-0264
  §5 minted.
- **`ConnectedAccount` carries exactly four fields** — `reference`, `identity`,
  `revision`, `state` — under `extra="forbid"`, and `_render_connections` states
  the consequence: *"A listing says which account and not which service, and that
  is a consequence rather than an omission: nothing in the tree says what an
  integration is yet, so there is nothing honest to put there (ADR-0151 §18)."*
- **ADR-0271's charge-against-quote comparison has not landed in `src/`.** The
  declaration field and the pin (`PermissionRuling.proved_quote`) exist; nothing
  reads `charged_output` at run time yet.

### Four things in the framing that do not survive contact with that tree

**First, a booking is not reconcilable, and there is no declaration to make it
one.** ADR-0259 §3 admits a reconciliation exactly where the committed
`ToolDefinition` is *"**not `side_effecting`** and the `PermissionDecision` its
`approval_ref` names carries **no `egress_binding`**"* — the complete conjunction —
and says in the same clause that *"**no `ToolDefinition` field is added to say
so**: the existing declarations are that test already"*. A booking fails both
limbs. §10 of that ADR books *"A third reconciliation route — a declared
reconciliation read on `ToolDefinition`, or an integration that can report an
effect's status without performing it"* as **not decided**, *"Fired by an
integration that offers such a read."* So no lookup can be declared here; §4
states what happens instead and §8 books the route.

**Second, ADR-0255 §13's gate is seven conditions and not the three its own
sentence names.** ADR-0265 and ADR-0267 each record a scope on §15 item 19's
**count**: three in its own text, five by its own parenthesis, six by ADR-0265's
containment for a wrongly minted intended action, and **seven** by ADR-0267, whose
seventh binds *"one whose acts are authorised through a `MONEY` ceiling … only
where the provider offers an enforceable **hold** on the quoted amount, or a
**conditional execution** that validates the quoted amount atomically with the
act"*. An ADR reading §13's three would clear a gate that is not cleared.

**Third, the walkthrough needs a provider that *fails* that seventh condition.**
ADR-0271 §3's finding exists for the case where the charge disagrees with the
quote the dispatch was pinned to, and no arm can drive a finding the provider
makes unreachable. **That is not a defect of the reference provider; it is the
reason it is a reference provider and not a production one**, and §7 makes it the
ground rather than leaving it as an awkwardness.

**Fourth, the connection listing cannot carry a *this is simulated* fact today.**
`ConnectedAccount` is four fields under `extra="forbid"` and the renderer
forecloses annotation by name. Announcing there is a `core/types.py` change under
ADR-0151 §18 and is **not** this decision's; §6 puts the announcement where the
user actually meets it and books the listing.

## Decision

### 1. One integration, two declarations, absent unless a deployment configures it whole

> **Normative.** A **simulated booking provider** is added in `tools/`, in a module
> of its own: a reference integration built by a single factory in
> `tools/builtin.py`, in `build_forecast_integration`'s shape, and wired from
> `app/composition.py` alone. It registers **exactly two** `ToolDefinition`s — an
> **availability read** and a **booking act** — and nothing else.

> **Normative — it is absent by default, and absence is the whole-or-absent shape
> `Settings` already uses and not a boolean flag.** Every configuration field it
> needs defaults to **absent**; a deployment supplying **none** of them builds **no
> provider object at all**, registers nothing in any registry and adds no entry to
> the seam's registration table; and a deployment supplying **some but not all** is
> **refused by a `Settings` model validator**, in
> `_the_forecast_registration_is_whole_or_absent`'s form. **A boolean flag beside an
> incomplete configuration is not an implementation of this clause**: it makes
> *enabled but unusable* a representable state, which is the half-configured
> provider ADR-0260 §11 refused for the forecaster.

> **Normative — configuring it is an operator act and nothing else can perform
> it.** **No model, no plan, no planner, no tool, no user-facing surface and no
> API enables this provider, and none is given a way to.** It is enabled by editing
> the deployment's configuration and restarting, and **no lane adds a second
> route.**

> **Normative — it registers only against a connection the user provisioned by
> ADR-0149 §4's explicit act**, supplying an identity and a credential the
> simulated provider **accepts and does not use**, exactly as ADR-0260 §12 rules
> for the reference forecaster. **No connection, credential, identity, reference or
> endpoint is fabricated, defaulted or inferred to make registration succeed.**

> **Normative — both declarations go in the `ToolRegistry` as well as the seam's
> registration table, which is the email integration's shape and deliberately not
> the forecast read's.** ADR-0260 §1 keeps the forecast read out of every registry
> because *"a registry entry would put its capability in front of the planner, and
> the planner naming it is the outcome the whole design exists to make
> unreachable"*. **Here the opposite is the requirement**: M33 is the planner
> proposing a booking, the user confirming it and the driver dispatching it, and a
> capability no planner can name has no walkthrough at all. **A lane that reads
> ADR-0260 §1 as a rule about egress integrations in general has read a clause
> written about a read that no user asks for.**

**Two declarations and not one, because the money path needs both ends.** The
quote is read from a step's `output` (ADR-0267 §4) and the charge from the acting
step's own (ADR-0271 §2), and ADR-0271 §2 forbids that *"no lane … mints an
`ActionQuote` from a charge"*. A single declaration that both quoted and charged
would make the acting step its own quote's producer, which is the defect
[#2409](https://github.com/leonapivato/ai-assistant/issues/2409) names.

### 2. What each declaration says, and the two kinds of field it says it with

**The fields divide, and the division is what keeps every one of them true.**
`reads`, `writes` and `discloses` are facts about **data reach** — what this
component actually touches, ADR-0016 §3's scale. `side_effecting`,
`reversibility`, `idempotency` and `risk_level` are facts about **the effect on
the system acted upon**, which for this provider is its own configured state.
Both sets are declared about *this* component and neither is declared about the
act it stands in for; that they come out differently is the whole content of §2.

> **Normative.** The **availability read** declares `side_effecting: False`,
> `idempotency: Idempotency.NATURAL`, `reversibility: Reversibility.REVERSIBLE`
> (which `_effects_are_consistent` requires of anything not side-effecting),
> **`risk_level: RiskLevel.LOW`**, **`cost: ToolCost(basis=CostBasis.FREE)`**, and a
> **`quoted_output`** naming, at depth one, the key carrying **the whole price this
> provider quotes for the booking** — `QuotedOutput.amount` in ADR-0267 §3's own
> sense — and the key carrying its ISO-4217 code. It
> declares **`charged_output: None`**: a read charges nothing, and ADR-0271 §2's
> *"A declaration carrying `None` reports no charge ever"* is the true statement
> here.

> **Normative.** The **booking act** declares `side_effecting: True`,
> `idempotency: Idempotency.NONE`, `reversibility: Reversibility.IRREVERSIBLE`,
> `risk_level: RiskLevel.HIGH`, **`cost: ToolCost(basis=CostBasis.FREE)`**, and a
> **`charged_output`** naming, at depth one, the key carrying **the whole amount
> that invocation charged** and the key carrying its ISO-4217 code (ADR-0271 §2).
> It declares **`quoted_output: None`**.

> **Normative — the booking has a durable state change, and it is *two* things,
> because one of them must be prunable and the other must not.** A booking commits,
> to durable state the provider holds **under the deployment's data directory**:
>
> 1. a **booking record** carrying what it was asked and what it charged — the
>    detail, which is the user's; and
> 2. an advance of a **monotonic commit count**, a non-personal figure the provider
>    increments on every committed booking and **never decrements**.
>
> Both **survive a restart**, and **the provider offers no operation that removes
> or amends either**. **Without a durable effect, `IRREVERSIBLE` would be a claim
> about nothing** — an implementation returning configured JSON and changing no
> state would satisfy every arm below while reproducing neither the double booking
> nor the failed cancellation the walkthrough exists to demonstrate. This decision
> fixes **no store, no schema and no file format**, and the count is **a figure and
> not a log**: it carries no identifier, no instant and nothing of what was booked.

> **Normative — the append is failure-atomic and serialised.** A record is
> **wholly present or wholly absent** after any interruption, and two appends in
> one process **never interleave**, so a stop mid-write cannot leave a partial
> record that makes the store unreadable on the next start. **A naive append that
> can be truncated or interleaved is not an implementation of the clause above**,
> because a store that cannot be read back proves nothing about at-most-once.

> **Normative — a failure at or after the commit boundary is reported as one that
> may have committed, and never as a certain failure.** Where the append has
> reached the point at which it may have landed — the commit or flush itself
> included — the provider raises
> **`ClassifiedToolError(effect_may_have_committed=True)`**, so the seam completes
> the step `INDETERMINATE` and ADR-0255 §6's authoritative record of the
> uncertainty is what stands. **A booking that may have happened is never recorded
> as certainly failed**: that is the one state from which a later plan re-books
> with the corpus's own machinery agreeing it may, and it is the failure §4 exists
> to keep reachable rather than to create by accident.

> **Normative — and nothing fallible runs after the commit.** The provider does no
> work between the commit and its return that can raise: the output is composed
> from values it already holds, and **an escaping exception after a committed
> append is a defect of the implementation and not a state this clause admits**.
> The two clauses are one rule — narrow the window, and classify honestly whatever
> is left in it.

> **Normative — the store is an ordinary store of this deployment and this
> decision invents no regime for it.** It sits **in the data directory**, so
> `ai-assistant-purge` (ADR-0126, ADR-0153) destroys it with every other store; it
> **validates a booking's arguments against the declaration's own
> `parameters_schema` before it writes, and persists only the fields that schema
> names**, so that nothing a caller supplied off-schema is ever stored; and the
> **lane owes it exactly what every store's lane owes, and nothing more**. **This
> decision fixes no schema, no format and no path**, and **no lane reads its
> silence on any of those as permission to omit them** — they are the lane's under
> the rules that already govern every store here.

> **Normative — the booking *record* is bounded, and ADR-0004 §6's retention limb
> is why.** It **carries a bound on how many records it retains**, beyond which the
> oldest are pruned, so the detail does not accumulate indefinitely. **This
> decision states the requirement and not a figure**, which is the lane's. That the
> limb reaches a store outside `memory/` is **ADR-0004's own reading of itself**:
> its ADR-0268 scope note says of the goal authorization store that *"§6's
> retention limb is reached by those rows before it is reached by the record"*, so
> §6's retention obligation is not confined to `memory/` and **this decision
> narrows it in no respect.**

> **Normative — the commit count is not pruned, and it is what carries the act's
> irreversibility past the record's retention.** Pruning the oldest booking
> records removes **detail about** bookings; it does not remove the fact that they
> happened, because the count stands. **No retention rule, no bound and no pruning
> decrements it.** This is the whole reason the state is two things: a provider
> whose only durable artifact were a prunable record would have an effect that
> retention undoes, which is `RECOVERABLE`, and §2 would be declaring something
> untrue as soon as the bound was crossed.

> **Normative — and it claims no exemption from ADR-0004 §6.** A **per-subject**
> view, export or deletion surface exists for **no** store in this tree —
> ADR-0101 §7 records that ADR-0004 §6's export right *"has none"* and defers both
> surfaces jointly, *"land together or neither lands"* — and this store is on
> exactly that footing, neither better nor worse. **The lane that gives that right
> a surface owes this store's rows in the same change**, as it owes every other
> store's; §8 books it.

> **Normative — and `IRREVERSIBLE` does not rest on any artifact being
> unpurgeable.** ADR-0016 §2's scale asks whether **the change the tool made can be
> undone**, and the answer here is that **no operation of this provider, and none
> in this system, undoes a booking**: the count only rises.

> **Normative — the non-recoverability rule is confined to the *wholesale*
> installation purge, and selective removal is expressly a different question.**
> **No lane reads `ai-assistant-purge` — which destroys the whole data directory —
> as making a tool `RECOVERABLE`**, and that is stated over every tool rather than
> over this one. **A rule that selectively removed or decremented this provider's
> commit count would undo its bookings, and the decision that lands one re-declares
> this tool's `reversibility` in the same change or preserves an irreversible
> effect beside it.** Pruning **booking records** is neither: §2 keeps the count out
> of the bound for exactly this reason, so the two rules are not in tension and no
> later decision has to choose between them. §8 books the selective-removal case.

**The reading is stated because a reviewer can reach the other one, and it is
worth the paragraph.** ADR-0016 §2's `RECOVERABLE` examples are *"a file in the
trash; a correction email"* — each a recovery **of the thing the tool affected**,
leaving the rest of the world standing. `ai-assistant-purge` is not that: it
destroys the **whole data directory** (ADR-0126, ADR-0153) — memory, the trail,
the plans, the connections and this store alike. **Counting it as a recovery would
make every tool in this system `RECOVERABLE`**, `send_email` included, since every
tool's record lives in that directory; and §2 names that collapse as the failure
the scale exists to avoid — *"The scale would then have one useful value, a policy
keyed on it could not tell booking a flight apart from adding a calendar entry,
and the user would be prompted identically for both."* **The reading here is the
one that keeps §2's scale doing what §2 says it is for**, and it narrows no clause
of ADR-0016: it says what *"undone"* has always meant there, over every tool.

> **Normative — `IRREVERSIBLE` then states what is true of this provider.**
> ADR-0016 §2 fixes `IRREVERSIBLE` as *"it cannot be taken back"* and
> `RECOVERABLE` as *"undoable, but not by this tool"*. **Neither this tool nor
> anything else in this system undoes a booking record**: §8 keeps cancellation,
> modification and refunds out of this decision entirely, and no other component is
> given a route to the store. A declaration reading `REVERSIBLE` would auto-grant
> against a policy threshold written for exactly this act, and ADR-0016 §2's
> *"`reversibility` alone is not sufficient to auto-grant"* is relied on here in
> both directions. **A later decision that gives this provider a cancellation
> re-declares `reversibility` in the same change.**

> **Normative — `risk_level` is not lowered because the provider is simulated.**
> `risk_level` is what a policy reads to decide whether the user is asked, and a
> declaration tuned to make a walkthrough quieter would demonstrate a confirmation
> path no real booking takes. `HIGH` is ADR-0016 §2's ordering read over an act
> that is irreversible and charges; `send_email` already declares `HIGH` for an act
> whose only consequence is a disclosure to a chosen recipient.

> **Normative — `Idempotency.NONE` is declared and no `KEYED` window is.**
> ADR-0016 §4 admits `KEYED` only on a real deduplication *guarantee* and this
> provider offers none. **`NONE` is also what makes the walkthrough worth
> running**: under ADR-0192 §1 a `side_effecting` non-`NATURAL` authorisation is
> **spendable**, so ADR-0259 §2's effect claim is the only thing standing between a
> replan and a second booking — the guarantee M33 exists to demonstrate, which a
> `KEYED` declaration would hide behind the provider's own dedupe.

> **Normative — `reads`, `writes` and `discloses` state only what this component
> touches, and each is fixed here rather than left to the lane.** Both
> declarations declare **`reads: (DataTier.SECRET, DataTier.OPERATIONAL)`** — the
> credential the bound connection names, which ADR-0148 §6's conditions 2 and 3
> make it read on every call, and the configured availability and prices (§5).
> Both declare **`discloses: ()`**, because nothing this provider is given leaves
> the device (§3). The **availability read** declares **`writes: ()`**; the
> **booking act** declares **`writes: (DataTier.PERSONAL,)`**, the record §2 below
> requires it to keep, which carries what the user asked for. **A lane that
> declares `reads: ()` or `writes: ()` on the booking has declared the silent
> no-reach claim ADR-0016 §1 makes these fields required to prevent**, and arm 4
> asserts all three over the registered definitions.

> **Normative — this section declares the *simulated* provider and constrains a
> real one's declaration in exactly one respect: no lane copies `discloses: ()`
> into a provider that discloses.** **Every other field of a real provider's
> declaration is its own ADR's**, decided against `ToolDefinition`'s existing
> semantics and against what that provider actually does. The stated cost of
> `discloses: ()` here is that the walkthrough exercises no disclosure gating; §8
> books it.

> **Normative — both `cost` values are `CostBasis.FREE`, and `cost` is never the
> charge.** Invoking either tool spends nothing: the provider is in-process,
> reaches no metered service and holds no account that could be billed, so `FREE`
> is the true claim and `UNKNOWN` would be a declaration that something might be
> spent when nothing can be. ADR-0271 §2 rules that *"No lane substitutes
> `ToolDefinition.cost`, `ToolInvocation.incurred_cost`, a quote, a ceiling or a
> zero"* for a charge, and **neither declaration's `cost` is derived from,
> defaulted from or kept in step with the configured prices** — the price the
> booking charges is a fact about the act, not about calling it.

> **Normative — a quote is prospective, and a charge that disagrees with it does
> not falsify it.** ADR-0267 §3's `amount` is *"the whole charge the act will
> make"* **as the provider states it at the read**; ADR-0271 §2 fixes the other
> half — *"A charge is **retrospective**"* — and §3 of that decision exists
> precisely for the case where the two differ, *"the quote was true when it was
> read and false when the charge was made"*. **So §5's disagreeing-charge
> configuration is not a provider whose `quoted_output` lies**; it is the case the
> corpus wrote a finding for, and **no lane reads either declaration as an
> obligation that the charge equal the quote.**

> **Normative — `risk_level` is `LOW` on the read and `HIGH` on the act, and the
> gap between them is the whole point of the field.** The read performs nothing,
> discloses nothing and spends nothing; the act is irreversible and charges. **A
> deployment that finds the read prompting, or the act not prompting, has a policy
> threshold to examine and not a declaration to edit.**

> **Normative — neither declaration carries a `bounded_arguments` member**, so no
> `BoundKind.MONEY` argument is declared and the owner's `max_price` route is not
> opened here (§8). **And nothing is declared for the effect key**: it is derived
> at `ToolCall.effect_key` and *"Derived rather than minted, supplied, configured
> or carried as a field"* is relied on rather than restated.

> **Normative — the booking act declares at least one `postcondition`**
> (`StepVerification`, ADR-0253 §4), over a key of its own output, **so that M33's
> verification half has a subject**. **This decision requires no more than one and
> requires no strength of it**: the owner ruled on #2255 that verification space
> exists but need not be strong, and a predicate over one step's own output is
> *"not the verification A10 lands"* — the two are not conflated here either.

### 3. Bound like every other integration, reaching no network, and establishing no contact

> **Normative.** Both declarations are **bound at the designated egress seam**
> (ADR-0154), against the registration's configured endpoint, and the callable
> performs **ADR-0148 §6's four pre-transmit conditions whole** before it answers:
> the bound reference is connectable; the transport endpoint the binding carries is
> the one it is configured to use; the connection reference names the connection
> record it consults and it reads under the slot that record names; and the account
> identity currently recorded for that reference equals the identity the binding
> carries. **A condition that does not hold refuses the call**, exactly as it would
> for a provider on the wire.

**Running the four conditions over a destination nothing is transmitted to is the
point, not a ceremony.** They are what a real booking provider's safety rests on,
and a walkthrough that skipped them would demonstrate a path the first real
provider does not take. What M33 needs to see is the binding refusing a
re-provisioned connection, and that refusal is reachable only because they run.

> **Normative — the transport is in-process, and that is enforced rather than
> asserted.** The provider **opens no socket, resolves no name and performs no
> HTTP exchange**; its module is added to the transport-confinement contract's
> enumerated `source_modules` in `pyproject.toml` **in the same change**, as
> ADR-0260 §12 requires of the reference forecaster, so that a later edit giving it
> a transport **fails `lint-imports`** rather than passing review. **No lane grants
> it a transport and no deployment configuration can give it one**; in particular it
> takes **no `OutboundTransport` parameter**, so the injection route by which the
> real and the fake transport both reach production code does not reach it at all.

> **Normative — it establishes no outbound contact and adds no
> `OutboundDestination` member.** ADR-0264 §3 already rules this, and it is applied
> rather than re-decided: *"A driven step establishes none, whatever its binding,
> its disposition or its addressed status … no component derives `REACHED`, and
> none adds an `OutboundDestination`, from an `EgressBinding`, from
> `Disposition.EXECUTED`, from `StepStatus.SUCCEEDED` or from any combination of
> them."* A booking is a driven step. **This decision adds no member to that
> vocabulary and no lane adds one on its authority.**

> **Normative — `FORECAST_PROVIDER` is not a precedent for adding one here, and
> the difference is stated so that a reader does not take the count for the
> rule.** ADR-0260 added a second member for a **read seam** the servicer performs
> and §2 of ADR-0264 folds from a recorded disposition; §3 is what governs a step
> the driver dispatches, and it says no. **The ground is ADR-0264 §3 and not the
> simulation**, so a real booking provider inherits the same answer and needs its
> own ADR to change it (ADR-0264 §5).

### 4. An uncertain booking is not reconciled, and this decision declares no lookup

> **Normative.** **No reconciliation lookup is declared on either definition** and
> none can be: ADR-0259 §3's reconcilable test is *not `side_effecting`* **and**
> *no `egress_binding`*, which a booking fails on both limbs, and that section rules
> that *"**no `ToolDefinition` field is added to say so**"*. **An `INDETERMINATE`
> booking step stays `INDETERMINATE`**, its status remaining *"the authoritative
> record of the uncertainty"* (ADR-0255 §6), and ADR-0259 §4's reconciliation pass
> passes over it exactly as the corpus already has it do. **No lane adds a
> reconciliation route, a status read, a second invocation seam or a
> `ToolDefinition` field on this decision's authority.**

> **Normative — and the provider is required to be able to *produce* that state.**
> It can be configured to answer a booking with an outcome the seam completes
> `INDETERMINATE`, so that ADR-0261's *report rather than withdraw* and ADR-0255
> §6's authoritative record are driven **against a production component** rather
> than asserted over a fake. **This is ADR-0260 §12's own rule applied here**: an
> arm over a production component cannot assert what no production component can
> produce.

**What the user is then told is not this decision's.** The route the owner ruled
for it — the assistant raises the situation on the next turn and asks permission,
and on a yes the check is an ordinary read step of the goal's next attempt — is
ADR-0259 §10's own entry, *"**Decided in direction by the owner** (#2255, comment
of 2026-09-13) **and still not decided here**"*, delayed until a consequential
integration exists. §8 carries it with what fires it.

### 5. Deterministic and scriptable, from configuration and from nothing else

> **Normative.** The provider's **availability, prices and charges are read from
> the deployment's configuration** and from no other source. It consults **no clock
> it was not given, no random source, no file it was not configured with and no
> network**, so one configuration answers identically on every run — which is what
> makes §10's arms and the M33 walkthrough **deterministic and offline in the
> ordinary gate**, ADR-0260 §13's standing requirement rather than a new one.

> **Normative — every configured amount and currency is validated when the
> configuration is read, in the domains the landed readers accept.** An amount is
> a value ADR-0267 §4's reading admits — a JSON **string** a `Decimal` accepts or a
> JSON **integer**, whose `Decimal` is **finite and not negative** — and a currency
> is a string of ADR-0267 §1's ISO-4217 shape. **A configuration carrying a JSON
> float, a JSON boolean, a negative amount, `"NaN"`, `"Infinity"` or a malformed
> currency is refused when it is read, and no provider is built from it.**
> Otherwise a deployment starts, every arm below passes on its own fixtures, and
> the walkthrough's quote or charge silently yields nothing — ADR-0267 §4's and
> ADR-0271 §2's readings each *"raise nothing"* by design, so a bad configuration
> has no other place to be caught.

> **Normative — the configuration must be able to express each of these without a
> code change:** an availability answer whose quoted price is **under** a stated
> bound; one **over** it; a request for a date the configuration makes
> **unavailable**; a booking whose **charge equals** the quote it was pinned to; a
> booking whose **charge disagrees** with it, in amount and, separately, in
> currency; and the `INDETERMINATE` outcome §4 requires. **A configuration shape
> that cannot express one of these is not an implementation of this clause.** This
> decision fixes **no field names, no file format and no `Settings` shape** —
> those are the implementing lane's, subject to §1's whole-or-absent rule — and
> fixes only what the shape must be able to say.

**The disagreeing charge is why this provider offers no hold and no conditional
execution** (§7). ADR-0271 §3's finding fires when the charge disagrees with the
pinned quote; a provider validating the quoted amount atomically with the act
would make that case unreachable and the finding undemonstrable.

### 6. Honesty: in every output, in what the user is shown, and not yet in the listing

> **Normative.** **Every *successful* output the simulated provider returns
> carries a field stating that no real reservation was made and no money moved** —
> an availability answer and a booking alike. It is carried by the record whether
> or not any surface renders it, so a trail, an export or an audit of a
> walkthrough is **self-describing** to a reader who was not present when the
> deployment was configured.

> **Normative — on a failure the provider itself classifies, the statement rides
> in that failure's own message.** `ToolResult` refuses a non-`SUCCEEDED` result
> carrying an `output` — *"a non-`SUCCEEDED` result carrying an output is a
> **partial** result an executor could record as a whole one, which is worse than
> an absent one"* — and a `FAILED` or `INDETERMINATE` step records a `failure` and
> no `output` (ADR-0039 §2). So a `ToolFailure` **this provider returns** carries
> the statement in its **`message`**, which is operator-facing Tier 2 text and
> admits it.

> **Normative — and the obligation reaches no outcome the seam synthesised.** A
> deadline the invocation seam completes, an escaping error the seam classifies,
> and every other failure value composed outside this provider carry **no
> provider-authored text and are not required to**: the provider did not write
> them, this decision changes no seam, and a clause obliging provider prose on a
> message the provider never composed would be an obligation nobody could meet.
> **This decision adds no field to `ToolResult`, `ToolFailure` or `StepExecution`
> and no lane adds one on its authority**; a structured failure carrier is its own
> contract ADR and §8 books it.

> **Normative — that field is not a mechanism.** **No policy, criterion,
> comparison, disposition, validator or `ToolDefinition` field is keyed on it, and
> no lane makes any behaviour conditional on it.** A component branching on it
> would be reading a provider's prose as a permission. It is a statement in a
> record and nothing more.

> **Normative — both declarations say it in their `description`, which is where
> the user meets it.** ADR-0016 §1 makes `description` the one free-text field with
> two audiences, *"the model, which is told what the tool does, and the user, who is
> shown what they are approving"*. **Each description states that the provider is
> simulated and that no real reservation is made, and neither describes the tool as
> booking anything without that word.** That reaches the user at the confirmation
> prompt — the one moment the approval design exists to serve — rather than on a
> page they may never open.

> **Normative — the connection listing is *not* where this is announced, and the
> reason is that it cannot be.** `ConnectedAccount` carries exactly four fields
> under `extra="forbid"`, and the renderer states the ground: *"A listing says
> which account and not which service … nothing in the tree says what an
> integration is yet, so there is nothing honest to put there (ADR-0151 §18)."*
> **This decision adds no field to `ConnectedAccount`, no annotation to the
> listing and no second call behind it**, and §8 books the change that would.

**The ground is the owner's standing ruling, read in its mirror** — *convenience
alone is insufficient justification for a user-facing restriction; genuine
constraints should be explained and evaluated*. A deployment with a genuine
constraint — nothing was really booked — **explains it**, rather than leaving the
user to infer it from a configuration file they cannot see. **It is not the
outbound statement** (§3): that one is about reaching outside this system, and
this provider does not.

### 7. Why building this is not the wiring ADR-0255 §13 forbids, and what still stands

> **Normative — §13's gate is lifted for nothing and narrowed in no respect.**
> **No consequential capability is wired into a production deployment until all
> seven conditions stand**: A8's, A9's and A10's guarantees implemented and
> demonstrated; the evidence-to-claim window closed (ADR-0255 §13, §1,
> [#2309](https://github.com/leonapivato/ai-assistant/issues/2309)); the durable
> recovery of a resolved confirmation whose claim was refused (ADR-0255 §3, §13);
> ADR-0265's containment for a wrongly minted intended action; and ADR-0267's hold
> or conditional execution for a capability authorised through a `MONEY` ceiling.
> **This decision discharges none of them, and no lane cites it toward any.**

> **Normative — the ground on which this provider may nevertheless be built and
> configured is §13's own second sentence, and not an exemption invented here.**
> That sentence reads: *"A milestone may demonstrate dependent execution against
> **controlled integrations** with no such capability wired; **wiring one is what
> this rule binds.**"* **This provider is such a controlled integration**: its act
> reaches no system outside the deployment, moves no money and confers no
> capability in the world, so the milestone that drives it wires no consequential
> capability and §13's first sentence is **not reached** rather than narrowed.
> **A provider that reached any system outside this deployment, or moved any
> money, is a consequential capability whatever it is named**, and §13's seven bind
> it entire.

> **Normative — ADR-0262 §3's consequence class is satisfied at rung 2, and that
> is required rather than avoided.** That section computes the strength a goal's
> verification owes from `ToolDefinition`'s declarations: **rung 2** is a step
> whose definition is `side_effecting` and whose `reversibility` is more severe
> than `REVERSIBLE`, or whose `discloses` is non-empty, or whose decision carries
> an `egress_binding`. §2's booking is `side_effecting` and `IRREVERSIBLE` and its
> decision carries a binding, **so it classifies at rung 2 and this decision
> requires that it does** — a reference provider classifying at rung 1 would
> demonstrate the wrong rung of the ladder M33 exists to exercise.

> **Normative — and ADR-0262 §3's class is not ADR-0255 §13's test, which is why
> the two answers differ without contradicting.** §3 asks *what did this attempt
> do, and how strongly must it be verified* — a question about **evidence inside
> this system**, answered from declarations, and it is answered here in the
> strictest direction. §13 asks *may this deployment be given a capability whose
> acts it cannot take back in the world* — a question about **consequence outside
> this system**, which §13's own second sentence answers for a controlled
> integration. **No lane reads ADR-0262 §3 as defining what §13 gates**, and
> **no lane reads this clause as licence to lower a rung**: the whole of what it
> says is that a rung-2 classification does not by itself make a component a wired
> consequential capability.

> **Normative — ADR-0255 §13's last clause is about that decision's own lanes and
> is untouched here.** *"**The lanes of this decision** wire no consequential
> capability, register no booking integration, and enable nothing in a production
> deployment."* This is not a lane of that decision, and its own lanes registered
> none. **That clause binds entire and this decision neither widens nor narrows
> it.**

> **Normative — and this decision creates no route by which this provider becomes
> a real one.** **The first real booking provider is its own ADR**, and it is not
> reached by editing this one's configuration, by re-pointing its endpoint, by
> granting it a transport (§3), or by registering a different implementation behind
> its declarations. **No lane re-uses this integration's module, factory,
> declarations, registration or configuration to reach a real provider**, and a
> deployment that wants one waits for that ADR.

**The forecast precedent is relied on rather than stretched.** ADR-0260 §12 built
a reference provider for a read and reasoned that an arm over a production
component cannot assert what no production component can produce. That reasoning
transfers whole; what does not transfer is the read's freedom from §13, and §7 is
this document paying for that difference explicitly rather than inheriting a
clearance it was never granted.

### 8. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane
> cites it toward any of them.

- **A real booking provider, and every field of its declaration.** **Its own
  ADR**, which owes ADR-0255 §13's seven conditions and ADR-0267's
  hold-or-conditional-execution in particular. §2 constrains it in exactly one
  respect — it does not copy `discloses: ()` — and settles nothing else about what
  it declares. **Fired by** a decision that takes it.
- **A price ceiling supplied as an argument** — the owner's `max_price` route, and
  the `BoundKind.MONEY` `bounded_arguments` member §2 declines. **Not decided.**
  **Fired by** the decision that takes that route.
- **Refunds, cancellation and modification of a booking.** **Not decided.**
  ADR-0261 stands entire — an effect already dispatched is **reported rather than
  withdrawn** — and this provider offers no act that withdraws one, which is what
  §2's `IRREVERSIBLE` states. **Fired by** A8's second ADR (modify-before-replace)
  or a decision that takes refunds.
- **A declared reconciliation lookup on `ToolDefinition`.** **Not decided** (§4).
  ADR-0259 §10's *third reconciliation route* entry governs and is left standing.
  **Fired by** the decision that takes it.
- **What the user is told about an uncertain booking.** **Not decided** (§4), and
  ADR-0259 §10 books it — decided in direction by the owner, delayed until a
  consequential integration exists. **Fired by** that decision.
- **Annotating a connection listing with what an integration *is*.** **Not
  decided** (§6), and the honest statement is that this is a standing gap rather
  than a fresh deferral. ADR-0151 §18 scopes out *"What an integration **is**: an
  endpoint, a service identity, a scope list, an account chooser"* and fires that
  entry *"with the first integration"* — a condition the web search, email and
  forecast integrations have already met, with no lane having taken it. **This
  decision does not take it either**, because it is a `ConnectedAccount` change
  under `extra="forbid"` and therefore its own contract ADR, and because §6's
  announcement does not depend on it. **The gap is filed rather than re-deferred
  here.**
- **Whether configuring this provider fires ADR-0259 §10's two
  first-consequential-capability entries** — the effect identity that survives a
  tool's redefinition, and the evidence-to-claim window. **Not decided**, and
  stated so that a reader does not assume either way. This provider is **not** a
  consequential capability (§7), so on this decision's reading neither is fired;
  **a lane that concludes otherwise raises it rather than acting on it.**
- **Disclosure gating over a booking's arguments.** **Not decided**, and it is the
  stated cost of §2's empty `discloses`. **Fired by** the real provider's ADR.
- **A per-subject view, export or deletion surface over the booking store.**
  **Not decided**, and not deferred afresh: ADR-0101 §7 defers that surface for
  **every** store — ADR-0004 §6's export right *"has none"*, and the two surfaces
  *"land together or neither lands"* — and §2 puts this store on exactly that
  footing rather than claiming an exemption from it. **Fired by** ADR-0101 §7's
  own two conditions, and the lane that satisfies either owes this store's rows in
  the same change.
- **Selective removal of this provider's commit count, and the retention figure
  itself.** **Not decided** (§2). The bound's number is the lane's; what is
  reserved here is a decision that would **decrement or selectively erase the
  count**, because that would undo bookings and therefore change what §2 declares.
  **Such a decision re-declares this tool's `reversibility` in the same change, or
  preserves an irreversible effect beside the count.** **Fired by** a decision that
  takes selective erasure — a per-subject deletion surface being the likeliest, and
  the entry above being where it is already booked.
- **A structured carrier for metadata on an unsuccessful outcome.** **Not
  decided** (§6). `ToolResult` refuses an `output` on a non-`SUCCEEDED` result and
  `ToolFailure` carries `kind` and `message` alone; adding one is a `core/types.py`
  change and its own contract ADR. **Fired by** a decision that takes it.

### 9. Scope, marking, and this ADR classified

> **Normative.** This decision is a **stacked addition** under ADR-0082 §1: it adds
> obligations and **amends no named clause of any earlier ADR**, so under that
> section's rule it *"is recorded in the ADR that makes it, and nowhere else"* and
> **no record is owed on any earlier document** — not on a `Status` line, not as a
> dated note.

**The working, against ADR-0070 §1's test applied to each earlier ADR's text** —
*would a reader holding only that ADR now act differently, or read one of its
clauses more widely than it now holds?*

- **ADR-0255 §13** — no. Its rule binds verbatim; §7 restates it at the count
  ADR-0265 and ADR-0267 already recorded on that document, adds none and lifts
  none.
- **ADR-0260 §1 and §12** — no. §1's registry exclusion is about the forecast read
  and stays exactly true of it; §1's own stated reason — the planner naming a
  capability nobody asked for — does not reach a capability the user asks for, and
  §1(2) above says so in its own text rather than reading §1 down.
- **ADR-0264 §3 and §5** — no. §3 is cited and applied; §5's vocabulary is not
  added to.
- **ADR-0259 §3 and §10** — no. §3's conjunction is applied as written; §10's entry
  is pointed at and left standing.
- **ADR-0262 §3** — no. Its ladder is applied and §7 requires the booking to
  classify at its **rung 2**; no rung, limb or comparison is changed, and the
  clause distinguishing its question from ADR-0255 §13's states what each already
  asks rather than narrowing either.
- **ADR-0014 §3, ADR-0029 §3, ADR-0039 §2** — no. §6's statement rides in the
  carriers those decisions already provide and adds no field to `ToolResult`,
  `ToolFailure` or `StepExecution`.
- **ADR-0032 §1** — no. §2's commit-boundary clause uses `ClassifiedToolError`
  for what that decision already mints it for — a tool classifying its own
  failure — and adds no field, no branch and no seam behaviour.
- **ADR-0004 §6, ADR-0101 §7, ADR-0126, ADR-0153** — no. §2 adds a store on the
  same footing as every other, purged by the same act, and owed to the same
  deferred surface; it claims no exemption, so no sentence of any of them becomes
  false or over-wide. **A reader holding only ADR-0004 §6 is not misled**, because
  §2 says in terms that it claims no exemption, bounds the record under §6's
  retention limb, and books the deferred surface in §8. **That limb is read as
  ADR-0004 itself reads it** — its ADR-0268 scope note applies it to the goal
  authorization store's rows, a store outside `memory/` — so this decision widens
  and narrows nothing about its reach.
- **ADR-0016, ADR-0148 §6, ADR-0149 §4, ADR-0151 §18, ADR-0267 §3, ADR-0271 §2** —
  no. Each is a declaration, a condition or an open question this decision
  **satisfies** or **leaves open**; a new integration that declares honestly is
  their ordinary use.

> **Normative.** This ADR is **marked** under ADR-0089 §2: its marked clauses are
> the whole of what it obligates, and its unmarked prose is read to determine what
> a marked clause means and supplies no obligation (§3).

> **Normative.** **It is drafted, reviewed and revised as `Proposed`, and its
> status is flipped only once both required reviews — adversarial and
> architecture — return clean on one tree**, the flip made by `just adr-ratify`
> and, being ADR-0165 §2's one exempt shape, re-running nothing.
> `CONTRIBUTING.md` → "Finishing an ADR PR" is the sequence, pointed at rather
> than restated. **Nothing implements against this decision until it has merged**
> (ADR-0015 §5, golden rule 5).

### 10. The lane cut, and the arms it owes

> **Normative.** **One lane, one PR**: the integration module, its two
> declarations, its configuration and its registration — `tools/` plus
> `app/composition.py`, which is ADR-0260 §12's L1 shape and the composition
> root's own job — together with the transport-confinement entry (§3) and the
> `Settings` fields and validator (§1, §5) in the same change. **The M33
> walkthrough is not that lane** and it follows.

> **Normative.** The lane owes these arms, each **deterministic, offline and in the
> ordinary gate**, each with **the production component as its subject** and not a
> literal restated in the test:
>
> 1. **Absent by default** — a default `Settings` builds no provider and registers
>    neither declaration, in the registry or at the seam.
> 2. **Half-configured is refused** — `Settings` refuses a partial configuration,
>    one arm naming the refusal.
> 3. **Enabled with no provisioned connection** — registers nothing and fabricates
>    nothing.
> 4. **Each declaration's shape** — `side_effecting`, `idempotency`,
>    `reversibility`, `risk_level`, **`reads`**, **`writes`**, `discloses`, `cost`,
>    `quoted_output`, `charged_output`, `bounded_arguments` and the booking's
>    postcondition, **every one of them named**, exactly as §2 states, asserted
>    over the registered definition.
> 5. **The quote is read, under and over a bound** — ADR-0267 §4's mint yields an
>    `ActionQuote` from the availability step's `output` under the registered
>    `quoted_output`, **once from a configuration whose price is under a stated
>    bound and once from one whose price is over it**, the two differing in
>    configuration alone.
> 6. **An unavailable date, read *and* booked** — a configuration under which the
>    requested date is unavailable: the availability read answers as such, **and a
>    booking attempted for that same date is refused by the provider and appends
>    no record**. The second half is what stops a provider that answers
>    *unavailable* and books anyway.
> 7. **The charge is readable, agreeing and disagreeing** — ADR-0271 §2's reading
>    yields the charge from the booking step's `output` under the registered
>    `charged_output`, over **three** configurations: one whose charge equals the
>    pinned quote, one whose **amount** disagrees, and one whose **currency**
>    disagrees, the last two independently configurable.
> 8. **The effect key** — two dispatches of one intended action under one goal
>    carry one derived `EffectKey`, and the second is not dispatched (ADR-0259 §2).
> 9. **The durable state, both halves** — a booking appends a record **and**
>     advances the commit count; both are readable **after a restart**; the
>     provider exposes no operation that removes, amends or decrements either; the
>     store leaves **no artifact outside the configured data directory**; and after
>     `ai-assistant-purge` over that directory a reopened store holds **no booking
>     record and no count** (§2).
> 10. **The bound, and what survives it** — bookings past the configured bound
>     prune the oldest **records**, the store stays readable and within its bound
>     after a restart, and **the commit count still reports every booking made**
>     (§2). This is the arm that shows retention removing detail and not the act.
> 11. **Off-schema arguments** — a booking request carrying a field the
>     declaration's `parameters_schema` does not name is refused, and **no record
>     is appended** (§2).
> 12. **A refused configuration** — a configured amount or currency outside the
>     readers' accepted domains is refused when the configuration is read, one arm
>     per refused shape (§5).
> 13. **The provider deduplicates nothing, which is what `Idempotency.NONE`
>     declares** — **two separately authorised intended actions carrying identical
>     booking arguments append two records**. Arm 8 shows the system's effect claim
>     stopping a repeat; this arm shows that **nothing but that claim would have**,
>     which is the ground §2 states for `NONE` and would otherwise go
>     unestablished.
> 14. **Two concurrent bookings** — two calls entering the provider at once leave
>     **two whole records** and a store readable afterwards, which is §2's
>     serialised, failure-atomic append with a subject.
> 15. **The commit boundary, both sides** — a fault injected **before** the commit
>     leaves **no** record and is reported as a certain failure; a fault injected
>     **at or after** it raises
>     `ClassifiedToolError(effect_may_have_committed=True)` and the step completes
>     **`INDETERMINATE`**; and after an interruption at the commit boundary the
>     store **reads back whole**, carrying every record that preceded it (§2).
> 16. **The four conditions** — a binding whose connectability, endpoint,
>     connection reference or recorded identity does not match refuses the call,
>     **one arm per condition** (ADR-0148 §6).
> 17. **No network** — the transport-confinement contract covers the new module and
>     fails if the entry is removed.
> 18. **The uncertain booking, told truthfully** — the `INDETERMINATE` step §4
>     requires is produced by a configuration that fails **at the commit boundary**,
>     and the arm asserts the store afterwards: the flag the provider reported was
>     **true of what it did**. A configuration that fails **before** any commit is
>     a separate arm reporting `effect_may_have_committed=False`, leaving **no
>     record and no count advance**, and completing `FAILED` rather than
>     `INDETERMINATE`. **An arm reaching `INDETERMINATE` through a provider that
>     could not have committed demonstrates a pessimistic misreport rather than an
>     uncertain effect**, and is not an implementation of this arm.
> 19. **The honesty statement** — the field on every successful output, and the
>     statement in the `message` of a `ToolFailure` **this provider returns** (§6).

> **Normative — arm 7 asserts the *reading* and not ADR-0271 §3's finding, because
> that comparison has not landed in `src/`.** An arm demanding a demonstration a
> lane cannot make is a demonstration nobody gives — ADR-0255 §15's own reason for
> keeping such an arm out. **Where the comparison has landed by the time this lane
> runs, the lane extends arm 7 to assert the finding**; **where it has not, the
> finding's arm is owed by the lane that lands the comparison**, and this
> decision's §5 configuration requirement is what makes it available to that lane.

> **Normative.** **No lane files or defers anything this decision has not named**,
> and **no lane of this decision configures the provider in any deployment** —
> that is the operator act §1 reserves.

## Consequences

**What becomes easier.** M33's booking half gets a subject. Every money-path
mechanism that has landed — the quote and its mint, the pin, the effect claim, the
four egress conditions, the charge's reading — becomes assertable against a
**production component** rather than a fake, which is the difference between a
mechanism that is tested and one that is only specified. The walkthrough drives an
over-bound quote, a disagreeing charge and an uncertain booking without a code
change, and a later real provider has a worked example of what a booking
declaration looks like, with §2's clause naming the three fields it must not copy.

**What becomes harder.** There is now a component in the tree that acts, charges,
keeps durable state it never undoes and is declared `IRREVERSIBLE`, whose only
protections against becoming a real one are §7's prohibition, the
transport-confinement contract and its taking no transport parameter. That is a deliberate trade: the alternative — a fake in
`ai_assistant.testing` — cannot be registered, cannot be bound, and never reaches
ADR-0148 §6's conditions.

**What would trigger revisiting this.** A real booking provider's ADR, which
supersedes §7's ground for its own capability and must satisfy ADR-0255 §13's
seven. A decision taking ADR-0259 §10's third reconciliation route, which would
give §4 a lookup to declare. A decision adding an integration fact to
`ConnectedAccount`, which would move §6's announcement into the listing. A decision
adding a structured carrier for metadata on an unsuccessful outcome, which would
move §6's failure statement out of `ToolFailure.message`. A measured case in which
§2's declarations turn out to be the wrong ones for a real provider to start
from.

## Alternatives considered

**A fake in `ai_assistant.testing` instead of an integration in `tools/`.**
Rejected: a canonical fake is registered in nothing, bound to nothing, and never
reaches ADR-0148 §6's conditions, so every arm over it asserts the walkthrough's
machinery against a stand-in for the thing under test. ADR-0260 §12 rejected the
same alternative for the forecaster in the same words.

**Declaring the booking `REVERSIBLE` because nothing real was booked.** Rejected,
and it is the most tempting error available here. `reversibility` is about the
effect on the system acted upon, and this provider offers no undo for its own
state either; a `REVERSIBLE` booking would auto-grant against a policy threshold
written for exactly this act, and every arm over the confirmation path would then
demonstrate a path a real provider never takes.

**Declaring `Idempotency.KEYED` so a repeat is harmless.** Rejected: the provider
offers no deduplication guarantee, ADR-0016 §4 admits `KEYED` only on one, and a
`KEYED` declaration would make the authorisation non-spendable and hide ADR-0259
§2's effect claim — the guarantee M33 exists to demonstrate — behind the
provider's own behaviour.

**Giving the provider a hold or a conditional execution, so that it satisfies
ADR-0267's seventh condition.** Rejected: it would make the disagreeing charge
unreachable, and with it ADR-0271 §3's finding. A reference provider that cannot
produce the failure the corpus wrote a finding for is not a reference provider.

**Keeping it out of the `ToolRegistry`, as ADR-0260 §1 keeps the forecast read.**
Rejected: that clause's own ground is that the planner naming the capability is
the outcome to make unreachable, and here the planner naming it is the
walkthrough. A booking no planner can propose has no confirmation, no dispatch and
no effect claim to demonstrate.

**Adding an `OutboundDestination` member for it.** Rejected: ADR-0264 §3 already
rules that a driven egress step adds none, §5 closes the vocabulary against
anything identifying a particular destination, and the member would be a
`core/types.py` change this decision has no ground to make (golden rule 5).

**Announcing the simulation in the connection listing.** Rejected as
unimplementable without a contract change: `ConnectedAccount` is four fields under
`extra="forbid"` and ADR-0151 §18 owns the question. §6 puts the announcement in
the `description` the user is shown at approval, which is nearer the moment that
matters and needs nothing added.
