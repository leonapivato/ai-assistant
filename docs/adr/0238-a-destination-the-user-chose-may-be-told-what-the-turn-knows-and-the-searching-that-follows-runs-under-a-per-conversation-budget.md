# 238. A destination the user chose may be told what the turn knows, and the searching that follows runs under a per-conversation budget

- Status: Proposed
- Date: 2026-09-05
- **Partially supersedes** [ADR-0231](0231-the-planner-asks-for-a-search-the-turns-own-words-compose-it-and-the-results-come-back-as-records.md)
  — **§3's utterance-only clause, §4's first and second clauses, and §12's second
  and third clauses.** Those five, and nothing else in that ADR.
- **Partially supersedes** [ADR-0233](0233-the-approver-is-shown-the-bytes-that-would-leave-and-that-is-the-whole-of-what-makes-a-model-composed-span-approvable.md)
  — **§9's first clause, in its exclusivity alone (the word "only"), and §9's second
  clause, for the one class §1 below names.** Those two scopes, and nothing else.
- **Partially supersedes** [ADR-0155](0155-residency-governs-the-assistants-own-store-and-that-store-is-never-externalised.md)
  — **§3's third clause, a second time: the prohibition sentence acquires a second
  exception beside the one ADR-0233 §9 states.** That sentence, and nothing else.
- **Partially supersedes** [ADR-0181](0181-an-egress-call-records-whether-it-was-planned-over-external-content.md)
  — **§5's second clause, the lineage floor, for a closed-loop request as §5 below
  defines one.** That clause in that scope, and nothing else.
- **Partially supersedes** [ADR-0193](0193-a-standing-recipient-grant-is-a-user-act-on-a-canonical-destination-set-and-never-covers-a-call-planned-over-external-content.md)
  — **§3's first clause in its fifth comparison, §4's first clause, and §6's
  eighth-check clause in its seventh limb alone, each for a closed-loop request.**
  Those three, and nothing else — §5's rule that a grant reaches the recipient and never
  the payload is left standing deliberately, and §1 below is built so that it can be.

## Context

### Where this comes from

The owner ruled milestones 31–33 onto `track:planning`'s live record (#1908) on
2026-09-05. Milestone 31 is stated there, and its words are this ADR's brief:

> **31 — contextual search without babysitting.** The assistant uses relevant
> conversation context and personal knowledge to formulate searches, refines them
> after seeing results, and continues within an enforced budget. Removes two of 29's
> limits: the composer sees only the latest utterance (ADR-0231 §3), and a
> conversation that has read a result declines every later search (ADR-0231 §12).
> **This is a contract reversal, not a relaxation.**

and its exit:

> "find more about that, taking my preferences into account" resolves the reference,
> uses relevant context, performs useful follow-up searches and answers **without
> repeated permission requests**. Negative arm: an injected result cannot raise the
> budget and cannot carry an excluded record into a query.

The design umbrella is #2096, corrected by its 2026-09-06 comment recording the
owner's roadmap ruling. Item 2 of that comment is what this ADR is named for: the
note records one fact per **source** — who can write here — and the roadmap needs
the mirror for **destinations**, so that milestone 31 (the provider) and milestone
32 (a site the provider returns) are two values of one rule rather than two
boundaries. Item 3 is the sentence this ADR is obliged to write rather than dodge:

> ADR-0231 §12's "no byte of a search result can reach a later search request" is the
> structural answer to #1844's channel. Refining a query over results dissolves it.
> The replacement is trust in the provider plus budget and audit, not a new structural
> claim; the ADR must say so rather than claim the property survives.

§4 below is that sentence, and it is the paragraph a reviewer should read first.

### The exit, and what this ADR can and cannot demonstrate

**This ADR decides a contract and lands no code**, under golden rule 5 and ADR-0015
§5. Its implementing lane is separate and is briefed from the merged text.

**And on `origin/main` after that lane, no destination carries `USER_CHOSEN` and the
mechanism is legible and inert** — exactly the posture ADR-0231 §9 recorded for the
search itself, and for the same reason: the fact §1 records is set by a **user act**,
§14 defers the surface offering that act to the surface ADRs as ADR-0193 §13 requires,
and until one exists there is nothing to perform the act with. **So every supersession
this ADR makes has no live subject on the tree it merges into.** With no `USER_CHOSEN`
destination, no request is closed-loop (§5), so ADR-0181 §5's floor and ADR-0193 §3
and §4 bind on every request exactly as they do today, ADR-0155 §3's third clause has
only ADR-0233 §9's exception, and the composer is supplied the turn's utterance and
nothing else. That is stated here so nobody reads inertness as this ADR being
theoretical, and so nobody reads the supersessions as taking effect on merge.

### The tree, read rather than assumed, at `origin/main` `b732dc7e`

- `QueryComposer` in `core/protocols.py` declares
  `async def compose(self, utterance: NonBlankEncodableText, /) -> QueryOutcome`, one
  positional-only parameter, one member. Its docstring carries §3's safety claim in
  full.
- `EgressBinding` in `core/types.py` already carries two facts of the class §5 adds a
  third to — `planned_with_external_content` (ADR-0181 §3) and `coverage` (ADR-0233 §4) —
  each written by the component that composed the arguments, each mirrored on
  `CarriedProvenance`, and each compared through `EgressBinder.rebind` and
  `PermissionDecision.authorises`.
- `ConversationExport` carries `schema_version: Literal[2]`, `conversations` and `turns`,
  so a field on `Conversation` or on `ConversationTurn` would change a portable document's
  shape and move that literal (ADR-0212 §8, ADR-0014 §5). §8 puts this decision's counters
  in their own store instead, and neither type is touched.
- `MemoryRecord` is a discriminated union over the four record kinds, every one of
  which carries `placement` on `MemoryBase` (ADR-0217 §1).
- **Nothing in `planning/` or `orchestration/` imports `secret_store`**, and
  `tools/web_search.py` opens by stating "**Nothing here reads a secret, holds a
  ``Secrets`` face or constructs a transport**". The credential is the seam's, at the
  position ADR-0148 §7 puts it. §12's credential clause is therefore a statement about
  the tree and not an aspiration.
- `PROTOCOL_VERSION` stands at **31** in `wire/envelope.py`, and
  `AssistantEngine.recent_decisions` and `export_decisions` return
  `tuple[PermissionDecision, ...]` across the wire (`wire/client.py`). A
  `PermissionDecision` carries an `EgressBinding`, so §5's field **does** cross and §13
  moves the number.
- `web_search_cost_per_call` and `web_search_cost_currency` exist (ADR-0236 §1), and
  `WebSearchEgress` reports no figure on a completed search, so `consumed_call` writes
  `unknown_cost()` — the fact #2126 records and §10 decides.

### The four locks in front of the exit, and the count that is wrong in the framing

The exit's operative words are **"without repeated permission requests"**. Reaching
them means a follow-up search on a turn whose supply already holds a result rules
`ALLOW` without asking. Four ratified clauses stand in the way and they are
independent — moving fewer than all four leaves the search at `CONFIRM`:

1. **ADR-0231 §3** gives the composer one argument, so "find more about **that**"
   composes to nothing whatever else is relaxed.
2. **ADR-0231 §12's third clause** routes the second search to the policy, which
3. **ADR-0181 §5's second clause** and **ADR-0193 §4's first clause** each refuse
   independently. ADR-0231 §12 names both in one breath — "ADR-0193 §4 admits no grant
   on such a request **and** ADR-0181 §5's floor admits no `ALLOW` but a decision of
   the user about that request" — and ADR-0193 §4's own last limb is general rather
   than grant-shaped: "route (a) … **is the only route to an `ALLOW`**". A different
   standing carrier does not escape it.
4. **ADR-0155 §3's third clause**, which a widened composer engages the moment a store
   value is supplied to it, with only ADR-0233 §9's four conditions as an exception —
   and those four require a per-call `CONFIRM` answered by the user, which is the
   repeated permission request the exit forbids.

**A fifth clause is engaged and is not in the framing at all**: ADR-0193 §3's first
clause makes "the request's binding does not carry `planned_with_external_content`"
the fifth of five comparisons a grant must satisfy, so moving §4 alone would leave
`RecipientGrants.covering`'s own conjunction refusing.

### Claims in the framing that do not survive contact with the tree

- **"ADR-0233 §9's second clause" is not the whole of what moves there.** §9's *first*
  clause reads "may carry covered content **only** where all four hold". That "only"
  is an exclusivity claim about the whole class, so a second exception breaches it as
  surely as the second clause's standing-authorisation bar does. §7 moves both, in
  scope.
- **ADR-0231 §4 moves as well as §3 and §12.** Its second clause says "**the ADR that
  fork commissions is the only instrument that may move**" ADR-0155 §3's third clause.
  ADR-0233 is that ADR and has landed, so the sentence is spent — but a reader holding
  only ADR-0231 would act on it, which is ADR-0070 §1's test coming out on the
  supersession side. Its first clause — "No component supplies a `QueryComposer` with
  covered content in ADR-0155 §3's sense" — is the clause §2 reverses in terms.
- **ADR-0223 §6 does not move, and the reason is a design constraint rather than a
  convenience.** Its clause reads that ADR-0181 §5's floor "applies to a request whose
  binding carries `planned_with_external_content` because a **stamped episode** was in
  the turn's supply, **exactly as it applies for any other reason**. It is not
  narrowed, exempted or conditioned **for this cause**, and no lane adds an
  **episode-shaped** carve-out to it." §5's condition is stated over the request's kind
  and the destination's recorded trust and is **blind to how the taint arrived**, so
  the episode cause is treated exactly as every other cause and the clause is honoured
  rather than moved. ADR-0223 §6 is therefore the reason §5 must be cause-blind, and a
  carve-out written the obvious way — "except where the external content is a search
  result" — would have breached it.
- **ADR-0223 §6 and ADR-0233 §9 disagree about a clause number.** ADR-0223 §6 calls the
  lineage floor "ADR-0181 §5's **third** clause"; ADR-0233 §9 calls it "ADR-0181 §5's
  **second** clause", and clause order makes the second correct. This ADR cites the
  clause by its words and not by either number, and §16 files the discrepancy rather
  than settling it.

