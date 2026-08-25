# 194. A ceiling on what the world may cost is decided before the act, and an unknown price is never zero

- Status: Proposed
- Date: 2026-08-25
- **Decides `core` contract surface and implements none of it (golden rule 5).**
  It adds **two** Protocols, three `core/types.py` models and three
  `core/errors.py` classes, and it lands none of them: the triad and its primary
  production implementation land **together, in one paired lane**, separate from
  this ADR and sequenced behind ADR-0192's (§11). That pairing is ADR-0137 §2's
  and is not this ADR's choice to make otherwise; splitting them would produce the
  contract-only PR followed by an implementation PR that §2 exists to prevent. **Because this ADR decides a
  contract surface, its required review set is adversarial *and* architecture**,
  even though the PR carrying it is prose only — `CONTRIBUTING.md` → "Stop when
  the required reviews are green" and ADR-0015 §1.
- Amends: ADR-0021 §6's **Spend accumulation** deferral and ADR-0029 §7's
  spend-accumulation half.
- **Partially supersedes ADR-0087** — the enumeration of the types the wire
  encoding carries, in the **three** clauses that state it: §2c's table, §6's
  inventory of the scalar types the promoted surface reaches, and §9's count of the
  values §2 gives no encoding. It gains `Decimal` because §5 promotes a member
  carrying one and the enumeration is exhaustive by construction (the codec raises
  on a type it does not list). No existing row's spelling moves and §3's
  exhaustive-three table is untouched (§9). §10 applies ADR-0070 §1 and ADR-0082
  §1 to each record this ADR takes.
- **Depends on ADR-0192 by number, and on no field of it.** This ADR cites that
  decision as the thing that records what an invocation cost — a completion row
  carrying a reported figure, and a claim that may stand open — and reshapes
  nothing of it: it adds no member to its Protocol, no entry to its refusal order
  and no field to its row. What it does not do is *precede* it in implementation:
  §11 sequences the lane that builds this behind the lane that builds ADR-0192's
  record. That is what the rule requires, in its own words: a substantive contract
  ADR "ships as **its own PR, ratified before the implementation PR that depends
  on it**" (`CONTRIBUTING.md` → "Contract ADRs land before their implementation",
  ADR-0015 §5). The ordering it fixes is *ADR before implementation*, and it fixes
  no ordering between two ADRs — which is why the same document says a contract
  ADR is reviewed while it stands `Proposed`, "so a finding can still change the
  decision". Deciding two contracts in parallel and building them in order is
  batch #1544's shape, and no clause of `CONTRIBUTING.md` or of a ratified ADR
  forbids it. If ADR-0192's ratified text lands differing from what this ADR
  cites, this ADR's own §9 is where that is reconciled, at the cost of a
  paragraph — which is the cost that document names for finding it early.

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

> **Normative.** `core.config.Settings` gains exactly four fields and no others:
> `world_spend_currency: str | None`, `world_spend_month_ceiling: Decimal | None`,
> `world_spend_day_ceiling: Decimal | None` and
> `world_spend_unknown_allowance: Decimal | None`, each defaulting to `None`. They
> are the whole of what this mechanism **adds** to configuration: no lane adds a
> fifth field, and these four are the only settings that turn the mechanism on or
> change what it refuses **given a period**. They are not the only settings its
> answers depend on, and the clause below names the one that is not among them.

> **Normative.** It reads exactly one **existing** setting besides them,
> `Settings.timezone`, and that setting's influence is **period selection and
> nothing else**: it fixes the `[start, end)` bounds below, so which period a row
> falls in, and therefore which rows a total sums and which total an admission is
> compared against. Changing it from `UTC` to `Pacific/Kiritimati` over identical
> rows and identical spend settings can move a row across the current day's
> boundary and change both a stated total and an admission — that is the zone doing
> its job and not a second spend knob, and the clause above is written to leave
> room for it rather than to deny it. The zone is the user's one answer to "what day
> is it", already ratified and already read by every other dated surface; this
> mechanism neither validates it again nor carries a zone of its own. The
> composition root therefore reads **five** settings (§5), and a reader counting
> only four cannot implement the period rule.

> **Normative.** `world_spend_currency` is validated on **shape only** — exactly
> three uppercase ASCII letters, ISO-4217's alphabetic form, neither normalised
> nor checked against the live register. This is `ToolCost.currency`'s rule
> (ADR-0016 §4) and not a second one.

> **Normative.** An amount is **countable** exactly where all three hold: it is
> finite; its absolute value is **strictly less than** `Decimal("1E15")`; and its
> **value** can be expressed with at most **nine** fractional digits. It is a test
> on the number and not on its representation, so `Decimal("1.0000000000")` is
> countable because its value is `1`. This predicate governs every amount this
> mechanism reads: a configured ceiling, the allowance, a declared
> `ToolCost.amount` and a reported one. It governs **inputs** and not results: a
> computed total is a sum of countable amounts over rows nothing bounds, so it is
> not itself bounded by this predicate and is never refused on it.

> **Normative.** The predicate is **context-independent**, and an implementation
> evaluates it without consulting `decimal.getcontext()`. Read `digits` and
> `exponent` from the amount's own `Decimal.as_tuple()`: the scale test is
> `exponent >= -9`, or every digit the amount carries at a position below
> `10**-9` is zero. No ambient precision, rounding mode or trap setting changes a
> classification or makes one raise, and an implementation that reaches for
> `quantize` uses an isolated context sized for the operand rather than the
> caller's.

> **Normative.** A **configured** amount that is not countable is refused at load
> with `ConfigurationError`, naming the field. A **declared** amount that is not
> countable refuses the call at admission with `SpendUndeterminedError` where a
> ceiling is configured — it is §4's **first** ground, first in that section's
> evaluation order as well as in its list, and it is not a crossing: no ceiling was
> reached, and the projection could not be formed at all. A
> **reported** amount that is not countable makes its period's accounted total
> **indeterminate** (§2).

> **Normative.** An amount that is not countable is **never** replaced by
> `world_spend_unknown_allowance`. The allowance stands for a price nobody knows;
> an out-of-range amount is a price somebody stated and this mechanism cannot add,
> and substituting a small number for a large stated one would defeat both the
> admission and the account. The allowance reaches an `UNKNOWN` basis and nothing
> else.

> **Normative.** Either ceiling, where set, is a `Decimal` that is **finite and
> greater than or equal to zero**. A non-finite value is refused at load, as
> `ToolCost.amount` refuses one, and for the same reason: `Decimal` admits
> `Infinity` and `NaN`, neither survives arithmetic in a running total, and `NaN`
> makes every comparison false rather than answering.

> **Normative.** `world_spend_unknown_allowance`, where set, is a `Decimal` that
> is **finite and strictly greater than zero**. Zero is refused at load in every
> spelling `Decimal` admits for it — `Decimal("0")`, `Decimal("-0")`,
> `Decimal("0.00")`, `Decimal("0E-9")` — and so is any negative value.

> **Normative.** A ceiling and the allowance may each be set only where
> `world_spend_currency` is set. `world_spend_currency` **may be set alone**: that
> configures a **reporting currency** under which totals are computed and readable
> (§6) and nothing is ever refused. A configuration violating this raises
> `ConfigurationError` at load, as every other malformed setting does.

> **Normative.** A ceiling bounds **the sum over tool invocations**, across every
> registered tool, and is scoped to the world as a whole. No per-tool, per-capability
> or per-protocol ceiling is decided here, and no lane adds one without its own
> ratified decision (§8).

> **Normative.** The two periods are **calendar periods in the user's configured
> time zone** (`Settings.timezone`), and each is the half-open instant interval
> `[start, end)`: a row belongs to the period containing its recorded instant, and
> a period's `end` instant belongs to the next period.

> **Normative.** The boundary for a civil date `D` in that zone is the
> **earliest instant whose local civil date is greater than or equal to `D`**. A
> period's `start` is that boundary for its own first date and its `end` is that
> boundary for the first date of the following period — the next day for
> `CALENDAR_DAY`, the first of the next month for `CALENDAR_MONTH`.

> **Normative.** That one selection is the whole rule and covers every transition
> a zone may carry, with no case distinguished by an implementation. Where `D`'s
> civil midnight is **repeated** across a backward transition it selects the
> **earlier** of the two instants; where midnight **does not exist** across a
> forward transition it selects the transition instant itself; and where the
> **whole civil date `D` is skipped** — `Pacific/Apia` has no instant whose local
> date is 2011-12-30 — it selects the first instant of the next date that exists,
> which makes `D`'s period **zero-length**. A zero-length period holds no rows,
> states a total of zero where a currency is configured, and refuses nothing. No
> implementation constructs a boundary by naming a wall-clock midnight and
> accepting whatever `fold` a default supplies.

> **Normative.** Where a period's `end` is not representable — as a `UtcInstant`,
> or as a civil time in the period's own zone, which `Pacific/Kiritimati` reaches
> first because its offset carries a late-9999 boundary into year 10000 — the `end`
> is the **latest instant representable in both**, and the period is closed at it.
> The mechanism does not refuse on that ground; what is lost is the membership of a
> handful of instants no clock this system accepts can reach (ADR-0026).

> **Normative.** The **same rule binds at the other end**, and it is stated
> separately because an implementation that clamped only the late boundary passes
> every case the clause above describes. Where a period's `start` is not
> representable — as a `UtcInstant`, or as a civil time in the period's own zone —
> the `start` is the **earliest instant representable in both**, and the period is
> opened at it. A **positive-offset** zone reaches this first, and it is reachable
> from a clock reading `checked_clock` accepts: at `0001-01-02T00:00:00Z` in
> `Etc/GMT-7` the current calendar month begins on civil `0001-01-01`, whose local
> midnight is earlier than the earliest instant there is, so an implementation that
> constructs that midnight raises `OverflowError` where this rule requires a
> clamped `start`. The mechanism does not refuse on that ground either, and what is
> lost is the same handful of unreachable instants at the opposite end.

> **Normative.** Both ceilings bind independently and simultaneously where both
> are set. A call is refused where it would cross **either**. A
> `world_spend_day_ceiling` above the month ceiling is accepted and is simply
> never the binding one; nothing refuses a configuration on that ground.

> **Normative.** **No ceiling configured means no ceiling.** Where both ceilings
> are unset this mechanism refuses nothing and admits every call — unconditionally,
> whatever any total says. Where a reporting currency is nonetheless configured the
> totals are still computed and still readable (§6). No default amount is minted,
> here or by an implementation.

**The two numbers are contract, and they are what makes §2's exact arithmetic
computable rather than aspirational.** Without a bound, two amounts a validator
would accept — `Decimal(f"1e{decimal.MAX_EMAX}")` and `Decimal("1")` — have an
exact sum needing more coefficient digits than `decimal.MAX_PREC` admits, so the
computation exhausts memory instead of trapping and the outcome depends on the
machine. Bounded, the digits a sum needs are bounded too, the context §2 requires
can always be sized, and the traps become a backstop against an implementation
that failed to size it. The numbers themselves are stated so a reader can disagree
with a number rather than with the principle: 10^15 in any real currency's major
unit exceeds any plausible monthly ceiling by orders of magnitude, and nine
fractional digits carry every currency's minor unit and every nano-unit price a
metered API quotes.

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
to) — **or** a priced tool a policy may auto-`ALLOW` outright, which that floor
does not reach: it binds a non-empty `discloses`, and a `PER_CALL` tool may
declare none. The paragraph above is about reaching the *world*, and this
mechanism counts every registered tool (§1), so the two are not the same set and
the narrower claim would not carry the ceiling's own scope. Neither route is
walked in the tree today — nothing declares a `PER_CALL` cost (§5) and nothing
populates `authorised_by` — and when either is, the ground under this clause is
gone and the default is reopened by that fact; §8 records both as the trigger
rather than pre-deciding it here.

### 2. What is counted: a declared estimate before, a reported figure after, and an unknown price that is never zero

> **Normative.** An accounted total is computed only where
> `world_spend_currency` is set. Where no currency is configured nothing is
> summed, no total is stated, and nothing is refused.

> **Normative.** The **accounted total** of a period is the sum of the reported
> per-invocation costs carried by ADR-0192's **completion** rows whose recorded
> instant falls in that period. Nothing else contributes to it: not a
> `ToolDefinition.cost`, not a `PermissionDecision`, not a model call.

> **Normative.** An **open claim in the period makes that period's accounted total
> indeterminate**, whatever the allowance is set to and whatever the claim's
> decision declared. A claim ADR-0192 records with no completion states that an act
> may have happened and does not state what it cost; a total that omitted it would
> count a possibly-incurred cost as zero, and a total that substituted a figure for
> it would state one nobody reported.

> **Normative.** The **projected total** for a call under admission is the
> accounted total of the period plus the declared amounts of **every** reservation
> the gate is holding — §3's, whichever period each was taken in, since a call
> admitted before a boundary can complete after it — plus that call's own
> **declared** cost —
> the `ToolCost` on the `ToolDefinition` the call's recorded decision pins. Every
> declared amount here is used **only** for the admission arithmetic in §3; none is
> added to the accounted total and none is written to any row.

> **Normative.** A `FREE` basis contributes zero, in both totals. A `PER_CALL`
> basis in the configured currency contributes its `amount`.

> **Normative.** A cost whose basis is `UNKNOWN` contributes
> `world_spend_unknown_allowance` where that setting is set. Where it is not the
> cost has no number at all, and the two sides part rather than sharing one: a
> **declared** `UNKNOWN` cost refuses the call at admission with
> `SpendUndeterminedError` where a ceiling is configured — §4's **second** ground,
> and like the first it is not a crossing, since no ceiling was reached and the
> projection was never formed — while a **reported** `UNKNOWN` cost makes its
> period's accounted total **indeterminate**. An `UNKNOWN` cost is never treated as
> zero and never omitted from a total.

> **Normative.** No implementation substitutes a large number for an unpriced cost,
> and that is why the refusal is the undetermined class rather than a crossing. A
> stand-in "greater than any ceiling" would have to be a particular `Decimal`, §4
> makes a `SpendCeilingError` state the projected total that crossed, and two
> implementations picking `Decimal("1E15")` and `Decimal("1E16")` would refuse the
> same call while reporting different contract values — which §2's one-representation
> rule exists to forbid. There is no projected total here to state, and the class
> that says so is the one whose whole subject is a spend that could not be reduced
> to a number.

> **Normative.** An indeterminate accounted total refuses admission **only where
> that period's own ceiling is configured**. A period nobody set a ceiling for is a
> reporting figure and enforces nothing (§1), so with only a day ceiling set, a
> month that cannot be measured refuses nothing. It does not need to: a period
> contains its days, so an open claim or an unpriced completion in the **current**
> day makes that day indeterminate too and the day ceiling refuses on its own
> period. What the narrowing excludes is exactly the case where the unmeasurable
> row is in an *earlier* day of the same month — a bound the user never stated
> refusing work they authorised, which is the direction §1 declines a defaulted
> ceiling for. Where **neither** ceiling is set nothing is refused whatever either
> total says: §1's "no ceiling configured means no ceiling" is unconditional, and
> this clause is what makes it so.

> **Normative.** A cost denominated in a currency other than `world_spend_currency`
> is **never converted**. It is treated exactly as an `UNKNOWN` basis is by the
> clauses above — the allowance where one is configured, and otherwise §4's second
> ground when declared and an indeterminate period when reported.
> A cost whose *amount* is not countable is
> **not** treated that way; §1's clause governs it, and the allowance never reaches
> it. No implementation reads an exchange rate, and no lane adds one
> without its own ratified decision (§8).

> **Normative.** Every sum and comparison this mechanism performs is the
> **mathematically exact one**, and the result is what conformance pins — never a
> precision, a rounding mode or an exponent range. An implementation using
> `decimal.Context` sizes **both** its precision and its exponent bounds from the
> operands, so that no addition or comparison rounds, overflows or goes subnormal
> on any well-formed input, and it traps `Inexact`, `Rounded`, `Overflow`,
> `Underflow` and `Subnormal` so that a failure to size it raises rather than
> answering quietly. Two conforming implementations therefore return the same
> admission decision for the same inputs; none rounds to a currency's minor unit,
> and none compares two amounts through `float`.

