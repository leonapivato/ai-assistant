# 236. The operator declares what one web search costs, and where none is declared the search confirms on that ground as well

- Status: Proposed
- Date: 2026-09-04

## Context

### Where this comes from

Issue #2111. `WEB_SEARCH` declares `cost=ToolCost(basis=CostBasis.UNKNOWN)`, and
`ThresholdActionPolicy` fires **two** floors on that declaration rather than one —
`_DISCLOSURE_FLOOR` and `_UNKNOWN_COST_FLOOR`. Its route-(b) predicate,
`_only_the_disclosure_floor`, admits the standing-grant lookup only where
`fired == [_DISCLOSURE_FLOOR]`, so on a search the seam is consulted **zero** times
and no `RecipientGrants` this system can hold changes the answer. Every search is
`CONFIRM`, in every configuration, whatever the user has granted.

That is not what ADR-0231 §5 decided. Its declaration clause already names the field
this ADR supplies:

> a `cost` that is the operator's configured per-call figure where one is configured
> and `UNKNOWN` where none is

and §5's commentary states the intent in terms — *"A deployment that configures a
per-call figure declares it; one that does not declares `UNKNOWN`, which confirms"*.
What ADR-0231 did not do is say **how** a deployment configures one. Its four
`Settings` fields are all bounds; `build_web_search_integration` takes no cost
parameter and constructs `WEB_SEARCH` unchanged. So the first limb of that clause —
*"where one is configured"* — names a state no deployment can reach.

### Why this matters now rather than eventually

ADR-0235 landed the surface ADR-0231 §19 named as the mechanism's firing condition, and
it is now **in the tree** rather than only in a ratified text:
`AssistantEngine.grantable_decisions` lists a recorded `CONFIRM` on a `WEB_SEARCH`
decision and `AssistantEngine.establish_recipient_grant` performs the act on it, over
`orchestration/recipient_grants.py`. That path works. A user *can* establish a standing
grant over the search provider's canonical destination set — a search's decision meets
all seven of ADR-0235 §3's availability conditions, the two that would exclude it being
the ones that module tests directly (a `step_id` or `execution_id` set, and a binding
carrying `planned_with_external_content`), and a `WEB_SEARCH` request carries neither.
`ActionPolicy.resolve` then reaches the `ALLOW` that mints the grant, because `resolve`
re-checks the rules and an approved `CONFIRM` is not blocked by a second firing floor.

And then the next search confirms anyway. The grant is recorded, it covers the
recipients, and `decide` never asks about it. **The affordance is worse than absent:
the user performs the one act the corpus offers them and nothing changes**, with no
record anywhere saying why. ADR-0231 §9's own statement of what a deployment can
change — *"Two things make a search serviceable and both are the user's or the
operator's: a standing grant, once a surface offers the establishing act; and the
thresholds `Settings` already exposes"* — is, as of ADR-0235, an undercount. There is a
third, and nobody can set it.

### The tree, read rather than assumed, at `origin/main` `452dca46`

- `tools/web_search.py` — `WEB_SEARCH` declares `cost=ToolCost(basis=CostBasis.UNKNOWN)`
  as a module constant. Its docstring already anticipates this ADR: *"This template
  declares `UNKNOWN`; a deployment that knows its per-call figure is ADR-0231 §5's
  'operator's configured per-call figure'"*.
- `tools/builtin.py` — `build_web_search_integration` takes `connection`, `origin`,
  `records`, `secrets`, `transport`, `ledger`, `gate` and the three bounds. No cost.
  It is *"the one place in production a searcher is constructed"*.
- `permissions/policy.py` — `_UNKNOWN_COST_FLOOR` fires on
  `tool.cost.basis is CostBasis.UNKNOWN`; `_FLOORS` is the pair; `decide`'s docstring
  states the consequence in terms — *"An `UNKNOWN` cost still draws `CONFIRM`"*, and
  each such case *"reaches the seam **zero** times"*.
- The thresholds do not save it. `WEB_SEARCH` is `risk_level=LOW` against a default
  `confirm_at_risk` of `MEDIUM`, and `REVERSIBLE` against a default
  `confirm_at_reversibility` of `IRREVERSIBLE`, so neither threshold rule fires and
  the two floors are the whole of `fired`. This is why the gap is specific to the
  search: `send_email` is `HIGH` and `IRREVERSIBLE`, so its `fired` was never the
  singleton `_only_the_disclosure_floor` requires and its own `UNKNOWN` cost changes
  nothing about its reachability.
- `core/types.py` — `ToolCost` requires `amount` **and** `currency` for `PER_CALL`,
  refuses both for every other basis, refuses a non-finite amount, and refuses a
  **negative** one with `<`. `Decimal("0")` is therefore already an admissible
  `PER_CALL` amount.
- `core/config.py` — the four bounds are there, and so are `web_search_connection`
  and `web_search_origin`, refused half-set by
  `_the_search_registration_is_whole_or_absent`. That pair is itself the precedent for
  a search `Settings` field that is not one of ADR-0231 §5's four: the module says so —
  *"These are the connected account's configuration and not two more of ADR-0231 §5's
  four bounds"*.
- `core/config.py` also already carries ADR-0194 §1's countability predicate as
  `_spend_is_countable`, and `_checked_spend_amount` applies it with a floor, for the
  two ceilings and the allowance.
- `orchestration/reads.py` — `SearchDisposition` is now merged and carries **exactly
  fifteen** members, ADR-0231 §13's enumeration one for one: `NOT_CONFIGURED`,
  `NO_BUDGET`, the four `COMPOSER_*`, `BINDING_FAILED`, `RULING_CONFIRM`, `RULING_DENY`,
  `RULING_UNAVAILABLE`, and the five carried from `SearchRefusal`. **None names the cost
  floor**, and none distinguishes a ground within the ruling stage. That is the premise
  §5 rests on, read off the implementation rather than off the ADR alone.