### What this ADR is not allowed to settle

- **Milestone 32's fetch.** §1's fact is shaped so that a later ADR can read it for a
  destination nobody chose, and this ADR decides nothing about fetching, link
  following, address grammars or non-public addresses. `UNCHOSEN` is defined here; what
  may be done to an `UNCHOSEN` destination is decided there.
- **A second provider, or a provider named in a turn.** ADR-0231 §19 defers both and
  this ADR fires neither.
- **The surfaces that offer §1's establishing act.** ADR-0193 §13 assigns surface
  layout to ADR-0177, ADR-0178 and ADR-0186, and §14 inherits that assignment whole.
- **A monetary ceiling.** §9 declines it in terms and leaves ADR-0194 §1 and §8 exactly
  where they stand.
- **A user-pick surface for search results**, which #2096's 2026-09-04 correction
  records as owned by no lane. Nothing here decides one.

## Decision

### 1. Destination trust: one recorded fact per destination, set by the user, and absence reads `UNCHOSEN`

> **Normative.** `core/types.py` gains **`DestinationTrust`**, a `StrEnum` closed at
> exactly **two** members: `USER_CHOSEN`, valued `user_chosen`, denoting a destination
> the user picked by name and told this system it may be told about them; and
> `UNCHOSEN`, valued `unchosen`, denoting every other destination. The vocabulary is
> **added to and never renamed**, and no implementation or later ADR adds a third
> member without the ADR that decides it — `DestinationProtocol`'s discipline
> (ADR-0150), applied to the fact rather than to the protocol.

> **Normative.** The trust of a destination is `USER_CHOSEN` **only** where a live
> record of a user act says so, and `UNCHOSEN` in every other case, including where no
> record exists, where a record was revoked, and where a record cannot be read. The
> absent case is the fail-closed direction and is stated as ADR-0146 §2 states its own
> — "A span for which no origin was recorded is **system-selected**" — for the same
> reason: the permissive default is what makes an unimplemented path work and is
> therefore precisely the state in which the rule would be false.

> **Normative.** The fact is **set by a recorded act of the user and by nothing else**.
> No configuration sets it, no connected account sets it, no operator setting sets it,
> no tool declaration sets it, no `RecipientGrant` sets it, and **no model output ever
> sets it, raises it, or is consulted about it**. A model may not propose a
> destination's trust, may not be shown a destination in order to judge it, and no
> component infers the fact by inspecting a destination, a host, a response, or any
> content whatever. This is ADR-0217 §3's precedence read on the destination axis — the
> owner's act is final and a model may only narrow — with the narrowing arm not granted
> here at all.

> **Normative.** The fact is **prospective and revocable**, on ADR-0193 §9's shape: a
> revocation takes effect for every later request and rewrites no recorded decision, and
> a destination whose record is revoked reads `UNCHOSEN` from that moment.

> **Normative.** `core/types.py` gains **`DestinationTrustRecord`**, a frozen model
> refusing unknown fields, with exactly five fields: `id: Identifier`, **minted by the
> caller that constructs the record**, as `RecipientGrant`'s is (ADR-0193 §1), so that the
> record is a complete value before it reaches any store and the store's refusal of a
> duplicate is a comparison rather than an allocation; `destinations:
> tuple[CanonicalDestination, ...]`, non-empty, the canonical destination set this record
> is over; `trust: DestinationTrust`; `established_at: UtcInstant`, the instant of the
> user's act; and `revoked_at: UtcInstant | None`, defaulting to `None`. It carries **no
> tool, no account, no payload, no description and no content**: it is a fact about a
> destination set and nothing else, which is what makes it readable for a destination no
> grant covers.

> **Normative.** A `DestinationTrustRecord` whose `trust` is `UNCHOSEN` is **refused at
> construction**. `UNCHOSEN` is what absence means (above), so a record asserting it
> would be a second spelling of nothing, and two spellings of one state is the shape
> ADR-0217 §1's refusal table exists to prevent.

> **Normative.** `core/protocols.py` gains **one** `@runtime_checkable` Protocol,
> **`DestinationTrustStore`**, with exactly **four** members and no more: **`record`**,
> taking a `DestinationTrustRecord` and appending it, refusing a duplicate `id`, an empty
> destination set and a record duplicating a live record's destination set, by an
> `InvalidDestinationTrustError` beside `InvalidRecipientGrantError`; **`trust_of`**,
> taking a sequence of `CanonicalDestination` and answering a `DestinationTrust`;
> **`revoke`**, taking a record `id` and the instant of the user's act, prospective and
> idempotent, refusing an unknown id by the same error; and **`live`**, answering the
> records that are not revoked, ordered, for the surface that lets a user see and revoke
> what they granted; and **`export`**, answering **every** stored record, revoked ones
> included, in a stable order. **No member is added, no argument widened and no return
> changed by any later lane** without the ADR that decides it.

> **Normative.** **`export` exists because the data right does.** ADR-0004 §6 gives the
> owner their data, and ADR-0193 §1 already applies that to authorisation records, live
> and revoked alike: a revoked trust record is the evidence that the user once permitted a
> destination and then withdrew it, which is exactly what an audit of one's own decisions
> is for. `live` is the operating read and `export` is the right; neither stands in for the
> other, and the user-facing layout of an export stays the surface lanes' (§14).

> **Normative.** **`trust_of` answers `USER_CHOSEN` only where every member of the
> sequence it was given is a member of some one live record's `destinations`**, compared
> as `CanonicalDestination` compares — every field, never across protocols — and
> `UNCHOSEN` otherwise, including for an empty sequence. **Coverage is a comparison of
> recorded values and is never an inference**: no implementation folds case, matches a
> domain, treats an account member as covering a recipient member or the reverse, relates
> the two sets by anything but membership, or re-canonicalises either side. That is
> ADR-0193 §3's second clause, restated over this store because the hazard is identical
> and the store is a different one.

> **Normative.** The store is **local and durable and is never written to a remote
> service** (ADR-0004 §2), it holds a Tier 1 fact, and it ships as a **triad** — Protocol,
> shared conformance suite, canonical fake — under `CONTRIBUTING.md` → "Adding a
> Protocol".

> **Normative.** The store is **not** a field on `RecipientGrant`. Two reasons, and each is sufficient. **A destination nobody chose
> has no grant to carry a field** — milestone 32's subject is a site the provider
> returned, for which no `RecipientGrant` exists or ever will, so a grant-carried field
> could not express the value that milestone reads. And **ADR-0193 §5 is correct and is
> left standing**: "A grant states nothing about the payload and authorises no content",
> so deriving a payload permission from a recipient grant would be the shape ADR-0097 §7
> refuses and ADR-0155 §3 quotes against itself — "the floor satisfied by a consent the
> user gave about something else entirely".

> **Normative.** **The two acts are separate and neither implies the other.** A
> `RecipientGrant` authorises *whether this system may talk to this party*; the record
> above authorises *what class of payload this system may compose for it*. A grant
> established before this ADR, or established after it without the second act, leaves
> its destination reading `UNCHOSEN`, and no component reads the existence, breadth,
> age or liveness of a grant as evidence of trust. A deployment reaching `USER_CHOSEN`
> has a user who answered the second question knowing it was a second question.

**Two values and not three, unlike the source side.** #2096's source writer-set is
three-valued because policy there needs two boundaries — a value may fill an unbounded
blank alone, only inside a confirmed flow, or only under a per-call confirmation. The
destination side needs one boundary, because the question is binary at every seam this
corpus has: either the user picked this party or nobody did. A third value would be a
guess about a mechanism no ADR has yet designed, and the enumeration is extended by ADR
precisely so that milestone 32 or 33 may add one when it has a policy that reads it.

**"Never inferred" and "absence reads `UNCHOSEN`" are not in tension.** Reading a total
function over a partial store is not inference in ADR-0098 §1's sense; inference is
deciding a fact by inspecting content. Nothing here inspects anything: a record either
exists and is live, or it does not.

### 2. The composer keeps one positional argument, and a type decides what may be in it

> **Normative.** `QueryComposer.compose`'s signature becomes
> `async def compose(self, supply: SearchSupply, /) -> QueryOutcome`. The parameter
> stays **positional-only** and stays **the only one**; `QueryComposer` stays a
> single-member Protocol; and **every other clause of ADR-0231 §3 binds entire and
> unchanged** — no keyword, no second member, and no constructor dependency on a
> `MemoryStore`, a `ContextProvider`, a `ConversationStore`, a `TranscriptArchive` or
> any other store seam. A composer holds a `ModelProvider` and nothing else that reads,
> lives in `ai_assistant.planning`, and is reached by `orchestration` through this
> Protocol and by no other route.

> **Normative.** `core/types.py` gains **`SearchSupply`**, a frozen model refusing
> unknown fields, with exactly two fields: `utterance: NonBlankEncodableText`, the
> unrewritten user text for the turn being planned, as `orchestration` already holds it;
> and `records: tuple[MemoryRecord, ...]`, defaulting to the empty tuple.

> **Normative.** **`SearchSupply` refuses at construction** any `records` member whose
> `placement.reach` is not `PlacementReach.ANYONE` (§3). The refusal is on the type, so
> no producer, decode, test double or later lane can construct a supply carrying an
> excluded record, and the property is decidable from the value rather than kept by a
> caller.

> **Normative.** **A supply carrying a non-empty `records` is constructed only for a
> destination whose recorded trust is `USER_CHOSEN`.** Where the destination the
> servicing would bind to reads `UNCHOSEN`, the supply carries the utterance and an
> empty `records`, and ADR-0231 §3's utterance-only property therefore holds for that
> destination exactly as ratified. One type, two admissible populations, and which one
> applies is decided by a recorded fact and never by a judgement.

> **Normative.** **`SearchSupply` is constructed at exactly one site** —
> `service_read_request` in `orchestration/reads.py`, which ADR-0231 §11 already fixes
> as the one servicing site — and by no other component. No subsystem outside
> `orchestration` builds one, and no lane adds a second construction site.

