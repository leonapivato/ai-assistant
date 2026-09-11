# 244. A `CONFIRM` on a search parks as a durable question, and the answer runs that exact read once

- Status: Proposed
- Date: 2026-09-10
- **Partially supersedes** [ADR-0231](0231-the-planner-asks-for-a-search-the-turns-own-words-compose-it-and-the-results-come-back-as-records.md)
  — **§9's second clause in three of its limbs, §9's fifth clause in its one-route limb,
  and §16's first clause in its any-store limb. Nothing else in that ADR.** §9's second
  clause closes *"**The servicer asks the user nothing and parks nothing.** … A recorded
  `CONFIRM` on a `WEB_SEARCH` decision **resolves in no turn**: no lane resumes it, offers
  it to an interface, or treats it as outstanding work, and §19 defers the surface that
  would."* §1 below has the servicing **park the read** and §6 has a lane **resume** it, so
  the *parks-nothing* limb, the *resolves-in-no-turn* limb and the *treats-it-as-outstanding-work*
  limb each move (ADR-0235 already took the *offers-it-to-an-interface* limb, for the
  establishing act alone, and §1 below is the second thing that limb now admits).
  **The asks-the-user-nothing limb binds entire** — the servicing puts no question inside
  the turn, composes from the supply it has and returns, and ADR-0226 §5's clause that no
  implementation *"raises out of the turn, parks **it**, or puts a question to the user"*
  is obeyed rather than moved: what parks is the **read**, never the turn.
  §9's fifth clause closes *"The one route to an `ALLOW` is ADR-0193's **standing recipient
  grant**"*; §7 below reaches an `ALLOW` by ADR-0148 §3's route **(a)** — a recorded
  resolution of a `CONFIRM` about this request — which ADR-0231 §9 itself named and closed
  only *"because it needs someone to ask, which ADR-0226 §5 forbids the servicer doing"*.
  This ADR supplies the asker; the grant route is untouched, and ADR-0193 §4 binds entire,
  so **no grant covers a request whose binding carries `planned_with_external_content`**.
  §16's first clause closes *"nothing is written to any store on account of a search"*; §3
  below writes the park. **Its subject — the minted record — is untouched**: no minted
  record is ingested, proposed, folded, superseded or written to the `MemoryStore`, §16's
  second, third, fourth and fifth clauses bind entire, and the park holds no minted record
  at all. **§9's first, third and fourth clauses bind entire** — a `WEB_SEARCH` request is
  serviced only on a **recorded `ALLOW`** (§7 obeys it rather than relaxing it), the
  composing stage is told what ADR-0242 §6 tells it and no more, and no lane makes a search
  reachable by weakening its declaration. §§1–8, §10–§15, §17–§21 and §11's servicing order
  are untouched, and §13's audit gains what §17 below states and nothing else.