- `testing/searching.py` — `FAKE_WEB_SEARCH` declares `UNKNOWN` too, as a module
  constant, and `FakeWebSearcher` takes bounds but no cost. The module states the posture
  this ADR reuses twice over: `DEFAULT_MAX_RESULTS`' comment refuses *"a canonical fake
  configurable into a state no deployment can be in"*, and `FAKE_WEB_SEARCH`'s own
  docstring says its safety fields are the production declaration's *"because a fake
  ruled on more leniently than the real thing would let a consumer's policy test pass for
  a reason no deployment enjoys"*.

### What this ADR is not allowed to settle

- **Which surfaces offer the establishing act.** ADR-0193 §13 and ADR-0235 own it.
- **Whether `risk_level=LOW` is honest.** ADR-0231 §19 defers it to the owner with the
  consequence stated. This ADR takes no position and moves nothing that depends on it.
- **A per-tool spend ceiling.** ADR-0194 §1's last clause forbids one without its own
  ratified decision, and §15 of ADR-0231 sets none. This decision declares a **price**,
  which is an input to ADR-0194's arithmetic, and adds no bound of any kind.
- **Any `core/protocols.py` or `core/types.py` surface.** Nothing here needs one.

## Decision

### 1. The figure is the operator's, in two `Settings` fields, and it reaches the declaration through the one builder

> **Normative.** `core.config.Settings` gains exactly two fields:
> `web_search_cost_per_call: Decimal | None` and
> `web_search_cost_currency: str | None`, each defaulting to `None`. They are the
> whole of what this decision adds to configuration, and no lane adds a third under
> it.

> **Normative.** `build_web_search_integration` takes both as keyword arguments and
> constructs the declaration it registers with
> `ToolCost(basis=CostBasis.PER_CALL, amount=<the figure>, currency=<the code>)` where
> both are supplied, and with `ToolCost(basis=CostBasis.UNKNOWN)` where neither is.
> **The rule is stated over building a `ToolCost`, not over reading a setting.** That
> builder is the **only** place in production where either value becomes a `ToolCost`,
> and `FakeWebSearcher` (§7) is the only other site under `src/ai_assistant` that may
> build one from them at all — it is the canonical fake, it is test-only, and its
> parity clause is what puts it there. **No** other component derives a cost from
> either value, interprets one, substitutes one, defaults one, or edits a
> `ToolDefinition` after construction; nothing in `interfaces/`, `orchestration/` or
> `permissions/` reads either setting for any purpose at all.

> **Normative.** **`app/composition.py` reads both settings and passes them through
> unchanged**, which is the whole of what it does with them and is what §7's third
> clause obliges. Passing a value is not interpreting it: the composition root applies
> no default, performs no arithmetic, constructs no `ToolCost`, and does not decide
> whether the pair is whole — §2's refusals have already run at `Settings` load, and
> the builder restates them at its own site.

> **Normative.** The module-level `WEB_SEARCH` constant keeps `UNKNOWN` and no lane
> mutates it. The configured declaration is a **second value built per registration**,
> equal to `WEB_SEARCH` in every other field. ADR-0016 §1's `frozen=True` argument is
> why: a permission decision is recorded against the definition that was in force, and
> a shared constant whose `cost` was rewritten at start-up would be the back door that
> clause names.

**Two fields rather than one, and neither carries a grammar.** `ToolCost` needs an
amount and an ISO-4217 code, and a single setting holding `"USD 0.005"` would invent a
parse — a third spelling of a currency alongside `ToolCost.currency`'s and
`world_spend_currency`'s, with its own failure modes and its own refusal message.
The pair is `web_search_connection`/`web_search_origin`'s shape, one field pair along,
and it is refused half-set for the same stated reason.

**The `web_search_` prefix and not `search_`, deliberately.** The four `search_*`
fields are bounds the composer, the searcher and the transport enforce. This is the
connected account's commercial fact, in the same class as which account and which
origin, and the prefix is what tells an operator reading their configuration which of
the two kinds they are looking at.

### 2. The domain, and where it is refused

> **Normative.** `web_search_cost_per_call`, where set, is a `Decimal` that is
> **finite**, **greater than or equal to zero**, and **countable under ADR-0194 §1** —
> absolute value strictly below `Decimal("1E15")` and expressible to at most nine
> fractional digits. A value outside that domain is refused at `Settings` load, before
> any composer, searcher, transport or filesystem call, with the `ConfigurationError`
> ADR-0194 §1's own configured-amount clause requires, naming the field.

> **Normative.** `web_search_cost_currency`, where set, is **exactly three uppercase
> ASCII letters** — ISO-4217's alphabetic form — validated on **shape only**, neither
> normalised nor checked against the live register. That is `ToolCost.currency`'s rule
> (ADR-0016 §4) and `world_spend_currency`'s, and not a third one.

> **Normative.** The two are set **together or not at all**, and a configuration
> setting exactly one is refused at load. Neither may be set unless
> `web_search_connection` and `web_search_origin` are both set: a per-call figure for
> a searcher no deployment builds is a value nothing reads, and the quiet reading of
> it is the unsafe one.

> **Normative.** `build_web_search_integration` states the same rules at the one place
> a searcher can be built without going through `Settings`, and raises for a violation
> exactly as it already does for a bound outside ADR-0231 §5's domain. The domain is
> therefore enforced twice, deliberately, and the two statements are of one rule.

**Countability is not a bound this ADR invents; it is the predicate the figure will
meet anyway.** ADR-0194 §1 says its predicate *"governs every amount this mechanism
reads: a configured ceiling, the allowance, a declared `ToolCost.amount` and a reported
one"*, and this figure is a declared `ToolCost.amount` from the moment the builder runs.
Refusing an uncountable one at load costs an operator one error message; admitting it
would mean a declaration that loads, registers, rules `ALLOW`, and is then refused at
the gate with `SpendUndeterminedError` on every call — ADR-0194 §1's first ground, met
at the latest possible moment for a fact known at the earliest. ADR-0230 §6's style is
that a bound is refused where it is configured, and this is the same posture applied to
a price.

**Zero is admissible and is the subject of §3.** The floor is `>= 0` and not `> 0`,
which is `ToolCost.amount`'s own floor and a ceiling's rather than the allowance's.
ADR-0194 §1 refuses a zero *allowance* because an allowance stands in for an unknown
and a zero one would make an unpriced call free; nothing in that argument reaches a
price an operator states about a call they are paying for.

