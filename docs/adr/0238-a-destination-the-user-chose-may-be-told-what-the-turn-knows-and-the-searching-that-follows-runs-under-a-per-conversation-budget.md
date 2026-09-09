# 238. A destination the user chose may be told what the turn knows, and the searching that follows runs under a per-conversation budget

- Status: Partially superseded by ADR-0241 (§13's `core`-surface clause in one limb — `WebSearcher` gains one argument, `timeout: timedelta`, on `search`; `ActionPolicy`, `AuditTrail` and `MemoryStore` are untouched, `WebSearcher` gains no member and no widened return, and every other clause of §13 binds entire — and §11's closure of `SearchDisposition` at exactly sixteen members in that count alone, including its no-seventeenth sentence (the enumeration becomes eighteen: one member for a deadline expiry and one for a fault the searcher itself raised, #2112; its members, their values, the injectivity of every mapping into it, its no-message rule, its exclusion of `SearchRefusal.NO_RESULT` and its audit clauses all stand). Those two scopes, and nothing else in this ADR) and ADR-0242 (§1's `record` refusal clause, in the type of the refusal alone: the ground on which a record duplicates a live record's destination set raises `DuplicateDestinationTrustError`, a subclass, because it is the one ground on which the user's recourse is no act at all; the duplicate-`id` and empty-set grounds keep raising `InvalidDestinationTrustError` unchanged, the base class still catches all three, and no check is moved and no atomicity weakened; everything else of §1 stands entire — the two-member vocabulary, the fail-closed absence, the set-by-a-user-act-and-nothing-else clause, the record's five fields, the canonical-destination validator, the `UNCHOSEN` construction refusal, the five-member store surface with its no-member-added clause, `record`'s atomicity, `export`'s data right and `trust_of`'s comparison-not-inference rule — as do §§2-18, and §14's surface assignment is discharged rather than superseded)
- Date: 2026-09-05
- **Partially superseded and amended: 2026-09-09 by ADR-0241** — two scopes superseded,
  one amended, and nothing else in this ADR. §16 defers *"a per-conversation bound on
  elapsed search time"* and names what fires it: *"an ADR that first decides how a deadline
  reaches `WebSearcher.search` at all — a `core/protocols.py` change, and so its own
  ratified ADR under golden rule 5"*, and separately the owner ruling that milestone 31's
  exit is not met by calls and cost alone. Both triggers fired (#1908 on 2026-09-09,
  #2167), and ADR-0241 is the ADR §16 sent a lane to write. **The deferral is not
  discharged**: ADR-0241 supplies the per-call quantity §16 had none of — a bound on a
  servicing's **search work**, the two ledger appends staying unbounded under ADR-0192 §3
  — and leaves the per-conversation bound deferred, restating what now fires it.

  **§13's `core`-surface clause, in one limb.** §13 rules that *"`ActionPolicy`,
  `AuditTrail`, `MemoryStore` and `WebSearcher` each gain no member, no argument and no
  widened return"*. ADR-0241 §1 gives `WebSearcher.search` one required keyword-only
  argument, `timeout: timedelta`, so that the bound is the caller's — ADR-0029 §4's
  *"How long a turn may wait is a property of the turn"* at a second seam — and so that a
  per-operation figure in ADR-0228 §4's shape stays a later `Settings` decision rather than
  a later Protocol change. A reader holding only this ADR would refuse it, which is
  ADR-0070 §1's test met. **The scope is `WebSearcher` and the argument limb alone**: the
  other three Protocols are untouched, `WebSearcher` gains no member and no widened return,
  and §13's enumerated `core/types.py` additions, its `PROTOCOL_VERSION` move, its
  `ConfirmationEgress` and `ConversationExport` clauses and its two decodes-as-written
  clauses all bind entire.

  **§11's closure of `SearchDisposition` at sixteen, in that count alone.** §11 adds one
  member and says *"no lane reads this as licence to add a seventeenth"* — a sentence
  written to stop a lane adding one, and it stopped this one: the seventeenth and
  eighteenth arrive by a ratified ADR, which is the instrument §11 reserves. ADR-0241 §4
  adds a member for a deadline expiry, distinct from `TRANSPORT_FAILED` because the two
  differ in what the system may assert about whether it disclosed anything; ADR-0241 §8
  adds one for a fault the searcher itself raised after the ruling, which rules #2112 in
  the same act and is the one stage §11's vocabulary had no member for. §11's audit
  clauses — one event, one key, counts only, no identifier — its injectivity, its
  no-message rule and its exclusion of `SearchRefusal.NO_RESULT` all stand entire.

  **§8 is amended, not superseded, and the distinction is the point.** §8 grounds its
  refusal to derive an elapsed bound on a premise: *"`WebSearcher.search(call, /)` takes
  **no timeout and no deadline** … Nor is there a per-call bound to substitute"*, and
  concludes *"With no bound on one servicing, no product of two ratified quantities bounds
  a conversation's."* ADR-0241 §1 supplies that bound, so the premise stops being true once
  its implementing lane lands, and a reader holding only this ADR would go on believing
  there is nothing to derive from. **Nothing §8 decided changes**: it bounds provider calls
  and not elapsed time; it adds one `Settings` field and not two; the deleted elapsed
  counter, provisional charge and `SearchClaim` handle stay deleted and ADR-0241 §9
  reinstates none of them; its correction of the ADR-0228 §4 derivation stands; and the
  counter stays on the conversation record with `ConversationStore`'s lifecycle.
  **ADR-0060's own header is the precedent**: ADR-0118 put a deadline on the embedding seam
  and was recorded there as *"§5's `Embedder` assessment amended by ADR-0118"*, because
  §5's assessment was a premise the deadline overtook while §1's rulings stood. This line
  now carries the leading token, so under ADR-0082 §2 the amendment qualifier is not written
  on it and this note is the whole of that record.

  **What is relied upon as written.** §5's closed-loop condition and §6's reach; §8's
  `admit_search`/`observe_search`/`search_draw` triad and its atomicity; §9's refusal of
  #2116; §10's `UNKNOWN`-by-design ruling and its cross-field refusal, which ADR-0241 §5
  extends to an interrupted call rather than moving; §12's negative arm, whose *"The
  comparison has no other input — no clock reading, no interval and no duration a provider
  could stretch"* binds verbatim, ADR-0241's deadline being a **separate** comparison and
  not a second input to that one; and §15's arms, of which Arm 6d — *"an admitted call is
  never refunded"* — is what ADR-0241 §6 applies to an interruption. The record is made in
  ADR-0241's own change under ADR-0082 §7. This line carried no leading token before, so
  the supersession leads and `Accepted` is dropped (`docs/adr/template.md`); the remainder
  of this ADR stays accepted. Refs #1908, #2167, #2112, #2178.
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
- **Partially supersedes** [ADR-0074](0074-conversation-is-an-entity-and-every-turn-is-an-episode.md)
  — **§9's enumeration of what the `ConversationStore` owes, which §8 below widens by
  three operations carrying a per-conversation search budget.** That enumeration, and
  nothing else — §9's `core/types.py` enumeration, its per-conversation exclusion
  obligation, its bounded-and-ordered read rule, its two-store reasoning, §7's retention
  reclaim and §8's deletion protocol are relied upon as written, and §8 below adds no step
  to either sequence.
- **Partially superseded: 2026-09-09 by [ADR-0242](0242-the-act-that-trusts-a-destination-has-its-own-surface-and-a-search-that-did-not-happen-is-explained-in-the-reply.md) — §1's
  `record` refusal clause, in the type of the refusal alone.** That clause has `record` refuse
  *"a duplicate `id`, an empty destination set and a record duplicating a live record's
  destination set, by an `InvalidDestinationTrustError` beside `InvalidRecipientGrantError`"*.
  ADR-0242 §2 gives the third ground a subclass, `DuplicateDestinationTrustError`, because it
  is the one ground on which the user's recourse is **no act at all** — what they asked for is
  already true — and a surface reading this ADR alone could not tell that case from the others.
  A reader holding only this ADR builds one class for three grounds, which is ADR-0070 §1's
  test met. **It is the same call ADR-0235 §4 made on ADR-0193 §1's *"one class rather than
  several"* limb, for the same reason and with the same guarantee**: the base class keeps every
  ground, so a caller wanting one handler still writes one `except
  InvalidDestinationTrustError`, no check is moved, and no atomicity is weakened. What moved is
  the refusal's type and nothing else.

  **Everything else in §1 stands entire and ADR-0242 relies on it throughout** — the
  two-member vocabulary, the fail-closed absence, *"set by a recorded act of the user and by
  nothing else"* with its bar on every model, the record's five fields, ADR-0193 §1's
  canonical destination validator, the `UNCHOSEN` construction refusal, the five-member store
  surface with its *"No member is added, no argument widened and no return changed by any
  later lane"* clause, `record`'s atomicity, `export`'s data right, and `trust_of`'s
  comparison-not-inference rule. §§2-18 are untouched.

  **§14's surface assignment is discharged rather than superseded, and §16's deferral of "The
  surfaces that offer §1's act" is *fired*.** §14 obliges *the lane implementing this ADR* to
  implement no surface and reserves the question to the ADRs that govern the surfaces
  (ADR-0193 §13); that stays true of that lane, and ADR-0242 is such an ADR — it decides the
  command-line surface in its own ratified text, leaves ADR-0177 §1's browser enumeration
  unwidened and defers the browser to a lane that widens it in its own text. Discharging a
  reservation is not amending it, and ADR-0235 §9 discharged ADR-0193 §13 the same way for the
  sibling act with no record on that ADR's line. ADR-0242 §16 and §17 show the working.

  This ADR's `Status` line read `Accepted`, so it takes the leading `Partially superseded by`
  token and `Accepted` is dropped, as `docs/adr/template.md` requires. Appended note per
  ADR-0070 §1; no text below is rewritten. Refs #2178, #2168, #1908.

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
  shape and move that literal (ADR-0212 §8, ADR-0014 §5). §8 puts this decision's counter
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
> tuple[CanonicalDestination, ...]`, **non-empty, duplicate-free and in the one canonical
> order**, the destination set this record is over; `trust: DestinationTrust`; `established_at: UtcInstant`, the instant of the
> user's act; and `revoked_at: UtcInstant | None`, defaulting to `None`. It carries **no
> tool, no account, no payload, no description and no content**: it is a fact about a
> destination set and nothing else, which is what makes it readable for a destination no
> grant covers.

> **Normative.** **`destinations` takes ADR-0193 §1's canonical destination tuple, by the
> same validator and not a second one.** It is refused at construction unless it is
> non-empty, duplicate-free and in the total order `EgressBinding.canonical_destination_set`
> already produces — the rule `RecipientGrant.destinations` carries today. **The reason is
> this store's duplicate refusal, and it is that ADR's own reason**: pinning one spelling at
> construction "is what lets three separate rules stated over *identity* … each be written
> as tuple equality and each mean set equality", and stating the duplicate rule over
> membership instead "was the other available repair and is the weaker one", because it
> leaves the comparison free to drift back to tuple equality with no test noticing.
> **Without it §1's revocation clause is false**: `(Alice, Bob)` and `(Bob, Alice)` are
> unequal tuples over one logical set, both would be admitted as live, and revoking the
> record the user was shown would leave the other standing with the destination still
> reading `USER_CHOSEN` — the exact failure the duplicate refusal exists to prevent.
> **`trust_of` is unaffected**, its rule being membership rather than order, so no clause
> here re-canonicalises a caller's query sequence.

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

> **Normative.** **`record`'s checks and its append are one operation, with no
> interleaving point between them.** The duplicate-`id` check, the empty-set refusal and
> the duplicate-live-set refusal are taken inside the same indivisible act as the append,
> not read and then written. **The duplicate-live-set refusal is the one that fails
> silently without this**: two engines over one data directory each read no live record
> over a destination set and each append, the store then holds two, and the user's
> revocation of the record they were shown leaves the other standing — so the revocation
> clause above would be false of the *store* rather than of any one record, and a
> destination the user withdrew would keep reading `USER_CHOSEN`. This is
> `RecipientGrantStore.record`'s own obligation — "the duplicate-id check, the
> duplicate-**subject** refusal … and the append are **one** operation, not a read
> followed by a write" (ADR-0193 §1) — read one store over, for the reason that store
> gives for the same refusal: "revoking one would leave the other standing and the user
> would have revoked nothing". No caller-side lock discharges it, for the reason ADR-0074
> §9 gives and §8 quotes.

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
> excluded record. §3 states what that check binds at and what it leaves standing.

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
> results — and **no later turn reaches a result's content by any route**. §8's budget is
> one counter and one flag and no result, and no lane reads this ADR as deciding
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
> `PlacementReach.OWNER` is not supplied to a `QueryComposer` on any conforming path, and
> §2's validator is where that is enforced.

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

> **Normative.** **The validator binds at construction, and the bypass past it is the
> corpus's accepted one.** A caller that builds a conforming supply and then rewrites a
> referenced record's `placement` through `__dict__` or `object.__setattr__` defeats the
> check exactly as it defeats every other frozen `core` type. ADR-0068 rules that whole
> class "the caller's responsibility, inside the repository's threat model (ADR-0018 §3),
> and defended where it matters by revalidation at durable boundaries", and fixes the bar
> this ADR meets and does not raise: "exactly the bar every other frozen `core` type
> already sits at — no higher, and no lower". **No detachment obligation is placed on
> `SearchSupply`.** In this corpus detachment is a *store-read* obligation, discharged
> before a record reaches a supply — a `MemoryStore` read hands back "detached snapshots,
> like every other `MemoryStore` read" — and `MemorySearchResult`, the ratified frozen
> container of `tuple[MemoryRecord, ...]`, carries none of its own. A supply site that
> tampers with the value it has just built is an `orchestration` defect, not a supply
> this type admitted, and §2's single construction site is what makes that one site
> reviewable.

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
> record-level fact (§2, §3); the loop is bounded in **provider calls** per conversation
> and the draw is recorded (§8) — **in calls and not in elapsed time**, which §8 states it
> does not bound; and every one of those is decided from recorded facts. **No
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
> halves are stated in the clause below); and **this request holds an admission §8's
> `admit_search` granted for this call**. A request
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

> **Normative.** **Both halves are evaluated at the moment the request is built, and the
> recorded half is read *then* and not earlier.** `orchestration` obtains the stored flag
> by calling `search_draw` at that instant, alongside the current-turn half, and **no
> value read earlier in the servicing is cached, reused or carried forward** — not one read
> before `admit_search`, not one read to decide whether to search at all, and **not the draw
> `admit_search` itself answered**. **A read taken at admission would
> be the wrong instant**: `admit_search` is admitted before the query is composed, so a
> footing read there would be separated from the binding by the composition itself, and a
> fold that committed in between would be ignored by a request built after it. The flag is
> monotone, so reading it as late as possible is strictly the fail-closed direction.

> **Normative.** **The destination's trust is read at that same instant, and an earlier
> trust read authorises nothing.** `trust_of` is necessarily consulted **before** the supply
> is built, because §2 and §3 make it the fact that decides whether records may enter a
> `SearchSupply` at all — but that earlier answer decides only *what may be composed over*,
> and **no clause reads it as deciding what may be sent**. So the second condition is
> evaluated from a `trust_of` call taken at build time beside the recorded half, and a
> value carried over the composition satisfies it in no case.

> **Normative.** **The boundary is the read, and it is not the send — which is
> ADR-0193 §9's boundary, arrived at for ADR-0193 §9's reason.** These are two separate
> awaits on two stores with no transaction between them, and neither is a capability held
> through egress, so **no clause here claims that a revocation recorded after a read stops
> the request that read authorised.** ADR-0193 §9 states exactly this for a recipient grant
> and records that an earlier draft of it said otherwise and was blocked in review for it:
> what a revocation moves is the boundary "from the policy's lookup to `record`'s resolution
> read. It does not move it to the append: those are two awaits". §1's prospectivity is
> read the same way here — **`UNCHOSEN` "from that moment" governs every read that begins
> after the revocation is recorded**, and it is not a claim about work already past its
> read.

> **Normative.** **What the window contains is stated exactly, on both facts, because
> stating it as "one call" or as closed would be false.** The set that still passes after a
> revocation, or after an `observe_search(False)` commits, is **every request whose
> corresponding read had already answered and whose binding has not yet been ruled on** —
> bounded by the servicings in flight at that instant and by nothing this ADR states. There
> is no per-conversation serialisation, no reservation and no cap, and no clause here claims
> one. **The two facts have their own boundaries and are not one snapshot**: a request is
> closed-loop only if *each* read returned true at its own instant, and either may be
> falsified after its own read and before the ruling. What is **not** in the window is any
> request whose read begins after the revocation or the fold is recorded, and any widening:
> every call that passes goes to a destination the user had chosen when it was read, over a
> supply assembled under that same answer.

> **Normative.** **Closing the remainder is not attempted here, and what would close it is
> named.** It would take a linearisation across the trust store, the conversation record and
> the trail, or a capability held from the read through egress — the cross-store transaction
> ADR-0193 §9, ADR-0074 §8 and ADR-0007 §4 each decline to invent, refused there for reasons
> this ADR has no better answer to. **And it is the prospectivity the corpus already
> ships**: ADR-0097 §4 delivers revocation in exactly this sense for source grants, and a
> user who needs a send to stop *now* has the recourse they have for anything already in
> flight, which is not this ADR's to supply. §16 defers it with what fires it.

> **Normative.** **Nothing awaits between those two reads and the binding's construction,
> which is what makes the window as small as this shape allows.** The recorded half and
> `trust_of` are the **last** values `orchestration` obtains before it builds the request
> and constructs the `EgressBinding`; the current-turn half and the admission are already in
> hand, and neither is a fact another actor can change under this servicing — the
> current-turn half is computed from records this component holds, and the admission's only
> role is the fourth condition. **A lane that awaits anything between those reads and the binding
> has widened the window above** and has breached this clause. What the obligation buys is a
> narrower window, never a closed one, and no lane reads it as the latter.

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

> **Normative.** **The fourth condition is an admission already granted, never capacity
> still unspent.** `admit_search` spends the call it admits (§8), so by the time the request
> is built the draw no longer has room for it — a condition reading "the draw leaves room
> for one more call" would therefore be false for **every** admitted request, and false
> first for the last call a conversation is allowed. The order is fixed for that reason:
> **admit, then compose, then build the request, then bind, then rule, then send.** A
> servicing that was not admitted composes nothing, so no request lacking an admission ever
> reaches the fourth condition at all.

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

### 8. The budget: provider calls per conversation, carried on the conversation record

> **Normative.** `core.config.Settings` gains exactly **one** field.
> **`search_calls_per_conversation: int`**, defaulting to **8**, domain the integers
> from **0** through **64** inclusive, where **0 means no search is serviced in any
> conversation**. A value outside that domain is refused at `Settings` load with the
> `ConfigurationError` ADR-0194 §1's configured-amount clause requires, naming the field.

> **Normative.** **The bound ships with a value rather than meaning "unbounded" when
> unset.** ADR-0194 §1's "unset means unbounded" governs a monetary ceiling an operator
> chooses; a bound the milestone's exit is stated over may not be absent by omission, so
> a deployment that configures nothing still searches under it.

> **Normative.** **This decision bounds provider calls, and it does not bound elapsed
> time.** An earlier revision carried a second `Settings` field, a stored elapsed counter, a
> provisional charge and a `SearchClaim` handle settled after each call. **All of it is
> deleted, and nothing replaces it.** The bound this ADR enforces is the call ceiling above,
> and **no clause here states a per-conversation bound on wall-clock search time.**

> **Normative.** **The reason it is stated as absent rather than derived is that no
> derivation is available, and a draft of this section wrongly claimed one.** The claim was
> that the call ceiling times ADR-0228 §4's per-turn planning budget bounds a conversation's
> search time. **It does not.** ADR-0228 §4 gates only the **start** of an additional
> planner call — "checked … **immediately before each additional planner call and at no
> other point**" — and is "a gate on **starting** an iteration and never a cancellation of
> one in flight", so a servicing admitted inside the budget runs to completion outside it
> and its duration is charged to nothing. **Nor is there a per-call bound to substitute**:
> `WebSearcher.search(call, /)` takes **no timeout and no deadline**, ADR-0231 states none
> for that seam, and ADR-0029 §4's `timeout` is `ToolInvoker.invoke`'s — which does not
> reach here, ADR-0231 §5 having ruled the search seam **not a registered tool**. With no
> bound on one servicing, no product of two ratified quantities bounds a conversation's.

> **Normative.** **What ADR-0228 §4 is cited for here, and for nothing else: when a turn
> stops *starting* searches.** A search servicing is reached only from a planner call, so a
> turn whose planning budget is reached starts no further search — `converse` and
> `converse_streaming` declaring **PT20S**, `converse_spoken` declaring **none** and not
> iterating at all. **That bounds a turn's search *count*, not its search *time***, and no
> lane reads this paragraph as supplying a duration.

> **Normative.** **No lane closes the gap inside this ADR's fence.** Reintroducing a
> per-conversation elapsed counter, a claim handle or a settlement member is the apparatus
> deleted above and is refused here; and putting a deadline on `WebSearcher.search` is a
> `core/protocols.py` change, which golden rule 5 gives its own ratified ADR ahead of any
> implementation. §16 defers the bound with exactly that trigger.

> **Normative.** **The budget is state on the conversation record, and the store that
> holds it is `ConversationStore`.** It is not a store of its own. A per-conversation
> durable counter has a lifecycle — it must be fenced when the conversation is deleted and
> destroyed when the record is — and **that lifecycle already exists, ratified, on exactly
> one object**: `stamp_deleted` fences the record and `drop_if_eligible` destroys it
> (ADR-0074 §8). Putting the counter anywhere else obliges some protocol to reproduce that
> lifecycle across two stores with no transaction between them, which this corpus does not
> have.

> **Normative.** **That is a correction of an earlier revision of this decision, recorded
> because the reasoning is the load-bearing part.** A draft gave the budget a
> `SearchBudgetStore` of its own, and every protocol for telling it about a deletion failed
> in a different place. An ordering leaves a crash window on the side ADR-0074 §7 makes
> unavoidable — the retention reclaim only learns a conversation is eligible **once
> `drop_if_eligible` has already destroyed the record**, so the cleanup can only be ordered
> after the destructive act, and one process death strands the counter with nothing able to
> rediscover it. A durable stamp fences the fold but does not decide when to drop. And a
> reconciliation walk in ADR-0076's shape rests on a cross-store read that **aliases a
> tombstoned conversation with a dropped one** — `ConversationStore.get` answers `None`
> "when the id names nothing **or** names a conversation stamped deleted" — and that can be
> defeated by a re-minted id, which ADR-0074 §1 refuses to argue away by probability
> ("the factory is *injected*, so a repeating test double, a seeded factory, or a future
> non-random scheme makes a collision reachable in a way probability does not answer").
> **Moving the counters removes the question instead of answering it**, and every mechanism
> those drafts needed — a second store, a stamp of its own, an enumeration, a drop, a
> reconciliation pass, a stated orphan window — is deleted rather than repaired.

> **Normative.** `core/types.py` gains **`ConversationSearchDraw`**, a frozen model
> refusing unknown fields, with exactly two fields: `calls: int`, non-negative, the
> provider calls this conversation has spent; and `all_external_user_chosen: bool`,
> **required with no default**, false once any turn of this conversation has carried a
> recorded external span that was **not** minted by a `WEB_SEARCH` servicing at a
> destination of recorded trust `USER_CHOSEN`. It is a **read model** — what `search_draw`
> answers — and no member takes one as an argument.

> **Normative.** **The flag's value at creation is `True`, and that is safe because the
> only thing that creates it is `ConversationStore.start`.** A conversation `start` mints
> has **no turns at all** — ADR-0074 §2's `last_turn_at` is "unset until a turn lands" — so
> "every recorded external span this conversation has carried was minted by a `WEB_SEARCH`
> servicing at a destination of recorded trust `USER_CHOSEN`" is **vacuously true** of it.
> **No caller supplies the value, and no member of this store creates a conversation as a
> side effect of anything else.** The laundering hole an earlier revision had — a first
> admission minting a clean row for a conversation that already had turns, permanently
> closing a legacy conversation into the exception — is therefore unreachable by
> construction rather than forbidden by a rule: the field is created by the act that
> creates the conversation, at the one instant when `True` cannot be wrong.

> **Normative.** **A conversation record written before this decision decodes with the flag
> `False`.** That is ADR-0181 §12's own reading of a pre-existing row and the fail-closed
> direction: this decision never observed such a conversation's turns, so it may not report
> them clean. `observe_search` folds by **and**, so no later clean turn raises it, and §5's
> recorded half refuses every search of such a conversation for as long as it lives. **No
> lane back-fills the field, infers it from an episode, a log or a trail, or reads its
> absence as a clean history.**

> **Normative.** `core/protocols.py` gains **no** Protocol for the budget. It adds exactly
> **three** members to **`ConversationStore`**: **`search_draw`**, answering a
> conversation's `ConversationSearchDraw`; **`admit_search`**, which admits or refuses the
> next search call against the ceiling in one step; and **`observe_search`**, folding the
> value its caller computed into the stored flag by logical **and**. A fourth is added by
> no lane without the ADR that decides it. **This
> supersedes ADR-0074 §9's enumeration of what `ConversationStore` owes**, in the same
> scope ADR-0205 and ADR-0212 each recorded on that section, and §17 records it.

> **Normative.** The three members are declared with exactly these signatures, all `async`,
> and they take `conversation_id: str` because every other member of this store does:
>
> - `search_draw(self, conversation_id: str, /) -> ConversationSearchDraw | None`
> - `admit_search(self, conversation_id: str, /, *, max_calls: int) -> ConversationSearchDraw | None`
> - `observe_search(self, conversation_id: str, /, *, all_external_user_chosen: bool) -> None`
>
> `admit_search` answers `None` where it refuses, and otherwise the draw **as it stands
> after the increment**. **There is no handle**: it returns no token, nothing is settled
> afterwards, and no member takes a claim, a charge, a deadline or an interval. **The bound
> is passed in** rather than read by the store, so these three members read no `Settings`
> field, consult no clock and hold no policy — every judgement about what a bound is stays
> in `orchestration`. That the store has a clock of its own for `drop_if_eligible`'s grace
> (ADR-0074 §8) is not a licence for these to read it.

> **Normative.** **No `initial_footing`, and no argument on any member decides what the
> flag starts at.** An earlier revision passed a history fact into `admit_search` because
> that member could create a row; this one cannot create anything, so there is nothing for
> such an argument to be for. **A lane that adds one has reintroduced the creation path
> this clause removes.**

> **Normative.** **`admit_search` is one atomic step: compare, increment, and answer.**
> Given a conversation and the bound, it refuses where the stored `calls` have reached
> `search_calls_per_conversation`; otherwise it increments `calls` by one and answers the
> draw. **The read, the comparison and the write are one indivisible step**, and there is
> nothing outstanding afterwards to settle, release or reconcile.

> **Normative.** **That atomicity is an obligation this store already carries, extended to
> these members rather than invented for them.** ADR-0074 §9 rules that "**`ConversationStore`
> therefore owes per-conversation mutual exclusion between an append and a deletion as a
> contract obligation** … which every implementation satisfies in its own way: an in-memory
> store with a lock, a SQLite-backed one with a transaction, which is also what makes it
> hold across processes", and gives the reason a caller-side lock is not an answer: "the
> engine's own code already contemplates 'another engine over the same durable stores', so
> two engines — in one process or two — hold two locks and serialise nothing." **The
> exclusion the increment needs is the exclusion the record already owes**, and it is why
> concurrent turns, a failed turn and a process exit are answered by one clause rather than
> three: **two turns of one conversation, two servicings of one turn, and two engines over
> one data directory can none of them be admitted against the same draw.** That, and not
> the counter's address, is what answers the defect a per-turn budget had — and a
> `PlanningError` on a later revision still cannot erase a completed search's draw, because
> the increment is durable and taken before the call, not written at capture.

> **Normative.** **`admit_search` and `observe_search` create nothing, and that is
> `append`'s property rather than a new one.** For an id that names nothing, and for one
> naming a conversation **stamped deleted**, `admit_search` answers `None` and
> `observe_search` does nothing and raises nothing. `ConversationStore.append` refuses both
> cases too — `UnknownConversationError` "if `conversation_id` names nothing, or names a
> conversation stamped deleted — an append to a stamped conversation is refused, which is
> what makes a deletion durable against a racing capture" — and these two **answer instead
> of raising** because each is reached by a servicing that may already have been in flight
> when the deletion landed, and a user deleting a conversation should not turn a running
> turn into an error.

> **Normative.** **There is nothing for a late fold to resurrect.** The budget is a
> property of the conversation record, so a fold arriving after the record is stamped
> writes nothing, and one arriving after the record is dropped finds nothing to write to.
> **The whole class of hazard an earlier revision needed a durable stamp, an enumeration
> walk and a reconciliation pass to bound does not arise**, and no clause here fences a
> write with a read of another store: the refusal and the record are one object under the
> exclusion the store already owes.

> **Normative.** **An admitted call is consumed whatever the outcome, and there is no
> refund.** A servicing that is admitted and then does not transmit — a binding that refused, a
> ruling that was not `ALLOW`, a provider that rejected before or after receiving the query
> — still spends its `calls` increment. **`SearchOutcome` carries no transmission fact** and
> `WebSearcher` is not widened here to add one, so a refund rule would oblige the servicer
> to tell two `SearchRefusal.PROVIDER_REFUSED` outcomes apart when nothing in the contract
> distinguishes them. Conservative admission is the honest reading, and it errs toward
> searching less.

> **Normative.** **The flag means *every turn this decision has observed was clean*, and
> `orchestration` computes it.** For every turn it captures, `orchestration` calls
> `observe_search` with whether **every** recorded external span that turn's final supply
> carried was minted by a `WEB_SEARCH` servicing at a destination of recorded trust
> `USER_CHOSEN` — computed from records it holds as data it fetched, at the same instant and
> by the same component as ADR-0223 §1's own value. **The second conjunct an earlier
> revision needed — "and this decision has observed every turn this conversation has
> had" — is gone**, because creation is `start`'s: a conversation whose first turn this
> decision did not see is one created before it, and such a record decodes `False`.

> **Normative.** **The early fold is triggered by admission and not by a request: the
> moment `orchestration` admits to a turn a recorded external span that was **not** minted
> by a `WEB_SEARCH` servicing at a destination of recorded trust `USER_CHOSEN`, it calls
> `observe_search` with `False` for that conversation.** The trigger is that admission — the
> same fact §5's current-turn half is stated over — and it fires **whether or not that turn
> ever builds a `WEB_SEARCH` request**. **Capture's fold remains and is unchanged**; this
> one is earlier, not instead, and the two agree because `observe_search` folds by **and**.

> **Normative.** **Admission is the trigger because neither a request nor a capture is
> early enough.** §5's current-turn half is computed when a request is **built**, so a turn
> that reads a local file and never searches computes it nowhere, and a turn that reads one
> and *does* search computes it only after `admit_search` has already admitted that call.
> Both leave the stored flag true for as long as the turn is in flight — so a **second
> servicing of the same conversation** could be admitted, read the stale-true flag, find its
> own supply clean and be ruled closed-loop, although the conversation had already carried
> the file. Folding at admission puts the
> false on the record **as early as the fact exists**, which narrows that window from the
> whole of a turn to a single store write — and the two clauses below state exactly what
> that does and does not guarantee.

> **Normative.** **The guarantee is stated over the *read*, not over the admission, because
> `admit_search` does not consult the flag.** It admits on `calls` and on nothing else, and
> no member of this store gates admission on the footing. So the boundary is this and no
> more: **every request whose recorded-half read (§5) returns after the fold has committed
> sees the false**, the flag being monotone and `search_draw` a single indivisible read of
> it. **An admission is not that instant, and no clause here says it is** — a servicing may
> be admitted before a fold and still build a request after it, and §5 requires it to read
> the flag at build time precisely so that such a request sees the false rather than a value
> it read earlier. **The draw `admit_search` returns is not that read either**: it is the
> value at the moment of admission, and §5 forbids carrying it forward.

> **Normative.** **Nothing in this decision serialises two turns of one conversation.** The
> store's per-conversation exclusion serialises each member's own read-and-write, not two
> turns' worth of work; ADR-0074 §9's two-engines case makes an in-process ordering
> unavailable in principle; and `orchestration` cannot fold a fact before it holds it, so a
> read concurrent with the single `observe_search` await can still return the
> not-yet-lowered value. **A lane that reads any clause here as an ordering obligation on
> the caller has misread this section** — there is no such obligation, and none would be
> dischargeable.

> **Normative.** **The window it leaves is stated rather than claimed away, and it is
> bounded at both ends.** It opens when turn A admits its disqualifying span and closes when
> A's `observe_search` commits — one store write, with none of A's composition, transport or
> capture inside it. Before the early fold that window ran to A's *capture*.

> **Normative.** **What it costs when it is reached is every search whose recorded-half read
> falls inside it, up to the conversation's remaining call allowance — not one search.** An
> earlier revision of this section said "one search of one concurrent turn" and that was
> true only while a provisional elapsed charge serialised searching per conversation. **That
> charge is deleted (above), so nothing serialises them**: `admit_search` gates on the call
> counter alone, so with *n* calls left in the budget, *n* concurrent turns can each be
> admitted, each take its build-time `search_draw` before A's fold commits, each read the
> not-yet-lowered flag and each be ruled closed-loop. **The residual is therefore bounded by
> the call ceiling and by nothing tighter**, and it is stated at that size deliberately
> rather than at the flattering one. Every request whose read falls after the fold is
> refused, and §11's audit records both dispositions, so the size of a real occurrence is
> answerable from the audit rather than from this estimate. **The window is a property of the read's instant and not of the
> admission's**, which is why §5 puts the read as late as it can go.
> **Closing it entirely means serialising servicings of one conversation**, which is a new
> obligation on `orchestration` across concurrent turns that nothing in this corpus provides
> today; §16 defers it with what fires it, and **no lane closes it by having `orchestration`
> hold a lock**, for ADR-0074 §9's own reason — two engines hold two locks and serialise
> nothing.

> **Normative.** **A half that reads *true* is never folded early.** Reporting a turn
> **clean** stays capture's alone, because only capture sees the turn's **final** supply; an
> early true would report a turn clean before it had finished carrying things, which is the
> direction this section fails closed in everywhere else. The early fold writes `False` and
> nothing else, it is idempotent, and repeating it costs nothing.

> **Normative.** **Once false the flag never returns to true**, which is ADR-0106 §4's
> monotonicity read on this axis, and it is what keeps a conversation closed after the
> tainting episode has fallen out of the tail (ADR-0223 §6's un-tainting, which this ADR does
> not disturb). `observe_search` folds by **and** and by no other operation; no lane adds a
> member, a flag or a repair that raises it.

> **Normative.** **§5's recorded half is one read and no disjunction.** It is satisfied
> where `search_draw` answers a draw whose `all_external_user_chosen` is **true**, and by
> nothing else. `search_draw` answers **`None`** for an id that names nothing and for a
> conversation stamped deleted — `ConversationStore.get`'s own rule, "`None` when the id
> names nothing **or** names a conversation stamped deleted" — and `None` fails the
> condition. **An earlier revision needed a second limb** — no row, *and* no recorded prior
> turn — because a separate store could be silent about a conversation that existed. This
> store cannot be silent about one, so the limb is gone and the prior-turn test with it.

> **Normative.** **This is what closes a legacy conversation whose stamped episode is
> gone.** A conversation that read a file before this decision landed may, by the time of
> its next turn, have lost that episode — expired under ADR-0007 §2, deleted, or simply
> fallen out of the tail (ADR-0223 §6's own un-tainting, which ADR-0231 §12 records) — and
> `ConversationLifecycle.history` skips a turn whose episode does not resolve. Its current
> turn's supply can therefore be clean. **The decoded `False` is what refuses it**, and no
> later clean capture rescues it: `observe_search` folds by **and** onto a field that
> records what this decision has actually seen.

> **Normative.** **What the record now carries is one counter and one flag and no
> content** — no query, no result, no destination, no record, no text. It is local, durable
> and never written to a remote service (ADR-0004 §2), it is a Tier 1 fact, and it lives
> under the retention, deletion and export rules the conversation record already has rather
> than under new ones.

> **Normative.** **The conversation's lifecycle is not extended, and no cleanup is added.**
> ADR-0074 §7's retention reclaim and §8's deletion protocol are **unchanged by this
> decision** — no new step, no new call, no new ordering and no sweep. `stamp_deleted`
> fences the budget with the record it is part of; `drop_if_eligible` destroys the budget
> with the record; and the residue between them is exactly the tombstone ADR-0074 §8
> already states and bounds, which this ADR neither enlarges nor re-argues. **A lane that
> finds itself writing a lifecycle member, a sweep or a reconciliation for this budget has
> put the counter somewhere it does not belong.**

> **Normative.** **`Conversation`, `ConversationTurn` and `ConversationExport` gain no
> field and change no version.** The counter and the flag are the store's own row state rather than
> presented model state — the position the turn index and `ParkedBinding`'s uniqueness
> already hold — and `search_draw` is the read that presents them, added for
> `orchestration`'s use and not for a surface. So `ConversationExport.schema_version` stays
> at **2** and ADR-0212 §8 and ADR-0014 §5 are untouched. **A lane that finds a user-facing
> need for the draw moves that version in the same change**, with the records that entails,
> rather than reading this clause as permission not to; §16 records what fires it.

> **Normative.** **`admit_search` is called before a query is composed**, at the servicing
> site §2 names. Where it refuses, **no supply is constructed, no query is composed, no
> ruling is sought, no credential is read and no channel is opened**, and §11's audit
> records it. This is ADR-0231 §11's no-slot clause in a second place and by the same
> posture: the servicing does not yield, the turn composes from what it has, the user is
> asked nothing and nothing is parked.

> **Normative.** **This ADR adds no monetary bound**, no `SpendGate`, no ledger row, no
> ceiling and no `Settings` field for one, and ADR-0194's mechanism is neither coupled
> to these bounds nor read by them. ADR-0231 §15 binds entire: the transport call is
> admitted by a `SpendGate` inside the seam over ADR-0236's declared figure, exactly as
> today.

**A conversation and not a period, because the milestone says so and because the unit is
the one the user can see.** #1908 states the bound as "calls, time and cost per
conversation", and the conversation is the object a user starts, reads and abandons. **This
decision delivers two of those three, and says plainly that it does not deliver the
third.** **Calls** are bounded here, per conversation, by the one `Settings` field §8 adds.
**Cost** is bounded already and is not re-decided: ADR-0231 §15's `SpendGate` admits the
transport call inside the seam over ADR-0236's declared figure, and §9 declines a
per-conversation monetary bound in terms. **Time is not bounded by this ADR** — see above:
the derivation a draft claimed does not hold, and no per-servicing bound exists to build one
from. §16 defers it with what fires it. **Whether milestone 31's exit is satisfied by calls
and cost without a time bound is not this ADR's to decide**, and this clause states the gap
rather than papering over it. The honest cost is stated in Consequences: a long-lived conversation exhausts its budget and
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
> turn's `calls`. **Counts only.** No record id, no
> conversation id, no destination, no query text, no fragment or length of one, no
> title, no snippet and no provider message appears — ADR-0231 §13's Tier 1 clause and
> ADR-0004 §5 bind without qualification.

> **Normative.** **`SearchDisposition` gains exactly one member and is closed at
> sixteen**, recording that a servicing did not reach a query because `admit_search` refused. It is
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

> **Normative.** **An injected result cannot raise the budget.** The bound is a `Settings`
> value read by `orchestration`; the draw is a durable counter §8's `admit_search`
> increments atomically before a channel opens. **The comparison has no other input** — no
> clock reading, no interval and no duration a provider could stretch, the elapsed bound
> this decision once carried being deleted (§8). **A provider that stalls therefore cannot
> reach the budget at all** — it delays its own conversation and spends no extra call, which
> is what a counter of calls buys that a counter of time did not. No value a model produced,
> a request carried or a search result contained reaches either side of the comparison.
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
> `CarriedProvenance` (`closed_loop`, defaulting to `False`). In `core/protocols.py`: **one**
> new `@runtime_checkable` Protocol, `DestinationTrustStore` with its five members; **three
> new members on `ConversationStore`** (§8), which is the one existing Protocol this
> decision widens; and the changed parameter type on
> `QueryComposer.compose`. In `core/errors.py`: `InvalidDestinationTrustError`. In
> `core.config.Settings`: the one field §8 names and the cross-field refusal §10 states.
> **No other member of any `core` type or Protocol changes its type, its default or its
> meaning** — `ActionPolicy`, `AuditTrail`, `MemoryStore` and
> `WebSearcher` each gain no member, no argument and no widened return; **no existing
> member of `ConversationStore` changes its signature, its answer or its meaning**;
> `Conversation`, `ConversationTurn` and `ConversationExport` gain no field and change no
> version;
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
> a model-composed span — turns on `coverage` and not on this; §8's counter is the
> conversation record's own row state and appear on neither presented model, so
> `Conversation` and `ConversationTurn` stay as they are, which
> leaves `ConversationExport.schema_version` at **2** and ADR-0212 §8 and ADR-0014 §5
> untouched. **A lane that finds either statement false moves the corresponding version in
> the same change** rather than reading this clause as permission not to.

> **Normative.** **A stored `PermissionDecision` whose `egress_binding` predates this
> decision decodes with `closed_loop` false**, on ADR-0181 §12's own reading of a
> pre-existing row, and no lane back-fills it, infers it or reconstructs it. A false value
> is the state every binding in this corpus carries today, so nothing decoded changes
> behaviour.

> **Normative.** **A conversation record written before this decision decodes with a zero
> draw and the flag `False`** (§8), so §5's recorded half refuses it and every search of it
> runs under ADR-0231 §12 as ratified. No lane back-fills the field, infers it, reconstructs
> it from an episode, a log or a trail, or reads a pre-existing record as a clean history.

> **Normative.** **A conversation in progress when the implementing lane lands behaves
> exactly as it does under ADR-0231 today**: it is not closed-loop, so it searches under
> ADR-0231 §12 as ratified. The accumulated draw of such a conversation under-counts by
> at most the calls it made before the field existed, which ADR-0231 §12 already bounds
> at one per conversation, and that residue is accepted rather than repaired.

### 14. What the implementing lane owes

> **Normative.** **One new Protocol, and it ships as a triad** — the Protocol, a shared
> conformance suite asserting its obligations, and a canonical fake in
> `ai_assistant.testing` — in one change, never deferred (`CONTRIBUTING.md` → "Adding a
> Protocol"). That is `DestinationTrustStore`. **§8's three members are a widening of an
> existing Protocol, not a triad**: `ConversationStore`'s conformance suite and its
> canonical fake already exist, and the lane extends both in the same change. The
> `QueryComposer` conformance suite's one-positional-parameter check is kept and is
> restated over the new parameter type.

> **Normative.** **`ConversationStore`'s conformance suite asserts the atomicity
> `admit_search` claims**, in the shape `RecipientGrantStore`'s ceiling test already takes:
> concurrent admissions against a bound of one yield exactly one admission, and an
> implementation that reads, compares and writes as three awaits fails it. An
> implementation that cannot be opened twice states so and skips, as the ledger contracts
> already do. **This is the suite that already asserts §9's append-versus-deletion
> exclusion**, so the new arms extend a property the suite states rather than introducing
> one.

> **Normative.** **That suite also asserts what the three members do at the two lifecycle
> edges**, because an implementation that stored the counter anywhere but on the record
> would pass every other assertion in it. On an id that **names nothing**: `search_draw`
> answers `None`, `admit_search` answers `None`, `observe_search` raises nothing, and
> afterwards `search_draw` still answers `None` — **nothing was created**. On a conversation
> **stamped deleted**: the same three answers, alongside the `append` refusal the suite
> already asserts for that state. And after `drop_if_eligible` has removed the record, the
> same again. **No arm asserts a budget lifecycle member, because there is none.**

> **Normative.** **The lane reads the recorded half last, and the review of that lane
> checks the call order rather than taking it on trust.** §5 puts `search_draw` immediately
> before the request is built with nothing awaited in between, and that is the whole of what
> makes §8's boundary true — the store cannot enforce it, because `admit_search` does not
> consult the flag and no member does. A lane that reads the footing once and carries it
> through composition has silently widened the window §8 states, and §15's Arm 6f3 is the
> arm that catches it.

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
> one, the increment having been taken before the call rather than at capture.

> **Normative.** **Arm 6c4 — a late fold writes nothing, and the arm forces the
> interleaving rather than assuming it.** A conversation stamped between `admit_search` and
> the admission fold, and one stamped between its search returning and its capture: neither
> fold changes anything, neither raises, and `search_draw` answers `None` for both. The same
> is driven **after the record is dropped**, where there is nothing left to write to at all.

> **Normative.** **Arm 6c4b — the order a cross-store check would have got wrong.** The arm
> drives it explicitly: the fold's caller reads the conversation as **existing**, the
> deletion then lands, and the fold calls `observe_search`. Nothing is created, `search_draw`
> answers `None`, and a subsequent `admit_search` answers `None` and spends nothing. The
> arm exists because this is the interleaving no ordering between two stores could have
> fenced, and it is the one this decision makes unreachable by putting the counter on the
> record.

> **Normative.** **Arm 6d — an admitted call is never refunded.** A servicing whose ruling is
> not `ALLOW`, one whose binding refused, and one whose provider answered
> `SearchRefusal.PROVIDER_REFUSED` each spend their `calls` increment, and no path lowers
> `calls`.

> **Normative.** **Arm 6e — the footing is monotone.** A conversation whose flag is false
> stays false when a later turn's supply carries nothing external at all, including after
> the tainting episode has fallen out of the tail.

> **Normative.** **Arm 6f — a legacy conversation cannot be laundered clean.** A
> conversation record written before this decision — decoding with the flag `False` — is not
> closed-loop, **including where its stamped episode no longer resolves and its current
> supply carries nothing external at all**; and after a clean turn of it has been observed
> it is **still** not closed-loop, because `observe_search` folds by **and** and never
> raises. A conversation `start` minted after the decision landed is closed-loop on the
> first two conditions from its first turn. Both are asserted, because the first is the hole
> that opens one turn after a naive reading closes it.

> **Normative.** **Arm 6f2 — a dirty turn closes the conversation at admission, not at
> capture, and closes it even when it never searches.** With
> `search_calls_per_conversation` above one, on a conversation whose destination reads
> `USER_CHOSEN` and whose stored flag is true, in two shapes. **(i)** Turn A services a local-file
> read and then a `WEB_SEARCH`, so A's own request binds `closed_loop` false; a second
> servicing of that conversation, admitted **before A is captured**, carries nothing
> external of its own and is **not** closed-loop. **(ii)** Turn A services a local-file read
> and **builds no search request at all**; a concurrent turn B is admitted and composes, and
> B is **not** closed-loop for the same reason. The stored flag is
> false in both, and A's later capture folds false again to no effect. **(iii) The window,
> asserted as the boundary §8 states and not as an ordering.** B's **recorded-half read**
> lands **while A's admission fold is still in flight** — the arm blocks inside
> `observe_search` and releases it, rather than sequencing the two calls and hoping — and B
> **does** read the not-yet-lowered flag, which is the residual §8 names and this arm
> records so that it is a ratified property and not a surprise found later. **(iv) The
> residual is asserted at its true size, which is not one.** The same blocked fold is held
> open while **the conversation's whole remaining call allowance** is admitted — *n*
> concurrent turns for a draw with *n* left — and the arm asserts that **every one of them**
> reads the not-yet-lowered flag and is ruled closed-loop, that the *(n+1)*th is refused by
> `admit_search` on the counter rather than by the footing, and that every read landing
> after the fold commits is not closed-loop. **A one-turn arm cannot catch this**: it passes
> identically whether the residual is one search or the whole budget, which is exactly how
> an earlier revision of §8 came to claim the smaller figure.

> **Normative.** **Arm 5d — a revocation recorded before the build-time read is honoured,
> in two shapes and by two writers.** On a conversation whose destination reads
> `USER_CHOSEN`, the supply is assembled carrying records and the composer is entered; the
> trust record is **revoked while the composition is in flight**; the request is then built.
> It is **not** closed-loop, its binding carries `closed_loop` false, its ruling is the
> non-`ALLOW` ADR-0181 §5 and ADR-0231 §12 give, and **nothing reached the destination** —
> the arm asserts no transport call was made, because composition is a `ModelProvider` call
> inside `planning` (ADR-0231 §3) and the transport is not entered until after the ruling.
> The same is asserted where the revocation is written by a **second engine** over the same
> data directory rather than by the same one, which is the case no in-process ordering
> reaches.

> **Normative.** **Arm 5e — the window §5 states is asserted as a property, not assumed
> away.** A revocation committed **after** the build-time `trust_of` read and before the
> ruling leaves that one request closed-loop and ruled `ALLOW`, and the **next** request of
> that conversation is not. The arm exists so that the boundary is a ratified and tested
> property rather than a surprise, and so that a lane cannot later read §5 as promising that
> a revocation stops a request already past its read.

> **Normative.** **Arm 6f3 — an admission taken before the fold does not carry a stale
> footing past it.** The arm drives the interleaving the boundary would be false for if the read
> were taken at admission: turn B calls `admit_search` and is admitted **while the flag is
> still true**; turn A then admits a local-file span and its `observe_search(False)`
> **commits**; only then does B compose, read the recorded half and build its request.
> **B's request is not closed-loop**, its binding carries `closed_loop` false, and its
> ruling is the non-`ALLOW` ADR-0181 §5 gives. The arm asserts in the same breath that **no
> value read before `admit_search`, and not the draw `admit_search` itself answered, reached
> the binding** — the footing on the binding is the one §5's build-time read returned.

> **Normative.** **Arm 6g — the last permitted call is usable.** With
> `search_calls_per_conversation` set to one, the admitted servicing's own request is
> closed-loop: the fourth condition reads the admission this request holds, not the capacity
> left after spending it.

> **Normative.** **Arm 6g2 — a zero bound refuses every search, and each bound is
> asserted on its own.** With `search_calls_per_conversation` set to **zero**, a fresh
> conversation whose stored draw is zero is refused at admission — `admit_search` answers
> `None`, because the stored `calls` have already **reached** the bound. Nothing composes,
> no supply is built, no request reaches the seam, and the disposition §11 adds is
> recorded. **The arm exists because zero is a legal setting whose stated meaning is that
> no search is serviced in any conversation (§8), and because the idiomatic spelling of a
> reached-the-bound comparison — a truthiness guard on the bound — admits at zero**, `0`
> being falsy: the arm at one call cannot catch it.

> **Normative.** **Arm 6h — the budget goes with the record, and no step is added to make
> it.** A deleted conversation and a reclaimed one each leave nothing behind: after
> `stamp_deleted` all three members answer as §8 states, and after `drop_if_eligible` has
> removed the record `search_draw` answers `None`. **The arm asserts that ADR-0074 §7's and
> §8's sequences run exactly as they run on `origin/main`** — no extra call, no extra
> ordering — and that a conversation whose record is gone reads as an unknown id.

> **Normative.** **Arm 6h2 — the three crash points that cost an earlier revision two
> rounds, each now a no-op.** **(i)** A retention reclaim whose `drop_if_eligible` answered
> `True`, after which the process dies: **there is nothing left to clean**, because the
> counter went with the record in that one call. **(ii)** A deletion interrupted after
> `stamp_deleted` and re-run: the same state as one that ran straight through, and the
> budget is fenced from the first stamp onward. **(iii)** A fold that commits after the
> record is dropped: it writes nothing and creates nothing, and no sweep is needed to
> collect anything. Each arm asserts `search_draw` answers `None` and that no path
> reintroduces a row.

> **Normative.** **Arm 6h3 — a reclaim that declines leaves the draw alone.** §7's reclaim
> of an **ineligible** conversation — `drop_if_eligible` answering `False` — leaves that
> conversation's counter and flag **exactly as they were**, and its next search is admitted
> against them. That is the arm that would fail for any design in which some sweep decided,
> from outside the store's exclusion, that a conversation's budget could be cleared.

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
> set, a duplicate live set and an `UNCHOSEN` record; **a `DestinationTrustRecord` is
> refused at construction for an empty, a repeated-member or a non-canonically-ordered
> destination tuple** — `(Bob, Alice)` where `(Alice, Bob)` is the canonical spelling — so
> that the duplicate refusal cannot be defeated by reordering and a revocation cannot be
> left standing behind a reordered twin; **two concurrent `record` calls
> over equal destination sets admit exactly one**, which is the interleaving the refusal
> is stated over and which a sequential arm cannot reach, pinned as
> `RecipientGrantStore`'s own suite pins its duplicate-subject refusal; `revoke` is
> prospective and idempotent and rewrites no recorded decision; and `export` answers
> revoked records that `live` omits, which is the data right ADR-0004 §6 gives and
> ADR-0193 §1 already applies to authorisation records.

### 16. Deferred, by name, each with what fires it

- **Milestone 32's fetch, and everything about an `UNCHOSEN` destination beyond the
  member's existence.** Fired by the ADR that decides the bounded fetch (#2096 item 1).
  Not fired by a lane finding a snippet thin.
- **A third `DestinationTrust` member.** Fired by an ADR with a policy that reads it. Not
  fired by a lane wanting a finer scale, which is inspection by another name.
- **A per-conversation bound on elapsed search time.** §8 deletes the one an earlier
  revision carried and states that this decision bounds calls and not time; nothing in the
  corpus bounds a single servicing's duration, so there is nothing to derive a
  per-conversation figure from. **Fired by an ADR that first decides how a deadline reaches
  `WebSearcher.search` at all** — a `core/protocols.py` change, and so its own ratified ADR
  under golden rule 5 (ADR-0015) — after which a per-conversation bound over that quantity
  becomes stateable. Also fired by the owner ruling that milestone 31's exit is not met by
  calls and cost alone. **Not** fired by a lane reintroducing the deleted claim handle or
  settlement member, which answers nothing this defers, and not by §11's audit showing a
  conversation searching for a long time, which is the symptom rather than the trigger.
- **A rolling window for §8's bound**, in place of the flat per-conversation figure.
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
- **Closing §5's read-to-ruling window on either of its two facts** — a revocation
  recorded after the build-time `trust_of` read, or an `observe_search(False)` committed
  after the recorded-half read. Closing it takes a linearisation across the trust store,
  the conversation record and the trail, or a capability held from the read through egress:
  the cross-store transaction ADR-0193 §9, ADR-0074 §8 and ADR-0007 §4 each decline to
  invent, and this ADR inherits their refusal rather than opening a fourth. Fired by the
  ADR that decides a transactional posture across the local stores — ADR-0074 §8's "leg 5's
  'stores' concurrent-access posture' hardening tail". Not fired by a lane finding the
  window narrow, and not by one finding it wide.
- **Serialising servicings of one conversation**, which is the separate thing that would
  make two turns of one conversation ordered against each other at all. Fired by an ADR
  that gives `orchestration` a per-conversation ordering across concurrent turns and holds
  it across two engines — a store-level obligation in ADR-0074 §9's shape, not a lock,
  which §8 records as answering nothing.
- **Presenting the draw to the user, and with it a `ConversationExport` version move.**
  §8 keeps the counter as the store's own row state, so `Conversation`,
  `ConversationTurn` and `ConversationExport` are untouched and
  `ConversationExport.schema_version` stays at 2. Fired by an ADR or a surface lane that
  finds a user-facing need for the draw, which moves that version in the same change with
  the ADR-0014 §5 and ADR-0212 §8 records it entails. Not fired by an implementing lane
  finding it convenient.
- **The surfaces that offer §1's act.** ADR-0193 §13's assignment (§14).
- **The two corpus findings this ADR reports rather than settles**: ADR-0223 §6's and
  ADR-0233 §9's disagreement about which clause of ADR-0181 §5 is the lineage floor
  (**#2137**); and ADR-0231 §4's second clause, whose "only instrument" sentence is spent
  now that ADR-0233 has landed (**#2138**). Each is fired by an ADR reconciling it; neither
  is repaired in this change, and neither is fired by a reviewer of this PR.

### 17. Scope, and what this records against earlier ADRs

> **Normative.** This ADR partially supersedes **six** ratified ADRs and amends none.
> ADR-0231 in six scopes, ADR-0233 in two, ADR-0155 in one, ADR-0181 in one, ADR-0193
> in **three** — §3's fifth comparison, §4's first clause and §6's eighth-check clause in
> one limb — and **ADR-0074 in one**: §9's enumeration of what `ConversationStore` owes,
> which §8 widens by three members. Each is named on that ADR's `Status` line and in its
> appended dated note under ADR-0082 §1 and §2. **No other ADR's text moves**, and in
> particular ADR-0014, ADR-0076, ADR-0098, ADR-0106, ADR-0146, ADR-0148, ADR-0152,
> ADR-0154, ADR-0178, ADR-0184, ADR-0194, ADR-0204, ADR-0205, ADR-0212, ADR-0217, ADR-0223,
> ADR-0226, ADR-0228, ADR-0230, ADR-0235 and ADR-0236 are relied upon as written.

> **Normative.** **ADR-0074's record is the scope ADR-0205 and ADR-0212 each took on that
> same section, and no wider.** Its `Status` line already reads "ADR-0205 (§9's enumeration
> of what a `ConversationTurn` carries and of what the `ConversationStore` owes)" and
> "ADR-0212 (§9's enumeration of what Conversation carries and what ConversationStore
> owes …)", so this pair **accumulates** under ADR-0070 §4 beside them and displaces
> neither. **What moves is the obligation list alone**: a reader holding ADR-0074 would
> build a `ConversationStore` owing eleven things and find three missing. **ADR-0074 §7's
> retention reclaim, §8's deletion protocol, §9's exclusion obligation, its two-store
> reasoning and its `core/types.py` enumeration are relied upon as written and are not
> moved** — §8 adds no step to either sequence and no field to either type, which is the
> whole point of putting the counter where the lifecycle already is.

> **Normative.** **These records are made in this ADR's own change, while it stands
> `Proposed`, and that is ADR-0082 §7's rule rather than an oversight.** §7 names the
> contrary reading as "**the recurring misreading of ADR-0070 §1's 'a supersession that has
> landed' clause … not a governance gap but a reviewer failure mode**", and states the
> condition: "**§1's condition is that the superseding ADR *exists*, not that it is
> ratified** — the hazard §1 names is a `Status` line pointing at nothing, and an atomic
> pair makes that unreachable." ADR-0231's own header records that ADR-0235 did exactly
> this. **And the alternative would cost a round**: ADR-0165 exempts a ratification flip only
> where it is one ADR file and one changed line, so moving six other files' `Status` lines
> in that commit would forfeit the exemption. No lane defers these records to the flip.

> **Normative.** **Two near misses are named, because each was a supersession an earlier
> draft of this ADR would have owed and each is avoided by a decision rather than by luck.**
> ADR-0152 §7's transcription count, by §5's default; and ADR-0212 §8's and ADR-0014 §5's
> export version, by §8 keeping the counter as the store's own row state rather than
> putting them on `Conversation`. A lane that reverses either decision owes the record it
> avoids, and says so. **ADR-0074 §9's enumeration is no longer among them** — an earlier
> draft avoided it with a store of its own, and §8 now takes that record instead, which is
> the trade this decision makes deliberately.

> **Normative.** **ADR-0231 §16 is relied upon and is not moved.** Nothing here retains a
> minted record, admits one to a store, an archive or a later turn, or leaves a hook for
> one; §2's third population is within a turn for exactly that reason, and §16's own
> sentence — "a second turn re-searches … because nothing was retained" — stays true.

> **Normative.** Additions this ADR makes that contradict no sentence an earlier ADR
> wrote are **stacked additions** under ADR-0082 §1 and are recorded here and nowhere
> else: §1's trust store and its establishing act, which no ADR forbids and ADR-0235's
> act does not contain; §8's one `Settings` field; §10's cross-field refusal; and §11's
> two counts and one `SearchDisposition` member.

> **Normative.** On ADR-0231, ADR-0155, ADR-0193 and ADR-0074, whose `Status` lines already
> lead with `Partially superseded by`, this ADR's pair is **appended** to the existing pairs
> on the same line under ADR-0070 §4's accumulation rule, and no existing pair is dropped or
> rewritten. On ADR-0233 and ADR-0181 the line takes the leading token and `Accepted` is
> dropped, as `docs/adr/template.md` requires. **No ratified sentence of any of the seven is
> rewritten**, and no body text outside the header is touched.

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
- **ADR-0074 §9's enumeration of what `ConversationStore` owes** — **yes.** A reader
  holding only ADR-0074 would build that store owing eleven things and would find
  `search_draw`, `admit_search` and `observe_search` missing; §8 requires all three. Supersession, in that enumeration alone. §9's exclusion obligation, its
  two-store reasoning, its `core/types.py` enumeration, §7's reclaim and §8's deletion
  protocol are untouched — §8 leans on them rather than moving them, and a reader of any of
  those acts identically.
- **ADR-0212 §8's `Literal[2]`, ADR-0014 §5's version rule and ADR-0152 §7's transcription
  count** — **no**, on all three, and each is a near miss §17 names. `ConversationTurn` and
  `Conversation` gain nothing, so the export's shape and version stand; and `rebind`
  transcribes nothing new, so §7's count stands. A reader of any of the three acts
  identically.
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
- **The budget is visible.** Provider calls per conversation are recorded on the
  conversation record and reported in counts, so "how much did the loop search" is
  answerable from the audit rather than from a guess.
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
- **One new store and one widened one.** Destination trust is genuinely new and ships as a
  triad; the budget is three members on `ConversationStore`, whose conformance suite and
  canonical fake already exist and are extended in the same change. That is a smaller lane
  than an earlier revision's two triads, and it is the second time this decision has got
  smaller by taking something out.
- **`ConversationStore` is a large Protocol and this makes it larger.** Three more members on
  a contract that already carries seventeen is a real cost, and a reader looking for "what
  does a conversation store owe" now has more to hold. It is paid deliberately: the
  alternative was a second store whose whole content was a lifecycle this one already has,
  and twelve review rounds established that reproducing that lifecycle across two stores is
  where the defects live.
- **The budget counts calls and does not measure time, and search time is not bounded at
  all.** `admit_search` spends one call and there is nothing to settle
  afterwards, so a turn that dies mid-search costs its conversation exactly the one call it
  was admitted for — no remainder is stranded and no unlucky conversation searches less than
  its bound allows. **What is given up is any bound on elapsed search time, and it is given
  up outright rather than traded for a looser one.** A conversation may spend its eight calls
  over an arbitrarily long wall clock, because no contract bounds how long one servicing
  runs: `WebSearcher.search` carries no deadline and ADR-0228 §4 gates only when a turn stops
  *starting* searches. A deployment that needs a time guarantee has no setting for one, and
  §16 records what fires the ADR that would add it — a decision about how a deadline reaches
  that seam, which is a `core` Protocol change and so precedes any implementation.
- **Searching is no longer serialised per conversation.** The earlier revision's provisional
  charge made a second admission impossible while a search was in flight; counting calls
  does not, so two turns of one conversation may search concurrently up to the ceiling. That
  is a deliberate relaxation — the serialisation was a side effect of the charge rather than
  a property anything asked for — and the atomicity of the increment is what still makes the
  ceiling exact under concurrency.
- **A deleted conversation leaves no budget residue at all, and that is the whole return
  on the widening.** Because the counter is the record's, `stamp_deleted` fences it and
  `drop_if_eligible` destroys it, so this decision adds nothing to ADR-0074 §8's residue
  and owes no sweep, no stamp of its own and no recovery walk. The three crash windows an
  earlier revision had to name are not narrowed here; they do not exist.
- **Two turns of one conversation are not ordered against each other, and §8 says so.** The
  early fold narrows the window in which a concurrent turn can *read* a not-yet-lowered flag
  from a whole turn to a single store write, and does not close it. **The store cannot
  enforce the boundary on its own** — `admit_search` admits on the counter and never on the
  footing — so §5 carries it as an obligation on where the read sits, and §15's Arms
  6f2(iii) and 6f3 are what hold a lane to it.
  Closing it needs a per-conversation ordering across concurrent turns that this corpus does
  not have; §16 defers it with what fires it, and §15's Arms 6f2(iii) and 6f2(iv) pin the
  boundary that *is* guaranteed — including the residual's true size, the conversation's
  whole remaining call allowance — so that a later lane can neither quietly widen it nor
  restate it at the flattering figure.
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
rolling window and the call ceiling's default together, this decision adding one budget
setting and no second one — or when milestone 32's ADR needs a third
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

**Give the budget a `SearchBudgetStore` of its own.** Refused, and it is what §8 said
through eleven review rounds, so the reasoning is recorded rather than summarised. A
separate store needs a lifecycle — the counters must be fenced when a conversation is
deleted and destroyed when its record is — and every protocol for supplying one failed in a
different place. **An ordering** leaves a crash window on the side ADR-0074 §7 makes
unavoidable: the retention reclaim only learns a conversation is eligible once
`drop_if_eligible` has already destroyed the record, so the cleanup can only follow the
destructive act, and one process death strands the counters with nothing able to rediscover
them — the exact defect ADR-0076 was written to close for ADR-0074's own tombstones.
**A durable stamp** fences a late fold but does not decide when to drop. **A reconciliation
walk** in ADR-0076's shape then rests on a cross-store absence read that aliases a
tombstoned conversation with a dropped one (`ConversationStore.get` answers `None` for
both) and that a re-minted id defeats, which ADR-0074 §1 refuses to argue away by
probability. Every one of those mechanisms exists only to reproduce a lifecycle
`ConversationStore` already has, so the counters moved to where the lifecycle is and all of
them were deleted.

**Keep the budget on `ConversationTurn` and fold it per turn.** Refused earlier in this
decision's life and still refused: concurrent turns of one conversation spend the same draw
and an ordinary `PlanningError` erases a completed search's draw, because a turn row is
written at capture and a search is admitted long before. **What answers that is
`admit_search`'s atomicity, not the counter's address** — the increment is durable, taken
before the call, and made under the per-conversation exclusion ADR-0074 §9 already puts on
this store — which is why the same defect does not return now that the counter lives on the
conversation record instead.

**Serialise servicings of one conversation at the site, instead of at the store.**
Refused: it is a new obligation on `orchestration` across concurrent turns, and nothing in
this corpus provides it — `Engine._admit_and_reserve` is written for "the Nth concurrent
turn", and §8 names two concurrent turns of one conversation as a case it answers. A lock
inside one engine answers nothing, for ADR-0074 §9's own reason, and the store-level
ordering that would work is a contract obligation an ADR has to decide. §16 defers it with
that trigger.

**Let a member other than `start` create the flag.** Refused, and named because every
variant of it has already been tried here. A member that mints the flag for a conversation
it did not create must guess what that conversation's earlier turns carried: guessing
`True` launders a legacy conversation into the exception, and guessing `False` permanently
closes a conversation whose first turn simply did not search, making §15's Arm 1b
unreachable for every conversation that says hello before it asks for anything. **`start`
is the only moment at which the answer is knowable without guessing**, because it is the
only moment at which the conversation provably has no turns.