> **Normative.** The sizing always succeeds, and **not** because every operand is
> countable. §1's predicate governs the amounts this mechanism *reads* and
> explicitly not the totals it computes, and the projection's first operand is the
> accounted total — which §1 exempts by name and §5 declares deliberately unbounded
> in magnitude, over rows §11 requires a fixture of above `Decimal("1E19")` for. So
> the two kinds of operand are sized differently, and an implementation must not
> confuse them. A **source amount** — a configured ceiling, the allowance, a
> declared amount, a reported one — is bounded by §1, and fifteen integer digits
> and nine fractional ones is the whole of what it can need. An **accumulated
> operand** — the running total part-way through a sum, and the accounted total
> where it enters the projection — is bounded by nothing this ADR states, so its
> context is sized from the operand's **own representation**: the digit count and
> effective scale `as_tuple()` reports for the value in hand (the effective-scale
> clause below), never from §1's bound. Sized that way the context always
> succeeds, because every operand is a finite `Decimal` and a finite `Decimal`'s
> digits are countable before the operation. Sized from §1's bound instead, an
> implementation rounds, traps or refuses a valid large accumulator rather than
> returning and comparing it exactly — the failure §11's `1E19` fixture catches.
> The traps are therefore a backstop against a context that was not sized from its
> operands rather than a reachable state on well-formed input.

> **Normative.** A computed total has exactly **one** representation, so that two
> conforming implementations summing the same rows in any order state the same
> bytes on the wire (§5 carries a `Decimal`'s scale rather than normalising it, and
> ADR-0087 §4 makes two spellings of one number two values). The representation is
> the exact value at its **minimal non-negative scale**: as many fractional digits
> as the value needs and no more — none where it is an integer — and never a
> positive exponent; and its **sign is never negative**, so a total whose exact
> value is zero is `Decimal("0")` and never `Decimal("-0")`. Rows of `0.1`, `0.9`
> and `1` total `Decimal("2")` and never `Decimal("2.0")`, whatever order they were
> added in and however an implementation grouped them; rows of `Decimal("1E+1")`
> total `Decimal("20")` and never `Decimal("2E+1")`, which is where the
> no-positive-exponent half bites, since `Decimal("2E+0")` and `Decimal("2")` are
> one representation and not two — `as_tuple()` returns `(0, (2,), 0)` for both,
> so no rule can separate them and none here tries to.
> This governs a **result** — the accounted total and the projection — and no
> input: a declared or configured amount keeps the scale whoever wrote it chose.

> **Normative.** The sign clause is not decoration, and negative zero is the case
> it is stated for. `ToolCost` refuses a negative amount with `<`, and
> `Decimal("-0") < 0` is false, so `Decimal("-0")` is a reported cost a completion
> row may honestly carry and §1 classifies it as countable. Summing such rows,
> `Decimal("-0") + Decimal("-0")` is `Decimal("-0")` while
> `sum(rows, Decimal("0"))` is `Decimal("0")`: one number, two exact results, and
> §5 encodes them to `"-0"` and `"0"` — two spellings of one total on the wire,
> which is precisely what this clause forbids. So the total of a period whose
> rows are all negative zero is `Decimal("0")`, whatever an implementation seeded
> its accumulator with; §5's model refuses the other spelling at validation, and
> §11 drives it.

> **Normative.** A context is sized from the operands' **effective** scale, not
> from their raw exponents. `Decimal("0E-999999999999999999")` is countable under
> §1 — it is finite, its absolute value is below `1E15`, and its *value* needs no
> fractional digit — and an implementation that sized a precision from its
> exponent would demand one no machine can allocate for a sum whose exact result
> is the other operand. So an operand is reduced to the scale its value actually
> needs before it is added or compared: a zero coefficient contributes nothing
> whatever its exponent, and a value's trailing zeros below its last significant
> digit do not enlarge the context. This is §1's "a test on the number and not on
> its representation" carried into the arithmetic, and without it §1's bound
> guarantees nothing.