### 3. `FREE` is unreachable from configuration, and a free tier is a zero per-call figure

> **Normative.** No configuration reaches `CostBasis.FREE` for this declaration. The
> only two states a deployment can put the `cost` field in are the `PER_CALL` figure
> §1 builds and the `UNKNOWN` §4 leaves. No lane adds a basis selector, a `free`
> sentinel, or any third setting whose effect is a `FREE` basis.

> **Normative.** An operator asserting that a search costs them nothing states
> `web_search_cost_per_call = 0` with the currency their account is denominated in.
> That is a positive assertion carrying a currency, and it satisfies
> `_UNKNOWN_COST_FLOOR` exactly as any other `PER_CALL` figure does.

> **Normative.** Its **spend equivalence to a `FREE` basis is conditional and is
> stated as such**: a zero `PER_CALL` figure contributes zero to both of ADR-0194
> §2's totals where its currency **is** `world_spend_currency`, and where no
> `world_spend_currency` is configured at all, since §2's first clause then sums
> nothing. Where the two currencies **differ**, §2's non-conversion clause governs and
> a zero figure is treated as an `UNKNOWN` basis is — which a `FREE` basis would not
> be. No lane states the equivalence unconditionally, and §6 is where that residual is
> accounted for.

**Three reasons, and the first is decisive on its own.** ADR-0231 §9's fourth clause
forbids *"a `cost` declared `FREE` where the figure is not known"* as one of the
mis-declarations that would make a search reachable by weakening its declaration.
Making `FREE` unreachable from configuration turns that prohibition from a rule a
lane must remember into a property of the signature — the same move ADR-0231 §5 made
when it gave `build_web_search_integration` no registry parameter, which that function's
own docstring states in terms: *"the declaration is absent from `capabilities()` and
`all_tools()`" is a property of the two signatures rather than of a line somebody
remembered not to write*.

Second, `ToolCost` expresses `FREE` by the **absence** of an amount and a currency,
which is byte-for-byte the shape of "unset". A configuration surface offering `FREE`
would need a third state to carry it, and an operator who set that state and nothing
else would be indistinguishable, field by field, from one who set nothing. ADR-0016
§4's whole reason for the enum is that *"The distinction that matters to a policy is not
present/absent but free versus unknown"*; a two-field configuration that offered
three bases would reintroduce exactly the collapse the enum removed, one layer out.

Third, little is lost, and what is lost is stated rather than claimed away. ADR-0194
§2 says *"A `FREE` basis contributes zero, in both totals"* and that *"A `PER_CALL`
basis **in the configured currency** contributes its `amount`"* — so `Decimal("0")` in
that currency contributes zero and the two forms are spend-equivalent, while the
zero-figure form is strictly more informative because it says which register the zero
was asserted in. **The one configuration where `FREE` would genuinely be better is the
currency mismatch**: §2's non-conversion clause treats a zero `EUR` figure under a
`USD` spend currency as it treats an `UNKNOWN` one, so it consumes the allowance or
meets §4's second ground, where a `FREE` basis would have contributed zero. That
residual is real and is not the ground on which this section stands: reasons one and
two hold in every configuration, the mismatch is an operator's own misconfiguration
that §6 already refuses to paper over, and buying the mismatch case would cost the
structural unreachability that makes ADR-0231 §9's prohibition self-enforcing. An
operator declaring a zero figure states it in the currency they meter in, and §6's
consequence is what tells them why.

### 4. Absence: `UNKNOWN`, `CONFIRM` on the cost ground, and that is the shipped default

> **Normative.** Where neither field is set the declaration's `cost` is
> `ToolCost(basis=CostBasis.UNKNOWN)`, `_UNKNOWN_COST_FLOOR` fires beside
> `_DISCLOSURE_FLOOR`, `_only_the_disclosure_floor` is `False`, the
> `RecipientGrants` seam is consulted **zero** times, and the ruling is `CONFIRM`
> whatever grants exist. That is the shipped default and it is the state this ADR
> makes **legible rather than accidental**: it is what the corpus already produces,
> stated as a decision so that a deployment reads it as a configuration fact rather
> than as an unexplained refusal.

> **Normative.** No lane makes the search reachable by suppressing
> `_UNKNOWN_COST_FLOOR`, by exempting this declaration from it, by adding a setting
> that reaches it, or by reading a `RecipientGrants` past it. ADR-0231 §9's fourth
> clause and ADR-0036 §1's floors-take-no-setting rule both bind unchanged, and the
> route this ADR opens is the one ADR-0016 §4 already names: **declare the figure**.

> **Normative.** The `Settings` fields' own descriptions say what their absence
> means — that the search confirms on the cost ground as well as the disclosure one,
> so a standing grant cannot make it fire — because an operator reading their
> configuration is the reader who most needs the sentence, and ADR-0231 §5's
> load-time-refusal style already puts each field's meaning in its description.

**What this does and does not open, stated with the condition it depends on.** After
this ADR, a deployment that has configured the figure **and whose thresholds fire on
neither `risk_level=LOW` nor `reversibility=REVERSIBLE`** has
`fired == [_DISCLOSURE_FLOOR]` on a search, so `_only_the_disclosure_floor` admits the
lookup and a covering standing grant yields an `ALLOW` naming the grant's `id` and its
recomputed `subject_digest`. The shipped defaults are such a deployment —
`confirm_at_risk` is `MEDIUM` and `confirm_at_reversibility` is `IRREVERSIBLE` — but a
deployment that set `confirm_at_risk=LOW`, or `confirm_at_reversibility=REVERSIBLE`, has
`_risk_rule` or `_reversibility_rule` in `fired` beside the disclosure floor, so the
seam is consulted zero times and the search confirms whatever the figure says. **That
is not a defect this ADR fixes and not one it may fix**: those are the user's own
thresholds, ADR-0036 §1 makes them the user's, and ADR-0231 §5 already states the
neighbouring case in terms — a deployment judging `MEDIUM` honest *"gets a mechanism
that is never serviced under the shipped thresholds; that outcome is legible,
fail-closed and costs nothing but the capability"*. This decision removes the one
firing clause **no** configuration could reach; a threshold the user set is one they
can unset. ADR-0231 §9's fifth clause is untouched and
is the whole of what is left: **the one route to an `ALLOW` is still ADR-0193's
standing recipient grant, established by a recorded act of the user**, and ADR-0193 §4
still refuses any grant over a binding carrying `planned_with_external_content`. This
decision removes a second blocker; it creates no route.

