# 264. A turn that reached outside this system says so, and a reply cannot deny it on a surface that renders the statement

- Status: Proposed
- Date: 2026-09-13
- **Partially supersedes** [ADR-0242](0242-the-act-that-trusts-a-destination-has-its-own-surface-and-a-search-that-did-not-happen-is-explained-in-the-reply.md)
  — **§6's first clause, in its second sentence alone.** That sentence reads *"On every
  other turn it is given nothing, and the assembled prompt is byte-identical to what it is
  today"*, and it is false of a turn §6 below's carrier covers: a search that reached the
  provider and was answered records no `SearchDisposition`, so that turn carries no
  `SearchNotServiced` member and is one of the "every other" turns — and §6 below gives
  the composing stage a fragment on it. **The first sentence binds entire**: a turn on which
  at least one servicing recorded a disposition is still given one member of §8's vocabulary
  and still composes an answer that says so. §6's eligibility condition, its
  `NO_RESULT` clause, its notification clause and its `reply_degraded` clause bind entire,
  §7's carrier, §8's vocabulary and mapping and §9's statements are untouched, and §§1-5 and
  §§10-18 stand entire. ADR-0070 §1's test is met and its §3's partial form is the sanctioned
  tool: a reader holding only that ADR would assert a byte-identity that no longer holds.

## Context

### Where this comes from

