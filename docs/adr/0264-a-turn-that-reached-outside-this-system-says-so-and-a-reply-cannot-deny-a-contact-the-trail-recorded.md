# 264. A turn that reached outside this system says so, and a reply cannot deny a contact the trail recorded

- Status: Proposed
- Date: 2026-09-13

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
remaining failures. This decision closes that one.

### The tree, read rather than assumed, at `origin/main` `05656952`

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
  point of ADR-0226 §7's fourth group"* — and states the discipline: the fact is
  *"supplied by the servicing that knows it and never inferred at the resolution site,
  exactly as `hop_reached` is"*.
- **`ServicedRead.supplied` is a count in the *other* direction and is not this
  decision's.** ADR-0238 §11's first count is *"how many records this servicing supplied
  to the composer"* — the **query** composer, the population a chosen destination may be
  told about — and `_serviced_search` assigns it from `_search_supply`'s result before
  the query is composed and before anything is sent. It says what left, not what came
  back.
- **`Disposition.EXECUTED` is the gate's verdict and not the call's result.**
  `StepOutcome`'s own docstring is explicit: *"a client that renders success from
  `disposition` alone is wrong — `EXECUTED` says the permission gate let the call through
  and the executor committed **something**, not that the something succeeded"*, and it
  makes reading the addressed `StepExecution` by `step_id` an addressable operation
  rather than advice.
- **The egress side holds its own.** `orchestration.runner` builds the
  `ActionRequest` the policy rules on and sets `egress_binding` from what
  `EgressBinder.bind` returned, so a step whose call carried a binding is known
  inside `orchestration` at the time the step is driven. `tools/send_email.py` is
  a live egress tool.
- `TurnOutcome` carries fifteen members today, and **nine** of them — `routed`,
  `recipient_grant`, `search_not_serviced`, `read_confirmation`, `read_answer`,
  `goal_engagement`, `clarification`, `reference` and `disambiguation` — were added
  by a later ADR as a `None`-defaulting widening.

### The gap this closes, stated exactly

ADR-0242 §6 makes eligibility *"the disposition's presence and nothing else"*, and
its second clause states the consequence in terms: *"A turn on which every
servicing yielded records carries **no** `SearchNotServiced` member."* That is
correct for what §6 decides and is precisely the hole: on the successful turn the
system says nothing, has no field in which to say anything, and hands the model a
plan block that accounts for acting alone. The user is then told whatever the
model infers — and #2268 records it inferring the opposite of the truth.

### What this ADR is not allowed to settle

- **ADR-0242 §6's not-serviced statement.** Every clause of §§6-9 binds entire and
  none is narrowed, widened or re-read here.
- **The browser's rendering arrears.** Issue #2237 records that the browser renders
  none of ADR-0242 §9's statements. That is its own lane and this decision neither
  closes it nor competes with it (§9).
- **What the model writes.** No clause here inspects, classifies or corrects a
  composed reply.

## Decision

### 1. The eligibility condition: this turn reached outside itself, and the trail is what establishes it

> **Normative.** A turn carries the statement this decision mints on, and only on, a
> turn for which **at least one outbound contact is established** by §2 or §3. On every
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

> **Normative.** A servicing that emitted a `WEB_SEARCH` ask establishes an outbound
> contact where it **completed and recorded no `SearchDisposition`** — which is a search
> that reached the provider and was answered, records or none, because
> `SearchRefusal.NO_RESULT` maps to no disposition (ADR-0231 §13) — **or** where the
> disposition it recorded is one of
> `PROVIDER_REFUSED`, `RESPONSE_TOO_LARGE` and `UNATTESTED`, each of which is a response
> this system received and then refused.

> **Normative.** A servicing whose disposition is `NOT_CONFIGURED`, `NO_BUDGET`,
> `COMPOSER_DECLINED`, `COMPOSER_UNAVAILABLE`, `COMPOSER_MALFORMED`, `COMPOSER_TOO_LONG`,
> `BINDING_FAILED`, `RULING_CONFIRM`, `RULING_DENY`, `RULING_UNAVAILABLE` or
> `SPEND_REFUSED` establishes **no** contact. Every one of those is a stage before the
> send: no query was composed, no ruling was obtained, or the send was refused on a
> ceiling, and `NO_BUDGET`'s own definition is that *"no request is composed, no ruling
> is sought and no channel is opened"*.