### 5. The audit: no sixteenth member, and how a deployment tells the two grounds apart

> **Normative.** `SearchDisposition` is **unchanged**, closed at ADR-0231 §13's
> fifteen members, and this ADR adds none. A `CONFIRM` produced with the cost floor
> among its grounds is recorded as `RULING_CONFIRM`, exactly as one produced by the
> disclosure floor alone is.

> **Normative.** The two grounds are told apart from the deployment's **own
> configuration** and never from a per-turn record: with the pair unset the cost floor
> fires on **every** search of that deployment, and with it set on **none**. No lane
> reports a `RULING_CONFIRM` population for this kind without saying which of the two
> configurations produced it — which is ADR-0231 §13's own 0%-yield clause,
> *"No lane reports a figure for this kind without saying which of the two it is"*,
> read one configuration fact further.

> **Normative.** That obligation is **scoped to a population over which the pair did
> not change**, because nothing retained anywhere records which configuration a given
> turn ran under. A population spanning a change to either field is **not reportable
> on this axis at all**: a lane splits it at the change or states no ground, and no
> lane infers a ground for a turn, back-fills one, or reads the current configuration
> as evidence about an earlier turn. The instant of such a change is the operator's own
> fact and this system does not hold it.

**Why a member would be the wrong instrument, argued against §13's own standard.**
ADR-0231 §9 requires that *"the `SearchDisposition` member it is recorded under names
the **stage** that produced it"*. Both grounds are produced by the same stage — the
ruling — so a cost-ground member would not name a stage; it would name a ground
*within* one, which §13's one-field-per-servicing design does not carry and which no
other member does. §13's stated test for a member is that it distinguishes causes
*"an operator would act on differently"* across a **population of turns**, and it
enumerates nine that vary turn to turn: a provisioning fact, a user act waiting to
happen, a policy the operator set, a ceiling, an outage, an unattestable provider. The
cost ground varies with none of them. A field whose value is constant for every turn of
a deployment carries no information the deployment does not already hold, and §13's own
argument — *"collapsing them would make the one field useless at exactly the moment
someone reads it"* — cuts the other way here: adding a member that never varies is the
dilution, not the fix.

**The residual is named rather than argued away, because it is the one case a member
would have covered.** A deployment that changes the pair part-way through a period has
a population of `RULING_CONFIRM` records straddling two configurations and no retained
fact separating them, which is why the clause above refuses the report rather than
offering a reconstruction. What that costs is a report an operator can get by
re-scoping the window around a change they themselves made and dated; what a member
would cost is opening a closed fifteen-member enumeration, on every turn of every
deployment, to carry a value that is constant except across an operator act. §9 records
the trade so that a later ADR weighing #2112's sixteenth member weighs this one beside
it rather than rediscovering it.

> **Normative.** Whether ADR-0231 §13's enumeration should grow **at all** is issue
> #2112's question and is deferred to it by name. This ADR neither answers it nor
> pre-empts it: a later ADR opening §13 for a fault at the send is free to revisit this
> section's answer on its own grounds, and the reasoning above is stated so that such a
> lane can weigh it rather than rediscover it.

### 6. The spend mechanism is not coupled to this figure, and a currency mismatch is ADR-0194 §2's case

> **Normative.** `web_search_cost_currency` is **not** required to equal
> `world_spend_currency`, and no implementation compares them, converts between them,
> refuses one for the other, or reads either setting to validate the other.

> **Normative.** Where the two differ, ADR-0194 §2's non-conversion clause governs
> and is neither widened nor restated here: the declared cost *"is treated exactly as
> an `UNKNOWN` basis is"* by the gate — the allowance where one is configured, and
> otherwise §4's second ground when declared. The **policy** still sees a `PER_CALL`
> basis and `_UNKNOWN_COST_FLOOR` still does not fire, because that floor reads
> `cost.basis` and nothing else.

**The consequence is stated rather than smoothed over.** A deployment that configures
the figure in a currency other than its spend currency, with a ceiling set and no
allowance, reaches an `ALLOW` at the policy and is then refused at the gate with
`SpendUndeterminedError` — recorded as `SearchDisposition.SPEND_REFUSED`, which §13
already has, on the servicing that ADR-0231 §15 puts the gate inside. That is
fail-closed, legible in the audit, and correct: the user authorised the recipient and
the operator's own ceiling refused the spend. Coupling the two settings at load would
buy nothing for it and would cost a real configuration — a deployment metering no spend
at all has `world_spend_currency` unset, and a rule requiring equality would refuse it
a figure it has every right to declare.

### 7. What the implementing lane owes

> **Normative.** **One lane**, briefed from this ADR's merged text and not before it
> is Accepted and merged. It touches `core/config.py`, `tools/`, `app/composition.py`
> and `ai_assistant/testing/`, and it touches `core/protocols.py` and `core/types.py`
> **not at all**: no Protocol, no type, and no field added to one. **It is a
> substantive contract change all the same** — two `core.config.Settings` fields are
> *"a `core/` type crossing subsystem boundaries"* in ADR-0015 §5's terms — which is
> why this ADR ships as its own PR and is ratified before the lane opens, and §12 is
> where that route is stated. No lane reads the `core/protocols.py` sentence above as
> licence to implement ahead of this ADR's merge.

