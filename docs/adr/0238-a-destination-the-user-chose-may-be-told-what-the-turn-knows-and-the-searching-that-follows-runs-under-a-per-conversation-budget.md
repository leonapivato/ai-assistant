# 238. A destination the user chose may be told what the turn knows, and the searching that follows runs under a per-conversation budget

- Status: Proposed
- Date: 2026-09-05
- **Partially supersedes** [ADR-0231](0231-the-planner-asks-for-a-search-the-turns-own-words-compose-it-and-the-results-come-back-as-records.md)
  — **§3's utterance-only clause, §4's first and second clauses, §12's second and
  third clauses, and §13's closure of `SearchDisposition` at exactly fifteen members
  in that count alone.** Those six, and nothing else in that ADR.
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
> **`DestinationTrustStore`**, with exactly **five** members and no more: **`record`**,
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
> halves are stated in the clause below); and **this request holds a claim §8's store
> granted for this call**. A request
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

> **Normative.** **The fourth condition is a claim already held, never capacity still
> unspent.** `claim` charges the call it admits (§8), so by the time the request is built
> the draw no longer has room for it — a condition reading "the draw leaves room for one
> more call" would therefore be false for **every** admitted request, and false first for
> the last call a conversation is allowed. The order is fixed for that reason: **claim,
> then compose, then build the request, then bind, then rule, then send.** A servicing that
> did not claim composes nothing, so no request lacking a claim ever reaches the fourth
> condition at all.

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
> **required with no default**, false once any turn of this conversation has carried a
> recorded external span that was **not** minted by a `WEB_SEARCH` servicing at a
> destination of recorded trust `USER_CHOSEN`.

> **Normative.** **The field is required with no default, and that is the structural half of
> §5's legacy refusal.** A default of `True` would be a creation default: whichever store
> member first touched an unknown conversation would mint a clean-history row, and §5's
> recorded half — which reads the stored flag wherever a row exists — would then accept a
> legacy conversation whose prior turns this decision had never seen. **No member of this
> store creates a row carrying a flag its caller did not supply**, so that path does not
> exist rather than being forbidden.

> **Normative.** `core/protocols.py` gains **one** further `@runtime_checkable` Protocol,
> **`SearchBudgetStore`**, keyed by conversation, with exactly **seven** members:
> **`draw_of`**, answering a conversation's `ConversationSearchDraw` **or `None` where it
> holds no row for that conversation and where the row it holds is stamped deleted**;
> **`claim`**; **`settle`**; **`observe`**, folding the value its caller computed into the
> stored flag by logical **and**, creating the row where none exists; **`forget`**,
> **stamping** a conversation's row deleted and creating that stamp where no row exists;
> **`budgeted_conversation_ids`**, the bounded cursor-paged walk over every conversation
> this store holds a row for; and **`drop`**, removing one conversation's row entirely. An
> eighth member is added by no lane without the ADR that decides it.

> **Normative.** The seven members are declared with exactly these signatures, all `async`:
>
> - `draw_of(self, conversation_id: Identifier, /) -> ConversationSearchDraw | None`
> - `claim(self, conversation_id: Identifier, /, *, max_calls: int, max_elapsed: timedelta, initial_footing: bool) -> SearchClaim | None`
> - `settle(self, claim: SearchClaim, /, *, elapsed: timedelta) -> None`
> - `observe(self, conversation_id: Identifier, /, *, all_external_user_chosen: bool) -> None`
> - `forget(self, conversation_id: Identifier, /) -> None`
> - `budgeted_conversation_ids(self, /, *, limit: int | None = None, after_id: Identifier | None = None) -> list[Identifier]`
> - `drop(self, conversation_id: Identifier, /) -> None`
>
> `claim` answers `None` where it refuses. The bounds are **passed in** rather than read by
> the store, so the store holds no `Settings`, no clock and no policy — it is a counter with
> an exclusion, and every judgement about what a bound is stays in `orchestration`.

> **Normative.** **`initial_footing` is used only where `claim` creates the row, and is
> ignored where one exists** — the stored flag is authoritative and monotone, and no
> argument raises it. `orchestration` supplies the **history-only** component and that
> alone: whether this conversation had **no recorded turn before this one**. So a legacy
> conversation's row is created `False` by the very call that charges its first search, and
> §5's recorded half refuses that search rather than the one after it.