> **Normative.** A servicing whose disposition is `TRANSPORT_FAILED`, `DEADLINE_EXPIRED`
> or `SEARCH_FAILED` establishes **nothing either way**, and the turn carries no
> statement on its account. A refused connection, an expiry of `search_call_deadline` and
> a fault raised out of `WebSearcher.search` are each consistent with a request that left
> and with one that did not, and the site holds no value that separates them. **The
> non-asserting direction is taken deliberately**, and §12 defers the finer answer with
> its trigger.

> **Normative.** **The absence of a disposition establishes a contact only on a servicing
> that completed.** A servicing that failed discards its records and zeroes its counts
> (ADR-0226 §5), and nothing in the record says whether its search had already returned —
> `failed_after_read_returned` is stated over *reads* and not over the send. So a failed
> servicing carrying no disposition establishes nothing either way; one carrying a
> disposition is placed by the clauses above, which do not turn on whether the servicing
> then failed.

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
`SearchDisposition` names *the stage that produced the outcome*, and its members divide
cleanly into stages before the send, stages after a response arrived, and the send itself
— where an outage, an expiry and a raised fault are all recorded without recording whether
anything crossed the wire. Forcing that third group into either of the others would be
this decision asserting a fact its inputs do not establish, which is exactly what ADR-0242
§8 refuses when it states each member *"over what its inputs establish and never over a
cause they do not"*. **The user is not left silent there**: every member of the third group
already carries a `SearchNotServiced` member under ADR-0242 §8 — `INTERRUPTED` for
`DEADLINE_EXPIRED`, `UNAVAILABLE` for the other two — whose statements say the search was
begun and stopped, or that the lookup produced nothing usable, and §6's third clause
already forbids the latter from saying that no request was made.

**The tree states both halves of that partition already, in `tools/web_search.py`, and
this section is that statement read for a different consumer.** `_result_of`'s docstring
puts `SPEND_REFUSED` before the send in terms — it *"reaches no claim at all and so reaches
this function never"* — and puts `NO_RESULT` and `UNATTESTED` after a response in terms:
*"answers a provider gave: the call was made, it completed, and what came back is not
something this system will carry"*. For `DEADLINE_EXPIRED` it says exactly why the third
group exists: recording a failure there would say *the call did not act* about *"a search
whose query may have left the machine and may have been served and billed, which is the one
direction ADR-0014 §4 refuses to guess in"*.

**Two readings of that docstring have to be kept apart, because a reviewer will reach for
the wrong one.** It also groups `PROVIDER_REFUSED` and `RESPONSE_TOO_LARGE` with
`TRANSPORT_FAILED` as *"calls that did not complete as calls"* — a statement about the
**invocation's** outcome, which is what the ledger row and ADR-0192 §3's completion are
written from. It is not a statement about whether bytes crossed the wire, and this section
asks only that. A provider that refused answered, and a response too large to carry is a
response that arrived; a refused connection is neither.

**And absence here asserts nothing, which is why the third group is not the guess ADR-0014
§4 refuses.** That rule bites where a record must take one of several values and one of
them would be false; `INDETERMINATE` is what it buys. Here the statement is present or it
is not, an absent one claims nothing about the wire, and the turn is not silent: ADR-0242
§9 already renders `INTERRUPTED` or `UNAVAILABLE` for every member of this group, and
neither says no request was made. The user is told the honest indeterminate; what they are
not told is a sentence this system cannot support.

### 3. An egress contact, established from the binding the request carried

> **Normative.** A driven step establishes an outbound contact where **all three** hold:
> the `ActionRequest` the policy ruled on carried an `EgressBinding`; the step's
> `StepOutcome` disposition is `EXECUTED`; **and** the `StepExecution` that outcome
> addresses — the one whose `step_id` is `StepOutcome.step_id`, the operation
> `StepOutcome`'s docstring makes addressable rather than advisory — carries
> `StepStatus.SUCCEEDED`.