**Why one lane and not four, under ADR-0137 §1 rather than under `CLAUDE.md`'s short
form.** The bound is not "one subsystem per change" flatly; it is *"A slice is one lane
only if its implementation puts substantial **new machinery** into at most one
subsystem"*, and §1's second clause is explicit that *"Adaptation does not count against
the bound in this section. A lane may carry adaptation across any number of
subsystems."* §1 names the distinction in terms — new machinery is *"a store, a loop, a
codec, a producer, a policy engine"*, and adaptation is *"a call site updated, **an
argument threaded through**, a method added to a class that already had the rest of
them"*.

> **Normative.** **The classification of this lane under ADR-0137 §1 is that at most
> one subsystem receives new machinery, and it is `core/config.py`**: two fields and
> their refusals, and even those are built from `_checked_spend_amount` and
> `world_spend_currency`'s shape check, which already exist. Everything else is
> **adaptation** in §1's own sense — two keyword parameters threaded through a builder
> that already takes ten onto a constructor call it already makes; two values passed on
> the composition path that already passes three; the same pair on a canonical fake
> whose constructor already takes bounds and already refuses them. **This lane invokes
> no exception**: it needs neither ADR-0137 §2's contract-seam widening — it adds no
> Protocol and no triad — nor any other, because §1's bound is not reached. A reviewer
> disputing this disputes which of the four is a second **machine**, and naming one is
> what would decompose the lane.

**Splitting it would cost what this decision exists to buy.** A `core/config.py` lane
landing two fields nothing reads is the figure ADR-0231 §5's own commentary refuses —
*"a bound nothing reads is a figure an operator can set and watch do nothing"* — and a
builder lane landing a parameter the composition root does not pass leaves **every
configured deployment at `UNKNOWN`**, which is the third clause below's whole subject.
The four move together or the window between them is the gap #2111 records.

**Four obligations, one per file, each marked — because §3 of ADR-0089 makes the marked
set the whole of what this ADR obliges, and a per-file requirement stated only in a
bullet list would bind nothing.**

> **Normative.** **`core/config.py`** carries the two fields of §1 with the domain and
> refusals of §2, reusing `_checked_spend_amount` at `floor="zero"` for the amount
> rather than restating ADR-0194 §1's predicate a third time, and
> `world_spend_currency`'s own shape check for the code. The both-or-neither refusal
> and the registration-whole refusal are `model_validator(mode="after")` clauses in
> `_the_search_registration_is_whole_or_absent`'s shape, and each message names the
> field to set or to unset.

> **Normative.** **`tools/builtin.py`** gives `build_web_search_integration` the two
> keyword parameters, builds the per-registration declaration §1 requires, and states
> §2's domain at that site with the `Raises:` entry its docstring already carries for a
> bound.

> **Normative.** **`app/composition.py` forwards both settings to the builder**, on the
> one path that already passes the three bounds, and this is an obligation rather than
> a note: a lane that landed the fields, the builder and every test above while the
> composition root passed neither value would leave **every configured deployment at
> `UNKNOWN`** with a green gate, which is precisely the failure the whole decision
> exists to remove. §8's item 11 is what makes it fail instead.

> **Normative.** **`ai_assistant/testing/searching.py` keeps the canonical fake at
> parity.** `FakeWebSearcher` takes the same pair, in the same domain, and builds its
> declaration the same way — it is the one site §1 admits beside the builder. It is
> refused every state a deployment cannot be in: an amount with no currency, a currency
> with no amount, a negative or uncountable amount, a malformed code, and a `FREE`
> basis by there being no parameter that could ask for one. The module's own reason
> governs — a fake *"ruled on more leniently than the real thing would let a consumer's
> policy test pass for a reason no deployment enjoys"* — and a fake that could be made
> **cheaper** to rule on than any deployment can be is exactly that failure, on the one
> field this ADR moves.

> **Normative.** The lane also lands ADR-0231 §18's item 1 **over the production
> `ThresholdActionPolicy` and the production declaration**, which is the arm that ADR
> could only model. Its premise is now constructible: a deployment with the figure
> configured, a real `RecipientGrants` holding a covering grant, and the assertion that
> the ruling is an `ALLOW` whose `authorised_by` is the grant's id.

### 8. The representative-input tests this decision owes

> **Normative.** The implementing lane owes tests for each of the following, and each
> is a test over behaviour rather than over a call count.

1. **The figure reaches the declaration and the floor stops firing.** Over
   `build_web_search_integration` with the pair set: the registered declaration's
   `cost` is `PER_CALL` with that amount and that code, and
   `ThresholdActionPolicy(grants=…).decide` on a request carrying it, over a covering
   grant, returns an `ALLOW` whose `reason` names the standing grant and whose
   `authorised_by` is the grant's id. Asserted through the **production** policy and a
   real `RecipientGrants`, which is ADR-0231 §18's item 1 made reachable. The policy is
   constructed at the **shipped** thresholds, and the test says so, because §4's
   condition is that no threshold rule fires — a companion arm sets
   `confirm_at_risk=LOW` and asserts the ruling is `CONFIRM` and `covering` is never
   called, which is that condition asserted rather than assumed.
2. **The absence keeps both floors, and the grant is not consulted.** The same wiring
   with neither field set: the declaration's `cost` is `UNKNOWN`, the ruling is
   `CONFIRM`, its reason names both grounds, and the `RecipientGrants` fake fails the
   test if `covering` is called at all — which is `_only_the_disclosure_floor`'s
   zero-consultations property asserted rather than assumed.
3. **A zero figure is a figure.** `web_search_cost_per_call = 0` with a currency
   yields a `PER_CALL` declaration, an `ALLOW` on the covering grant, and a projected
   contribution of `Decimal("0")` at the gate. Its `basis` is asserted **not** to be
   `FREE`, which fails an implementation that mapped zero onto the other member.
4. **Every half-configuration is refused at load, and names its field.** Amount alone;
   currency alone; either set with the registration absent; either set with exactly one
   of `web_search_connection`/`web_search_origin` set. Each raises at `Settings` load
   and the message names a field to set or unset.
5. **Every out-of-domain amount is refused at load.** Negative; non-finite in each of
   `Decimal("Infinity")`, `Decimal("-Infinity")` and `Decimal("NaN")`; at or above
   `Decimal("1E15")`; and with a tenth fractional digit. And `Decimal("1.0000000000")`
   is **admitted**, because ADR-0194 §1's predicate is a test on the value and not on
   the representation.