Issue [#2268](https://github.com/leonapivato/ai-assistant/issues/2268), raised by
the milestone 31 QA re-run, drive C2: *"Turn 2 fired a search to the configured
provider … the composed reply told the user 'nothing was searched just now.'"*
The issue states the asymmetry that produced it:

> ADR-0242 §6/§8 make a turn say a search did not happen, with a typed statement,
> when a servicing yielded nothing. There is no counterpart for the inverse: a
> servicing that succeeded contributes records to the supply, and whether the reply
> acknowledges it is left to the model's prose. So a reply can deny an outbound call
> that the trail records.

and names what is owed:

> whether a turn that dispatched an outbound call owes a typed, surface-rendered
> statement that it did — the mirror of ADR-0242 §6 — so the trail and the reply
> cannot disagree about whether the world was contacted.

The owner's 2026-09-13 note lists *contradictory reporting* among milestone 31's
remaining failures. **What this decision supplies against it is an authoritative
counterstatement and not a prevention**: §7's statement is composed by code from a typed
value and stands beside the reply whatever the reply says, so a denial is **exposed** on
the surfaces that render it. No clause here stops a model writing one, and §10 says why.

### The tree, read rather than assumed, at `origin/main` `a520b891`

- **The negative half is built and the positive half is not.** `TurnOutcome`
  carries `search_not_serviced` (ADR-0242 §9), `orchestration.composing` holds
  `_SEARCH_NOT_SERVICED_PROMPTS` — one fixed fragment per member — and
  `interfaces.cli._render_search_not_serviced` renders one fixed statement per
  member beside the reply. Nothing anywhere carries the fact that a lookup **was**
  made.
- **The records arrive indistinguishable from stored ones.** A serviced
  `WEB_SEARCH` puts `MemoryRecord`s into the turn's supply, which reach the
  composing stage as `turn.memories` — the same shape a relevance read produces.
  The model is not told which of them arrived this turn from outside, and there is
  no field in which it could be.
- **The plan block actively invites the denial.** `orchestration.composing`'s
  `_render_plan` closes a decline with *"Nothing: the planner named no capability
  for this turn, so no action was taken"*. The line that scopes that statement,
  `_PLAN_IS_ABOUT_ACTING` — *"nothing above says whether a lookup was made"* —
  is appended **only** where `search_unserviced` is true (#2213). On a turn whose
  search succeeded it is not appended at all, so the plan block reads as an account
  of the whole turn and says no action was taken. That is the sentence #2268
  observed coming back.
- **The servicing site already holds the fact.** `orchestration.reads.ServicedRead`
  carries `kinds` and `disposition` per servicing, and `SearchDisposition` is a closed
  seventeen-member vocabulary naming *the stage that produced the outcome*.
  `SearchRefusal.NO_RESULT` is deliberately not among them, because a search that
  reached the provider and yielded nothing is a completed servicing.
- **And it already holds which records came from outside.** `ServicedCarriers.minted` is
  ADR-0249 §7's carrier: *"the ids of the records this servicing's `WEB_SEARCH` ask
  **minted**, in the order §10 minted them"*, empty on a servicing that carried no such
  ask and on one whose search did not yield. Its own docstring states this decision's
  premise — *"a minted record sits in `memories` beside every other, which is the whole
  point of ADR-0226 §7's fourth group"*.
- **`ServicedRead.supplied` is a count in the *other* direction.** `_serviced_search`
  assigns ADR-0238 §11's count from `_search_supply`'s result before the query is composed
  and before anything is sent, so it says what left and not what came back (§4).
- **`Disposition.EXECUTED` is the gate's verdict and not the call's result.**
  `StepOutcome`'s own docstring is explicit: *"a client that renders success from
  `disposition` alone is wrong — `EXECUTED` says the permission gate let the call through
  and the executor committed **something**, not that the something succeeded"*.
- **And the servicing is not the only site that performs the call.** ADR-0244 §7's
  resume runs the parked read's one call from `ParkedReadOperations._dispatched`, which is
  no servicing and drives no step; the records it returns are admitted later, by
  `admitted_fourth_group` inside `LearningLoop.resumed_read`. ADR-0242's negative member
  already rides that path — the engine sets `search_not_serviced` from
  `answered.not_serviced` — so the mirror is owed there too.
- `TurnOutcome` carries fifteen members today, **nine** of them added by a later ADR as
  a `None`-defaulting widening a client renders on its own.

### The gap this closes, stated exactly

ADR-0242 §6 makes eligibility *"the disposition's presence and nothing else"*, and
its second clause states the consequence in terms: *"A turn on which every
servicing yielded records carries **no** `SearchNotServiced` member."* That is
correct for what §6 decides and is precisely the hole: on the successful turn the
system says nothing, has no field in which to say anything, and hands the model a
plan block that accounts for acting alone. The user is then told whatever the
model infers — and #2268 records it inferring the opposite of the truth.

### What this ADR is not allowed to settle

- **ADR-0242 §6's not-serviced statement.** Every clause of §§6-9 binds entire and none is
  narrowed, widened or re-read here — **with one exception, recorded in the header rather
  than taken quietly**: §6's byte-identity sentence, which this decision falsifies and
  partially supersedes (§14).
- **The browser's rendering arrears.** Issue #2237 records that the browser renders none
  of ADR-0242 §9's statements; that is its own lane, not this one (§9).
- **What the model writes.** No clause here inspects, classifies or corrects a
  composed reply.

## Decision

### 1. The eligibility condition: this turn reached outside itself, and the trail is what establishes it

> **Normative.** A turn carries the statement this decision mints on, and only on, a
> turn for which **at least one outbound contact is established** by §2. On every
> other turn it carries nothing, the composing stage is given nothing, and the assembled
> prompt is byte-identical to what it is without this decision — the guarantee ADR-0242
> §6 makes for its own carrier, ADR-0228 §10 for its own and ADR-0227 §3 for its own.

> **Normative.** **The condition is stated over what the trail establishes and never
> over what the turn produced.** It does not turn on whether records reached the supply,
> on whether the supply ended non-empty, on whether the reply looks complete, or on
> anything a model returned. A contact that reached outside this system and came back
> with nothing is a contact, and a turn that searched and then answered from memory
> alone still made one.

> **Normative.** **Establishment is one-directional and the residue is silence.** Where
> the trail does not establish a contact the turn carries no statement, and no component
> infers one from a latency, a supply that grew, a record's shape, a provider's name in
> a configuration, or the absence of a refusal. A statement that might be false is worse
> than none, because its whole value is that a reader may rely on it.

**This is the mirror stated at ADR-0242 §6's own strength, and the two conditions do not
overlap by construction.** §6's is *the disposition's presence*; this one is *the contact's
establishment*. A turn may satisfy both — one servicing refused before it sent, another
sent and was answered — and §8 rules that both statements are then carried and both
rendered. Neither suppresses the other, because they are answers to different questions and
a user reading one has not been told the other.

### 2. A search contact, established from the disposition the servicing recorded

> **Normative.** **This section binds at every site that performs a `WEB_SEARCH` call,
> and there are two today**: the servicing in `ai_assistant.orchestration.reads`, and
> ADR-0244 §7's **dispatch on the resume**, which runs the parked read's one call after
> the user answers. Each computes the fact **at its own site**, from the outcome it holds
> and by the partition below, and carries it out beside the `SearchNotServiced` member it
> already carries — the placement ADR-0242 §7 fixes for its own member, *"computed at the
> servicing site, by the component that recorded the `SearchDisposition`"*. **No site
> recomputes another's**, and a later site that performs the call performs this
> computation too.

> **Normative.** **The fact is never derived from `SearchNotServiced`.** That vocabulary
> is non-injective by design (ADR-0242 §8) and `UNAVAILABLE` covers both a response that
> arrived and was refused and a transport that failed, which this section's second and
> third groups separate. A site holding only the member cannot compute this fact and does
> not try.

> **Normative.** A site establishes an outbound contact where its call
> **completed and recorded no `SearchDisposition`** — which is a search
> that reached the provider and was answered, records or none, because
> `SearchRefusal.NO_RESULT` maps to no disposition (ADR-0231 §13) — **or** where the
> disposition it recorded is `RESPONSE_TOO_LARGE` or `UNATTESTED`, each of which this
> system reaches only from octets the provider's channel had already returned.

> **Normative.** A call whose disposition is `NOT_CONFIGURED`, `NO_BUDGET`,
> `COMPOSER_DECLINED`, `COMPOSER_UNAVAILABLE`, `COMPOSER_MALFORMED`, `COMPOSER_TOO_LONG`,
> `BINDING_FAILED`, `RULING_CONFIRM`, `RULING_DENY`, `RULING_UNAVAILABLE` or
> `SPEND_REFUSED` establishes **no** contact. Every one of those is a stage before the
> send: no query was composed, no ruling was obtained, or the send was refused on a
> ceiling, and `NO_BUDGET`'s own definition is that *"no request is composed, no ruling
> is sought and no channel is opened"*.

> **Normative.** A call whose disposition is `TRANSPORT_FAILED`, `DEADLINE_EXPIRED`,
> `SEARCH_FAILED` or `PROVIDER_REFUSED` establishes **nothing either way**, and the turn
> carries no statement on its account. A refused connection, an expiry of
> `search_call_deadline` and a fault raised out of `WebSearcher.search` are each
> consistent with a request that left and with one that did not; and `PROVIDER_REFUSED`
> is recorded **both** for a response the provider gave and this system refused **and**
> for an account that changed across the credential read, whose limbs *"discarded the
> credential and wrote nothing to any channel — none was opened"* (ADR-0148 §6). None of
> the four carries a value separating its causes. **The non-asserting direction is taken
> deliberately**, and §12 defers the finer answer with its trigger.

> **Normative.** **A contact is established the moment a response arrived, and nothing
> that happens to the enclosing servicing afterwards unmakes it.** The discriminator is
> over the **call** and never over the servicing's completion: before the send there is no
> contact, a response that arrived is one whatever the servicing's disposition, and the
> send itself asserts nothing either way. A servicing whose `WEB_SEARCH` was answered and
> whose later `SIGHTED_QUERY` then raises carries the contact its call established, and so
> does one whose recorded disposition places it in the second group above.
> **What ADR-0226 §5 discards is the records and not the call**: a failed servicing
> zeroes its counts, so `records` counts what entered the supply, which on that turn is
> none — and §4 rules that a `records` of `0` never suppresses the statement.

> **Normative.** **The fact is therefore established where it is known — at the performing
> site, from the outcome it holds — and is carried out of the servicing on every path out
> of it, the failed one included.** That is the fold `ServicedCarriers` already performs:
> `not_serviced` and `minted` are *"folded onto the servicing's carriers on **every** path
> out of the body above — the completed servicing, the degraded one, and the one whose
> searcher raised"*, and this fact rides the same one. **No site re-derives it from
> `ServicedRead.disposition` after the servicing has ended**, because an absent disposition
> on a failed servicing covers both a search that was answered and a servicing that raised
> before its search was serviced, and the record holds nothing that separates them —
> `failed_after_read_returned` is stated over *reads* and not over the send. A site that
> performed no call establishes nothing either way.

> **Normative.** **That partition is total over the seventeen members
> `SearchDisposition` is closed at**, and the absence of a disposition is the eighteenth
> case. A `SearchDisposition` member minted by a later ADR establishes **nothing either
> way** unless that ADR's own text places it, which is the least-claiming direction and
> ADR-0242 §8's own default read on this question.

> **Normative.** **No component re-derives the partition from a member's name, its
> value, its declaration order or its docstring.** It is a mapping stated here and
> written once in `orchestration`, and a member added without an arm fails rather than
> falling to a default — the discipline `QUERY_DISPOSITIONS` and `SEARCH_DISPOSITIONS`
> already hold in that module.

**Three groups and not two, because the vocabulary genuinely holds three answers.**
`SearchDisposition` names *the stage that produced the outcome*, and a stage is not a wire
fact: an outage, an expiry, a raised fault and a provider's refusal are each recorded
without recording whether anything crossed the wire, because each is reached from more
than one producing path and the paths disagree. Forcing that third group into either of
the others would be this decision asserting a fact its inputs do not establish, which is
exactly what ADR-0242 §8 refuses when it states each member *"over what its inputs
establish and never over a cause they do not"*. **The user is not left silent there**:
every member of the third group already carries a `SearchNotServiced` member under
ADR-0242 §8 — `INTERRUPTED` for `DEADLINE_EXPIRED`, `UNAVAILABLE` for the other three —
and §6's third clause already forbids `UNAVAILABLE`'s statement from saying that no
request was made.

**The tree states both halves of that partition already, in `tools/web_search.py`, and
this section is that statement read for a different consumer.** `_result_of`'s docstring
puts `SPEND_REFUSED` before the send in terms — it *"reaches no claim at all and so reaches
this function never"* — and puts `NO_RESULT` and `UNATTESTED` after a response in terms:
*"answers a provider gave: the call was made, it completed, and what came back is not
something this system will carry"*. For `DEADLINE_EXPIRED` it gives the third group its
reason: a search *"whose query may have left the machine and may have been served and
billed"* is *"the one direction ADR-0014 §4 refuses to guess in"*.

**Two readings of that docstring have to be kept apart.** It also groups
`RESPONSE_TOO_LARGE` with `TRANSPORT_FAILED` and `PROVIDER_REFUSED` as *"calls that did
not complete as calls"* — a statement about the **invocation's** outcome, which is what
the ledger row and ADR-0192 §3's completion are written from. It is not a statement about
whether bytes crossed the wire, and this section asks only that. A response too large to
carry is a response that arrived, because that member is reached only from a reader
counting octets off the channel; a refused connection is not, and a provider refusal is
recorded for both.

**And absence here asserts nothing, which is why the third group is not the guess ADR-0014
§4 refuses.** That rule bites where a record must take one of several values and one of
them would be false; `INDETERMINATE` is what it buys. Here the statement is present or it
is not, and an absent one claims nothing about the wire — so the user is told the honest
indeterminate rather than a sentence this system cannot support.

### 3. No other outbound seam establishes a contact here, and the egress one expressly does not

> **Normative.** **This decision establishes a contact from a `WEB_SEARCH` call and from
> nothing else.** A driven step establishes none, whatever its binding, its disposition or
> its addressed status; no component mints an `OutboundContact` from an `EgressBinding`,
> from `Disposition.EXECUTED`, from `StepStatus.SUCCEEDED` or from any combination of them;
> and a turn whose only outbound act was a send carries no member and leaves the assembled
> prompt byte-identical to what it is without this decision.

> **Normative.** **The reason is that no value this system holds establishes it**, and
> ADR-0192 §4 says so in terms. `SUCCEEDED` is *"bounded by ADR-0031 §4 to exactly three
> facts — a validated callable return, an unexpired deadline, and no increase in the
> cancellation count — and none of them is a transmission"*; *"an egress callable that
> returns normally without putting a byte on the wire produces `SUCCEEDED` like any
> other"*; and *"nothing available today could carry it"*, because *"a transmission fact
> would have to come from the integration, and `ToolImplementation` returns `FrozenJson`
> with no channel for one"*. An earlier draft of this decision established an egress
> contact from exactly that triple and would have rendered *"this turn reached outside this
> system"* on a call that provably never left — the false statement §1 ranks below silence.

> **Normative.** **That is a stated cost and not an oversight** (§12). ADR-0170 §5 already
> has the composing stage told what became of each step, so the reply has an account of the
> *act*; what it lacks is an account of the *wire*.

### 4. `OutboundContact`: what it carries, and the one count it carries

> **Normative.** `core/types.py` gains **`OutboundContact`**, a frozen pydantic model with
> `extra="forbid"` whose fields are exactly: **`destinations`**, a **non-empty**
> `tuple[OutboundDestination, ...]`; and **`records`**, an `int` with `ge=0`. It carries
> **no destination, no host, no origin, no provider name, no connection reference, no
> account identity, no tool identifier, no query and no fragment of one, no record, no
> title, no snippet, no monetary figure, no duration, no `Settings` field name, no
> `SearchDisposition` value, no record id, no decision id and no instant.**

> **Normative.** **`destinations` holds each class contacted once, in
> `OutboundDestination`'s declared order and never in encounter order**, and the model
> **refuses** a value that is empty or that carries a class twice rather than accepting
> one a surface would then render as a contact naming nothing. A turn that contacted one
> class through three servicings carries that class once. **It is not an
> enumeration of a turn's servicings**, which is the direction ADR-0226 §9's
> counts-and-no-copy reasoning and ADR-0228 §10's *"no count, no duration, no guard
> name"* both refuse: what a reader is told is which kinds of thing this turn reached,
> and the system's internal shape stays inside it.

> **Normative.** **`records` is how many records this turn's established contacts put
> into the turn's supply** — the records admitted from those calls, counted as one
> population over the turn. It is a fact about **the turn**, stated over the supply and
> not over any later stage, so it is defined and true on every outcome shape a contact
> can reach, the parked and recovered ones ADR-0170 §4 composes nothing for included.

**"Over the supply and not over any later stage" is the half that had to be got right.**
A count over what the composing stage was given is undefined on a pass that composes
nothing and false on one where a channel's withholding (ADR-0199 §3) left it holding none
of them, and ADR-0170 §4 makes both shapes reachable beside a contact: a turn can service
a search, admit its records, and then park its step for confirmation. Stated over the
supply the count is defined everywhere and claims neither, and §6's fragment is then the
only place a statement about a model's own prompt is made.

> **Normative.** **The admitted set is recorded by the site that performs the admission
> and never reconstructed**, and in particular it is not `ServicedCarriers.minted`
> filtered after the fact. On an ordinary turn that site is the servicing; on ADR-0244 §7's resume it is **the admission in
> `LearningLoop.resumed_read`**, where `admitted_fourth_group` applies the resumed
> supply's deduplication and budget, and which is a different site from the dispatch that
> classified the contact. The rule is ADR-0249 §7's own for `minted` — *"supplied by the
> servicing that knows it and never inferred at the resolution site"* — applied to each
> of the two facts at the site that has it.

> **Normative.** **It is not `ServicedRead.supplied` and no lane derives it from that
> field.** ADR-0238 §11's count is *"how many records this servicing supplied to the
> composer"* — the **query** composer, the population a chosen destination may be told —
> and it is assigned before the query is composed and before anything is sent. It counts
> what left, and a turn that sent two remembered facts to the provider and got five
> results back would report `2` and then `0`. It is also **not** a count of what the
> provider returned, of what a servicing fetched before deduplication, or of anything a
> step produced.

> **Normative.** `records` is `0` on a search that reached the provider and was answered
> with nothing. **A `0` means this turn's supply holds no record its
> contacts brought in**, and it means nothing else.

**The count is stated over admission because that is the fact its own site holds, and no
clause here asserts of any bound that it cannot bite.** Where one response carries two
records under one id the supply takes one and `records` is `1`: ADR-0226 §7's
deduplication is over the whole union, which `admitted_fourth_group` states in terms —
*"two records of one batch sharing an id enter once, and the second consumes no slot"*.
**Neither that case nor a budget truncation is claimed unreachable**, because neither
claim can be made from the seam: `SearchOutcome` constrains a record's provenance and its
attestation and constrains neither identifier uniqueness nor record count, putting
`search_max_results` outside itself as a field *"the configured searcher enforces"*. An
unreachability argued from `tools/web_search.py` would be about the shipped searcher and
not about the seam every `WebSearcher` is wired through; stated over admission the count
needs no such argument.

> **Normative.** **A `records` of `0` never suppresses the statement.** The fact is the
> contact, and a turn that reached outside itself and brought nothing into its supply
> is the case this decision most needs to state — it is the one a user cannot tell from a
> turn that did not look, and telling them apart is what #2268 asks for.

> **Normative.** **Neither the value nor any rendering of it says what the reply did
> with the records.** What a model made of material in its prompt is not a fact this
> system holds. `records` says the records **entered this turn's supply** and no more,
> and no clause here, no field of this model, no prompt fragment and no rendering
> says that they entered the answer, that the answer rests on them, that it is more
> current for them, or that it would have differed without them.

**One count and not two.** A figure for what the provider returned would be a fact about
the system's plumbing that the user can do nothing with, and stating both would put two
numbers in front of a reader who has no way to tell which one matters. The count that
entered the supply is the one that bears on the answer in front of them, and the one whose
`0` is informative: *I reached outside this system and nothing came back that this turn
could use.*

### 5. `OutboundDestination`: a closed vocabulary of classes, never of destinations

> **Normative.** `core/types.py` gains **`OutboundDestination`**, a `StrEnum` valued by
> lower-cased member name, **closed at exactly one member**, which is also the order
> `destinations` renders in:
>
> 1. **`SEARCH_PROVIDER`** — the configured web search provider, which ADR-0247 §1 makes
>    the destination the owner chose and the recipient they granted.
>
> The vocabulary is **added to and never renamed**, and no implementation or later ADR
> adds a second member without the ADR that decides it.

**One member is the point rather than an embarrassment.** The vocabulary is what makes the
next seam's addition cheap — it arrives as a second member rather than as a second carrier
minted from scratch (§12) — so the `destinations` tuple is kept, non-empty and ordered,
rather than collapsed into the member's absence.

> **Normative.** **A member is a class of destination and never a destination.** No
> member names, encodes or is derived from a provider, a host, an account, a connection
> or a tool, and no later member may be one that identifies a particular destination —
> which would put a destination's identity into a reply, on every surface and on a
> channel of unbounded audience, when ADR-0193 §11 will not let even an audit surface
> decode the `authorised_subject` on a row in front of the user who owns it.

> **Normative.** A later outbound seam adds its own member with its own ADR. **It does
> not render as `SEARCH_PROVIDER` and does not render as nothing**: a contact class with no
> member is a contact this system made and did not state, which is the defect this decision
> exists to close.

### 6. The carrier, and what the composing stage is told

> **Normative.** The value is assembled **once per turn**, inside
> `ai_assistant.orchestration`, from the carriers §2 and §4 name and from nothing
> else — the contact classification each performing site computed (§2), and the
> admitted ids each admitting site recorded (§4). On ADR-0244 §7's resume those are two
> different sites and the engine is where the pair is brought together; no site
> recomputes another's fact, and nothing is inferred at the assembly point. It travels to
> the composing stage as data — the shape ADR-0242 §7 fixes for its
> own carrier and ADR-0228 §10 for its own — adds no member to any Protocol, and is
> **never recomputed downstream**.

> **Normative.** **Assembly accumulates and never replaces.** A servicing that establishes
> no contact clears nothing an earlier one established, and one that fails contributes its
> own zero without resetting what an earlier one admitted: §1's condition is *at least
> one*, and §4's count is one population over the turn. A last-writer-wins assembly is
> the defect this clause names.

> **Normative.** **The fragment obligation binds on a contact-carrying pass that
> composes a reply, and on no other.** ADR-0170 §4 requires no composition on a pass whose
> step parked for confirmation or whose `turn` is `None`, and a turn that serviced a
> search and then parked its step for confirmation is exactly such a pass. On it the
> member is carried and the surface statement is rendered exactly as §7 fixes, and there
> is no fragment because there is nothing to give one to — which is not a degradation,
> because the reply the fragment guards does not exist.

> **Normative.** Where the pass composes, the composing stage is given **one fixed
> fragment**, written in
> `ai_assistant.orchestration`, interpolating **`records` and nothing else**. The
> fragment states the two facts every contact has and no others: that **this turn reached
> outside this system**, and **how many records it took in from doing so — which may be
> none, and the fragment says so where it is none**. It asserts nothing about what was
> reached and nothing about material having arrived, because a contact that came back with
> nothing is still a contact and a record in the supply is not a record in the answer. It
> carries no destination, no host, no origin, no provider name, no connection
> reference, no account identity, no query or fragment of one, no record, no title, no
> snippet, no monetary figure, no duration, no `Settings` field name, no
> `SearchDisposition` value, no id and no command name — ADR-0242 §7's bar, binding here
> unchanged.

> **Normative.** The fragment **forbids the reply from denying that this turn reached
> outside this system**, and forbids it from saying that the answer is more current, more
> reliable or better for it. **The prohibition is stated over the contact**, which on this
> decision's one established seam is a lookup, and a later seam's member takes the
> prohibition in whatever terms its own ADR fixes rather than inheriting this one's.
> `_STOPPED_ASKING_PROMPT`'s own bar is the form — *"you have not been
> told any of that"* — and the fragment is stated at both ends: the model is told the fact
> so that it need not guess, and told what the fact does not license so that it does not
> embroider it.

> **Normative.** **`_PLAN_IS_ABOUT_ACTING` is appended on a turn carrying an
> `OutboundContact` too.** #2213 added that line on a turn that did not service a search,
> to stop the plan block being read as an account of lookups; on a turn that *did* reach
> outside, the same block says the same misleading thing and the same line answers it.
> The condition becomes *the turn carries either statement*, the line's own text is
> unchanged, and on a turn carrying neither the block is byte-identical to what it is
> today.

> **Normative.** **No lane widens the carrier to free text.** `destinations` is a closed
> vocabulary and `records` is an integer; a message, a provider response, a query, a
> record or a sentence assembled from any of them is refused here, for ADR-0231 §13's
> no-message reason and ADR-0004 §5's.

**Telling the model is not what makes this decision work, and that is the point.** A
prompt fragment is an instruction to a model, and a model may ignore one — #2268 is a
model ignoring the absence of one. What makes the guarantee structural is §7's rendered
statement, which is composed from the typed value by code and stands beside the reply
whatever the reply says. The fragment is there so the two ordinarily agree; the rendering
is there so that when they do not, the user can see it.

### 7. `TurnOutcome` gains one member, and a surface renders it from the value

> **Normative.** `TurnOutcome` gains exactly one field, **`outbound_contact`**, typed
> `OutboundContact | None` and defaulting to `None`, whose docstring names this ADR as
> the decision that added it. It carries **the value §6 computed, by value, and never a
> second computation**.

> **Normative.** `outbound_contact` is `None` on **every** outcome of a turn that
> established no contact: every such `converse`, `converse_streaming`, `converse_spoken`
> and `resume`; every routed pass (ADR-0197 §7), which ends the pipeline where it routed;
> ADR-0198 §1's **restatement**, which drives nothing and reaches nothing; and ADR-0250
> §3's `UNDECIDED` turn, which takes no read at all. That adds a value to ADR-0198 §2's
> enumeration without changing any value it fixes.

> **Normative.** **A widening and not a change.** ADR-0170 §4's three `reply`-`None`
> shapes and its one `reply_degraded` shape are untouched, no new outcome shape is
> minted, and no member is derived from another — the move ADR-0242 §9, ADR-0235 §4 and
> ADR-0250 §5 each made, none of which recorded a supersession of ADR-0170 for it and
> neither does this one.

> **Normative.** **`converse_spoken` gains no parameter and `SpokenTurn` gains nothing**,
> for ADR-0242 §9's reason: ADR-0200 §4 makes `spoken` *"the rendering of `outcome.reply`
> and of nothing else"*, so the spoken reply is the whole of what that user is told.
> **What is therefore not available on the spoken surface is this decision's guarantee**,
> and that is a stated cost rather than a gap (§12), taking ADR-0250 §15's shape. A spoken
> turn still carries `outbound_contact` and still gets §6's fragment, so the reply is
> composed under the same instruction — but no code-composed statement stands beside it.
> **This decision's title is bounded by that**: a reply cannot deny a contact **on a surface
> that renders the statement**, and the spoken one does not.

> **Normative.** **A surface renders, beside the reply and never in place of it, one
> statement composed from the value**: that this turn reached outside this system, naming
> each class in `destinations` in the vocabulary's declared order, and how many records
> that **brought into this turn's supply** — including that it brought none, where
> `records` is `0`. The exact wording is the lane's; what is fixed is that the statement is built
> from the value, that a `0` is stated rather than elided, and that no surface renders a
> statement for a value it was not given.

> **Normative.** **No statement says a record reached, entered, supported or affected the
> answer.** `records` establishes that the records entered this turn's supply and nothing
> beyond it (§4) — not that a model was given them, and not that one used them — and a
> surface asserting more would be attributing the answer's content to material a model
> may never have seen.

> **Normative.** **Rendering it is presentation and not business logic**, on ADR-0242
> §9's ratified ground and `_render_search_not_serviced`'s precedent. No adapter reads a
> store, joins a row, computes a contact, inspects a reply, or renders anything about a
> turn it was not handed this member for.

> **Normative.** **The statement is composed by code from typed values and by no model's
> decision**, and it **stands where the reply contradicts it** — the relation ADR-0197
> §10 already fixes between a routed account and a composed reply, and ADR-0170 §3's rule
> that no adapter resolves such a disagreement in the prose's favour. No lane suppresses,
> softens or conditions the statement on what the reply says, and none edits a reply to
> agree with it.

### 8. Both statements ride together, and neither is read off the other

> **Normative.** A turn may carry **both** `search_not_serviced` and `outbound_contact`,
> and where it does **both are rendered**, each in its own statement, neither suppressing
> nor qualifying the other. The reachable shape is one turn with two servicings — one
> refused before it sent, one answered — and it is a turn on which both sentences are
> true.

> **Normative.** **Neither member is computed from the other, and no clause of ADR-0242
> §§6-9 is narrowed, widened or re-read here — save the one sentence the header records as
> superseded.** §6's eligibility stays *the disposition's presence and nothing else*; §7's
> precedence order, at-most-one rule and success-does-not-clear rule stay exactly as
> written; §8's vocabulary and total mapping are untouched; §9's statements bind verbatim.
> **The exception is §6's byte-identity sentence alone** (§14): this decision gives the
> composing stage a fragment on a turn that carries no `SearchNotServiced` member, which
> that sentence promised would leave the prompt unchanged. Nothing else of §6 moves, and
> the eligibility condition in particular is untouched — which is why the two conditions
> still do not overlap and neither member is read off the other.

> **Normative.** **One turn's `UNAVAILABLE` now rides beside a contact, and that is the
> design.** Where a response arrived and was refused — `RESPONSE_TOO_LARGE` or
> `UNATTESTED` — ADR-0242 §8 maps it to `UNAVAILABLE`, whose
> statement §9 fixes as saying the lookup produced nothing usable and expressly **not**
> saying that no request was made. This decision supplies the other half of that
> sentence, which §9 declined to assert because it had nothing establishing it. Read
> together they say: a request was made, and nothing usable came back.

> **Normative.** **A servicing that failed after its search was answered is where the two
> conditions most visibly answer different questions, and the reply carries whichever of
> them stands.** Recording no disposition it carries a contact — `records` `0`, because
> ADR-0226 §5 discarded what came back — and **no** `SearchNotServiced` member, ADR-0242
> §6's eligibility being the disposition's presence and there being none. Recording
> `UNATTESTED` it carries **both**, and both are rendered. Neither shape is a disagreement
> between the two statements and neither member is read off the other: one says this turn
> reached outside itself, the other says what act would change what a lookup produced.

### 9. What each surface owes, and where the browser's arrears are answered

> **Normative.** The terminal renders the statement in the implementing lane (§11), beside
> `_render_search_not_serviced`'s, from the member and from nothing else.

> **Normative.** **The browser owes the same statement and takes it in the lane that
> closes #2237**, which is the lane already owed for the `SearchNotServiced` statements
> the browser renders none of. This decision adds its statement to that lane's list and
> **does not mint a browser lane of its own**, because two lanes editing one renderer for
> one rule is the collision that lane exists to avoid.

> **Normative.** A surface that renders no statement for a value it was given **has not
> implemented this section**, and is not exercising a permitted degradation — ADR-0242 §9's
> clause on exactly that, read here. What the browser's arrears are is a lane not yet run,
> which is a different thing from a rendering ruled optional.

### 10. A reply that denies a recorded contact: booked, with the reason

> **Normative.** **Whether a model's denial of a recorded contact is itself a recorded
> defect is not decided here, and no lane mints such a record on this decision's
> authority.** Detecting a denial means classifying the model's own prose against a fact —
> a model judgement over a model's output, in the composing path, whose false positives
> would themselves be recorded as defects. ADR-0227's audit records *acts*; a reply is not
> one.

> **Normative.** What this decision supplies in its place is **structural rather than
> detective**: the statement §7 renders stands beside the reply, is composed by code, and
> cannot be made to agree with a denial. A user reading both sees the disagreement without
> anything having classified it, and an operator reading the trail sees the contact
> whatever the reply said.

**Booked rather than refused, and #2291's audit-recording ADR is where it belongs.** That
work is already owed and is the right place for a question about what the system records
about its own conduct; deciding it here would reach into a decision this ADR has not read.

### 11. The lane cut

> **Normative.** The implementation is **two lanes**, in this order, and neither may
> absorb the other's paths.
>
> 1. **Contract and `orchestration`.** `OutboundDestination`, `OutboundContact` and
>    `TurnOutcome.outbound_contact` in `core/types.py`; §2's establishment at every site
>    that performs a `WEB_SEARCH` call; §4's admitted sets and §6's
>    assembly; the composing fragment and `_PLAN_IS_ABOUT_ACTING`'s widened condition.
>    **It is one lane under ADR-0137 §1 and expressly not under §2**: every piece of new
>    machinery this decision builds — the establishment, the carriers, the assembly, the
>    fragment — is in `ai_assistant.orchestration` and in no other subsystem, and what
>    lands in `core/types.py` is two type declarations and a `None`-defaulting field,
>    which is not *"a store, a loop, a codec, a producer, a policy engine"* but the
>    adaptation §1 puts outside its bound. §2 is unavailable here and is not invoked: it
>    widens the exception for **a contract triad with its primary implementation**, this
>    decision adds no Protocol and no triad, and §2 says in terms that *"any other
>    cross-subsystem pairing remains outside the exception"*.
> 2. **The terminal surface.** `interfaces/cli.py` renders §7's statement (golden rule 3).
>
> The browser's rendering is #2237's lane and is not a lane of this decision (§9).

> **Normative.** **Each arm of §13 is owed by the lane that owns the code it asserts
> over, and no arm obliges a lane to touch the other's paths.** Every arm's assertions
> about the member, the establishment, the admitted count, the composing prompt and
> `OutboundContact`'s own construction are lane 1's; every arm's assertions about a
> **rendered statement** are lane 2's, landed with the renderer they are about — arm 2's
> stated `0` and arm 3's two statements among the arms listed, and equally every rendering
> assertion §13's floor obliges beyond them. **The rule is stated over the assertion and
> never as a count of arms**, because §13 is a floor: a clause fixing which arms carry a
> rendering assertion would go stale the moment the floor obliged one it had not named.
> Lane 1 is complete when it owes no rendering assertion, and a lane that lands an
> assertion over code it does not own has broken the cut rather than honoured §13.

> **Normative.** Lane 1 changes `core/types.py`, so **this ADR is ratified and merged as
> its own PR before anything implements against it** — golden rule 5 and ADR-0015 §5,
> which bind on a `core` change whether or not ADR-0137 §2's pairing is available, and
> which ADR-0137 §2's own third clause restates rather than creates. This PR is that one,
> and it changes no code.

### 12. What this decision does not decide, by name, each with what fires it

> **Normative.** **Whether a `TRANSPORT_FAILED`, `DEADLINE_EXPIRED`, `SEARCH_FAILED` or
> `PROVIDER_REFUSED` servicing reached the world** (§2). For the first three, deciding it
> needs a fact from below the `WebSearcher` seam — whether bytes were written — which no
> value the site holds today carries. For `PROVIDER_REFUSED` it needs less and still more
> than exists: a typed seam value separating a provider's answer from an account change
> that opened no channel, which is a `core` change and takes its own ADR. **Fires** when a
> seam records either, or when a deployment reports a user misled by the silence on one of
> those four.

> **Normative.** **Whether an egress send establishes an outbound contact** (§3). §3
> refuses it because nothing this system holds establishes it, and ADR-0192 §4 states the
> gap rather than leaving it to be discovered: *"a transmission fact would have to come
> from the integration, and `ToolImplementation` returns `FrozenJson` with no channel for
> one"*. **Fires** when a seam carries that a byte was put on the wire — a typed
> transmission fact reaching `orchestration`, which is a `core` change and takes its own
> ADR. That ADR adds `OutboundDestination`'s second member (§5) and states its own
> establishment rule; it does **not** reuse `EXECUTED`, `StepStatus.SUCCEEDED` or an
> `EgressBinding`'s presence, each of which ADR-0192 §4 has already ruled insufficient.

> **Normative.** **Whether a reply that denies a recorded contact is recorded as a
> defect** (§10). **Fires** with the audit-recording ADR #2291 already owes.

> **Normative.** **The browser's rendering of this statement and of ADR-0242 §9's**
> (§9). **Fires** with #2237's lane, which is already owed.

> **Normative.** **A per-servicing or per-call account in a reply or on a surface.** §4
> refuses the enumeration and this ADR mints no route back to one. **Fires** with a
> decision that argues the case ADR-0226 §9 and ADR-0228 §10 argue against.

> **Normative.** **A notification.** No lane mints a `Notification`, a notification kind,
> a delivery or a poll result for an outbound contact — ADR-0235 §8's second clause, binding here as ADR-0242 §6 made it bind
> there.

### 13. The arms this decision owes

> **Normative.** The implementing lanes owe these eight arms **between them**, each over
> representative input and split by §11's ownership rule. A lane that lands fewer of the
> assertions it owns has not implemented this decision.

> **Normative.** **The enumeration below is a floor and not a ceiling**, on ADR-0219 §7's
> ground and in its words. **Every normative clause of this decision that an implementation
> can fail is owed an arm**; the list below names *"the ones whose absence would otherwise
> be non-obvious, each with the failure it exists to catch"*, and it is written that way
> deliberately, because *"a conformance list read as exhaustive is ADR-0108 §4's
> 'false-shelter shape' at one more remove, this time in the suite rather than in the
> contract"*. So a lane **adds the arm a normative clause needs whether or not that clause
> is listed here**, and no implementation is conformant on the ground that a rule it
> breaches has no arm below.
>
> 1. **A search that brought records into the supply, over a turn whose pre-existing
>    supply is non-empty.** `destinations` is `(SEARCH_PROVIDER,)`; `records` counts the
>    records the search brought in and **not** the pre-existing ones; `search_not_serviced`
>    is `None`; the prompt carries §6's fragment and `_PLAN_IS_ABOUT_ACTING`. The
>    non-empty pre-existing supply is what makes the arm discriminate: a lane reading
>    `ServicedRead.supplied` passes every other arm and fails this one. **The same search
>    returns two records under one id**, and `records` is the count the supply admitted —
>    the duplicate enters once (ADR-0226 §7) and is counted once — so a lane counting what
>    the response carried fails the arm. No arm asserts that a searcher cannot return such
>    a response (§4).
> 2. **A search that reached the provider and returned nothing** (`SearchRefusal.NO_RESULT`),
>    on a turn whose pre-existing supply is **non-empty**. `outbound_contact` is set with
>    `records` `0`, `search_not_serviced` is `None` (ADR-0242 §6's third clause), and the
>    rendered statement states the `0` rather than eliding it.
> 3. **The partition, asserted over the enumeration itself and then over its two
>    reachable sides.** The arm walks **every member of `SearchDisposition`** and asserts
>    the group §2 places it in, so a member added without an arm **fails** rather than
>    falling to a default — the discipline §18 item 9a of ADR-0231 already holds over
>    `SEARCH_DISPOSITIONS` — and it asserts that `TRANSPORT_FAILED`, `DEADLINE_EXPIRED`,
>    `SEARCH_FAILED` and `PROVIDER_REFUSED` establish nothing either way, the last over
>    **both** its causes, because an implementation reading it as a response is what this
>    arm exists to catch. Then the two sides in a turn: a
>    search refused before the send (`RULING_DENY`) carries **no** contact, carries
>    `search_not_serviced` `DECLINED`, and leaves the composing prompt byte-identical to
>    what it is without this decision; a response received and then refused (`UNATTESTED`)
>    carries **both** members — `outbound_contact` with `records` `0`, and
>    `search_not_serviced` `UNAVAILABLE` — and renders both statements (§8).
> 4. **A parked read the user approved, dispatched on the resume** (ADR-0244 §7), in two
>    shapes: one whose call returns records, **two of them under one id**, so `records` is
>    what `admitted_fourth_group` admitted at the resume's own site and not what the call
>    returned (§4); and one that reaches the provider and returns nothing, which carries a
>    contact with `records` `0`. Neither is a servicing and neither drives a step, and an
>    implementation that computes the fact only in `reads` fails this arm (§2).
> 5. **A turn with two search servicings that both admit records, in both encounter
>    orders**, where `records` is the **sum** of what the two admitted — §4 counts one
>    population over the turn — and `destinations` carries `SEARCH_PROVIDER` **once** and
>    not twice (§4). **A later servicing that refuses before the send (`RULING_DENY`), and
>    one that fails after a response, each leave the contact and the count standing** (§6),
>    and §6's one fragment is given once.
> 6. **`OutboundContact`'s own construction invariants, asserted on the model and not on
>    its producer**, because it is a boundary-crossing value a wire decode also builds: an
>    empty `destinations`, one carrying a class twice, one carrying a **negative**
>    `records` and one carrying an **unknown field** are each refused rather than accepted.

> 7. **A servicing that failed after its search had already been answered**, in three
>    shapes, which are what separate the ruling from the record it cannot be read off.
>    One whose search was answered and whose later `SIGHTED_QUERY` raises, recording **no
>    disposition**: it carries a contact with `records` `0` — ADR-0226 §5 discarded the
>    records, and §4's `0` does not suppress the statement — and `search_not_serviced`
>    `None`. One whose search recorded **`UNATTESTED`** before the same later failure: it
>    carries the contact **and** `search_not_serviced` `UNAVAILABLE` (§8). And one that
>    raised **before** its search was serviced, recording no disposition and performing no
>    call: it carries **no** contact. An implementation that suppresses a failed
>    servicing's contact fails the first, and one that classifies from the ended
>    servicing's record rather than at the performing site cannot tell the first from the
>    third (§2).
> 8. **A driven egress step establishes nothing** (§3): a step whose `ActionRequest`
>    carried an `EgressBinding`, whose disposition is `EXECUTED` and whose addressed
>    `StepExecution` is `SUCCEEDED` carries **no** `outbound_contact`, gets **no** fragment,
>    and leaves the composing prompt byte-identical to what it is without this decision. An
>    implementation that mints a contact from that triple fails this arm.

### 14. Scope, and what this records against earlier ADRs under ADR-0082 §1

> **Normative.** This decision is a **partial supersession of one clause and a stacked
> addition everywhere else.** One sentence of one earlier ADR is falsified — ADR-0242 §6's
> byte-identity sentence — and under ADR-0082 §1 that is recorded in **three** places and
> no others: this ADR's header, ADR-0242's `Status` line, and a dated note on ADR-0242.
> Every other clause a reader might expect a record for is a stacked addition, recorded in
> this ADR and nowhere else. The paragraphs below apply ADR-0070 §1's test to each, naming
> the sentence and the verdict.

**ADR-0242 §9's *"`TurnOutcome` gains exactly one field"* — no record owed.** That clause
states what *that* decision adds, not a closure on `TurnOutcome`; ADR-0244 §9 and ADR-0250
§5 have each since added members without recording against it, and ADR-0250 §5 added four.
A reader holding only ADR-0242 builds `search_not_serviced` exactly as §9 describes it and
is wrong about nothing.

**ADR-0242 §6's byte-identity guarantee — a record IS owed, and it is made.** §6 promises
that on a turn carrying no `SearchNotServiced` member *"the assembled prompt is
byte-identical to what it is today"*. A search that reached the provider and was answered
records no `SearchDisposition`, so that turn is one of §6's "every other" turns — and §6
below gives the composing stage a fragment on precisely it.

**The corpus settles this and settles it against the self-scoped reading.** An earlier draft
argued that §6 scopes the promise per carrier, citing its own *"the same guarantee ADR-0228
§10 makes for its own carrier"*. But ADR-0242's header records **Partially supersedes
ADR-0228 — §10's first clause, in its second sentence alone**, for a sentence of that same
form, falsified in that same way, by that same kind of second carrier. ADR-0242 did for
ADR-0228 exactly what this decision does for ADR-0242, and it recorded it. The phrase
describes where the guarantee came from; it does not exempt the next carrier from recording
against it. The record is therefore made rather than argued away, and ADR-0070 §1's test is
met: a reader holding only ADR-0242 would assert a byte-identity that no longer holds.

**ADR-0170 §4 — no record owed.** A `None`-defaulting member changes neither the three
shapes on which `reply` is `None` nor the one on which `reply_degraded` is `True`. ADR-0197
§8, ADR-0235 §4, ADR-0242 §9 and ADR-0250 §5 made the identical move. Two of them did
record a supersession of ADR-0170 §4, and in both it was for moving a **shape** and not
for adding a member: ADR-0197 §8 made a `turn`-`None` outcome able to carry a reply, and
ADR-0250 §5 added a second `turn`-`None` shape. This decision moves no shape.

**ADR-0198 §2 — no record owed.** The restatement's enumeration gains a value and loses
none: `turn`, `routed`, `reply`, `reply_degraded` and `step` carry there exactly what §2
says, and `None` is the true value of a member describing something a restatement did not
do — as ADR-0242 §9 and ADR-0235 §4 each state for their own members.

**ADR-0226 §9 and ADR-0238 §11 — no record owed, and `records` is expressly not
theirs.** No count is added to, removed from or redefined in the per-turn audit record,
and §4 states in terms that `records` is neither ADR-0238 §11's `supplied` nor derived
from it. The record those sections govern is unchanged and gains nothing.

**ADR-0249 §7's `minted` and ADR-0227 §3's `hop_reached` — no record owed.** §4 reads
`minted` and copies `hop_reached`'s shape; it redefines neither, adds to neither, and
takes neither out of the use its own ADR gives it. A second consumer of a carrier is not
a change to the carrier — the position ADR-0242 §6's own second consumer of
`ServicedRead.disposition` already stands in.

**`_PLAN_IS_ABOUT_ACTING`'s condition (§6) — no record owed.** That line and its condition
come from issue #2213 and from code; no ADR clause fixes when it is appended. Widening the
condition falsifies no ratified sentence.

### 15. This ADR classified under ADR-0070 §1 and ADR-0082 §1

> **Normative.** Under ADR-0070 §1 this is a **partial supersession**, in one clause of
> one ADR and in nothing else: a reader holding only ADR-0242 would act differently about
> §6's byte-identity sentence, which ADR-0070 §1's test makes a record owed rather than a
> matter of taste, and ADR-0070 §3's partial form is the sanctioned tool. **It is not an
> amendment** — no clause of any ADR is read more widely here — and against every other
> earlier decision it stands on its own, which §14 records candidate by candidate.

> **Normative.** This ADR is **marked** under ADR-0089: every obligation it imposes is in
> a marked clause, and text beside a mark is read to determine what the clause means and
> supplies no obligation of its own (ADR-0089 §3). Marking is forward-only (§5) and
> nothing already ratified becomes marked by this.

## Consequences

- **A turn that reached the world now says so, in a statement the reply cannot talk out
  of.** It is composed from a typed value by code and renders beside the reply on the
  surfaces §7 binds, so a reply that denies the contact is contradicted in front of the
  user rather than believed. **The denial is not prevented**: a model may still write one,
  and what changes is that it no longer stands alone (§10, and §7's spoken limit).
- **A `0` becomes sayable.** *I reached outside this system and nothing came back that
  this turn could use* is a sentence the system has never been able to make; it is the
  honest account of a search that found nothing, and it is the sentence whose absence made #2268 read as a
  contradiction rather than as a thin reply.
- **Four dispositions stay silent, on purpose.** A transport failure, a deadline expiry,
  a raised fault and a provider refusal carry no contact statement, because each is
  reached from producing paths that disagree about the wire — `PROVIDER_REFUSED` covers an
  account change that opened no channel as well as a response the provider gave. Each
  already carries a `SearchNotServiced` member whose statement is true, so the user is
  told something rather than nothing. The cost is under-inclusion — a genuine provider
  refusal stops carrying a contact — which is a statement withheld and not a false one
  (§1), and §12 says what would make the honest sentence available.
- **An egress send says nothing at all, and that is the honest position.** ADR-0192 §4
  rules that `SUCCEEDED` is consistent with no byte on the wire and that nothing available
  today carries the transmission fact, so §3 refuses the contact rather than approximating
  it. A send that did reach the world goes unstated until a seam carries that it did (§12).
- **The spoken surface does not carry the guarantee.** `SpokenTurn` gains nothing, so a
  spoken reply that denies a contact is contradicted by nothing the user hears (§7). The
  title is bounded to the surfaces that render the statement, and §12 books the rest.
- **`TurnOutcome` grows to sixteen members**, and `outbound_contact` is the **tenth** a
  later ADR has added as a `None`-defaulting fact a client renders on its own. That is
  ADR-0244 §9's rule working as designed and also the thing to watch: an eleventh and a
  twelfth make a client's rendering order a decision nobody has taken.
- **Revisit when** a seam carries that a byte was put on the wire, when the spoken
  surface gains a rendering of its own, or when a deployment reports a user misled by the
  silence §2's third group keeps.