> **Normative.** **The third condition is not decoration, and a reader dropping it
> builds a defect.** `Disposition.EXECUTED` is the *gate's* verdict: it says the call was
> authorised and handed to the executor and that the executor committed something, not
> that the callable was entered. A claim the `InvocationLedger` refused, and a
> `ToolBindingError` the seam raises before the claim (ADR-0192 §1), both commit a
> `FAILED` step beneath an `EXECUTED` disposition and reached nothing. Establishing a
> contact from the disposition alone would state a call that provably never left.

> **Normative.** A step whose addressed status is `FAILED` or `INDETERMINATE`
> establishes **nothing either way**, and that is the same ruling §2's third group takes
> for the same reason: `FAILED` covers a pre-callable refusal and a post-dispatch failure
> without separating them, and `INDETERMINATE` is ADR-0029 §4's expiry shape, which
> exists precisely because the call *may* have acted. The condition is therefore
> **under-inclusive and is stated as such rather than widened** — a callable that was
> entered and then failed reached the world, and ADR-0192 §1's ledger claim, appended
> *"immediately before the callable is entered"*, is the record of it, behind
> `ToolInvoker` where `StepOutcome` cannot see it. §12 defers the rest with its trigger.

> **Normative.** No component reads the `EgressBinding`, the tool, the connection, the
> destination or any parameter of the call in order to compute this fact. What is read is
> **that the binding was present**, and nothing of it crosses into the statement or into
> the prompt.

**This half is included because the rule is about the world and not about search.** #2268
is a search defect, and search is where the failure is acute — an egress send is driven as
a *step*, and ADR-0170 §5 already obliges the composing stage to be told the plan and what
became of each step, so the reply has an account of it. Ruling only on search would have
made this decision a second search clause rather than the general one the issue asks for,
and would have left the next outbound seam to mint its own vocabulary.

### 4. `OutboundContact`: what it carries, and the one count it carries

> **Normative.** `core/types.py` gains **`OutboundContact`**, a frozen pydantic model with
> `extra="forbid"` whose fields are exactly: **`destinations`**, a **non-empty**
> `tuple[OutboundDestination, ...]`; and **`records`**, an `int` with `ge=0`. It carries
> **no destination, no host, no origin, no provider name, no connection reference, no
> account identity, no tool identifier, no query and no fragment of one, no record, no
> title, no snippet, no monetary figure, no duration, no `Settings` field name, no
> `SearchDisposition` value, no record id, no decision id and no instant.**

> **Normative.** **`destinations` holds each class contacted once, in
> `OutboundDestination`'s declared order and never in encounter order.** A turn that
> contacted one class through three servicings carries that class once. **It is not an
> enumeration of a turn's servicings**, which is the direction ADR-0226 §9's
> counts-and-no-copy reasoning and ADR-0228 §10's *"no count, no duration, no guard
> name"* both refuse: what a reader is told is which kinds of thing this turn reached,
> and the system's internal shape stays inside it.

> **Normative.** **`records` is how many of the records the composing stage was given
> were minted by this turn's established contacts** — the count of ids in the
> contacting servicings' `minted` carriers that the supply handed to composition still
> holds, taken as one population over the turn so a record minted twice counts once.
> That is `hop_reached`'s own shape, which ADR-0227 §3 states as the ids a servicing
> reached *"that the supply holds after it"*, and it is computed in `orchestration` from
> two values that package already has.

> **Normative.** **It is not `ServicedRead.supplied` and no lane derives it from that
> field.** ADR-0238 §11's count is *"how many records this servicing supplied to the
> composer"* — the **query** composer, the population a chosen destination may be told —
> and it is assigned before the query is composed and before anything is sent. It counts
> what left, and a turn that sent two remembered facts to the provider and got five
> results back would report `2` and then `0`. It is also **not** a count of what the
> provider returned, of what a servicing fetched before deduplication, or of anything a
> step produced.

> **Normative.** `records` is `0` on a turn whose only contact was an egress one, on a
> search answered with nothing, on one whose every minted record deduplication removed,
> and on one whose minted records a channel's withholding kept out of the supply
> (ADR-0199 §3). **A `0` means no record from outside is in front of the composing
> stage**, and it means nothing else.