6. **A malformed currency is refused at load**, in `world_spend_currency`'s own cases:
   lowercase, four letters, two letters, digits, the empty string.
7. **The builder refuses the same states the `Settings` do**, driven directly, which is
   what makes the two statements one rule rather than two that can drift.
8. **The canonical fake refuses what a deployment cannot be.** Every case of 4, 5 and 6
   asked of `FakeWebSearcher`'s constructor, plus the assertion that no argument of any
   name produces a `FREE` basis.
9. **The module constants do not move.** `WEB_SEARCH.cost` and `FAKE_WEB_SEARCH.cost`
   are `UNKNOWN` after a registration built with a figure — the §1 clause that keeps a
   recorded decision's definition from being edited under it.
10. **The audit is unchanged.** A `CONFIRM` with the pair unset and one with it set but
    no covering grant are both recorded `RULING_CONFIRM`, and `SearchDisposition` has
    fifteen members. This is §5 asserted, and it fails a lane that reached for a
    sixteenth on the way past.
11. **The composition root forwards both values, asserted end to end.** Over
    `app/composition.py`'s own wiring, with `Settings` carrying the pair and a
    connected account: the declaration the built `WebSearchIntegration` registers is
    `PER_CALL` with that amount and that code. **Not** asserted over the builder called
    directly, since that is what item 1 does and it is exactly the assertion a
    composition root that dropped the pair would still pass. This is the arm §7's
    third clause exists for.
12. **A configured fake carries the figure it was configured with.** `FakeWebSearcher`
    constructed with `Decimal("1")` and `"USD"`: the `ActionRequest` its `request`
    returns carries a `tool` whose `cost` is `PER_CALL` with exactly that amount and
    that code, and one constructed with neither carries `UNKNOWN`. This is §7's parity
    clause asserted on its **happy path**, and it is owed separately from items 8 and
    9 because those two are jointly satisfiable by a fake that refuses every bad pair,
    leaves `FAKE_WEB_SEARCH` alone, and then hands out the `UNKNOWN` constant whatever
    it was constructed with — the one implementation the rest of this list cannot
    fail.
13. **A zero figure in a mismatched currency is refused at the gate, not at load.**
    `web_search_cost_per_call = 0` with `EUR`, `world_spend_currency = "USD"`, a
    ceiling set and no allowance: `Settings` loads, the policy rules `ALLOW` on a
    covering grant, and the `SpendGate` refuses. This is §3's stated residual and §6's
    consequence asserted, and it fails an implementation that coupled the two
    currencies at load or silently converted between them.

### 9. Deferred, by name, each with what fires it

- **An operator-configured cost for `send_email`, or for a registered integration in
  general.** `send_email` declares `UNKNOWN` too, and the same argument would reach it.
  It is not taken here because the consequence is different — `send_email` is `HIGH`
  and `IRREVERSIBLE`, so its `fired` is never the singleton route (b) needs and no cost
  figure makes it reachable — and because a general rule about operator-declared costs
  is a change to ADR-0016 §1's declared-by-the-author framing rather than a second
  instance of ADR-0231 §5's clause. Fired by an ADR deciding that framing, or by a
  registered integration whose reachability actually turns on it.
- **A `SearchDisposition` member distinguishing the cost ground.** §5's answer is no,
  on ADR-0231 §13's own standard. Fired by an ADR opening that enumeration — #2112 is
  the live candidate — **together with** a reader who would act differently on the two,
  which §5 argues does not exist while the ground is a constant of the deployment.
  **The one case that argument does not cover is named here so a later ADR weighs it
  rather than rediscovering it**: a population of `RULING_CONFIRM` records straddling a
  change to `web_search_cost_per_call` cannot be separated by ground from anything this
  system retains, which is why §5's second clause refuses the report over such a
  population instead of offering a reconstruction. That is the whole of what a member
  would buy, and it is judged not worth opening a closed fifteen-member enumeration on
  every turn of every deployment for. A later ADR that disagrees has the residual
  stated, the cost stated, and #2112 to take it with.
- **A per-tool or per-capability spend ceiling for the search.** ADR-0194 §1's last
  clause reserves it and ADR-0231 §15 sets none. ADR-0194 §8 states the trigger and this
  ADR does not touch it: *"Reopened by a decision that lands keyed per-user tool
  configuration — ADR-0016 §7's deferred 'tool enablement and per-user configuration',
  which is the store such a ceiling needs — and by nothing else."* Not fired by a lane
  finding a search expensive.
- **A shipped default for either `world_spend_*` ceiling, now that ADR-0194 §8's own
  trigger has fired.** That section defers a default ceiling *"until **any priced
  invocation can execute with no per-call user act**"*, and records that *"Nothing in
  the tree declares a `PER_CALL` cost today"* — which is why the route was *"open and
  unwalked"*. This decision is what walks it: with the figure configured and a standing
  grant established under ADR-0235, a priced search executes on no per-call act. **This
  ADR names the trigger and does not take the deferral**, because ADR-0194 §8's first
  clause is explicit that *"Nothing in this section grants a later lane the thing it
  defers. Each item is reopened by its own ratified decision and by nothing else"*.
  Recorded as issue #2116. Fired by that ADR, which needs a real provider's figure to
  weigh and is therefore not a thing this lane could decide from the corpus.
- **Reading the figure from the provider rather than from the operator.** A price the
  far end quotes would be a fact supplied by the party being paid, deciding an input to
  the ruling on whether this system may talk to that party — which is the direction
  ADR-0154 §4's actuator clause refuses at this seam, and which ADR-0148 §3's second
  clause already refuses in its own terms for *"a configured base URL or host"*. Fired
  by an ADR deciding how a priced remote seam is attested, and this deferral is stated
  so that a lane reaching for a provider's pricing endpoint knows it is a decision and
  not an optimisation.
