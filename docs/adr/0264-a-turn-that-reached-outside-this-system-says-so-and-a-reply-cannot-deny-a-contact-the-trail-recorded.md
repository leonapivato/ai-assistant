# 264. A turn that reached outside this system says so, and a reply cannot deny it on a surface that renders the statement

- Status: Proposed
- Date: 2026-09-13
- **Partially supersedes** [ADR-0242](0242-the-act-that-trusts-a-destination-has-its-own-surface-and-a-search-that-did-not-happen-is-explained-in-the-reply.md)
  — **§6's first clause, in its second sentence alone.** That sentence reads *"On every
  other turn it is given nothing, and the assembled prompt is byte-identical to what it is
  today"*, and §6 below falsifies it for **every turn that composes a reply**: the composing
  stage is given one fragment of this decision's own on each of them, the turns carrying no
  `SearchNotServiced` member included — a search that reached the provider and was answered,
  which records no `SearchDisposition`, and a turn that asked for no search at all (#2365).
  **The first sentence binds entire**: a turn on which
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

**And the same milestone's run found the inverse, which widens what is owed.** Issue
[#2365](https://github.com/leonapivato/ai-assistant/issues/2365), from the M32 acceptance
run driving the browser against the production hub on 2026-09-13: a turn whose trail records
`servicing=not_asked`, `servicings=()` and `stop=not_iterated` told the user its forecast
*"is already in front of me from **this turn's searches**"*. The figures came from retrieved
memory of earlier conversations — a legitimate source, and not what the reply said it was.
#2365 states why an earlier draft of this decision did not refuse it — *"a turn with no
servicing has no statement to render, so there is nothing for the surface to contradict"* —
and why it is the worse half of the pair: *"it is not a missing acknowledgement but a false
provenance claim"*, on exactly the class of fact whose value is its freshness.

**So the requirement is two-directional, and this decision is stated that way.** The owner's
2026-09-13 note lists *contradictory reporting* among milestone 31's remaining failures, and
the trail and the reply disagree in both directions: a reply denying a contact the trail
records (#2268), and one claiming a contact the trail does not (#2365). **What this decision
supplies against both is an authoritative counterstatement and not a prevention**: §7's
statement is composed by code from a typed value and stands beside the reply whatever the
reply says, so a denial and a false claim are each **exposed** on the surfaces that render
it. No clause here stops a model writing either, and §10 says why.

### The tree, read rather than assumed, at `origin/main` `a520b891`

- **The negative half is built and the positive half is not.** `TurnOutcome`
  carries `search_not_serviced` (ADR-0242 §9), `orchestration.composing` holds
  `_SEARCH_NOT_SERVICED_PROMPTS` — one fixed fragment per member — and
  `interfaces.cli._render_search_not_serviced` renders one fixed statement per
  member beside the reply. Nothing anywhere carries the fact that a lookup **was**
  made.
- **The records arrive indistinguishable from stored ones.** A serviced `WEB_SEARCH` puts
  `MemoryRecord`s into the supply, which reach the composing stage as `turn.memories` — the
  shape a relevance read produces. The model is not told which arrived this turn from
  outside, and there is no field in which it could be.
- **The plan block actively invites both errors.** `_render_plan` closes a decline with
  *"Nothing: the planner named no capability for this turn, so no action was taken"*, and
  the line that scopes it — `_PLAN_IS_ABOUT_ACTING`, *"nothing above says whether a lookup
  was made"* — is appended **only** where `search_unserviced` is true (#2213). On a turn
  whose search succeeded, and on #2365's turn that asked for none, it is not appended at
  all, so the block reads as an account of the whole turn.
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
- **`ServicedRead.supplied` is a count in the *other* direction**, assigned from
  `_search_supply`'s result before the query is composed and before anything is sent (§4);
  and **`Disposition.EXECUTED` is the gate's verdict and not the call's result** —
  `StepOutcome`'s own docstring says *"a client that renders success from `disposition`
  alone is wrong"* (§3).
- **And the servicing is not the only site that performs the call.** ADR-0244 §7's
  resume runs the parked read's one call from `ParkedReadOperations._dispatched`, which is
  no servicing and drives no step; the records it returns are admitted later, by
  `admitted_fourth_group` inside `LearningLoop.resumed_read`. ADR-0242's negative member
  already rides that path — the engine sets `search_not_serviced` from
  `answered.not_serviced` — so the mirror is owed there too.

### The gap this closes, stated exactly

ADR-0242 §6 makes eligibility *"the disposition's presence and nothing else"*, and its
second clause states the consequence in terms: *"A turn on which every servicing yielded
records carries **no** `SearchNotServiced` member."* That is correct for what §6 decides and
is precisely the hole: on such a turn the system says nothing, has no field in which to say
anything, and hands the model a plan block that accounts for acting alone. The user is then
told whatever the model infers — #2268 records it inferring the opposite of the truth, and
#2365 records it inventing a reach on a turn that asked for no search at all.

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

### 1. The condition, in both directions: what this turn did about reaching outside itself

> **Normative.** **The statement this decision mints is three-valued, and it is carried on
> every pass that composes a reply.** Its value is **`REACHED`** where **at least one
> outbound contact is established** by §2; **`INDETERMINATE`** where none is and at least one
> call established nothing either way; and **`NOT_REACHED`** otherwise — which includes the
> turn that made no call at all, #2365's shape. A pass that establishes a contact carries the
> statement whether or not it composes; a pass that neither establishes one nor composes
> carries nothing (§7).

> **Normative.** **There is therefore no turn on which the assembled prompt stays
> byte-identical, and that is a cost taken deliberately** — recorded against ADR-0242 §6 in
> the header, where an earlier draft of this decision took that guarantee over for its own
> carrier as ADR-0228 §10 and ADR-0227 §3 have for theirs. #2365 is a turn that would have
> had the byte-identity, and a reply claiming a reach that never happened is what the
> silence bought.

> **Normative.** **The condition is stated over what the trail establishes and never
> over what the turn produced.** It does not turn on whether records reached the supply,
> on whether the supply ended non-empty, on whether the reply looks complete, or on
> anything a model returned. A contact that reached outside this system and came back
> with nothing is a contact, and a turn that searched and then answered from memory
> alone still made one.

> **Normative.** **Neither direction is inferred, and the third value is what keeps that
> true.** No component infers `REACHED` from a latency, a supply that grew, a record's
> shape, a provider's name in a configuration, or the absence of a refusal; and none infers
> `NOT_REACHED` from a supply that did not grow, from a reply naming no source, or from any
> call §2 places in its third group. A value that might be false is worse than none in
> either direction, because the statement's whole value is that a reader may rely on it —
> which is why `INDETERMINATE` exists rather than being folded into `NOT_REACHED`.

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

> **Normative.** **That partition is total over the seventeen members `SearchDisposition`
> is closed at**, and the absence of a disposition is the eighteenth case. A member minted by
> a later ADR establishes **nothing either way** unless that ADR's own text places it — the
> least-claiming direction, and ADR-0242 §8's own default read.

> **Normative.** **The turn's value is folded from its calls, `REACHED` outranking
> `INDETERMINATE` and `INDETERMINATE` outranking `NOT_REACHED`.** One call that established
> a contact makes the turn `REACHED` however many others did not; failing that, one call
> that established nothing either way makes it `INDETERMINATE`; and a turn every one of
> whose calls fell before the send — **and a turn that performed no call at all** — is
> `NOT_REACHED`. The order is the least-claiming one available: a turn is never reported as
> having reached nothing while one of its own calls may have reached something.

> **Normative.** **A driven egress step contributes `INDETERMINATE` to that fold**, and is
> the one input to it that is not a `WEB_SEARCH` call. **The contribution is stated over the
> executor's own pre-callable fact and never over `Disposition.EXECUTED`**, which is not
> that fact: a step whose `ActionRequest` carried an `EgressBinding` contributes
> `INDETERMINATE` where the executor **reached the callable, or cannot say whether it did**,
> and contributes **nothing** where the executor establishes that it did not. The three
> exits ADR-0192 §1 places before the callable — a `ToolBindingError` the seam rejected, a
> `SpendError` refusing the call, and any other `AssistantError` out of the claim on the
> authorisation — are that establishment, committed `FAILED` for the stated reason that
> recording `INDETERMINATE` would be *"about a call that provably never reached the
> callable"*. A step that was refused, denied or never driven contributes nothing for the
> same reason. **This establishes no contact and §3 is unchanged** — what it establishes is
> that this system cannot say the turn reached nothing, which is §2's third group reached by
> ADR-0192 §4's reasoning rather than by a `SearchDisposition`.

> **Normative.** **No component re-derives the partition from a member's name, its
> value, its declaration order or its docstring.** It is a mapping stated here and
> written once in `orchestration`, and a member added without an arm fails rather than
> falling to a default — the discipline `QUERY_DISPOSITIONS` and `SEARCH_DISPOSITIONS`
> already hold in that module.

**Three groups and not two, because each member was read from the code that produces it.**
`SearchDisposition` names *the stage that produced the outcome*, and a stage is not a wire
fact: four members are reached from more than one producing path and the paths disagree.
`_result_of`'s own docstring states both other halves — `SPEND_REFUSED` *"reaches no claim
at all and so reaches this function never"*, while `NO_RESULT` and `UNATTESTED` are
*"answers a provider gave: the call was made, it completed"* — and for `DEADLINE_EXPIRED` it
gives the third group its reason, a search *"whose query may have left the machine and may
have been served and billed"* being *"the one direction ADR-0014 §4 refuses to guess in"*.
**One reading of it has to be kept out**: it also groups `RESPONSE_TOO_LARGE` with
`TRANSPORT_FAILED` and `PROVIDER_REFUSED` as *"calls that did not complete as calls"*, which
is about the **invocation's** outcome and not about whether bytes crossed the wire. A
response too large to carry arrived, because that member is reached only from a reader
counting octets off the channel; a refused connection did not; a provider refusal is
recorded for both. Forcing any of the four either way would assert a fact its inputs do not
establish, which ADR-0242 §8 and ADR-0014 §4 each refuse; `INDETERMINATE` is what §1 buys
instead.

### 3. No other outbound seam establishes a contact here, and the egress one expressly does not

> **Normative.** **This decision establishes a contact from a `WEB_SEARCH` call and from
> nothing else.** A driven step establishes none, whatever its binding, its disposition or
> its addressed status. **The prohibition is over `REACHED` and over `destinations`, and
> over nothing else**: no component derives `REACHED`, and none adds an
> `OutboundDestination`, from an `EgressBinding`, from `Disposition.EXECUTED`, from
> `StepStatus.SUCCEEDED` or from any combination of them, so no turn is `REACHED` on a
> send's account and no class is named on one.

> **Normative.** **But such a turn is not `NOT_REACHED` either, and §2's fold is where that
> is decided** (§2's egress clause). `EXECUTED` is consistent with a byte on the wire and
> with none, so a turn whose only outbound act was a driven send is `INDETERMINATE` with
> `destinations` empty — the statement saying this system cannot tell, rather than that
> nothing was reached. **That is this section working and not an exception to it**: what
> §2 takes from the step is the *absence* of a ground for either answer, which is the one
> thing `EXECUTED` does establish.

> **Normative.** **The reason is that no value this system holds establishes it**, and
> ADR-0192 §4 says so in terms: `SUCCEEDED` is *"bounded by ADR-0031 §4 to exactly three
> facts — a validated callable return, an unexpired deadline, and no increase in the
> cancellation count — and none of them is a transmission"*, *"an egress callable that
> returns normally without putting a byte on the wire produces `SUCCEEDED` like any
> other"*, and *"a transmission fact would have to come from the integration, and
> `ToolImplementation` returns `FrozenJson` with no channel for one"*.
> An earlier draft of this decision established an egress
> contact from exactly that triple and would have rendered *"this turn reached outside this
> system"* on a call that provably never left — the false statement §1 ranks below silence.

> **Normative.** **That is a stated cost and not an oversight** (§12): ADR-0170 §5 already
> has the composing stage told what became of each step, so the reply has an account of the
> *act* and lacks one of the *wire*.

### 4. `OutboundStatement`: what it carries, and the one count it carries

> **Normative.** `core/types.py` gains **`OutboundReach`**, a `StrEnum` valued by
> lower-cased member name and **closed at exactly three members** — **`REACHED`**,
> **`NOT_REACHED`** and **`INDETERMINATE`** — which are §2's three groups folded to the turn
> and nothing else. **`INDETERMINATE` is ADR-0014 §4's own word in its own sense**: the
> system holds no value that decides the question and says so rather than guessing. The
> vocabulary is added to and never renamed, and no fourth member arrives without its ADR.

> **Normative.** `core/types.py` gains **`OutboundStatement`**, a frozen pydantic model with
> `extra="forbid"` whose fields are exactly: **`reach`**, an `OutboundReach`;
> **`destinations`**, a `tuple[OutboundDestination, ...]`; and **`records`**, an `int` with
> `ge=0`. It carries
> **no destination, no host, no origin, no provider name, no connection reference, no
> account identity, no tool identifier, no query and no fragment of one, no record, no
> title, no snippet, no monetary figure, no duration, no `Settings` field name, no
> `SearchDisposition` value, no record id, no decision id and no instant.**

> **Normative.** **The three fields are coupled, and the model refuses an uncoupled
> value.** On `REACHED` `destinations` is **non-empty**; on `NOT_REACHED` and
> `INDETERMINATE` it is **empty** and `records` is `0`. A value carrying a destination
> beside a `NOT_REACHED`, or a count beside an `INDETERMINATE`, is refused rather than
> accepted and rendered as a reach nothing established.

> **Normative.** **`destinations` holds each class contacted once, in
> `OutboundDestination`'s declared order and never in encounter order**, and the model
> **refuses** one that carries a class twice rather than accepting
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

**"Over the supply and not over any later stage" is the half that had to be got right.** A
count over what the composing stage was given is undefined on a pass that composes nothing
and false on one where a channel's withholding (ADR-0199 §3) left it holding none of them,
and ADR-0170 §4 makes both shapes reachable beside a contact: a turn can service a search,
admit its records, and then park its step for confirmation. Stated over the supply the count
is defined everywhere and claims neither.

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
records under one id the supply takes one and `records` is `1` — ADR-0226 §7's
deduplication is over the whole union, which `admitted_fourth_group` states in terms.
**Neither that case nor a budget truncation is claimed unreachable**: `SearchOutcome`
constrains neither identifier uniqueness nor record count, putting `search_max_results`
outside itself as a field *"the configured searcher enforces"*, so an unreachability
argued from `tools/web_search.py` would be about the shipped searcher and not about the
seam every `WebSearcher` is wired through. Stated over admission the count needs no such
argument.

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

**One count and not two.** A figure for what the provider returned is plumbing the user can
do nothing with, and stating both would put two numbers in front of a reader with no way to
tell which matters. The count that entered the supply is the one that bears on the answer in
front of them, and the one whose `0` is informative: *I reached outside this system and
nothing came back that this turn could use.*

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

**One member is the point rather than an embarrassment.** The vocabulary makes the next
seam's addition cheap — a second member rather than a second carrier minted from scratch
(§12) — so the tuple is kept and ordered rather than collapsed into the member's absence.

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
> else — the contact classification each performing site computed (§2), the
> admitted ids each admitting site recorded (§4), and **the executed-egress fact the
> component that drove the step computed** (§2's egress clause), which is a typed
> classification carried out of the drive like the other two and never an
> `EgressBinding`, a `Disposition` or a `StepExecution` read at the fold. On ADR-0244 §7's
> resume the first two are two different sites and the engine is where they are brought
> together; no site recomputes another's fact, and nothing is inferred at the assembly
> point. It travels to
> the composing stage as data — the shape ADR-0242 §7 fixes for its
> own carrier and ADR-0228 §10 for its own — adds no member to any Protocol, and is
> **never recomputed downstream**.

> **Normative.** **Assembly accumulates and never replaces.** A servicing that establishes
> no contact clears nothing an earlier one established, and one that fails contributes its
> own zero without resetting what an earlier one admitted: §1's condition is *at least
> one*, and §4's count is one population over the turn. A last-writer-wins assembly is
> the defect this clause names.

> **Normative.** **The fragment obligation binds on every pass that composes a reply,
> except a routed one**, whatever the statement's value. ADR-0170 §4 requires no composition
> on a pass whose step parked for confirmation or whose `turn` is `None`, and a turn that
> serviced a search and then parked its step for confirmation is exactly such a pass. On it
> the member is carried and §7's statement is rendered exactly as that section fixes, and
> there is no fragment because there is nothing to give one to — which is not a degradation,
> because the reply the fragment guards does not exist.

> **Normative.** **A routed pass carries the member and renders the statement and is given
> no fragment**, so ADR-0197 §6's closure of the routed composer's inputs at *"exactly two"*
> stands unnarrowed and no record is owed against it (§14). The exclusion is not a
> convenience: a routed reply is composed over a `RouteOutcome` and not over a supply, the
> pass takes no read at all, and §7's rendered statement — which §6's closing paragraph
> names as what makes this decision structural — binds on it exactly as everywhere else. The
> guarantee is therefore whole on a routed pass; what it does without is the instruction the
> guarantee does not rest on.

> **Normative.** Where the pass composes, the composing stage is given **one fixed fragment
> per `OutboundReach` member**, written in
> `ai_assistant.orchestration`, interpolating **`records` and nothing else, and only on
> `REACHED`**. The `REACHED` fragment states the two facts every contact has and no others:
> that **this turn reached outside this system**, and **how many records it took in from
> doing so — which may be none, and the fragment says so where it is none**. The
> `NOT_REACHED` fragment states that **this turn reached nothing outside this system**, and
> the `INDETERMINATE` fragment that **this system cannot say whether it did**. None of the
> three asserts anything about what was reached or about material having arrived, because a
> contact that came back with nothing is still a contact and a record in the supply is not a
> record in the answer. Each
> carries no destination, no host, no origin, no provider name, no connection
> reference, no account identity, no query or fragment of one, no record, no title, no
> snippet, no monetary figure, no duration, no `Settings` field name, no
> `SearchDisposition` value, no id and no command name — ADR-0242 §7's bar, binding here
> unchanged.

> **Normative.** **Each fragment forbids the reply from contradicting the value it
> carries, in whichever direction that value points.** On `REACHED` it forbids denying that
> this turn reached outside this system, and forbids saying the answer is more current, more
> reliable or better for it. On `NOT_REACHED` it forbids claiming a lookup, a search, a
> fetch or any fresh read **this turn**, and forbids attributing any part of the answer to
> one — #2365's *"already in front of me from this turn's searches"* is the sentence this
> half exists to refuse, and a reply may of course still say where material it holds came
> from, provided it does not date it to this turn. On `INDETERMINATE` it forbids asserting
> either. **The prohibition is stated over the reach**, which on this
> decision's one established seam is a lookup, and a later seam's member takes the
> prohibition in whatever terms its own ADR fixes rather than inheriting this one's.
> `_STOPPED_ASKING_PROMPT`'s own bar is the form — *"you have not been
> told any of that"* — and the fragment is stated at both ends: the model is told the fact
> so that it need not guess, and told what the fact does not license so that it does not
> embroider it.

> **Normative.** **`_PLAN_IS_ABOUT_ACTING` is appended on every composing pass that
> renders a plan block**, which a routed pass does not. #2213
> added that line on a turn that did not service a search, to stop the plan block being read
> as an account of lookups; on a turn that *did* reach outside, and on #2365's turn whose
> planner named no capability at all, the same block says the same misleading thing and the
> same line answers it. The condition becomes *the pass composes*, and the line's own text
> is unchanged.

> **Normative.** **No lane widens the carrier to free text.** `destinations` is a closed
> vocabulary and `records` is an integer; a message, a provider response, a query, a
> record or a sentence assembled from any of them is refused here, for ADR-0231 §13's
> no-message reason and ADR-0004 §5's.

**Telling the model is not what makes this decision work, and that is the point.** A prompt
fragment is an instruction a model may ignore — #2268 is a model ignoring the absence of one,
#2365 a model inventing what none supplied. What makes the guarantee structural is §7's
rendered statement, composed from the typed value by code and standing beside the reply
whatever it says: the fragment is there so the two ordinarily agree, the rendering so that
when they do not, the user can see it.

### 7. `TurnOutcome` gains one member, and a surface renders it from the value

> **Normative.** `TurnOutcome` gains exactly one field, **`outbound_statement`**, typed
> `OutboundStatement | None` and defaulting to `None`, whose docstring names this ADR as
> the decision that added it. It carries **the value §6 computed, by value, and never a
> second computation**.

> **Normative.** `outbound_statement` is `None` on exactly the passes that **neither
> established a contact nor composed a reply**: a **routed park**, on which ADR-0197 §10
> rules *"the composing stage is not reached"*, and every other pass ADR-0170 §4 composes
> nothing for that established none. **A routed pass that is not a park carries
> `NOT_REACHED`**, because ADR-0197 §10 rules that on it *"the composing stage runs on §6's
> two inputs and an answer is owed"* — so there is prose, and §1's condition binds on it
> like any other. **It is likewise not `None` on an ordinary turn that reached nothing**:
> ADR-0198 §1's **restatement**, ADR-0250 §3's `UNDECIDED` turn and every `converse` whose
> planner asked for no search each carry `NOT_REACHED`, which is the value #2365 needed and
> did not have. That adds a value to ADR-0198 §2's enumeration without changing any value it
> fixes.

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
> turn still carries `outbound_statement` and still gets §6's fragment, so the reply is
> composed under the same instruction — but no code-composed statement stands beside it.
> **This decision's title is bounded by that**: a reply cannot deny a contact **on a surface
> that renders the statement**, and the spoken one does not.

> **Normative.** **A surface renders one statement composed from the value**, one per
> `OutboundReach` member — **beside the reply where one exists and never in place of it,
> and standing alone on a pass that composed none**, where by §1 and §7's `None` rule the
> only value such a pass can carry is `REACHED`. On `REACHED`: that
> this turn reached outside this system, naming each class in `destinations` in the
> vocabulary's declared order, and how many records that **brought into this turn's supply**
> — including that it brought none, where `records` is `0`. On `NOT_REACHED`: that this turn
> reached nothing outside this system. On `INDETERMINATE`: that this system cannot say
> whether it did. The exact wording is the lane's; what is fixed is that the statement is
> built from the value, that a `0` is stated rather than elided, and that no surface renders
> a statement for a value it was not given.

> **Normative.** **`REACHED` renders on every pass that carries it; `NOT_REACHED` and
> `INDETERMINATE` render only on a pass that composed a reply.** The asymmetry is principled
> and not economical: `REACHED` reports an **act this system performed**, which the user is
> owed whether or not prose was written — ADR-0227's posture that the audit records acts —
> while the other two report **nothing having happened**, whose only function is to stop a
> reply being read as claiming otherwise, so where there is no reply they answer a question
> nobody asked. **The condition is the reply's existence and never its content**: no surface
> reads the prose to decide whether to render, which would be the model judgement §10
> refuses.

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

> **Normative.** A turn may carry **both** `search_not_serviced` and `outbound_statement`,
> and where it does **both are rendered**, each in its own statement, neither suppressing
> nor qualifying the other. The reachable shape is one turn with two servicings — one
> refused before it sent, one answered — and it is a turn on which both sentences are
> true. **A turn whose every servicing refused before the send carries both too**:
> `search_not_serviced` names the act that would help, `NOT_REACHED` states that nothing
> left, and neither is read off the other.

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
> detective**: §7's statement is composed by code and cannot be made to agree with a denial
> or with a false claim, so a user reading both sees the disagreement without anything
> having classified it, and an operator reading the trail sees what happened whatever the
> reply said.

**Booked rather than refused** — #2291's audit-recording ADR is already owed, and deciding
this here would reach into a decision this ADR has not read.

### 11. The lane cut

> **Normative.** The implementation is **two lanes**, in this order, and neither may
> absorb the other's paths.
>
> 1. **Contract and `orchestration`.** `OutboundReach`, `OutboundDestination`,
>    `OutboundStatement` and `TurnOutcome.outbound_statement` in `core/types.py`; §2's establishment at every site
>    that performs a `WEB_SEARCH` call, and its fold — including the executed-egress
>    classification, which `orchestration.runner`'s `StepRunner` computes and carries out of
>    the drive; §4's admitted sets and §6's assembly; the three composing fragments and
>    `_PLAN_IS_ABOUT_ACTING`'s widened condition.
>    **It is one lane under ADR-0137 §1 and expressly not under §2**: every piece of new
>    machinery this decision builds — the establishment, the egress classification, the
>    carriers, the assembly, the fragments — is in `ai_assistant.orchestration` and in no
>    other subsystem, `StepRunner` included, and what
>    lands in `core/types.py` is three type declarations and a `None`-defaulting field,
>    which is not *"a store, a loop, a codec, a producer, a policy engine"* but the
>    adaptation §1 puts outside its bound. §2 is unavailable here and is not invoked: it
>    widens the exception for **a contract triad with its primary implementation**, this
>    decision adds no Protocol and no triad, and §2 says in terms that *"any other
>    cross-subsystem pairing remains outside the exception"*.
> 2. **The terminal surface.** `interfaces/cli.py` renders §7's statement (golden rule 3).
>
> The browser's rendering is #2237's lane and is not a lane of this decision (§9).

> **Normative.** **Each arm of §13 is owed by the lane that owns the code it asserts over,
> and no arm obliges a lane to touch the other's paths.** Every arm's assertions about the
> member, the establishment, the admitted count, the composing prompt and
> `OutboundStatement`'s own construction are lane 1's; every arm's assertions about a
> **rendered statement** are lane 2's, landed with the renderer they are about. **The rule
> is stated over the assertion and never as a count of arms**, because §13 is a floor: a
> clause naming which arms carry a rendering assertion would go stale the moment the floor
> obliged one it had not named. A lane that lands an assertion over code it does not own has
> broken the cut rather than honoured §13.

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

> **Normative.** **Whether a surface may abbreviate or suppress the `NOT_REACHED`
> statement.** §7 renders it on every composing pass, which puts one line about the world on
> every reply that reached nothing; that is the price of a statement a reader may rely on
> from its absence as well as from its presence (§1). **Fires** when a deployment reports
> the line read as noise, or when a surface gains a compact indicator it could ride.

> **Normative.** **A notification.** No lane mints a `Notification`, a notification kind,
> a delivery or a poll result for an outbound contact — ADR-0235 §8's second clause, binding here as ADR-0242 §6 made it bind
> there.

### 13. The arms this decision owes

> **Normative.** The implementing lanes owe these eleven arms **between them**, each over
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
>    on a turn whose pre-existing supply is **non-empty**. `outbound_statement` is set with
>    `records` `0`, `search_not_serviced` is `None` (ADR-0242 §6's third clause), and the
>    rendered statement states the `0` rather than eliding it.
> 3. **The partition, asserted over the enumeration itself and then over its two
>    reachable sides.** The arm walks **every member of `SearchDisposition`** and asserts
>    the group §2 places it in, so a member added without an arm **fails** rather than
>    falling to a default — the discipline §18 item 9a of ADR-0231 already holds over
>    `SEARCH_DISPOSITIONS` — and it asserts that `TRANSPORT_FAILED`, `DEADLINE_EXPIRED`,
>    `SEARCH_FAILED` and `PROVIDER_REFUSED` establish nothing either way, the last over
>    **both** its causes, because an implementation reading it as a response is what this
>    arm exists to catch. Then the three sides in a turn: a
>    search refused before the send (`RULING_DENY`) carries `reach` `NOT_REACHED` and
>    `search_not_serviced` `DECLINED`; one that established nothing either way
>    (`TRANSPORT_FAILED`) carries `INDETERMINATE`; and a response received and then refused
>    (`UNATTESTED`) carries `REACHED` with `records` `0` **and**
>    `search_not_serviced` `UNAVAILABLE`, and renders both statements (§8).
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
> 6. **`OutboundStatement`'s own construction invariants, asserted on the model and not on
>    its producer**, because it is a boundary-crossing value a wire decode also builds.
>    **Refused:** an **empty** `destinations` paired with `REACHED`; a **non-empty** one
>    paired with `NOT_REACHED` or `INDETERMINATE`; a non-zero `records` paired with either of
>    those two; one carrying a class twice; a **negative** `records`; and an **unknown
>    field**. **Accepted:** the two empty-`destinations`, zero-`records` shapes §4 requires
>    for `NOT_REACHED` and `INDETERMINATE`, so a lane that refuses emptiness outright fails
>    this arm.

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
> 8. **A driven egress step establishes no contact and is not nothing either** (§3), in
>    three shapes. One whose callable was reached and whose addressed `StepExecution` is
>    `SUCCEEDED`, and one whose callable was reached and whose addressed status is **not**
>    `SUCCEEDED`: both carry `reach` **`INDETERMINATE`** with `destinations` empty on a turn
>    with no established search contact, so an implementation gating on `SUCCEEDED` fails the
>    second — a failed send may still have transmitted. And one the executor exited **before
>    the callable** (ADR-0192 §1's three windows): it **contributes nothing**, so a turn
>    whose only other call reached the provider stays `REACHED`, one whose other call
>    established nothing either way stays `INDETERMINATE`, and one with no other call is
>    `NOT_REACHED`. **No egress outcome overrides the fold** (§2): the arm asserts each of
>    those three turns. An implementation that mints a contact from an executed step fails
>    this arm, **and so does one that answers `NOT_REACHED`** for a step whose callable was
>    reached — the send may have left, and saying it did not would be the false statement §1
>    ranks below silence.
> 9. **A turn that made no call at all** — #2365's shape, `servicing=not_asked`. The
>    statement is carried with `reach` `NOT_REACHED`, `destinations` **empty** and `records`
>    `0`; `search_not_serviced` is `None`; the prompt carries the `NOT_REACHED` fragment and
>    `_PLAN_IS_ABOUT_ACTING`; and the rendered statement says this turn reached nothing
>    outside this system. **An implementation that leaves the member `None` on such a turn
>    fails this arm**, which is the whole of what #2365 records.
> 10. **The rendering asymmetry** (§7): a pass that composed **no** reply renders neither
>    the `NOT_REACHED` nor the `INDETERMINATE` statement, while a `REACHED` pass in that
>    same shape renders its own. An implementation that conditions any of the three on what
>    the reply says fails this arm, and one that renders `NOT_REACHED` with no reply beside
>    it fails it too.
> 11. **A routed pass that is not a park**, whole-reply and streaming, which are separate
>    composers from the conversational one and the path an implementation updating only the
>    latter would leave behind. It carries `NOT_REACHED`, renders §7's statement, and its
>    composer is given **neither** §6's fragment **nor** `_PLAN_IS_ABOUT_ACTING` — ADR-0197
>    §6's two inputs unchanged, which is the assertion that keeps that closure true. A
>    **routed park** carries `None` and renders nothing. An implementation that gives the
>    routed composer a third input fails this arm, and so does one that leaves the routed
>    pass's member `None`.

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
§8, ADR-0235 §4, ADR-0242 §9 and ADR-0250 §5 made the identical move; the two that did
record against ADR-0170 §4 did so for moving a **shape** — a `turn`-`None` outcome able to
carry a reply, and a second `turn`-`None` shape. This decision moves no shape.

**ADR-0198 §2 — no record owed.** The restatement's enumeration gains a value and loses
none: `turn`, `routed`, `reply`, `reply_degraded` and `step` carry there exactly what §2
says. The added member's value there is **`NOT_REACHED`** and not `None` (§7), which is the
true statement about a restatement — it composes a reply and reaches nothing — and §2 fixes
no value for a member it does not have.

**ADR-0226 §9 and ADR-0238 §11 — no record owed, and `records` is expressly not theirs.**
No count is added to, removed from or redefined in the per-turn audit record, and §4 states
in terms that `records` is neither ADR-0238 §11's `supplied` nor derived from it.

**ADR-0249 §7's `minted` and ADR-0227 §3's `hop_reached` — no record owed.** §4 reads
`minted` and copies `hop_reached`'s shape, redefining neither and taking neither out of its
own ADR's use. A second consumer of a carrier is not a change to it — the position ADR-0242
§6's own second consumer of `ServicedRead.disposition` already stands in.

**ADR-0197 §6's *"exactly two"* routed-composer inputs and §10's two-input sentence — no
record owed, and §6 above is written so.** A routed pass carries the member and renders §7's
statement, and its composer is given nothing new, so the closure binds verbatim and a reader
holding only ADR-0197 builds the routed composer exactly as it describes. The alternative —
a third input there — would have been a supersession of a contract closure bought for a
fragment the guarantee does not rest on.

**`_PLAN_IS_ABOUT_ACTING`'s condition (§6) — no record owed.** That line and its condition
come from issue #2213 and from code; no ADR clause fixes when it is appended. Widening the
condition falsifies no ratified sentence.

**ADR-0227 §3, ADR-0228 §10, ADR-0240 §8 and ADR-0251 §7 — the same byte-identity promise,
four times over, and this decision records against none of them.** Each promises the prompt
is byte-identical on the turns its own carrier does not fire on, and §6 above falsifies all
four — but **they were false before this decision**, because the carriers compose: a turn
ADR-0242 §6 gives its member to is already one of the "every other" turns of the three that
predate it, and ADR-0242 recorded against ADR-0228 §10 alone, not against ADR-0227 §3 or
ADR-0240 §8, which its own carrier falsifies identically. This decision follows that practice
rather than inventing a rule on its own authority, and **files the gap instead of absorbing
it**: [#2370](https://github.com/leonapivato/ai-assistant/issues/2370) asks how far such a
record reaches and proposes ADR-0241 §10's form as the fix — that sentence alone is not
false, and it is not false because it writes *"it is given nothing **on this account**"*.

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

- **A turn now says what it did about reaching the world, in both directions, in a
  statement the reply cannot talk out of.** It is composed from a typed value by code and
  renders beside the reply on the surfaces §7 binds, so a reply that denies a contact
  (#2268) and one that claims a contact that never happened (#2365) are each contradicted in
  front of the user rather than believed. **Neither is prevented**: a model may still write
  either, and what changes is that it no longer stands alone (§10, and §7's spoken limit).
- **Every reply now carries one line about the world, and that is the price of the
  guarantee.** A statement rendered only sometimes teaches a reader nothing from its
  absence, which is exactly how #2365's turn passed unremarked; §12 books the question of
  abbreviating it once a deployment reports the line as noise.
- **A `0` becomes sayable.** *I reached outside this system and nothing came back that
  this turn could use* is a sentence the system has never been able to make; it is the
  honest account of a search that found nothing, and it is the sentence whose absence made #2268 read as a
  contradiction rather than as a thin reply.
- **Four dispositions answer `INDETERMINATE` rather than either side.** A transport
  failure, a deadline expiry, a raised fault and a provider refusal are each reached from
  producing paths that disagree about the wire — `PROVIDER_REFUSED` covers an account change
  that opened no channel as well as a response the provider gave — so the turn says this
  system cannot tell. **That third value is what the two-directional requirement forced**:
  with only `REACHED` and `NOT_REACHED` those four would have had to claim one, and
  `NOT_REACHED` on a call that may well have left is the false statement §1 ranks below
  silence. §12 says what would make the honest sentence available.
- **An egress send answers `INDETERMINATE`, which is the honest position.** ADR-0192 §4
  rules that `SUCCEEDED` is consistent with no byte on the wire and that nothing available
  today carries the transmission fact — so §3 refuses the **contact**, and §2 equally refuses
  the **denial**, because a turn that emailed somebody and was told it reached nothing would
  be misled as badly as #2365's was. A send that did reach the world is stated as reached
  only when a seam carries that it did (§12).
- **The spoken surface does not carry the guarantee.** `SpokenTurn` gains nothing, so a
  spoken reply that denies a contact is contradicted by nothing the user hears (§7). The
  title is bounded to the surfaces that render the statement, and §12 books the rest.
- **`TurnOutcome` grows to sixteen members**, and `outbound_statement` is the **tenth** a
  later ADR has added as a `None`-defaulting fact a client renders on its own. That is
  ADR-0244 §9's rule working as designed and also the thing to watch: an eleventh and a
  twelfth make a client's rendering order a decision nobody has taken.
- **Revisit when** a seam carries that a byte was put on the wire, when the spoken
  surface gains a rendering of its own, or when a deployment reports a user misled by the
  silence §2's third group keeps.