> **Normative.** **A `records` of `0` never suppresses the statement.** The fact is the
> contact, and a turn that reached outside itself and brought nothing into the answer is
> the case this decision most needs to state — it is the one a user cannot tell from a
> turn that did not look, and telling them apart is what #2268 asks for.

> **Normative.** **Neither the value nor any rendering of it says what the reply did
> with the records.** What a model made of material in its prompt is not a fact this
> system holds. `records` says the records were **put in front of composition** and no
> more, and no clause here, no field of this model, no prompt fragment and no rendering
> says that they entered the answer, that the answer rests on them, that it is more
> current for them, or that it would have differed without them.

**One count and not two, and it is the count of what reached the prompt.** A figure for
what the provider returned would be a fact about the system's plumbing that the user can do
nothing with, and stating both would put two numbers in front of a reader who has no way
to tell which one matters. The count that reached the supply is the one that bears on the
answer in front of them, and the one whose `0` is informative: *I looked outside, and
nothing from it was in front of me when I wrote this.* That sentence is unavailable
today, which is why #2268 was reported as a contradiction rather than as a thin reply.

### 5. `OutboundDestination`: a closed vocabulary of classes, never of destinations

> **Normative.** `core/types.py` gains **`OutboundDestination`**, a `StrEnum` valued by
> lower-cased member name, **closed at exactly two members** and declared in this order,
> which is also the order `destinations` renders in:
>
> 1. **`SEARCH_PROVIDER`** — the configured web search provider, which ADR-0247 §1 makes
>    the destination the owner chose and the recipient they granted.
> 2. **`EGRESS_TOOL`** — a tool whose authorised call carried an `EgressBinding`.
>
> The vocabulary is **added to and never renamed**, and no implementation or later ADR
> adds a third member without the ADR that decides it.

> **Normative.** **A member is a class of destination and never a destination.** No
> member names, encodes or is derived from a provider, a host, an account, a connection
> or a tool, and no later member may be one that identifies a particular destination —
> which would put a destination's identity into a reply, on every surface and on a
> channel of unbounded audience, when ADR-0193 §11 will not let even an audit surface
> decode the `authorised_subject` on a row in front of the user who owns it.

> **Normative.** A later outbound seam adds its own member with its own ADR. **It does
> not render as `SEARCH_PROVIDER`, does not render as `EGRESS_TOOL`, and does not render
> as nothing**: a contact class with no member is a contact this system made and did not
> state, which is the defect this decision exists to close.

### 6. The carrier, and what the composing stage is told

> **Normative.** The value is computed **once**, inside `ai_assistant.orchestration`,
> from the per-servicing records §2 names and the step facts §3 names, and from nothing
> else. It travels to the composing stage as data — the shape ADR-0242 §7 fixes for its
> own carrier and ADR-0228 §10 for its own — adds no member to any Protocol, and is
> **never recomputed downstream**.

> **Normative.** The composing stage is given **one fixed fragment**, written in
> `ai_assistant.orchestration`, interpolating **`records` and nothing else**. The
> fragment states the two facts every contact has and no others: that **this turn reached
> outside this system**, and **how many of the records in front of the model came from
> doing so — which may be none, and the fragment says so where it is none**. It asserts
> nothing about what was reached, nothing about a lookup, and nothing about material
> having arrived, because a turn that only sent something outward reached the world and
> brought nothing back. It carries no destination, no host, no origin, no provider name, no connection
> reference, no account identity, no query or fragment of one, no record, no title, no
> snippet, no monetary figure, no duration, no `Settings` field name, no
> `SearchDisposition` value, no id and no command name — ADR-0242 §7's bar, binding here
> unchanged.

> **Normative.** The fragment **forbids the reply from denying that this turn reached
> outside this system**, and forbids it from saying that the answer is more current, more
> reliable or better for it. **The prohibition is stated over the contact and never over
> a lookup**: a turn whose only contact was outward made no lookup, so a fragment barring
> the denial of one would put a false instruction in front of the model on exactly the
> shape §3 admits. `_STOPPED_ASKING_PROMPT`'s own bar is the form — *"you have not been
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
> neither does this one. `SpokenTurn` gains **nothing**, for ADR-0242 §9's reason: on
> `converse_spoken` the spoken reply is the whole of what the user is told.