- **A figure that varies by call.** ADR-0016 §4 is explicit that `cost` *"deliberately
  does **not** model money the tool moves"* and that per-parameter spend needs the
  schema introspection §7 of that ADR defers. One search, one figure. Fired by that
  deferral being taken.
- **Model-spend accounting for the composer's call.** ADR-0231 §15's deferral,
  inherited whole and untouched: this ADR prices the **provider** call and says nothing
  about the completion that composed the query.

### 10. Scope, and what this records against earlier ADRs

**This ADR records nothing against any earlier ADR, and that is a judgement made here
so that it can be reviewed here.** It is a classification of this change and is stated
as prose rather than marked (ADR-0089 §1). ADR-0082 §1 requires that the judgement be
made in the later ADR's text, that it name the clause, and that a reviewer be able to
overturn it *"by naming the sentence of the earlier ADR that does, or does not, become
false or over-wide"*. The candidates, each with the test's answer:

**ADR-0231 §5's four-fields clause — the one a reader will reach for first.** It says:

> **This decision adds exactly four `Settings` fields, each with the named default,
> stated domain and load-time refusal ADR-0230 §6 requires of its own.**

After this ADR, ADR-0231 still adds exactly four. The sentence is about what **that
decision** adds, and a fifth field added by a different decision does not falsify it —
ADR-0082 §1's *"Adding an obligation that contradicts no sentence the earlier ADR wrote
is a **stacked addition**: it is recorded in the ADR that makes it, and nowhere else."*
Two independent pieces of evidence say the clause was never a closure on the namespace.
**First, the contrast with ADR-0194 §1**, which closes its own list in terms — *"They
are the whole of what this mechanism **adds** to configuration: no lane adds a fifth
field"* — a sentence ADR-0231 §5 conspicuously does not carry. **Second, ADR-0231's own
implementation**: `web_search_connection` and `web_search_origin` are `Settings` fields
this same kind needs, added by ADR-0231's own lane, and `core/config.py` states the
reading in terms — *"These are the connected account's configuration and not two more
of ADR-0231 §5's four bounds"*. The clause has already been read as scoped to the
bounds it enumerates, on `main`, by the lane that wrote it.

**ADR-0231 §5's declaration clause is exercised, not moved.** *"a `cost` that is the
operator's configured per-call figure where one is configured and `UNKNOWN` where none
is"* is the clause this ADR implements. A clause becoming **reachable** is not a clause
becoming false or over-wide, and §1 above builds exactly the two states it names and no
third.

**ADR-0231 §9's clauses all stand entire.** Its fourth clause forbidding a `FREE`
declaration where the figure is unknown is **strengthened** by §3 above, which makes
`FREE` unreachable rather than merely forbidden; its fifth clause, *"The one route to
an `ALLOW` is ADR-0193's standing recipient grant"*, is true before and after. §9's
prose stating that *"Two things make a search serviceable"* is unmarked text in a
marked ADR (ADR-0089 §3), and what it glosses — the fifth clause — is unchanged. This
ADR supplies a third thing the prose undercounted; it does not make the clause the
prose serves read more widely.

**ADR-0231 §13 is untouched** because §5 above adds no member and changes no mapping.
**ADR-0231 §15 is untouched**: *"This ADR sets no ceiling of its own, adds no `Settings`
field for one"* stays true, because a declared price is not a ceiling and §9 above
defers a search ceiling by name.

**ADR-0231 §17's five-lanes clause is not amended either.** §7 above adds a lane, but
§17's sentence is about the lanes **that decision** briefs; the ADR-0235 precedent is
exact, since §12 of that ADR briefs its own lanes for this same kind without recording
anything against §17.

**ADR-0016 is not amended, and the precedent for that is ADR-0231's.** §4 of ADR-0016
glosses `UNKNOWN` as *"the author does not know"*, and after this ADR the search's
`UNKNOWN` also means *"and the operator did not state"*. That reading was already
ratified: ADR-0231 §5's declaration clause put an operator-configured figure on this
declaration, and ADR-0231 §20 recorded nothing against ADR-0016 for it. This ADR
supplies the mechanism for a clause already ratified against ADR-0016 without a record,
so recording one now would be recording a change ADR-0231 made. ADR-0016 §1's substance
is untouched in any case: no safety field acquires a default, nothing is derived from
what the integration is called, and the figure is **declared** — by the party that
knows it, which for an integration registered against one operator's account is the
operator.

**ADR-0194 is not amended.** §6 above takes its §2 non-conversion clause and its §1
countability predicate as they stand and adds no fifth spend field; the two fields §1
adds are a **price**, which §2 already names as an input the projection reads.

**ADR-0235 is not amended.** Its population (b) becomes consequential for search rather
than changing shape: `grantable_decisions` lists the same rows and
`establish_recipient_grant` performs the same act. What changes is that the grant it
records is subsequently **consulted**.

**ADR-0036 §1 is not amended.** *"A threshold is the user's; a floor is the
contract's"* stands: `_UNKNOWN_COST_FLOOR` remains a module constant no argument reaches, and this
ADR changes the **declaration** the floor reads rather than the floor.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Unmarked; a statement about this change rather than an obligation (ADR-0089 §1).