- **Partially supersedes** [ADR-0235](0235-the-establishing-act-rides-an-answer-to-a-confirmation-live-or-recorded-and-a-refused-search-reaches-the-user-as-history-and-not-as-work.md)
  — **§3's seven-condition closure in that count alone, and §8's first clause in its
  nowhere-else limb. Nothing else in that ADR.** §3 makes the establishing act available
  *"on a decision meeting **all seven** of the following"*; §5 below adds an **eighth** — the
  decision's id is not named by a `ParkedRead` whose disposition is `OPEN`, `APPROVED` or
  `DENIED` — because a decision whose question a park is holding, or has just taken the
  answer to, is answered through `resume` and not through a second act, which is §3's own third
  clause read at a park that carries no `step_id` (*"no lane reaches this operation from a
  park by clearing either field"*). **The seven conditions themselves bind verbatim**, their
  order is unchanged, the eighth is tested after them, and `UngrantableActError` names it as
  it names the others. §8's first clause closes *"The message that a search was refused is
  `grantable_decisions`' listing and the act offered beside it … and is **nowhere else**"*;
  ADR-0242 §7 already put a statement in the reply, and §4 and §13 below put the **question
  itself** on the surface as a confirmation a user may answer. **§8's second and third
  clauses bind entire**: this is not a notification and no lane mints one, and neither the
  listing, the reply nor the rendered question states that the turn would have answered
  differently, that a reply was incomplete, that a search would have succeeded, or that
  anything is owed. §§1–2, §4–§7, §9–§14 are untouched; §9's per-channel posture is extended
  for this kind by §13 below rather than moved.
- **Partially supersedes** [ADR-0242](0242-the-act-that-trusts-a-destination-has-its-own-surface-and-a-search-that-did-not-happen-is-explained-in-the-reply.md)
  — **§8's eight-member closure in that count alone, three rows of §8's mapping table, and
  §9's statement enumeration by one member. Nothing else in that ADR.** §8 closes
  `SearchNotServiced` *"at exactly **eight** members"* while providing that *"no
  implementation or later ADR adds a ninth member without the ADR that decides it"*: §11
  below is that ADR and adds `ANSWER_AWAITED`, so the enumeration becomes **nine**. The
  eight members, their values, their declared order relative to one another, the
  added-to-and-never-renamed rule, the totality of the mapping and its non-injectivity all
  stand entire. The three `RULING_CONFIRM` rows are **discriminated rather than
  re-pointed**: where the read **parked**, the member is `ANSWER_AWAITED`; where it did not,
  each row keeps the member it has today, which is what keeps §8's
  `AUTHORISATION_AWAITED`-asserts-exactly-two-things clause **true**, since an unparked
  `CONFIRM` is still one the establishing act may ride and a parked one is not.
  §9's *"one fixed statement per member"* enumeration gains the ninth member's statement and
  no other changes: every statement §9 fixes for the existing eight binds verbatim, and
  §9's bars — no statement says performing the act will make the next search happen, none
  says why a ruling was not an `ALLOW`, and none carries a destination, a query, a count, a
  figure, a `Settings` field name or a `SearchDisposition` value — bind on the ninth exactly
  as on the eight. §§1–7, §10–§18 are untouched, and §7's carrier, its precedence rule and
  its at-most-one-per-turn clause bind entire.
- **Partially supersedes** [ADR-0052](0052-durable-resume-of-a-parked-confirmation.md)
  — **§3's `TurnOutcome(turn=None, step=<resolution>)` sentence, as it reaches a resume
  answering a parked *read*, and nothing else in that ADR.** §3 rules that *"A resume driven
  from a recovered park returns `TurnOutcome(turn=None, step=<resolution>)`; the in-process
  path is unchanged and still carries the real turn."* §8 below has an approved read's
  resume carry a **real** `TurnResult` and a composed reply and **no** `step` at all, so a
  reader holding only ADR-0052 would build the wrong outcome — ADR-0070 §1's test met, and
  a third scope beside ADR-0197 §13's routed pair and ADR-0198 §8's restatement. **§3's own
  reason is obeyed rather than overturned**: it refuses to *"fabricate a `TurnResult` with
  empty context and memories — which would misrepresent what the turn saw"*, and §2 below
  persists the two members that would otherwise be fabricated while §8 assembles the other
  two afresh and says which is which. **§1, §2 and §4 bind entire**, and so does the rest of
  §3 — a recovered park still re-mints its continuation from durable state, the handle stays
  an opaque re-derivable token, and `_Parked.turn` stays optional.
- **Requires new `core` contract surface and lands none of it** (§2, §3, §4, §9, §11).
  Flagged under golden rule 5: it is ratified and merged as its own PR before anything
  implements against it (ADR-0015 §5).
- **Its required review set is adversarial *and* architecture**, the set `CONTRIBUTING.md`
  requires of the ADR deciding `core/protocols.py` and `core/types.py` surface.
- **It moves `PROTOCOL_VERSION` from 34 to 35**, stated up front rather than found by the
  implementing lane (§17), by ADR-0124 §9's rule in three of its limbs at once.
- **It fixes the contract half of [#2221](https://github.com/leonapivato/ai-assistant/issues/2221)**
  and takes no position on [#2212](https://github.com/leonapivato/ai-assistant/issues/2212),
  whose posture is postponed to a security pass and which this ADR does not move. Batch
  [#2222](https://github.com/leonapivato/ai-assistant/issues/2222) carries the
  pre-registered acceptance scenarios §19 binds to by number.

## Context

### Where this comes from

Milestone 31 made searching the normal case, and the milestone-31 QA re-probe found that on
the owner's own store it never happens. #2221 records the dead end and #2206 the probe.
The chain is short and every link is ratified:

1. A context-bearing search's request carries `planned_with_external_content` `True`,
   because ADR-0181 §5's lineage floor is met by any retrieved record resting on recorded
   external content — which on a store with any history is nearly every turn (#2212).
2. `ActionPolicy` therefore rules `CONFIRM`: ADR-0193 §4 gives no standing grant over such
   a request, and the disclosure floor fires in any case.
3. ADR-0231 §9 rules that such a `CONFIRM` *"resolves in no turn: no lane resumes it, offers
   it to an interface, or treats it as outstanding work"*, so nothing is sent and nothing is
   asked.
4. ADR-0242 §6 puts a statement in the reply. Under §8's mapping the recorded
   `RULING_CONFIRM` with an external-content binding at a `USER_CHOSEN` destination is
   `UNAVAILABLE` — the member that *"names no cause and no act"* and whose §9 statement says
   the lookup produced nothing the turn could use.

So the user asks a question, the assistant silently declines to look, and the reply says the
lookup produced nothing. Every clause behaved as written. What is missing is the one thing
ADR-0231 §9 named and did not build: **an asker**. ADR-0148 §3 has always carried two routes
to an `ALLOW` on an egress call — a standing grant, and *a recorded resolution of a `CONFIRM`
about this request* — and ADR-0231 closed the second in terms, because *"it needs someone to
ask, which ADR-0226 §5 forbids the servicer doing"*. This ADR supplies the asker, and it
supplies it out of machinery this corpus already has for actions.

### What the tree already has, read rather than assumed, at `origin/main` `2602bff9`

- **A durable confirmation binding.** ADR-0044 puts `execution_id` on the request and the
  decision, extends the resolution invariant so a binding *"may carry at most one
  resolution"*, and adds `AuditTrail.pending_confirmation` so a restarted process can find
  the question a binding still awaits.
- **A durable resume.** ADR-0052 enumerates parked executions, re-mints a continuation
  token from durable state, and answers it through `AssistantEngine.resume` — a token that
  is *"re-derivable from durable state on demand"* rather than a structured value carried
  across a restart.
- **A confirmation that carries its egress.** ADR-0178 gives `Confirmation` the
  `ConfirmationEgress` member — the account identity and the binding's own spans, from which
  the canonical destination set derives — and §7 states the floor every surface rendering one
  owes: the identity, every occurrence with the argument it was selected by, both destination
  forms where a span carries one, whole and untruncated, as data neutralised on render.
- **A search request that is an `ActionRequest` like any other.** ADR-0231 §6 has
  `orchestration` build it, `EgressBinder.bind` derive its binding, `ActionPolicy.decide`
  rule on it and the `AuditTrail` record the decision — everything ADR-0148's per-call
  machinery does, with only the **route** to the send moved off `ToolInvoker.invoke`.
- **A rebind that refuses what an approval did not cover.** ADR-0152 §7's `rebind` derives
  the binding afresh and *"refuses unless the binding it derived is **equal** to
  `approved`"*, taking from the approved value nothing but each span's provenance.
- **A lifetime on the record.** ADR-0059 §1's `expires_at` fixes *when* a `CONFIRM` stops
  being answerable, at the instant the question was asked.

Four facts about that machinery decide the shape of this decision, and each is checked in
the tree rather than remembered.

**The decision is there and the query is not.** `ActionRequest.parameters` are *"bound by
digest, never stored"* (ADR-0148 §6) and `EgressBinding`'s spans *"hold no content"*
(ADR-0150 §10), which ADR-0231 §13 states as a consequence in terms: an auditor *"can
establish **that** a search was authorised, to which origin, at what instant, with a payload
of what extent, and whether it succeeded — and cannot establish what was asked."* So the
trail cannot re-present the question, and §3 below decides where the question lives.

**A search has no step and may not be given one.** ADR-0231 §6 rules that
`PermissionDecision.step_id` is `None` and `execution_id` is `None` on a `WEB_SEARCH`
decision, and that *"no lane synthesises a plan step, an `ExecutionState`, an execution or a
claim on one in order to satisfy a clause written about steps"*. ADR-0052's recovery walks
`plans.active_executions()` and reads a step's raw parameters from the plan; neither reaches
a search. The park's durable identity is therefore the **recorded decision**, not a binding
of two ids — which is the population ADR-0235 §3 already reads.

**`Confirmation` already carries the query.** `Confirmation.parameters` is *"The arguments
the tool would run with, as structured data"*, and a search request's parameters are exactly
the origin and the composed query. So a surface rendering a read's confirmation renders the
exact query today, through the member it already renders, and §4 below adds a discriminator
rather than a second copy of the text.

**`TurnOutcome` refuses a reply where `turn` is `None`.** ADR-0170 §4 fixes the three shapes
on which `reply` is `None` — a park, a recovered resume, a composition failure that published
nothing — and the model validator refuses prose on the first two *in both directions*. An
approved read that answered the user through a turn-less outcome is therefore not
constructible, which is why §8 decides the continuation's shape rather than leaving it to a
lane.

### What this ADR is not allowed to settle

- **#2212's posture.** The lineage floor and what a `planned_with_external_content` `True`
  binding costs are postponed to a security pass. This ADR changes no rule of ADR-0181 and
  reaches its outcome without one: what it adds is a way to **answer** the `CONFIRM` that
  floor produces, not a way to avoid producing it.
- **Parallel or concurrent reads.** Scheduling, dependency and snapshot semantics, and more
  than one outstanding ask per kind are the owner's handoff document's second half and are
  M32/M33's. §20 defers them by name with what fires them. ADR-0231 §11's servicing order is
  untouched.
- **The general cancellation obligation.** #2173's L7 covers user correction and
  cancellation during execution; §11 below decides the boundary for this operation kind
  alone (#2217) and leaves #2173 open.
- **Whether a search should be planned at all**, what the composer may see (ADR-0238 §2),
  and what a destination's recorded trust admits (ADR-0238 §5). None of them moves.

## Decision

### 1. A recorded `CONFIRM` on a `WEB_SEARCH` request parks the read, and the turn does not park

> **Normative.** Where a `WEB_SEARCH` servicing records a `CONFIRM`, the servicing site
> **parks the read**: it writes one `ParkedRead` (§2) to the `ParkedReads` store (§3),
> naming the recorded decision, and yields no records into the supply. Where the park is
> written the servicing's disposition is still `SearchDisposition.RULING_CONFIRM` — §13 of
> ADR-0231 names the **stage that produced the outcome** and the stage is unchanged — and
> §12 below decides what the user is told.

> **Normative.** **The turn does not park, is not suspended and does not fail.** The
> servicing returns to `service_read_request`, the remaining kinds are serviced in
> ADR-0231 §11's fixed order, the supply is what it would have been, and the turn composes
> and returns its reply. ADR-0226 §5 binds entire — no implementation *"raises out of the
> turn, parks **it**, or puts a question to the user on account of a read that did not
> land"* — and ADR-0231 §9's asks-the-user-nothing limb binds with it: **what parks is the
> read, and the question is offered by a surface after the turn has ended.**

> **Normative.** **A park is written only where the store accepted it.** Where
> `ParkedReads` refused or raised, no park exists, nothing is outstanding, and the
> servicing is exactly what it is today: the decision stands unresolved on the trail, the
> establishing act may ride it where ADR-0235 §3's conditions hold, and §12's mapping gives
> the turn the member it gives today. **A lane that reported a park it did not write would
> tell the user to answer a question nothing holds**, which is the one failure this section
> is stated to prevent.

> **Normative.** **Nothing is sent, opened, claimed or spent when a read parks.** No
> channel is opened, no credential is read, no `ToolCall` is constructed, no
> `InvocationLedger` claim is appended, no minted record exists, and ADR-0194's spend
> admission is not reached. ADR-0231 §9's first clause is obeyed and not relaxed: the
> servicing of this kind yields nothing, and it yields nothing **on the record already
> recorded**.

> **Normative.** **The conversation's search call is spent, and parking does not refund
> it.** `admit_search` was answered before the ruling and ADR-0238 §8 rules that *"An
> admitted call is consumed whatever the outcome, and there is no refund"*. §6 states what
> is asked again at resume; **no lane increments, decrements, re-admits or reserves a draw
> on account of a park.**

**Parking the read rather than the turn is the whole design, and it is what makes this
compatible with the section that forbade it.** ADR-0231 §9 refused parking on a stated
argument — that it *"would put a durable confirmation, a resume path, a wire operation and a
surface behind a mechanism ADR-0226 §5 designed to be invisible, and would let a marginal
improvement in reach take a reply down"*. The second half is the objection that mattered, and
this decision does not incur it: **no reply goes down.** The turn that asked completes,
composes and answers exactly as it does today, ADR-0242 §6's statement tells the user a
lookup did not happen, and the only thing that is new is that the lookup is still there to be
made. The first half — a durable confirmation, a resume path, a wire operation, a surface —
is a cost this ADR pays deliberately, because the milestone that made searching normal turned
*"a marginal improvement in reach"* into the mechanism's ordinary path.

**And the third alternative ADR-0231 §9 refused is the one this ADR builds, so it is
answered in its own terms.** That section refused *"recording a pending confirmation for the
user to answer later"* because it *"invents an outstanding-work concept the corpus has
nowhere to put and that nothing would resolve"*. The corpus does have somewhere to put it —
ADR-0044's durable binding, ADR-0052's re-minted continuation and ADR-0178's rendered
confirmation are that concept, built for actions and ratified since. What was true in
ADR-0231's own terms is that **nothing would resolve it**, and §6 below is the resolver.

### 2. The park record: `ParkedRead`, and the three things it must not carry

> **Normative.** `core/types.py` gains **`ParkedRead`**, a frozen model with
> `extra="forbid"`, whose fields are exactly: `id`, the park's own identifier, minted by the
> injected factory and never by a caller; `conversation_id`, the conversation the parked turn
> ran under; `decision_id`, the recorded `CONFIRM` this park holds the question of;
> `parameters`, the search request's arguments **byte for byte as the ruling was taken over
> them** — the origin and the composed query, and nothing else; `goal`, the `Goal` the parked
> turn was planned against; `plan`, the `ActionPlan` the planner returned on that turn;
> `parked_at`, the instant the park was written; `expires_at`, the instant past which it is
> no longer answerable (§3), **required with no default**; and `disposition`, a
> `ParkedReadDisposition` naming the park's state.

> **Normative.** **The three content fields are typed `| None` and a validator states when
> each is present: all three on an `OPEN` park, none on a terminal one.** `parameters`, `goal`
> and `plan` are the fields settlement clears (§3), and the type is what expresses the two
> shapes rather than a rule to remember — a terminal park read back with a fabricated `Goal`
> or an empty `ActionPlan` would misrepresent a record, and one read back with its query
> intact would breach the retention rule in the one place a reader would not look. **A model
> validator refuses both halves**: a park whose `disposition` is `OPEN` carrying any of the
> three as `None`, and a terminal park carrying any of them at all.

> **Normative.** `core/types.py` gains **`ParkedReadDisposition`**, a `StrEnum` valued by
> lower-cased member name and closed at exactly **five** members: `OPEN`, the question stands
> and may be answered; `APPROVED`, the user answered **yes** and the park's one answer was
> spent on that answer; `DENIED`, the user answered **no** and the park's one answer was spent
> on that; `CANCELLED`, the question was withdrawn without an answer (§11); and `EXPIRED`, the
> deadline passed with no answer. **`OPEN` is the only non-terminal member**, the other four
> are terminal, and no transition leaves a terminal member. The vocabulary is added to and
> never renamed.

> **Normative.** **`APPROVED` records what the user said and asserts nothing about what
> followed.** It does **not** state that a ruling was recorded, that the read was dispatched,
> that a request left the device or that any record came back: §6 takes the gate before it
> asks the policy, so an `APPROVED` park beside no recorded resolution is a reachable and
> honest state. **What happened after the answer is the trail's and the ledger's to say**, and
> a lane reading a disposition as evidence of a send has read the wrong record.

> **Normative.** **A `ParkedRead` carries no minted record, no result, no snippet, no title,
> no address, no origin beyond the one its `parameters` already state, no credential, no
> `SecretName`, no connection reference, no `BoundAccount` and no binding.** The binding, the
> account identity and the canonical destination set are the **recorded decision's**, read
> through `decision_id` at the moment a confirmation is assembled, exactly as ADR-0178 §5
> already rules for every other confirmation: *"the engine populates `egress` from the
> **recorded** `PermissionDecision` the confirmation is about"*. No field is added to
> `ParkedRead` through which any of them could travel, and no lane copies one into it.

> **Normative.** **`parameters` are the ruling's own and are checked against the recorded
> `CONFIRM`, not trusted from the store.** The request rebuilt from them carries the
> decision's own `tool`, hashes to its `parameters_digest`, and carries `step_id` and
> `execution_id` both unset — the three facts a `CONFIRM` fixes about its subject
> (ADR-0021 §1, ADR-0044 §1) — and §6's clause 4 refuses the answer where any of them
> differs. **`PermissionDecision.authorises` is not the check here and cannot be**: it
> returns `True` only where `ruling.outcome is PermissionOutcome.ALLOW`, so it is `False`
> of every `CONFIRM` by construction; it is the check the **resolving `ALLOW`** passes
> before a `ToolCall` is constructed and is re-evaluated at the seam (ADR-0231 §6), which
> is where §7 applies it. **The subject check here and the authorisation check there are
> two checks at two instants**, and a lane collapsing them would refuse every parked read.

> **Normative.** **The `goal` and the `plan` are persisted because §8 composes over them
> and would otherwise fabricate them.** They are read at resume, are never rendered to the
> user as part of the question (§4), are never handed to the query composer, and are
> **never** a route by which a model composes a new query — §16's third refusal binds on
> them by name.

**Three fields carry Tier 1 content, and that is stated here rather than discovered.**
`parameters` holds the composed query, `goal` holds the objective minted from the utterance,
and `plan` holds what the planner decided. ADR-0004 §2's residency clause governs all three:
an implementation persists **locally only**, and §3's retention rule is what keeps the
exposure bounded in time rather than in principle. This is the same trade `ConversationStore`
and the `MemoryStore` already make for conversation history, and it is why the park is a
store and not a log: ADR-0004 §5's *"Tier 0/1 data must never be logged"* is untouched, and
ADR-0231 §13's audit event gains none of it (§17).

**The plan is persisted rather than re-derived, and re-deriving it would be the wrong kind
of cheap.** Re-planning at resume would put a model call between the user's *yes* and the
read, would let the planner ask for a **different** read — a second question behind an
answered one — and would produce a `TurnResult` whose `plan` is not the plan the parked turn
ran. ADR-0014 §2's frozen plan is the value the turn actually had; persisting it is how the
continuation stays a continuation.

### 3. The store: `ParkedReads`, one open park per conversation, and content that lives exactly as long as the question

> **Normative.** `core/protocols.py` gains **`ParkedReads`**, a durable store with exactly
> these seven members and no more:
>
> - `async def park(self, record: ParkedRead, /) -> bool` — writes an `OPEN` park, or
>   answers `False` where this conversation already holds one. The read of the existing park
>   and the write are **one indivisible step**.
> - `async def get(self, park_id: str, /) -> ParkedRead | None` — the park under that id, or
>   `None`.
> - `async def open_park(self, conversation_id: str, /) -> ParkedRead | None` — this
>   conversation's open park, or `None`.
> - `async def park_of_decision(self, decision_id: str, /) -> ParkedRead | None` — the park
>   naming that decision, **whatever its disposition**, or `None` where no park names it. It is
>   what §5's eighth condition is decided from, it survives a restart because the row does, and
>   it is a second read rather than a widening of `get`: the token path holds a park id and the
>   listing path holds a decision id, and neither has the other's.
> - `async def outstanding(self) -> tuple[ParkedRead, ...]` — every `OPEN` park, in
>   `parked_at` order, for §5's enumeration.
> - `async def settle(self, park_id: str, /, *, disposition: ParkedReadDisposition, at:
>   UtcInstant) -> bool` — moves an `OPEN` park to a terminal member and **clears
>   `parameters`, `goal` and `plan` in the same step**, answering `True` to the caller that
>   moved it and `False` to every other. The read, the comparison and the write are one
>   indivisible step, and `settle` on an already-terminal park answers `False` and changes
>   nothing.
> - `async def drop_for_conversation(self, conversation_id: str, /) -> int` — removes **every**
>   park of that conversation, open or terminal, content and terminal facts alike, and answers
>   how many rows it removed. It is the one destructive member, it is the conversation
>   deletion sequence's route (below), and it is idempotent: a second call answers `0`.

> **Normative.** **A conversation holds at most one `OPEN` park.** `park` enforces it, and
> the enforcement is the store's rather than a caller's for `admit_search`'s own reason
> (ADR-0238 §8): two turns of one conversation, two servicings of one turn, and two engines
> over one data directory can none of them be admitted against the same conversation's park.
> A servicing whose `park` answered `False` has written no park, and §1's third clause
> governs what it then is.

> **Normative.** **One park names one decision, and `park` refuses a second naming the same**
> — which is what makes `park_of_decision` a single answer rather than a listing. It holds by
> construction as well as by rule, since one servicing records one `CONFIRM` and writes at most
> one park for it, and the clause is stated so that an implementation cannot reach a state
> where two rows answer one decision id.

> **Normative.** **`settle` is the resolve-once gate, and it is what makes a duplicate
> answer a no-op rather than a second dispatch.** No lane reads a park, decides, and writes
> back; no lane dispatches a read before `settle` has answered `True` for it; and a caller
> that lost the compare-and-swap dispatches nothing, sends nothing and reports the settled
> state. That is ADR-0044 §2(b)'s one-answer invariant — *"once **any** confirmation for it
> is resolved, the binding is decided"* — restated for a park, at the seam a read has instead
> of a binding of two ids.

> **Normative.** **A settled park keeps its terminal facts and loses its content.** `id`,
> `conversation_id`, `decision_id`, `parked_at`, `expires_at` and `disposition` survive
> settlement; `parameters`, `goal` and `plan` do not, and no implementation retains a copy,
> a digest of the query, a snapshot or an archive of them. **The content lives exactly as
> long as the question does**, which is the retention rule this ADR states and the whole of
> what it states: ADR-0231 §16's *"nothing was retained"* posture holds of a read that ran,
> because what the park held is gone the moment the read is dispatched.

> **Normative.** **Every park carries a deadline, and there is no spelling for a park
> without one.** `core.config.Settings` gains exactly one field, **`parked_read_ttl:
> timedelta`**, required, with a default of **PT24H** and refused at load where it is zero
> or negative. It admits **no disable sentinel**, unlike `confirmation_ttl`, and for
> `routed_confirmation_ttl`'s stated reason: a park nothing can free is a durable row
> holding Tier 1 content that no act, no enumeration and no reclaim would ever reach.
> `expires_at` on the `ParkedRead` and on the recorded `CONFIRM` (§6) are both computed from
> it, once, at the instant the park is written.

> **Normative.** **The conversation's deletion sequence drops that conversation's parks
> through `drop_for_conversation`**, and it is the capture/lifecycle stage in `orchestration`
> that calls it — *"the one layer that legitimately holds both handles by injection"*
> (ADR-0074 §9). **It reaches the store through the Protocol and never through a concrete
> one** (golden rule 1), which is why the member is on the contract rather than left to an
> implementation. An **open** park stranded by a crash in that sequence is **not** an
> unrecoverable orphan: it carries its own `expires_at`, `outstanding` enumerates it, and
> §10's expiry settles it and clears its content without any reference to the conversation
> record. A **terminal** park stranded there holds no content at all (§3), so what is left is
> six scalar facts that the next deletion call removes. **No lane adds a cross-store
> reconciliation walk, a tombstone, a stamp of its own or a second lifecycle.**

**A store of its own, where ADR-0238 §8 refused one — and the disanalogy is the whole
argument.** That section moved a per-conversation counter **onto the conversation record**
because *"a draft gave the budget a `SearchBudgetStore` of its own, and every protocol for
telling it about a deletion failed in a different place"*: the reclaim *"only learns a
conversation is eligible **once `drop_if_eligible` has already destroyed the record**"*, so
one process death *"strands the counter with nothing able to rediscover it"*. **A park is
rediscoverable and a counter is not.** A counter is keyed by conversation id, has no terminal
event, no deadline and no enumeration that would ever visit it again; a park has all four, so
the failure mode that decided ADR-0238 §8 is closed here by the deadline rather than left
open by a store. Putting the park on the conversation record instead would breach that
contract's own stated invariant — `ConversationStore` *"holds no content"*, and a park holds
three content fields — and would give one store two tiers of obligation.

**And `permissions/` is where the implementation belongs, for the reason `SqliteSourceReadTrail`
is already there.** ADR-0004 §7 charters that subsystem for gating access to Tier 0/1 data
*and* recording it; a park is the unanswered half of a recorded permission question, joined to
the trail by `decision_id`. It is **not** the `AuditTrail`, for ADR-0097 §4's reason applied
here: the trail's premise is that its records are not fabricated and its invariants are stated
over `tool`, `parameters_digest`, `step_id` and `execution_id` — putting the query itself into
it would breach ADR-0148 §6's *"bound by digest, never stored"* in the one store that clause is
about.

### 4. `Confirmation` gains one field, and it is the discriminator rather than a second copy of the query

> **Normative.** `Confirmation` gains exactly one field: **`read: ReadKind | None`**,
> **required with no default**, carrying the kind of read the question is about and `None`
> on a confirmation about a plan step. No other member of `Confirmation` is added, removed,
> renamed, re-typed or re-defaulted, and `extra="forbid"` and `frozen=True` are unchanged.

> **Normative.** **`read is not None` is the discriminator**, in ADR-0178 §4's shape and for
> its reason: absence is the state and the type is what expresses it. What it states is that
> **answering this question dispatches a read rather than a plan step**, and nothing more. No
> lane reads it as a warrant about what the read will return, whether it will run, or what
> the reply will then say.

> **Normative.** **The exact query is already carried and no field is added for it.**
> `Confirmation.parameters` is the search request's own argument mapping — the origin and
> the composed query, byte for byte as the ruling was taken over them — and it is what a
> surface renders. **No lane adds a summary, an abbreviation, a normalised form, a
> re-cased form, a truncation or a paraphrase of the query to this type**, and none renders
> one (§9).

> **Normative.** `Confirmation.tool_id` and `tool_description` are the **searcher's own
> registered declaration**, held by value as they are for a tool, and `reason` is the
> recorded `CONFIRM`'s own `reason`. `egress` is populated exactly as ADR-0178 §5 rules —
> from the recorded decision the confirmation is about, at the assembly site, from no store
> read of its own — and on a `WEB_SEARCH` park it is **always present**, because ADR-0231
> §5 registers the search integration at the egress seam and ADR-0231 §9 declines the
> servicing where the binder returned nothing.

> **Normative.** **The `goal`, the `plan` and the conversation's history are not part of the
> question and no surface is given them.** The engine reads `goal` and `plan` from the park
> for §8's continuation and puts neither on the `Confirmation`. What the user judges is what
> would leave the device — the query, the destination in both forms, the account identity
> and the payload description — which is ADR-0148 §8's fourth clause and no more than it.

**One field rather than a nested value, which is where this departs from ADR-0178 §1 and
why.** That section chose one nested value over four fields because four independent optional
members *"admit fifteen partial states"*. There is one fact here and no partial state to
reach, so a nested one-field model would be a container with nothing to contain. What
survives from §1 is the part that mattered: the field carries **no default**, for §1's stated
reason — `Confirmation` is built at the engine's assembly sites, in the canonical fake and in
every test that builds one, and *"a defaulted field is what a lane forgets"*.

**And a `ReadKind` rather than a bare bool, because the kinds are already enumerated and the
next one is coming.** ADR-0226's read request has four kinds and ADR-0240 added a fifth; this
decision parks exactly one of them (§20 defers the rest with what fires them). A bool would
have to be widened into an enum by the first ADR that parks a second kind, and widening a
wire-carried type is what ADR-0124 §9 charges a version for.

### 5. `pending_confirmations` lists a parked read, and the establishing act does not offer one

> **Normative.** `AssistantEngine.pending_confirmations` enumerates **`ParkedReads.outstanding`
> beside** ADR-0052 §1's parked steps, and assembles one `Confirmation` per `OPEN` park:
> `parameters` from the park, `tool_id`, `tool_description` and `reason` from the recorded
> decision, `egress` by ADR-0178 §5, `read` the park's kind, and a continuation token
> registered against the park's id. Its signature does not move.

> **Normative.** **The enumeration settles an expired park rather than offering it**, so
> `pending_confirmations` never offers a question that cannot be answered, and the settlement
> happens at the read rather than in a sweep of its own. **It settles nothing else**: an
> `OPEN` park that has not expired is offered, never closed, whatever any other record says
> (§6's one-gate clause). **No lane adds a background task, a reclaim pass or a scheduler.**

> **Normative.** **The token is re-minted from durable state and is opaque**, exactly as
> ADR-0052 §1 rules for a step: durability comes from the handle being *"re-derivable from
> durable state on demand"*, no adapter constructs or interprets one, and a restart empties
> the handle table and the next call re-mints (ADR-0084 §7).

> **Normative.** **Enumeration is idempotent and holds no ceiling slot.** A park already
> named by a handle reuses that handle rather than minting a second, which is ADR-0052 §2's
> reconciliation at a second population; and a read park **does not consult and does not
> occupy `max_outstanding_confirmations`**, which bounds the `converse` path's *new*
> in-process parks. What bounds read parks is §3's one-per-conversation rule and their
> deadline, and refusing to surface a park that already exists would strand it — ADR-0052
> §2's own reason.

> **Normative.** **`grantable_decisions` gains an eighth condition: the decision's id is not
> named by a `ParkedRead` whose disposition is `OPEN`, `APPROVED` or `DENIED`** (ADR-0235 §3).
> It is evaluated after §3's seven, in that position, and `UngrantableActError` names it
> exactly as it names the others where the act is attempted on such a decision.
> **The read that decides it is `ParkedReads.park_of_decision` (§3)**, which answers whatever
> park names that decision, open or terminal, so the exclusion survives a restart and is taken
> through the contract rather than from a concrete store (golden rule 1).

> **Normative.** **The condition is stated over the three dispositions and not over an open
> park, because the gate is taken before the resolution is written (§6).** A park that
> settles `APPROVED` or `DENIED` holds a resolution the answering call has not yet recorded,
> and a decision that left this listing at the settlement would be one the establishing act
> could resolve **first** — recording an `ALLOW` the user never gave that answer for, and
> leaving the answering call's own append to fail. The transition `OPEN` → `APPROVED` →
> (recorded) therefore never passes through a grantable state, which is the property this
> clause exists to have rather than an implementation note.

> **Normative.** **A park that was `CANCELLED` or `EXPIRED` does not exclude its decision.**
> Neither disposition writes a resolution and neither ever will, so the decision is an
> unresolved `CONFIRM` exactly as §3's seven conditions find it, and the establishing act may
> ride it where they hold. **No lane widens the exclusion to every park ever written**, which
> would take a capability away on the strength of a question nobody answered.

> **Normative.** **One question, one act, and the split is decided rather than incidental.**
> A decision a park holds is answered through `resume`, and answering it is what dispatches
> the read; the establishing act *"resumes nothing and services nothing"* (ADR-0235 §3), so
> offering both on one row would let a user perform the act that changes nothing about this
> lookup while the lookup's own question stood unanswered beside it. **The establishing act
> is not removed from this population** — a settled park's decision, and a `CONFIRM` no park
> was written for (§1), each stay subject to ADR-0235 §3 on their own terms.

> **Normative.** **The act still rides an answer where a park holds the confirmation.**
> `resume`'s `remember_recipients_until` reaches a read park's answer exactly as ADR-0235 §2
> rules it, unchanged: §2's binding refusal governs, so a request whose binding carries
> `planned_with_external_content` establishes nothing (ADR-0193 §4), and ADR-0235 §6's order of the
> two records and its ceiling enforcement bind entire. This ADR adds no clause to either.

**Listing the two populations from one operation is what keeps one renderer.** ADR-0178 §5's
fourth clause already rules that *"a recovered confirmation carries the **same** egress
content a live one carries"* so that *"a surface therefore needs one renderer, not two"*. A
read's confirmation is a third population of the same type, and a surface that already
renders ADR-0178 §7's floor renders it with the one branch §4's discriminator gives it.

### 6. The answer: `resume`, the one gate, and the six things established at that instant

> **Normative.** A parked read is answered through **`AssistantEngine.resume`** and through
> no second operation. Its signature does not move, `approved` carries the answer, and an
> unknown token raises `UnknownContinuationError` as it does today.

> **Normative.** **Six things are established at the instant of the answer, in this order,
> and the read is dispatched only where every one of them holds.**
>
> 1. **The park.** `get` answers a park, its `disposition` is `OPEN`, and `expires_at` is
>    strictly after the clock's reading (ADR-0059 §1's comparison). An expired park is
>    settled `EXPIRED` and the answer is refused as stale (§10).
> 2. **The conversation.** `search_draw` answers a draw for `conversation_id` — so a
>    conversation that names nothing or is stamped deleted refuses (ADR-0238 §14) — and
>    `Settings.search_calls_per_conversation` is not `0`, which ADR-0238 §8 defines as *"no
>    search is serviced in any conversation"*. **`admit_search` is not called and no second
>    call is drawn**: the call was admitted before the ruling and consumed whatever the
>    outcome (§1).
> 3. **The decision.** The trail holds the decision `decision_id` names, its ruling is a
>    `CONFIRM`, no decision resolving it is recorded, and its own `expires_at` has not passed.
> 4. **The subject.** The request is rebuilt from the park's `parameters` and the searcher's
>    own registered declaration, and it is the recorded `CONFIRM`'s **own subject**: the same
>    `tool`, a `parameters_digest` equal to the decision's, and `step_id` and `execution_id`
>    both unset. `EgressBinder.rebind` then derives the binding afresh and **refuses unless it
>    is equal to the recorded one** (ADR-0152 §7). **What the user was shown is what may be
>    sent**: a destination, an account identity or a payload description that moved between
>    the question and the answer is a refusal, not a send. **`PermissionDecision.authorises`
>    is not this check** — it is `True` only of an `ALLOW` and is therefore `False` of every
>    `CONFIRM` — and it is applied where it belongs, to the **resolving** decision, by
>    `ToolCall`'s own validator and again at the seam (§7, ADR-0231 §6).
> 5. **The gate.** `settle` moves the park from `OPEN` to the member the **user's answer**
>    names — `APPROVED` on `approved` `True`, `DENIED` on `False` — and answers `True` to
>    exactly one caller. **Only that caller proceeds.** A caller answered `False` has not
>    taken the park's one answer: it rules nothing, records nothing, sends nothing, and
>    returns `ALREADY_SETTLED`.
> 6. **The ruling.** `ActionPolicy.resolve` is asked with the user's `approved`, and **its
>    answer is recorded whatever it is** — the second obligation ADR-0235 §3 already relies
>    on, and ADR-0004 §7's reason: a ruling the trail never sees is a decision nobody can
>    audit. On `approved` `True` an `ALLOW` dispatches (§7) and any other answer dispatches
>    nothing and is `AUTHORITY_CHANGED`; on `approved` `False` the recorded answer is the
>    `DENY` the user asked for and the outcome is `DECLINED` (§10). **The park is already
>    spent either way**, and `AUTHORITY_CHANGED` is reserved for an approving answer the
>    policy refused.

> **Normative.** **The gate is the park's compare-and-swap, and every settlement is taken by
> the party about to act on it, before it acts.** An answer settles it (clause 5); a
> cancellation settles it (§11); **nothing else settles an `OPEN` park on the strength of a
> record it read** — not a second `resume`, not a store read, not a comparison of the trail
> with the park, and not a reconciliation of any kind. That is what makes "one answer, at most
> one dispatch" a property of one atomic write rather than of an agreement between several
> readers.

> **Normative.** **Expiry is the one settlement no party takes for itself, and it can take
> nothing from anyone.** A park past its `expires_at` is settled `EXPIRED` by whatever
> operation next reads it (§5, §10), which is safe precisely because clause 1 refuses to
> answer such a park at all: there is no live answerer for the settlement to race. **No other
> condition is given this treatment**, and a lane that settled an unexpired park from a record
> it read has broken the clause above.

> **Normative.** **The gate is taken before the resolution is recorded, and that order is
> the decision rather than an accident.** Recording first and settling after leaves a window
> in which a second party sees an answered decision beside an open park and has to guess
> whether the first is still running — and any rule it follows there either strands the park
> or takes the settlement away from a live dispatcher, so that an approved read dispatches
> **zero** times. Settling first has no such window: a park the trail resolves was settled
> before that resolution was written, so an `OPEN` park is never one somebody else has
> answered.

> **Normative.** **What the order costs is stated rather than hidden.** A process that dies
> between clause 5 and clause 6 leaves a park `APPROVED` with **no** resolution recorded and
> nothing sent: the user's answer was accepted, the question is closed, and the lookup did
> not happen. **Nothing re-opens it** — the user's recourse is to ask again — and nothing is
> unrecorded in ADR-0004 §7's sense, because no decision was taken: the policy was never
> asked. That is a bounded loss of one answer, and it is preferred to the unbounded hazard
> the other order carries, which is a send nobody authorised or a send made twice.

> **Normative.** **Order 4 before 6 is ADR-0152 §7's, not a preference.** The binding must be
> whole before the ruling that authorises the resumed call (ADR-0148 §1), so the rebind
> happens *before* `resolve` is reached — *"which is the ruling that authorises the resumed
> call, so it is §1's earliness on the second ruling exactly as `bind` is on the first"*.
> Clause 5 sits between them because it is a gate on **acting** rather than a step of the
> authorisation, and because a park spent on an answer the subject check would have refused
> is an answer the user has to give again for no reason.

> **Normative.** **Nothing else is consulted for authority.** No standing recipient grant is
> read, established, extended or implied by an approval (§16); `trust_of` is not asked again
> and no destination's recorded trust is written; and no threshold, floor or `Settings` value
> is relaxed to reach the `ALLOW`. **The approval is the authority, and it is ADR-0148 §3's
> route (a) — a recorded resolution of a `CONFIRM` about this request — and no other.**

> **Normative.** **The three remaining budgets are re-established where they have always
> been established, and this ADR moves none of them.** ADR-0194's spend admission runs at
> the seam after ADR-0231 §6's three pre-execution checks and before the ledger claim;
> ADR-0241 §1's deadline is passed to `search` from `Settings.search_call_deadline` at
> dispatch; and ADR-0192's claim and completion are the seam's. Each is therefore evaluated
> **at the instant of the dispatch and not at the instant of the park**, which is the whole
> of what "re-checked" means here.

> **Normative.** **A duplicate answer dispatches nothing and says so.** A second `resume` on
> a settled park's token is refused by clause 1 or clause 5 and returns `ALREADY_SETTLED`; it
> consults no policy, opens no channel, records nothing and mints nothing. ADR-0198 §§1–4's
> restatement governs a token whose *binding* this engine settled and retains; this clause
> governs a park whose settlement is durable, and the two agree: **one answer, at most one
> dispatch, however many times a token is presented.**

> **Normative.** **A refused resolving append is never raised out of `resume`.** Clause 5
> makes the already-resolved ground of `InvalidResolutionError` unreachable through this
> path — the park's one answer was taken before the append was attempted — so a refusal here
> is one of that class's other grounds, or a fault. The answer is **not** recorded, the park
> stays spent, nothing is dispatched, and the outcome is `OPERATION_CHANGED`. **It is
> returned and not raised**, because a refusal on `resume` is a result (§9).

### 7. Approval runs that exact read once, by the route ADR-0231 §6 already fixed

> **Normative.** On a recorded `ALLOW` and a park this caller settled, the read is dispatched
> **by ADR-0231 §6's route, unchanged**: `orchestration` builds the `ToolCall` over the
> **resolving `ALLOW`** — unconstructable unless that decision `authorises` the request — and
> hands it to `WebSearcher.search`, which
> performs ADR-0029 §2's three pre-execution checks in order, ADR-0194's spend admission,
> ADR-0192's claim, the send and the completion. **No lane adds a second route, a second
> servicing site, a second caller of `request` or a plan step.** ADR-0231 §6's last clause
> binds entire: nothing here opens a route for any other send.

> **Normative.** **The query is the approved query and the model composes nothing.**
> `QueryComposer` is not called at resume, no model call precedes the send, and the value
> passed to the searcher is the park's own `parameters` — the ones the ruling was taken over
> and the ones the user read. ADR-0231 §11's *"the only value `WebSearcher.request` is ever
> passed"* clause is satisfied by identity here: what was composed in the parked turn is what
> is sent, and no repair, extension, truncation or re-casing is admitted between them.

> **Normative.** **The records the read mints are ADR-0231 §10's, unchanged**, and they are
> supply and never a store write (ADR-0231 §16). They carry their provenance and their
> attestation exactly as they do on an unparked servicing, they are deduplicated and admitted
> under ADR-0226 §6's budget of ten, and they resolve in no store: a park's approval changes
> where a search happens in time and changes nothing about what a search **is**.

> **Normative.** **The dispatch is one call.** `settle` is the gate and it is taken before the
> policy is asked (§6), so an approval that raced another, a token presented twice, a restart
> between the answer and the send, and two engines over one data directory can none of them
> produce a second call.

> **Normative.** **Three crash states exist after the gate and each is named rather than
> reconciled.** A crash **before the ledger claim** — between the settlement, the recorded
> ruling and the claim — leaves **no invocation row at all**, which ADR-0192 §1 admits and
> which nothing infers a send from. A crash **after the claim and before the completion**
> leaves the claim **open**, and ADR-0231 §6's clause governs it verbatim: such a claim states
> as its own state that the search may have reached the provider, nothing reconciles it, and
> **no lane adds a recovery arm, completes it from outside the seam or resolves it by
> guessing.** A crash **after the completion** leaves a finished row and a park already
> terminal. In all three the park is spent and the user's recourse is to ask again.

### 8. The continuation: a resumed turn that composes over the approved read and says which is which

> **Normative.** An approved read's `resume` returns a `TurnOutcome` whose **`turn` is a real
> `TurnResult`**, whose `step` is `None`, whose `routed` is `None`, whose `conversation_id` is
> the park's, and whose `reply` is composed. Its `goal` and `plan` are **the parked turn's**,
> read from the park; its `context` and `memories` are **assembled at the instant of the
> resume** by the ordinary pipeline, with the approved read's minted records appended as
> ADR-0226 §7's **fourth group** in servicing order, over the deduplicated union, constructed
> once.

> **Normative.** **Two members are the parked turn's and two are the resumed turn's, and the
> outcome does not pretend otherwise.** ADR-0052 §3 refuses to *"fabricate a `TurnResult` with
> empty context and memories — which would misrepresent what the turn saw"*, and this clause
> obeys that reason by persisting what would have been fabricated (§2) and assembling the rest
> for real. No implementation fills `context` or `memories` from a snapshot, a cache or an
> archive of the parked turn, and none reports the resumed turn's supply as the parked turn's.

> **Normative.** **The resumed turn plans nothing and services nothing else.** No planner call
> is made, so no `read_request` arises, no other read kind is serviced, ADR-0228 §2's revision
> is not reached, and no second search is composed, ruled or parked. **A resume that found
> itself planning has left this decision's fence.**

> **Normative.** **The reply is composed over the union and is the ordinary composition.**
> ADR-0170 §4 binds unchanged: `reply` is non-`None` because `turn` is non-`None` and this is
> not a park, and `reply_degraded` reports a composition that did not complete, on that shape
> and no other. Where the dispatched read yielded no records — it was refused, expired,
> interrupted or returned nothing — the turn still composes, and ADR-0242 §6's carrier gives
> the composing stage its member exactly as it does on any other turn.

> **Normative.** **The exchange is captured as a turn's exchange is captured.** The resumed
> turn appends to the conversation, its episode is written through the path that already
> writes one, `capture_degraded` reports a capture that did not land, and ADR-0223 §1's
> `derived_from_external` stamping is computed over the resumed turn's **final** supply, which
> carries the minted records. This decision adds no capture, no writer and no second retention
> rule (ADR-0231 §16).

> **Normative.** **The parked turn's own reply stands and is not amended, replaced, retracted
> or annotated.** It was a true answer over the supply that turn had. Nothing rewrites it, no
> lane edits its episode, and the resumed turn is a further exchange in the conversation rather
> than a correction of an earlier one.

**Why the continuation is a turn rather than a delivery of records.** The alternative was to
return the minted records to the surface and let the user ask again. It fails on three counts,
each checkable. The records are turn-scoped and resolve in no store (ADR-0231 §16), so a
surface holding them has nothing it may cite them by and no later turn can reach them. The
reply is *"the only place"* an answer is stated (ADR-0170 §3), and `interfaces/` composing one
over records is golden rule 3's business logic in an adapter. And a user who has just answered
*yes* to a lookup has expressed the question already; making them retype it would spend a
second `admit_search` draw, a second composition and a second ruling to reach the answer the
first one authorised.

### 9. What the question and the answer ride: the two members `TurnOutcome` gains

> **Normative.** `TurnOutcome` gains exactly two fields, both typed optional and both
> defaulting to `None`, and each docstring names this ADR as the decision that added it:
>
> - **`read_confirmation: Confirmation | None`** — the confirmation for a read **this turn
>   parked**, so the question appears in the exchange that raised it. It is `None` on every
>   turn that parked no read.
> - **`read_answer: ReadAnswerOutcome | None`** — what became of an answer to a parked read.
>   It is `None` on every outcome that answered none.

> **Normative.** **The two are mutually exclusive and the type states it.** A `converse` or
> `converse_streaming` outcome may carry the first and never the second; a `resume`
> answering a parked read carries the second and never the first; ADR-0198 §1's restatement
> and ADR-0197 §7's routed park carry neither. A model validator refuses an outcome carrying
> both, in `StepOutcome._confirmation_matches_disposition`'s own spirit — a shape a caller
> cannot reach is better refused by the type than documented.

> **Normative.** `core/types.py` gains **`ReadAnswerOutcome`**, a `StrEnum` valued by
> lower-cased member name, closed at exactly **seven** members, added to and never renamed:
>
> 1. **`DISPATCHED`** — the read ran; the outcome's `turn` and `reply` carry what it produced
>    (§8).
> 2. **`DECLINED`** — the answer was no; the `DENY` is recorded and the park is `DENIED`.
> 3. **`ALREADY_SETTLED`** — the park was answered, denied, cancelled or expired before this
>    answer arrived; nothing was dispatched and the recorded answer stands.
> 4. **`EXPIRED`** — the deadline passed before the answer arrived; the park is settled
>    `EXPIRED` and nothing was dispatched.
> 5. **`AUTHORITY_CHANGED`** — `ActionPolicy.resolve` answered other than an `ALLOW` at the
>    instant of the answer; the ruling **is** recorded, nothing was dispatched, and the park is
>    spent (§2).
> 6. **`OPERATION_CHANGED`** — the rebuilt request is not the recorded `CONFIRM`'s own
>    subject, the binding derived at the instant of the answer is not the one the ruling was
>    taken over, or the trail refused the resolving append; nothing was dispatched, and where
>    the subject or the binding failed the park is still `OPEN` while a refused append leaves
>    it spent and the answer unrecorded (§6).
> 7. **`UNAVAILABLE_NOW`** — the conversation no longer exists or is stamped deleted, or
>    `search_calls_per_conversation` is `0` in this deployment; nothing was ruled and nothing
>    was dispatched.

> **Normative.** **Every refusal is returned and none is raised**, which is
> `AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception` binding at the
> seam it is stated over. `resume` raises `UnknownContinuationError` for a token this engine
> does not hold, exactly as it does today, and **this ADR mints no error class**. ADR-0235
> §3's `UngrantableActError` is the shape for an operation whose *return* is a grant and has
> no disposition to carry a refusal in; `resume` has one, and §3 says so in terms.

> **Normative.** **Where more than one member is true, the first in the order above is the
> one carried**, so the answer is deterministic across implementations, and no lane branches
> on a message. `ALREADY_SETTLED` and `EXPIRED` are ordered ahead of the three change members
> because a park that is closed is not a question any recheck could re-open.

> **Normative.** **`read_answer` states what became of the answer and never why a ruling went
> the way it did.** No member carries, and no statement rendered for one carries, a
> destination, a host, an origin, a provider name, an account identity, a query or any
> fragment of one, a monetary figure, a budget, a threshold, a `Settings` field name or a
> `SearchDisposition` value. That is ADR-0242 §9's bar, binding on this vocabulary as it
> binds on that one, and for the same reason.

> **Normative.** **`SpokenTurn` gains nothing**, and a spoken turn's servicing parks exactly
> as any other's. The park is durable and is answered from a surface that admits the act
> (§13); the spoken reply says a lookup awaits an answer and names no command, which is
> ADR-0242 §9's `SpokenTurn` clause and §5's placement posture unchanged.

**Two members rather than one, because they are two facts and a turn holds at most one of
them.** Collapsing them into a single "read" member would give one field a `Confirmation` on
one path and an enum on another, which is a union a client must discriminate before it can
render either. Each is the shape ADR-0197 §8, ADR-0235 §4 and ADR-0242 §9 already used — one
`None`-defaulting member per fact, widening `TurnOutcome` without touching ADR-0170 §4's
three `reply`-`None` shapes or its one `reply_degraded` shape.

### 10. Denial and expiry: terminal, recorded, and the sibling turn's reply stands

> **Normative.** **A denial takes the same gate in the same order.** `resume` with `approved`
> `False` takes §6's clauses 1–4, **settles the park `DENIED` at clause 5**, and only then
> asks `ActionPolicy.resolve` and records the `DENY`; it returns `read_answer` `DECLINED`
> with `turn` `None` and `reply` `None` — ADR-0170 §4's second shape exactly. **A denial that
> lost the gate rules nothing and records nothing** and returns `ALREADY_SETTLED`, exactly as
> a losing approval does, so an approval and a denial racing one park cannot leave the park
> saying one thing and the trail the other. **Nothing is sent, no channel is opened, no claim
> is appended, and no minted record exists.**

> **Normative.** **An expiry is settled and is never dispatched.** A park whose `expires_at`
> is at or before the clock's reading is settled `EXPIRED` at the first operation that reads
> it — an answer (returning `EXPIRED`), an enumeration (which does not list it), or the
> conversation's own next servicing. The settlement clears the content (§3), records no
> ruling, and the decision on the trail stays the unresolved `CONFIRM` it was.

> **Normative.** **An expired park's decision is not thereby made grantable, and it is not
> thereby made ungrantable either.** ADR-0235 §3's seven conditions decide it on their own
> terms, and §5's eighth stops excluding it — an `EXPIRED` park writes no resolution and never
> will (§5). **No lane infers a recipient grant, a trust record or a policy change from an
> expiry**, and none reads the row's return to that listing as anything but the absence of a
> question a park was holding.

> **Normative.** **The parked turn's reply stands on every terminal disposition.** A denial,
> an expiry and a cancellation each leave the earlier exchange exactly as it was: its reply
> is not amended, retracted, annotated or re-composed, its episode is not edited, and no
> notification is minted for any of the three. ADR-0235 §8's second clause binds entire —
> *"a notification is a decision about interrupting the user and this ADR takes none"* — and
> neither does this one.

> **Normative.** **No terminal disposition is inferred from silence.** A park is `OPEN` until
> something settles it, and `OPEN` is not read as approval by any component: the read is
> dispatched by §6's clauses 5 and 6 together and by nothing else, and there is no timeout, retry, sweep or
> reclaim that dispatches a read the user did not answer.

**The expiry is a settlement rather than a deletion, and the difference is one the user can
see.** A row that vanished would make a duplicate answer indistinguishable from a mistyped
token, and ADR-0198's whole argument for restating a settled binding is that *"the engine
states what was decided rather than refusing to say"*. So the terminal facts survive
(§3) and the content does not, which lets the surface say "that lookup expired" instead of
"no such question".

### 11. Cancellation for this operation kind, and the boundary it does not cross

> **Normative.** `AssistantEngine` gains exactly one operation:
> `async def cancel_read(self, token: ContinuationToken, /) -> ReadCancellation`. It is the
> cancellation source #2217 names, **for this operation kind alone**, and it takes no other
> argument, no reason, no free text and no deadline.

> **Normative.** `core/types.py` gains **`ReadCancellation`**, a `StrEnum` closed at exactly
> **three** members: **`WITHDRAWN`**, an `OPEN` park was settled `CANCELLED` and nothing was
> ever sent; **`INTERRUPTED`**, a read this process had dispatched and had not completed was
> cancelled; and **`NOTHING_TO_CANCEL`**, the park is settled and no dispatch of it is running
> here. An unknown token raises `UnknownContinuationError`, exactly as `resume` does.

> **Normative.** **Cancelling an `OPEN` park withdraws the question and records no answer.**
> `ActionPolicy.resolve` is not called, no ruling is recorded, and the decision on the trail
> stays the unresolved `CONFIRM` it was — which is the whole difference from a denial: a
> denial is the user answering *no* and is a ruling; a cancellation is the user withdrawing
> the question and is not one. The park is settled `CANCELLED` and its content is cleared in
> the same step (§3), so a cancellation and a concurrent answer cannot both take effect.

> **Normative.** **A cancellation takes §6's gate and takes it the same way.** It settles the
> park `CANCELLED` through the one compare-and-swap, so a cancellation racing an answer is
> decided by that write and by nothing else: a cancellation that lost it answers
> `NOTHING_TO_CANCEL` where the answer is already running or done, and an answer that lost it
> returns `ALREADY_SETTLED`. **Neither party acts on a park the other took.**

> **Normative.** **Cancelling a dispatched read cancels the task running it, and the seam's
> accounting is ADR-0241 §7's, unchanged.** *"A cancellation that interrupted the call
> completes the claim before it re-raises, with `interrupted_outcome` and an `UNKNOWN` cost,
> and releases the channel"*; `CancelledError` is re-raised and is converted into neither an
> outcome nor a refusal; a cancellation delivered after the outcome was established changes
> no row. **This ADR adds no clause to ADR-0241 and no lane cites this section toward a
> deadline, a `WebSearcher` argument or an accounting rule.**

> **Normative.** **What is cancelled is the `resume` call running the dispatch, and no
> `TurnOutcome` is produced for it.** The cancellation is a teardown and is converted into
> neither an outcome nor a refusal (ADR-0060 §1, ADR-0241 §7): nothing catches it to compose
> a reply over a supply that has no records, and no lane invents a `read_answer` member, a
> `SearchNotServiced` member or a `SearchDisposition` for it. What tells the user is
> **`cancel_read`'s own answer**, which is the act they performed.

> **Normative.** **A cancelled dispatch leaves the park `APPROVED` and does not re-open it.**
> The question was answered, the call was made, and ADR-0241 §7's *"the deadline stops the
> waiting, not the work"* posture applies to a cancellation just as it does to an expiry —
> **no caller assumes the query did not leave.** The user's recourse is to ask again, and no
> lane reports a cancelled dispatch as a park that can be answered a second time.

> **Normative.** **A cancellation reaches only a dispatch running in the process that
> received it.** There is no durable cancellation record, no cross-process signal and no
> cancellation queue; a park settled `APPROVED` whose dispatch is running elsewhere answers
> `NOTHING_TO_CANCEL`, which is true of what this process can do. That is honest under
> ADR-0043's one-resident-process-per-data-directory posture rather than in spite of it, and
> **§20 defers the general case with what fires it** — #2173's L7 obligation, which this ADR
> leaves open.

> **Normative.** **Cancellation establishes nothing and forfeits nothing.** It records no
> ruling, revokes no grant, writes no trust record, and does not refund the conversation's
> spent `admit_search` call (ADR-0238 §8). A cancelled park frees the conversation's one
> open-park slot (§3) and nothing else.

**Two states, one operation, and the alternative was worse.** A separate `withdraw` and
`interrupt` would ask the caller to know which state the park is in before it acts — a race
by construction, since the state can change between the read and the call. One operation whose
answer *reports* which of the two happened puts the discrimination where the atomicity already
is, which is `settle` (§3) and the running task's own registry.

### 12. `SearchNotServiced` gains `ANSWER_AWAITED`, and three rows are discriminated rather than re-pointed

> **Normative.** `SearchNotServiced` gains one member, **`ANSWER_AWAITED`**, so the
> enumeration is closed at **nine** and is declared **first**, which is also its position in
> the precedence order ADR-0242 §7 applies. It names: *the search was put to the user as a
> question, the question is recorded and open, and it awaits their answer.*

> **Normative.** **It is declared first because it is the only member naming work the system
> is still holding.** The other eight name something that already ended — a deployment
> setting, an unadmitted conversation, a ceiling, a `DENY`, a destination the user has not
> chosen, a recorded decision an act may ride, a search begun and stopped, and the residue.
> A member that lost the tie-break on a turn holding one of those **and** an open park would
> leave the park unmentioned in the one place the user reads, and an unmentioned park is one
> nobody answers. Inserting at the head leaves every existing pairwise order and every
> existing value unchanged.

> **Normative.** **The three `RULING_CONFIRM` rows of ADR-0242 §8's table are discriminated
> by one further fact — whether a park was written — and are otherwise unchanged**:
>
> | `SearchDisposition` | park written | `SearchNotServiced` |
> | --- | --- | --- |
> | `RULING_CONFIRM`, any binding, any `trust_of` answer | yes | `ANSWER_AWAITED` |
> | `RULING_CONFIRM`, `planned_with_external_content` `False` | no | `AUTHORISATION_AWAITED` |
> | `RULING_CONFIRM`, `planned_with_external_content` `True`, `trust_of` `UNCHOSEN` | no | `TRUST_MISSING` |
> | `RULING_CONFIRM`, `planned_with_external_content` `True`, `trust_of` `USER_CHOSEN` | no | `UNAVAILABLE` |
>
> **Every other row of ADR-0242 §8's table is untouched**, the mapping stays total over all
> eighteen `SearchDisposition` members, its non-injectivity stands, and a member minted by a
> later ADR still maps to `UNAVAILABLE` unless that ADR maps it elsewhere.

> **Normative.** **The discriminator is a fact the servicing site holds and not a store read**
> (ADR-0242 §7): the site wrote the park, or its `park` answered `False`, and that boolean is
> the whole of the further input. **No renderer, no adapter and no composing stage reads
> `ParkedReads` to compute a member**, and no component recomputes the carrier downstream.

> **Normative.** **This is what keeps ADR-0242 §8's `AUTHORISATION_AWAITED` clause true.**
> That member *"asserts exactly two things, both established"*, the second being that the
> decision *"is one the establishing act **may ride**"*. A parked decision is **not** one
> (§5's eighth condition), so a parked `CONFIRM` reported as `AUTHORISATION_AWAITED` would
> assert something false. The discrimination is therefore obligatory rather than cosmetic,
> and `TRUST_MISSING`'s and `UNAVAILABLE`'s clauses are preserved by the same move.

> **Normative.** **`ANSWER_AWAITED` asserts exactly two things, both established**: that a
> `CONFIRM` was recorded rather than the search made, and that a park holding that question
> is open — both known to the site by construction, neither read back from a store. It
> asserts **nothing** about which floor fired, nothing about what grants or trust records
> stand, nothing about what the read will return, and nothing about whether approving it
> will produce an answer the user wants.

> **Normative.** **The prompt fragment for it is fixed, written in
> `ai_assistant.orchestration`, and interpolates nothing** (ADR-0242 §7). It carries no
> destination, host, origin, provider name, account identity, query or fragment of one,
> record, count, monetary figure, duration, budget, `Settings` field name,
> `SearchDisposition` value, record id, decision id or command name. The reply says **a
> lookup awaits your answer** and never that the lookup produced nothing — which is the
> literal #2221 records as false and this clause's whole subject.

### 13. What a surface owes: the floor, the exact query, and the channels

> **Normative.** A surface rendering a `Confirmation` whose `read` is present owes
> **ADR-0178 §7's floor entire** — the account identity, every occurrence the `spans` carry
> with the argument it was selected by, both destination forms for the occurrences that carry
> a destination, the payload description, whole and untruncated, every value inserted as data
> and neutralised for that target on render. **Being a read relaxes no clause of it.**

> **Normative.** **It renders the exact query, as `Confirmation.parameters` carries it, and
> never a summary.** No surface abbreviates, elides, truncates, re-cases, normalises,
> re-wraps into a different quoting, translates or paraphrases the query, and none renders a
> description of it in its place. **A surface that showed the user less than what would leave
> the device has not put ADR-0148 §8's question**, and that is this clause's whole reason —
> the approver's judgement is over the bytes, which is ADR-0233 §1's decision read at this
> confirmation.

> **Normative.** **It says that answering *yes* dispatches this one read**, and it says no
> more than that. No surface states that the read will succeed, that the answer will change,
> that a standing authorisation is being created, that the destination becomes trusted, or
> that any later search is affected — ADR-0235 §8's third clause binding on this rendering
> as it binds on that listing.

> **Normative.** **The terminal now, the browser now, and voice withheld.** The command line
> and the browser each render the pending read, collect the answer, and offer the
> cancellation act (§11); a spoken channel renders neither the question nor the act, and a
> spoken turn's reply is the whole of what the user is told. **This ADR admits the browser
> for this kind rather than inheriting ADR-0235 §9's deferral of it**, because the batch this
> lane belongs to states its exit over both surfaces; ADR-0235 §9's browser deferral and
> voice withholding are untouched for the establishing act.

> **Normative.** **A surface that renders no statement for a `ReadAnswerOutcome` member it
> was given, or that renders a read's confirmation without §7's floor, has not implemented
> this section** — it is not permissibly degraded, which is ADR-0242 §9's last clause read
> here. What a surface may do is **refuse** a confirmation it cannot render, on the
> discriminator §4 gives it, exactly as ADR-0178 §4's second clause already permits.

> **Normative.** **No adapter reads a store, joins a row, computes a member or composes a
> reply.** Rendering a fixed statement per enum member is presentation (ADR-0242 §9), and
> golden rule 3 binds: `interfaces/` gains no read of a `PermissionDecision`, a `ToolCall`,
> an `ActionRequest`, an `EgressBinding` or a `ParkedRead`, and ADR-0042 §6's prohibition
> stands word for word.

### 14. A pending read holds no execution slot, and ADR-0231 §11's order does not move

> **Normative.** **A park holds no execution slot, no step, no `ExecutionState` and no
> claim.** ADR-0231 §6 binds entire: `step_id` and `execution_id` stay `None` on a
> `WEB_SEARCH` decision, and no lane synthesises a plan step, an execution or a `RUNNING`
> claim so that a clause written about steps has a subject here. A park blocks no plan, no
> step, no execution and no unrelated work in the turn that wrote it or in any later turn.

> **Normative.** **ADR-0231 §11's servicing order is unchanged** — local file, then web
> search, then citation hop, then sighted query — and so is its budget clause. A servicing
> that parked draws **no** slot of ADR-0226 §6's budget of ten, because it admits no record;
> the kinds after it are serviced with what they would have had; and the turn's fourth group
> is exactly what it would have been.

> **Normative.** **A conversation with an open park still converses, still plans and still
> services every other read kind.** What it does not do is write a second park (§3), and a
> servicing whose `park` answered `False` is §1's third clause — the decision stands
> unresolved and the turn is told what it is told today. **No lane blocks, queues, defers or
> fails a turn on account of an open park.**

> **Normative.** **Parallel and concurrent reads are out of scope** and nothing here decides
> them: one open park per conversation, one read per park, one dispatch per settlement. §20
> defers the general case by name with what fires it.

### 15. Restart survival: what is persisted, what is reconstructed, and what is neither

> **Normative.** **A park survives a restart and is offered again**, which is ADR-0052 §1's
> mechanism at a second population: `pending_confirmations` enumerates `ParkedReads.outstanding`
> from durable state and re-mints a continuation token for each open park. **Nothing durable
> holds a token**, and a restart empties the handle table exactly as ADR-0084 §7 rules.

> **Normative.** **Persisted:** the park's id, its conversation, its decision id, the request
> `parameters`, the `goal`, the `plan`, `parked_at`, `expires_at` and the disposition (§2).
> **Reconstructed at the moment it is needed:** the tool declaration and its description
> (from the searcher's own registration), the `reason` and the whole egress content (from the
> recorded decision, ADR-0178 §5), the continuation token (re-minted), the situational
> context and the supply (assembled at resume, §8), and the canonical destination set (derived
> by `core` as ADR-0178 §7 requires and never accepted from the wire as a materialised value).
> **Neither persisted nor reconstructed:** any minted record, any result, any snippet, any
> title, any address, any credential and any connection reference (§2).

> **Normative.** **A restart is not a second question and never a second dispatch.** The park
> re-offered after a restart is the same park, named by the same decision, settled by the same
> compare-and-swap; a park settled before the restart is not offered; and a dispatch that a
> crash interrupted leaves the park `APPROVED` and its claim open, which ADR-0231 §6 already
> rules is the honest state and not one to reconcile (§7).

> **Normative.** **A crash between the answer and the ruling leaves a spent park and no
> recorded decision, and nothing re-opens it** (§6). The park is terminal, its content is
> cleared, nothing was sent, and the recovery is the user's: ask again. **There is no
> intermediate state a restart has to resolve**, because the gate is taken before anything
> else is written — which is the property settling first buys and the reason this section is
> four sentences rather than a recovery protocol.

> **Normative.** **ADR-0231 §16's minted-record clauses bind entire across a restart.** A
> minted record's id *"is minted for one turn, rendered to no model, accepted from none, and
> resolves in no store"*; a park holds none, a restart recovers none, and no lane makes the
> park a route by which a record outlives its turn. What survives a restart is the
> **question**, and what survives the answer is the **episode** the resumed turn captured —
> which is exactly what ADR-0231 §16 already says survives a search.

> **Normative.** **Retention is the park's deadline and the conversation's lifecycle, and
> there is no third rule.** §3's `parked_read_ttl` bounds every park's content in time;
> ADR-0074 §8's `stamp_deleted`/`drop_if_eligible` bound it by the conversation, through the
> capture/lifecycle stage that drops a deleted conversation's parks (§3). **This ADR adds no
> retention setting, no archive, no export and no second reclaim.**

### 16. Refusals, stated as obligations rather than left to be inferred

> **Normative.** **There is no auto-approval, and no configuration reaches one.** No
> `Settings` field, no deployment mode, no threshold, no environment variable and no
> composition-root argument answers a park on the user's behalf, and none makes a park
> answer itself after an interval. `parked_read_ttl` **expires** a park (§10); it never
> approves one.

> **Normative.** **An approval establishes nothing standing.** It does not create, extend,
> renew or imply a recipient grant (ADR-0193), a destination trust record (ADR-0238 §5) or a
> policy change of any kind; it authorises **one** call, once, and ADR-0148 §3's route (a) is
> what it is. Where the user also performs the establishing act, that is ADR-0235 §2's
> `remember_recipients_until` riding the same answer and is a **second** recorded act with its
> own refusals (§5) — never an inference from the first.

> **Normative.** **The model cannot mint or alter the approved query.** No model call
> precedes the dispatch (§7), `QueryComposer` is not called at resume, and the value sent is
> the park's `parameters` checked against the recorded decision's digest (§2). **No component
> repairs, extends, truncates, re-cases, normalises or re-composes a parked query**, and a
> lane that found itself needing to has left this decision's fence.

> **Normative.** **#2212's rules are untouched.** ADR-0181's lineage floor, what marks a
> record as resting on recorded external content, and what a `planned_with_external_content`
> `True` binding costs are exactly what they are on `origin/main`. This decision neither
> narrows the floor, nor exempts a search from it, nor makes any binding fact easier to
> satisfy; it decides what happens **after** the `CONFIRM` that floor produces.

> **Normative.** **Existing action confirmations are byte-for-byte unchanged.** A
> confirmation about a plan step keeps every member it has, gains `read` `None` and nothing
> else, is assembled at the two sites ADR-0178 §5 names by the route it names, is enumerated
> by `pending_confirmations` as it is today, and is resumed by `resume` as it is today. **No
> clause of this ADR reaches a step's park**, and no lane reads a clause here as licence to
> change one.

> **Normative.** **No second route, no second servicing site, no second asker.** A search is
> composed at one site (ADR-0231 §11), sent by one route (ADR-0231 §6), and asked about in
> one way (§6). This decision opens no route for any other send and no park for any other
> read kind (§20), and a lane wanting either needs the ADR that decides it.

> **Normative.** **Nothing here weakens a declaration to reach an outcome.** ADR-0231 §9's
> fourth clause binds entire: a `discloses` narrowed, a `risk_level` or `reversibility`
> restated, a `cost` declared `FREE` where the figure is not known, or a deployment setting
> suppressing the disclosure floor are each the mis-declaration ADR-0016 §1 and ADR-0148 §2
> refuse, and **no reading of this ADR licenses one**. A park is the answer to a `CONFIRM`,
> never a way to stop one being produced.

### 17. The audit, `PROTOCOL_VERSION`, and the versions that do not move

> **Normative.** **ADR-0231 §13's audit binds entire and gains no field.** One `INFO`-level
> structured event per turn under the one fixed key, carrying counts and kinds and copying no
> text; a park adds no second event, no second key and no new emission point. The disposition
> a parked servicing records is `RULING_CONFIRM`, which is the member §13 already fixes for
> the stage that produced it, and the resumed turn's own servicing records its own
> disposition in its own turn's event.

> **Normative.** **No park id, decision id, query, origin, address or fragment of any of them
> enters that event.** ADR-0226 §9's no-copy rule and ADR-0004 §5's *"Tier 0/1 data must never
> be logged"* bind without qualification, and the park's content is the clearest Tier 1 in
> this decision. **The Tier 1 record of what was authorised stays `AuditTrail`'s and
> `InvocationLedger`'s** (ADR-0231 §6, §13), and this ADR adds no field to either.

> **Normative.** **`PROTOCOL_VERSION` moves 34 → 35**, once, for this whole decision, and
> `wire/envelope.py`'s log gains one entry naming this ADR and this reason. ADR-0124 §9's rule
> is met three times over: `Confirmation` gains a **required** member and is `extra="forbid"`,
> so a peer at 34 handed one fails to decode a confirmation it asked for (ADR-0178 §6's
> reasoning, unchanged); `TurnOutcome` gains two members a projection emits; and
> `AssistantEngine` gains a method, which §9 states bumps *"and that is the honest consequence
> rather than an oversight"*.

> **Normative.** **`PlanExport.schema_version` does not move.** No `ActionPlan` field, no
> `ReadAsk` field and no `ReadKind` member is added, removed or re-typed by this decision:
> the plan a park persists is the plan the planner already returned, stored as a value and
> not re-shaped. ADR-0039 §10's mechanism is not reached.

> **Normative.** **`SearchDisposition` does not move**, and neither does `SearchRefusal`,
> `SearchOutcome`, `QueryOutcome`, `QueryRefusal`, `ConfirmationEgress`, `EgressBinding`,
> `EgressSpan`, `PermissionDecision` or `ActionRequest`. The one enumeration this decision
> widens is `SearchNotServiced` (§12), and the three it mints are `ParkedReadDisposition`,
> `ReadAnswerOutcome` and `ReadCancellation` (§2, §9, §11).

> **Normative.** **No lane reads this section as authority for bumping on a defaulted
> addition alone.** What obliges the move is the conjunction ADR-0228 §6 states and the two
> further limbs above; ADR-0213 §11's no-bump ruling stands for the case it decided, and this
> ADR neither repairs nor inherits **#1956**.

### 18. What the implementing lanes owe, cut at ADR-0137 §2's seam

> **Normative.** **Lane 1 — the contract triad with its primary consumer, one PR.** The
> `core` surface (§2, §3, §4, §9, §11: `ParkedRead`, `ParkedReadDisposition`,
> `ReadAnswerOutcome`, `ReadCancellation`, `Confirmation.read`, `TurnOutcome.read_confirmation`
> and `read_answer`, `SearchNotServiced.ANSWER_AWAITED`, the `ParkedReads` Protocol,
> `AssistantEngine.cancel_read`, `Settings.parked_read_ttl`); the **shared conformance suite**
> for `ParkedReads`, stating §3's atomicity, its one-open-park rule, its settle-once answer,
> its content-clearing settlement, its open-and-terminal shapes (§2), its one-park-per-decision
> rule and `park_of_decision`'s answer across every disposition, and its
> `drop_for_conversation` semantics;
> the **canonical fake** in `ai_assistant.testing`; and
> `orchestration`'s park, enumeration, answer, dispatch, continuation and cancellation —
> the consumer whose demands shape the contract, which is what ADR-0137 §2 means by primary.
> `PROTOCOL_VERSION` 34 → 35 and the envelope log entry ride here, because a tree whose wire
> version disagrees with its own `core` types is the state that clause exists to prevent.

> **Normative.** **Lane 2 — the durable store and the wiring.** `SqliteParkedReads` in
> `permissions/`, satisfying the conformance suite, opened and closed alongside the other
> connection-owning stores in the composition root's ordered shutdown (ADR-0042 §2), wired as
> **one instance** into the servicing site and the engine; and the capture/lifecycle stage's
> drop of a deleted conversation's parks (§3). One subsystem plus `app/`, which is where
> concretes are wired.

> **Normative.** **Lane 3 — the command line.** ADR-0178 §7's floor for a read's
> confirmation, the exact query rendered (§13), the answer collected, the seven
> `ReadAnswerOutcome` statements, the ninth `SearchNotServiced` statement naming `assistant
> resume`, and the cancellation act. **Lane 4 — the browser**, the same obligations at its own
> surface. Both are `interfaces/` lanes and neither authors business logic (golden rule 3).

> **Normative.** **The order is 1, then 2, then 3 and 4**, which may run in parallel. **No
> lane lands ahead of this ADR being ratified and merged** (ADR-0015 §5, golden rule 5), and
> no lane splits the triad (ADR-0137 §3).

> **Normative.** **Four rulings of this ADR are deliberately not suite clauses**, and putting
> them there would be the error, exactly as ADR-0231 §17 says of its own four: that no model
> call precedes a dispatch (§16), that the value sent is the park's own `parameters` (§7),
> that no adapter reads a store (§13), and that the composition root wires one instance
> (Lane 2). A generic conformance suite cannot see a wiring or the absence of a call; each is
> a property of a call site and is asserted by a representative test where that site is (§19).

### 19. The representative-input tests this decision owes

> **Normative.** The implementing lanes owe the arms below, each bound to the
> pre-registered acceptance scenario on **#2222** it discharges. They are stated over
> **inputs and observable outcomes**, never over an implementation's internals, and each is
> driven at the seam it is about rather than through a turn that would have to violate a
> clause to reach it.
>
> - **Arm 1 (#2222 scenario 1) — the question appears and nothing is sent.** A servicing whose
>   policy rules `CONFIRM` writes one park, opens no channel, appends no claim, admits no
>   record, returns a turn whose `read_confirmation` carries the exact query and the
>   destination in both forms, and whose reply — composed from the fixed fragment for
>   `ANSWER_AWAITED` — says a lookup awaits an answer and does **not** say it produced
>   nothing.
> - **Arm 2 (scenario 2) — approve dispatches once.** A `resume` with `approved` `True` sends
>   exactly one request carrying the park's `parameters` byte for byte, settles the park
>   `APPROVED` **before** it records the one resolving `ALLOW`, and returns `read_answer`
>   `DISPATCHED` with a `TurnResult` whose fourth group holds the minted records and whose
>   reply is composed over them. A **second** `resume` on the same token sends nothing, records
>   nothing and returns `ALREADY_SETTLED`.
> - **Arm 3 (scenario 3) — deny.** `approved` `False` settles the park `DENIED` and then
>   records a `DENY`, opens no channel, and returns `DECLINED` with `turn` and `reply`
>   `None`; the parked turn's episode is unchanged.
> - **Arm 4 (scenario 4) — restart.** With a park written and the engine rebuilt over the same
>   durable state, `pending_confirmations` offers the **same** park with the same content and a
>   freshly minted token, and an approval after the restart dispatches exactly once.
> - **Arm 5 (scenario 5) — expiry.** A park past `expires_at` is not enumerated, is settled
>   `EXPIRED` on the first operation that reads it, has its content cleared, and answers a later
>   `resume` with `EXPIRED` having dispatched nothing.
> - **Arm 6 (scenario 6) — the changed operation, three arms.** A binding that no longer
>   derives equal refuses with `OPERATION_CHANGED` and no ruling recorded; a
>   `ActionPolicy.resolve` answering other than `ALLOW` refuses with `AUTHORITY_CHANGED` and
>   the answer **recorded**; a deleted conversation and a deployment at
>   `search_calls_per_conversation` `0` each refuse with `UNAVAILABLE_NOW`.
> - **Arm 7 (scenario 7) — cancellation, both states.** `cancel_read` on an `OPEN` park
>   returns `WITHDRAWN`, settles it `CANCELLED`, records **no** ruling and sends nothing; on a
>   dispatch in flight it returns `INTERRUPTED`, the claim is completed with
>   `interrupted_outcome` and an `UNKNOWN` cost (ADR-0241 §7), the channel is released, and
>   the `resume` call ends with no `TurnOutcome` and the park stays `APPROVED`. On a settled
>   park with nothing running it returns `NOTHING_TO_CANCEL`.
> - **Arm 8 (scenario 8) — the refusal arms.** No configuration answers a park; a `ParkedRead`
>   whose `parameters` do not hash to its decision's digest dispatches nothing; a second park
>   for one conversation is refused by the store and the servicing takes ADR-0242 §8's
>   undiscriminated member; a step's confirmation is unchanged in every member and every
>   assembly site; and `grantable_decisions` omits a decision a park names `OPEN`, `APPROVED`
>   or `DENIED` and lists it again once that park is `CANCELLED` or `EXPIRED` (§5).
> - **Arm 9 (the store's own suite) — atomicity.** Two concurrent `park` calls for one
>   conversation yield exactly one park; two concurrent `settle` calls for one park yield
>   exactly one `True`; a `settle` clears the three content fields in the same step that moves
>   the disposition; and `drop_for_conversation` removes open and terminal rows alike and
>   answers `0` the second time.
> - **Arm 10 — the crash between the gate and the ruling.** With the park settled `APPROVED`
>   and no resolution recorded, the next `resume` returns `ALREADY_SETTLED`, the next
>   `pending_confirmations` does not list the park, **nothing is dispatched**, and no ruling
>   appears in the trail. Driven by settling and stopping before `resolve`, at the seam rather
>   than through a real crash.
> - **Arm 11 — two concurrent answers, end to end.** Two `resume` calls on one token, both
>   past clause 4, produce **one** settlement, **one** recorded resolution and **one**
>   dispatch; the loser returns `ALREADY_SETTLED`, consults no policy, records nothing and
>   **raises nothing**. Held with the winner paused **after** its settlement and before its
>   recorded ruling, so the arm fails an implementation in which the loser's path can act on a
>   park the winner has taken. **A concurrent `pending_confirmations` during that pause
>   dispatches nothing, settles nothing and does not list the park.**
> - **Arm 12 — an approval racing a denial.** One `resume` with `approved` `True` and one
>   with `False` on one token produce **one** settlement, **one** recorded ruling, and a park
>   whose disposition and the trail's recorded answer say the **same** thing; the loser
>   returns `ALREADY_SETTLED` having consulted no policy, whichever of the two it is.
> - **Arm 13 — the establishing act racing an answer.** With a `resume` paused after its
>   settlement and before its recorded ruling, `grantable_decisions` omits that decision and
>   `establish_recipient_grant` on it raises `UngrantableActError` naming the eighth
>   condition; the paused `resume` then records its own ruling and dispatches. The arm fails
>   an implementation whose eighth condition is stated over an `OPEN` park alone.
> - **Arm 14 — the exclusion survives a restart.** With a park settled `DENIED`, no resolution
>   recorded, its deadline not passed and the engine rebuilt over the same durable state,
>   `park_of_decision` answers that terminal row, `grantable_decisions` omits its decision, and
>   `establish_recipient_grant` on it raises `UngrantableActError`. The arm fails an
>   implementation holding the exclusion in memory.

> **Normative.** **Arm 2's second half, Arm 9 and Arm 11 are the three this decision would be worthless
> without**, and they are named here so that no lane treats them as optional: everything else
> in this ADR is a way of arranging for exactly one call to leave the machine for one answer.

### 20. Deferred, by name, each with what fires it

> **Normative.** **Parallel and concurrent reads.** More than one open park per conversation,
> scheduling between them, dependency and snapshot semantics, and more than one outstanding
> ask per kind are **deferred**, not declined. **What fires them:** the M32/M33 design that the
> owner's 2026-09-10 handoff document's second half opens. Until then §14's clauses bind and
> ADR-0231 §11's servicing order is unchanged.

> **Normative.** **Parking any read kind but `WEB_SEARCH`.** A local file fetch, a citation
> hop, a sighted query and a structured read are serviced exactly as they are today and none
> of them parks. **What fires it:** an egress-bearing read kind whose ruling can be a `CONFIRM`
> — none of the four is one today, since each reads what is already on the device or in the
> store. `Confirmation.read` is typed `ReadKind | None` so that such an ADR widens no type
> (§4).

> **Normative.** **Cancelling a dispatch running in another process.** §11's act reaches the
> process that received it. **What fires it:** #2173's L7 obligation, or the first deployment
> that runs two engines over one data directory — which ADR-0043's posture does not admit
> today.

> **Normative.** **A durable record of what was asked.** ADR-0231 §19 already defers the
> content-bearing durable record of a query and §13 states why the trail cannot hold one;
> the park is **not** that record and must not be read as one, because its content is cleared
> the moment the question is answered (§3). **What fires it:** ADR-0231 §19's own trigger,
> unchanged by this decision.

> **Normative.** **A filtered listing of decisions an act may ride.** ADR-0242 §14's deferral
> stands and this ADR adds nothing to it; §5's eighth condition narrows the population
> `grantable_decisions` already computes and creates no new listing.

### 21. Scope, and what this records against earlier ADRs

**Four ADRs get a record and each is header-only.** ADR-0231, ADR-0235, ADR-0242 and ADR-0052
each gain a `- Status:` line naming this ADR with the scope in the parenthesis, and a dated
note in the header saying which clause moved and why — ADR-0082 §1's form, and the reciprocal
half of the header bullets above. **No ratified body text is rewritten**, which is ADR-0001's
append-only rule and the reason the note carries the argument rather than an edit to the
clause.

**Five ADRs are reused and not amended, and the distinction is checked clause by clause.**
**ADR-0044** is used exactly as written: its resolution invariant, its one-answer rule and its
`pending_confirmation` query are unchanged, and a read park sits where §2(b)'s per-*binding*
rule does not fire — both ids are unset — so ADR-0036 §2's per-*confirmation* index is the
trail-side gate and §3's `settle` is the park-side one. **ADR-0052** is amended in one sentence
(the header records it) and reused in everything else. **ADR-0178** is reused entire: §1's
no-default reasoning shapes §4's field, §4's absence-is-the-discriminator shape is copied,
§5's assembly rule is what populates `egress` on a read's confirmation, and §7's floor binds
with two clauses added beside it (§13) rather than any clause of it relaxed — which is
ADR-0070 §1's amend-not-supersede side, exactly as ADR-0233 §8's floor sat beside §7 before.
**ADR-0148** is used in the direction it was written: §3's route (a) opens because this ADR
supplies the asker, §6's digest binding is what §2's parameter check leans on, and §8's fourth
clause is what §13's floor discharges. **ADR-0241** is untouched: §7's accounting is cited and
not moved, and no clause here reaches a deadline, a `WebSearcher` argument or a completion row.

**And three are cited but carry no record, because nothing a reader holding them would do is
now wrong.** ADR-0193 §4 still covers no request whose binding carries
`planned_with_external_content`, and this ADR does not reach an `ALLOW` through a grant.
ADR-0226 §5 still designs the servicing to be invisible, and §1 obeys it by parking the read
rather than the turn. ADR-0238 §8's budget is spent where it was always spent, and §6's
clause 2 reads a draw rather than drawing one.

### 22. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**ADR-0070 §1's test is whether a reader holding only the earlier ADR would do the wrong
thing, and it comes out on the supersession side four times.** A lane holding only ADR-0231
would refuse to park a read, would leave a recorded `CONFIRM` resolving in no turn, would
refuse a store write on account of a search, and would name the standing grant as the one
route to an `ALLOW` — four clauses, each named in the header with its scope. A lane holding
only ADR-0235 would offer the establishing act on a parked decision and would keep the message
of a refused search out of every place but one listing. A lane holding only ADR-0242 would
build a suite asserting `SearchNotServiced` has eight members and would map a parked
`RULING_CONFIRM` to a member whose own clause it would then falsify. A lane holding only
ADR-0052 would return `TurnOutcome(turn=None, step=<resolution>)` from a resume that in fact
composed an answer over records. **Each is a supersession and not an amendment**, because in
each case the earlier sentence becomes **false** rather than incomplete.

**Where it is an amendment instead, that is stated rather than upgraded.** ADR-0178 §7 gains
two clauses beside it (§13) and loses none, so §7's every sentence stays true of every
surface — ADR-0070 §1's amendment side, and ADR-0082 §1's stacked-addition form, which is how
ADR-0233 §8 already sat beside the same section. `Settings` gains one field (§3) as ADR-0241
§3's `search_call_deadline` did, a stacked addition under ADR-0082 §1 that moves no earlier
ADR's field count.

**ADR-0082 §1's record is made in this same change**, on all four headers, with the scope
stated per clause rather than per ADR — because three of the four are ADRs whose earlier
partial supersessions already name clauses, and a record naming only the document would leave
a reader unable to tell which sentence moved.

### 23. Marking, review and ratification

**Every ruling above is marked** (ADR-0089 §1): a block quote at column 0, one obligation per
clause, a passage stating two separable obligations split into two. Unmarked text argues,
measures, classifies or exhibits, and supplies no obligation (§3) — including the tables in
§12 and §19, which are inside marked clauses and are read as part of them.

**The required review set is adversarial *and* architecture**, because this ADR decides
`core/protocols.py` and `core/types.py` surface (`CONTRIBUTING.md` → "Stop when the required
reviews are green"; ADR-0015 §1). It lands **no** implementation — no `src/`, no `tests/` —
and is ratified and merged as its own PR before anything implements against it (ADR-0015 §5,
golden rule 5). `just adr-ratify` makes the one-line `Proposed` → `Accepted` flip (ADR-0165).

## Consequences

**A search the user's own context makes `CONFIRM` can now happen at all.** That is the point:
#2221's dead end closes without touching #2212's floor, and the owner's store stops being the
configuration on which the mechanism is inert.

**The corpus gains a second durable store holding Tier 1 content, and it is bounded in time by
construction.** `parked_read_ttl` admits no disable sentinel, `settle` clears content in the
same step that closes the question, and the conversation's own deletion sequence drops what is
left. What is genuinely new is a window — between the question and its answer — in which a
composed query is durable on disk. This ADR states that plainly rather than minimising it,
because it is the price of showing the user what would leave the device before it leaves.

**A conversation can hold one open park and no more.** A user who neither answers nor cancels
blocks that conversation's next search until the deadline passes. The acts that free it are all
cheap — answer, deny, cancel — and the deadline is the deployment's; but a deployment setting a
long `parked_read_ttl` should expect a conversation to go a long time without a second search
offer, and §20's deferral is where that is revisited.

**Two answers now exist for one recorded `CONFIRM` and they do different things.** Answering
the park dispatches the read; establishing a grant makes the recipients standing and dispatches
nothing. §5 keeps them from being offered on one row at one moment, and ADR-0235 §2's
`remember_recipients_until` is how a user does both in one act.

**A resume can now be a turn.** That is the largest shape change: three of the corpus's resume
paths return a step, a routed operation or a restatement, and a fourth now returns a composed
answer over records. The validator that refuses prose on a turn-less outcome is what forced it
and is what keeps it honest.

**What becomes harder.** Every surface rendering confirmations now has a branch, and a surface
that ignores it renders a read's question as though it were an action's — which is why §13
states the floor over "a surface" rather than over the two that exist. And the audit still
cannot say what was asked (ADR-0231 §13): a park is not an archive, and an auditor reading the
trail after the answer sees an authorised call whose query is gone, exactly as they do today.

## Alternatives considered

**Park the turn.** ADR-0231 §9's own second alternative, and it is refused for the reason that
section gave: it would *"let a marginal improvement in reach take a reply down"*. §1 parks the
read and lets the turn answer, which costs the user one extra exchange and costs no reply.

**Put the query on the audit trail.** The smallest diff, and the wrong store. ADR-0148 §6 fixes
that parameters are *"bound by digest, never stored"*, ADR-0150 §10 that spans *"hold no
content"*, and ADR-0097 §4 that the trail's premise is that its records are not fabricated.
A store that holds the query is a new obligation and belongs in a new place.

**Put the park on the conversation record.** ADR-0238 §8's move for a counter, and it fails
here on that contract's own stated invariant — `ConversationStore` *"holds no content"* — and
on tiering: a park holds three content fields and the record holds none. The reason ADR-0238
gave for moving the counter was that a counter has no way of being rediscovered after a crash;
a park has a deadline and an enumeration, which is the disanalogy §3 states.

**Key the park on `(execution_id, step_id)` and reuse `pending_confirmation`.** Unavailable:
ADR-0231 §6 rules both ids `None` on a `WEB_SEARCH` decision and forbids synthesising a step
*"in order to satisfy a clause written about steps"*. The decision id is the key a search
already has, and ADR-0235 §3 already reads that population.

**Return the minted records to the surface instead of composing.** Refused in §8: the records
are turn-scoped and resolve in no store, the reply is the only place an answer is stated
(ADR-0170 §3), and composing one in `interfaces/` is business logic in an adapter.

**Re-plan at resume rather than persisting the plan.** Refused in §2: it would put a model call
between the user's *yes* and the read, could produce a second question behind an answered one,
and would report a plan the parked turn never had.

**Reuse `AUTHORISATION_AWAITED` rather than minting a ninth member.** Refused in §12: that
member *"asserts exactly two things, both established"*, the second being that the establishing
act may ride the decision — which a parked decision does not (§5). Reusing it would make a
pinned assertion false, which is a worse outcome than a ninth member in a vocabulary whose own
clause provides for one.

**One `withdraw` operation and one `interrupt` operation.** Refused in §11: it would ask the
caller to know the park's state before acting, which is a race by construction.