> **Normative.** **`initial_footing` is *not* the value `observe` receives, and no lane
> reads the two as one argument.** `observe` takes the **conjunction** of that history fact
> with the completed turn's **own** external-origin result (below); `claim` takes the
> history fact by itself, because the turn's own result does not exist when `claim` runs —
> **claim precedes composition, servicing and capture** (§5's fixed order). So a turn
> admitted on a true footing whose own supply then proves dirty is closed by `observe` and
> never by `claim`, and a lane that passes the conjunction to `claim` would be passing a
> value it cannot yet compute.

> **Normative.** **The claim, the charge and the row's creation are one indivisible step.**
> No implementation reads, decides, creates and charges as separate awaits, and none creates
> a row in one operation and sets its flag in another.

> **Normative.** **The provisional charge is the whole remainder, and three things follow
> from that one choice.** First, **`orchestration` never needs to know the transport's
> timeout**: that value is `WebSearchEgress`'s own state inside the seam, it is on no
> Protocol and in no `Settings` field this ADR adds, and reaching for it would cross golden
> rule 1. Second, **at most one claim of a conversation is outstanding at a time** — while
> one is in flight the stored `elapsed` equals the bound, so the next `claim` refuses — which
> serialises searching per conversation without a lock anywhere. Third, the overrun is
> therefore **one call's**, and §8 can say so truthfully.

> **Normative.** **So the settled total may exceed the bound by at most one call's excess
> over the remainder it was granted, and by no more.** No lane states a bound on the size of
> that one excess — the accounted interval includes ADR-0192's unbounded ledger writes — but
> **no lane states that two calls can overrun**, because two cannot be outstanding.

> **Normative.** `core/types.py` gains **`SearchClaim`**, a frozen model refusing unknown
> fields, with exactly three fields: `conversation_id: Identifier`, `id: Identifier` minted
> by the store, and `charge: timedelta`, the provisional amount this claim added. **At most
> one claim of a conversation is outstanding at a time** (above), so the handle is not there
> to disambiguate concurrent claims; it is there so that `settle` can be **idempotent and
> stale-safe**. A second `settle` of one claim changes nothing; a `settle` naming a claim the
> store has already settled, or one whose conversation has been forgotten, changes nothing;
> and a `settle` naming a conversation alone could not tell a late settlement of a
> superseded claim from a settlement of the claim now outstanding. `settle` replaces the
> charge of **that** claim and no other.

> **Normative.** **`forget` is the lifecycle member, it is a *stamp* and not a drop, and it
> is idempotent.** It stamps one conversation's row deleted — **creating that stamp where
> the store holds no row at all**, because a stamp on nothing is exactly what makes a later
> observation unable to create one — answers the same whether a row was there or not, and is
> safe to call again after a partial failure, which is what a sweep that may be interrupted
> and re-run needs (ADR-0074 §7, §8).

> **Normative.** **The stamp is `ConversationStore.stamp_deleted`'s shape, taken from the
> corpus rather than invented here.** That member is durable, "hides the conversation from
> every presenting read, and **refuses every later append**, so a capture racing the deletion
> cannot slip a turn in behind it", and "what the stamp does *not* do is remove anything".
> This store's stamp does the same three things to its own row: it is durable, `draw_of`
> answers `None` for a stamped conversation, and every later `claim` and `observe` is
> refused. **A check-then-act across two stores could not do it.** Reading from one store
> that a conversation exists and then writing to another is a decision taken before `forget`
> lands and acted on after; this section contemplates **two engines over one data
> directory**, so no
> in-process ordering closes that gap, and a correctness argument that depends on it is one
> this ADR declines to state. The stamp closes it because the refusal and the row are one
> object under this store's own per-conversation exclusion.

> **Normative.** **`claim` and `observe` are decided against the stamp inside the store,
> atomically, and neither creates anything for a stamped conversation.** `claim` on a
> stamped conversation **refuses**, answering `None` exactly as it does at an exhausted
> bound, so the servicing takes this section's no-slot posture and composes nothing.
> `observe` on a stamped conversation is a **no-op that raises nothing**: it folds nothing,
> creates nothing and reports nothing to its caller — a fold arriving after a deletion has
> nothing left to be true of, and raising would break a servicing that was already in flight
> when the deletion landed. `settle` is unchanged and was already this shape. **No member
> consults the `ConversationStore`, and none is passed a value its caller read from one**:
> the stamp is the whole of the test, and it is read in the same indivisible step as the
> write it guards.

> **Normative.** **`forget` invalidates every outstanding claim of that conversation, and
> settling one afterwards is a no-op that creates nothing.** A user may delete a
> conversation while one of its searches is still in flight; the claim then names a row that
> is stamped, or one already dropped, and `settle` **must revive neither** — a deleted
> conversation leaving spendable budget state behind would breach this section's
> row-goes-with-the-conversation clause and ADR-0074 §8's deletion. `settle` on an unknown
> conversation, on a stamped one, on a forgotten claim, or on a claim already settled
> changes nothing and raises nothing, so the servicing that was in flight completes and
> reports normally.

> **Normative.** **`claim` is one atomic step: admit, charge, and answer the deadline.**
> Given a conversation and the two bounds, it refuses where the stored `calls` have reached
> `search_calls_per_conversation` or the stored `elapsed` has reached
> `search_elapsed_per_conversation`; otherwise it increments `calls` by one and charges to
> `elapsed` **the conversation's whole remaining elapsed budget**, which `settle` then
> replaces with what the call actually took, releasing the remainder. **The read, the
> comparison and the write are one indivisible step.** That is `RecipientGrantStore`'s
> atomic count-with-append (ADR-0193 §1) applied to a counter, and it is why concurrent
> turns, a failed turn and a process exit are answered by one clause rather than three:
> **two turns of one conversation, two servicings of one turn, and two engines over one
> data directory can none of them be admitted against the same draw.**

> **Normative.** **`settle` replaces that claim's provisional charge with the interval the
> claim actually occupied, whether that is smaller or larger.** There is no direction rule:
> a settlement that could only lower would let a call that overran its charge cost the
> conversation nothing, which is the wrong direction for a bound. **The accounted interval
> is the one `orchestration` can measure — its own await of the search servicing**, from
> before the seam is entered to after it returns. `settle` changes no `calls`, and **a claim
> that is never settled stands at its full charge** — the fail-closed direction, and the
> reason nothing is owed for a turn that ends in an exception, a `PlanningError` on a later
> revision, a restart or a disconnection.

> **Normative.** **The interval is `orchestration`'s await and not the provider exchange,
> because the exchange's duration is a fact no contract reports.** `SearchOutcome` carries no
> elapsed value and `WebSearcher` is not widened here to add one, so the only honest quantity
> is the one the caller holds. It includes ADR-0192's ledger claim and completion writes,
> which that ADR left unbounded when it superseded ADR-0029 §4's reach — **so no lane states
> that a call's accounted time is bounded by the transport's timeout**, and §16 defers
> bounding it with what fires that.

> **Normative.** **A claimed call is consumed whatever the outcome, and there is no
> refund.** A servicing that claims and then does not transmit — a binding that refused, a
> ruling that was not `ALLOW`, a provider that rejected before or after receiving the query
> — still spends its `calls` increment. **`SearchOutcome` carries no transmission fact** and
> `WebSearcher` is not widened here to add one, so a refund rule would oblige the servicer
> to tell two `SearchRefusal.PROVIDER_REFUSED` outcomes apart when nothing in the contract
> distinguishes them. Conservative admission is the honest reading, and it errs toward
> searching less.

> **Normative.** **The elapsed bound is a start-only bound with a stated overrun, and
> `WebSearcher` is not widened to carry a deadline.** A call is admitted only while the
> stored `elapsed` is **strictly below** the bound; once admitted it runs under the
> transport's own timeout, which ADR-0231 §6 and ADR-0029 §4 already place inside the seam
> and which `WebSearcher.search(call, /)` takes no parameter to override. That is ADR-0228
> §4's shape — a bound checked at the start of an operation rather than enforced mid-flight.

> **Normative.** **No call is admitted once the stored `elapsed` has reached the bound**,
> and while a claim is outstanding the stored value *is* the bound. The excess is the one
> stated above, and no lane claims a size for it.

> **Normative.** **No lane closes the overrun by adding a timeout parameter to
> `WebSearcher.search`, by wrapping the seam in a cancellation outside it, or by having
> `orchestration` time the call and abandon it.** ADR-0029 §4 puts the timeout inside the
> implementation and ADR-0231 §6 keeps it there; a caller-imposed cancellation would be a
> second timeout in a second place, which is the shape this corpus has already refused.
> Firing the overrun open is an ADR deciding how a deadline reaches that seam at all.

> **Normative.** **The flag means two things at once, and `orchestration` computes both.**
> It means *every turn this decision has observed was clean* **and** *this decision has
> observed every turn this conversation has had*. For every turn it captures,
> `orchestration` calls `observe` with the conjunction of: whether **every** recorded
> external span that turn's final supply carried was minted by a `WEB_SEARCH` servicing at a
> destination of recorded trust `USER_CHOSEN` — computed from records it holds as data it
> fetched, at the same instant and by the same component as ADR-0223 §1's own value; **and**,
> where the store holds no row for this conversation yet, whether the conversation had **no
> recorded turn before this one**.

> **Normative.** **The early fold is triggered by admission and not by a request: the
> moment `orchestration` admits to a turn a recorded external span that was **not** minted
> by a `WEB_SEARCH` servicing at a destination of recorded trust `USER_CHOSEN`, it calls
> `observe` with `False` for that conversation.** The trigger is that admission — the same
> fact §5's current-turn half is stated over — and it fires **whether or not that turn ever
> builds a `WEB_SEARCH` request**. **Capture's fold remains and is unchanged**; this one is
> earlier, not instead, and the two agree because `observe` folds by **and**.

> **Normative.** **Admission is the trigger because neither a request nor a capture is
> early enough.** §5's current-turn half is computed when a request is **built**, so a turn
> that reads a local file and never searches computes it nowhere, and a turn that reads one
> and *does* search computes it only after `claim` has already admitted that call. Both
> leave the stored flag true for as long as the turn is in flight, and `settle` releases the
> draw inside that window — so a **second servicing of the same conversation** could claim,
> read the stale-true flag, find its own supply clean and be ruled closed-loop, although the
> conversation had already carried the file. Folding at admission puts the false in the row
> **as early as the fact exists**, which narrows that window from the whole of a turn to a
> single store write — and the two clauses below state exactly what that does and does not
> guarantee.

> **Normative.** **What the early fold guarantees is a boundary, not an ordering.** The
> guarantee is this and no more: **every claim of that conversation admitted after the fold
> has returned reads the false**, because the flag is monotone and `claim` reads it in the
> same indivisible step that charges the draw. **No clause here claims more.**
> `orchestration` cannot fold a fact before it holds it, and admission is the instant it
> holds it, so a claim concurrent with that single `observe` await can still be admitted on
> a flag the fold has not yet lowered. **Nothing in this decision serialises two turns of
> one conversation**: `claim`'s atomicity serialises the *draw* and not the flag, and this
> section's own two-engines case makes an in-process ordering unavailable in principle.
> **A lane that reads "before any later claim" as an ordering obligation on the caller has
> misread this section** — there is no such obligation here, and none would be
> dischargeable.

> **Normative.** **The window it leaves is stated rather than claimed away.** Before the
> early fold it spanned turn A's whole composition, servicing, transport and capture — every
> await of a search — and `settle` released the draw inside it. After it, it is one store
> write with none of turn A's I/O inside it. What it costs when it is reached is **one
> search of one concurrent turn** ruled closed-loop on a conversation that had, at that
> instant, admitted a disqualifying span it had not yet recorded; the conversation is closed
> for every claim admitted after the fold returns, and §11's audit records both dispositions.
> **Closing it entirely means serialising servicings of one conversation**, which is a new
> obligation on `orchestration` across concurrent turns that nothing in this corpus provides
> today; §16 defers it with what fires it, and **no lane closes it by having `orchestration`
> hold a lock**, for the reason ADR-0074 §8 gives about exactly that shape — two engines
> hold two locks and serialise nothing.

> **Normative.** **A half that reads *true* is never folded early.** Reporting a turn
> **clean** stays capture's alone, because only capture sees the turn's **final** supply; an
> early true would report a turn clean before it had finished carrying things, which is the
> direction this section fails closed in everywhere else. The early fold writes `False` and
> nothing else, it is idempotent, and repeating it costs nothing.

> **Normative.** **A fold reaching this store after `forget` is expected, and the stamp is
> what makes it harmless.** `observe` creates a row where none exists (above), so an
> observation racing a deletion would otherwise resurrect budget state for a conversation
> ADR-0074 §8 has destroyed — the hazard `settle` is already fenced against, now fenced the
> same way. **The fence is the stamp and nothing else.** In particular **no clause obliges
> `orchestration` to fold only for a conversation whose record the `ConversationStore` still
> holds**: that is a read of one store used to license a write to another, it can be true
> when it is read and false when the write lands, and it is unavailable in principle under
> this section's two engines. **A lane that finds a fold reaching this store after `forget`
> has found the case this clause is written for, not a breach of it** — what it must find,
> and what §15's arms assert, is that the fold created nothing.

> **Normative.** **So a row created for a conversation that already had turns is created
> false**, and the refusal §5's recorded half makes for an unobserved legacy conversation
> survives the row's creation. Without the second conjunct, one clean turn of a legacy
> conversation whose tainting episode had expired would mint a `True` row and the prior-turn
> test would never run again — the same hole a `None`-means-true reading opens, arriving one
> turn later.

> **Normative.** **Once false the flag never returns to true**, which is ADR-0106 §4's
> monotonicity read on this axis, and it is what keeps a conversation closed after the
> tainting episode has fallen out of the tail (ADR-0223 §6's un-tainting, which this ADR does
> not disturb). `observe` folds by **and** and by no other operation; no lane adds a member,
> a flag or a repair that raises it.

> **Normative.** **Absence of a row is not evidence of a clean history, and §5's recorded
> half says so in terms.** That half is satisfied where `draw_of` answers a row whose
> `all_external_user_chosen` is **true**, **or** where `draw_of` answers `None` **and** the
> `ConversationStore` holds no recorded turn of that conversation before this one. It is
> **not** satisfied by `None` alone. A conversation with no prior turn cannot have a history
> to hide, which is why the first limb of the disjunction is vacuous truth rather than a
> guess; a conversation that has turns and no row is one this decision has never observed,
> and it fails.

> **Normative.** **A stamped conversation reads as `None` here too, and that is fail-closed
> in both branches.** One with recorded turns fails the recorded half outright, on the
> clause above. One with none — a conversation stamped before it ever took a turn — would
> satisfy the recorded half vacuously, and it reaches nothing: `claim` refuses for a stamped
> conversation before a supply is constructed or a query composed, so no request of a
> deleted conversation is ever ruled on. **No lane closes that by making `draw_of` present
> the stamp**; hiding a stamped row from every presenting read is what makes it
> `ConversationStore.stamp_deleted`'s shape rather than a sixth state for §5 to read.

> **Normative.** **This is what closes a legacy conversation whose stamped episode is
> gone.** A conversation that read a file before this decision landed may, by the time of
> its next turn, have lost that episode — expired under ADR-0007 §2, deleted, or simply
> fallen out of the tail (ADR-0223 §6's own un-tainting, which ADR-0231 §12 records) — and
> `ConversationLifecycle.history` skips a turn whose episode does not resolve. Its current
> turn's supply can therefore be clean. **The prior-turn test is what refuses it**, and no
> later clean capture rescues it: `observe` folds by **and** onto a row that, once created,
> records what this decision has actually seen.

> **Normative.** **The store is local, durable and never written to a remote service**
> (ADR-0004 §2), it holds a Tier 1 fact, it ships as a **triad**, and it holds **two
> counters, one flag, one deletion stamp and no content** — no query, no result, no
> destination, no record, no text.

> **Normative.** **A conversation's row goes when the conversation goes, and the removal is
> driven by a walk rather than by an ordering between two stores.** The capture/lifecycle
> stage in `orchestration` owns both halves, because ADR-0074 §9 already rules that "the
> **capture/lifecycle stage in `orchestration`** owns every cross-store sequence".
>
> - **The fence, in ADR-0074 §8's deletion.** `forget` runs **immediately after
>   `ConversationStore.stamp_deleted` succeeds** and before any episode is destroyed. That
>   order is normative and not an implementer's choice: the budget stamp is only ever
>   written for a conversation already stamped, so a process that dies between the two can
>   never leave a **stamped budget row on a live conversation** — a state nothing would
>   repair and which would silently end that conversation's searching for good. A death the
>   other way round leaves a stamped conversation with an unstamped row, which
>   `ConversationStore.stamped_conversation_ids` (ADR-0076) makes discoverable and which the
>   reclaim's re-run repairs, `forget` being idempotent.
> - **ADR-0074 §7's retention reclaim is not extended at all.** It calls `drop_if_eligible`
>   exactly as it does today and says nothing to this store, so **no crash window is opened
>   between a conversation's destruction and its row's removal** — there is no such
>   sequence to interrupt. The row of a reclaimed conversation is removed by the walk below,
>   like every other row whose conversation is gone.
>
> **No step of either sequence removes a row**, which is what keeps both re-runnable in
> ADR-0074 §8's sense: every member either stamps or is idempotent, and a repeat after a
> crash at any point converges on the same state.

> **Normative.** **`budgeted_conversation_ids` is the recovery read, and it is ADR-0076's
> read applied to this store.** ADR-0076 exists because "a process that died between the
> stamp and the drop left work **no later run could rediscover**", making "the residue §8's
> grace and reclaim exist to reclaim … permanent by the absence of a way to enumerate it".
> A store whose rows are removed by a cross-store sequence has exactly that defect and needs
> exactly that remedy. So this store owes an enumeration, in ADR-0076's shape member for
> member: **ids and nothing else** — no draw, no flag, no stamp instant, because the pass
> needs an id and nothing more, and a value-returning read would be a resurrection of
> exactly what the stamp hides; **`id` ascending with the cursor placed lexically
> and not by looking the row up**, which is a correctness requirement here for ADR-0076's
> own reason — this walk's rows are removed by the very sweep walking them, so an id naming
> no row is a perfectly good cursor and is not an error; **reading removes nothing**, so a
> resumed walk is as safe as a restarted one; and a **bounded batch**, `limit` defaulting to
> the store's configured **100**, the figure ADR-0076's walk already uses, a fixed figure
> and not a `Settings` field. It yields **every** conversation this store holds a row for,
> stamped or not, because the row a retention reclaim leaves behind was never stamped.

> **Normative.** **`drop` removes one conversation's row entirely, stamped or not, and the
> reconciliation is its only caller.** It is idempotent and answers the same on a
> conversation the store holds no row for. **The lifecycle stage calls it for one reason
> only: the walk yielded an id for which the `ConversationStore` holds no record at all.**
> The reconciliation is the same sweep ADR-0074 §8 already runs — in the deleting call, at
> engine start, and later on the hub's schedule — extended by one pass that drains
> `budgeted_conversation_ids` to an empty batch and drops what no conversation claims. Like
> every other part of that sweep it is idempotent, resumable and re-runnable.

> **Normative.** **This cross-store read is admissible where §8's earlier one was not, and
> the difference is stated rather than assumed.** The read this section refuses is one that
> **licenses a write creating state at a servicing site**, where a stale answer becomes a
> wrong ruling and where two engines make the ordering unavailable. This one licenses a
> **removal, in the lifecycle stage ADR-0074 §9 already gives every cross-store sequence**,
> and its staleness is one-directional and harmless in both directions. A conversation
> record is never resurrected — ids are opaque and minted per conversation (ADR-0074 §1) —
> so "no record" cannot become "a record", and a row dropped on that answer was never a live
> conversation's. And where the answer is stale the *other* way, the row is simply kept and
> reconsidered on the next pass. **A lane that reads this clause as re-admitting the fence
> §8 removed has misread it**: nothing here is consulted by `claim`, by `observe`, or by any
> path that decides whether a search may be serviced.

> **Normative.** **The residue is bounded by the sweep, which is ADR-0074 §8's own bound
> for the same class of thing.** Between a conversation's destruction and the next
> reconciliation pass, this store holds that conversation's row — **two counters, one flag
> and a stamp; no query, no result, no destination, no record and no text**. That is
> strictly less than the tombstone ADR-0074 §8 already accepts for the same interval,
> "ordinals, timestamps and episode ids — **no content** — surviving a deletion the user was
> told succeeded", and it is bounded the same way: by a sweep that runs in the deleting call,
> at start-up and on the hub's schedule. ADR-0074 §8 names an *unbounded* version of this
> the "content-free-but-real residue" it bounds, and **bounded is the whole of what makes it
> permissible**. ADR-0126's destruction of the cold data directory removes the store with
> everything else.

> **Normative.** **The walk is also what closes the window a fold suspended past a deletion
> would otherwise leave open.** A fold that commits after both the stamp and the record are
> gone creates a row for a conversation that no longer exists — ADR-0074 §8's orphaned-write
> shape, which that section accepts permanently for an episode because nothing can
> enumerate what to sweep. Here something can: the next reconciliation pass yields that id,
> finds no record, and drops it. **So this store's version of that window is bounded by one
> sweep rather than accepted for good**, and the ADR claims exactly that and no more — a row
> created after the last pass stands until the next one, and a system whose sweep never runs
> again keeps it, which is the same condition under which ADR-0074's own tombstones persist.

> **Normative.** This ADR adds **one call** to ADR-0074 §8's deletion and **nothing** to
> §7's reclaim, changing the shape of neither, and **`ConversationStore` gains no member,
> `Conversation` and `ConversationTurn` gain no field, and `ConversationExport` does not
> change shape or version** — the walk this decision needs is the one ADR-0076 already put
> on that store, read rather than widened.

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

> **Normative.** **`SearchDisposition` gains exactly one member and is closed at
> sixteen**, recording that a servicing did not reach a query because `claim` refused. It is
> not free text, it collapses with no existing member, the mapping from each refusal
> vocabulary stays **injective**, and it lives in `ai_assistant.orchestration` beside the
> rest of that enumeration, which crosses no subsystem boundary. **This supersedes ADR-0231
> §13's closure of that enumeration at exactly fifteen**, in that clause's count alone: the
> fifteen members it names, their values, their injective mapping, the no-message rule on
> `BINDING_FAILED` and `RULING_UNAVAILABLE`, and its exclusion of `SearchRefusal.NO_RESULT`
> all stand entire, and no lane reads this as licence to add a seventeenth.

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
> increments atomically before a channel opens. **`settle` writes a clock reading
> `orchestration` took, not a value anything else produced** — and a provider that stalled
> to inflate it would only spend the conversation's budget faster, which is the fail-closed
> direction. No value a model produced, a request carried or a search result contained
> reaches either side of the comparison.
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
> `ConversationSearchDraw` and `SearchClaim` as new types, and one member on each of `EgressBinding` and
> `CarriedProvenance` (`closed_loop`, defaulting to `False`). In `core/protocols.py`: two
> new `@runtime_checkable` Protocols, `DestinationTrustStore` with its five members and
> `SearchBudgetStore` with its seven, and the changed parameter type on
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

> **Normative.** **A conversation §8's store holds no row for reads a zero draw and no flag
> at all** — `draw_of` answers `None` — and §5's recorded half is then satisfied only where
> that conversation has no recorded turn before this one. No lane back-fills a row, infers
> one, reconstructs one from an episode, a log or a trail, or reads a missing row as a clean
> history.

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

> **Normative.** **That suite also asserts the stamp, because the stamp is the whole of §8's
> deletion fence and an implementation that merely dropped the row would pass every other
> assertion in it.** After `forget`: `draw_of` answers `None`; `claim` answers `None`;
> `observe` raises nothing and leaves `draw_of` answering `None`; a second `forget` changes
> nothing; and `forget` on a conversation the store never held leaves a state in which
> `observe` still creates no row — the arm that separates a stamp from a drop. And after
> `drop`: the row is gone, `draw_of` answers `None`, a second `drop` changes nothing, and
> `observe` **creates a row again**, because `drop` removes the stamp with the row and the
> conversation it named is gone.

> **Normative.** **The suite asserts `budgeted_conversation_ids` as a walk, in the shape
> ADR-0076's own conformance already takes**: it yields every id the store holds a row for,
> stamped and unstamped alike; it is `id` ascending; an `after_id` naming **no row** is a
> valid cursor and not an error; `limit` of `0` answers an empty batch; reading removes
> nothing; and a walk interleaved with `drop` of the ids it has already yielded still drains
> to an empty batch without skipping an id it had not yet reached. That last arm is the one
> the sweep's real shape needs and the one a lookup-placed cursor fails.

> **Normative.** **The lane wires the reconciliation pass into the sweep that already
> exists**, and does not add a second scheduler, a background task or a `Settings` field for
> an interval. ADR-0074 §8's reclaim already runs in the deleting call, at engine start and
> on the hub's schedule; §8's pass is one more step of it, draining
> `budgeted_conversation_ids` to an empty batch. **Draining is not optional**: finishing a
> batch and stopping is the failure ADR-0076 names for its own walk, and a pass that stops
> early leaves exactly the residue the walk was added to bound.

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

> **Normative.** **Arm 6c — the elapsed bound is start-only, with its overrun.** With
> `search_elapsed_per_conversation` at sixty seconds and fifty-nine already stored, one
> further call is admitted and the next is refused, whatever the admitted call's settled
> interval turns out to be, and no call is cancelled from outside the seam.

> **Normative.** **Arm 6c2 — one claim at a time, and settlement in both directions.**
> While a claim of a conversation is outstanding, a second `claim` for it is refused; after
> `settle` releases the unused remainder, a further claim is admitted. A claim settled
> **below** its charge returns the remainder; one settled **above** it raises the stored
> `elapsed` past the bound, and the next `claim` is then refused.

> **Normative.** **Arm 6c3 — `forget` under an outstanding claim.** A conversation deleted
> while one of its searches is in flight reads as no row afterwards — stamped when the
> deletion lands, then removed by the reconciliation pass; settling that claim revives
> neither, raises nothing, and the in-flight servicing completes and reports normally.

> **Normative.** **Arm 6c4 — no fold resurrects a deleted conversation, and the arm forces
> the interleaving rather than assuming it.** A conversation deleted between `claim` and the
> admission fold, and one deleted between its search returning and its capture, each leave
> **no row** afterwards: neither the admission fold, nor capture's fold, nor `settle`
> creates one, and `draw_of` answers `None` for both.

> **Normative.** **Arm 6c4b — the fold that a cross-store check would have licensed.** The
> arm drives the exact order the removed check-then-act would have got wrong: the fold's
> caller reads the conversation as **existing**, then `forget` lands, then the fold calls
> `observe`. **No row exists afterwards** and `draw_of` answers `None`. The same order is
> asserted for `claim` — read-exists, `forget`, `claim` — which answers `None` and charges
> nothing. Both are asserted on a conversation the store held **no row for** when `forget`
> ran, which is the case a drop could not fence and the stamp does.

> **Normative.** **Arm 6d — a claimed call is never refunded.** A servicing whose ruling is
> not `ALLOW`, one whose binding refused, and one whose provider answered
> `SearchRefusal.PROVIDER_REFUSED` each spend their `calls` increment, and no path lowers
> `calls`.

> **Normative.** **Arm 6e — the footing is monotone.** A conversation whose flag is false
> stays false when a later turn's supply carries nothing external at all, including after
> the tainting episode has fallen out of the tail.

> **Normative.** **Arm 6f — absence is not a clean history, and creating a row does not
> launder one.** A conversation with recorded turns and no budget row is not closed-loop,
> **including where its stamped episode no longer resolves and its current supply carries
> nothing external at all**; and after a clean turn of that conversation has been observed —
> which creates its row — it is **still** not closed-loop, because the row was created false.
> A conversation with no recorded prior turn and no row is closed-loop on the first two
> conditions. All three are asserted, because the middle one is the hole that opens one turn
> after the first is closed.

> **Normative.** **Arm 6f2 — a dirty turn closes the conversation at admission, not at
> capture, and closes it even when it never searches.** With
> `search_calls_per_conversation` above one, on a conversation whose destination reads
> `USER_CHOSEN` and whose row is true, in two shapes. **(i)** Turn A services a local-file
> read and then a `WEB_SEARCH`, so A's own request binds `closed_loop` false; a second
> servicing of that conversation, admitted **after A's claim is settled and before A is
> captured**, carries nothing external of its own and is **not** closed-loop. **(ii)** Turn
> A services a local-file read and **builds no search request at all**; a concurrent turn B
> claims and composes, and B is **not** closed-loop for the same reason. The stored flag is
> false in both, and A's later capture folds false again to no effect. **(iii) The window,
> asserted as the boundary §8 states and not as an ordering.** B's `claim` is admitted
> **while A's admission fold is still in flight** — the arm blocks inside `observe` and
> releases it, rather than sequencing the two calls and hoping — and B **is** admitted on
> the not-yet-lowered flag, which is the residual §8 names and this arm records so that it
> is a ratified property and not a surprise found later. The arm then asserts the guarantee
> that *is* made: once that `observe` has returned, the next `claim` of the conversation is
> admitted on a false flag and its request is **not** closed-loop.

> **Normative.** **Arm 6g — the last permitted call is usable.** With
> `search_calls_per_conversation` set to one, the admitted servicing's own request is
> closed-loop: the fourth condition reads the claim this request holds, not the capacity
> left after charging it. The same is asserted for the last second of the elapsed bound.

> **Normative.** **Arm 6h — `forget` stamps and the reconciliation clears.** A deleted
> conversation and a reclaimed one each leave **no row** once the reconciliation pass has
> run; `forget` answers the same on a second call and on a conversation that never had a
> row; `drop` answers the same on a second call and on a conversation that never had a row;
> and a conversation whose row is gone and whose turns are gone reads as a conversation with
> no recorded prior turn.

> **Normative.** **Arm 6h2 — the two sequences and the pass, in place.** ADR-0074 §8's
> deletion run whole, followed by a reconciliation pass, leaves no row. **§7's reclaim of an
> ineligible conversation** — `drop_if_eligible` answering `False` — leaves that
> conversation's row **exactly as it was**, flag and counters included, and its next search
> is admitted against it; **the pass leaves it alone too**, because the `ConversationStore`
> still holds its record. And a deletion interrupted after `stamp_deleted` and re-run leaves
> the same state as one that ran straight through, which is what ADR-0074 §8's
> re-runnability requires of the store this ADR adds to it.

> **Normative.** **Arm 6h3 — the three crash windows the walk exists for, each driven and
> each recovered.** **(i)** A retention reclaim whose `drop_if_eligible` answered `True`,
> after which the process dies: the row stands with no conversation, and **the next
> reconciliation pass removes it**. **(ii)** A deletion that dies after
> `ConversationStore.stamp_deleted` and before `forget`: the conversation is still
> enumerable through `stamped_conversation_ids`, the reclaim's re-run stamps the row, and
> the pass removes it once the record is dropped. **(iii)** A fold that commits after both
> the record and the row are gone, creating a row for a conversation that no longer exists:
> **the next pass removes that too.** Each arm asserts `budgeted_conversation_ids` yields
> the stranded id and that `draw_of` answers `None` afterwards.

> **Normative.** **Arm 6h4 — a stamped row is never left on a live conversation.** The arm
> drives a deletion that dies **between** `stamp_deleted` and `forget` and asserts the
> conversation's row is **not** stamped; and it asserts that no path in either sequence
> calls `forget` for a conversation the `ConversationStore` does not hold stamped. That is
> the state nothing repairs — a live conversation whose searching is silently over — and
> the ordering in §8 is what makes it unreachable.

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
- **Bounding a search's accounted interval.** §8 accounts `orchestration`'s own await,
  which includes ADR-0192's ledger claim and completion writes — unbounded since that ADR
  superseded ADR-0029 §4's reach. Fired by an ADR bounding those writes, or by one deciding
  how a deadline reaches `WebSearcher.search` at all. Not fired by a lane finding one
  conversation's overrun large.
- **Serialising servicings of one conversation**, which is what would close §8's stated
  window between an admission fold and a concurrent turn's `claim`. Fired by an ADR that
  gives `orchestration` a per-conversation ordering across concurrent turns and holds it
  across two engines — a store-level obligation in ADR-0074 §9's shape, not a lock, which
  §8 records as answering nothing. Not fired by a lane finding the window narrow, and not
  by one finding it wide.
- **Removing the residue *between* reconciliation passes**, rather than bounding it by
  one. §8's walk drops a stranded row on the next pass; what it does not do is make the
  destruction of a conversation and the removal of its row one act. ADR-0074 §8 names what
  would — "a transactional posture across the local stores, which is leg 5's 'stores'
  concurrent-access posture' hardening tail" — and this ADR inherits that entry rather than
  opening a second one. Not fired by a lane finding a sweep interval long.
- **The surfaces that offer §1's act.** ADR-0193 §13's assignment (§14).
- **The two corpus findings this ADR reports rather than settles**: ADR-0223 §6's and
  ADR-0233 §9's disagreement about which clause of ADR-0181 §5 is the lineage floor
  (**#2137**); and ADR-0231 §4's second clause, whose "only instrument" sentence is spent
  now that ADR-0233 has landed (**#2138**). Each is fired by an ADR reconciling it; neither
  is repaired in this change, and neither is fired by a reviewer of this PR.

### 17. Scope, and what this records against earlier ADRs

> **Normative.** This ADR partially supersedes **five** ratified ADRs and amends none.
> ADR-0231 in six scopes, ADR-0233 in two, ADR-0155 in one, ADR-0181 in one and ADR-0193
> in **three** — §3's fifth comparison, §4's first clause and §6's eighth-check clause in
> one limb — each named on that ADR's `Status` line and in its appended dated note under
> ADR-0082 §1 and §2. **No other ADR's text moves**, and in particular ADR-0014, ADR-0074,
> ADR-0098, ADR-0106, ADR-0146, ADR-0148, ADR-0152, ADR-0154, ADR-0178, ADR-0184,
> ADR-0194, ADR-0204, ADR-0205, ADR-0212, ADR-0217, ADR-0223, ADR-0226, ADR-0228,
> ADR-0230, ADR-0235 and ADR-0236 are relied upon as written.

> **Normative.** **These records are made in this ADR's own change, while it stands
> `Proposed`, and that is ADR-0082 §7's rule rather than an oversight.** §7 names the
> contrary reading as "**the recurring misreading of ADR-0070 §1's 'a supersession that has
> landed' clause … not a governance gap but a reviewer failure mode**", and states the
> condition: "**§1's condition is that the superseding ADR *exists*, not that it is
> ratified** — the hazard §1 names is a `Status` line pointing at nothing, and an atomic
> pair makes that unreachable." ADR-0231's own header records that ADR-0235 did exactly
> this. **And the alternative would cost a round**: ADR-0165 exempts a ratification flip only
> where it is one ADR file and one changed line, so moving five other files' `Status` lines
> in that commit would forfeit the exemption. No lane defers these records to the flip.

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
- **ADR-0231 §13's closure of `SearchDisposition` at exactly fifteen members** — yes; a
  reader would refuse a sixteenth, and the contract test asserting the count would fail.
  Supersession, in that count alone. §13's members, values, injective mapping, no-message
  rule and `NO_RESULT` exclusion are untouched.
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
- **A conversation's budget is charged in full and then settled, in either direction.** A
  claim takes the whole remaining elapsed budget up front, so while a search is in flight
  that conversation cannot start another — searching is serialised per conversation, which
  is a real constraint on a conversation being driven from two devices at once. `settle`
  then writes what the call actually took, **which may be more than was charged**: the
  accounted interval includes ADR-0192's unbounded ledger writes, so one call may carry the
  total past the bound and no size is claimed for that excess. A turn that dies after
  claiming leaves the whole remainder charged, so an unlucky conversation searches less than
  its bound would allow. Both are the fail-closed direction, and they are the price of not
  writing to the store twice per call.
- **A deleted conversation's row outlives it until the next sweep, and this store owes a
  walk to make that bounded.** §8's `forget` is a stamp rather than a drop, because a drop
  cannot fence an observation that arrives after it and this decision would not rest on a
  cross-store check that can go stale between two awaits. Removing the row then cannot ride
  the deletion sequence — every ordering across the two stores leaves a crash window in
  which the conversation is destroyed and its row is left with nothing able to rediscover
  it — so removal is a reconciliation pass over `budgeted_conversation_ids`, which is
  ADR-0076's remedy for ADR-0074 §8's identical defect. The price is a seventh member and a
  sweep obligation on the implementing lane; what it buys is that the residue is bounded by
  a sweep rather than accepted for good, including the orphan ADR-0074 §8 accepts
  permanently for an episode.
- **Two turns of one conversation are not ordered against each other, and §8 says so.** The
  early fold narrows the window in which a concurrent turn can be admitted on a
  not-yet-lowered flag from a whole turn to a single store write, and does not close it.
  Closing it needs a per-conversation ordering across concurrent turns that this corpus does
  not have; §16 defers it with what fires it, and §15's Arm 6f2(iii) pins the boundary that
  *is* guaranteed so that a later lane cannot quietly widen it.
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

**Fence `observe`'s creation power with the `ConversationStore`, rather than with a stamp.**
Refused, and it is what §8 said in an earlier draft. `orchestration` reading that a
conversation still exists and then folding is check-then-act across two stores: the read can
be true when it is taken and false when the write lands, and §8's own two-engines case makes
an in-process ordering unavailable in principle. The check would also have been unfenceable
in the one case that matters most — a conversation the budget store holds **no row** for,
where there is nothing for a drop to have removed.

**Scope observation to the claim, so a fold whose claim `forget` invalidated is a no-op.**
Refused as insufficient rather than wrong: it reuses a fence §8 already ratifies for
`settle` and adds no residue, but §8's fold is triggered by **admission** and fires for a
turn that never claims — precisely the case the request-triggered draft got wrong — so the
path with no claim to scope to would stay open and the stamp would be owed anyway.

**Serialise servicings of one conversation at the site, instead of fencing the store.**
Refused: it is a new obligation on `orchestration` across concurrent turns, and nothing in
this corpus provides it — `Engine._admit_and_reserve` is written for "the Nth concurrent
turn", and §8 names two concurrent turns of one conversation as a case it answers. A lock
inside one engine answers nothing, for ADR-0074 §8's own reason, and the store-level
exclusion that would work is a contract obligation an ADR has to decide. §16 defers it with
that trigger.

**Remove the budget row inside the deletion sequence, and get recoverability from the
ordering.** Refused, and it is what §8 said in an earlier draft. Every ordering of "destroy
the conversation" against "remove its row" leaves a crash window, and each one is worse in
its own way: removing the row after `drop_if_eligible` strands it with nothing able to
rediscover it, which is precisely the defect ADR-0076 was written to close for ADR-0074's
tombstones; removing it before, on a reading of eligibility taken outside
`drop_if_eligible`'s exclusion, resets a live conversation's draw. ADR-0074 §7's reclaim
makes the first unavoidable, because eligibility is only known once the record is already
gone. The walk removes the ordering question rather than answering it, and §8 keeps the
stamp for the fence and the walk for the removal.

**Remove `observe`'s power to create a row and leave creation to `claim` alone.** Refused,
and named because it looks like the clean version of the stamp. A conversation whose first
turn does not search would have its row created by a later `claim` carrying
`initial_footing` **false** — a prior turn exists — permanently closing a conversation that
was never dirty, and making §15's Arm 1b unreachable for every conversation that says hello
before it asks for anything.
