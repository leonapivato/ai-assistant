# 194. A ceiling on what the world may cost is decided before the act, and an unknown price is never zero

- Status: Proposed
- Date: 2026-08-25
- **Decides `core` contract surface and implements none of it (golden rule 5).**
  It adds a Protocol, two `core/types.py` models and one `core/errors.py` class,
  and it lands none of them: the triad and its primary implementation are a
  separate lane, sequenced behind ADR-0192's (§11). **Because this ADR decides a
  contract surface, its required review set is adversarial *and* architecture**,
  even though the PR carrying it is prose only — `CONTRIBUTING.md` → "Stop when
  the required reviews are green" and ADR-0015 §1.
- Amends: ADR-0021 §6's **Spend accumulation** deferral and ADR-0029 §7's
  spend-accumulation half; §10 applies ADR-0070 §1 and ADR-0082 §1 to each.

## Context

Milestone 25 (#1427) asks for "a budget ceiling on what the world may cost". The
tree has the vocabulary for one and none of the mechanism.

**What exists.** `ToolDefinition.cost` is a `ToolCost` — a `CostBasis` of `FREE`,
`PER_CALL` or `UNKNOWN`, with a `Decimal` amount and an ISO-4217 currency
required exactly on `PER_CALL` (ADR-0016 §4). It was written for this: `Decimal`
"never a float, because this feeds spend limits", and `UNKNOWN` exists so that a
policy can tell "free" from "nobody knows" and "fail closed" on the second. Its
one consumer is `ai_assistant.permissions.policy`, whose `_UNKNOWN_COST_FLOOR`
sends an `UNKNOWN`-cost tool to `CONFIRM` — ADR-0021 §5's clause acquiring an
enforcer. Nothing anywhere adds two costs together.

**What was deferred, and why.** ADR-0021 §6 defers spend accumulation in one
sentence: "a running total against a budget needs invocation to report what was
actually spent, and ADR-0016 §4 already records that `cost` is an estimate
nothing reconciles". ADR-0029 §7 repeats the block from the invocation side —
spend accumulation "additionally needs a cost report invocation cannot honestly
produce" — and ADR-0029 §3 states the omission it rests on: "`ToolResult` carries
no cost and no disclosure report", because "billing is asynchronous, so a `spent`
field would hold a number the tool made up".

**What removes the block.** ADR-0192 lands the invocation record: a claim
appended atomically at the invocation seam immediately before the callable is
entered, a completion carrying what the call reported it cost, and the rule that
an accumulator sums the reported figures over completion rows and never copies a
declaration onto a row. Its §5 is titled for this document and hands it four
questions by name — no ceiling, no budget period, no currency reconciliation and
no refusal outcome — and one accounting corner already ruled: the call that
crosses a ceiling is still spent, so no lane treats it as free.

**Every other "budget" in this tree is internal pacing and none of it is this
one.** `gateway_notification_budget`, the hub's `ConnectionBudget` and its
`shutdown_drain_seconds` drain budget, a conversation turn budget, a
consolidation run budget and an interruption budget all bound *work this process
does to itself* — connections, seconds, turns. None of them is denominated in
money and none of them describes the world. This ADR touches none of them, adds
no ceiling over any of them, and no lane reads it as doing either.

**What the surveyed field does.** #1548 surveys five agent runtimes for a spend
ceiling and finds exactly one: Claude Code's `max_budget_usd`, which is over
model tokens, is a client-side estimate its own documentation says not to bill
from, counts a tool execution as zero, and lets the crossing response complete
and be counted. LangChain's `ToolCallLimitMiddleware` under
`exit_behavior="continue"` delivers its limit to the model as a tool message
asking it not to call again — "a ceiling that informs the model is not a
ceiling". The survey's conclusion for this lane is three sentences: accumulate
reconciled per-call `ToolCost` rather than tokens; refuse *before* execution; and
keep `UNKNOWN` failing closed rather than counting it as zero.

**The one fact about this tree that shapes the answer more than any other.** The
only world-reaching tool that exists declares `cost=ToolCost(basis=CostBasis.UNKNOWN)`
(`ai_assistant.tools.send_email`), and its own text says why: "Which provider a
connected account sends through is undecided (ADR-0125 §12), and some charge per
message, so `FREE` would be a claim about a provisioning surface nobody has
designed." So the naive fail-closed rule — refuse every unknown-priced call while
a ceiling stands — switches off the entire world the moment a user configures a
ceiling, and does it for the one tool whose author was being honest. The tool
cannot know its price. The user who connected the account can. §2 is built on
that asymmetry.

**What this ADR is not allowed to settle.** It decides nothing about who may
receive bytes (ADR-0148 §3's second route, #68), nothing about how the world is
reached (#85), and nothing about ADR-0192's record beyond citing it. It does not
reopen ADR-0016 §7's *transacted cost* deferral — money a tool moves is still not
modelled anywhere — and it lands no reconciliation of a reported figure against a
provider's bill, which is ADR-0014 §7's deferral and stays there.

## Decision

### 1. One ceiling, in one currency, over calendar periods, and unset means unbounded

> **Normative.** `core.config.Settings` gains exactly five fields and no others:
> `world_spend_currency: str | None`, `world_spend_month_ceiling: Decimal | None`,
> `world_spend_day_ceiling: Decimal | None`,
> `world_spend_unknown_allowance: Decimal | None`, each defaulting to `None`, and
> nothing else. They are the whole of this mechanism's configuration and no other
> setting conditions it.

> **Normative.** `world_spend_currency` is validated on **shape only** — exactly
> three uppercase ASCII letters, ISO-4217's alphabetic form, neither normalised
> nor checked against the live register. This is `ToolCost.currency`'s rule
> (ADR-0016 §4) and not a second one.

> **Normative.** Each of the three amounts, where set, is a `Decimal` that is
> **finite and greater than or equal to zero**. A non-finite value is refused at
> load, as `ToolCost.amount` refuses one, and for the same reason: `Decimal`
> admits `Infinity` and `NaN`, neither survives arithmetic in a running total,
> and `NaN` makes every comparison false rather than answering.

> **Normative.** `world_spend_currency` is set if and only if at least one of
> `world_spend_month_ceiling` and `world_spend_day_ceiling` is set;
> `world_spend_unknown_allowance` may be set only where at least one ceiling is.
> A configuration failing either biconditional raises `ConfigurationError` at
> load, as every other malformed setting does.

> **Normative.** A ceiling bounds **the sum over tool invocations**, across every
> registered tool, and is scoped to the world as a whole. No per-tool, per-capability
> or per-protocol ceiling is decided here, and no lane adds one without its own
> ratified decision (§8).

> **Normative.** The two periods are **calendar periods in the user's configured
> time zone** (`Settings.timezone`): `CALENDAR_DAY` is midnight to midnight, and
> `CALENDAR_MONTH` is the first instant of the month to the first instant of the
> next. Each is half-open — a row belongs to the period containing its recorded
> instant, and the period's end instant belongs to the next period.

> **Normative.** Both ceilings bind independently and simultaneously where both
> are set. A call is refused where it would cross **either**. A
> `world_spend_day_ceiling` above the month ceiling is accepted and is simply
> never the binding one; nothing refuses a configuration on that ground.

> **Normative.** **No ceiling configured means no ceiling.** Where both ceilings
> are unset, this mechanism refuses nothing, admits every call, and the running
> total is still computed and still readable (§6). No default amount is minted,
> here or by an implementation.

**Calendar rather than rolling, and the day ceiling is what pays for it.** A
rolling window is the more precise instrument and the wrong one for this
quantity. What a user has in mind when they cap spend is a bill, and bills arrive
on calendar boundaries; a window that resets continuously has no moment a user
can point at and no answer to "when can I do this again" other than an
arithmetic one. A calendar boundary is also a comparison against a fixed instant
rather than a continuous re-decision over a moving set of rows. The cost of the
calendar is real and is exactly one thing: a month ceiling admits a spike on the
last day of a month and the same spike on the first day of the next, so twice the
ceiling can leave in forty-eight hours. That is what the optional day ceiling is
for, and it is why the day ceiling is offered here rather than deferred — it is
the rate limit the rolling window would have supplied, in a form a user can
state.

**Why a per-tool ceiling is not offered, given that it was the obvious second
knob.** A per-tool ceiling is keyed configuration — a mapping from tool id to
amount — and keyed per-user configuration over tools is precisely what ADR-0016
§7 defers as "policy state, not a property of the tool", needing a store rather
than a setting. It also buys no bound the world ceiling does not already give: it
partitions one budget rather than lowering it, so it constrains *composition*,
not *exposure*. The property people actually want from a per-tool cap — "this
thing must not run away" — is a rate limit, and the day ceiling supplies it
without a keyed store. §8 names the trigger.

**Unset means unbounded, and the ground it rests on is a per-call user act rather
than optimism.** Today nothing reaches the world without the user answering about
that specific call: ADR-0021 §5's disclosure floor forbids auto-granting any tool
with a non-empty `discloses`, ADR-0148 §3 leaves route (a) — "a decision of the
user recorded in the `AuditTrail` as the resolution of a `CONFIRM` about *this*
request" — as the only available route, and ADR-0148 §8 makes that universal at
the egress seam. An unconfigured ceiling therefore does not open a door; it
declines to add a second lock to a door that is already answered one call at a
time. A defaulted number would be worse than nothing in both directions: too low
and it refuses work the user authorised, in a currency `core` chose for a user it
does not know; too high and it is decoration. **What would change this is a
standing grant** — an authorisation that lets a call execute with no per-call
user act (ADR-0021 §6, #68, and the ADR ADR-0148 §3's third clause reserves it
to). When such an authorisation can cover an egress call, the ground under this
clause is gone and the default is reopened by that fact; §8 records it as the
trigger rather than pre-deciding it here.

### 2. What is counted: a declared estimate before, a reported figure after, and an unknown price that is never zero

> **Normative.** The **accounted total** of a period is the sum of the reported
> per-invocation costs carried by ADR-0192's **completion** rows whose recorded
> instant falls in that period. Nothing else contributes to it: not a
> `ToolDefinition.cost`, not an open claim, not a `PermissionDecision`, not a
> model call.

> **Normative.** The **projected total** for a call under admission is the
> accounted total of the period plus that call's **declared** cost — the
> `ToolCost` on the `ToolDefinition` the call's recorded decision pins. The
> declared amount is used **only** for the admission arithmetic in §3; it is never
> added to the accounted total and never written to any row.

> **Normative.** A `FREE` basis contributes zero, in both totals. A `PER_CALL`
> basis in the ceiling's currency contributes its `amount`.

> **Normative.** A cost whose basis is `UNKNOWN` contributes
> `world_spend_unknown_allowance` where that setting is set, and where it is not,
> it contributes **more than any ceiling**: in the projected total the call is
> refused, and in the accounted total the period's total becomes **indeterminate**
> and no further call in that period is admitted. An `UNKNOWN` cost is never
> treated as zero and never omitted from a total.

> **Normative.** A cost denominated in a currency other than `world_spend_currency`
> is **never converted**. It is treated exactly as an `UNKNOWN` basis is by the
> clause above. No implementation reads an exchange rate, and no lane adds one
> without its own ratified decision (§8).

> **Normative.** An indeterminate accounted total is a state of one period and
> ends when that period does. It is not carried into the next period, and no
> implementation persists it as a flag: it is recomputed from the rows each time
> the total is computed.

> **Normative.** Every completion row in the period is counted, including the one
> whose reported cost carried the total past a ceiling and including one whose
> outcome is `INDETERMINATE`. No row is excluded from the total because a refusal
> followed it, because the act may not have happened, or because the figure is
> inconvenient. This is ADR-0192's rule and not a new one.

> **Normative.** Model-provider spend is **out of scope**. No model call, token
> count or provider charge enters either total, and no lane folds a model ledger
> into this one (§8 names the trigger).

**The allowance is the user supplying the fact the tool's author could not, and
that is why it is not an escape hatch.** `UNKNOWN` means "the author does not
know" (ADR-0016 §4), and `send_email`'s own text shows the shape of that
ignorance exactly: the author does not know which provider a connected account
sends through, and some charge per message. The user who connected the account
does know, and they know it once, for all sends, in advance. So the allowance is
not a licence to ignore an unknown price; it is the only party who *can* price
the call stating a per-call worst case, on the record, in configuration, outside
any turn. The arithmetic stays a real bound: every unknown-priced call is
accounted at the number the user chose, so the ceiling holds against the user's
own stated worst case rather than against zero. And the direction of the default
is the safe one — unset, an unknown price is refused, and the mechanism is
useless with `send_email` until the user says what a send may cost. That is the
correct discomfort: it converts "nobody knows" into a question the one informed
party answers, instead of into a silent zero.

**It is also not the escape hatch #1548 tells this lane to avoid, and the
difference is who holds it.** The survey's avoid-list entry is Claude Code's
`dangerouslyDisableSandbox` retry, whose defining property is that the **model**
may reach for it mid-turn to obtain a capability it was not handed. The allowance
is unreachable from a turn: it is a configuration value, it is read and never
written by anything in the pipeline, and setting it *tightens* the arithmetic
against the alternative of refusing outright only in the sense that it lets work
proceed — it widens nothing the user has not already authorised per call under
ADR-0021 §5 and ADR-0148 §3. A model cannot set it, a tool cannot raise it, and
no code path defaults it.

**Why the declared amount is admissible for the projection and inadmissible for
the total.** ADR-0192 §5 forbids copying a declaration onto a row labelled
incurred, because that "would discharge the deferral in appearance and reproduce
the estimate underneath". This clause obeys that in the place it bites: the
accounted total is made of reported figures only, and the declaration touches no
row and no stored value. But the admission decision is taken *before* the act,
and before the act the reported figure does not exist — the only price available
is the declared one. Refusing to use it would leave the admission with nothing to
project and would make the ceiling enforceable only in arrears, which is
LangChain's ceiling with a delay. The two numbers stay separable because they are
used in different sentences and only one of them is ever stored.

**What this ceiling can and cannot promise, stated rather than implied.** It
promises that **no invocation begins** while the projected total exceeds a
ceiling. It does not promise that the accounted total never exceeds one: a
declared estimate can understate what a call turns out to have cost, and
ADR-0016's own Consequences say "a wrong number will mislead a spend policy, and
no mechanism detects the drift". So the guaranteed bound is the ceiling plus the
last admitted call's overrun of its own declaration, and the overrun is
**recorded** — it lands in the accounted total, refuses the next call, and is
readable (§6). This is the survey's accounting corner taken in the honest
direction: the crossing call is counted, not excused, and this ADR says which of
the two properties it has rather than letting a reader assume the stronger one.

### 3. The admission is decided at the invocation seam, and the policy is left a pure function

> **Normative.** The admission is evaluated inside `ToolInvoker.invoke`,
> **before** ADR-0192's claim is appended and therefore before the callable is
> entered. A refused call reaches no callable, appends no claim, and appends no
> completion.

> **Normative.** The admission compares the projected total (§2) against each
> configured ceiling for the period that contains the invoker's current instant,
> and refuses where the projected total is **strictly greater** than a ceiling.
> A projected total exactly equal to a ceiling is admitted.

> **Normative.** The instant that fixes the period is read from an injected
> `Clock` wrapped by `checked_clock` (ADR-0026), and no caller supplies it. A
> clock that raises refuses the call, as ADR-0029 §5's fail-closed reading of the
> same measurement requires.

> **Normative.** `ActionPolicy` is **unchanged**. It gains no ceiling input, no
> store handle, no clock and no member; `ActionPolicy.decide` stays a function of
> its argument; and ADR-0021 §5's floors, including the `UNKNOWN`-cost floor that
> sends such a tool to `CONFIRM`, are neither relaxed, satisfied nor duplicated by
> anything here.

> **Normative.** No implementation makes the admission conditional on the calling
> subsystem, the tool's identity, a setting other than §1's five, or a value
> carried in the request. There is no parameter, argument or configuration by
> which a caller obtains an invocation the ceiling would refuse.

**The policy was the obvious home and it is the one place this cannot go.** It
already reads `ToolCost` and already produces the `PermissionRuling`, so
`ActionPolicy.decide` looks like where a cost rule belongs. Two things forbid it,
and the second is fatal on its own.

The first is what `decide` is. `ActionPolicy`'s contract says it "supplies neither
an `id` nor a clock, which leaves `decide` a genuine function of its argument —
and that is what makes the obligations below checkable at all", and ADR-0021 §5
builds monotonicity and the two floors on exactly that property; ADR-0097 §7 goes
further and forbids an `ActionPolicy` from consulting a grant seam at all. A
ceiling check needs a running total, which is a store read, and a period, which is
a clock read. Putting either behind `decide` would make the conformance suite's
monotonicity obligation untestable — the same request would rule differently at
two instants — and would hand `permissions` a store handle the corpus has twice
refused it.

The second is that a ruling cannot bind a total that moves after it. A `CONFIRM`
is answered by a human, at human speed; between the ruling and the act, other
calls complete, the accounted total rises, and a calendar period can roll over. A
ceiling evaluated at ruling time is therefore a statement about a total that no
longer holds when the call runs — which is precisely the failure the survey names
in LangChain's `exit_behavior="continue"`, arrived at by a different route. The
only instant at which the answer is true is the instant before the act, and
ADR-0192 has already established what happens there: an atomic claim, immediately
before the callable, at the one seam every invocation passes.

**Two other placements, and why neither.** The **egress binder**
(`ai_assistant.tools.egress_binder`) sees every egress call and only egress calls,
so a ceiling there would be silent about every other priced tool — and `ToolCost`
is declared by every `ToolDefinition`, not only by disclosing ones. A ceiling on
"what the world may cost" that a paid non-egress integration walks past is not the
bound its name claims. The **executor** in `orchestration` is a caller, and a
check in a caller is a check something else can reach the callable without: ADR-0029
§1 put the invoker where it is precisely so that "handing every holder of a lookup
the ability to execute" stops being possible, and a ceiling enforced one level
above the seam inherits none of that.

**The residue this placement leaves, named rather than left to be found.** The
admission is a read followed by ADR-0192's claim, which is a second operation, so
two invocations in flight can each project a total that does not yet include the
other. The overshoot is bounded — by the number of concurrent calls times the
largest declared estimate among them — and it is **unreachable today**, because
ADR-0029 §7 rules that "one executor runs at a time". It is not unreachable
forever. The obligation is stated in §8 and belongs to the ADR that lands parallel
execution: it either moves the admission into the claim's own atomic operation or
holds a lease across the pair, and it may not land concurrency and leave this
clause as it stands.

### 4. The refusal is a refusal, and it says why without saying what

> **Normative.** A call the ceiling refuses raises `SpendCeilingError`, a new
> class in `core/errors.py` deriving from `AssistantError`. It is a seam fault: it
> is raised, never returned as a `ToolResult`, and it is never auto-retried.

> **Normative.** The refusal is an exit **before the callable is entered**, so it
> falls in the window ADR-0034 §1 governs and qualifies on that section's second
> ground — the contract says the exit precedes the callable. The executor commits
> `RUNNING → FAILED` and never retries, on the window and not on a list of
> classes.

> **Normative.** The ceiling never produces a `CONFIRM`, never routes a question
> to the user, and no per-call answer overrides it. The only way to spend past a
> ceiling is to change the configured ceiling.

> **Normative.** `SpendCeilingError` is **not** a `PermissionDeniedError` and no
> lane makes it one.

> **Normative.** The message is **payload-free**. It states the ceiling that was
> crossed, its period, its currency, the accounted total and whether that total is
> indeterminate — and carries no argument value, no recipient, no account, no tool
> output and no digest of any of them.

**A refusal rather than a confirmation, and the user has already been asked.**
Every call that reaches this seam has passed ADR-0021 §5's floors, and every
egress call has been answered by the user about that specific request (ADR-0148
§3, §8). Asking a second question — "you are over your ceiling, proceed?" — adds
no information the user does not have and converts the ceiling into a prompt,
which is the "trains its user to approve everything" failure in the one place
where the user's earlier, calmer instruction is the better authority. #1548 puts
the same conclusion in one sentence about a shipped system: a ceiling that informs
rather than binds is not a ceiling. The relief valve is deliberately outside the
turn — the user raises the ceiling, in configuration, as a deliberate act — which
is the same shape ADR-0021 §5 blesses for its own floor: "A user who wants their
calendar tool to stop asking says so once, on the record."

**Not a `PermissionDeniedError`, and the corpus has drawn this line twice
already.** That class means, in `core/errors.py`'s own words, that "somebody did
and said no" — `ai_assistant.orchestration.runner` raises it when a confirmation
was refused or a recorded ruling was not `ALLOW`. Here the recorded ruling **is**
`ALLOW`: the user said yes about this call, and what refuses is arithmetic over a
period. Folding the two together would let a surface tell a user their answer was
overruled when it was honoured and their month was spent, and would leave a trace
unable to separate "you declined" from "you are out of budget". That is
`SourceNotGrantedError`'s reasoning one store over — ADR-0097 §7's "a source
refusal and an action refusal are different subjects, and a caller that cannot
tell them apart is one that will report 'you declined to send that email' when the
calendar was never granted."

**Payload-free because the refusal travels further than the call did.** The error
crosses the seam into the executor and reaches a step failure that a user reads,
and it is composed at a moment when the call's arguments are in hand — which is
the shape ADR-0093 §8 made a rule for `SensorError` ("a `SensorError`'s message is
payload-free"), and which ADR-0021 §1's payload rule and ADR-0192's no-content row
enforce on the two records beside it. Nothing about which recipient, which
subject, or which argument is needed to explain a ceiling; the numbers are the
whole explanation.

### 5. `SpendLedger`: one `core` Protocol, two `core` types, one holder

> **Normative.** `core/protocols.py` gains `SpendLedger`, with exactly two
> members, both `async`.
> `admit_invocation(*, estimate: ToolCost) -> None` evaluates §3's admission and
> raises `SpendCeilingError` where it refuses, returning `None` otherwise; it
> stores nothing and appends nothing.
> `spend_totals() -> tuple[SpendTotal, ...]` returns one `SpendTotal` per period
> this ADR defines, in a fixed order — `CALENDAR_DAY` then `CALENDAR_MONTH` — and
> returns both entries whether or not either ceiling is configured.

> **Normative.** `core/types.py` gains `SpendPeriod`, a `StrEnum` with exactly two
> members, `CALENDAR_DAY` and `CALENDAR_MONTH`, and no ordering semantics.

> **Normative.** `core/types.py` gains `SpendTotal`, frozen with
> `extra="forbid"`, carrying exactly: `period: SpendPeriod`;
> `period_start: datetime` and `period_end: datetime`, both timezone-aware and
> `period_end` exclusive; `ceiling: Decimal | None`; `currency: str | None`,
> present if and only if `ceiling` is; and `accounted: Decimal | None`, where
> `None` states that the period's total is **indeterminate** under §2.

> **Normative.** A `ToolInvoker` implementation holds a `SpendLedger`. It acquires
> no `AuditTrail` and no additional store handle by this ADR, and the ledger can
> neither record nor read a `PermissionDecision`, neither export nor `clear`.

> **Normative.** `app/composition.py` is the sole holder and the sole wirer: it
> constructs the ledger, reads §1's settings, injects the clock, and hands the
> object to the invoker. No subsystem constructs one, and no default is
> substituted where the composition root did not wire one.

> **Normative.** One object implements `SpendLedger` and ADR-0192's ledger seam,
> because the totals are computed from that ledger's own rows. Two stores keyed by
> the same rows could disagree about a total, which is the failure ADR-0016 §7
> named for two registries, one seam over.

**A `None` accounted total is the right shape here, and it is not the optional
`ToolCost` ADR-0016 §4 refused.** That refusal was about a *cost* field whose
`None` had to be distinguished from **free** — two meanings collapsing into one
absence, in a field where a spend policy would read the absence as zero. A total
has no such collision: zero spend is `Decimal("0")` and is representable, so the
only thing `None` can mean is the one thing it does mean — the sum is not a
number, because a member of it was not one. The state it names is exactly §2's
indeterminate period, and it is computed rather than stored, so nothing can leave
it set.

**Two members and no more, and each is there for a named consumer.**
`admit_invocation` has one caller, the invoker, and takes the one value the
invoker holds that the ledger cannot derive — the declaration on the definition
ADR-0029 §2's checks have already pinned. `spend_totals` has one caller, the
engine operation in §6. There is deliberately no member that returns "the amount
remaining", no member that reserves, and no member that writes: a reservation
would be a second two-phase ledger beside ADR-0192's, duplicating its claim and
its completion for a quantity that is already derivable from them.

**A new Protocol, so it is a triad.** Contract, shared conformance suite and
canonical fake in `ai_assistant.testing`, in one change and never deferred
(`CONTRIBUTING.md` → "Adding a Protocol"), and under ADR-0137 §2 it rides with
its primary production implementation — the `permissions` store that also
satisfies ADR-0192's ledger, which is the consumer whose demands shape it. §11 is
where that lands.

### 6. What the user sees

> **Normative.** `AssistantEngine` gains exactly one member, a read:
> `spend_totals()`, relaying `SpendLedger.spend_totals` and returning what it
> returns.

> **Normative.** `interfaces/cli.py` gains exactly one command, which renders that
> operation's `SpendTotal` values: each period, its bounds in the user's
> configured time zone, its ceiling and currency where configured, and its
> accounted total — or, where the total is indeterminate, that it is, and that no
> further call in that period will be admitted.

> **Normative.** This operation is **not** one of ADR-0177 §1's thirty. No browser
> request resolves to it, no browser argument reaches it, the gateway makes no
> call of its own to it, and this ADR does not widen that enumeration. A browser
> view is a later consumer lane with its own ratified decision, on the route
> ADR-0177 §1's third clause fixes.

> **Normative.** No surface presents an accounted total as an amount billed, owed,
> or charged. It is the sum of what this system's tools reported, and a surface
> states it as that. No surface presents a `ToolDefinition.cost` as a measurement
> of what any call cost (ADR-0016 §3's ceiling rule and ADR-0186 §8's fifth
> clause, one field over).

> **Normative.** The confirmation card gains nothing from this ADR. This ADR adds
> no field to a `Confirmation`, no cost line to its rendering and no ceiling
> figure to it.

**The CLI and not the browser, following ADR-0186 §6 rather than reasoning
afresh.** That section closed ADR-0177 §1's enumeration for the audit surface on
two grounds that both hold here: the CLI is the surface a milestone's exit test
can be measured on with no gateway in the loop, and a browser view landing beside
in-flight browser work collides with it in the same assets for no gain this
milestone can measure. The trigger for reopening is the same as ADR-0186's — a
later lane widening the enumeration in its own text.

**Nothing on the confirmation card, and the reason is the same one that put the
admission at the seam.** A figure on the card would be a total read at ruling
time, shown to a user who then answers, after which the total moves — so it would
be a number the seam does not enforce at the moment the user acted on it. That is
informing rather than binding, on the surface where the difference matters most.
What the user already gets at that moment is the declaration: `permissions.policy`
composes its ruling reason from the tool's own facts and names the cost basis in
it, which is the declared fact ADR-0016 §4 makes available and the only one that
is true at ruling time.

### 7. Data rights: the total is derived, erasure resets it, and the period rolls over

> **Normative.** The accounted total is **derived**. It is a function of ADR-0192's
> rows and this ADR mints no durable record: no counter, no per-period row, no
> cached total and no marker survives a restart. An implementation that caches
> recomputes from the rows and no cache is authoritative.

> **Normative.** This ADR creates no new personal data and therefore adds no
> retention rule, no TTL and no export artifact of its own. The rows the total is
> derived from are ADR-0192's, and their tier, their retention and their export are
> that ADR's.

> **Normative.** `AuditTrail.clear()` erases the rows, so after it every accounted
> total is `Decimal("0")` and every period is determinate. Nothing preserves a
> total across an erasure, and no lane adds a spend counter that outlives one.

> **Normative.** A period boundary is computed from the injected clock at the
> moment of the read or the admission; rows do not move between periods, and a
> clock that steps backwards changes which period is current without rewriting the
> history of any other.

**Erasure resetting the ceiling is a consequence stated in the open rather than a
hole.** A durable spend counter that survived `clear()` would be a record of the
user's activity that the user's own erasure does not reach — the shape ADR-0004
§6 exists to forbid — and it would be inconsistent besides, since the rows it
counted are gone and it could no longer be checked against anything. So the
mechanism is honest in the only direction available: the ceiling counts what the
trail holds, and a user who erases the trail erases the evidence the ceiling
counts. The user who does that has made a deliberate, wholesale act about their
own record (ADR-0021 §4), and the ceiling is not a lock against that user.

### 8. Out of scope, each with the trigger that brings it in

Scoping something out is a decision, so each carries the condition that reopens it.

> **Normative.** Nothing in this section grants a later lane the thing it defers.
> Each item is reopened by its own ratified decision and by nothing else — not by
> resemblance to a mechanism this ADR did land, and not by a lane finding the
> deferral inconvenient.

- **A default ceiling.** Reopened when an authorisation can cover an egress call
  with no per-call user act — the standing grant ADR-0021 §6 defers and ADR-0148
  §3's third clause reserves. The ground under §1's "unset means unbounded" is
  that per-call act; when it goes, the default is that ADR's question.
- **Per-tool, per-capability and per-protocol ceilings.** Reopened by a decision
  that lands keyed per-user tool configuration — ADR-0016 §7's deferred "tool
  enablement and per-user configuration", which is the store such a ceiling needs.
- **Currency conversion, and a ceiling over more than one currency.** Reopened by
  a decision that names a rate source, which is itself a world-reaching read and
  therefore has an egress question of its own before it has an arithmetic one.
  ADR-0016 §4 already rules conversion "out of scope entirely" and this ADR does
  not narrow that.
- **Model-provider spend.** Reopened by either of two facts: an ADR bringing
  `models/` under the injected transport capability (#85, ADR-0017 §8's carve-out),
  or a ledger over model calls landing. Whether one ceiling then covers both axes
  is that ADR's question; this ADR bounds one axis and says which.
- **Reconciliation against a provider's bill**, and any surface by which a user
  corrects a reported figure. ADR-0014 §7's deferral, restated by ADR-0029, and it
  stays there. Its consequence is stated rather than hidden: an unknown-priced
  completion with no configured allowance closes its period until the period rolls
  over, and the only remedies are the allowance, a changed ceiling, and time.
- **The concurrency residue of §3's placement.** Reopened by, and owed by, the ADR
  that lands parallel execution (ADR-0029 §7, ADR-0014 §7): it moves the admission
  into the claim's atomic operation or holds a lease across the pair. It may not
  land concurrency and leave §3 as written.
- **Money a tool moves.** ADR-0016 §7's transacted-cost deferral, untouched. The
  price of a flight lives in a call's parameters, and pricing it needs the
  parameter-level policy ADR-0016 §4 declined to invent.

### 9. What this changes in other ADRs, clause by clause

**ADR-0021 §6, "Spend accumulation".** Its sentence — "The declaration-level rule
lands (`UNKNOWN` fails closed); a running total against a budget needs invocation
to report what was actually spent" — named a precondition and left the mechanism
undone. ADR-0192 supplies the precondition; this ADR supplies the mechanism. A
reader holding only ADR-0021 would read spend accumulation as still deferred and
would be wrong about the tree, so a record is owed on it (§10). The remainder of
§6 is untouched: standing grants, recipient authorisation, Tier 0/1 gating, payload
description, retention and richer queries are all still deferred, and this ADR
touches none of them.

**ADR-0021 §5.** Untouched and unrelaxed. Its `UNKNOWN`-cost floor still sends
such a tool to `CONFIRM` at the policy; §2's treatment of `UNKNOWN` in a total is a
second, later reading of the same declaration by a different consumer, and neither
satisfies nor lifts the floor. A stacked addition in ADR-0082 §1's sense: no
sentence of §5 becomes false, so no record is owed against it.

**ADR-0029 §7's "Standing grants and spend accumulation" bullet.** Its second half
— spend accumulation "additionally needs a cost report invocation cannot honestly
produce (§3)" — is a deferral this ADR discharges, on a report ADR-0192 makes
producible. A record is owed (§10). Its first half, standing grants, is untouched
and stays deferred.

**ADR-0029 §3's cost omission and ADR-0016's "estimate nothing reconciles"
Consequence.** Both are ADR-0192's to address and neither is addressed here. This
ADR adds no field to `ToolResult`, changes no sentence of ADR-0016, and edits
neither document. It consumes what ADR-0192 lands and cites it by number.

**ADR-0016 §7's transacted-cost deferral.** Unaffected and still deferred (§8).
This ADR bounds the price of invoking a tool, which is what ADR-0016 §4 says
`cost` is, and never the money a tool moves.

**ADR-0177 §1 and ADR-0186 §6.** Neither is widened. §6 above adds an operation
that is not one of the thirty and says so in the same terms ADR-0186 §6 used,
which is a stacked addition against both: no sentence of either becomes false, and
no record is owed against either.

**ADR-0034 §1.** Unchanged. §4's refusal qualifies under its existing second
ground; nothing here adds a class to a list or widens the window.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

**ADR-0021 §6 — a record is owed, and it is an amendment.** The clause says spend
accumulation is deferred. After this ADR it is not, so a reader holding only
ADR-0021 reads the deferral more widely than it now holds. It is an **amendment**
rather than a supersession because nothing §6 *decided* is reversed: a deferral
decides not to decide now, and its own stated precondition — invocation reporting
what was actually spent — is satisfied rather than overruled. Its reason survives
whole; only its currency lapses. This is the treatment ADR-0016's header already
gives its own discharged deferrals ("§7's invocation deferral is discharged by
ADR-0029"). The record is a `Status` qualifier naming this ADR and an appended
dated note on ADR-0021, per ADR-0082 §2 — and where ADR-0021's `Status` line is by
then led by `Partially superseded by`, §2 puts the record in the note alone and no
qualifier is added.

**ADR-0029 §7 — a record is owed, on the same reading.** The bullet's second half
defers spend accumulation and gives a precondition ADR-0192 satisfies. Same test,
same answer, same form: a `Status` qualifier and an appended dated note, or the
note alone where §2 excludes the qualifier.

**Everything else in §9 is a stacked addition and no record is owed.** ADR-0021
§5, ADR-0016 §§3–4, ADR-0029 §§1–5, ADR-0034 §1, ADR-0177 §1, ADR-0186 §6 and §8:
for each, every sentence stays true and the obligation this ADR adds is stated
here. ADR-0082 §1 is explicit that a record demanded on book-keeping grounds
alone — that a list "should mention" a change — is not owed, and none is taken
here.

**This ADR supersedes nothing and withdraws nothing.** It adds `core` surface, it
discharges two deferrals, and it names the ADRs it depends on rather than
replacing them.

### 11. What the implementing lane owes, and what it is sequenced behind

> **Normative.** The implementing lane lands `SpendLedger` as a triad — the
> Protocol, a shared conformance suite, and a canonical fake in
> `ai_assistant.testing` — together with the `SpendTotal` and `SpendPeriod` types,
> the `SpendCeilingError` class, §1's five settings, the invoker's call to
> `admit_invocation`, the engine operation and the CLI command, in one change
> under ADR-0137 §2.

> **Normative.** That lane is sequenced **after** ADR-0192's implementation has
> merged. It reads the completion rows that ADR lands and cannot be written
> against a record that does not exist.

> **Normative.** The conformance suite pins the clock and drives at least: a
> projected total exactly equal to a ceiling, admitted; one cent over, refused; a
> `FREE` call admitted with the accounted total already at the ceiling; an
> `UNKNOWN` estimate refused with no allowance configured and admitted at the
> allowance with one; an `UNKNOWN` completion making the period indeterminate and
> the next call refused; a foreign-currency cost taking the `UNKNOWN` path; a
> period rollover clearing an indeterminate total; both ceilings configured with
> the day ceiling binding first; and no ceiling configured admitting everything
> while still reporting a total.

> **Normative.** The lane asserts that a refused call left **no** claim and no
> completion in ADR-0192's ledger, and that the refusal reached the executor as
> ADR-0034 §1's pre-callable exit.

> **Normative.** The lane changes no tool's declared `ToolCost`. In particular it
> does not re-declare `send_email`'s `UNKNOWN`; the honest declaration stands and
> §2's allowance is the mechanism that makes it usable.

## Consequences

- **A ceiling exists, and it binds rather than informs.** It is evaluated at the
  one seam every invocation passes, before the act, and its refusal is a raise the
  executor cannot route around. Against the surveyed field that is the property
  nobody had: the one ceiling in five runtimes is over tokens, is an estimate, and
  lets the crossing call complete.
- **Configuring a ceiling makes `send_email` unusable until the user also
  configures an allowance.** This is the sharpest cost of the decision and it is
  deliberate: the only world-reaching tool declares `UNKNOWN`, and §2 refuses to
  turn that into a zero. The user's remedy is one setting, and the alternative —
  counting an unknown price as nothing — would have made the ceiling a decoration
  for exactly the tool the milestone is about.
- **An unknown-priced completion closes its period.** Where no allowance is set, a
  single such row stops every further invocation until the calendar rolls or the
  user acts. That is a real denial of service on the user's own assistant, taken
  knowingly: the alternative is a total that under-reports by an unbounded amount
  while presenting itself as a bound. §8 names the deferral that would soften it.
- **The ceiling is not a guarantee about the total, and says so.** It bounds what
  *begins*, not what *ends up spent*, because a declaration can understate.
  Stating the weaker property is what keeps the number honest — the same candour
  #1548 credits Claude Code's docs for, applied to our own.
- **`permissions` gains no store handle and `ActionPolicy` gains nothing.** The
  monotonicity and floor obligations stay checkable on a pure function, which is
  what ADR-0021 §5's whole conformance argument rests on.
- **Erasing the trail resets the ceiling.** Accepted, because the alternative is a
  spend record that outlives the user's own erasure.
- **`core` grows by four names** — `SpendLedger`, `SpendPeriod`, `SpendTotal`,
  `SpendCeilingError` — plus one engine member and five settings. That is the
  breaking-change surface golden rule 5 asks be flagged, and none of it lands
  here.
- **Two deferrals close and a third is created.** ADR-0021 §6's and ADR-0029 §7's
  spend-accumulation halves are discharged; the concurrency residue of §3 is a new,
  named obligation on the ADR that lands parallel execution.
- **Revisit when** a standing grant makes a call executable with no per-call user
  act (the default becomes a live question), when a second priced integration
  lands (the per-tool deferral gets its first real case), or when a user's tools
  span two currencies.

## Alternatives considered

- **The ceiling in `ActionPolicy.decide`.** Rejected in §3 on two independent
  grounds: it would give the policy a clock and a store, destroying the pure
  function ADR-0021 §5's conformance obligations are built on; and a ruling cannot
  bind a total that moves between the ruling and the act.
- **A rolling window instead of calendar periods.** Rejected in §1. More precise,
  and it gives a user no boundary they can name, no answer to "when can I do this
  again", and a continuous re-decision over a moving set of rows. The day ceiling
  supplies the rate limit that was the rolling window's real advantage.
- **Counting an `UNKNOWN` cost as zero.** Rejected in §2, and it is #1548's named
  failure. It makes the ceiling silently wrong for exactly the tools whose authors
  were honest about not knowing.
- **Refusing every `UNKNOWN`-priced call outright, with no allowance.** Rejected
  in §2. Strictly correct as arithmetic and it switches off the only world-reaching
  tool in the tree, punishing an honest declaration. The allowance keeps the
  arithmetic sound by having the one party who can price the call state a worst
  case.
- **A `CONFIRM` on crossing, so the user can override once.** Rejected in §4. The
  user has already answered about this call; a second question converts a standing
  instruction into a prompt, which is the shape the survey and ADR-0021 §5 both
  warn about.
- **A reservation ledger — reserve, execute, settle.** Rejected in §5. It closes
  §3's concurrency residue completely, and it does so by building a second
  two-phase ledger beside ADR-0192's, with its own open-reservation recovery
  problem. Under one executor the residue is unreachable, so the cost is certain
  and the benefit is not yet real; §8 hands the choice to the ADR that makes it
  real.
- **Adding the ceiling refusal to ADR-0192's claim, as a fifth entry in its
  refusal order.** Rejected. It is the tightest possible placement — one atomic
  operation, no residue at all — and it puts a budget decision inside a Protocol
  whose stated capability is appending two kinds of row, reshaping a contract this
  ADR depends on and whose refusal list is closed in its own text. The ADR that
  lands concurrency may take it; taking it here would couple two proposals under
  review.
- **A per-tool ceiling as the primary control.** Rejected in §1: it needs keyed
  configuration ADR-0016 §7 defers, and it partitions one budget rather than
  lowering it.
- **Folding model spend into the same total.** Rejected in §2 and §8. It is a
  different ledger over a different act, and folding it in is how a world budget
  becomes a token budget in disguise — #1548's last avoid-list entry.