A **stacked addition** throughout, under ADR-0082 §1's own name for it. Nothing above
supersedes a ratified clause wholly or partially, nothing amends one, and §10 states
the working for each candidate against the quoted sentence. Under ADR-0070 §1's test —
*"Any change to what was decided requires a new ADR that supersedes the old one"* —
there is no earlier decision this reverses: every clause it interacts with was decided
to admit exactly the state §1 constructs, and the one clause that reads narrowly on its
face (§5's four fields) has already been read the other way on `main` by the lane that
wrote it.

**The reading under which a record *is* owed was available and is not taken.** It would
run: a reader of ADR-0231 §5 counting search `Settings` fields gets four and would now
get five, so the clause reads more widely than it holds. It is not taken because the
clause's subject is what ADR-0231 adds, not what the kind may ever have, and because
taking it would require the same record for `web_search_connection` and
`web_search_origin`, which are already on `main` with none. A reviewer who disagrees
has the route ADR-0082 §1 gives them: name the sentence, and the record is a header-only
`Status` addition on ADR-0231 in `template.md`'s first-partial form beside its existing
partial-supersession pair, with no body byte moved.

### 12. Marking, review and ratification

Unmarked; a record of route rather than an obligation.

This ADR is **marked** under ADR-0089: the block-quoted clauses are the whole of what
it obliges, and the prose beside them is read to determine what they mean and supplies
no obligation of its own (§3).

**It is a substantive contract ADR under ADR-0015 §5** — its two
`core.config.Settings` fields are *"a `core/` type crossing subsystem boundaries"*, read
by `app/`, `tools/` and every other consumer of `Settings` — so it *"ships as its own
PR, ratified before the implementation PR that depends on it"*, which is what this PR
is and why §7's lane does not open until it merges. §7's first clause states the same
classification, and nothing in this ADR reads the absence of a `core/protocols.py` or
`core/types.py` change as putting it outside that route.

ADR-0015 §1's **mechanical** test for the architecture lens — *"A change touching
`core/protocols.py` or `core/types.py`"* — does not reach it, and it is put through
**both** required reviews all the same, adversarial and architecture, green on one
tree. Two grounds, neither of which an author should decide narrowly for themselves:
the `Settings` surface above, and the fact that this decision changes the
`ToolDefinition` a `PermissionDecision` is recorded against — the one field of that
declaration standing between a granted search and an `ALLOW`.

It is drafted, reviewed and revised as `Proposed`, and its status is flipped only once both have returned clean, by the
one-line `Proposed` → `Accepted` flip ADR-0165 exempts. `CONTRIBUTING.md` →
"Finishing an ADR PR" is the sequence and is pointed at rather than re-argued. Nothing
implements against §§1–8 until this has merged (ADR-0015 §5, golden rule 5).

## Consequences

- **A standing grant starts changing the answer for a search.** ADR-0235 gave the user
  an act; this gives that act an effect. The two together are what make ADR-0231 §18's
  item 1 — *"the search is `ALLOW`ed on route (b)"* — reachable through the production
  policy with the production declaration, which is the arm PR #2108 could only model
  over a fake declaration it constructed itself.
- **A deployment that wants a search has one more thing to configure, and it is told
  so.** The failure mode this ADR most wants to avoid is an operator who connects an
  account, grants the recipient, and gets a `CONFIRM` with no clue why. §4's
  description clause is the whole of the answer, and it is cheap: the sentence lives
  next to the field.
- **The `UNKNOWN` state stops being a bug and becomes a choice.** An operator who does
  not know their per-call price gets exactly the behaviour ADR-0016 §4 designed —
  policy fails closed — and now knows that is what is happening.
- **Two more ways to get configuration wrong.** Half a pair, and a pair with no
  registration. Both are refused at load with a message naming the field, which is the
  trade `_the_search_registration_is_whole_or_absent` already made once for this kind.
- **A currency mismatch is now reachable and is refused late.** A deployment can
  configure `EUR` for the search and `USD` for its spend ceiling, reach an `ALLOW`, and
  be refused at the gate on every call. §6 states it rather than preventing it, because
  the alternative refuses a deployment that meters no spend at all. An operator meeting
  it reads `SPEND_REFUSED` in the audit, which is the disposition ADR-0231 §13 already
  has for it.
- **The canonical fake gains a knob, and a narrow one.** `FakeWebSearcher` becomes
  configurable into the two cost states a deployment can be in and no others, which is
  one more constructor argument for every consumer to ignore and one fewer way for a
  policy test to pass for a reason no deployment enjoys.
- **The corpus acquires its first `PER_CALL` cost, and ADR-0194's arithmetic acquires
  its first real operand.** Every `cost` on `main` today is `FREE` or `UNKNOWN`, which is
  why ADR-0194 §8 could call the priced route *"open and unwalked"*. It is walked now,
  and with no `world_spend_*` ceiling configured a granted search is metered and refused
  by nothing — §1's *"unset means unbounded"* working as decided. §9 names that as
  ADR-0194 §8's own trigger and issue #2116 carries it.
- **`send_email` keeps its `UNKNOWN` cost, visibly.** §9 defers the general case and
  says why the consequence differs. A reader who notices the asymmetry now finds it
  argued rather than unexplained.

## Alternatives considered

- **A ratified "CONFIRM-forever on the cost ground".** The other option #2111 names.
  Rejected: it would make the first limb of ADR-0231 §5's declaration clause — *"where
  one is configured"* — dead letter, would require superseding it to say so, would make
  ADR-0235's population (b) pointless for the one kind ADR-0235 §8 wrote its
  refused-search message for, and would leave ADR-0231 §18's item 1 permanently
  unreachable in production. It also contradicts ADR-0231 §9's own promise that
  inertness is not permanence.
- **Suppressing `_UNKNOWN_COST_FLOOR` for this declaration.** Rejected outright:
  ADR-0231 §9's fourth clause names *"a deployment setting that suppresses the
  disclosure floor"* as a mis-declaration, and the same reasoning reaches the cost
  floor; ADR-0036 §1 makes a floor take no setting; and it would give a search a
  privilege no other declaration has, on the strength of nobody having priced it.
- **A single `Settings` field holding a `ToolCost` as JSON.** Rejected: it would put a
  `core` type's serialisation in an environment variable, admit bases §3 forbids, and
  fail at load with a pydantic error about a nested model rather than a sentence naming
  a field.
- **Defaulting the currency to `world_spend_currency` where set.** Rejected on ADR-0016
  §1's rule that a default is a claim: it would claim the operator's provider bills in
  the currency they meter in, which is a guess about a commercial fact, and it would
  make the declaration depend on a spend setting §6 keeps it independent of.
- **Requiring a strictly positive figure, so that a free tier must be declared
  `FREE`.** Rejected: it would force the one basis §3 makes unreachable, and
  `ToolCost.amount`'s own floor is `>= 0`, so zero needs no accommodation anywhere.
- **A sixteenth `SearchDisposition` member.** Rejected in §5 against ADR-0231 §13's own
  standard, and deferred to #2112 by name rather than settled quietly.