> **Normative.** A trapped computation is a **refusal** under admission and an
> **indeterminate** total under a read — the same fail-closed direction the rest
> of this section takes.

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
**aggregate** overrun of every call that was admitted before any of their
completions became visible, and each overrun is **recorded** — it lands in the
accounted total, refuses the next call, and is readable (§6). Under a single call
in flight that aggregate is the last admitted call's overrun of its own
declaration, which is the shape the bound is easiest to picture in; it is stated
over the set rather than over that one call because §3 records that more than one
invocation is in flight today (**#1561**), and ten concurrent calls declaring 10
each against a ceiling of 100 are all admissible at equality — if each then
reports 100 the accounted total is 1000, not the 190 the one-call reading would
predict. The reservation bounds what may be *admitted*; nothing bounds what a
declaration understated, and this is the second place that asymmetry shows.

**It also does not promise a bound across a clock that steps backward over a
period boundary, and §7 is where that comes from rather than this section.** A
completion is recorded at its own instant and rows do not move between periods, so
a clock that steps back across midnight selects a period whose rows exclude a
completion recorded after the step: a call completed and released just after
midnight is not in the total the step-back selects, a second call is admitted
against that total, and a later forward step puts both in one period. Carrying a
*reservation* across a boundary closes this for as long as the first call is
outstanding (§3), which is the whole of what the mechanism can do without
rewriting history. This is the survey's accounting corner taken in the honest
direction: the crossing call is counted, not excused, and this ADR says which of
the two properties it has rather than letting a reader assume the stronger one.

### 3. The admission is decided at the invocation seam, and the policy is left a pure function

> **Normative.** The admission is evaluated inside `ToolInvoker.invoke`,
> **before** ADR-0192's claim is appended and therefore before the callable is
> entered. A refused call reaches no callable, appends no claim, and appends no
> completion.

> **Normative.** It runs **after all three** of ADR-0029 §2's checks, in that
> section's own order and reordering none of them: the call is revalidated and
> detached; the definition on the detached copy matches the registry's original;
> `decision.authorises(request)` is re-evaluated on that same copy. Only then is
> `admit_invocation` called, and the estimate it is given is read off **that
> detached, checked copy** — never off the argument the caller passed.

> **Normative.** The admission is **not** a fourth member of ADR-0029 §2's
> enumeration, and that section stays exhaustive at three. §2 enumerates the checks
> that establish the call is the one the user authorised, each raising
> `ToolBindingError`; the admission establishes something else entirely, raises
> neither that class nor into that sequence, and is ordered *after* it the way any
> later obligation on `invoke` is. A reader holding only ADR-0029 implements those
> three binding checks correctly and completely; what they do not implement is an
> obligation **this** ADR states, which is an addition to `invoke`'s work rather
> than a change to §2's decision — ADR-0082 §1's stacked addition, and the same
> shape by which ADR-0192's claim append reaches `invoke` without replacing that
> enumeration either. No sentence of §2 becomes false, so no record is owed against
> it (§9), and no lane may read this clause as licence to add a fifth.

> **Normative.** The order is fail-closed in one direction and that is why it is
> marked rather than assumed. A `ToolCall` mutated after construction — the
> `__dict__` write ADR-0029 §2 puts inside the threat model — could carry an
> `UNKNOWN` cost the user never authorised; reaching the gate first, it would be
> refused as this ADR's `SpendUndeterminedError` when it is in fact ADR-0029's
> `ToolBindingError`, and the operator would be sent to a budget setting to repair
> a binding failure. A `ToolBindingError` therefore pre-empts every refusal in §4,
> and no lane may move the admission earlier to save a store read.

> **Normative.** The admission runs **inside the deadline `invoke` already
> enforces** — the required `timeout` of ADR-0029 §4, enforced by the seam and not
> by the caller. What that buys is §4's guarantee and **not a stronger one**: the
> seam stops waiting, not that the gate stops working. §4 states it in the weaker
> form deliberately — *"what it buys is that the seam stops waiting, not that the
> tool stops working. Python has no way to interrupt a coroutine that declines to
> be cancelled, so any stronger claim would be false"* — and this ADR claims no
> more for the admission than §4 claims for the callable. What this clause forbids
> is the thing that *would* be new: an implementation admitting **outside** the
> deadline has moved the one await §4 exists for out of its reach, in the window
> before the callable is even created, and `invoke(timeout=...)` then means less
> than it meant before this ADR.

> **Normative.** A deadline that expires during the admission is classified by
> ADR-0029 §4's **existing** rule, unchanged and unnarrowed: `FAILED` where the
> tool is not `side_effecting` or its `idempotency` is `NATURAL`, `INDETERMINATE`
> otherwise, read off the detached copy §2's step 1 captured. This ADR adds no case
> and relaxes none. **That classification is not this ADR's choice — it is the one
> ADR-0034 §1 assigns**, and it is quoted here rather than cited because the result
> is easy to mistake for a departure from that section:
>
> > *"Everything else that happens once `invoke` has been entered is outside this
> > rule, and that is a limit rather than an oversight. `ToolInvoker` exposes no
> > 'the callable was reached' fact and this ADR introduces none […]. So a
> > conforming `invoke` that suspends during its own pre-call work and is cancelled
> > there yields no fact about how far it got, and the executor must not manufacture
> > one. That case stays ADR-0029 §4's, with §4's classification:
> > `interrupted_outcome` on the trusted declaration, which answers `INDETERMINATE`
> > for a side-effecting non-`NATURAL` tool."*
>
> An admission blocked on its store **is** `invoke` suspended in its own pre-call
> work, and the expiry reaches it there as a cancellation. ADR-0034 §1 qualifies its
> `RUNNING → FAILED` rule on one of exactly two grounds — `invoke` was never
> entered, or the contract says the exit precedes the callable — and neither is
> available here: `invoke` was entered, and the expiry is not an *exit this seam
> raises* at all, so no contract proves where it landed. What the executor holds is
> a timed-out `invoke` and nothing about which await it expired in. Reading this
> ADR's own "the callable had not been created" as that fact would manufacture the
> reachability fact ADR-0034 §1 declines to introduce, which golden rule 5 makes a
> `ToolInvoker` change with a contract ADR of its own — a different lane, and the
> standing ground of **#234**.
>
> **This is therefore the case ADR-0034 §1 keeps, and it is not the case §4's
> refusal takes.** A raised `SpendCeilingError` *is* a pre-callable exit on that
> section's second ground and commits `RUNNING → FAILED` (§4); an expiry during the
> admission is not, and `INDETERMINATE` for a side-effecting non-`NATURAL` tool is
> both the assigned answer and the more pessimistic one, which is the direction
> ADR-0014 §4 refuses to guess against.
>
> What this ADR does add is that **no reservation survives it**: the expiry reaches
> the member as a cancellation, and §3's rule below removes a reservation whose
> handle will never be delivered.

> **Normative.** Where **neither ceiling is configured**, `admit_invocation`
> returns before it reads the clock, reads the store or performs any arithmetic.
> It cannot refuse in that configuration — not on a crossed ceiling, not on a
> raising clock, not on a failed store read, not on a trapped computation — which
> is what makes §1's "no ceiling configured means no ceiling" unconditional in
> fact and not only in wording.

> **Normative.** Where at least one ceiling is configured, the admission compares
> the projected total (§2) against each configured ceiling for the period that
> contains the invoker's current instant, and refuses where the projected total is
> **strictly greater** than a ceiling. A projected total exactly equal to a ceiling
> is admitted.

> **Normative.** An admission that is granted **reserves its own declared
> contribution**, in the same atomic step as the decision. The store read, the
> comparison and the reservation are one critical section over the holder's state,
> with no other admission interleaved **and no release taking effect inside it
> either**;
> `admit_invocation` returns an opaque **admission handle**; and the projected total of every later admission counts
> the declared amounts of the admissions this holder has granted whose handles are
> still outstanding. The Nth concurrent invocation therefore sees the N−1
> reservations already taken and cannot project a total that omits a call already
> admitted.

> **Normative.** Outstanding handles are **distinct**, and distinctness is tested
> on the **validated** `SpendAdmissionHandle` rather than on whatever a factory
> returned. `Identifier` strips, so `"h"` and `" h "` are two raw strings and one
> handle; an implementation checking uniqueness before construction would hold two
> reservations under one key. No value this holder has **ever delivered** as a
> handle is delivered again, whatever an injected id factory does — a repeated
> value is disambiguated rather than trusted, which is the rule
> `Engine._mint_handle` already states for the continuation table and for the same
> reason: two reservations sharing a handle are one reservation, so the other's
> amount silently leaves the projection and a later call is admitted against a
> total that omits an admitted one.

> **Normative.** Distinctness is over the holder's **lifetime** and not over the
> outstanding set, and the difference is load-bearing rather than tidy. A value
> re-minted after its first reservation was released is the worse case of the two,
> because the release rule below makes the damage silent: a second release of the
> retired handle is required to be a **no-op**, an implementation keying on the
> raw value alone cannot tell it from a release of the live reservation now
> carrying that value, and it drops the live one — after which a later admission
> projects a total omitting a call already in flight and admits spend the ceiling
> should have refused. Uniqueness among the outstanding set does not close that,
> so it is not what this clause says, and no lane may narrow it to the set on the
> ground that a retired handle "is not held any more". §11 drives it.

> **Normative.** The holder **mints** the handle; an injected id factory supplies
> candidate values and nothing more. A candidate `SpendAdmissionHandle` would
> refuse — a blank or whitespace-only string, a lone surrogate or any other
> unencodable value, a value of the wrong type — and a factory raising an
> `Exception` are each replaced by a value the holder generates itself. Neither
> reaches the caller and neither costs the call: the admission stands, its
> reservation is held, and a valid handle is delivered. This is the clause above
> carried from *collision* to *unusability* on the same ground — the factory
> supplies the opacity and the holder supplies the handle — and it strands no
> reservation, which the no-stranded-reservation clause below requires anyway.

> **Normative.** §4's `BaseException` exemption binds here as everywhere else, and
> the substitution above is over `Exception` alone. A `CancelledError` raised by
> the factory is a cancellation delivered inside `admit_invocation` and nothing
> else: it propagates unchanged, and the clause below removes any reservation
> already recorded before it leaves the member. An implementation that caught
> `BaseException` around the mint would swallow one, which §4 forbids in as many
> words.

> **Normative.** A factory failure is deliberately **not** a refusal. §4 enumerates
> `SpendUndeterminedError` over six grounds, each of them a way the spend the
> admission needed could not be reduced to a number, and a handle generator that
> misbehaved
> is none of them; raising one would tell the user a fact about their budget that
> nothing measured, which is the confusion §4 keeps two classes to prevent. Nor may
> the underlying error escape: §5 closes `admit_invocation`'s `Exception` set at
> two classes, and a `ValidationError` from constructing the handle, or a factory's
> own exception, would be a third. `Engine._mint_handle` lets a raising factory
> propagate one seam over because that member's failure set is open; this one's is
> closed, which is the whole of the difference.

> **Normative.** A reservation stands **until its handle is released**, and is
> counted into the projected total of every later admission until then —
> **whatever period either falls in**. It is not scoped to the period it was taken
> in and does not expire at a boundary. The completion it stands for is recorded at
> its own instant (§2) and a call admitted before midnight can complete after it,
> so a reservation that lapsed at the boundary would leave that call counted in
> neither period while it ran; carrying it counts the call in one period too many
> for as long as it is in flight, which is the fail-closed direction and is bounded
> by the call.

> **Normative.** No release **takes effect** between an admission's row snapshot
> and its reservation, and saying so is not pedantry: an implementation that
> serialised admissions against each other while letting a release land between an
> admission's row snapshot and its comparison admits a call it must refuse.
> Concretely — accounted 90, one reservation of 10, a ceiling of 100 — an admission
> snapshots 90, the first call's completion of 10 lands and its handle is released,
> and the admission then reads no reservation and projects 100 for a further
> estimate of 10, where the truth at that instant is 110. The reservation is the
> conservative stand-in for a completion the snapshot may not yet show — that is
> why dropping one inside a running admission is the single interleaving that can
> under-count, while the completion's own append, which this holder does not
> serialise against at all, cannot.

> **Normative.** `release_admission` therefore **never waits**, and it is
> deliberately *not* placed inside the admission's critical section to achieve the
> clause above. It records the release in the holder's own memory — an operation
> that touches no store, performs no I/O and cannot block — and a recorded release
> takes effect at the **start of the next admission's critical section**, before
> that admission's row snapshot. The property is preserved exactly as stated: no
> release is ever applied inside a critical section already running. What is
> removed is the wait.

> **Normative.** That is a liveness rule rather than a refinement, because the
> alternative contradicts the deadline clause above. The admission's store read is
> inside the critical section, so a gate blocked on a store that never answers
> holds it for as long as **its own** deadline allows. Were a release made to wait
> on that exclusion, a *second* invocation whose callable had already returned
> would block in its `finally` behind the first invocation's store I/O; the
> no-stranded-reservation rule below, which requires a cancelled release to
> complete its state change before re-raising, would hold it there through its own
> expiry, and its `invoke` would outlast the `timeout` its caller set — the one
> thing the deadline clause above promises this ADR does not do, and it would do it
> to an invocation that had already succeeded. A release that cannot block cannot
> do that, and it makes the no-stranded-reservation rule bounded by construction
> instead of conditional on another invocation's store. §11 drives both halves.

> **Normative.** A store read that **declines to be cancelled** is therefore not
> an exception to the clause above; it is the case ADR-0029 §4 already excludes,
> and this ADR neither widens it nor closes it. §4's third bullet decides it in as
> many words — *"A tool that suppresses its own cancellation can outlive its
> deadline, and no seam can prevent that … This is a genuine hole and the honest
> position is that it is unclosable from this side … not a claim that the deadline
> is a hard bound."* `permissions/audit.py`'s `_run_to_completion` is exactly such
> a read: ADR-0054 has it absorb a cancellation until the `sqlite3` worker
> physically finishes, because releasing the lock while the worker still holds the
> connection would let a second caller use it concurrently. A gate reading through
> that pattern over wedged SQL outlives the timeout, and §4 says so already.

> **Normative.** Nothing here is new, and the placement is what makes that
> checkable. ADR-0192's completion append already sits inside `invoke` over a store
> built the same way, so the admission's read is §4's third bullet one seam earlier
> rather than a new class of hazard, and no record is owed against §4 for meeting
> a case it enumerated. What this ADR does own it does: §11 requires the lane to
> drive the **primary** holder through `invoke` and through shutdown rather than
> only a cancellable fake, so which of §4's two sides the lane's read falls on is
> a stated and tested fact instead of an inherited default nobody looked at.

> **Normative.** `ToolInvoker.invoke` releases the handle in a `finally`, after
> ADR-0192's completion has been appended or after the failure that prevented it.
> A release is **idempotent** and raises no `Exception`: an unknown handle and a
> handle already released are each a no-op. A `finally` that raised would replace
> the call's own outcome with a book-keeping failure, which is the one thing this
> clause must not do.

> **Normative.** Neither member leaves a reservation nobody can release. Where
> `admit_invocation` has recorded a reservation and does not deliver its handle —
> a `CancelledError` between the two is the reachable case — it **removes that
> reservation before the exception leaves the member**. Where
> `release_admission` is cancelled, it completes its own state change first and
> re-raises afterwards. Both are the same rule: a `BaseException` propagates
> unchanged (§4), and it does not take a reservation's only key with it.

> **Normative.** A reservation is **in-memory state of the holder** — never a row,
> never durable, and never a `PermissionDecision`. It is discarded when the process
> restarts, which is the one way an unreleased reservation ever ends; §7's
> accounted total is rebuilt from ADR-0192's rows and loses nothing with it.
> Between the completion append and the release the same call is counted twice,
> once accounted and once reserved, and that direction is deliberate: the mechanism
> over-counts for one operation rather than under-counting for one.

> **Normative.** Where **neither ceiling is configured** no reservation is taken
> and the handle is a value the release accepts and ignores. The short-circuit
> above is unconditional and this clause does not qualify it.

> **Normative.** The instant that fixes the period is read from an injected
> `Clock` wrapped by `checked_clock` (ADR-0026), and no caller supplies it. A
> clock that raises refuses the call with `SpendUndeterminedError` (§4), as
> ADR-0029 §5's fail-closed reading of the same measurement requires.

> **Normative.** `ActionPolicy` is **unchanged**. It gains no ceiling input, no
> store handle, no clock and no member; `ActionPolicy.decide` stays a function of
> its argument; and ADR-0021 §5's floors, including the `UNKNOWN`-cost floor that
> sends such a tool to `CONFIRM`, are neither relaxed, satisfied nor duplicated by
> anything here.

> **Normative.** The **decision** reads exactly four things: the `ToolCost` handed
> to `admit_invocation`; §1's four settings with the `Settings.timezone` §1 exempts
> as the period selector; the **instant** read from the injected clock, which is
> what selects the period and whose failure is §4's third ground; and the rows and
> reservations the holder holds. Nothing else conditions it — not the calling subsystem, not the tool's identity, not a
> capability, not a protocol, and no **caller-controlled** value: there is no
> parameter, argument, header or configuration by which a caller obtains an
> invocation the ceiling would refuse, and no override, bypass or force flag exists
> to be reached for.

> **Normative.** The injected **id factory** is a dependency of the *handle* and
> not of the decision, and the two are counted separately for that reason. It is
> consulted only after an admission has been granted, no value it returns and no
> failure it has changes whether the call is admitted (§3's minting rule), and an
> implementation that let it reach the comparison would have made the outcome
> depend on a source of opacity. The inventory above is over the decision; this is
> the whole of what else the member touches.

> **Normative.** The `ToolCost` is not an exception to that and is the reason it is
> stated as four things rather than as "nothing from the request". It is the
> **pinned declaration** — the `cost` on the `ToolDefinition` the call's recorded
> `PermissionDecision` pins (§2), which ADR-0016 §5 binds to the tool id for the
> life of the process and ADR-0021 §2 freezes onto the decision — so a `FREE` call
> and a `PER_CALL` call *must* admit differently and do. What it is not is
> caller-supplied: the invoker reads it off the pinned definition and cannot
> substitute one, a turn cannot author it, and a tool cannot restate it between the
> ruling and the call. A prohibition written over "any value carried in the
> request" would have forbidden the one input the arithmetic is made of.

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

**Why the admission reserves, and the premise an earlier draft rested on that the
tree does not support.** The admission is a read followed by ADR-0192's claim,
which is a second operation, so two invocations whose admissions both run *before*
either claim lands could each project a total that does not include the other:
with an accounted total of 90, a ceiling of 100 and two declared estimates of 10,
both admissions read 90, both project exactly 100, both are admitted at equality,
and 110 leaves. An earlier draft of this section deferred that as **unreachable
today**, on ADR-0029 §7's sentence that "one executor runs at a time". **That
reading does not survive contact with the tree.** `Engine.converse` takes no lock,
`Engine._admit_and_reserve` is written for "the **Nth concurrent turn**" in its own
contract, and separate hub connections dispatch against one engine — so two
invocations are in flight and their admissions interleave today. What ADR-0029 §7
and ADR-0014 §7 defer is the *plan executor* — leases, parallel steps, recovery
across processes — and not the engine's turn concurrency, which arrived later and
bounds itself. Reading that sentence as a serialisation guarantee is filed as
**#1561**; a ceiling resting on it would be a ceiling resting on a premise its own
system contradicts.

**So the reservation is taken here rather than deferred, and it is the shape the
engine already uses.** `Engine._admit_and_reserve` bounds the confirmation table
the same way: admit and reserve in one step that cannot be interleaved, hand back
a handle, release it in a `finally`. This is that pattern one seam over, against a
number instead of a slot count, and it costs one member and no durable state.
§2's open-claim rule still does its own work — once a claim is appended the period
is indeterminate and a second admission is refused whatever the allowance says —
but the ceiling no longer depends on that rule to be sound.

**What is left is one process wider than a turn.** Reservations live in the holder
that took them, so two hub *processes* over one data directory would each keep
their own set. ADR-0083 puts one resident process per data directory, which is why
that is a scope-out (§8, #1553) rather than the same defect one level up — and it
is reopened by an ADR landing a second process, not by parallel execution inside a
turn, which this section now handles.

### 4. The refusal is a refusal, and it says why without saying what

> **Normative.** `core/errors.py` gains exactly three classes: `SpendError`,
> deriving from `AssistantError`, and two deriving from it —
> `SpendCeilingError` and `SpendUndeterminedError`. Each is a seam fault: raised,
> never returned as a `ToolResult`, and never auto-retried.

> **Normative.** A call is refused with `SpendCeilingError` where a **configured
> ceiling would be crossed** — and only then. It is refused with
> `SpendUndeterminedError` where the spend the admission needed **could not be
> reduced to a number**, on exactly six grounds: an amount the admission reads is
> not countable under §1; the call's own declared cost has no number at all, being
> an `UNKNOWN` basis or a cost in a currency other than `world_spend_currency`
> with no allowance configured (§2); the injected clock raised; the store read
> failed; the period is indeterminate under §2; or the arithmetic trapped. No other
> `Exception` escapes `admit_invocation`; a backend exception is translated rather
> than propagated, so `tools/` never sees a store's own error type.

> **Normative.** The six are evaluated in **that order**, after §3's no-ceiling
> short-circuit and before any comparison against a ceiling, and the **first** one
> that holds is the one the message names. Without a fixed order two conforming
> implementations meeting a non-countable amount and a raising clock in the same
> call would send the operator to two different repairs, each satisfying its own
> clause. The order is not arbitrary: the first two are facts about the call and
> need no I/O, so they are decided before anything is read; the clock precedes the
> store because the period is what selects the rows; indeterminacy is a property of
> rows already read; and a trap can only arise once operands exist. A crossing is
> knowable only last, so a `SpendCeilingError` never pre-empts a
> `SpendUndeterminedError` and a call that could not be measured is never reported
> as one that overspent.

> **Normative.** A `BaseException` that is not an `Exception` — a `CancelledError`
> delivered from outside, above all — is **propagated unchanged** and is never
> translated into either class. The enumeration above is over operational failures
> the seam decides; a cancellation is neither a refusal nor a budget fact, and
> ADR-0029 §4 and ADR-0031 already own how one is classified.

> **Normative.** The two are separate classes because their messages state
> different facts and one of them would otherwise be false. A ceiling refusal
> names the ceiling that was crossed; a refusal on a clock failure, a trapped sum,
> an open claim, an unpriced cost or an amount that is not countable crossed no
> ceiling at all, and reporting it as one would tell the user a number about their
> budget that nothing measured.

> **Normative.** The refusal is an exit **before the callable is entered**, so it
> falls in the window ADR-0034 §1 governs and qualifies on that section's second
> ground — the contract says the exit precedes the callable. The executor commits
> `RUNNING → FAILED` and never retries, on the window and not on a list of
> classes.

> **Normative.** The ceiling never produces a `CONFIRM`, never routes a question
> to the user, and no per-call answer overrides it. **What is closed is the
> direction, not a count: nothing a turn can reach lifts a refusal.** A later
> admission may nonetheless succeed where the same call was refused, and every way
> that happens is a change to what the arithmetic reads rather than an override of
> the decision: the configuration changed; the period rolled over; another call's
> reservation was **released** (§3); the ground under a `SpendUndeterminedError`
> ceased — an open claim gained its completion, or a store read or an injected
> clock that failed succeeded on a later attempt; or the rows themselves were
> erased by the user's `clear()` (§7), which resets the accounted total to
> `Decimal("0")`. None is reachable from inside a turn: the gate can neither record
> nor `clear` (§5), a turn cannot edit configuration or move the clock, and a
> release retires only a call the invoker itself admitted. The release is the one
> worth naming twice, because it is the only one that needs no act outside the
> mechanism: it is not a relaxation but the projection ceasing to count a call that
> is no longer in flight. A refused call retried after that release may be admitted
> in the same period under the same configuration, and that is the mechanism
> working: what refused it was a total including an in-flight call, and that call's
> own reported cost is what the retry is now measured against. (That a call *admitted* under the projection may still carry the accounted
> total past a ceiling, because its declaration understated it, is §2's stated
> overrun and not an override of a refusal: nothing was refused.)

> **Normative.** Neither class is a `PermissionDeniedError` and no lane makes
> either one.

> **Normative.** Where the projection crosses **both** configured ceilings, the
> refusal names **both**, in §5's fixed period order — `CALENDAR_DAY` then
> `CALENDAR_MONTH` — with each one's ceiling and accounted total. Neither is a
> precedence over the other, and no implementation picks one: naming only the day
> would tell a user to wait until tomorrow when their month is spent, and naming
> only the month would hide the nearer bound. One `SpendCeilingError` is raised
> whatever the count, and two conforming implementations state the same facts in
> the same order.

> **Normative.** Both messages are **payload-free**. A `SpendCeilingError` states
> the ceiling that was crossed, its period, its currency, the accounted total and
> the **projected** total that crossed it — the accounted figure alone would leave
> a user reading "90 against a ceiling of 100" beside a refusal and no way to see
> the reservations and the declaration that made 101 (§2, §3).
> A `SpendUndeterminedError` names **which of the six grounds above** applied — the
> first one that held, under the order above — and
> names the period only where one was determined — a clock that raised leaves no
> period to name, and the message says the clock failed rather than inventing one.
> It states no amount.

> **Normative.** Where the ground is an **indeterminate period** and **both**
> configured periods are indeterminate at once — a current-day open claim is in the
> month as well as the day — the message names **both**, in §5's fixed order,
> `CALENDAR_DAY` then `CALENDAR_MONTH`. This is the both-ceilings rule below applied
> to the other class and for the same reason: neither period takes precedence over
> the other, naming only the day would tell a user to wait until tomorrow when the
> month cannot be measured either, and an unfixed choice leaves two conforming
> implementations stating different facts about one refusal. It names only the
> periods that are **both** indeterminate and carrying a ceiling of their own,
> since §2 refuses on no other, and one `SpendUndeterminedError` is raised whatever
> the count. Neither carries an argument value, a recipient, an account,
> a tool output or a digest of any of them.

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

### 5. `SpendGate` and `SpendLedger`: two `core` Protocols, three `core` types, one holder

> **Normative.** `core/protocols.py` gains **two** Protocols. `SpendGate` has
> **two** `async` members:
> `admit_invocation(*, estimate: ToolCost) -> SpendAdmissionHandle`, which
> evaluates §3's admission, raises under §4 where it refuses, and where it admits
> takes §3's reservation and returns its handle; and
> `release_admission(handle: SpendAdmissionHandle) -> None`, which drops that
> reservation and is the idempotent, no-raising, **never-blocking** member §3
> requires — it awaits no store and no lock a store read is held under, which is
> §3's liveness rule and the reason it is `async` only for symmetry with the member
> beside it. Neither appends a row and neither
> writes durable state. `SpendLedger` has one member, **`async`** like the two
> above it and with exactly this signature:
> `async def spend_totals(self) -> tuple[SpendTotal, ...]`. It returns one
> `SpendTotal` per period this ADR defines, in a fixed order — `CALENDAR_DAY` then
> `CALENDAR_MONTH` — and returns both entries whatever is configured. It is `async`
> because it reads a store, which is `CLAUDE.md`'s rule for an I/O-bound method,
> and because §6's relaying `AssistantEngine` member is `async` for that reason and
> could not await a synchronous one without either blocking the loop or diverging
> from the signature it relays. Every member of both Protocols is awaited by the
> conformance suites and by every caller.

> **Normative.** `core/types.py` gains `SpendAdmissionHandle`, frozen with
> `extra="forbid"`, carrying exactly `handle: Identifier` and nothing else. It is a
> model and not a bare `str` because it crosses a subsystem boundary — `tools/`
> holds it, `permissions/` mints and resolves it — which is `CLAUDE.md`'s rule for
> boundary-crossing data, and because `Identifier` refuses the blank string that
> would satisfy "a handle is present" while naming nothing. `ContinuationToken` is
> the same shape for the same reasons one seam over, and this ADR copies it rather
> than inventing a second convention.

> **Normative.** The handle is **opaque**: a caller neither parses it, orders it,
> nor derives a period, an amount or a tool from it, and no implementation encodes
> one in it. It reaches no record, no surface and no wire frame — it lives between
> the invoker and the gate for the duration of one call — so nothing here promotes
> a new value onto ADR-0085's surface, and no adapter, engine or client ever holds
> one.

> **Normative.** `admit_invocation` takes a `ToolCost` and **no tool identity**,
> and that is §3's ratified decision rather than an omission: the admission is not
> conditional on which tool is calling, so the seam is given nothing it must not
> read. Two tools declaring the same cost are deliberately indistinguishable here.

> **Normative.** That is **not** the temporary signature ADR-0016 §5 refuses — "a
> contract whose author expects it to break is not a contract" — and the difference
> is that §8's per-tool ceiling is **declined on the merits**, not scheduled. §1
> gives the argument: such a ceiling partitions one budget rather than lowering it,
> the property people want from it is a rate limit the day ceiling already
> supplies, and it needs the keyed per-user store ADR-0016 §7 defers. This ADR does
> not expect it to land. If a later decision reopens it, widening this contract is
> that decision's to make and it is a breaking change with its own ratified ADR
> (golden rule 5) — which is the corpus's ordinary route and is what ADR-0016 §5's
> own registration case took when invocation landed. Pre-shaping the seam for a
> ceiling this ADR argues against would hand the gate an identity §3 forbids it to
> use, which is a worse contract than one that is narrow and says why.

> **Normative.** They are two Protocols because they have two consumers and
> neither needs the other's face: the invoker holds a `SpendGate` and **never** a
> `SpendLedger`, and the engine holds a `SpendLedger` and never a `SpendGate`. No
> implementation hands `tools/` a route to a totals projection, and none hands an
> adapter a route to an admission.

> **Normative.** `admit_invocation` raises exactly `SpendCeilingError` and
> `SpendUndeterminedError` under §4's division and no other `Exception`, subject
> throughout to §4's `BaseException` exemption — a `CancelledError` delivered from
> outside propagates unchanged, here as on every member below. Minting the handle
> adds no third class: an id factory that raises an `Exception`, or returns a value
> `SpendAdmissionHandle` refuses, is replaced by a value the holder generates (§3),
> so neither a `ValidationError` nor the factory's own exception reaches `tools/`.

> **Normative.** `release_admission` raises **no** `Exception` at all, under §4's
> same `BaseException` exemption. It is called from a `finally` whose call has
> already succeeded or already failed, and a member that could raise there would
> substitute a book-keeping failure for the outcome the caller was about to
> report.

> **Normative.** `spend_totals` derives **both** entries from **one** reading of
> the injected clock and **one** snapshot of the rows. A conforming implementation
> does not read the clock twice, and does not compute one period's total, let a
> completion append, and then compute the other's: a day total of 10 returned
> beside a month total of 0 states two facts that cannot both be true of one
> instant, and a clock read either side of a calendar boundary pairs periods that
> do not contain each other. The two entries are one observation of one moment.

> **Normative.** `spend_totals` **returns** an indeterminate period rather than
> raising on one — that state is `accounted=None` with `currency` present (below).
> It raises exactly `SpendUndeterminedError` among `Exception`s, and only where it
> cannot produce the values at all: a store read that failed or an injected clock
> that raised. A backend exception is translated rather than propagated, and §4's
> `BaseException` exemption binds here too.

> **Normative.** `core/types.py` gains `SpendPeriod`, a `StrEnum` with exactly two
> members, `CALENDAR_DAY` and `CALENDAR_MONTH`, and no ordering semantics. With
> `SpendTotal` and `SpendAdmissionHandle` below, that is three names in that module
> and no more.

> **Normative.** `core/types.py` gains `SpendTotal`, frozen with
> `extra="forbid"`, carrying exactly: `period: SpendPeriod`;
> `period_start: UtcInstant` and `period_end: UtcInstant`, `period_end` exclusive;
> `start_offset: timedelta` and `end_offset: timedelta`, the UTC offsets **the
> producer resolved** as in force at those two instants; `ceiling: Decimal | None`;
> `currency: EncodableText | None`; and `accounted: Decimal | None`. The bounds are
> the ones §1's rule computed for this value's `period` in the ledger's configured
> zone; that correspondence is a **producer** obligation checked by the conformance
> suite and the lane (§11), and deliberately not a validator on the model.

> **Normative.** **No zone name crosses the wire, and that is the decision rather
> than an omission.** An earlier draft carried the IANA zone the boundaries were
> computed in and had a renderer resolve it. That makes acceptance and rendering of
> a wire value depend on the **consumer's installed `tzdata`**: the frame would
> carry a zone *name* and not the rule-set that named it, so a hub on one revision
> and a client on another — over a zone whose transitions were revised, of which
> `Asia/Gaza` is the live example — disagree about the boundaries of the same civil
> day, and the client rejects or misrenders a value its producer computed
> correctly. ADR-0016 §2 forbids exactly that of a `core/types.py` semantic:
> intrinsic means "computable from the type's own declaration alone" and "the same
> answer for every consumer". A test suite running against one installed `tzdata`
> could not have caught it.

> **Normative.** The **offsets are the whole of what a renderer needs**, and
> carrying them is a retraction onto a type the encoding already carries rather
> than an addition to it: `timedelta` is in ADR-0087 §2c's table under §2e, so this
> ADR widens that enumeration by `Decimal` alone (§9) and by nothing else. A
> renderer prints each bound as that bound plus its own offset and labels it with
> that offset; it resolves no zone, reads no `tzdata` and consults no
> configuration. Two offsets rather than one because a period containing a
> transition has different offsets at its two ends — which is the case §1's
> boundary rule exists for — and a single offset would misrender exactly the
> periods that rule was written to get right.

> **Normative.** What is given up is stated: a reader of a `SpendTotal` alone
> cannot name the zone, only the offsets. That is accepted, because naming the zone
> is what created the dependency, and the surface that wants the name has it —
> `Settings.timezone` is the producer's own configuration (§1), readable where the
> ledger runs. A later decision that genuinely needs a self-contained civil label
> adds a producer-resolved one; no lane infers a zone back out of an offset, which
> is many-to-one and would be a guess.

> **Normative.** The model's **one** string field, `currency`, is
> `EncodableText`-based and **not** bare `str`, because ADR-0085 §4c binds every
> string the promoted surface can carry
> and `tests/core/test_text_encodability_coverage.py` admits no exemption — it
> discovers every `str` leaf on every model in `core.types` and fails the gate on
> one that is not wrapped. The currency validator below layers on that
> base rather than replacing it, which is what ADR-0085's header means by "the new
> member's text fields layer on it", and is how `ToolCost.currency` is already
> typed even though its own rule is the stricter one.

> **Normative.** Both instants are `UtcInstant` and never a bare `datetime`.
> ADR-0023 §2 makes that the type of every instant-valued field in
> `core/types.py`, `tests/core/test_instant_coverage.py` fails the gate on a bare
> annotation, and this ADR claims no exemption from either.

> **Normative.** The offsets are carried rather than assumed by a reader. The
> boundaries were computed in the *ledger's* zone, and a surface may be a client
> configured differently from the process that computed them; a renderer uses these
> fields and never its own configuration and never its own `tzdata`.

> **Normative.** Both offsets are **strictly within `±24` hours** and carry
> whatever resolution the zone database gives them — **seconds included, and not
> rounded to a minute**. `core/clock.py` already accounts for the historical
> offsets the tz database carries, naming `Asia/Manila`'s `-15:56:08` and
> `America/Metlakatla`'s `+15:13:42` as the widest; a whole-minute rule would make
> a `SpendTotal` unable to state the offset actually in force for a reading
> `checked_clock` accepts, leaving the producer to leak a validation failure,
> round the offset, or fail to return the value §6 promises. The `±24`-hour bound
> is strict and is the whole of the range rule.

> **Normative.** That is an **intrinsic** invariant in ADR-0016 §2's sense — decided
> from the field's own value, needing no zone database, the same answer for every
> consumer — which is the property the zone name could not have. Rounding, by
> contrast, would have been this model quietly disagreeing with the clock contract
> about what an offset is.

> **Normative.** `ceiling` is non-`None` only where `currency` is. `accounted` is
> `None` in exactly two states, which `currency` discriminates: where `currency`
> is `None`, no currency is configured and no total was computed; where `currency`
> is not `None`, the period is **indeterminate** under §2. No third meaning is
> assigned to the absence.

> **Normative.** `currency`, where present, carries `ToolCost.currency`'s rule and
> not a second one: exactly three uppercase ASCII letters, ISO-4217's alphabetic
> form, neither normalised nor checked against the live register (§1). A blank
> string, a lowercase code, a non-ASCII one and a wrong-length one each raise at
> validation. `EncodableText` is the base the field layers on and is **not** the
> whole of its rule: it admits `""` and `"usd"`, and a `SpendTotal` carrying either
> would state a currency §1 refuses as configuration and a renderer would print it.

> **Normative.** The two amounts carry their own numeric invariants, and they are
> **not the same one**. A `ceiling`, where present, is exactly what §1 admits as a
> configured ceiling: finite, greater than or equal to zero, and **countable** —
> it is the value the user configured and nothing computes it. An `accounted`
> total, where present, is finite and carries §2's **one representation** for a
> computed total rather than merely a value compatible with it — because it *is* a
> computed total, and a model that accepted a second spelling of one would accept a
> value this mechanism cannot produce and would put bytes on the wire that no
> conforming implementation states. Stated over `as_tuple()`: the sign is 0, the
> exponent is between `-9` and `0` inclusive, and where the exponent is negative
> the last digit is non-zero. So `Decimal("2")` and `Decimal("20")` construct while
> `Decimal("2.0")`, `Decimal("2E+1")` and `Decimal("-0")` each raise, and
> `Decimal("0")` is the only spelling of a zero total. `Decimal("2E+0")` is not a
> case: it and `Decimal("2")` are one representation, `(0, (2,), 0)`, so a
> validator cannot tell them apart and this clause does not ask it to. That
> subsumes the two invariants a reader would
> otherwise reach for — non-negativity, and at most **nine** fractional digits,
> which holds because every row contributing to it carries at most nine — and it is
> deliberately **not** bounded in magnitude: §1's predicate governs inputs and not
> results, and a total over rows nothing bounds may exceed `Decimal("1E15")`
> honestly. A model that accepted a negative ceiling, a non-countable ceiling, or a
> total in any representation other than the one above would state a fact this
> mechanism cannot produce, so each raises at validation.

> **Normative.** ADR-0087 §2c's scalar table gains one row, **`Decimal`**, and
> this ADR is where it is decided because this ADR is what puts one on the promoted
> surface. The table is exhaustive by construction — `wire/codec.py`'s projection
> raises `TypeError` for a type it does not list, "a type nobody has spelled a form
> for has no canonical bytes" — so without the row `spend_totals` cannot cross the
> wire at all. The gap is **older than this ADR**: `ToolCost.amount` is a `Decimal`
> today and a `PermissionDecision` carrying a `PER_CALL` cost already cannot be
> exported (**#1559**), which is the two-implementations-disagree shape #565 closed
> for a lone surrogate `str`. Nothing in the tree declares a `PER_CALL` cost, which
> is why it has not bitten.

> **Normative.** The form is a **JSON string**, never a JSON number. A number would
> be read back by a decoder through a binary float on the far side, which is the
> one thing §2's exact arithmetic forbids, and ADR-0087 §2c's `float` grammar is
> about a value that *is* a binary64 — this one is not.

> **Normative.** The encoding of a finite `Decimal` is determined by its own
> `as_tuple()` — `(sign, digits, exponent)` — and by nothing else. It is the
> **to-scientific-string** form of the General Decimal Arithmetic specification,
> stated here rather than named, because ADR-0087 §1's objection to "whatever
> `repr` does" applies to a library's `str` too. Let `adjusted` be
> `exponent + len(digits) - 1`.
>
> - Where `exponent <= 0` **and** `adjusted >= -6`, the form is **plain**. Where
>   `exponent` is 0 it is the digits alone. Otherwise a point is placed
>   `-exponent` digits from the right of the digits; where `adjusted` is negative
>   the digits are preceded by `0.` and by `-adjusted - 1` zeros.
> - Otherwise the form is **exponential**: the first digit, then a point and the
>   remaining digits *only if there are any*, then `E`, then `+` or `-`, then the
>   magnitude of `adjusted` in decimal with no leading zero.
> - A `-` precedes either form where `sign` is 1, **negative zero included**.
>
> Decoding is the inverse and reads the string back to the same triple. The
> normative vectors are `Decimal("1.50")` → `"1.50"`, `Decimal("1E15")` →
> `"1E+15"`, `Decimal("0")` → `"0"`, `Decimal("-0")` → `"-0"`,
> `Decimal("1.0000000000")` → `"1.0000000000"`, `Decimal("0.0000000001")` →
> `"1E-10"`, `Decimal("1.23E+7")` → `"1.23E+7"`, and
> `Decimal("0E-999999999999999999")` → `"0E-999999999999999999"`.
>
> The `1.23E+7` vector carries the exponential branch's **multi-digit** coefficient
> — "then a point and the remaining digits *only if there are any*" — which every
> other exponential vector here leaves untested, each having a one-digit
> coefficient. It is pinned to its **exact bytes** because round-tripping cannot
> catch the error it exists for: `Decimal("123E+5")` has the same
> `(sign, digits, exponent)` triple, so an encoder emitting `"123E+5"` reconstructs
> an indistinguishable value and passes every round-trip assertion while putting
> two spellings of one number on the wire.

**Verified rather than asserted, in the shape ADR-0087 §2c uses for its float
grammar.** This grammar reproduces CPython 3.14's `str` on every vector above and
on **200,000 pseudo-random finite decimals** — coefficients of one to thirty
digits, exponents drawn from ±40, both signs — with no mismatch, and
`Decimal(s).as_tuple()` returned the encoded triple on every one. So an
implementation may call `str` today and conform; what is *ratified* is the
grammar, and the vectors are what would catch an interpreter that stopped agreeing
with it.

**This is not a fourth row in ADR-0087 §3, and that was checked rather than
hoped.** §3's table is the exhaustive list of places the library and the ratified
bytes disagree. Measured on pydantic today, `model_dump(mode="json")` renders
`Decimal("1.50")` as `"1.50"` and `Decimal("1E15")` as `"1E+15"` — which is this
grammar — so there is nothing to disagree about, §3's three rows stay exhaustive,
and ADR-0084 §3's appended record of what that clause loses needs no
reconciliation. This is §3's own treatment of negative zero applied again: where
the library is right, the corpus ratifies it unchanged. An earlier draft of this
ADR spelled the value from `as_tuple()` directly (`"150E-2"`), which *would* have
been a fourth row, and it bought nothing the specification's own form does not.

> **Normative.** The scale is **carried and not normalised**, and that follows from
> ADR-0087 §4 rather than from taste: §4's relation is indistinguishability, not
> `==`, and `Decimal("1.0")` and `Decimal("1")` compare equal while `as_tuple()`
> tells them apart — so they are two values, and a spelling that mapped both onto
> one would normalise, which §4 forbids in as many words. Neither encoding nor
> decoding consults `decimal.getcontext()` and neither performs arithmetic, so
> §1's context-independence rule holds on the wire as it holds in the predicate.

> **Normative.** A **non-finite** `Decimal` — `NaN`, `sNaN`, or an infinity — has
> **no** encoding and the encoder raises, exactly as ADR-0087 §2c gives a
> non-finite `float` none and for the same reason. §1's validators and §5's make
> every `Decimal` this ADR puts on the surface finite already, so the refusal is a
> backstop rather than a reachable state.

> **Normative.** This is an **addition to §2c and a change to no byte any
> conforming encoder was emitting**: the projection raised on a `Decimal` before
> and encodes one after, so no ratified vector's spelling moves. The record it owes
> ADR-0087 is in §9 and §10.

> **Normative.** `PROTOCOL_VERSION` is bumped **once**, by the **consumer group
> §11 names**, and that one bump carries **two** independent ADR-0124 §9 grounds
> because that group makes both incompatible changes in one change. §11 already
> puts the codec entries and the promoted member in that group; this clause names
> the grounds so neither is read as unversioned.
>
> - **The codec's domain widens.** A peer at the new version may emit a `PER_CALL`
>   `Decimal` inside a `PermissionDecision`, and a peer at the old version refuses
>   it — ADR-0124 §9's first limb, "a frame a conforming peer at the new version
>   may send would be refused by a conforming peer at the old version".
> - **The promoted method set gains a member.** An old peer refuses an unknown
>   `spend_totals`, which is the same limb one surface out and is the ground
>   ADR-0186 §5 bumped on.

> **Normative.** ADR-0087 §8's first case is **absent and that is not a defence**,
> which is stated because the two rules are easy to conflate. §8's first case is
> about bytes *changing* for a value an encoder already emitted; no conforming
> encoder emitted any bytes for a `Decimal` before, it raised, so no ratified
> vector's spelling moves and §8's ground is genuinely not met. ADR-0124 §9's is,
> independently: it asks what a new peer **may send** that an old one refuses, not
> whether an old spelling moved. A lane reading ADR-0087's note as "no bump owed"
> and stopping there would ship the widened codec unversioned.

> **Normative.** **No lane splits the codec widening out of that group**, and this
> is the clause that forbids it rather than a matter of convenience. Landing the
> codec in an earlier change and the member in a later one creates a window in
> which a peer carrying the widened codec announces a version an old peer believes
> it understands — and ADR-0124 §9's "in the same change" would then oblige that
> earlier lane to bump on its own, making two bumps where the topology needs one.
> One change, one bump, both grounds.

> **Normative.** A `ToolInvoker` implementation holds a `SpendGate`. It acquires
> no `AuditTrail`, no `SpendLedger` and no additional store handle by this ADR,
> and the gate can neither record nor read a `PermissionDecision`, neither export
> nor `clear`.

> **Normative.** `app/composition.py` is the **sole constructor and sole wirer**:
> it builds the object, reads §1's four spend settings **and `Settings.timezone`**,
> injects the clock, and hands the
> invoker its `SpendGate` face and the engine its `SpendLedger` face. Those two are
> the only runtime holders. No subsystem constructs one, and no default is
> substituted where the composition root did not wire one.

> **Normative.** One object implements `SpendGate`, `SpendLedger` and ADR-0192's
> ledger seam, because all three read the same rows. Two stores keyed by the same
> rows could disagree about a total, which is the failure ADR-0016 §7 named for
> two registries, one seam over.

**A `None` accounted total is the right shape here, and it is not the optional
`ToolCost` ADR-0016 §4 refused.** That refusal was about a *cost* field whose
`None` had to be distinguished from **free** — two meanings collapsing into one
absence, in a field where a spend policy would read the absence as zero. Here
zero spend is `Decimal("0")` and is representable, so "the total is zero" never
reaches the absence at all. The absence carries two states rather than one, and
the clause above gives them a discriminator that is already on the model:
`currency` present means the sum was attempted and is not a number; `currency`
absent means no currency was configured and no sum was attempted. That is a
two-field read of the same kind ADR-0016 §2 obliges `permissions` to make of
`discloses` and `reversibility`, and it is stated on the type rather than left to
a consumer to infer. Both states are computed rather than stored, so nothing can
leave either one set.

**Two faces rather than one, and the split is ADR-0029 §1's argument one seam
over.** That section refused to hand every holder of a lookup the ability to
execute, and gave as its reason that "a consumer that only reads is one a test can
double without stubbing execution". The same holds here in both directions: an
invoker able to read a totals projection has acquired a permissions-owned history
it has no use for, and an adapter able to call the admission has acquired the
ability to spend a budget. `admit_invocation` takes the one value the invoker
holds that the store cannot derive — the declaration on the definition ADR-0029
§2's checks have already pinned. `spend_totals` has one caller, the engine
operation in §6.

**Why `SpendGate` has a second member and `SpendLedger` does not.** There is
deliberately no member returning "the amount remaining" and none that writes a
row. `release_admission` is neither: it retires a reservation §3 requires the
admission to take, and the pair exists because the alternative to a handle is a
gate that cannot tell which of several in-flight calls has finished. It is the
shape `Engine._admit_and_reserve` already uses for the confirmation ceiling —
admit and reserve atomically, hand back a handle, release it in a `finally` — and
it is deliberately *not* a durable reservation: nothing is appended, nothing
survives a restart, and the accounted total stays derivable from ADR-0192's rows
alone (§7). A second two-phase ledger beside ADR-0192's is the alternative this
declines, and Consequences records why.

**Two new Protocols, so they are a triad.** Contract, shared conformance suite
and canonical fake in `ai_assistant.testing`, in one change and never deferred
(`CONTRIBUTING.md` → "Adding a Protocol"), and under ADR-0137 §2 they ride with
their primary production implementation — the `permissions` store that also
satisfies ADR-0192's ledger, which is the consumer whose demands shape them. §11
is where that lands.

### 6. What the user sees

> **Normative.** `AssistantEngine` gains exactly one member, a read, with exactly
> this signature: `async def spend_totals(self) -> tuple[SpendTotal, ...]`. It
> relays `SpendLedger.spend_totals` and returns what it returns. It raises
> `SpendUndeterminedError`, and — as every member of that surface does —
> `OversizedValueError` under ADR-0085 §8, which this ADR does not lift and makes
> no claim about the reachability of: §1 bounds each amount and nothing bounds the
> number of rows, so an accounted total is not bounded and the declaration is a
> real one. No other **`AssistantError`** escapes it, and §4's `BaseException`
> exemption binds. It is `async` because the member it relays is I/O-bound, which
> is `CLAUDE.md`'s rule for one.

> **Normative.** That closed set is over this surface's own failure vocabulary and
> **not** over a transport's, which is stated because the two are easy to read as
> one. A hub-backed implementation — `HubClient`, and the `HubEngineClient` §11
> names — raises `HubUnavailableError` where no hub is listening or the connection
> goes away mid-request, and `ProtocolError` on a malformed or truncated reply.
> **Both reach the caller unwrapped**, and neither is a failure this member
> declares.

> **Normative.** They are not translated to `SpendUndeterminedError`, and that is
> the substantive half. §4 enumerates that class over six grounds, each of them a
> way *the spend* could not be reduced to a number; a connection that was not there
> is none of them, and reporting one as the other would tell a user a fact about
> their budget that nothing measured — the confusion §4 keeps two classes to
> prevent, one seam further out.

> **Normative.** This is not an exemption this member claims but the rule the
> surface already runs on, and it is copied rather than invented.
> `wire/errors.py`'s `TransportError` is "deliberately **not** an
> `AssistantError`: **no Protocol method declares one**, and a caller that catches
> `AssistantError` is catching the engine's failures rather than the wire's"
> (ADR-0085 §9). `recent_decisions` and `export_decisions` are in exactly this
> position and declare neither, and ADR-0186 §5 leaves the client's error mapping
> "derived from the Protocol" for the same reason. An adapter renders the two
> differently because they mean different things to a user, and §11 drives both
> paths so no lane closes the gap by translating.

> **Normative.** `interfaces/cli.py` gains exactly one command, and it is named
> here rather than left to the lane: **`spend`**, invoked as `assistant spend`,
> taking no argument and no option. A command's token is the whole of its public
> invocation contract — a user's script binds to it, and `spend`, `spending` and
> `spend-totals` would each satisfy a clause that only described the rendering — so
> the name is decided where the operation is. It follows the single-noun shape the
> surface already uses for a read (`beliefs`, `questions`, `conversations`) rather
> than the hyphenated form reserved for a verb on an object
> (`forget-conversation`, `export-decisions`). It renders
> that operation's `SpendTotal` values: each period, each bound rendered from the
> value's **own** `start_offset`/`end_offset` and labelled with that offset — never
> from the client's zone and never through the client's `tzdata` (§5) — its ceiling
> and currency where configured, and its accounted total. Where `accounted` is absent it
> renders which of §5's two states applies, reading `currency` to tell them apart:
> that no currency is configured and no total is stated, or that the period is
> indeterminate — and, where **that period's own** `SpendTotal.ceiling` is
> present, that no further call in that period will be admitted. Where the
> indeterminate period carries no ceiling the command says so and states no such
> consequence, because §2 refuses nothing on it; a renderer printing the line from
> the absence of `accounted` alone tells a user their calls are blocked when they
> are not.

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

> **Normative.** `AuditTrail.clear()` erases the rows, so after it every period a
> currency is configured for is determinate with an accounted total of
> `Decimal("0")`, and every period is otherwise unchanged — with no currency
> configured no total was stated before the erasure and none is stated after it.
> Nothing preserves a total across an erasure, and no lane adds a spend counter
> that outlives one.

> **Normative.** The ordering of `clear()` against an invocation whose claim is
> already appended is **ADR-0192 §6's** and is inherited unchanged: the erasure
> wins, and a completion whose claim was erased under it is refused. This ADR adds
> only the budget consequence, which is the one already stated above — the rows are
> gone, so the total is what the remaining rows say, and the spend of an erased
> invocation is not counted. No lane mints a marker, a generation or a carried-over
> amount to recover it, which would be the spend counter outliving an erasure that
> the clause above forbids.

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

> **Normative.** Each clause below states one thing this ADR does **not** decide
> and the condition that reopens it. Every one of them is marked, because ADR-0089
> §3 makes the marked set the whole of what a marked ADR obligates and a trigger
> stated in unmarked prose would bind nothing — the same reason §1, §2, §3 and §5
> each cite this section by number when they forbid a lane from adding the thing.

> **Normative.** **A default ceiling** is not decided. §1's "unset means unbounded"
> stands until **any priced invocation can execute with no per-call user act**, and
> that is the whole trigger: not a standing grant specifically, but the property. A
> standing grant is the route the corpus already names — the one ADR-0021 §6 defers
> and ADR-0148 §3's third clause reserves — and it is not the only one, because a
> `PER_CALL` tool declaring `discloses=()` sits outside ADR-0021 §5's floor, which
> binds only a **non-empty** `discloses`, so a policy may auto-`ALLOW` it with no
> standing grant in existence. Nothing in the tree declares a `PER_CALL` cost today
> (§5), so that route is open and unwalked; the first tool to walk it reopens this
> as surely as a standing grant does. No lane mints a default before either
> happens.

> **Normative.** **Per-tool, per-capability and per-protocol ceilings** are not
> decided, and no lane adds one under this ADR. Reopened by a decision that lands
> keyed per-user tool configuration — ADR-0016 §7's deferred "tool enablement and
> per-user configuration", which is the store such a ceiling needs — and by nothing
> else.

> **Normative.** **Currency conversion, and a ceiling over more than one
> currency**, are not decided, and no implementation reads an exchange rate (§2).
> Reopened by a decision that names a rate source, which is itself a world-reaching
> read and therefore has an egress question of its own before it has an arithmetic
> one. ADR-0016 §4 already rules conversion "out of scope entirely" and this ADR
> does not narrow that.

> **Normative.** **Model-provider spend** is not decided and enters neither total
> (§2). Reopened by either of two facts: an ADR bringing `models/` under the
> injected transport capability (#85, ADR-0017 §8's carve-out), or a ledger over
> model calls landing. Whether one ceiling then covers both axes is that ADR's
> question; this ADR bounds one axis and says which.

> **Normative.** **Reconciliation against a provider's bill**, and any surface by
> which a user corrects a reported figure, are not decided and no lane adds either
> here. ADR-0014 §7's deferral, restated by ADR-0029, and it stays there. Its
> consequence is stated rather than hidden: an unknown-priced completion with no
> configured allowance leaves its period indeterminate until the period rolls over,
> which refuses every further call in that period **while that period's own ceiling
> is configured** and refuses nothing where it is not (§2); the remedies are the
> allowance, a changed ceiling, and time.

> **Normative.** **Spend reservations across *processes*** are not decided
> (**#1553**). §3's reservation closes the admission race inside one process, which
> is where it is reachable (#1561); a second hub process over one data directory
> would keep its own reservation set and see none of the first's. ADR-0083 puts one
> resident process per data directory, so this stays out of scope while that rule
> stands, and it is reopened by the ADR that lands a second one — which owes either
> a durable reservation or an admission folded into ADR-0192's own atomic append.
> Parallel execution *inside* a turn does **not** reopen it: §3 already handles
> that.

> **Normative.** **Money a tool moves** is not decided and no ceiling here bounds
> it. ADR-0016 §7's transacted-cost deferral, untouched: the price of a flight
> lives in a call's parameters, and pricing it needs the parameter-level policy
> ADR-0016 §4 declined to invent.

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

**ADR-0087 §2c's scalar table — partially superseded.** §5 adds a `Decimal` row to
it and states the form, the vectors and the non-finite refusal. A reader holding
only ADR-0087 refuses to encode a `Decimal`; a reader holding this ADR encodes
one, which is ADR-0070 §1's test — "a change to what was decided is anything a
reader would act on differently" — coming out on the supersession side, so this is
a **partial supersession** and not an amendment (§10). The scope replaced is
exactly §2c's enumeration of the types this encoding carries; **no existing row's
spelling moves**, and ADR-0087 §8's first case therefore does not apply: no
conforming encoder emitted any bytes for a `Decimal` — it raised — so no protocol
version bump is owed **on this ground**, though the consumer group bumps anyway for
its promoted method. **Three clauses of ADR-0087 fall inside the replaced scope and not one**, because
each of them states the enumeration from a different side and a reader acting on
any of them acts differently now. §2c's table is the enumeration itself. §6's
sentence inventories "the scalar types the promoted surface reaches" and omits
`Decimal` — an omission that was **already** inaccurate, since `ToolCost.amount`
reaches that surface today (#1559), and one this ADR makes decisive. §9's first
bullet says "§2 gives **two** values no encoding — a lone surrogate `str` and a
non-finite `float`"; after this ADR there are three, the non-finite `Decimal` §5
refuses. What §9's *open problem* does not gain is a case: every `Decimal`-typed
field on the promoted surface refuses a non-finite value at validation —
`ToolCost`'s model validator does, and §5's does — so the gap that bullet is about
stays exactly as wide as it was.

**§3 is outside the scope, measured rather than assumed.** Its table is the
exhaustive list of disagreements between the library and the ratified bytes, and
§5's grammar is what `model_dump(mode="json")` already produces, so no fourth row
arises and ADR-0084 §3's appended record of that clause's losses is untouched.
§2a, §2b, §2d, §2e, §4, §5's existing vectors, §7's boundary and §8 itself are
untouched and stay accepted.

**ADR-0029 §7's "one executor runs at a time".** Not changed by this ADR and not
relied on by it. §3 records that the sentence decides the *plan executor* ADR-0014
§7 defers and does not describe the engine's turn concurrency, which is reachable
today; the correction is filed as **#1561** and the record it owes ADR-0029 and
ADR-0014 belongs to whoever takes that issue, not here. What this ADR does is stop
depending on the reading: the admission reserves rather than assuming it is alone.

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
dated note on ADR-0021, per ADR-0082 §2 — and ADR-0021's `Status` line **is** led
by `Partially superseded by` (ADR-0193, merged 2026-08-25), so §2 puts the record
in the note alone and no qualifier is added to that line. This ADR's own record on
ADR-0021 is written in that shape.

**ADR-0029 §7 — a record is owed, on the same reading.** The bullet's second half
defers spend accumulation and gives a precondition ADR-0192 satisfies. Same test,
same answer, same form: a `Status` qualifier and an appended dated note, or the
note alone where §2 excludes the qualifier.

**ADR-0087 §2c — a partial supersession, and not an amendment.** The table
enumerates the types the encoding carries, and `wire/codec.py` refuses one it does
not list; after this ADR it carries one more. ADR-0070 §1 admits an in-place
amendment "only when the amendment changes no decision" — a reader would act
**identically** before and after — and that is not this: before, a reader refuses
to encode a `Decimal`; after, they encode it by a rule stated here. That the
existing rows are untouched does not make the enlarged domain an amendment, and
the argument that "nothing §2c decided is reversed" was the wrong test — §1's is
whether a reader acts differently, not whether an old sentence became false. So
this ADR **partially supersedes** ADR-0087, in ADR-0070 §3's first-class form.
The named scope is the enumeration of the types the encoding carries **wherever
ADR-0087 states it** — §2c's table, §6's inventory of the scalar types the
promoted surface reaches, and §9's count of the values §2 gives no encoding — and
every other clause stays accepted, §3's exhaustive three included (§9 above states
why that one is outside the scope rather than merely unmentioned). The record is ADR-0070 §4's status form
on ADR-0087 — a leading `Partially superseded by` naming this ADR and the exact
scope — plus an appended dated note, and ADR-0087's ratified text is not
rewritten.

**Everything else in §9 is a stacked addition and no record is owed.** ADR-0021
§5, ADR-0016 §§3–4, ADR-0029 §§1–5, ADR-0034 §1, ADR-0177 §1, ADR-0186 §6 and §8:
for each, every sentence stays true and the obligation this ADR adds is stated
here. ADR-0082 §1 is explicit that a record demanded on book-keeping grounds
alone — that a list "should mention" a change — is not owed, and none is taken
here.

**This ADR supersedes one enumeration and withdraws nothing.** It partially
supersedes ADR-0087's enumeration of the types the wire encoding carries, in the
three clauses that state it — §2c, §6 and §9 — which is the one place where
carrying its own decision means a reader of an earlier ADR must now act
differently. Otherwise it adds `core` surface, discharges two deferrals, and names
the ADRs it depends on rather than replacing them.

### 11. Two lanes, what each owes, and what both are sequenced behind

> **Normative.** The **paired lane** lands `SpendGate` and `SpendLedger` as a
> triad — both Protocols, a shared conformance suite for each, and canonical fakes
> in `ai_assistant.testing` — together with the `SpendTotal`, `SpendPeriod` and
> `SpendAdmissionHandle` types, §4's three error classes, §1's four **new**
> settings — it adds no fifth and changes none that exists — and the **primary
> production implementation**, which is the `permissions` store that also satisfies
> ADR-0192's ledger. That is the whole of it: it lands under ADR-0137 §2's pairing
> and under §3's rule that a triad is never split.

> **Normative.** Every other consumer is a **follow-on lane**, briefed only after
> the paired lane has merged and against its merged text, which is ADR-0137 §4.
> The invoker's call to `admit_invocation`, the composition-root wiring, the
> `AssistantEngine` member and the CLI command are **one consumer group**: each is
> adaptation to a contract already landed, none carries substantial new machinery,
> and they draw one class of finding, which is ADR-0137 §4's own grouping test.

> **Normative.** That group **extends `ToolInvoker`'s own triad in the same
> change**, because it changes what `invoke` observably does: every implementation
> consults a `SpendGate` before the claim, releases its handle in a `finally`, and
> newly raises `SpendCeilingError` and `SpendUndeterminedError` out of the
> pre-callable window. The `ToolInvoker` Protocol's documented failure set, the
> shared `ToolInvoker` conformance suite, the canonical `FakeToolInvoker` in
> `ai_assistant.testing` and the concrete implementation move **together**, which
> is ADR-0137 §3's rule that a triad is never split. A change that taught only the
> concrete invoker would leave a consumer passing against a fake that admits what
> production refuses.

> **Normative.** The `ToolInvoker` suite drives, over a gate fake: a refused
> admission reaching **no** callable, appending no claim and no completion; the
> handle released on the admitted path after the completion, on the raising path,
> and under a cancellation delivered inside the callable; and a
> `release_admission` that is never called twice for one admission by the invoker
> even though the gate must tolerate it.

> **Normative.** That gate fake **records its arguments**, and the suite asserts
> the invoker forwarded the **pinned definition's own** `ToolCost` — the object on
> the revalidated, detached copy ADR-0029 §2's checks produced — unchanged, for a
> `FREE` definition, a `PER_CALL` one and an `UNKNOWN` one. Without it an invoker
> passing `FREE` for a registered `PER_CALL` cost of 20 lets the callable begin at
> an accounted total of 90 against a ceiling of 100 and still passes every clause
> above, because those assert refusal and release and never look at what was
> handed over. The suite also asserts the estimate is not read from the caller's
> argument: with the argument mutated after construction, the call fails ADR-0029's
> way and the gate is never reached (§3).

> **Normative.** That group carries the **whole** of the promoted surface's
> topology, because widening `AssistantEngine` breaks every implementation of it at
> once: the loopback `HubEngineClient`'s forwarding member, `HubClient`'s, the
> dispatch and codec entries the operation needs, and the **`PROTOCOL_VERSION` bump
> in the same change** that ADR-0124 §9 requires of any change to the promoted
> method set. ADR-0186 §§5 and 11 are the worked precedent for exactly this
> topology, and a lane that changes only the concrete engine and the canonical fake
> leaves the loopback client failing its own conformance suite.

> **Normative.** The browser gets nothing from that group. §6's operation is not
> one of ADR-0177 §1's thirty, and no gateway route, argument or call is added for
> it.

> **Normative.** The `AssistantEngine` widening carries its own triad obligation in
> that same change: the shared `AssistantEngine` conformance suite and the
> canonical `FakeAssistantEngine` gain `spend_totals` alongside the Protocol
> member, and that suite drives an oversized result to `OversizedValueError` as it
> does for every other member of the surface. A Protocol change extends its triad in the change that makes it, and
> ADR-0137 §3 forbids splitting that.

> **Normative.** Both lanes are sequenced **after** ADR-0192's implementation has
> merged. They read the completion rows and the open claims that ADR lands and
> cannot be written against a record that does not exist.

> **Normative.** The conformance suite pins the clock and drives at least: a
> projected total exactly equal to a ceiling, admitted; one cent over, refused; a
> `FREE` call admitted with the accounted total already at the ceiling; an
> `UNKNOWN` estimate refused with no allowance configured and admitted at the
> allowance with one; an `UNKNOWN` completion making the period indeterminate and
> the next call refused **where no allowance is configured**, and the same
> completion leaving the period **determinate** at the allowance where one is; a
> **reported `FREE` completion**, which contributes **zero** and leaves both totals
> determinate and unchanged, with the next admission using that zero — an
> accumulator treating every completion carrying no amount as `UNKNOWN` passes the
> declared-`FREE` and reported-`UNKNOWN` fixtures beside it, then makes the period
> indeterminate and blocks a call nothing should have blocked; a
> completion whose outcome is **`INDETERMINATE`** carrying a countable `PER_CALL`
> cost, which is **counted** — asserted in `spend_totals` *and* in the next
> admission, since an accumulator filtering that outcome out reports zero for a
> call the provider charged for and admits spend past the ceiling, and §2's rule
> that no row is excluded "because the act may not have happened" is exactly what
> it would be violating; an
> **open claim** making the period indeterminate whatever the allowance is
> set to and whatever its decision declared, including the case where the
> completion append itself failed; a foreign-currency cost taking the `UNKNOWN`
> path; a period rollover clearing an indeterminate total; both ceilings configured
> with **only the day ceiling** crossed, and again with **only the month ceiling**
> crossed while the day total stays under its own — the second is what catches an
> implementation that checks one ceiling and stops; a reporting currency configured with no
> ceiling, where a total is stated and **nothing is refused even while the period
> is indeterminate**; and no currency configured at all, where no total is stated.

> **Normative.** The suite drives §2's per-period indeterminacy where the two
> periods **disagree**, since every other indeterminacy fixture here puts the
> unmeasurable row in the current day and makes both periods indeterminate at
> once: an unpriced completion in an **earlier** day of the current month, with
> only the **day** ceiling configured. The month is indeterminate and the day is
> not, the call is **admitted**, and `spend_totals` states the month's `accounted`
> as `None` beside the day's figure. It drives the mirror with only the **month**
> ceiling configured, where the same row refuses. The CLI is driven on the first
> fixture too: the indeterminate month entry carries `ceiling=None`, so §6's "no
> further call will be admitted" line is **absent** there and present on the
> second — a renderer printing it from the absence alone tells a user their calls
> are blocked when they are not.

> **Normative.** The suite drives the boundary cases §1's period rule exists for,
> on real IANA zones: a civil date whose midnight is **repeated** across a backward
> transition, one whose midnight **does not exist** across a forward transition,
> and one that is **skipped whole** — with a row placed on each side of the
> selected instant. For the third, what is asserted is what the Protocol can
> observe: `spend_totals` selects a period from the current instant, and no instant
> selects a skipped date, so the suite pins the two **adjacent** daily periods and
> the single boundary they share, which is the observable consequence of the
> skipped date's period being zero-length. It also places a completion **exactly on**
> a shared boundary and asserts it contributes to the **following** period and not
> to the one that ends there, which is §1's half-open `[start, end)` rule and the
> one thing a row placed only on each *side* of a boundary never tests: an
> implementation comparing `recorded_at <= period_end` passes every before/after
> fixture here, counts a midnight completion in both periods, and refuses a call
> that should be admitted. A suite that exercises only UTC does not
> discharge this clause.

> **Normative.** The suite pins each refusal to its class under §4: a crossed
> ceiling to `SpendCeilingError`, and **five** of the six undetermined grounds — a
> non-countable declared amount, a declared cost with no number at all (an
> `UNKNOWN` basis and, separately, a foreign-currency one, each with no allowance
> configured), a raising clock, a failed store read and an indeterminate period —
> each to `SpendUndeterminedError`, with the message
> asserted to name **which** ground. The two unpriced cases are the ones a suite
> written before §4's second ground existed would leave classed as a crossing, and
> the assertion that they are *not* `SpendCeilingError` is the point: nothing measured
> a ceiling. It also asserts that no backend exception type escapes either member,
> while a `CancelledError` delivered during either member propagates unchanged.

> **Normative.** The lane drives the trap on the **read** side too, and the two are
> not one fixture: `spend_totals` must return the affected periods as
> **indeterminate** — `currency` present, `accounted=None` (§§2, 5) — and not raise.
> An implementation translating a trap correctly inside `admit_invocation` can
> still leak the `decimal` exception out of `spend_totals`, or raise
> `SpendUndeterminedError` from it, and pass every admission-side trap assertion.
> §5 permits that member exactly one raised class and only where it cannot produce
> the values at all; a trapped sum is not that case, because the other period's
> figure is still computable.

> **Normative.** The sixth ground, a **trapped computation**, is the *lane's* to
> drive and not this suite's, and that follows from §2 rather than leaving a gap.
> §2 requires a context sized from its own operands, under which the traps are "a
> backstop against a context that was not sized from its operands rather than a
> reachable state on well-formed input" — so no input this suite can supply through
> the Protocol makes a **conforming** implementation trap, and an obligation stated
> here would either pass vacuously or force the suite to reach past the Protocol
> into an implementation's arithmetic, which is the coupling a shared conformance
> suite exists to avoid. The lane therefore drives it at a fault-injection point it
> owns — the seam its own summation goes through — and asserts exactly what this
> suite asserts of the other five: `SpendUndeterminedError`, and a message naming
> the trapped computation as the ground. §4's enumeration stays at **six**: the
> class is what an implementation raises when its own sizing is wrong, and dropping
> the ground because no well-formed input reaches it would leave that case
> unclassified — which is the failure §4 keeps two classes to prevent.

> **Normative.** The suite drives §4's **order** with fixtures where two grounds
> hold at once, because each ground's isolated test passes under either order and
> the messages send an operator to different repairs: a non-countable declared
> amount **and** a raising clock, which must name the amount; a raising clock
> **and** a failed store read, which must name the clock; a failed store read
> **and** an indeterminate period, which must name the store; and an indeterminate
> period **and** a projection that would also cross a ceiling, which must raise
> `SpendUndeterminedError` and not `SpendCeilingError`. The last is what stops an
> implementation from reporting an unmeasurable period as an overspend.

> **Normative.** It drives the two **adjacent** pairs as well, which the fixtures
> above skip and which are the easiest order to get wrong because both grounds are
> facts about the same estimate: grounds **1 and 2** together — a cost in a currency
> other than `world_spend_currency` whose amount is *also* not countable,
> `Decimal("1E15")`, with no allowance configured, which must name the amount and
> not the currency; and grounds **2 and 3** together — an `UNKNOWN` estimate with no
> allowance beside a clock that raises, which must name the unpriced cost and not
> the clock. An implementation checking the currency before the magnitude passes
> every fixture above and fails the first; one reading the clock before it looks at
> the estimate at all fails the second.

> **Normative.** The suite drives §3's short-circuit: with **neither** ceiling
> configured, a raising clock, a failed store read and an indeterminate period each
> admit rather than refuse, because `admit_invocation` returned before it consulted
> any of them.

> **Normative.** The suite drives §3's reservation as a **race**, because that is
> the property and a sequential case cannot show it: two admissions are driven
> concurrently against one gate with no claim, completion or release between them —
> an accounted total of 90, a ceiling of 100 and two declared estimates of 10 — and
> exactly **one** is admitted, the second refused with `SpendCeilingError`.
> Releasing the first's handle and driving the second again then admits it. A suite
> that drives the two admissions in sequence with a release between them passes
> against an implementation that reserves nothing, and does not discharge this
> clause.

> **Normative.** The suite drives `release_admission` as the no-raising member §5
> requires: an unknown handle, a handle already released and a handle taken while
> no ceiling was configured each raise nothing and leave the projection where it
> was; a live handle released **after** its period rolled over still drops its
> reservation, because §3 does not expire one at a boundary; and a release does
> **not** lower any accounted total, which is read from rows.

> **Normative.** The suite drives handle **distinctness** with an id factory that
> returns one value repeatedly: two admissions granted against an accounted total
> of 70 and a ceiling of 100 at estimates of 10 each receive handles that are not
> equal, releasing one leaves the other counted, and a third estimate of 20 is
> refused while both stand. A suite driving only the single-admission race passes
> against an implementation whose second reservation overwrote its first.

> **Normative.** It drives the **retired-value** case the outstanding-set reading
> would let through, which the clause above cannot reach because it never releases
> before the second admission: the same repeating id factory, a first admission
> granted **and released**, a second admission granted — whose handle is asserted
> not equal to the first's — and the **first** handle then released a second time.
> That stale release is a no-op: the second reservation still stands, and an
> estimate that fits only without it is refused. An implementation minting unique
> values only among outstanding handles, and keying reservations on the raw value,
> passes every distinctness clause above and drops a live reservation here.

> **Normative.** It drives the same with a factory whose values collide **only
> after validation** — `"h"` then `" h "`, and a value differing only by a Unicode
> space `Identifier` strips — asserting the same three outcomes. An implementation
> comparing raw factory output passes the clause above and fails this one, which is
> the whole reason it is stated separately.

> **Normative.** It drives §3's minting rule with factories that **fail** rather
> than collide, because a closed exception set is only closed if the suite tries to
> open it: a factory returning `"   "`, one returning a lone surrogate, one
> returning a non-`str`, and one that **raises** an `Exception` of its own. In each
> case `admit_invocation` returns a valid `SpendAdmissionHandle` — no
> `ValidationError` and no factory exception escapes, and §5's two classes stay the
> whole of the member's `Exception` set — and the reservation it stands for is both
> counted in the next projection and released by that handle. A suite driving only
> factories whose values validate leaves the one path on which a `ValidationError`
> reaches `tools/` untested, and an implementation that passed the factory's output
> straight into the model fails here and nowhere else.

> **Normative.** It drives the `BaseException` half of that rule in the same place,
> because a substitution written over `BaseException` passes every case above and
> is wrong: a factory raising `CancelledError` propagates it **unchanged** out of
> `admit_invocation`, no handle is returned, and the later projection counts no
> reservation for that call — §3's cancellation rule asserted on the projection and
> not on the exception alone, at the one boundary the mint adds to it.

> **Normative.** The suite drives a refusal **lifted by a release**, which §4
> names as the one way a refusal clears with no act outside the mechanism: an
> accounted total of 90, a ceiling of
> 100, an outstanding reservation of 10 and an estimate of 1 refused at 101; the
> outstanding handle released; the same estimate admitted in the same period under
> the same configuration. It asserts the `SpendCeilingError` from the first attempt
> states the **projected** figure that crossed and not only the accounted one.

> **Normative.** It drives the **other** ways §4 says a refusal clears, each as a
> refused call retried and then admitted, because an enumeration nothing exercises
> is where a wrong one hides: the ceiling raised in configuration; the clock
> advanced past the period boundary; an open claim gaining its completion, which
> ends the `SpendUndeterminedError` §2's indeterminacy caused; and a store read and
> an injected clock that raised once and succeed on the retry. Each is driven
> through the suite's own fixtures — the configuration, the clock and the rows —
> and none through a tool call, which is §4's point that no route from inside a
> turn reaches any of them. The sixth way, erasure, is the lane's rather than the
> suite's, because `clear()` is `AuditTrail`'s member and not one this suite's
> Protocols expose; it is driven below.

> **Normative.** The suite drives a gate that **stays blocked** past the caller's
> deadline, over a fake that is **cancellation-cooperative by construction** —
> which is what makes the assertion one about the seam rather than about ADR-0029
> §4's excluded case (§3), and is stated because a fake built on a thread or a
> shielded wait would make the clause untestable rather than failing it:
> `admit_invocation` awaiting a store that never answers, `invoke` given
> a short `timeout`, and the call returning a classified `ToolResult` within it
> rather than hanging — `FAILED` for a non-`side_effecting` tool and for a
> `NATURAL` one, `INDETERMINATE` for a side-effecting non-`NATURAL` one, which is
> ADR-0029 §4's rule unchanged. It asserts the callable was never created and that
> the later projection counts no reservation. A suite whose gate fake always
> answers leaves the one window where a new await sits outside the deadline
> untested.

> **Normative.** The suite drives the deadline as **one** window shared by the
> admission and the callable, which the blocked-gate clause above does not reach:
> a gate that consumes more than half the `timeout` and less than the whole of it,
> and a callable that then does the same — each inside the deadline on its own,
> together past it. It asserts that `invoke` expires at the **single original
> deadline**, measured from where the caller's `timeout` began and not restarted
> when the admission returned, and that the result carries ADR-0029 §4's
> classification for that expiry. An implementation giving the admission its own
> fresh window and the callable another passes the never-answering-gate clause
> above — that gate expires inside the first window — and then returns this call
> **successfully** at nearly twice the deadline the caller set, which is
> `invoke(timeout=...)` no longer meaning what §3 says it still means.

> **Normative.** The suite drives outstanding reservations of **unequal** amounts,
> because every multi-reservation fixture above uses estimates of 10 each and an
> implementation holding a reservation *count* and reusing one amount passes them
> all: reservations of 1 and 9 against a ceiling of 15, where a further estimate of
> 6 projects 16 and is **refused** — the count-and-reuse implementation projects 8
> and admits. It then releases each handle in turn and asserts that only that
> handle's own amount leaves the projection, which is the second half of the same
> property and the one a single release cannot show.

> **Normative.** The suite drives the release **race** §3's take-effect rule exists
> for: an admission paused after its row snapshot, the outstanding call's
> completion appended and its handle released while that admission is paused, and
> the admission then resumed. It asserts **both** halves of that rule — the release
> returns *without waiting* for the paused admission, and its effect is *not*
> applied to it. Accounted 90, reservation 10, ceiling 100, second estimate 10: the
> second is **refused**, because the snapshot of 90 still carries the reservation
> of 10 standing in for the completion just appended, and 90 plus 10 plus 10 is
> 110. An implementation that applies a release inside a running admission passes
> every race and double-count fixture above and admits it.

> **Normative.** The suite drives §3's liveness rule with **two** invocations,
> which the single blocked gate above cannot reach: one whose `admit_invocation` is
> blocked inside the critical section on a store that never answers, and a second,
> already admitted, whose callable has returned and which releases its handle while
> the first is still blocked. The release returns promptly and the second `invoke`
> returns within its **own** `timeout`, unaffected by the first invocation's store
> and by the first invocation's deadline. It drives the same with the second
> invocation's release **cancelled** while the first is still blocked, and asserts
> that it still drops the reservation and re-raises without waiting. An
> implementation that serialises releases behind admissions passes every fixture
> above this one and returns late on both.

> **Normative.** The suite drives §3's cancellation rule at **both** boundaries and
> asserts on the projection rather than on the exception alone: a `CancelledError`
> delivered inside `admit_invocation` after it would have reserved leaves the later
> projection unchanged — no reservation nobody holds a handle for — and one
> delivered inside `release_admission` still drops the reservation. In both the
> `CancelledError` propagates unchanged, which is the assertion that is *not*
> sufficient on its own.

> **Normative.** The suite drives a reservation **across a period boundary** with
> the invocation still outstanding: a call admitted late in a day, the clock
> advanced past midnight, and the reservation still counted in the next admission's
> projection whichever period it falls in; then released, and no longer counted.
> It drives a backward step **within one period** as well, which the boundary case
> below never reaches: a completion of 90 recorded at 15:00, the clock stepped back
> to 10:00 **the same day**, and an estimate of 20 against a ceiling of 100 —
> `spend_totals` still states 90 and the admission projects 110 and **refuses**,
> because §2 counts every row in the calendar interval and not the rows earlier
> than the current instant. A ledger filtering at `recorded_at <= now` computes
> zero here and admits, while passing every rollover fixture beside it.
> It drives the same with a clock that steps **backward** across the boundary,
> since §7 permits one, and asserts that **while the first call is still
> outstanding** no combination of rollover and step admits a pair of calls whose
> declarations together cross a ceiling — the reservation is counted whichever
> period is current, so neither direction of step can lose it.

> **Normative.** The suite asserts that of an outstanding pair and **not** of a
> pair whose first call has already completed and been released, and the difference
> is §7's rule rather than a gap the suite is leaving: rows do not move between
> periods, so a clock stepped back across a boundary selects a period whose rows
> exclude a completion recorded after the step, a second call is admitted against
> that total, and a later forward step puts both completions in one period. §2
> states that limit as one the ceiling does not promise. A suite asserting
> otherwise would be requiring an implementation that rewrote history, which §7
> forbids in as many words, so this clause exists to stop a lane reading the one
> above it as the wider claim.

> **Normative.** The suite pins the **order** of the returned tuple —
> `CALENDAR_DAY` first, `CALENDAR_MONTH` second — by asserting the exact sequence
> of `period` values rather than looking each entry up, and the consumer group
> asserts the same through the relayed engine member and the CLI's rendered order.
> §5 states the order as part of the contract; a producer returning the month first
> satisfies every totals, coherence and error-ordering fixture here and changes what
> every reader of the surface sees.

> **Normative.** The suite drives `spend_totals`' coherence: with a clock that
> steps between reads, both returned entries carry bounds selected from **one**
> instant; and with a completion appended between the two aggregations an
> implementation would perform, the day total is never larger than the month total
> that contains it. A suite reading the two entries without moving anything between
> them does not discharge this clause.

> **Normative.** The suite drives the double-count window §3 states rather than
> leaving it to be discovered: with a reservation outstanding **and** its completion
> already appended, the projected total counts the call twice and the next
> admission may be refused on that basis; after the release it is counted once. The
> assertion is that the direction is over-counting, and it is what stops an
> implementation from "fixing" the window by releasing before the completion lands.

> **Normative.** It drives that same configuration again with each **estimate**
> state that refuses where a ceiling *is* configured: a declared amount that is not
> countable (§1), an `UNKNOWN` basis with no allowance set (§2), and a cost
> denominated in a currency other than `world_spend_currency` (§2). Each is
> **admitted**, and the ledger is not consulted in any of them. Without these three
> the clause above is discharged by an implementation that tests the estimate
> *before* it tests whether a ceiling exists: it passes every case listed there and
> still refuses a call in the one configuration that must refuse nothing.

> **Normative.** The suite drives an exact sum in the **admitted** direction under
> a hostile ambient `decimal` context — a precision of ten, with traps armed:
> countable rows whose exact accounted total needs more significant digits than
> that context carries, while the projected total stays **below** the ceiling, so
> the call is admitted and `spend_totals` states the exact sum. That is what pins
> the result rather than a precision, and a suite that drives only refusals does not
> discharge this clause: an implementation computing in the caller's context would
> round or trap exactly here, where it must admit and state an exact figure.

> **Normative.** The admitted case is bounded at **twenty-four** significant
> digits, not twenty-eight, and the suite does not ask for more of it. §1 bounds
> every contributing amount below `1E15` and to nine fractional digits, so a total
> that stays under a likewise countable ceiling carries at most fifteen integer and
> nine fractional digits. A below-ceiling sum needing a twenty-ninth digit is not a
> fixture anyone can build, and the hostile context above is what tests the same
> property in its place.

> **Normative.** The suite drives the case needing **more significant digits than a
> default 28-digit context carries** where such a total is in fact reachable — an
> **accounted** total, which §1's predicate does not bound, because that predicate
> governs inputs and not results. One fixture serves it: enough completion rows in
> one period that their exact sum exceeds `Decimal("1E19")` while retaining nine
> fractional digits, which takes rows in the ten thousands since §1 bounds each
> below `1E15`. Against that fixture the suite drives two reads of the same number:
> a `spend_totals` read with a **reporting currency and no ceiling**, where the
> exact total is stated and nothing is refused; and an admission with a ceiling
> configured, where the projected total exceeds it and the call is refused with
> `SpendCeilingError`. A conforming implementation sizes its context from the
> operands (§2) and neither rounds the stated total nor answers the comparison out
> of a default context. This fixture is also what pins §2's second sizing rule: the
> accounted total here is an **accumulated operand**, above every bound §1 states,
> and an implementation that sized the projection's context from the fifteen
> integer and nine fractional digits §1 bounds a *source* amount to, instead of
> from the accumulator's own `as_tuple()`, rounds or traps on it rather than
> comparing it exactly. The stated total is asserted digit for digit, so rounding
> it is a failure rather than a near miss.

> **Normative.** The suite drives a configured ceiling of **zero** as a ceiling
> that *binds*, which the exotic-zero fixture below does not reach because it only
> requires behaviour equal to `Decimal("0")`. With a zero ceiling and an accounted
> total of zero, the **smallest positive countable estimate** is refused, while a
> `FREE` call and a zero-amount one are **admitted** at equality (§3's
> strictly-greater rule). An implementation testing `if ceiling:` rather than
> `ceiling is None` treats zero as no ceiling at all, admits the positive call §3
> requires it to refuse, and passes every other ceiling fixture here — including
> both spellings of zero below, which it also admits.

> **Normative.** The suite drives `Decimal("0E-999999999999999999")` — countable
> by §1, numerically zero, and carrying an exponent no context can be sized from —
> as a configured **ceiling**, as a **declared** amount and as a **reported** one.
> Each is classified as countable and each is carried through the arithmetic to the
> same answer as `Decimal("0")` would give, with no trap raised and no allocation
> attempted from the raw exponent. As the **allowance** it is refused at load with
> `ConfigurationError` and for a different reason entirely — §1 requires an
> allowance strictly greater than zero in every spelling `Decimal` admits for zero,
> and this is one — which the suite drives as its own case so that a lane cannot
> read the countability obligation as licence to accept it. This is §2's effective-scale clause,
> and an implementation sizing a context from `as_tuple().exponent` fails it by
> exhausting memory rather than by returning a wrong number.

> **Normative.** The suite drives `SpendTotal.currency`'s shape rule as hostile
> constructions: `""`, `"usd"`, `"US"`, `"USDD"` and a three-character non-ASCII
> value each raise at validation, and `"USD"` constructs. The field's
> `EncodableText` base admits every one of the refused values, so a suite that
> drove only encodability would leave the rule untested.

> **Normative.** The suite drives §1's countability predicate at **both** of its
> boundaries, by naming the values rather than asking for one outside the range.
> The magnitude bound is strict, so it is pinned at the number itself: exactly
> `Decimal("1E15")` is **not** countable, and `Decimal("999999999999999.999999999")`
> — the largest countable value below it — **is**. The scale bound is pinned
> independently of magnitude, so an implementation cannot satisfy it with an
> over-magnitude fixture: `Decimal("0.000000001")`, nine non-zero fractional
> digits, is countable, and `Decimal("0.0000000001")`, a non-zero tenth, is not.

> **Normative.** Those four values are driven on **each** of the four amounts §1's
> predicate governs, with the classification's stated consequence asserted in each
> place: as a configured **ceiling** and as the **allowance**, where a non-countable
> value is refused at load with `ConfigurationError` naming the field and a
> countable one loads; as a **declared** `ToolCost.amount` with a ceiling
> configured, where a non-countable value refuses the call with
> `SpendUndeterminedError` and a countable one is carried into the projection; and
> as a **reported** cost on a completion row, where a non-countable value makes the
> period's accounted total indeterminate and a countable one is summed into it. A
> suite carrying only over-magnitude fixtures discharges neither bound: an
> implementation that dropped the fractional-digit half of the predicate, and one
> that wrote `<=` where §1 says strictly less than, each pass it.

> **Normative.** The suite also drives the case the predicate's wording exists for
> — a value written with ten fractional digits that is numerically equal to one
> with none, accepted as countable, because the test is on the value and not on the
> representation. It asserts that in **none** of the non-countable cases is the
> allowance substituted, and it drives every case in this clause and the two above
> it again under a hostile ambient `decimal` context — a precision of ten, with
> traps armed — asserting the same classifications and no leaked `decimal`
> exception.

> **Normative.** The suite drives the case where **both** configured periods are
> indeterminate at once — both ceilings configured and an open claim in the current
> day, which is in the month as well — and asserts the single
> `SpendUndeterminedError` names **both**, in §5's fixed order, `CALENDAR_DAY` then
> `CALENDAR_MONTH`. An implementation naming only the day passes the ground and
> class clauses above and the both-ceilings clause below, and still tells a user to
> wait until tomorrow when the month cannot be measured either. It drives the
> mirror as the assertion that the rule is over *configured* periods: with only the
> month ceiling set and the same claim, the message names the month alone.

> **Normative.** The suite drives the case where **both** ceilings are crossed by
> one projection — day 9 of 10 and month 99 of 100 against an estimate of 2 — and
> asserts one `SpendCeilingError` naming both periods in §5's fixed order with each
> one's ceiling and total. §4 fixes that there is no precedence, so a suite driving
> only the single-crossing cases leaves two conforming implementations free to
> report different periods.

> **Normative.** `SpendTotal` **validates its own invariants** rather than relying
> on its annotations, and **every one of them is decidable from the value alone**:
> `start_offset` and `end_offset` are strictly within `±24` hours; `ceiling`
> is non-`None` only where `currency` is; and `accounted` is
> non-`None` only where `currency` is. A construction violating any of them raises
> at validation, and the shared contract drives each as a hostile construction:
> an offset of `±24` hours exactly and one beyond it each **raise**, beside the
> currency and absence cases. It drives the **bound order** the same way, which no
> offset or producer fixture reaches: reversed bounds — `period_start` after
> `period_end` — **raise**, and equal bounds **construct**, since §1's zero-length
> period is a value the model must accept. A validator that admitted the reversed
> pair, or refused the equal one, passes every other clause in this section.

> **Normative.** The suite drives the offsets' **resolution** in the accepting
> direction, because a whole-minute validator passes every refusing fixture above:
> `Asia/Manila`'s `-15:56:08` and `America/Metlakatla`'s `+15:13:42` each
> **construct**, are carried unrounded, and render as themselves. A model that
> rounded to the minute states an offset the clock contract says was never in
> force.

> **Normative.** It drives the **bound-plus-offset** invariant at both ends, which
> the offset and clamp fixtures reach separately and never together:
> `period_start` at the earliest representable instant with a negative
> `start_offset` **raises**, `period_end` at the latest with a positive
> `end_offset` **raises**, and the same bounds with offsets of the opposite sign
> construct and render. It asserts the CLI renders both accepting cases rather than
> only that they validate, since the invariant exists for the renderer.

> **Normative.** **Each bound plus its own offset is representable**, and the model
> checks it: `period_start + start_offset` and `period_end + end_offset` each land
> inside `datetime`'s range. This is intrinsic on the same test — two fields and an
> addition, no zone database — and it is the invariant that makes §6's rendering
> total, since a renderer performs exactly those two additions. Without it the
> listed range and ordering rules admit a value the required renderer cannot print:
> `period_start` at `0001-01-01T00:00:00Z` with a negative `start_offset`
> underflows, and a `period_end` near `datetime.max` with a positive `end_offset`
> overflows, each while satisfying every other clause here.

> **Normative.** The model's bound invariant is otherwise the **intrinsic** one and
> nothing more: `period_start` is strictly before `period_end`, except on §1's
> zero-length period where they are equal. It does **not** re-derive §1's
> boundaries and compare, and that is a decision rather than an omission — the
> tempting stronger validator would reject a `CALENDAR_DAY` carrying a month's
> bounds, which this one admits, and it is the producer and not the model that
> §11's clause below holds to §1's rule.

> **Normative.** No validator on this model resolves a zone, reads `tzdata` or
> constructs a `ZoneInfo`, and the suite asserts that by driving the **whole model
> surface with no zone database reachable at all** — every hostile construction and
> every accepting one, unchanged. §5 gives the reason the fields are shaped this
> way; this clause is what stops a later lane reintroducing a lookup, since a
> validator that consulted one would pass every other fixture here.

> **Normative.** The correspondence to §1's rule is therefore checked at the
> **producer**, by the conformance suite and the lane (the real-producer clause
> below), which is the only place that can compare against §1's rule rather than
> against a second implementation of it — and where one `tzdata` governs both sides
> by construction, because there is only one side.

> **Normative.** The **numeric** invariants are driven as hostile constructions
> too, and they are the ones a validator list is likeliest to omit: a negative
> `ceiling`, a negative `accounted`, a `ceiling` of exactly `Decimal("1E15")` and
> one with a tenth fractional digit each raise; an `accounted` above
> `Decimal("1E15")` **constructs**, because §1's predicate governs inputs and a
> total is a result; and an `accounted` with a tenth fractional digit raises. A
> non-finite value raises for either field.

> **Normative.** `accounted`'s **representation** invariant (§5, over §2's one
> representation) is driven as hostile constructions in its own right, because it
> is the one a validator list built from "finite, non-negative, nine digits" passes
> without carrying: `Decimal("2.0")`, `Decimal("2E+1")` and `Decimal("-0")` each
> raise, while `Decimal("2")`, `Decimal("20")`, `Decimal("0")` and
> `Decimal("0.000000001")` each construct. The positive-exponent fixture is
> `Decimal("2E+1")` and deliberately not `Decimal("2E+0")`, which is `Decimal("2")`
> in `Decimal`'s own representation and would make the case unwritable. `ceiling`
> is driven with the same values and the **opposite** expectation for the scale
> ones — a configured `Decimal("2.0")` ceiling constructs, because §2's rule
> governs results and a ceiling is an input — which is what stops a lane from
> applying one numeric validator to both fields.

> **Normative.** The same property is driven **end to end** rather than only at the
> model, since a construction test passes against an implementation that never
> computes the offending value: over completion rows of `0.1`, `0.9` and `1`, every
> permutation of the row order yields a `SpendTotal` whose `accounted` is
> `Decimal("2")` — asserted on `as_tuple()`, not on `==`, which `Decimal("2.0")`
> satisfies — and encodes to the bytes `"2"` through `wire/codec.py`. It is driven
> again over rows that are **all** `Decimal("-0")`, where the total is
> `Decimal("0")` and the bytes are `"0"`: an accumulator seeded from the first row
> rather than from zero preserves the sign and fails exactly here, and a suite
> asserting only equality passes it, since `Decimal("-0") == Decimal("0")`.

> **Normative.** The **projected** total is driven for the same property, because
> §2's representation clause governs both results and only one of them has a model
> to enforce it. An accounted total of `Decimal("2")` and a declared estimate of
> `Decimal("1.0")` project `Decimal("3.0")` under a naive sum where §2 requires
> `Decimal("3")`, and the projection reaches the user through
> `SpendCeilingError`'s message (§4): so the suite drives that pair over a ceiling
> of `Decimal("2.5")` and asserts the projected figure the error states is the
> canonical one, on its exact tuple or on the rendered text and never on `Decimal`
> equality, which `Decimal("3.0")` satisfies. It drives the same with a declared
> `Decimal("-0")` against an accounted zero, where the projection is `Decimal("0")`
> and not `Decimal("-0")`. An implementation that canonicalised the ledger's total
> and not the projection passes every clause above and states the wrong number in
> the one place a user reads it.

> **Normative.** The **positive-exponent** case is driven through aggregation and
> not only as a hostile construction, because those two catch different
> implementations: two completion rows of `Decimal("1E+1")` sum to `Decimal("2E+1")`
> under `+`, and a `SpendTotal` built from that raises where §2 requires
> `Decimal("20")`. So the suite asserts the accounted total's tuple is
> `(0, (2, 0), 0)` and its bytes are `"20"`, and asserts the same through the
> projection. An implementation that canonicalised scale and sign but left the
> exponent alone passes both clauses above and fails the ledger read outright,
> which is a worse failure than a wrong number and is why this is a fixture rather
> than a remark.
> **Normative.** The lane drives §5's `Decimal` wire form against the real encoder
> rather than describing it: **each of the eight** vectors §5 states is asserted to
> its exact bytes and round-trips through `wire/codec.py` to a value the type
> cannot distinguish from the original — the threshold pair matters most, since an
> encoder emitting `"0.0000000001"` where §5 says `"1E-10"` escapes a suite that
> checks only round-tripping, and `Decimal("-0")` escapes one that checks only
> equality —
> `Decimal("1.0")` and `Decimal("1")` reaching **different** bytes is the assertion
> that catches a normalising implementation — a non-finite `Decimal` raises at the
> projection, and a `SpendTotal` and a `PermissionDecision` carrying a `PER_CALL`
> `ToolCost` both cross the wire and come back equal, which is #1559's case as a
> regression rather than as a promise. The vectors are added to ADR-0087 §5's
> suite, where a vector for a case no existing vector covers belongs (§8).

> **Normative.** The consumer group drives §6's **transport** clause, which this
> ADR asserts is driven and which nothing else here reaches: through the hub-backed
> `spend_totals`, a call with **no hub listening** raises `HubUnavailableError` and
> a call answered with a **malformed or truncated** reply raises `ProtocolError`,
> each reaching the caller **unchanged** and neither arriving as
> `SpendUndeterminedError`. A `HubClient.spend_totals` catching `Exception` and
> translating passes every success and budget-failure fixture in this section and
> tells a user their spend is indeterminate when the truth is that there is no hub
> — which is the confusion §4 keeps two classes to prevent, one seam further out.

> **Normative.** The lane asserts `SpendTotal`'s **one** string field, `currency`,
> is `EncodableText`-based by construction, which
> `tests/core/test_text_encodability_coverage.py` already does for every model in
> `core.types` and this ADR claims no exemption from. It is one and not two because
> §5 carries resolved offsets in place of a zone name; a lane that finds two here
> has added a field §5's exact schema forbids.

> **Normative.** The lane drives §1's configuration **dependencies** at load,
> which no admission fixture reaches because a valid fixture supplies a currency
> without being asked: each ceiling alone and the allowance alone with
> `world_spend_currency` unset raises `ConfigurationError` naming the field, and
> `world_spend_currency` set **alone** loads and configures a reporting currency
> that refuses nothing (§1). It drives §1's **numeric** rules at load in the same
> place, on `Settings` and not on `SpendTotal`: a **negative** ceiling and a
> negative allowance, and `NaN`, `sNaN`, `Infinity` and `-Infinity` for each
> ceiling and for the allowance, are each refused with `ConfigurationError` naming
> the field. A validator checking only the zero spellings and countability accepts
> an allowance of `Decimal("-1")`, which would let an `UNKNOWN` estimate *lower* a
> projection and admit a call already at its ceiling — the one direction this
> mechanism must never move in. Without these a `world_spend_day_ceiling` of
> `Decimal("10")` loads beside no currency and silently caps nothing, which is a
> configured ceiling that does not bind. It drives `world_spend_currency`'s own
> shape rule at load in the same place — `""`, `"usd"`, `"US"`, `"USDD"` and a
> three-character non-ASCII value each refused, `"USD"` accepted — since §5's
> hostile constructions test `SpendTotal` and not `Settings`.

> **Normative.** The lane loads a **day ceiling above the month ceiling** — §1's
> `day=100` beside `month=10` — asserting it is **accepted** and that the month is
> simply the binding one, with an estimate of 20 refused on the month while the day
> is nowhere near crossed. §1 says nothing refuses a configuration on that ground;
> a settings validator quietly imposing `day <= month` passes every dependency and
> crossing fixture here and rejects a configuration this ADR calls valid.

> **Normative.** The lane refuses a zero allowance at load in each of §1's
> spellings, and asserts the calendar month whose exclusive end is not
> representable is closed at the latest instant representable in both UTC and the
> configured zone rather than refusing — driven in a **positive-offset** zone and a
> **negative-offset** one, with the rendering §6 requires exercised on the clamped
> bound rather than only its construction.

> **Normative.** It drives §1's **lower** clamp in the same two shapes, which the
> clause above does not reach: at a `checked_clock` reading of
> `0001-01-02T00:00:00Z`, a positive-offset zone (`Etc/GMT-7`) whose current
> month's civil start carries its local midnight below the earliest representable
> instant, asserting the returned `period_start` is the clamped one and that both
> periods and their §6 rendering are produced rather than an `OverflowError`; and
> the negative-offset mirror, where no clamp applies and the ordinary boundary is
> returned, so the fixture pins the clamp to the case that needs it. An
> implementation clamping only the late boundary passes every fixture above this
> one and crashes here.

> **Normative.** The lane **reopens the primary holder** on a persistent store that
> already carries completion rows, and asserts both `spend_totals` and the next
> admission reconstruct the accounted total from those rows. §7 makes the total
> derived and says no cache is authoritative; nothing else here tests it, because a
> holder that keeps a correct in-process cache and initialises it to zero on
> construction passes every aggregation, rollover and erasure fixture above, then
> reports zero after a restart and admits calls against spend the store still
> holds. The fixture asserts the reconstructed figure equals the one the same rows
> produced before the reopen, and that a call which was refused before it is
> refused after it.

> **Normative.** The lane drives `clear()` interleaved with an in-flight
> invocation in both orderings, and asserts ADR-0192 §6's outcome together with
> this ADR's budget consequence: the erased invocation's spend is not counted, and
> nothing is minted to recover it. It drives erasure as §4's sixth lifting path in
> the same place: a call refused at a projected 101 against a ceiling of 100,
> `clear()`, and the same call admitted in the same period under the same
> configuration, with the accounted total `Decimal("0")` (§7) rather than a
> preserved figure. That is the promise this ADR makes about a spend counter
> outliving an erasure, asserted from the outside.

> **Normative.** The consumer group drives §6's CLI rendering in its **ordinary**
> states and not only on the clamped bound, because each of them is a way a correct
> total is shown as a wrong fact. Three fixtures: a client configured in a zone
> **different** from the one the ledger computed in, where each bound renders from
> the value's own offset and the client's zone is not consulted — driven with the
> client's zone database **absent** as well, which the value's offsets make
> survivable and a zone name would not have; `currency=None`, where the command
> says no currency is configured and states no total; and `currency` present with
> `accounted=None` **and a ceiling configured**, where it says the period is
> indeterminate *and* that no further call in it will be admitted. A renderer
> collapsing §5's two absences into one message passes every other clause here and
> tells a user "no total" while their calls are being refused.

> **Normative.** It drives §6's command by its **token**: `assistant spend` is the
> invocation asserted, and the token appears in the CLI's own help output. A suite
> that reaches the renderer through its Python function alone leaves the one thing
> a user's script binds to untested, and a rename would pass it.

> **Normative.** The lane asserts that a refused call left **no** claim and no
> completion in ADR-0192's ledger, and that the refusal reached the executor as
> ADR-0034 §1's pre-callable exit.

> **Normative.** The lane drives the deadline against the **primary** holder and
> not only against the suite's cancellable fake, which is what §3's limit clause is
> about: a real gate whose store read is wedged, reached through
> `ToolInvoker.invoke` with a short `timeout`, and the same holder taken through
> shutdown while that read is outstanding. What is asserted is which of ADR-0029
> §4's **two sides** the lane's own read falls on — the seam returning at its
> deadline where the read is cancellation-cooperative, or the deadline outlived
> where it is not (§4's third bullet, §3) — **stated in the test**, together with
> what happens to the connection at shutdown. Either is conforming; what is not
> conforming is a lane that writes only cooperative-fake fixtures, inherits
> ADR-0054's absorption without noticing, and leaves a reader of its tests
> believing the deadline is a hard bound.

> **Normative.** The lane drives the **producer** obligation §5 declines to put on
> the model: the `SpendTotal` values `spend_totals` returns are asserted to carry
> exactly the boundaries §1's rule computes for their own `period` in the ledger's
> configured zone, **and offsets equal to the ones in force at those two instants
> in that zone** — asserted to differ from each other on the DST fixture, which is
> the case a single offset would have misrendered — on the DST, skipped-date and
> both-clamp fixtures above. This is the whole of
> where that correspondence is checked, so a lane treating it as belt-and-braces
> beside a model validator has misread §5: there is no such validator, by decision.

> **Normative.** The lane drives §2's stated overrun end to end: a call whose
> declaration understates it is **admitted**, its reported cost carries the
> accounted total past the ceiling, that row is counted rather than excused, and
> the next call is refused. This is the property this ADR promises and the one it
> does not, asserted rather than described.

> **Normative.** Neither lane changes any tool's declared `ToolCost`, and neither
> re-declares `send_email`'s `UNKNOWN`. The honest declaration stands, and §2's
> allowance is the mechanism that makes it usable.

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
- **An unknown-priced completion, where no allowance is configured, leaves its
  period indeterminate**, and while **that period's own** ceiling is configured
  that stops every further invocation in it until the calendar rolls or the user
  acts. (With an allowance configured it contributes that amount and the total
  stays a number; where the indeterminate period carries no ceiling of its own —
  an unpriced row in an earlier day of a month nobody capped — nothing is refused,
  which is §2's per-period rule and, where neither ceiling is set, its
  unconditional case.) That is a real denial of service on
  the user's own assistant, taken knowingly: the alternative is a total that
  under-reports by an unbounded amount while presenting itself as a bound. §8 names
  the deferral that would soften it.
- **An open claim does the same, for as long as it stands open.** ADR-0192 obliges
  the invoker to complete every claim and ADR-0014 §4's recovery scan closes the
  ones a crash left, so the state is transient by construction rather than
  permanent — but a store that cannot record the completion is a store whose
  budget arithmetic is genuinely unknown, and this ADR says so instead of
  guessing.
- **A currency with no ceiling is a supported configuration**, and it is the
  cheapest way in: the totals are computed and readable, nothing is ever refused,
  and a user can watch what the world costs for a month before deciding what to
  cap it at. It is also what keeps the unbounded case coherent — a total needs a
  denominator, and this is where it comes from.
- **The ceiling is not a guarantee about the total, and says so.** It bounds what
  *begins*, not what *ends up spent*, because a declaration can understate.
  Stating the weaker property is what keeps the number honest — the same candour
  #1548 credits Claude Code's docs for, applied to our own.
- **`permissions` gains no store handle and `ActionPolicy` gains nothing.** The
  monotonicity and floor obligations stay checkable on a pure function, which is
  what ADR-0021 §5's whole conformance argument rests on.
- **Erasing the trail resets the ceiling.** Accepted, because the alternative is a
  spend record that outlives the user's own erasure.
- **Two numbers are now contract** (§1). An amount at or above 10^15, or whose
  value needs more than nine fractional digits, is not countable: configured, it is
  refused at load; declared, it refuses the call; reported, it makes the period
  indeterminate. It is never swapped for the allowance — that stands for a price
  nobody knows, not for one this mechanism cannot add. The bound is what makes the
  exact arithmetic computable rather than aspirational, and the numbers are stated
  so a reader can disagree with a number rather than with the principle.
- **`core` grows by eight names** — `SpendGate`, `SpendLedger`, `SpendPeriod`,
  `SpendTotal`, `SpendAdmissionHandle`, `SpendError`, `SpendCeilingError`,
  `SpendUndeterminedError` — plus two members on the first, one on the second, one
  engine member, four settings and one row on ADR-0087 §2c's table. That is the
  breaking-change surface golden rule 5 asks be flagged, and none of it lands here.
- **Two deferrals close and one scope-out is narrowed.** ADR-0021 §6's and
  ADR-0029 §7's spend-accumulation halves are discharged. The concurrency residue
  an earlier draft deferred is **closed here** by §3's reservation, on the finding
  that it was reachable today rather than unreachable (#1561); what remains named
  is the cross-process case (#1553), which ADR-0083's one-process rule makes
  unreachable for a reason that is checkable rather than assumed.
- **Revisit when** any priced invocation becomes executable with no per-call user
  act — a standing grant, or simply a `PER_CALL` tool declaring `discloses=()`,
  which ADR-0021 §5's floor does not reach (§8) — at which point the default
  becomes a live question; when a second priced integration lands (the per-tool
  deferral gets its first real case); or when a user's tools span two currencies.

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
- **A durable reservation ledger — reserve, execute, settle.** Rejected in §3.
  What it buys over §3's in-memory reservation is survival across a process
  restart, and it pays for that with a second two-phase ledger beside ADR-0192's
  and an open-reservation recovery problem of its own. A restart discards the
  accounted total's *cache* and nothing else — §7 rebuilds it from rows — so the
  only thing a durable reservation preserves is a claim about calls that were
  in flight when the process died, which ADR-0192's own open claims already make
  the period indeterminate for. **An earlier draft rejected the reservation
  outright**, on the ground that "under one executor the residue is unreachable";
  that ground was false (#1561) and §3 now takes the in-memory half of this
  alternative rather than deferring the problem.
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
