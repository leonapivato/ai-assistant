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
  are untouched, and §13's audit gains what §15 below states and nothing else.
- **Partially supersedes** [ADR-0235](0235-the-establishing-act-rides-an-answer-to-a-confirmation-live-or-recorded-and-a-refused-search-reaches-the-user-as-history-and-not-as-work.md)
  — **§3's seven-condition closure in that count alone, and §8's first clause in its
  nowhere-else limb. Nothing else in that ADR.** §3 makes the establishing act available
  *"on a decision meeting **all seven** of the following"*; §5 below adds an **eighth** — the
  decision is not one a parked read holds — because a decision whose question a park is
  holding is answered through `resume` and not through a second act, which is §3's own third
  clause read at a park that carries no `step_id` (*"no lane reaches this operation from a
  park by clearing either field"*). **The seven conditions themselves bind verbatim**, their
  order is unchanged, the eighth is tested after them, and `UngrantableActError` names it as
  it names the others. §8's first clause closes *"The message that a search was refused is
  `grantable_decisions`' listing and the act offered beside it … and is **nowhere else**"*;
  ADR-0242 §7 already put a statement in the reply, and §4 and §9 below put the **question
  itself** on the surface as a confirmation a user may answer. **§8's second and third
  clauses bind entire**: this is not a notification and no lane mints one, and neither the
  listing, the reply nor the rendered question states that the turn would have answered
  differently, that a reply was incomplete, that a search would have succeeded, or that
  anything is owed. §§1–2, §4–§7, §9–§14 are untouched; §9's per-channel posture is extended
  for this kind by §9 below rather than moved.
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
  empty context and memories — which would misrepresent what the turn saw"*, and §3 below
  persists the two members that would otherwise be fabricated while §8 assembles the other
  two afresh and says which is which. **§1, §2 and §4 bind entire**, and so does the rest of
  §3 — a recovered park still re-mints its continuation from durable state, the handle stays
  an opaque re-derivable token, and `_Parked.turn` stays optional.
- **Requires new `core` contract surface and lands none of it** (§2, §3, §5, §10, §16).
  Flagged under golden rule 5: it is ratified and merged as its own PR before anything
  implements against it (ADR-0015 §5).
- **Its required review set is adversarial *and* architecture**, the set `CONTRIBUTING.md`
  requires of the ADR deciding `core/protocols.py` and `core/types.py` surface.
- **It moves `PROTOCOL_VERSION` from 34 to 35**, stated up front rather than found by the
  implementing lane (§15), by ADR-0124 §9's rule in three of its limbs at once.
- **It fixes the contract half of [#2221](https://github.com/leonapivato/ai-assistant/issues/2221)**
  and takes no position on [#2212](https://github.com/leonapivato/ai-assistant/issues/2212),
  whose posture is postponed to a security pass and which this ADR does not move. Batch
  [#2222](https://github.com/leonapivato/ai-assistant/issues/2222) carries the
  pre-registered acceptance scenarios §17 binds to by number.

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
  M32/M33's. §18 defers them by name with what fires them. ADR-0231 §11's servicing order is
  untouched.
- **The general cancellation obligation.** #2173's L7 covers user correction and
  cancellation during execution; §10 below decides the boundary for this operation kind
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
> §11 below decides what the user is told.

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
> establishing act may ride it where ADR-0235 §3's conditions hold, and §11's mapping gives
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

> **Normative.** `core/types.py` gains **`ParkedReadDisposition`**, a `StrEnum` valued by
> lower-cased member name and closed at exactly **five** members: `OPEN`, the question stands
> and may be answered; `APPROVED`, the answer was yes and the read was dispatched;
> `DENIED`, the answer was no; `CANCELLED`, the question was withdrawn without an answer
> (§10); and `EXPIRED`, the deadline passed with no answer. **`OPEN` is the only
> non-terminal member**, the other four are terminal, and no transition leaves a terminal
> member. The vocabulary is added to and never renamed.

> **Normative.** **A `ParkedRead` carries no minted record, no result, no snippet, no title,
> no address, no origin beyond the one its `parameters` already state, no credential, no
> `SecretName`, no connection reference, no `BoundAccount` and no binding.** The binding, the
> account identity and the canonical destination set are the **recorded decision's**, read
> through `decision_id` at the moment a confirmation is assembled, exactly as ADR-0178 §5
> already rules for every other confirmation: *"the engine populates `egress` from the
> **recorded** `PermissionDecision` the confirmation is about"*. No field is added to
> `ParkedRead` through which any of them could travel, and no lane copies one into it.

> **Normative.** **`parameters` are the ruling's own and are checked against it, not
> trusted from it.** They hash to the recorded decision's `parameters_digest`, and §7's
> dispatch re-evaluates `PermissionDecision.authorises` over the request rebuilt from them.
> A park whose parameters do not authorise under its own decision is refused at resume with
> that reason and dispatches nothing — so a park store that was edited, restored from a
> stale copy or written by a defective implementation cannot put a query the policy never
> ruled on onto the wire.

> **Normative.** **The `goal` and the `plan` are persisted because §8 composes over them
> and would otherwise fabricate them.** They are read at resume, are never rendered to the
> user as part of the question (§4), are never handed to the query composer, and are
> **never** a route by which a model composes a new query — §14's third refusal binds on
> them by name.

**Three fields carry Tier 1 content, and that is stated here rather than discovered.**
`parameters` holds the composed query, `goal` holds the objective minted from the utterance,
and `plan` holds what the planner decided. ADR-0004 §2's residency clause governs all three:
an implementation persists **locally only**, and §3's retention rule is what keeps the
exposure bounded in time rather than in principle. This is the same trade `ConversationStore`
and the `MemoryStore` already make for conversation history, and it is why the park is a
store and not a log: ADR-0004 §5's *"Tier 0/1 data must never be logged"* is untouched, and
ADR-0231 §13's audit event gains none of it (§15).

**The plan is persisted rather than re-derived, and re-deriving it would be the wrong kind
of cheap.** Re-planning at resume would put a model call between the user's *yes* and the
read, would let the planner ask for a **different** read — a second question behind an
answered one — and would produce a `TurnResult` whose `plan` is not the plan the parked turn
ran. ADR-0014 §2's frozen plan is the value the turn actually had; persisting it is how the
continuation stays a continuation.

### 3. The store: `ParkedReads`, one open park per conversation, and content that lives exactly as long as the question

> **Normative.** `core/protocols.py` gains **`ParkedReads`**, a durable store with exactly
> these five members and no more:
>
> - `async def park(self, record: ParkedRead, /) -> bool` — writes an `OPEN` park, or
>   answers `False` where this conversation already holds one. The read of the existing park
>   and the write are **one indivisible step**.
> - `async def get(self, park_id: str, /) -> ParkedRead | None` — the park under that id, or
>   `None`.
> - `async def open_park(self, conversation_id: str, /) -> ParkedRead | None` — this
>   conversation's open park, or `None`.
> - `async def outstanding(self) -> tuple[ParkedRead, ...]` — every `OPEN` park, in
>   `parked_at` order, for §5's enumeration.
> - `async def settle(self, park_id: str, /, *, disposition: ParkedReadDisposition, at:
>   UtcInstant) -> bool` — moves an `OPEN` park to a terminal member and **clears
>   `parameters`, `goal` and `plan` in the same step**, answering `True` to the caller that
>   moved it and `False` to every other. The read, the comparison and the write are one
>   indivisible step, and `settle` on an already-terminal park answers `False` and changes
>   nothing.

> **Normative.** **A conversation holds at most one `OPEN` park.** `park` enforces it, and
> the enforcement is the store's rather than a caller's for `admit_search`'s own reason
> (ADR-0238 §8): two turns of one conversation, two servicings of one turn, and two engines
> over one data directory can none of them be admitted against the same conversation's park.
> A servicing whose `park` answered `False` has written no park, and §1's third clause
> governs what it then is.

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

> **Normative.** **The conversation's deletion sequence drops that conversation's parks**,
> and it is the capture/lifecycle stage in `orchestration` that does it — *"the one layer
> that legitimately holds both handles by injection"* (ADR-0074 §9). A park stranded by a
> crash in that sequence is **not** an unrecoverable orphan: it carries its own `expires_at`,
> `outstanding` enumerates it, and §9's expiry settles it and clears its content without any
> reference to the conversation record. **No lane adds a cross-store reconciliation walk, a
> tombstone, a stamp of its own or a second lifecycle.**

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