> **Normative.** **What may enter `records` is closed to three populations and nothing
> else**: episodes of this conversation that `orchestration` selected into the turn's
> supply; `MemoryRecord`s the turn's retrieval and episodic supplement selected; and
> records **this turn's own** `WEB_SEARCH` servicings minted at a destination whose
> recorded trust is `USER_CHOSEN`. No record of any other origin enters, and in
> particular no record minted at an `UNCHOSEN` destination, by a fetch, by a file read,
> by a reader or by any tool does — which is what §5's condition is stated over from the
> other side.

> **Normative.** **ADR-0231 §16 binds entire and this ADR retains nothing.** A minted
> record's `id` "is minted for one turn … and resolves in no store", "no later turn
> reaches it", and "**a second turn re-searches** … because nothing was retained". So the
> third population above is **within one turn** — the refinement ADR-0228 §2's revision
> makes real, where a second servicing of the same turn composes over the first's
> results — and **no later turn reaches a result's content by any route**. §8's store
> holds two counters and one flag and no result, and no lane reads this ADR as deciding
> retention, an archive admission or a store write for a minted record.

> **Normative.** **What a later turn has instead is the captured episode**, stamped and
> retrieved exactly as ADR-0221, ADR-0223 and retrieval already deliver it, plus whatever
> `MemoryRecord`s the turn selected. That is what resolves "find more about **that**"
> across turns, and it is the first two populations doing the work rather than the
> third.

> **Normative.** Every other clause of ADR-0231 §11 binds unchanged. The only value
> `WebSearcher.request` is passed is the `query` of a `QueryOutcome` the composer
> returned in that same servicing, byte for byte; `orchestration` does not repair,
> extend, truncate or re-case it; and no component augments, re-ranks or annotates a
> query from anything after the composer has written it. **What moves is what the
> composer may be handed, and nothing about what happens to its answer.**

**The mechanism survives; only its content moves, and that is the whole design.**
ADR-0231 §3 named the mechanism itself as the paragraph to check hardest, and its
argument is ADR-0093 §10's: "a caller able to widen the read is a caller able to defeat
the bound", so the property should be decidable from the declaration rather than kept by
a rule. That argument is not weakened by widening what the one argument carries — it is
**relocated**, from the absence of a parameter to the validator on the value. A caller
holding an excluded record still has nothing to pass, because the type refuses it. What
is genuinely given up is narrower than the shape of the change suggests, and §4 says
exactly what it is.

**Why one value rather than three parameters.** Three parameters would put the bound
back in the caller's hands — a supply site that passed the right records would be
conforming and one that passed the wrong ones would be a defect nobody could see from
the signature. One validating value moves the whole question to a place a reviewer reads
once. It is `Placement`'s discipline (ADR-0217 §1's refused-at-construction table) and
`QueryOutcome`'s (ADR-0231 §3's exactly-one validator), and it is deliberately **not**
the unforgeable composed-query value ADR-0231 §19 defers: this type is constructible by
any caller, and what it guarantees is what it *contains*, never who built it.

### 3. Excluded information is ADR-0217's placement, unchanged, with no new axis

> **Normative.** The record-level fact that keeps information out of a query is
> **`Placement.reach`** (ADR-0217 §1), read exactly as ADR-0217 defines it and with no
> field, member, axis, tag or band added by this ADR. A record whose reach is
> `PlacementReach.OWNER` is never supplied to a `QueryComposer`, and §2's validator is
> where that is enforced.

> **Normative.** **No component decides exclusion by inspecting content**, and no lane
> reads this section as licence to filter a record, a span, a query or a supply by
> resemblance, keyword, classifier, detector or any reading of text. ADR-0098 §5's
> unrecoverability and ADR-0146 §2's recorded-never-inferred rule bind here entire, and
> ADR-0098 §6's refusal of a detector as a gate binds with them.

> **Normative.** **The residue is one bit and is stated rather than closed.** A fact the
> user excluded that the model has already paraphrased into a sentence carrying no
> `OWNER` reach is not detected, is not subtracted, and may reach a query. That is
> ADR-0098 §5's corridor, unchanged and unnarrowed, and no clause of this ADR is read as
> an assurance about it.

**ADR-0217 is the answer already in the corpus and inventing a second axis would have
been the defect.** `Placement` records *who may receive this record*; a search provider
is not the owner; the user sets it by an explicit act (ADR-0217 §7); a model may only
narrow it (§3); and it is on `MemoryBase`, so every record kind carries it. The
milestone's phrase "explicitly excluded information stays outside the search context" is
implementable as exactly that and, as #2096's correction records, is implementable as
nothing else. Applying it at the composer's supply site is the same subtraction
ADR-0204 already performs before a reply is spoken, taken one seam further out.

### 4. What is given up, said plainly, and what replaces it

> **Normative.** **ADR-0231 §12's second clause is superseded and its property is
> given up.** "No byte of a search result can reach a later search request" ceases to be
> true of a closed-loop request (§5): a result minted at a `USER_CHOSEN` destination may
> enter `SearchSupply.records` and may shape the query the composer writes. **No lane
> states, implies or relies on that property holding after this ADR**, and no clause of
> this ADR is read as re-establishing it in another form.

> **Normative.** **What replaces it is not a structural claim.** The bound on a closed
> loop is: the destination is one the user chose and told this system it may be told
> about them (§1); what may be supplied is closed by type and filtered by a recorded
> record-level fact (§2, §3); the loop is bounded in calls and time per conversation and
> the draw is recorded (§8); and every one of those is decided from recorded facts. **No
> lane cites budget or audit as making the channel structurally absent.** They bound it
> and they make it visible; they do not remove it.

> **Normative.** **#1844's exfiltration channel is answered by trust in the recipient
> and not by there being no channel.** A search result read at iteration one may steer
> the bytes of iteration two's query, those bytes leave, and the party that receives
> them is the party the user named. No clause of this ADR narrows ADR-0098 §5, and none
> is cited as detecting an attacker-shaped query.

**ADR-0231 §12 stated the risk in #1844's own words and answered it twice — "there is no
channel for the steering to travel down" and "the policy closes even that." This ADR
takes the first answer away outright and rewrites the second.** The honest accounting is
short. The channel's payload is a query composed over a supply that may contain
attacker-chosen bytes. Its capacity is whatever a query can carry, bounded by
`search_query_max_chars`. Its rate is bounded by §8. Its terminus is one party, fixed by
a connected account the operator configured and a trust act the user performed. Its
record is §11's audit. What the design buys with that is the milestone's whole subject —
"find more about that" becoming answerable — and the trade is the owner's, made on
#1908 in terms, not a lane's to soften by claiming more than it has.

**And the first turn's query already left.** ADR-0231 §12 recorded that plainly: "the
query — the user's own question, reformulated by a model that saw nothing else — reaches
the provider, and the provider keeps it under its own policy for as long as it likes."
The relaxation here changes what that query may contain and how often one may be sent.
It does not open a door that was shut; it widens one the user opened by granting the
recipient.

### 5. The closed-loop condition, and why it is blind to how the taint arrived

> **Normative.** A request is **closed-loop** when **all four** hold: its kind is
> `WEB_SEARCH`; the destination its binding carries has recorded trust `USER_CHOSEN`
> (§1); **every recorded external span this conversation has carried — on any earlier
> turn, and on this turn up to the moment the request is built — was minted by a
> `WEB_SEARCH` servicing at a destination of recorded trust `USER_CHOSEN`** (the two
> halves are stated in the clause below); and the conversation's accumulated draw (§8)
> leaves room in every bound of §8 for the call this request would make. A request
> failing any of the four is not closed-loop, and every clause this ADR supersedes binds
> on it exactly as it does today.

> **Normative.** **The third condition ranges over the conversation's recorded turns
> *and* over the current turn**, and the current turn is evaluated live rather than from
> a record that does not exist yet. Its two halves are: the conversation's stored
> `all_external_user_chosen` flag (§8) is true; **and** every recorded
> external span in the turn's pre-servicing supply and in every record this servicing has
> already contributed was minted by a `WEB_SEARCH` servicing at a destination of recorded
> trust `USER_CHOSEN`. The second half is computed by `orchestration` at the moment the
> request is built, from records it holds as data it fetched — the same site, the same
> instant and the same data as ADR-0231 §11's tenth clause computes
> `planned_with_external_content` over.

> **The current-turn half is not an optimisation; without it the condition is wrong in
> both directions.** ADR-0231 §11 fixes the servicing order as local file, then web
> search, then citation hop, then sighted query, so a turn may read a file and *then*
> reach the search. Recorded turns still say true, so a condition reading history alone
> would admit exactly the cross-kind request §5 exists to refuse; and treating the
> current turn's missing record as false would refuse every first search of every turn,
> which is every search there is.

> **Normative.** **Neither half is decided from the taint bit.**
> `planned_with_external_content` is one bit over a selection (ADR-0181 §4) and ADR-0223
> §1 stamps one bit on the captured episode, so neither can say *what* the external
> content was. **No component recovers either half by inspecting an episode, a record's
> content, a query or a reply**, and no component asks a model for either.

> **Normative.** **The whole condition reaches the ruling as one recorded fact on the
> binding.** `EgressBinding` gains `closed_loop: bool`, **defaulting to `False`**: true
> exactly where all four conditions above hold for this request, and false otherwise —
> so false for every request that is not a `WEB_SEARCH`, and false on every binding this
> corpus builds today. `CarriedProvenance` gains the same field with the same default, and
> the seam writes the binding's value from the carrier's unchanged. This is ADR-0181 §3's
> carriage and ADR-0233 §4's shape, stated over the same two types for the same reason.

> **Normative.** **The default is `False` rather than "required with no default", and that
> is a decision rather than a convenience.** It keeps **ADR-0152 §7's transcription count
> untouched**: `rebind` re-derives a binding for a resumed confirmation and "takes from
> `approved` **exactly one** thing", already narrowed twice (ADR-0181 §3, ADR-0233 §4), and
> a fourth transcription would supersede that clause a third time. With the default,
> `rebind` transcribes nothing new and constructs `False` — **the correct value for every
> request that can resume**, because a `CONFIRM` on a `WEB_SEARCH` decision "resolves in no
> turn" (ADR-0231 §9, whose limbs bind entire under ADR-0235 §3), so no closed-loop request
> is ever resumed.