> **Normative.** **A surface renders, beside the reply and never in place of it, one
> statement composed from the value**: that this turn reached outside this system, naming
> each class in `destinations` in the vocabulary's declared order, and how many records
> that put **in front of composition** — including that it put none there, where `records`
> is `0`. The exact wording is the lane's; what is fixed is that the statement is built
> from the value, that a `0` is stated rather than elided, and that no surface renders a
> statement for a value it was not given.

> **Normative.** **No statement says a record reached, entered, supported or affected the
> answer**, and none says the turn looked something up on a turn whose only contact was
> outward. `records` establishes that the records were available to composition and
> nothing beyond it (§4), and a surface asserting more would be attributing the answer's
> content to material a model may have ignored entirely.

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
> §§6-9 is narrowed, widened or re-read here.** §6's eligibility stays *the disposition's
> presence and nothing else*; §7's precedence order, at-most-one rule and
> success-does-not-clear rule stay exactly as written; §8's vocabulary and total mapping
> are untouched; §9's statements bind verbatim.

> **Normative.** **One turn's `UNAVAILABLE` now rides beside a contact, and that is the
> design.** Where a response arrived and was refused — `PROVIDER_REFUSED`,
> `RESPONSE_TOO_LARGE`, `UNATTESTED` — ADR-0242 §8 maps it to `UNAVAILABLE`, whose
> statement §9 fixes as saying the lookup produced nothing usable and expressly **not**
> saying that no request was made. This decision supplies the other half of that
> sentence, which §9 declined to assert because it had nothing establishing it. Read
> together they say: a request was made, and nothing usable came back.

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
about its own conduct; deciding it here would be this ADR reaching into a decision it has
not read. §12 names the trigger.

### 11. The lane cut

> **Normative.** The implementation is **two lanes**, in this order, and neither may
> absorb the other's paths.
>
> 1. **Contract and `orchestration`.** `OutboundDestination`, `OutboundContact` and
>    `TurnOutcome.outbound_contact` in `core/types.py`; the §2/§3 establishment and the
>    §6 carrier in `ai_assistant.orchestration`; the composing fragment and
>    `_PLAN_IS_ABOUT_ACTING`'s widened condition; every arm of §13. The two packages ride
>    in one lane under ADR-0137 §2 — a contract seam and the primary production
>    implementation whose demands shape it — and under no wider reading of it.
> 2. **The terminal surface.** `interfaces/cli.py` renders §7's statement. No logic, no
>    store read, no computation (golden rule 3).
>
> The browser's rendering is #2237's lane and is not a lane of this decision (§9).

> **Normative.** Lane 1 changes `core/types.py`, so **this ADR is ratified and merged as
> its own PR before anything implements against it** (golden rule 5, ADR-0015 §5). This
> PR is that one, and it changes no code.

### 12. What this decision does not decide, by name, each with what fires it

> **Normative.** **Whether a `TRANSPORT_FAILED`, `DEADLINE_EXPIRED` or `SEARCH_FAILED`
> servicing reached the world** (§2). Deciding it needs a fact from below the
> `WebSearcher` seam — whether bytes were written — which no value the site holds today
> carries. **Fires** when a seam records it, or when a deployment reports a user misled
> by the silence on one of those three.

> **Normative.** **An egress step whose callable was entered and then failed, and one
> whose addressed status is `INDETERMINATE`** (§3). ADR-0192 §1's ledger claim is the
> record of the first and it is behind `ToolInvoker`; the second is ADR-0029 §4's
> may-have-acted shape, which no value on the step separates. **Fires** on the first
> widening that brings the claim, or an equivalent fact, out to `StepOutcome` — which is
> a `core` change and takes its own ADR.

> **Normative.** **Whether a reply that denies a recorded contact is recorded as a
> defect** (§10). **Fires** with the audit-recording ADR #2291 already owes.

> **Normative.** **The browser's rendering of this statement and of ADR-0242 §9's**
> (§9). **Fires** with #2237's lane, which is already owed.

> **Normative.** **A per-servicing or per-call account in a reply or on a surface.** §4
> refuses the enumeration and this ADR mints no route back to one. **Fires** with a
> decision that argues the case ADR-0226 §9 and ADR-0228 §10 argue against.