> **Normative.** **The default is safe in the direction a default is usually unsafe.**
> `False` is the **restrictive** value, so a composition site that fails to compute it
> yields a request that is not closed-loop and rules exactly as `origin/main` rules today.
> The failure mode of the omission is that this milestone does not work, which is loud. It
> is not a floor bypassed by a missing field, which is what ADR-0233 §4's "required with no
> default" guards for a three-valued fact whose safe member is not its first.

> **Normative.** **`closed_loop` is written by `orchestration`, at the moment the request
> is built, and by nothing else.** It is computed from the conversation's recorded turns,
> the current turn's supply, the trust store's answer and the budget fold — every one of
> them a value `orchestration` holds as data it fetched. **It is discarded, never merged,
> if any producer emitted one**; no model output contributes to it; no component infers
> it, defaults it, repairs it or recomputes it downstream; and a lane that finds itself
> computing it outside `orchestration` has breached this clause.

> **Normative.** **A stored binding written before this decision decodes with
> `closed_loop` false**, which is ADR-0181 §12's own case and the fail-closed direction.
> The two comparisons that already carry a binding carry this field for no reason special
> to it: `EgressBinder.rebind` re-derives and refuses unless the binding equals the parked
> one (ADR-0152 §7), and `PermissionDecision.authorises` compares the whole binding at the
> seam (ADR-0181 §5's fifth clause). Neither is moved, duplicated or widened here.

> **Normative.** **What the fact buys is a value the ruling can read, and not a claim
> anybody re-derives.** No `ActionPolicy` acquires a store handle, a trail read, a grant
> seam or a conversation identity in order to check the four conditions — ADR-0181 §5's
> third clause and ADR-0097 §7 forbid the last of those outright — and no `AuditTrail`
> revalidates them. The trust boundary is exactly the one this corpus already accepts for
> `planned_with_external_content` (ADR-0181 §2, §4) and for `coverage` (ADR-0233 §5): the
> component that composed the arguments computes the fact, and everything downstream reads
> what it wrote.

> **Normative.** **A turn with no such record fails the condition**, and so does a
> conversation holding one. Absence is the fail-closed direction here as it is in §1, so
> no conversation that predates the implementing lane acquires the carve-out, and a
> failure to write the record is a failure to search rather than a failure to refuse.

> **Normative.** **The condition is blind to why a turn carries external content.** It
> is stated over what was minted and where it went, never over the cause of a stamp, so
> a stamped episode is treated exactly as any other cause — which is what ADR-0223 §6
> requires of any clause reaching that floor, and this ADR adds no episode-shaped
> carve-out to it.

> **Normative.** **A search result authorises nothing else.** The relaxations §6 and §7
> make are available to a closed-loop request and to no other request of any kind. Every
> other request in the conversation — an email, a fetch, a tool call, a search to an
> `UNCHOSEN` destination — keeps ADR-0181 §5's floor, ADR-0193 §3 and §4, ADR-0155 §3
> and ADR-0233 §9 exactly as written, and no lane reads a conversation's closed-loop
> status as reaching them.

**The condition is what stops a later kind riding this one, and it is stated as a rule
rather than carved by hand for that reason.** Milestone 32's subject is a page fetched
from a site the provider returned. Such a page is minted by a fetch, not by a
`WEB_SEARCH` servicing, and its destination reads `UNCHOSEN`, so a conversation that has
read one fails the third condition permanently and searches under ADR-0181 §5 as
written. The same is true of a file, a calendar, an inbox or any MCP result — ADR-0098
§1's external class is broad, and the condition is stated positively over one narrow
population precisely so that breadth costs nothing to enumerate.

**"Same kind" is three facts and not one, which is the correction the obvious
formulation needs.** A carve-out for "a search in a conversation that has read a search
result" would admit a conversation that read a result at an `UNCHOSEN` destination, and
would admit one whose taint came from somewhere else entirely if the loop could not tell
the two apart — which, on today's one-bit stamp, it cannot. Naming the destination's
trust and requiring a per-turn record are what make the sentence checkable.

### 6. The lineage floor and the grant move exactly as far as the closed-loop condition reaches

> **Normative.** **ADR-0181 §5's second clause is superseded for a closed-loop request
> alone.** On such a request an `ActionPolicy` may return `ALLOW` on ADR-0148 §3's
> route (b) — a standing user policy established by a recorded act of the user — despite
> the binding carrying `planned_with_external_content`. On every request that is not
> closed-loop the clause binds exactly as ratified, and §5's remaining clauses, §5's
> memory-ruling-point clause and every other section of ADR-0181 are untouched.

> **Normative.** **ADR-0193 §3's first clause is superseded in its fifth comparison, and
> §4's first clause is superseded, for a closed-loop request alone.** A `RecipientGrant`
> may cover such a request notwithstanding the binding carrying
> `planned_with_external_content`, and the other four comparisons — liveness, tool
> equality, account equality, and every member of the request's canonical destination set
> being a member of the grant's — bind entire and are not narrowed, widened or reordered.
> The fifth comparison stands unchanged for every request that is not closed-loop.

> **Normative.** **ADR-0193 §6's eighth-check clause is superseded in one limb, for a
> closed-loop request alone.** That clause admits a route-(b) `ALLOW` only where all eight
> hold, the seventh being that "the decision's `egress_binding` is an **`EgressBinding`**
> whose `planned_with_external_content` **is `False`**". That limb becomes: whose
> `planned_with_external_content` is `False`, **or** whose `closed_loop` is `True`. **The
> other seven are untouched** — the outstanding-grant read, both ends of liveness, tool
> equality, account equality, destination-set containment and the recomputed
> `subject_digest` — and each is still taken over the record the store returned rather than
> over the decision's account of it.

> **Normative.** **The `OriginUnrecordedBinding` arm stays refused by name.** ADR-0193 §6
> states the origin check "over the binding's **arm**, not only over a field's value", and
> a binding that records no origin carries no `closed_loop` either. Such a decision is
> refused exactly as today, and no lane reads this section as making an unrecorded origin
> readable as a closed loop.

> **Normative.** **`record` validates the fact on the binding and not the conditions
> behind it**, and this ADR claims no more. It holds no conversation store, no trust store
> and no supply, and ADR-0193 §6's "nothing is taken on trust" is stated over the *grant*,
> which `record` can and does re-read. The four conditions are `orchestration`'s to compute
> at the one site §5 names, exactly as `planned_with_external_content` is, and the trail has
> never revalidated that field either.

> **Normative.** **The `AuditTrailContract` suite gains both arms in the same change as the
> field**: a closed-loop route-(b) `ALLOW` over external content is recorded, and one whose
> `closed_loop` is false is refused exactly as
> `test_a_decision_planned_over_external_content_is_refused` requires today. Neither arm is
> deferred to a later lane.

> **Normative.** **ADR-0193 §5 is not superseded and is relied upon.** A grant still
> reaches the recipient and never the payload; it still authorises no content, classifies
> no span, raises no tier and satisfies no floor stated over anything but recipient
> authorisation. What permits the payload is §1's separate recorded act, and no component
> reads a grant as supplying it.

> **Normative.** **ADR-0154 §4 item (ii)'s floor is not lifted further by this ADR.**
> ADR-0193 §12 superseded it in exactly one respect — a `RecipientGrant` covering a
> request under ADR-0193 §3 may source an `ALLOW` — and this ADR moves what ADR-0193 §3
> requires without adding a second standing-authorisation carrier at the seam. No lane
> reads this section as opening one.

> **Normative.** **ADR-0148 §3 is untouched.** Route (b) is used as it is already
> written; no third route is created; and the enumeration of what is not a user act —
> "a tool's own declaration, the scope or audience of a credential, a configured base
> URL or host, an allowlist the system assembled" — binds on §1's act as on any other.

**The floor is moved rather than removed, and the difference is the closed-loop
condition doing work at every ruling.** ADR-0181 §5's clause was ruled with no live
subject, on ADR-0098 §3's ground that "an actuator rule is free now and expensive later"
and that "the lane that opens standing authorisation for egress will be doing it because
per-call confirmation has become tiresome". That description fits this ADR exactly, and
the answer to it is that the exception is not general: it names one kind, one
destination class, one closed population of external content and one budget, all four
checked per request from recorded values. The clause's own last sentence — that an ADR
lifting ADR-0154's floor "may not lift it for a call carrying
`planned_with_external_content`" — is the sentence being moved, and it is moved to the
narrowest thing that reaches the milestone rather than to the widest thing the argument
would carry.

### 7. ADR-0155 §3's third clause takes a second exception, and ADR-0233 §9's four conditions are untouched

> **Normative.** **ADR-0155 §3's third clause acquires a second exception.** An egress
> span may carry covered content all of whose covered paths contain a model call where
> **all three** hold: the span is the `query` of a `QueryOutcome` a `QueryComposer`
> returned over a `SearchSupply` §2 admits; the request carrying it is closed-loop (§5);
> and the ruling on it is an `ALLOW` under §6. Where any of the three fails, the clause
> forbids the span exactly as written.

> **Normative.** **ADR-0155 §3's second clause is untouched and has no subject here.**
> Every covered path of a composer's output continues back through the composer's own
> model call, so no covered content this exception admits has a covered path containing
> none. No lane reads this section as reaching a span the second clause governs, and §2's
> supply site is where that is decided from recorded origin rather than argued.

> **Normative.** **ADR-0233 §9's first clause is superseded in its exclusivity alone.**
> Its "**only** where all four hold" becomes "where all four hold, or where §7's three
> hold"; the four conditions themselves are not weakened, reordered, reinterpreted or
> made disjunctive, and they remain the whole of what makes a model-composed span
> approvable **by confirmation**. A span reaching a destination outside §7's three
> conditions meets §9's four or is refused.

> **Normative.** **ADR-0233 §9's second clause is superseded for the class §7 admits and
> for nothing else.** "No standing authorisation, standing policy, standing recipient
> grant, configuration, connected account, tool declaration or approved payload
> description covers such a call, ever" continues to bind on every model-composed covered
> span outside §7's three conditions — and within them, the standing route §6 opens is
> the user's own act about this destination and this payload class, and not a
> configuration, an account or a declaration. Nothing here makes a configuration, a
> connected account or a tool declaration into an authorisation of anything.

> **Normative.** **ADR-0233 §8's floor is not read as satisfied, discharged or waived by
> this ADR**, and no surface owing it is relieved of it. §7's route reaches an `ALLOW`
> without a `Confirmation`, so §8's floor has no confirmation to bind — it binds
> unchanged wherever ADR-0233 §9's four conditions are the route, which is every other
> model-composed span in this corpus.

**The owner's ruling is the authority for a second exception, and it is cited rather than
assumed.** ADR-0155 §3 reserved the choice between ratifying its third clause and
commissioning a content-bearing approval surface to "an owner ruling", and closed "An
owner ruling alone does not relax this clause; relaxation requires the commissioned ADR
and its approval surface, ratified, and **until then** every lane implements the
prohibition as written." Arm (b) was ruled on 2026-09-04, ADR-0233 is the commissioned
ADR and is ratified and implemented, and ADR-0233's own record states that the "until
then" has stopped running. The owner ruled milestone 31 on 2026-09-05, in terms that name
this clause's consequence and require it to move — "**This is a contract reversal, not a
relaxation**". So the instrument ADR-0155 §3 requires exists, the condition it attached
is met, and this ADR is an ADR making a further relaxation on an owner ruling rather than
a lane taking one on its own reading. **A lane may not do this without that ruling**, and
nothing here is read as making it easier for the next one.

**Why a second exception rather than a widening of ADR-0233's four.** ADR-0233 §9 states
its conditions "together rather than as one gate" precisely so that "a later ADR removing
any one of them removes the ground this relaxation stands on". Widening its second
condition to admit a standing route would have removed the digest binding's reason to
exist and would have reached every model-composed span in the corpus. A second, separately
stated exception over one kind, one destination class and one closed population leaves
ADR-0233's conjunction intact for everything else — which is what makes its own
relaxation legible in the way §9 wanted.

### 8. The budget: calls and elapsed time per conversation, carried on the turn row

> **Normative.** `core.config.Settings` gains exactly two fields.
> **`search_calls_per_conversation: int`**, defaulting to **8**, domain the integers
> from **0** through **64** inclusive, where **0 means no search is serviced in any
> conversation**. And **`search_elapsed_per_conversation: timedelta`**, defaulting to
> **60 seconds**, domain finite and non-negative, where zero means the same. A value
> outside either domain is refused at `Settings` load with the `ConfigurationError`
> ADR-0194 §1's configured-amount clause requires, naming the field.

> **Normative.** **Both bounds ship with a value rather than meaning "unbounded" when
> unset.** ADR-0194 §1's "unset means unbounded" governs a monetary ceiling an operator
> chooses; a bound the milestone's exit is stated over may not be absent by omission, so
> a deployment that configures nothing still searches under both.

> **Normative.** `core/types.py` gains **`ConversationSearchDraw`**, a frozen model
> refusing unknown fields, with exactly three fields: `calls: int`, non-negative, the
> provider calls this conversation has claimed; `elapsed: timedelta`, non-negative and
> finite, the time those calls were allowed; and `all_external_user_chosen: bool`,
> defaulting to `True`, false once any turn of this conversation has carried a recorded
> external span that was **not** minted by a `WEB_SEARCH` servicing at a destination of
> recorded trust `USER_CHOSEN`.

> **Normative.** `core/protocols.py` gains **one** further `@runtime_checkable` Protocol,
> **`SearchBudgetStore`**, keyed by conversation, with exactly **four** members:
> **`draw_of`**, answering a conversation's `ConversationSearchDraw`, and answering
> `calls=0`, `elapsed=0` and `all_external_user_chosen=True` for a conversation it holds
> nothing for; **`claim`**; **`settle`**; and **`observe`**, folding one turn's externality
> footing into the stored flag by logical **and**. A fifth member is added by no lane
> without the ADR that decides it.

> **Normative.** **`claim` is one atomic step: admit, charge, and answer the deadline.**
> Given a conversation and the two bounds, it refuses where the stored `calls` have reached
> `search_calls_per_conversation` or the stored `elapsed` has reached
> `search_elapsed_per_conversation`; otherwise it increments `calls` by one, adds to
> `elapsed` the **deadline it is about to grant**, and answers that deadline — the lesser of
> the transport's own timeout and the conversation's remaining time. **The read, the
> comparison and the write are one indivisible step.** That is `RecipientGrantStore`'s
> atomic count-with-append (ADR-0193 §1) applied to a counter, and it is why concurrent
> turns, a failed turn and a process exit are answered by one clause rather than three:
> **two turns of one conversation, two servicings of one turn, and two engines over one
> data directory can none of them be admitted against the same draw.**

> **Normative.** **`settle` replaces a claim's charged deadline with the time the call
> actually took**, which is never more than the deadline. It is the only write that lowers
> `elapsed`, it lowers no `calls`, and **a claim that is never settled stands at its full
> deadline** — the fail-closed direction, and the reason nothing is owed for a turn that
> ends in an exception, a `PlanningError` on a later revision, a restart or a disconnection.

> **Normative.** **A claimed call is consumed whatever the outcome, and there is no
> refund.** A servicing that claims and then does not transmit — a binding that refused, a
> ruling that was not `ALLOW`, a provider that rejected before or after receiving the query
> — still spends its `calls` increment. **`SearchOutcome` carries no transmission fact** and
> `WebSearcher` is not widened here to add one, so a refund rule would oblige the servicer
> to tell two `SearchRefusal.PROVIDER_REFUSED` outcomes apart when nothing in the contract
> distinguishes them. Conservative admission is the honest reading, and it errs toward
> searching less.

> **Normative.** **The elapsed bound is enforced as a deadline and never as a hope.** The
> value `claim` answers is the deadline that call is given, so a call cannot run past the
> conversation's remaining time and the stored `elapsed` can never exceed the bound. No
> implementation admits a call on accumulated time alone and then lets it run to the
> transport's own timeout.

> **Normative.** **The footing is monotone and is written by `orchestration`.** For every
> turn it captures, `orchestration` calls `observe` with whether **every** recorded external
> span that turn's final supply carried was minted by a `WEB_SEARCH` servicing at a
> destination of recorded trust `USER_CHOSEN` — computed from records it holds as data it
> fetched, at the same instant and by the same component as ADR-0223 §1's own value. **Once
> false the flag never returns to true**, which is ADR-0106 §4's monotonicity read on this
> axis, and it is what keeps a conversation closed after the tainting episode has fallen out
> of the tail (ADR-0223 §6's un-tainting, which this ADR does not disturb).

> **Normative.** **A conversation this store holds nothing for reads a true flag, and that
> is correct rather than permissive.** Vacuous truth over zero observed turns is what a new
> conversation deserves; a conversation that searched before this decision landed carries
> its stamped episode in the very next turn's supply, so §5's **current-turn** half is false
> for it before any `observe` has run, and its first captured turn writes the flag false for
> good. No legacy conversation acquires the carve-out at any point.

> **Normative.** **The store is local, durable and never written to a remote service**
> (ADR-0004 §2), it holds a Tier 1 fact, it ships as a **triad**, and it holds **counters
> and one flag and no content** — no query, no result, no destination, no record, no text.

> **Normative.** **A conversation's row goes when the conversation goes.** The
> capture/lifecycle stage in `orchestration` clears it in the same sequences it already
> runs — ADR-0074 §8's deletion and §7's retention reclaim — because ADR-0074 §9 already
> rules that "the **capture/lifecycle stage in `orchestration`** owns every cross-store
> sequence". This ADR adds a store to those sequences and changes neither, and
> **`ConversationStore` gains no member, `Conversation` and `ConversationTurn` gain no
> field, and `ConversationExport` does not change shape or version.**

> **Normative.** **`claim` is called before a query is composed**, at the servicing site §2
> names. Where it refuses, **no supply is constructed, no query is composed, no ruling is
> sought, no credential is read and no channel is opened**, and §11's audit records it. This
> is ADR-0231 §11's no-slot clause in a second place and by the same posture: the servicing
> does not yield, the turn composes from what it has, the user is asked nothing and nothing
> is parked.

> **Normative.** **This ADR adds no monetary bound**, no `SpendGate`, no ledger row, no
> ceiling and no `Settings` field for one, and ADR-0194's mechanism is neither coupled
> to these bounds nor read by them. ADR-0231 §15 binds entire: the transport call is
> admitted by a `SpendGate` inside the seam over ADR-0236's declared figure, exactly as
> today.

**A conversation and not a period, because the milestone says so and because the unit is
the one the user can see.** #1908 states the bound as "calls, time and cost per
conversation", and the conversation is the object a user starts, reads and abandons. The
honest cost is stated in Consequences: a long-lived conversation exhausts its budget and
searches no more, and the remedy is a new conversation. The rolling-window variant is
deferred in §16 with its trigger rather than smuggled in as a default.

**Money stays where money already lives.** A per-conversation *monetary* bound would be a
per-tool ceiling, which ADR-0194 §8 defers and reopens "by a decision that lands keyed
per-user tool configuration … and by nothing else". This ADR does not walk that trigger.
What it gives instead is a determinate maximum an operator can compute in their head —
the call bound times ADR-0236's declared per-call figure — with ADR-0194's period
ceilings as the money backstop underneath. That is a smaller claim than "cost is bounded
per conversation" and it is the one this corpus can actually make.

### 9. #2116 is not taken here, and milestone 31 does not wait on it

> **Normative.** **ADR-0194 §8's deferred default spend ceiling is not decided by this
> ADR.** No `Settings` field acquires a shipped default here, ADR-0194 §1's "unset means
> unbounded" is not moved, and no lane reads §8 above as having taken it. §8's own first
> clause governs: each deferral is reopened by its own ratified decision and by nothing
> else.

**#2116 is a correct report and it is not this ADR's to answer.** Its trigger has fired —
ADR-0235's establishing surface and ADR-0236's per-call figure together make a priced
invocation executable with no per-call user act — and what it asks for is a shipped
default monetary ceiling over *every* priced tool, in a currency this corpus does not
convert (ADR-0194 §8, ADR-0016 §4), weighed against what a real provider charges. That is
a deployment-wide spend policy, not a fact about contextual search, and deciding it inside
an ADR about destination trust would bind every future priced tool by a side effect. §8's
bounds are what milestone 31's exit is stated over and they hold whether or not #2116 ever
closes.

### 10. #2126 decided: a completion reports `UNKNOWN` by design, and one load-time refusal makes repeat searching reachable

> **Normative.** **A completed `WEB_SEARCH` reports an `UNKNOWN` incurred cost, by
> design.** `WebSearchEgress` reports no figure, `consumed_call` writes
> `unknown_cost()`, and that is ratified here rather than repaired. **No lane copies
> `web_search_cost_per_call` into `incurred_cost`**, restates a declared estimate as a
> reported figure, or otherwise crosses ADR-0194 §2's estimate/reported boundary: a
> reported figure nobody measured is the substitution that clause's own no-stand-in rule
> refuses.

> **Normative.** **Where `web_search_cost_per_call` is set and any ADR-0194 period
> ceiling is configured, `world_spend_unknown_allowance` must also be set**, and a
> configuration setting the first two and not the third is refused at `Settings` load
> with a `ConfigurationError` naming the field. This is `web_search_cost_per_call` and
> `web_search_cost_currency`'s own cross-field shape (ADR-0236 §2), applied to the pair
> that actually determines whether a priced search is repeatable.

> **Normative.** Nothing in this section changes what a search **declares**, what the
> gate admits, or how ADR-0194 §2 treats an indeterminate total. The allowance is the
> mechanism ADR-0194 already provides for a reported `UNKNOWN`, used as designed.

**The trap #2126 records is real and it is fatal to this milestone, which is why it is
answered here rather than deferred.** On a deployment with a declared figure, a grant, a
period ceiling and no allowance, the first search of a period completes, records
`UNKNOWN`, makes the period's accounted total indeterminate, and every later search that
period is refused `SpendUndeterminedError`. One search per period is not "continues within
an enforced budget"; it is a different milestone's behaviour arriving by accident. The
issue names two ways to close it and this ADR takes the second, because the first would
have to cross a boundary ADR-0194 §2 draws on purpose, and because the allowance exists
for exactly this case. The refusal is what stops an operator discovering the interaction
from the audit two weeks later.

### 11. The audit

> **Normative.** ADR-0226 §9 and ADR-0231 §13 bind entire and this decision adds **no
> second audit, no second event key and no new emission point**. One `INFO`-level
> structured log event per turn, under the one fixed key, carrying the ambient
> correlation identifier and **no other identifier**.

> **Normative.** The record gains, per turn: the count of records supplied to the
> composer; the count of records withheld from the supply by §3's filter; and this
> turn's `calls` and `elapsed`. **Counts and quantities only.** No record id, no
> conversation id, no destination, no query text, no fragment or length of one, no
> title, no snippet and no provider message appears — ADR-0231 §13's Tier 1 clause and
> ADR-0004 §5 bind without qualification.

> **Normative.** **`SearchDisposition` gains exactly one member**, recording that a
> servicing did not reach a query because a bound of §8 was met. It is not free text, it
> collapses with no existing member, and it lives in `ai_assistant.orchestration` beside
> the rest of that enumeration, which crosses no subsystem boundary.

> **Normative.** **The destination's recorded trust is not written to this event.** It
> is a durable fact about a configured account, readable from the store that holds it,
> and a per-turn log is not where a deployment's standing configuration is reported.

**The audit is the trigger's measuring instrument and it is also the only thing that makes
§4's admission checkable.** A deployment that has given up a structural property owes
itself a number for how often the loop actually re-searched and how much of the supply it
was given. Both are readable over a population from this one event, and neither is a
per-turn quantity anyone should read as one (ADR-0226 §8).

### 12. The negative arm, stated as obligations

> **Normative.** **An injected result cannot raise the budget.** Both bounds are
> `Settings` values read by `orchestration`; the draw is a durable counter §8's store
> increments atomically before a channel opens, and it is never lowered by any write but
> `settle`, which only ever replaces a granted deadline with a smaller elapsed.
> **No value produced by a model, carried in a request, contained in a search result, or
> read from any record contributes to either side of the comparison**, and no component
> raises, extends, resets, suspends or re-reads a bound on account of a turn's content.
> A deployment raises a bound in `Settings` and by no other route.

> **Normative.** **An injected result cannot carry an excluded record into a query.**
> §2's validator refuses a non-`ANYONE` reach at construction, evaluated per record and
> regardless of why that record was selected, so no selection a result influences can
> place one in a supply.

> **Normative.** **An injected result cannot make a destination trusted.** §1's fact is
> set by a recorded user act alone and is never proposed, raised or judged by a model.

> **Normative.** **An injected result cannot widen the closed-loop population.** Both
> halves of §5's third condition are computed by `orchestration` from records it holds as
> data it fetched. A record that arrives from an `UNCHOSEN` destination or by any other
> route fails the current-turn half **at once** — before the next request of that same
> turn is built, not only at capture — and fails the recorded half for every later turn of
> the conversation.

> **Normative.** **An injected result cannot make a binding claim a closed loop.**
> `closed_loop` is written by `orchestration` alone, discarded and never merged if any
> producer emitted one, and compared through `rebind` and `authorises` on every resumed
> path. No model output, no request content and no search result contributes to it.

> **Normative.** **Credentials stay out structurally and no clause here moves them
> nearer.** No composer holds a `Secrets` face; nothing in `planning/` or
> `orchestration/` reads the secret store; the credential is read inside the seam at
> ADR-0148 §7's position and reaches no supply, no query and no record. The one residue
> is ADR-0231 §12's, unchanged: **a secret the user typed into their own utterance may be
> carried into a query**, exactly as `send_email` may carry one into a body (#75), and no
> detector closes it (ADR-0098 §5, §6).

### 13. The `core` surface, the version, and what a record written before this decodes to

> **Normative.** The `core` surface this decision adds is exactly this and no more. In
> `core/types.py`: `DestinationTrust`, `DestinationTrustRecord`, `SearchSupply` and
> `ConversationSearchDraw` as new types, and one member on each of `EgressBinding` and
> `CarriedProvenance` (`closed_loop`, defaulting to `False`). In `core/protocols.py`: two
> new `@runtime_checkable` Protocols, `DestinationTrustStore` with its five members and
> `SearchBudgetStore` with its four, and the changed parameter type on
> `QueryComposer.compose`. In `core/errors.py`: `InvalidDestinationTrustError`. In
> `core.config.Settings`: the two fields §8 names and the cross-field refusal §10 states.
> **No other member of any `core` type or Protocol changes its type, its default or its
> meaning** — `ActionPolicy`, `AuditTrail`, `ConversationStore`, `MemoryStore` and
> `WebSearcher` each gain no member, no argument and no widened return; `Conversation`,
> `ConversationTurn` and `ConversationExport` gain no field and change no version;
> `Provenance` gains no field, so ADR-0098 §5's deferral of a per-span externality fact is
> neither taken nor narrowed; and `CarriedProvenance.spans`, its key and value types, its
> detachment validator and its serializer all stand.

> **Normative.** **`PROTOCOL_VERSION` moves 31 → 32**, and `wire/envelope.py`'s log gains
> an entry naming this ADR and this reason: `AssistantEngine.recent_decisions` and
> `export_decisions` return `tuple[PermissionDecision, ...]`, a `PermissionDecision`
> carries an `EgressBinding`, and `EgressBinding` gains a member — which is ADR-0178 §6's
> rule and ADR-0233's own ground for moving it. The field's `False` default is why a peer
> one version behind still decodes what it is sent; the move is owed because the shape
> changed, not because anything breaks.

> **Normative.** **`ConfirmationEgress` gains no member and `ConversationExport` changes
> neither shape nor version.** `closed_loop` is an authorisation-route fact rather than a
> fact about what would leave, and ADR-0233 §8's floor — the one thing a surface owes about
> a model-composed span — turns on `coverage` and not on this; §8's counters live in their
> own store precisely so that `Conversation` and `ConversationTurn` stay as they are, which
> leaves `ConversationExport.schema_version` at **2** and ADR-0212 §8 and ADR-0014 §5
> untouched. **A lane that finds either statement false moves the corresponding version in
> the same change** rather than reading this clause as permission not to.

> **Normative.** **A stored `PermissionDecision` whose `egress_binding` predates this
> decision decodes with `closed_loop` false**, on ADR-0181 §12's own reading of a
> pre-existing row, and no lane back-fills it, infers it or reconstructs it. A false value
> is the state every binding in this corpus carries today, so nothing decoded changes
> behaviour.

> **Normative.** **A conversation §8's store holds no row for reads a zero draw and a true
> flag**, which §8 states is correct rather than permissive, and which §5's current-turn
> half is what actually closes for a legacy conversation. No lane back-fills a row, infers
> one, or reconstructs one from an episode, a log or a trail.

> **Normative.** **A conversation in progress when the implementing lane lands behaves
> exactly as it does under ADR-0231 today**: it is not closed-loop, so it searches under
> ADR-0231 §12 as ratified. The accumulated draw of such a conversation under-counts by
> at most the calls it made before the field existed, which ADR-0231 §12 already bounds
> at one per conversation, and that residue is accepted rather than repaired.

### 14. What the implementing lane owes

> **Normative.** **Both** new Protocols ship as **triads** — the Protocol, a shared
> conformance suite asserting its obligations, and a canonical fake in
> `ai_assistant.testing` — in one change, never deferred (`CONTRIBUTING.md` → "Adding a
> Protocol"). The `QueryComposer` conformance suite's one-positional-parameter check is
> kept and is restated over the new parameter type.

> **Normative.** **`SearchBudgetStore`'s conformance suite asserts the atomicity `claim`
> claims**, in the shape `RecipientGrantStore`'s ceiling test already takes: concurrent
> claims against a bound of one yield exactly one admission, and an implementation that
> reads, compares and writes as three awaits fails it. An implementation that cannot be
> opened twice states so and skips, as the ledger contracts already do.

> **Normative.** **The `PROTOCOL_VERSION` move (§13) rides the `core` change**, with its
> `wire/envelope.py` log entry, because the field lands there and a version behind the
> shape is the defect that log exists to prevent.

> **Normative.** **The lane implements no surface for §1's establishing act**, and
> ADR-0193 §13's assignment binds unchanged: which surfaces offer it, what the wire
> carries for it and how a browser or command-line surface lays it out are ADR-0177's,
> ADR-0178's and ADR-0186's to decide. No lane mints a trust record beside them, and no
> lane reads this ADR's dependence on that surface as licence to.

> **Normative.** **The production composer's prompt is `planning/`'s and its widened
> input changes no rule about what it may write.** A composed query stays a model
> completion with no recorded origin, of the same class as `ActionPlan.rationale`
> (ADR-0231 §3), and **no lane reads its having been composed over a wider supply as
> making it a worse class than one composed over the utterance alone** — ADR-0231 §3's
> own clause, which was written on the other axis, read here on this one.

> **Normative.** The lane wires the trust store into the one servicing site and into
> nothing else, holds no reference to it in any other subsystem, and adds no second
> caller. `app/composition.py` is the only place the concrete store is constructed.

### 15. The representative-input tests this decision owes

> **Normative.** Each arm below is a test the implementing lane owes, over the production
> policy, the production composer seam and the production servicing path, and not over a
> double standing in for one of them.

> **Normative.** **Arm 1a — refinement, within one turn.** On a turn whose destination
> reads `USER_CHOSEN`, a first servicing mints results and a plan revision (ADR-0228 §2)
> asks again; the second servicing's supply carries the first's minted records, the query
> differs, the ruling is `ALLOW` on route (b), and the user is asked nothing.

> **Normative.** **Arm 1b — the exit's cross-turn arm.** A later turn of the same
> conversation, whose supply carries the stamped episode and no minted record of any
> earlier turn, composes a query resolving a reference the utterance alone cannot ("find
> more about that"), rules `ALLOW` on route (b) with the binding carrying both
> `planned_with_external_content` **and** `closed_loop` true, is recorded by
> `AuditTrail.record` rather than refused, and asks the user nothing.

> **Normative.** **Arm 2 — the same conversation with the trust record absent.** Every
> other fact identical, the destination reads `UNCHOSEN`: the supply carries the
> utterance and an empty `records`, the second search draws a non-`ALLOW`, and the
> servicing yields nothing.

> **Normative.** **Arm 3 — the negative arm, budget.** A search result whose text asks
> in any terms for more searches, a higher budget or a suspended bound changes neither
> bound and neither side of the comparison; the conversation stops at
> `search_calls_per_conversation` and the disposition §11 adds is recorded.

> **Normative.** **Arm 4 — the negative arm, exclusion.** A record whose
> `placement.reach` is `OWNER` is refused by `SearchSupply` at construction, in a
> selection the result influenced and in one it did not, and the withheld count reaches
> the audit.

> **Normative.** **Arm 5 — the cross-kind closure, in both directions.** A conversation
> that read a search result and then read one record of any other external origin is not
> closed-loop from that turn onward, and its next search draws a non-`ALLOW` under
> ADR-0181 §5 as written. **And within one servicing**: a turn that services a local-file
> read before its `WEB_SEARCH` — which ADR-0231 §11's fixed order makes the ordinary
> case — binds `closed_loop` false on that same turn's search, however its recorded turns
> read.

> **Normative.** **Arm 5b — the audit trail's own refusal.** A route-(b) `ALLOW` over
> external content whose binding carries `closed_loop` false is refused by
> `AuditTrail.record` exactly as today, and one carrying it true is recorded; a decision
> whose binding is an `OriginUnrecordedBinding` is refused by name in both cases.

> **Normative.** **Arm 5c — nothing else rides it.** A `send_email` and a
> non-`WEB_SEARCH` egress call in a closed-loop conversation each bind `closed_loop`
> false and rule exactly as they do today.

> **Normative.** **Arm 6 — the legacy conversation.** A conversation whose turns carry no
> `search` record is not closed-loop, contributes a zero draw, and behaves as ADR-0231
> §12 rules.

> **Normative.** **Arm 6b — the budget is consumed at admission, in four shapes.** With
> `search_calls_per_conversation` set to one and a stored draw of zero: two servicings of
> **one turn** yield one call and not two; two **concurrent turns** of one conversation
> yield one call and not two; a turn that searches and then fails on a later revision
> (`PlanningError`, so capture is never reached) leaves the draw at one, so the **next
> turn** searches not at all; and a store reopened after a process exit reads that same
> one, with the unsettled claim standing at its full deadline.

> **Normative.** **Arm 6c — the elapsed bound is a deadline.** With
> `search_elapsed_per_conversation` at sixty seconds and fifty-nine already stored, the
> admitted call is given a one-second deadline rather than the transport's own timeout, and
> the stored `elapsed` never exceeds the bound.

> **Normative.** **Arm 6d — a claimed call is never refunded.** A servicing whose ruling is
> not `ALLOW`, one whose binding refused, and one whose provider answered
> `SearchRefusal.PROVIDER_REFUSED` each spend their `calls` increment, and no path lowers
> `calls`.

> **Normative.** **Arm 6e — the footing is monotone.** A conversation whose flag is false
> stays false when a later turn's supply carries nothing external at all, including after
> the tainting episode has fallen out of the tail.

> **Normative.** **Arm 7 — the spend interaction.** A deployment with a declared per-call
> figure, a period ceiling and no `world_spend_unknown_allowance` is refused at
> `Settings` load, naming the field; one with the allowance set searches repeatedly
> without the period's total becoming indeterminate.

> **Normative.** **Arm 8 — the model cannot reach the fact.** No path from any model
> output writes, raises or is consulted about a destination's trust, and the conformance
> suite for the trust store asserts that its recording member is reached by no component
> holding a `ModelProvider`.

> **Normative.** **Arm 8b — an ordinary confirmation still resumes.** A parked
> `send_email` confirmation resumes through `rebind` unchanged: the re-derived binding
> carries `closed_loop` false by default, transcribes nothing new from `approved`, and
> equals the parked binding — so ADR-0152 §7's comparison passes exactly as it does today,
> for a decision recorded before this change and for one recorded after it.

> **Normative.** **Arm 9 — the trust store's own conformance.** `trust_of` answers
> `USER_CHOSEN` only where every member of the sequence is in one live record's set;
> `UNCHOSEN` for an empty sequence, for a partial match, for a match spanning two records,
> for a revoked record, and where the two sides differ in any field of a
> `CanonicalDestination` or across protocols; `record` refuses a duplicate id, an empty
> set, a duplicate live set and an `UNCHOSEN` record; `revoke` is prospective and
> idempotent and rewrites no recorded decision; and `export` answers revoked records that
> `live` omits, which is the data right ADR-0004 §6 gives and ADR-0193 §1 already applies
> to authorisation records.

### 16. Deferred, by name, each with what fires it

- **Milestone 32's fetch, and everything about an `UNCHOSEN` destination beyond the
  member's existence.** Fired by the ADR that decides the bounded fetch (#2096 item 1).
  Not fired by a lane finding a snippet thin.
- **A third `DestinationTrust` member.** Fired by an ADR with a policy that reads it. Not
  fired by a lane wanting a finer scale, which is inspection by another name.
- **A rolling window for §8's bounds**, in place of the flat per-conversation figure.
  Fired by §11's audit showing conversations exhausting their budget while still useful.
  Not fired by a lane finding a bound tight.
- **A monetary per-conversation bound**, and ADR-0194 §8's default ceiling (#2116). Fired
  by ADR-0194 §8's own trigger and by nothing else (§9).
- **A durable record of the query that left**, and the join from §11's audit to a search's
  content. ADR-0231 §19 defers it and this ADR inherits that deferral whole; the wider
  supply does not make a payload store owed.
- **A per-span externality fact on `Provenance`**, which would let §5's third condition be
  read per record rather than per turn. ADR-0098 §5 defers it on three grounds and this
  ADR takes none of them. Fired by the ADR that decides how this corpus records per-span
  origin at all.
- **Moving `search_max_results`, or a second search per servicing.** ADR-0231 §19's entry
  is untouched: this ADR widens what one query is composed over and how many servicings a
  conversation may have, and moves neither ceiling.
- **The surfaces that offer §1's act.** ADR-0193 §13's assignment (§14).
- **The two corpus findings this ADR reports rather than settles**: ADR-0223 §6's and
  ADR-0233 §9's disagreement about which clause of ADR-0181 §5 is the lineage floor
  (**#2137**); and ADR-0231 §4's second clause, whose "only instrument" sentence is spent
  now that ADR-0233 has landed (**#2138**). Each is fired by an ADR reconciling it; neither
  is repaired in this change, and neither is fired by a reviewer of this PR.

### 17. Scope, and what this records against earlier ADRs

> **Normative.** This ADR partially supersedes **five** ratified ADRs and amends none.
> ADR-0231 in five scopes, ADR-0233 in two, ADR-0155 in one, ADR-0181 in one and ADR-0193
> in **three** — §3's fifth comparison, §4's first clause and §6's eighth-check clause in
> one limb — each named on that ADR's `Status` line and in its appended dated note under
> ADR-0082 §1 and §2. **No other ADR's text moves**, and in particular ADR-0014, ADR-0074,
> ADR-0098, ADR-0106, ADR-0146, ADR-0148, ADR-0152, ADR-0154, ADR-0178, ADR-0184,
> ADR-0194, ADR-0204, ADR-0205, ADR-0212, ADR-0217, ADR-0223, ADR-0226, ADR-0228,
> ADR-0230, ADR-0235 and ADR-0236 are relied upon as written.

> **Normative.** **Four near misses are named, because each was a supersession an earlier
> draft of this ADR would have owed and each is avoided by a decision rather than by luck.**
> ADR-0152 §7's transcription count, by §5's default. ADR-0212 §8's and ADR-0014 §5's
> export version, and ADR-0074 §9's enumeration, by §8's own store. A lane that reverses any
> of those three decisions owes the record that decision avoids, and says so.

> **Normative.** **ADR-0231 §16 is relied upon and is not moved.** Nothing here retains a
> minted record, admits one to a store, an archive or a later turn, or leaves a hook for
> one; §2's third population is within a turn for exactly that reason, and §16's own
> sentence — "a second turn re-searches … because nothing was retained" — stays true.

> **Normative.** Additions this ADR makes that contradict no sentence an earlier ADR
> wrote are **stacked additions** under ADR-0082 §1 and are recorded here and nowhere
> else: §1's trust store and its establishing act, which no ADR forbids and ADR-0235's
> act does not contain; §8's two `Settings` fields; §10's cross-field refusal; and §11's
> two counts and one `SearchDisposition` member.

> **Normative.** On ADR-0231, ADR-0155 and ADR-0193, whose `Status` lines already lead
> with `Partially superseded by`, this ADR's pair is **appended** to the existing pairs on
> the same line under ADR-0070 §4's accumulation rule, and no existing pair is dropped or
> rewritten. On ADR-0233 and ADR-0181 the line takes the leading token and `Accepted` is
> dropped, as `docs/adr/template.md` requires. **No ratified sentence of any of the six is rewritten**, and no
> body text outside the header is touched.

### 18. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Each edit, with §1's test applied: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?

- **ADR-0231 §3's utterance-only clause** — yes. A reader would refuse a composer any
  record. Supersession.
- **ADR-0231 §4's first clause** — yes. A reader would refuse to supply a composer covered
  content at all. Supersession. **Its second clause** — yes. A reader would hold that no
  instrument but ADR-0233 may move ADR-0155 §3's third clause, and would refuse this ADR
  on that ground. Supersession.
- **ADR-0231 §12's second clause** — yes, and this is the property §4 above gives up.
  Supersession. **Its third clause** — yes; a reader would refuse every second search.
  Supersession.
- **ADR-0233 §9's first clause** — yes, in its exclusivity: a reader would hold the four
  conditions to be the only route. Supersession. **Its second clause** — yes; a reader
  would refuse any standing route to such a call. Supersession.
- **ADR-0155 §3's third clause** — yes; a reader would refuse the span. Supersession, and
  the second one this sentence has taken.
- **ADR-0181 §5's second clause** — yes; a reader would return no `ALLOW`. Supersession.
- **ADR-0193 §3's fifth comparison and §4's first clause** — yes on both; a reader would
  find no grant covering, and would hold route (a) to be the only route. Supersession.
- **ADR-0193 §6's eighth-check clause, in its seventh limb** — yes; a reader would refuse
  to record the `ALLOW` §6 above permits, and ADR-0231 §9's *"only on a recorded `ALLOW`"*
  would then stop the search anyway. Supersession. The other seven limbs, the
  `OriginUnrecordedBinding` arm, the ordering rule, the revocation rule and the digest
  recomputation are untouched.
- **ADR-0074 §9's enumeration, ADR-0212 §8's `Literal[2]`, ADR-0014 §5's version rule and
  ADR-0152 §7's transcription count** — **no**, on all four, and each is a near miss §17
  names. `ConversationTurn` and `Conversation` gain nothing, so the export's shape and
  version stand; and `rebind` transcribes nothing new, so §7's count stands. A reader of
  any of the four acts identically.
- **ADR-0223 §6** — **no.** Its clause requires the floor to apply for a stamped-episode
  cause exactly as for any other, and forbids an episode-shaped carve-out. §5's condition
  is cause-blind, so a reader of ADR-0223 acts identically. No record owed, and §16 files
  its clause-number discrepancy rather than editing it.
- **ADR-0193 §5, ADR-0154 §4, ADR-0148 §3, ADR-0217, ADR-0146 §2, ADR-0098 §5 and §6,
  ADR-0194 §1, §2 and §8, ADR-0231 §16, ADR-0152 §7 and ADR-0178 §6** — **no.** Each is
  used as written and §2, §5, §6, §7, §9, §12 and §13 state so in terms.
- **ADR-0181 §3 and ADR-0233 §4** — **no**, and they are the shape §5's binding fact is
  built to. Each puts one fact about a call on `EgressBinding` and `CarriedProvenance`,
  computed by the component that composed the arguments; §5 adds a third by the same
  construction and moves neither. A reader of either acts identically.

### 19. Marking, review and ratification

This ADR is **marked** under ADR-0089: every obligation it imposes is in a
`> **Normative.**` block quote, and unmarked prose determines what a marked clause means
and supplies no obligation of its own.

It changes `core/protocols.py` and `core/types.py`, so it owes **both** the adversarial
and the architecture review (ADR-0015 §1, ADR-0020 §2), and it is merged and ratified
before any lane implements against it (golden rule 5).

## Consequences

**Easier.**

- **"Find more about that" becomes answerable**, and a conversation that searched once
  may search again. That is the whole of milestone 31 and the reason for every cost below.
- **One rule covers two milestones.** A destination is one the user chose or one nobody
  chose, and milestone 32 reads the same fact rather than drawing a second boundary.
- **The exclusion question has an answer that already exists.** `Placement` is the user's
  own act, already on every record, already narrowable only downward by a model.
- **The budget is visible.** Calls and elapsed time per conversation are recorded on the
  turn row and reported in counts, so "how much did the loop search" is answerable from
  the audit rather than from a guess.
- **#2126's trap is closed before anyone falls into it**, by a refusal at load rather than
  a `SpendUndeterminedError` on the second search of a period.

**Harder.**

- **A structural property is gone and cannot be recovered by a later lane.** "No byte of a
  search result can reach a later search request" was decidable from two contracts. What
  replaces it is decidable from recorded facts, which is weaker, and §4 says so rather
  than dressing it up. Anyone reading this corpus for its exfiltration story reads §4.
- **The corpus's largest standing prohibition has now been relaxed twice.** ADR-0155 §3's
  third clause took its first exception on 2026-09-04 and its second here, and both rest on
  owner rulings. A third would want a reason better than "there are already two".
- **A long conversation runs out of searches.** The bound is flat per conversation, so a
  conversation used for a week stops searching and the remedy is a new one. §16 defers the
  rolling window with its trigger; until then this is a real product edge.
- **Two user acts where there was one.** A deployment reaching `USER_CHOSEN` needs a grant
  *and* a trust record, and the surfaces for both are other lanes'. Until they land the
  mechanism is inert, and a user who performs only the first gets the old behaviour with no
  explanation — which is ADR-0231 §19's "telling the user a search was refused" deferral,
  inherited and now costing more.
- **Two new stores, and two triads for one implementing lane.** Destination trust and the
  search budget are each small and each genuinely new, but a lane owing two Protocols, two
  conformance suites and two canonical fakes beside a composer change and a binding field is
  a large lane, and the batch that briefs it should expect that.
- **A conversation's budget is spent optimistically and settles down, never up.** A turn
  that dies after claiming leaves its full deadline charged, so an unlucky conversation
  searches slightly less than its bound would allow. That is the fail-closed direction and
  it is the price of not writing twice per call.
- **A result's content is lost with the turn that read it.** ADR-0231 §16 stands:
  refinement over raw results is a within-turn capability, and a later turn works from the
  captured episode. The honest mechanism is narrower than the milestone's sentence sounds,
  and it is stated rather than engineered around.
- **`EgressBinding` now carries three facts about a call's origin and coverage.**
  `planned_with_external_content`, `coverage` and `closed_loop` are each required, each
  written by the component that composed the arguments, and each compared through `rebind`
  and `authorises`. That is a coherent set today; a fourth would be worth asking whether
  the binding wants one value rather than three flags.

**Revisit when** §11's audit shows what conversations actually draw — which decides the
rolling window and the two defaults together — or when milestone 32's ADR needs a third
`DestinationTrust` member, or if an injection benchmark arm (#2096 item 9) is ever built,
since it is the instrument that would tell anyone whether §4's trade was priced correctly.

## Alternatives considered

**Widen ADR-0233 §9's four conditions instead of adding a second exception.** Refused: §9
states its conditions as a conjunction precisely so that removing one removes the ground,
and admitting a standing route into condition 2 would have reached every model-composed
span in the corpus rather than one kind at one destination class.

**Carry destination trust as a field on `RecipientGrant`.** Refused for two independent
reasons in §1: a destination nobody chose has no grant to carry it, so milestone 32 could
not read it; and ADR-0193 §5's "a grant reaches the recipient and never the payload" is
correct, so deriving a payload permission from a recipient grant is ADR-0097 §7's shape.
The cost of refusing it is a Protocol triad the implementing lane owes.

**Carve the ADR-0181 §5 exception directly — "except where the external content is a
search result".** Refused: it breaches ADR-0223 §6's no-episode-shaped-carve-out clause on
one reading, it admits a result from an `UNCHOSEN` destination, and it is undecidable on
today's one-bit stamp, which cannot say what an earlier turn's externality was. §5's
three-fact condition is what makes the sentence checkable.

**Make a closed-loop request's binding carry `planned_with_external_content` as false.**
Refused outright, and named here because it is the shortcut a later lane will reach for. It
is forbidden in terms by ADR-0231 §12's fourth clause and ADR-0223 §6's second clause, it
breaches ADR-0106 §4's monotonicity, and it would put a false statement in a record the
whole authorisation story rests on.

**Bound the budget per turn instead of per conversation, avoiding a durable accumulator.**
Refused: the loop is already bounded at two servicings per turn (ADR-0228 §3), so a per-turn
bound adds nothing, and the milestone's exit is stated over a conversation that "continues
within an enforced budget". A bound a process restart resets is not enforced.

**Keep the composer's `str` parameter and add a second one for the supply.** Refused: it
puts the bound back in the caller's hands, where a conforming implementation and a
defective one are indistinguishable from the signature. One validating value is where a
reviewer can check it once.

**Report a figure on a completed search so the period stays determinate.** Refused in §10:
it crosses ADR-0194 §2's estimate/reported boundary and substitutes a figure nobody
measured, which that clause's no-stand-in rule refuses. The allowance is the mechanism the
corpus already has for a reported `UNKNOWN`.