> **Normative.** **A notification.** This is a statement in a reply and beside it, and no
> lane mints a `Notification`, a notification kind, a delivery or a poll result for an
> outbound contact — ADR-0235 §8's second clause, binding here as ADR-0242 §6 made it bind
> there.

### 13. The arms this decision owes

> **Normative.** The implementing lane owes these six arms, each over representative
> input, and a lane that lands fewer has not implemented this decision.
>
> 1. **A search that minted records into the supply, over a turn whose pre-existing
>    supply is non-empty.** `destinations` is `(SEARCH_PROVIDER,)`, `records` is the
>    number of **minted** records composition was given and **not** the pre-existing
>    ones, `search_not_serviced` is `None`, and the prompt carries §6's fragment and
>    `_PLAN_IS_ABOUT_ACTING`. The non-empty pre-existing supply is what makes the arm
>    discriminate: a lane reading `ServicedRead.supplied` passes every other arm and
>    fails this one.
> 2. **A search that reached the provider and returned nothing** (`SearchRefusal.NO_RESULT`),
>    on a turn whose pre-existing supply is **non-empty**. `outbound_contact` is set with
>    `records` `0`, `search_not_serviced` is `None` (ADR-0242 §6's third clause), and the
>    rendered statement states the `0` rather than eliding it.
> 3. **A search refused before the send** (`RULING_DENY`). `outbound_contact` is `None`,
>    `search_not_serviced` is `DECLINED`, and the composing prompt is byte-identical to
>    what it is without this decision.
> 4. **A response received and then refused** (`UNATTESTED`). **Both** members are
>    carried — `outbound_contact` with `records` `0`, and `search_not_serviced`
>    `UNAVAILABLE` — and both statements render (§8).
> 5. **Three egress steps over one tool, and only the first carries a contact**: one
>    whose addressed `StepExecution` is `SUCCEEDED`, where `destinations` is
>    `(EGRESS_TOOL,)` and `records` is `0`; one whose disposition is `EXECUTED` and whose
>    addressed step is **`FAILED`** because the invocation claim was refused before the
>    callable, which carries **no** contact; and one refused at the gate, which carries
>    none either.
> 6. **A turn that both searched and sent, in that encounter order and in the reverse.**
>    `destinations` is `(SEARCH_PROVIDER, EGRESS_TOOL)` in both, which is the declared
>    order and not the encounter order (§4); and the one fragment §6 fixes is rendered
>    once, stating the contact rather than a lookup.

### 14. Scope, and what this records against earlier ADRs under ADR-0082 §1

> **Normative.** This decision is a **stacked addition**: it adds obligations that
> contradict no sentence any earlier ADR wrote, so under ADR-0082 §1 it is recorded in
> this ADR and **nowhere else** — no `Status` qualifier and no dated note on any earlier
> ADR. The paragraphs below apply ADR-0070 §1's test to each clause a reader might expect
> a record for, naming the sentence and the verdict.

**ADR-0242 §9's *"`TurnOutcome` gains exactly one field"* — no record owed.** That clause
states what *that* decision adds, not a closure on `TurnOutcome`; ADR-0244 §9 and ADR-0250
§5 have each since added members without recording against it, and ADR-0250 §5 added four.
A reader holding only ADR-0242 builds `search_not_serviced` exactly as §9 describes it and
is wrong about nothing.

**ADR-0242 §6's byte-identity guarantee — no record owed, and this is the one worth being
explicit about.** §6 promises that on a turn carrying no `SearchNotServiced` member *"the
assembled prompt is byte-identical to what it is today"*. §6 makes that promise about its
own carrier, as ADR-0228 §10 and ADR-0227 §3 each make it about theirs — and those three
already hold simultaneously over one prompt, which is only possible on the self-scoped
reading. Read as a closure on the prompt, ADR-0242 §6 would have falsified ADR-0228 §10 on
the day it was ratified and would have recorded it; it did not, so the corpus already
settles the reading. This decision adds nothing on a turn carrying no contact, which is the
promise in the sense the corpus holds it.

**ADR-0170 §4 — no record owed.** A `None`-defaulting member changes neither the three
shapes on which `reply` is `None` nor the one on which `reply_degraded` is `True`. ADR-0197
§8, ADR-0235 §4, ADR-0242 §9 and ADR-0250 §5 made the identical move. Two of them did
record a supersession of ADR-0170 §4, and in both it was for moving a **shape** and not
for adding a member: ADR-0197 §8 made a `turn`-`None` outcome able to carry a reply, and
ADR-0250 §5 added a second `turn`-`None` shape. This decision moves no shape.

**ADR-0198 §2 — no record owed.** The restatement's enumeration gains a value and loses
none: `turn`, `routed`, `reply`, `reply_degraded` and `step` carry there exactly what §2
says, and `None` is the true value of a member describing something a restatement did not
do. ADR-0242 §9 and ADR-0235 §4 state this in the same words for their own members.

**ADR-0226 §9 and ADR-0238 §11 — no record owed, and `records` is expressly not
theirs.** No count is added to, removed from or redefined in the per-turn audit record,
and §4 states in terms that `records` is neither ADR-0238 §11's `supplied` nor derived
from it: that count is what this system told a destination, assigned before the send, and
this one is what came back and was put in front of composition. The record those sections
govern is unchanged and gains nothing.

**ADR-0249 §7's `minted` and ADR-0227 §3's `hop_reached` — no record owed.** §4 reads
`minted` and copies `hop_reached`'s shape; it redefines neither, adds to neither, and
takes neither out of the use its own ADR gives it. A second consumer of a carrier is not
a change to the carrier — the position ADR-0242 §6's own second consumer of
`ServicedRead.disposition` already stands in.

**`_PLAN_IS_ABOUT_ACTING`'s condition (§6) — no record owed.** That line and its condition
come from issue #2213 and from code; no ADR clause fixes when it is appended. Widening the
condition falsifies no ratified sentence.

### 15. This ADR classified under ADR-0070 §1 and ADR-0082 §1

> **Normative.** Under ADR-0070 §1 this is a decision **standing on its own**: no reader
> holding any earlier ADR would now act differently about what that ADR decided, and no
> clause of one is read more widely. It is therefore neither a supersession nor an
> amendment, and §14 records the test's answer for each candidate.

> **Normative.** This ADR is **marked** under ADR-0089: every obligation it imposes is in
> a marked clause, and text beside a mark is read to determine what the clause means and
> supplies no obligation of its own (ADR-0089 §3). Marking is forward-only (§5) and
> nothing already ratified becomes marked by this.

## Consequences

- **The system can no longer tell a user it reached nothing on a turn it reached the
  world.** The statement is composed from a typed value by code, renders beside the
  reply, and cannot be talked out of by the prose next to it. That is the whole of what
  #2268 asks for and the whole of what this decision claims.
- **A `0` becomes sayable.** *I reached outside this system and nothing from it was in
  front of me* is a sentence the system has never been able to make; it is the honest account of a search
  that found nothing, and it is the sentence whose absence made #2268 read as a
  contradiction rather than as a thin reply.
- **Three dispositions stay silent, on purpose.** A transport failure, a deadline expiry
  and a raised fault carry no contact statement, because the system does not know. Each
  already carries a `SearchNotServiced` member whose statement is true, so the user is
  told something rather than nothing — but the honest sentence about the wire is not
  available, and §12 says what would make it so.
- **The egress half is under-inclusive until `StepOutcome` carries the claim.** An egress
  call that was dispatched and then failed goes unstated, and so does one whose step is
  `INDETERMINATE`, because `EXECUTED` is the gate's verdict and the addressed status is
  the only thing under it that separates a call from a refusal. That is stated rather
  than discovered, and it is the narrow direction: the statement is never false, only
  sometimes absent.
- **`TurnOutcome` grows to sixteen members**, ten of them `None`-defaulting facts a
  client renders on its own. That is ADR-0244 §9's rule working as designed and also the
  thing to watch: an eleventh and a twelfth make a client's rendering order a decision
  nobody has taken.
- **Revisit when** a second outbound seam lands, when `StepOutcome` gains the dispatch
  fact, or when a deployment reports a user misled by the silence §2's third group keeps.
