# 247. The configured web-search provider is the destination the owner chose and the recipient they granted, a search to it never asks on lineage or coverage grounds, and the per-conversation call budget is removed

- Status: Partially superseded by ADR-0251 (one scope. §5's per-turn sentence alone: "**Per turn**: ADR-0228 §4's planning budget gates the start of each additional planner call, so a turn that declares one starts at most two planner calls and therefore at most two searches, and an operation declaring none does not iterate at all." ADR-0251 §5 moves ADR-0228 §3's count to the attempt and declares four for a conversational one, so the figure two stops being true of a turn inside such an attempt; the sentence's second limb, that an operation declaring none does not iterate at all, binds verbatim and is kept by ADR-0251 §5 unchanged, as is ADR-0228 §4's PT20S gate the first limb names. §5's per-search clause (ADR-0241 §1's deadline and ADR-0231 §5's ceilings), its per-money clause (ADR-0194's ceiling and ADR-0016 §4's unknown-cost floor) and above all its per-conversation clause — "**Per conversation: nothing bounds the number of searches**, and that is the decision rather than an omission" — all bind **verbatim**, and ADR-0251 §11 answers §13's first deferral by keeping that sentence true rather than by reversing it. §5's removal clauses, its two-SQLite-columns clause, its dissolution of two ADR-0238 deferrals and its #1908-sentence clause are untouched, and §§1-4 and §§6-16 are untouched) and ADR-0254 (§2's discriminator clause in its route-(b) limb alone, which takes one further conjunct — a non-resolving egress `ALLOW` carrying a digest is route (b) where `authorised_goal` is unset and route (d) where it is set; §2's route-(c) limb, its derived fact, its ordering before the grant seam, its digest-free admission and its eligibility-versus-discriminator division all bind entire, as do §§1 and 3-16)
- Date: 2026-09-11
- **Partially superseded: 2026-09-12 by ADR-0251 — §5's per-turn sentence alone.
  Nothing else in this ADR.** §13's first deferral names its own trigger — *"Fired by the
  owner's own trigger, quoted: 'Revisit if planner passes, batching or unattended work
  expand.'"* — and milestone 32's investigation loop expands planner passes. ADR-0251 is
  the decision that fires it and answers it.

  **The sentence that moves.** §5 reads *"**Per turn**: ADR-0228 §4's planning budget
  gates the start of each additional planner call, so a turn that declares one starts at
  most two planner calls and therefore at most two searches, and an operation declaring
  none does not iterate at all."* ADR-0251 §5 moves ADR-0228 §3's count from the turn to
  the attempt and declares **four** for a conversational one, so *at most two* stops being
  true of a turn inside such an attempt. A reader holding only this ADR would tell an
  operator a turn runs at most two searches and would be wrong, which is ADR-0070 §1's
  test coming out on the supersession side.

  **The sentence's second limb is kept, and so is the gate its first limb names.**
  *"[A]n operation declaring none does not iterate at all"* binds verbatim: ADR-0251 §5
  keeps ADR-0228 §4 entire — `converse` and `converse_streaming` still declare PT20S from
  the turn's entry into the loop, `converse_spoken` still declares none — and adds a
  second, fail-closed declaration one level up, where an attempt kind that declares no
  allowance likewise does not iterate.

  **What §5 keeps, and the third clause is the one that matters.** Its **per-search**
  clause and its **per-money** clause bind verbatim and ADR-0251 §11 quotes them as two of
  the four things bounding the expanded loop. And its **per-conversation** clause binds
  **verbatim** — *"**Per conversation: nothing bounds the number of searches**, and that
  is the decision rather than an omission. Every turn is owner-initiated, so the count is
  bounded by how many times the owner asks."* ADR-0251 §11 answers §13's deferral by
  **keeping that sentence true**: it rules normatively that no attempt advances without an
  owner act — nothing schedules, sweeps, resumes, retries or continues an attempt on a
  timer, at startup or in a background job — and that the expansion is bounded per attempt
  by a declared allowance. It reintroduces **no** per-conversation bound of any kind, in
  any form: `Settings.search_calls_per_conversation` stays removed,
  `ConversationSearchDraw` stays removed, `ConversationStore` regains no member and
  `SearchDisposition` regains no `NOT_ADMITTED`.

  **§13's first deferral is therefore discharged rather than superseded, and its two
  remaining limbs stay unfired.** Batching and unattended work would each falsify *"every
  turn is owner-initiated"*, and ADR-0251 §11 restates them as what would fire a
  per-conversation bound again. **ADR-0238 §16's rolling-window entry and its
  per-conversation elapsed-time entry stay exactly where §13 restated them** and are
  neither discharged nor narrowed.

  **Nothing else in this ADR moves.** §5's removal of the `Settings` field and of
  `ConversationSearchDraw`, its `ConversationStore` obligation clause, its
  two-SQLite-columns clause, its dissolution of two ADR-0238 deferrals and its clause
  about #1908's sentence are untouched; and §§1-4 and §§6-16 — the configured provider as
  the chosen destination and granted recipient, route (c)'s trail, the lineage floor and
  coverage exception, `closed_loop`'s two conditions, what the removal took with it,
  `rebind`'s transcription, the configuration-authority contract, the unchanged list, the
  `core` surface and version, the lane cut, the tests, the remaining deferrals and the
  scope record — all stand exactly as ratified.
- **Partially supersedes** [ADR-0238](0238-a-destination-the-user-chose-may-be-told-what-the-turn-knows-and-the-searching-that-follows-runs-under-a-per-conversation-budget.md)
  — **§1's third clause in the limb reaching a `WEB_SEARCH` request at the configured
  provider; §5's four-condition definition of `closed_loop` in its second, third and fourth
  conditions; §5's non-transcription clause in the count it keeps and in its never-resumed
  premise; §6's first clause in the conditions under which the relaxation is available;
  §8's `Settings`-field clause and its ships-with-a-value clause; §8's
  `ConversationSearchDraw` clause, its three-member clause, its signature clause, its
  atomicity clauses, its creation-value and pre-existing-record clauses, its early-fold
  clauses, its window clauses and its monotonicity clause; §11's closure of
  `SearchDisposition` in that count alone; §11's per-turn record in its `calls` limb alone;
  and §13's `core`-surface enumeration in the limbs naming the removed field, type and
  three members.** Those nine scopes, and nothing else in that ADR beyond what the four
  records preceding this one already made there: §1's other clauses, §2 entire, §3, §4,
  §5's writer, producer-discard, trust-boundary, window and pre-existing-row clauses, §6's
  remaining clauses, §7, §9, §10, §11's one-event, one-key, counts-only, no-identifier and
  no-trust-in-the-event rules, §12's negative arm, §13's remaining clauses, §14, §15's
  other arms and §16's deferrals bind as those records left them.
- **Partially supersedes** [ADR-0244](0244-a-confirm-on-a-search-parks-as-a-durable-question-and-the-answer-runs-that-exact-read-once.md)
  — **§6's clause 2 entire, the fact it establishes passing to a read of
  `ConversationStore.get`; §9's definition of `UNAVAILABLE_NOW` in its
  `search_calls_per_conversation` limb alone; and §12's re-closure of `SearchNotServiced`
  at nine members in that count alone.** Those three scopes, and nothing else in that ADR:
  §§1-5, §6's other five clauses and its ordering, §7, §8, §9's other six members and its
  precedence rule, §§10-11, §12's remaining clauses and §§13-23 bind as written.
- **Partially supersedes** [ADR-0242](0242-the-act-that-trusts-a-destination-has-its-own-surface-and-a-search-that-did-not-happen-is-explained-in-the-reply.md)
  — **§8's closure of `SearchNotServiced` at eight members in that count alone, and §8's
  two-members-not-one clause for the refusal whose subject is removed.** Those two scopes,
  and nothing else in that ADR beyond what ADR-0244 already recorded there: §1's trust act
  and its surface, §§2-7, §8's remaining clauses including the precedence order and the
  totality and non-injectivity of its mapping, §9's bar on what a statement may say and
  §§10-18 bind as that record left them.
- **Partially supersedes** [ADR-0193](0193-a-standing-recipient-grant-is-a-user-act-on-a-canonical-destination-set-and-never-covers-a-call-planned-over-external-content.md)
  — **§3's first clause in its application to a `WEB_SEARCH` request at the configured
  provider, which reaches an `ALLOW` by a route of its own rather than by coverage; and
  §6's pairing clause together with the scope of its eight-check invariant, in the limb
  reaching a non-resolving `ALLOW` whose `authorised_subject` is unset — the digest's
  presence becoming what tells a route-(b) row from a route-(c) one, over the whole history
  and from the row alone.** Those two scopes, and nothing else in that ADR beyond what
  ADR-0238 already recorded there: §1, §2, §3's five comparisons wherever a grant is the
  route and its comparison-not-inference rule, §4, §5, §6's eight checks themselves, §7,
  §§8-9, §11's rendering bar and §§12-16 bind as that record left them.
- **Partially supersedes** [ADR-0148](0148-an-egress-call-is-authorised-as-one-whole-and-nothing-in-it-moves-after-the-ruling.md)
  — **§3's first clause in the route enumeration alone, which takes a third route; and §3's
  second clause in the *"a configured base URL or host"* limb, for a `WEB_SEARCH` request
  at the configured provider alone.** Those two scopes, and nothing else in that ADR: §3's
  other limbs and remaining clauses, including the source-grant refusal and the clause
  reserving three questions to the standing-grant ADR, and §1, §2, §§4-7, §8 and §§9-15
  bind as written.
- **Partially supersedes** [ADR-0181](0181-an-egress-call-records-whether-it-was-planned-over-external-content.md)
  — **§5's second clause in its application to a `WEB_SEARCH` request at the configured
  provider.** That scope, and nothing else in that ADR beyond what ADR-0238 already
  recorded there: §5's memory-ruling-point clause, its separate-binding clause on `decide`
  and `resolve`, its two-comparisons clause, its `authorises` clause and its
  `ActionPolicy`-contract clause, and §§1-4 and §§6-12 bind as that record left them.
- **Partially supersedes** [ADR-0152](0152-the-binding-is-derived-at-one-seam-never-supplied-to-it-and-a-call-it-cannot-describe-is-refused.md)
  — **§7's transcription count alone, which becomes four.** That scope, and nothing else in
  that ADR beyond what ADR-0181 and ADR-0233 already recorded there: §7's every other
  clause, §§1-6 and §§8-16 bind as those records left them.
- **Partially supersedes** [ADR-0021](0021-permission-decisions-and-the-audit-trail.md)
  — **§3's clause that a policy constructed with no authorisation source leaves
  `authorised_by` unset, in the limb reaching a request whose binding carries
  `closed_loop`.** That scope, and nothing else in that ADR: §3's other clauses, §4's
  resolution invariant, §5's disclosure floor and its monotonicity obligation — satisfied
  rather than relaxed — and §6's deferral of standing grants for other actions bind as
  written.
- **Partially supersedes** [ADR-0246](0246-reach-does-not-bind-at-all-on-a-search-bound-to-a-destination-the-user-chose-and-the-supply-type-refuses-no-placement.md)
  — **§11's Arm F′ in its `calls` count alone**, the arm being restated over the three
  counts that remain once the per-conversation call budget is removed. That scope, and
  nothing else in that ADR: Arm F′'s each-at-its-true-value requirement, its withheld-at-zero
  and supplied-narrowed-at-two limbs and its one-identifier-and-no-other rule, §1's rule
  that `Placement.reach` does not bind at all on a chosen destination's supply, §§2-10,
  §11's other arms, §12's deferrals and §§13-15 bind as written.
- **Note (2026-09-12) — two things this ADR's own implementation found its text got wrong,
  recorded rather than rewritten.** All four lanes §11 cuts are merged (PRs #2253, #2254,
  #2259 and #2261), and two statements above did not survive being implemented. This is a
  self-amendment naming no other ADR, so under ADR-0082 §1's self-amendment clause and
  ADR-0070 §1 the appended dated note is the whole record, no `Status` line moves, and
  **every ratified section below is byte-identical** (#2260).
  - **(a) Nine representative-input arms retire with the read they are arms over (PR
    #2259).** The `Partially supersedes` record on ADR-0238 above, and §14's restatement of
    it, say that *"§15's other arms … bind as those records left them"*. That is over-wide.
    §1 replaces `SearchFooting.trusted`'s two `trust_of` reads with the registration fact and
    §4 retires ADR-0238 §5's build-time read, and nine arms are stated over exactly those
    reads. Four are **ADR-0238 §15 Arms 5d, 5e, 6f2(iii) and 6f3** — a revocation recorded
    before the build-time read is honoured, the window §5 states, and the two discriminations
    between an admission and the fold's stored flag. Four are **ADR-0242 §15's trust
    journeys**: Arm 2's fixtures **(b)** and **(c)**, which §15 says *"differ in the
    `trust_of` answer alone"*; **Arm 2c**'s recovery journey walked to its end; and **Arm
    3**'s limb **(b)**. The ninth is **unnumbered**, in ADR-0242 §15's *"Beside the five"*
    paragraph — *"an arm in which trust is revoked between ADR-0238 §5's two reads, asserting
    that the carried member is `TRUST_MISSING`"* — which names both reads in terms, so §1 and
    §4 between them take its whole subject away. Once the servicing site takes no `trust_of`
    answer at either position none of the nine has a subject, and a lane cannot both implement
    §1 and pass them. Read the record above and §14's restatement as reaching §15's arms
    **other than those nine**, and §12's own enumeration — Arms 1a, 2, 5b and 5c restated,
    Arms 3, 4, 6 and 6b replaced or retired — as extended by them and by nothing else. Every
    other arm of either ADR, numbered or not, binds exactly as recorded, and lane 3 restated
    the fold-based ones in place rather than dropping them.
  - **(b) §11's lane-4 enumeration of two `SearchFooting` members is withdrawn; §3 governs
    (PR #2261).** §11 names `minted_user_chosen` and `selected` among the members lane 4
    deletes. They are ADR-0238 §2's populations at the one construction site,
    `_search_supply`: `selected` carries the first two, `minted_user_chosen` the third. §3
    rules that *"`SearchSupply`, its populations and its construction site are untouched"*
    and that §2's three populations *"bind entire"*, and the record on ADR-0238 above
    repeats it. Deleting the two sets would admit into the supply every record another
    servicing of the turn contributed — a fetched file, a citation hop — which §2 excludes
    by name. So **the enumeration is wrong where §3 is right**, and §3 governs:
    `SearchFooting.selected` and `minted_user_chosen` **stand**. Lane 4 removed the
    enumeration's other `SearchFooting` members and kept these two, reading §11's
    enumeration as a scope bound satisfied by removing fewer. Every other limb of that
    enumeration, and every other clause of §11, binds as written.
- **Partially superseded: 2026-09-12 by ADR-0254 — §2's discriminator clause in its
  route-(b) limb alone. Nothing else in this ADR.** §2 rules that *"a non-resolving egress
  `ALLOW` whose `authorised_by` is set is **route (b) where `authorised_subject` is set**
  and **route (c) where it is not**"*. ADR-0254 §6 adds a fourth route whose rows are
  non-resolving, carry an `authorised_by` and carry a digest, so a reader holding that
  sentence would classify a route-(d) row as route (b) — which is false, and is ADR-0070
  §1's test met. The route-(b) limb takes one further conjunct, **and `authorised_goal` is
  unset**, and route (d) is the limb where that field is set. **The route-(c) limb is
  untouched**: a digest-free standing row is route (c) exactly as this ADR left it, admitted
  on `closed_loop` and pointer equality, refused otherwise, with no store read, no
  `Settings` read and no clock. **Every other clause of §2 binds entire** — the one derived
  fact and the rule that `closed_loop` alone is never the condition of any relaxation; the
  two configured values as a constructor argument that is not a store handle; route (c)
  reachable exactly where route (b) is and on the same five conditions; route (c) taken
  before the grant seam is consulted; a policy with no `RecipientGrants` reaching route (c);
  `authorised_by` set to the binding's `account.reference` and `authorised_subject` left
  unset; the eligibility-versus-discriminator division; the trail-asserts-what-it-can-see
  clause; the exclusion of a pre-ADR-0238 digest-free row from route (c); and the
  no-revalidation clause. **ADR-0254's route (d) relaxes neither floor this ADR relaxed**:
  §3's retirement of the lineage floor and the coverage exception is for a request at the
  configured provider and for nothing else, and ADR-0254 §6's conditions 3 and 4 keep
  `planned_with_external_content` and `SpanCoverage` binding on route (d) unrelaxed.
  **ADR-0254 §12 states by name that this ADR's configured-provider authority takes no
  expiry**: it has no record, no instant and no revocation event, §8(b)'s prospectivity is
  its whole lifecycle, and the owner's decision 7 of 2026-09-12 excludes it in terms. Refs
  #2255.

## Context

### Where this comes from

The owner ordered a pass over the safety posture of a `WEB_SEARCH` read — the whole of
it at once rather than one finding per milestone — and recorded the ground it was ruled
on. Two facts from that pass decide everything below.

**A web search sends one query string to the configured provider and nothing else.** No
page fetch exists (milestone 32's subject, ADR-0238 §16), so the only bytes that leave on
this path are a query a `QueryComposer` returned. And **composing that query is a model
call**, so the supply the query is composed over already reaches the configured *model*
provider on every turn of every conversation.

**Production has never reached the state ADR-0238 designed for.** `assistant
destination-trust` answers *"Nothing chosen"*, so `DestinationTrust.USER_CHOSEN` is a
value no live deployment holds: ADR-0238's closed loop, ADR-0245's and ADR-0246's supply
widening and ADR-0242's `trust-destinations` act have never applied to a real search.
Every production search composes from the user's words alone, and a search planned over
external content asks (ADR-0181 §5). The pass enumerated the gates a search passes once a
destination *is* chosen and found them firing in sequence: call budget, then §8's early
fold, then the closed loop failing (#2212), then the lineage floor's `CONFIRM`, then the
park — answerable only because `closed_loop` was `False`, which #2232 says stops being
true the moment the loop opens.

### The owner's rulings of 2026-09-11, which this ADR records

The rulings are quoted, in their own words, because this ADR records a decision rather
than derives one. The ground first:

> a web search sends one query string to the configured provider and nothing else; no page
> fetch exists; composing the query is a model call, so the supply already reaches the
> configured model provider every turn. Disclosure of the owner's eligible context to the
> provider the owner configured is **accepted, not deemed harmless**: outside content may
> steer which notes appear in a query, and the fixed destination bounds where it goes, not
> what it contains. Fetch (milestone 32) gets its own rules and inherits none of these
> loosenings.

Then the five:

> 1. **The configured web-search provider is the chosen destination and the granted
>    recipient.** Configuration (origin + connection + credential) is the owner's choosing
>    act for this one kind; no `trust-destinations` act, no `remember-recipients` grant, no
>    window. Unconfiguring revokes. ADR-0238 §1 and ADR-0193 §3 are amended for
>    `WEB_SEARCH` to the configured provider only; the general choosing act and grants
>    remain for every other destination (email today, fetched sites later).
> 2. **A search to the configured provider never asks on lineage or coverage grounds.**
>    ADR-0181 §5's floor and the ADR-0233 coverage exception (a query composed over stored
>    records cannot use the grant route) both retire for that request; ADR-0238 §5's third
>    condition and §8's `all_external_user_chosen` flag retire for search and stay ratified
>    for other destinations. Retiring one without the other changes nothing. The negative
>    arm stands: outside content cannot change the destination. #2212 is decided by this.
> 3. **`search_calls_per_conversation` is removed** (ADR-0238 §8). The bounds are ADR-0228
>    §4's planner-pass limit (at most two searches per turn, every turn owner-initiated)
>    and ADR-0194's optional spend ceiling. #1908's "enforced budget" wording re-points at
>    those. Revisit if planner passes, batching or unattended work expand.
> 4. **#2232:** the closed-loop fact is recorded with the parked request (ADR-0152 §7's
>    transcription count 3 → 4; ADR-0238 §5's non-transcription clause amended), so any
>    park that still arises is answerable.
> 5. **Unchanged:** the unknown-cost floor, risk/reversibility thresholds (a deny takes its
>    own exit), the search deadline, the spend ceiling, response bounds, Tier 0, ADR-0244's
>    park (one open per conversation), ADR-0226 §5's audience refusal.

And the obligation this ADR's §8 discharges:

> **The ADR must state the contract for configuration-based authority** (review finding,
> accepted): which account and origin the authority covers; what a change to either does to
> standing authority and to an open park; how unconfiguring revokes and what becomes of an
> open park; and what recorded authority each automatic search cites in the audit trail in
> place of a decision id.

**What "accepted, not deemed harmless" forbids.** The ruling is not that a search
discloses nothing worth protecting. It is that the disclosure is one the owner has decided
to accept, to a party they named, for one kind of call. So no clause of this ADR is stated
over a judgement about content, and no clause of it reaches a second kind, a second
destination or a second party. §3's retirements are stated over *which request* rather
than over *what the request carries*, which is what keeps ADR-0098 §5's and §6's refusal of
a content detector untouched.

### The tree, read rather than assumed, at `origin/main` `7fbc7eac`

What this ADR changes exists and was read rather than imagined.

- `permissions/policy.py`'s `_only_the_disclosure_floor` is the five-condition predicate
  that decides whether route (b) is reachable. Two of its limbs already read
  `closed_loop`: `(not external or binding.closed_loop)` and `(binding.coverage is
  SpanCoverage.NOT_COVERED or binding.closed_loop)`. Where it holds, `_covering` is asked
  for a grant and an `ALLOW` is returned **only if one is found** — so with an empty grant
  store, which is every deployment's, the search draws `CONFIRM`.
- `permissions/policy.py`'s `_FLOORS` comment records the constraint §2 below has to
  satisfy: *"ADR-0021 §5's floor forbids an `ALLOW` with `authorised_by` **unset** for a
  non-empty `discloses`, and a route-(b) `ALLOW` sets it."*
- `permissions/audit.py`'s `_names_a_standing_authorisation` is a **non-resolving `ALLOW`
  with an `egress_binding` and `authorised_by` set**, and every decision it answers true
  for is validated against the recipient-grant store by ADR-0193 §6's eight checks.
  `_check_authorisation` separately requires a *resolving* `ALLOW` to cite its own
  `resolves`.
- `core/types.py`'s `BoundAccount` carries `identity` and `reference: DurableIdentifier`,
  and `PermissionRuling.authorised_by` is a `DurableIdentifier | None`, so a connection
  reference is a value that field already admits by type.
- `tools/egress_binder.py`'s `rebind` transcribes three facts from `approved` —
  `provenance`, `planned_with_external_content`, `coverage` — and passes the literal
  `False` for `closed_loop`, with ADR-0238 §5's reasoning in the comment beside it.
- `orchestration/reads.py` carries `SearchFooting`, whose `trusted`, `admit`, `footing`,
  `clean`, `admitted`, `observe`, `_place`, `_lower` and `_fold` are the mechanism §3 and
  §5 retire, and `SearchServicer.service`, whose `closed_loop=` argument is the conjunction
  of the current-turn half, the recorded half and the build-time trust read.
- `core/config.py` carries `search_calls_per_conversation`, default 8, domain 0–64; and the
  pair `web_search_connection` / `web_search_origin`, set together or not at all, which
  `tools/builtin.py`'s `build_web_search_integration` turns into the one registration a
  search binds against. The transport pins every call to the registration's origin **as
  text, before parsing** (ADR-0154's condition 5).
- `core/protocols.py`'s `ConversationStore` carries twenty members, three of them ADR-0238
  §8's: `search_draw`, `admit_search`, `observe_search`. `get` is among the other
  seventeen and answers `None` *"when the id names nothing **or** names a conversation
  stamped deleted"* — the same rule `search_draw` answers `None` on.
- `memory/conversation_store.py` adds `search_calls` and `all_external_user_chosen` to the
  `conversations` table through `_migrate_search_draw`, an `ALTER TABLE … ADD COLUMN`.
- `core/types.py`'s `SearchNotServiced` is closed at nine members and is carried on
  `TurnOutcome.search_not_serviced`, which crosses the wire;
  `orchestration.reads.SearchDisposition` is closed at eighteen and crosses no subsystem
  boundary. `PROTOCOL_VERSION` is **35**.
- `orchestration/parked_reads.py` answers `UNAVAILABLE_NOW` where the deployment holds no
  searcher, **before** it reads `search_draw`, and again where `search_draw` answers `None`
  or `self._max_calls == 0`.
- The **only** production caller of `DestinationTrustStore.trust_of` is
  `SearchFooting.trusted`. `orchestration/destination_trust.py` holds the listing,
  recording and revocation face ADR-0242 §1 decided; it calls `record`, `live`, `revoke`
  and `export`, and not `trust_of`.

### What this ADR is not allowed to settle

It decides nothing about milestone 32's fetch, which ADR-0238 §16 reserves and which the
owner's ruling excludes by name. It decides nothing about a second search provider
(ADR-0231 §19). It adds no tier, axis, band or placement value, and re-reads ADR-0217,
ADR-0199, ADR-0204 and ADR-0004 not at all. It does not relax ADR-0155 §3's second clause
or ADR-0233 §7, which stay absolute. It does not decide whether the `trust-destinations`
act should be retired now that its one production reader goes away — §13 defers that with
what fires it. And it opens no route for any egress kind but `WEB_SEARCH` to the
configured provider: an email planned over outside content confirms after this ADR exactly
as it does before it.

## Decision

### 1. The configured search provider is the destination the owner chose, for `WEB_SEARCH` and for nothing else

> **Normative.** **A `WEB_SEARCH` request is *at the configured provider* when both hold:
> the binding's `account.reference` equals this deployment's configured
> `Settings.web_search_connection`, and the binding's canonical destination set is the one
> `Settings.web_search_origin` canonicalises to.** Both are compared as recorded values —
> `DurableIdentifier` equality and `CanonicalDestination` equality, every field, never
> across protocols — and neither is inferred, folded, matched by domain or
> re-canonicalised. A request failing either is **not** at the configured provider and
> every clause this ADR relaxes binds on it exactly as it does today.

> **Normative.** **That predicate is the authority's *extent*, and it is checked where the
> binding exists — at the ruling — and never where it does not.** It is **not** the rule
> `orchestration` evaluates to write `closed_loop`, and no clause of this ADR asks it to
> be: at the servicing site the binding has not been derived yet, and a fact the seam
> derives cannot be an input to the derivation. **Three sites, each holding what it needs**:
> `orchestration` writes the carried fact (§4) before the binding, exactly as it writes
> `planned_with_external_content` and `coverage`; the **policy** takes this predicate over
> the binding the request carries (§2); and the **trail** takes the pointer check over the
> decision it is handed (§2). A lane that finds itself comparing a configured value against
> a binding inside `orchestration` has put the check at the one site that cannot hold it.

> **Normative.** **On such a request the destination is the one the owner chose, and the
> configuration is the choosing act.** This supersedes **ADR-0238 §1's third clause** —
> *"The fact is **set by a recorded act of the user and by nothing else**. No configuration
> sets it, no connected account sets it, no operator setting sets it"* — **in the limb that
> reaches a `WEB_SEARCH` request at the configured provider, and in no other limb.** The
> clause binds entire on every other destination and every other kind, and is the reason
> this ADR names one kind rather than stating a rule about configuration.

> **Normative.** **`DestinationTrust`, `DestinationTrustRecord` and `DestinationTrustStore`
> are untouched, and `trust_of` answers exactly as it does today for every caller.** No
> record is minted, written, implied or synthesised by a configuration; `trust_of` is not
> taught to read one; and a deployment that has recorded no trust act still answers
> `UNCHOSEN` for every destination it is asked about, including the search provider's. What
> changes is which fact the **servicing site** consults, not what the store says. So
> ADR-0238 §1's remaining clauses — the two-member vocabulary, the fail-closed absence, the
> record's five fields, the canonical-destination validator, the five-member store surface,
> `record`'s atomicity, `export`'s data right and `trust_of`'s comparison-not-inference
> rule — bind entire, as does ADR-0242 §1's `trust-destinations` act and §4's listing and
> revocation.

> **Normative.** **The servicing site stops asking the trust store, and reads one fact it
> already holds: whether this deployment has a search registration at all.**
> `SearchFooting.trusted`'s two `trust_of` reads — the one deciding what may be composed
> over (ADR-0238 §2) and the one taken at the instant the request is built (ADR-0238 §5) —
> are both replaced by that fact, which is true where `Settings.web_search_connection` and
> `Settings.web_search_origin` are set and false where they are not. **`Settings` is a pair
> the composition root already hands the one site that holds the `WebSearcher`**, so no
> value reaches below `orchestration`, no store handle is added and no await is introduced.

> **Normative.** **That the registration's binding *is* the configured one is the egress
> seam's guarantee and not an assumption.** `EgressBindingSeam` derives a `WEB_SEARCH`
> binding from the registration `build_web_search_integration` built out of those same two
> values, so its `account.reference` and canonical destination set are the configured ones
> by construction, and the transport pins every call to the registration's origin **as
> text, before parsing** (ADR-0154's condition 5, ADR-0231 §5, §8). **This ADR relies on
> that derivation and does not restate it**; what §2 adds is the ruling-side check that
> holds even if a later lane registers something else against a search account.

> **Normative.** **The configured provider is also the granted recipient, and no
> `RecipientGrant` is established, read, extended or implied.** This supersedes **ADR-0193
> §3's first clause in its application to a `WEB_SEARCH` request at the configured
> provider**: coverage by a grant is not the route such a request takes to an `ALLOW`, and
> §2 below gives it its own. **ADR-0193 §3's five comparisons bind entire wherever a grant
> *is* the route** — on an email, on a fetch, on a tool call, and on a `WEB_SEARCH` at any
> destination that is not the configured provider — and **ADR-0193 §5 is relied upon and
> not superseded**: a grant still reaches the recipient and never the payload. Nothing here
> widens what a grant covers; it names a request that needs none.

> **Normative.** **Unconfiguring revokes, and it revokes by removing the subject rather
> than by recording a withdrawal.** Where `web_search_connection` and `web_search_origin`
> are unset, no registration exists, no request is composed, and the authority §2 states
> has nothing to attach to. §8(c) states what that does to a park.

**Why the rule is stated over the request and not over the destination.** The obvious
formulation — *"the configured provider's destination set reads `USER_CHOSEN`"* — would be
a fact about a destination, and a fact about a destination is readable by every kind. An
egress call of another kind that bound to that same set would inherit an authorisation the
owner gave about searching. That call is unreachable today, because the search
registration pins one origin and no other tool is registered against it; **unreachable
today is exactly the argument this corpus refuses to rest on** (ADR-0074 §1's own refusal
to argue a collision away by probability). Stating the rule over the request costs one
extra conjunct and closes it by construction.

**Why the comparison is stated at all, when the binder already pins the origin.** Every
`WEB_SEARCH` binding this corpus can build carries the registration's account and origin,
so the first clause's two conjuncts are presently total. They are written because §8(a)
owes the contract a statement of *what the authority covers*, because §8(b) and §8(c) are
unstateable without it, and for ADR-0098 §3's reason as ADR-0181 §5 quotes it: an actuator
rule is "free now and expensive later". The lane that adds a second provider, or registers
a second tool against a search account, finds the rule already written rather than
discovering it is owed.

### 2. Route (c): the ruling rests on the configuration, and the trail validates it without a store

> **Normative.** **ADR-0148 §3's first clause gains a third route, and the enumeration of
> what is not a user act takes one exception.** §3 rules that an `ALLOW` on an egress
> request requires every member of its canonical destination set to be covered by **(a)** a
> recorded resolution of a `CONFIRM` about this request or **(b)** a standing user policy
> established by a recorded act of the user, and its second clause names *"a configured
> base URL or host"* among the things that are **not** a user act. **This adds (c): the
> request is a `WEB_SEARCH` at the configured provider (§1).** ADR-0148 §3's second clause
> binds entire in every other limb — a tool's own declaration, the scope or audience of a
> credential, an allowlist the system assembled, a recipient appearing in a prior call, a
> destination extracted from a span — and on every other kind, including a configured base
> URL or host for an email.

> **Normative.** **The policy derives one fact and every relaxation reads it: the request
> is *at the configured provider*.** It is `binding.closed_loop` **and** §1's predicate of
> that same binding — `account.reference` equal to the configured connection reference, and
> canonical destination set equal to the configured one. **`closed_loop` alone is never the
> condition of any relaxation in this corpus after this decision**, and a lane that used it
> alone has reopened the hole §3's limbs are stated to close: §4 writes it before the
> binding exists, so it asserts *"this deployment's own search"* and cannot assert *which
> account and origin the binding carries*.

> **Normative.** **The policy is constructed with the two configured values to take that
> predicate.** `ThresholdActionPolicy` gains one constructor argument — the deployment's
> configured search destination, being the connection reference and the canonical
> destination set — beside the `RecipientGrants` it already takes. **This is not a store
> handle, a trail read, a grant seam or a conversation identity**, so ADR-0238 §5's clause
> forbidding those is untouched and its trust boundary is unmoved: the policy re-derives
> none of the carried facts and reads what `orchestration` wrote. **A policy constructed
> without it takes the predicate as false for every request**, which is the fail-closed
> direction and is the same shape ADR-0021 §3 gives a policy with no authorisation source.

> **Normative.** **Route (c) is reachable exactly where route (b) is reachable, and on the
> same five conditions.** `permissions/policy.py`'s `_only_the_disclosure_floor` keeps all
> five — with §3 restating two of them over the derived fact, and with a grant source no
> longer required for route (c) — and where it holds **and the request is at the configured
> provider**, the ruling is an `ALLOW` on route (c) **without consulting the recipient-grant
> seam at all**. Every other ground survives exactly as ADR-0193 §3 requires of a grant: an
> `UNKNOWN` cost still draws `CONFIRM`, a `risk_level` or `reversibility` at the policy's
> own threshold still draws `CONFIRM`, a threshold `DENY` still stands, and each reaches no
> route at all because `fired == [_DISCLOSURE_FLOOR]` is false for it.

> **Normative.** **A request carrying `closed_loop` that is *not* at the configured
> provider keeps every floor, and reaches route (b) in no case that route (b) does not
> already admit.** Because §3's two limbs read the derived fact, such a request planned over
> external content, or carrying covered content, fails `_only_the_disclosure_floor`
> outright: the grant seam is consulted **zero** times, no `ALLOW` is reachable however many
> grants the store holds, and the ruling is the `CONFIRM` ADR-0181 §5 and ADR-0233 §9
> require. **This is the case a reading that put the configuration check only on route (c)
> would leave open**, and it is closed by putting the check in the limbs rather than beside
> them.

> **Normative.** **Route (c) is taken before the grant seam is consulted, so no ruling at
> the configured provider ever cites a grant again.** Where both routes would be reachable
> for one request, (c) answers it, `_covering` is called **zero** times, and the recorded
> `authorised_by` is the connection reference.

> **Normative.** **A policy constructed with no `RecipientGrants` reaches route (c).** That
> is the one way route (c) differs from route (b)'s reachability, and it is the decision
> rather than an oversight: the authority route (c) cites is the deployment's own
> configuration, which the policy is handed no seam for and needs none, so ADR-0021 §3's
> *"a policy with no authorisation source leaves `authorised_by` unset"* is superseded **in
> the limb that reaches a request carrying `closed_loop`, and in no other**. On every other
> request a sourceless policy still sets neither field.

> **Normative.** **A route-(c) `ALLOW` sets `authorised_by` to the binding's
> `account.reference` and leaves `authorised_subject` unset.** ADR-0021 §5's disclosure
> floor forbids an `ALLOW` with `authorised_by` unset for a non-empty `discloses`, so the
> field is **owed** and is not a matter of taste; a pointer without a digest is the shape
> `PermissionRuling`'s own validator already admits for route (a). The pointer is not a
> string the policy invented: it is a value carried on the binding the seam derived, which
> is what the trail's own check below compares it against.

> **Normative.** **`authorised_subject` is unset on route (c), and its presence is what
> tells the two standing routes apart.** The digest exists for ADR-0004 §7's minimisation —
> a grant naming ten thousand recipients costs sixty-four characters rather than ten
> thousand destination entries — and route (c)'s subject is one origin the binding already
> carries in the clear, so a digest of it would add no fact an auditor could not read.
> **What the absence then buys is a discriminator**: a non-resolving egress `ALLOW` whose
> `authorised_by` is set is **route (b) where `authorised_subject` is set** and **route (c)
> where it is not**.

> **Normative.** **That discriminator reads nothing but the row, and it is total over every
> row written after ADR-0193's implementation.** §6's pairing clause **refuses** a
> standing-authorisation row that *"names standing authorisation … and fingerprints none"*,
> so **every route-(b) row written since then carries a digest** — including the closed-loop
> grant-covered `ALLOW` ADR-0238 permits and the tree drives. It therefore needs **no store
> read**, which is what ADR-0193 §9 requires — a revoked or cleared grant leaves a recorded
> decision's meaning intact — and **no assumption that grant ids and connection references
> are drawn from disjoint namespaces**, which they are not: both are `DurableIdentifier`,
> and an earlier revision of this section rested on a collision being unlikely. **A recorded
> decision's authority is readable from the decision.** What ADR-0193 §11 reserves — a
> digest-free pointer written before that implementation — is neither route, and the
> eligibility conjunct below is what excludes it.

> **Normative.** **The recipient-grant invariant is narrowed by that conjunct, and route
> (c) gets an invariant of its own that needs no store.** `AuditTrail.record`'s route-(b)
> scope — a non-resolving `ALLOW` with an `egress_binding` and `authorised_by` set — is
> narrowed by **and whose `authorised_subject` is set**, and ADR-0193 §6's pairing refusal
> becomes route (b)'s rather than every standing row's. This supersedes **ADR-0193 §6's
> pairing clause and the scope of its eight-check invariant, in that limb alone**; the
> eight checks themselves — the outstanding-grant read, both ends of liveness, tool
> equality, account equality, destination-set containment, the origin arm and the
> recomputed `subject_digest` — bind entire on every route-(b) row.

> **Normative.** **In its place the trail admits a digest-free standing row on two
> conditions and refuses it otherwise, and the refusal is the one it makes today.** A
> non-resolving `ALLOW` carrying an `egress_binding` and an `authorised_by` with **no**
> `authorised_subject` is accepted **only** where its binding's `closed_loop` is `True`
> **and** its `authorised_by` equals that binding's `account.reference`. Failing either, it
> is refused exactly as `_check_standing_shape`'s pairing clause refuses it at
> `origin/main`. Both facts are read from the decision — **no store read, no `Settings`
> read and no clock** — and the pointer half is `_check_authorisation`'s own reason stated
> one route over: *"Without this the pointer is a string a policy could invent."*

> **Normative.** **`closed_loop` is route (c)'s *eligibility* and the digest is its
> *discriminator*, and neither does the other's work.** The digest says which route a row
> claims, over the whole history and from the row alone; `closed_loop` says whether the row
> is of the one kind ADR-0148 §3's new route covers. **So an `ALLOW` on an email, a fetch or
> any other kind — whose binding carries `closed_loop` `False` — is refused with no grant
> exactly as it is today**, and a faulty policy cannot reach past the trail's independent
> enforcement by omitting a digest. **A lane that discriminated by `closed_loop`, or gave
> the trail a `Settings` value, has breached this clause**; so has one that admitted a
> digest-free row on the pointer alone.

> **Normative.** **The trail asserts what it can see, and the policy asserts the rest.**
> The trail holds no configuration, so it can never take §1's account-and-origin predicate;
> what it takes is the row's internal consistency and the kind. **Neither component is
> offered the other's job**, and a lane that let the policy skip the comparison has breached
> this clause as surely as one that gave the trail a `Settings` value.

> **Normative.** **A stored digest-free standing row whose binding carries `closed_loop`
> `False` is *neither* route, and ADR-0193 §11 governs it entire.** ADR-0193 §11
> contemplates such a row in terms — *"a pointer written before this ADR's implementation
> validated any"* — and rules that no surface distinguishes it from a grant the store still
> holds, from one erased and from one expired. **This ADR does not give it a basis it never
> had**, and no component reads it as a configuration authority. **The eligibility conjunct
> is what makes that exclusion exact rather than hopeful**: `closed_loop` was added to
> `EgressBinding` by ADR-0238, which lands after ADR-0193's implementation, so **no row
> predating that implementation can carry `closed_loop` `True`** and none is ever
> classified as route (c). ADR-0193 §11's three states, its non-distinguishing bar, its
> opaque-digest rule and its no-liveness rule bind entire, and this ADR adds no surface
> obligation to any of them.

> **Normative.** **No stored row is revalidated, rewritten or re-derived.**
> `AuditTrail.record`'s invariants are write-path checks; a decision ADR-0238 wrote keeps
> its `authorised_by`, its digest and its recorded meaning, and no read path applies route
> (c)'s pointer check or its eligibility conjunct to it. **No row of the
> route-(b)-with-`closed_loop` shape is written after this decision**, the ordering clause
> above seeing to that, and every one already written stays readable as what it was.

> **Normative.** **`OriginUnrecordedBinding` and `CoverageUnrecordedBinding` stay refused
> by name.** ADR-0184 §7's and ADR-0233 §14's ended-epoch refusals are untouched, and a
> binding that records no origin carries no `closed_loop` either, so no lane reads this
> section as making an unrecorded origin readable as a configured provider.

> **Normative.** **What a surface renders for route (c) names the basis and quotes no
> identifier.** The reason text says that this deployment's owner configured this search
> provider, and it names **no origin, no host, no connection reference, no credential and
> no `Settings` field**. `BoundAccount.reference` is *"never shown to the user"* (ADR-0148
> §6, §8's fourth clause) and this ADR does not move that: the reference is recorded on the
> decision for an auditor and is rendered to nobody. ADR-0193 §11's bar on what the audit
> surface renders binds on this route as it binds on route (b).

**Why a third route rather than reading the configuration as route (b).** Route (b) is *a
standing user policy established by a recorded act of the user*, and the corpus has a
store for exactly that, with a record, a subject digest, prospective revocation and a
data-right export. A configuration is none of those things: it has no record id, no
established-at instant, no revocation event and nothing for `ADR-0193 §6`'s eight checks to
re-read. Calling it a route-(b) act would either falsify those checks or force the trail to
read `Settings`, which it must not. Naming it (c) leaves ADR-0193's mechanism exactly as
ratified and puts this authority's own weaker invariant beside it, stated honestly: **what
the trail can check about route (c) is that the pointer matches the binding, and not that
any record authorises it.** That is less than route (b) offers, and it is said rather than
implied.

### 3. The lineage floor and the coverage exception both retire on such a request, and they retire together

> **Normative.** **ADR-0181 §5's second clause does not bind a `WEB_SEARCH` request at the
> configured provider.** On such a request an `ActionPolicy` returns `ALLOW` on §2's route
> (c) despite the binding carrying `planned_with_external_content`. **This supersedes
> ADR-0238 §6's first clause**, which made the same relaxation available to a *closed-loop*
> request under §5's four conditions, by replacing those conditions with §4's two. On every
> request that is not one, ADR-0181 §5's second clause binds exactly as ratified, and
> §5's remaining clauses, its memory-ruling-point clause and every other section of
> ADR-0181 are untouched.

> **Normative.** **ADR-0233's coverage exception does not bind it either, and the two
> retire in one act.** ADR-0233 §9's four conditions make a model-composed span approvable
> *by confirmation*, and route (c) is not a confirmation; ADR-0238 §7 opened the one
> exception this corpus admits, over three conditions of which the binding-carried fact is
> the one the policy can read.

> **Normative.** **Both limbs of `_only_the_disclosure_floor` are restated over §2's
> derived fact and not over `closed_loop`.** They become *"the binding does not carry
> `planned_with_external_content`, **or** the request is at the configured provider"* and
> *"the binding carries no covered content, **or** the request is at the configured
> provider"*. **That is a change of text, not only of reach**, and it is what makes the
> retirement exactly as wide as §1's predicate: a binding carrying `closed_loop` whose
> account or origin is not the configured one satisfies neither limb, so both floors bind on
> it in full. ADR-0238 §7's own sentence governs the remainder — *"Where any of the three
> fails, the clause forbids the span exactly as written"* — and is unmoved.

> **Normative.** **Retiring one without the other would change nothing, and the ADR says so
> rather than leaving it to be discovered.** A query a `QueryComposer` composed over
> `SearchSupply.records` is a model-composed span over covered content, so its
> `SpanCoverage` is `MODEL_ON_EVERY_PATH` whenever the supply carries a record at all. A
> deployment that lifted the lineage floor alone would still be stopped by the coverage
> limb on every query the milestone exists to compose, and one that lifted the coverage
> exception alone would still be stopped by the lineage floor on every turn that had read
> anything. **Both limbs are satisfied by one fact and are not two decisions.**

> **Normative.** **ADR-0155 §3's second clause, ADR-0233 §7 and ADR-0233 §9's four
> conditions are untouched and are not reachable from here.** A span carrying covered
> content some covered path of which contains **no** model call stays forbidden absolutely,
> whatever this ADR permits: `SpanCoverage.PATH_WITHOUT_MODEL` is refused by ADR-0233 §6's
> construction-time refusal before any policy sees it, and no clause here relaxes,
> conditions or routes around it. **The subject of this section is the model-composed
> subclass alone.**

> **Normative.** **`SearchSupply`, its populations and its construction site are
> untouched.** ADR-0238 §2's three populations, its single construction site and its trust
> clause bind entire — with §1 deciding what that trust clause answers for a search at the
> configured provider — and ADR-0246 §1's rule that `Placement.reach` does not bind at all
> on such a supply binds entire beside it. **No record-level fact is added, removed or
> re-read here.**

> **Normative.** **Nothing rides this that is not a `WEB_SEARCH` at the configured
> provider.** An email, a fetch, a tool call and a search bound anywhere else each keep
> ADR-0181 §5's floor, ADR-0193 §3 and §4, ADR-0155 §3 and ADR-0233 §9 exactly as written,
> in the very same conversation and the very same turn. **This is ADR-0238 §5's own last
> clause, restated because this ADR widens the exception it guards.**

### 4. What `closed_loop` becomes: two conditions, and the third and fourth retire

> **Normative.** **`CarriedProvenance.closed_loop`, and so `EgressBinding.closed_loop`, is
> written `True` exactly where the request's kind is `WEB_SEARCH` and this deployment holds
> a search registration — which `orchestration` knows because `WebSearcher.request`
> answered a proposal rather than `None` (ADR-0231 §17) — and `False` otherwise.** This
> supersedes **ADR-0238 §5's four-condition definition**: the second condition, a
> `trust_of` read at build time, is replaced by that fact, the **third** — every recorded
> external span the conversation has carried was minted by a `WEB_SEARCH` servicing at a
> chosen destination — is **retired**, and the **fourth** — the request holds an admission
> `admit_search` granted — is retired with the budget §5 removes. The field itself, its
> type, its `False` default, its carriage on `CarriedProvenance` and its comparison inside
> `PermissionDecision.authorises` are **unchanged**.

> **Normative.** **What that fact asserts is *"this is the deployment's own search"*, and
> what makes it an authority is §1's predicate taken at the ruling.** The carried fact is
> computed where every other carried fact is computed and before the binding exists; the
> account and the origin are compared where they exist. **Neither site is offered the
> other's job**, and a reader who takes §4's fact alone as the whole authority has dropped
> §2's second clause.

> **Normative.** **`all_external_user_chosen` retires with the third condition, and neither
> outlives the other.** The flag's only reader was §5's recorded half; the current-turn
> half's only reader was §5's live half; §8's early fold and capture fold exist only to
> maintain the flag. §5 below removes all of them in one act, which is the ruling's own
> sentence — *"Retiring one without the other changes nothing"* — applied to the mechanism
> that maintained it.

> **Normative.** **`closed_loop` is still written by `orchestration`, at the moment the
> request is built, and by nothing else.** It is discarded and never merged if any producer
> emitted one; no model output contributes to it; no component infers it, defaults it,
> repairs it or recomputes it downstream; and a lane computing it outside `orchestration`
> has breached this clause. **ADR-0238 §5's writer clause, its producer-discard clause, its
> trust-boundary clause and its `False`-decodes-for-a-pre-existing-row clause bind entire**
> — what moves is the value's definition, not its provenance.

> **Normative.** **The negative arm, restated over what it now protects.** **Outside
> content cannot change the destination**: §1's comparison is taken over the binding the
> seam derived from the deployment's own registration, and no value a model produced, a
> request carried, a search result contained or a record held reaches either side of it.
> **Outside content cannot make a request closed-loop**, because the two conditions are the
> kind and the configuration and neither is a fact a turn's content touches. **Outside
> content cannot reach a second destination**, because the transport pins every call to the
> registration's origin as text (ADR-0154's condition 5, ADR-0231 §8) and this ADR moves no
> word of that. **And credentials stay out structurally**: no composer holds a `Secrets`
> face, nothing in `planning/` or `orchestration/` reads the secret store, and the one
> residue is ADR-0231 §12's unchanged — a secret the user typed into their own utterance may
> be carried into a query, and no detector closes it (ADR-0098 §5, §6).

> **Normative.** **The condition is weaker than ADR-0238 §5's and this ADR states what it
> gave up.** Under §5, a conversation that had read a local file, an inbox, a calendar or
> an MCP result searched under ADR-0181 §5's floor for the rest of its life. Under this
> section it does not: a search at the configured provider is authorised whatever the
> conversation has carried, because the owner's ruling is that the destination bounds where
> the query goes and that this disclosure is accepted. **The property given up is real and
> is named here rather than in Consequences**: a prompt injected into a fetched file can
> steer *which of the owner's notes appear in a query* to the provider the owner chose. It
> cannot steer *where the query goes*, which is the arm above.

### 5. The per-conversation call budget is removed, and what bounds a conversation instead

> **Normative.** **`Settings.search_calls_per_conversation` is removed.** This supersedes
> **ADR-0238 §8's first clause** — the one `Settings` field, its default of 8, its domain of
> 0 through 64 and its `0`-means-no-search reading — and **§8's second clause**, which
> required the bound to ship with a value rather than mean unbounded when unset. No field
> replaces it, no default replaces it, and no per-conversation quantity is substituted.

> **Normative.** **`ConversationSearchDraw` is removed from `core/types.py`, and
> `ConversationStore` loses `search_draw`, `admit_search` and `observe_search`.** This
> supersedes **ADR-0238 §8's `ConversationSearchDraw` clause, its three-member clause, its
> signature clause, its atomicity clauses, its creation-value clause, its
> pre-existing-record clause, its early-fold clauses, its window clauses and its
> monotonicity clause**, and it is stated as a removal because the type has no field left
> once `calls` goes with the budget and `all_external_user_chosen` goes with §4's third
> condition. **This is a `core/protocols.py` change and therefore a BREAKING contract
> change** — golden rule 5 — which is why it is ratified here and merged before anything
> implements against it (ADR-0015).

> **Normative.** **`ConversationStore`'s obligation list returns to what ADR-0074 §9 states
> plus what ADR-0205 and ADR-0212 added, and this ADR adds nothing to it.** ADR-0238 §17
> recorded its three members as a supersession of ADR-0074 §9's enumeration; that
> supersession is **discharged** by this removal rather than deepened, and §14 records it on
> ADR-0074's own line. **ADR-0074 §7's retention reclaim, §8's deletion protocol and §9's
> exclusion obligation are untouched**: nothing is added to either sequence and no field is
> added to any type, exactly as ADR-0238 §8 intended when it put the counter where the
> lifecycle already was.

> **Normative.** **The two SQLite columns stay in the schema, are read by nothing and are
> written by nothing.** `_migrate_search_draw`'s `ALTER TABLE … ADD COLUMN` and the
> `conversations` table's `CREATE TABLE` keep `search_calls` and
> `all_external_user_chosen`, so a database written before this decision and one written
> after it have one shape. **No rebuild migration is performed and no column is dropped**:
> SQLite drops a column by rebuilding the table, which is a destructive act over the one
> table holding every conversation, and the two columns cost a deployment two integers per
> row. A lane that wants them gone needs the ADR that decides a table rebuild, and §13
> defers it with what fires it.

> **Normative.** **What bounds a conversation's searching after this is named, and nothing
> is claimed beyond it.** **Per turn**: ADR-0228 §4's planning budget gates the start of
> each additional planner call, so a turn that declares one starts at most two planner
> calls and therefore at most two searches, and an operation declaring none does not
> iterate at all. **Per search**: ADR-0241 §1's deadline bounds one servicing's search
> work, and ADR-0231 §5's `search_max_results`, `search_max_result_chars` and
> `search_max_response_bytes` bound what comes back. **Per money**: ADR-0194's optional
> spend ceiling, admitted at the seam over ADR-0236's declared per-call figure, and
> ADR-0016 §4's unknown-cost floor where no figure is declared. **Per conversation: nothing
> bounds the number of searches**, and that is the decision rather than an omission. Every
> turn is owner-initiated, so the count is bounded by how many times the owner asks.

> **Normative.** **Two of ADR-0238's deferrals are dissolved rather than discharged.** Its
> *"rolling window for §8's bound"* has no bound to roll, and its *"per-conversation bound
> on elapsed search time"* had, as its stated purpose, a product of the call ceiling and a
> per-servicing quantity. **Neither is decided here and neither is forbidden**: §13 restates
> both over the state this ADR leaves, with what fires each.

> **Normative.** **#1908's "enforced budget" sentence is not edited by this ADR, and this
> ADR does not edit any issue.** The sentence names a per-conversation call budget that
> stops existing; what it should point at is ADR-0228 §4's planner-pass limit and ADR-0194's
> spend ceiling, per the owner's ruling 3. **The dispatcher makes that edit on #1908**, and
> the implementing lanes make none.

**The owner's own trigger for revisiting this is recorded rather than paraphrased.**
*"Revisit if planner passes, batching or unattended work expand."* Each of those is a
change to the sentence "every turn is owner-initiated", which is the whole of what makes an
unbounded per-conversation count acceptable. §13 states it as a deferral with exactly that
trigger.

### 6. What the removal takes with it, member by member, and what it leaves standing

> **Normative.** **`SearchDisposition.NOT_ADMITTED` is removed, and the enumeration closes
> at seventeen.** Its only producer was `admit_search` refusing. This supersedes **ADR-0238
> §11's closure of that enumeration**, as ADR-0241 left it at eighteen, **in that count
> alone**: the remaining members, their values, the injectivity of every mapping into it,
> its no-message rule, its exclusion of `SearchRefusal.NO_RESULT` and its audit clauses
> stand entire, and no lane reads this as licence to remove an eighteenth.

> **Normative.** **`SearchNotServiced.SEARCH_DISABLED` and `SearchNotServiced.NOT_ADMITTED`
> are removed, and the enumeration closes at seven.** Both are defined over `admit_search`'s
> refusal and over `Settings.search_calls_per_conversation`'s value, and neither has a
> producer once §5 lands. This supersedes **ADR-0242 §8's closure at eight members and its
> two-members-not-one clause**, and **ADR-0244 §12's re-closure at nine in its count alone**.
> **Removing the first two members leaves every remaining pairwise order and every
> remaining value unchanged**, so ADR-0242 §7's precedence order, the totality and
> non-injectivity of §8's mapping, the added-to-and-never-renamed rule and §9's bar on what
> a statement may say all stand entire.

> **Normative.** **`SearchNotServiced.TRUST_MISSING` and
> `SearchNotServiced.AUTHORISATION_AWAITED` are *not* removed, and no lane removes them.**
> Both become unreachable on a deployment that has configured a search provider —
> `TRUST_MISSING` is defined over a `trust_of` read answering `UNCHOSEN`, which §1 stops
> taking, and `AUTHORISATION_AWAITED` records a `CONFIRM` the establishing act could ride,
> which §3 stops producing for this path. **Removing them is outside the owner's ruling**,
> which named the budget and its dependents and left the choosing act standing for every
> other destination. The finding is recorded as an issue and §13 defers it with what fires
> it.

> **Normative.** **`ReadAnswerOutcome` keeps all seven members, and `UNAVAILABLE_NOW` loses
> one of its three grounds.** ADR-0244 §9 defines it as *"the conversation no longer exists
> or is stamped deleted, **or** `search_calls_per_conversation` is `0` in this
> deployment"*, and `orchestration/parked_reads.py` adds a third — the deployment holds no
> searcher. **This supersedes ADR-0244 §9's definition of that member in its
> `search_calls_per_conversation` limb alone**; the other two grounds bind entire, the
> member keeps its name, its value and its position in §9's precedence order, and no
> member is added or removed.

> **Normative.** **ADR-0244 §6's clause 2 is superseded and replaced by a read of
> `ConversationStore.get`.** Clause 2 establishes, at the instant of the answer, that
> *"`search_draw` answers a draw for `conversation_id` … and
> `Settings.search_calls_per_conversation` is not `0`"*. With both gone, the fact that
> clause was establishing is **that the conversation exists and is not stamped deleted**,
> and `get` answers it by the same rule — *"`None` when the id names nothing **or** names a
> conversation stamped deleted"* — with no Protocol member added and none widened. Clause
> 2's remaining sentence binds entire: **`admit_search` is not called and no second call is
> drawn** becomes vacuous rather than false, because there is no call to draw.

> **Normative.** **ADR-0244 §6's other five clauses, its ordering and its gate bind
> entire**, as do §§1–5, §7, §8, §§10–23. In particular §6's *"`trust_of` is not asked again
> and no destination's recorded trust is written"* stays true and is **strengthened** by
> §1: `trust_of` is not asked at the park either. And §6's *"the approval is the authority,
> and it is ADR-0148 §3's route (a)"* is unmoved — a park that is answered is authorised by
> the answer, never by §2's route (c), and no lane reads route (c) as reaching a resumed
> call.

> **Normative.** **ADR-0238 §11's audit keeps its event, its key and its counts, less
> one.** The per-turn record's *"this turn's `calls`"* goes with the draw; the count of
> records supplied to the composer and ADR-0246 §7's supplied-narrowed count stay, as does
> ADR-0245's withheld count at its zero. This supersedes **ADR-0238 §11's second clause in
> its `calls` limb alone**; its one-event rule, its one-key rule, its counts-only rule, its
> no-identifier rule and its refusal to write the destination's trust to the event bind
> entire.

> **Normative.** **ADR-0246 §11's Arm F′ is superseded in its `calls` limb, and is restated
> over three counts.** That arm requires the event to record *"the supplied count, the
> withheld count at **zero**, this turn's `calls` and the supplied-narrowed count at
> **two**"*, and closes with *"restated here so the arm cannot be satisfied by dropping a
> field §7 keeps"* — a sentence written against a lane dropping a field for convenience,
> which is a different act from an ADR removing the quantity. **The arm binds entire on its
> other three counts, on its each-at-its-true-value requirement and on its
> one-identifier-and-no-other rule**, and a lane owes it in that form: a turn carrying an
> admitted `DERIVED` narrowing and an admitted `OWNER_ACT` one records the supplied count,
> the withheld count at zero and the supplied-narrowed count at two, carrying the ambient
> correlation identifier and no other. **Every other arm of ADR-0246 §11 binds entire**,
> and §1's rule that `Placement.reach` does not bind at all is untouched.

> **Normative.** **Nothing else is removed.** `SearchSupply`, `DestinationTrust`,
> `DestinationTrustRecord`, `DestinationTrustStore`, `EgressBinding.closed_loop`,
> `CarriedProvenance.closed_loop`, `ParkedRead`, `ParkedReads`, `Confirmation.read`,
> `TurnOutcome.read_confirmation`, `TurnOutcome.read_answer`, `SearchRefusal`,
> `ConversationExport.schema_version` and every `Settings` field but the one §5 names stay
> exactly as they are.

### 7. `rebind` transcribes `closed_loop`, and a park written before this decision is unmoved

> **Normative.** **`EgressBindingSeam.rebind` takes `closed_loop` from `approved`, matched
> to the binding it re-derived, exactly as it takes `provenance`,
> `planned_with_external_content` and `coverage`.** This supersedes **ADR-0152 §7's
> transcription count** — already moved from one to two by ADR-0181 §3 and to three by
> ADR-0233 §4 — **in that count alone, which becomes four**. Every other clause of §7 binds
> entire: the derivation is otherwise afresh and subject to every clause of ADR-0152 §5 and
> §6; the refusal unless the derived binding **equals** `approved`, whole and by value; the
> refusal of an unmatched `provenance`; the `None`-returning and refusing limbs of §8's
> partition; and the returned call carrying the binding it **derived** and never the one it
> was given.

> **Normative.** **ADR-0238 §5's non-transcription clause is superseded.** That clause
> states that `closed_loop`'s `False` default *"keeps ADR-0152 §7's transcription count
> untouched"* and that `rebind` *"transcribes nothing new and constructs `False` — the
> correct value for every request that can resume"*. Its premise was that a `CONFIRM` on a
> `WEB_SEARCH` decision resolves in no turn, so no closed-loop request is ever resumed;
> **ADR-0244 falsified that premise by making such a `CONFIRM` a durable park that can be
> answered**, and #2232 is the defect. The field's `False` **default** is not superseded and
> stays: it is still the restrictive value and still what a binding decodes to where nothing
> wrote one.

> **Normative.** **What this repairs is stated exactly.** After §3, a search at the
> configured provider still draws `CONFIRM` on a ground route (c) does not discharge — an
> `UNKNOWN` per-call cost (ADR-0016 §4, ADR-0236), or a `risk_level` or `reversibility` at
> the operator's threshold (ADR-0021 §5, ADR-0036) — and such a request parks under
> ADR-0244 with `closed_loop` **`True`**. Under the transcription-free `rebind`, the
> re-derived binding carries `False`, compares unequal to the approved one, and the answer
> is `OPERATION_CHANGED`: **a park nobody could ever answer.** With the transcription, the
> two compare equal and the read runs.

> **Normative.** **No park is migrated, re-derived, rewritten or repaired, and what the
> transcription does to an existing one depends on the value that park already stores.**
> **A park whose recorded binding carries `closed_loop` `False` answers exactly as it does
> today**, `False` being the literal the old code passed, so the transcription changes no
> byte of its outcome — and that is every park a deployment with no recorded trust act can
> hold, which is every production deployment (§Context). **A park whose recorded binding
> carries `True` becomes answerable**, where before it was refused at every answer.

> **Normative.** **Such a park is reachable under ADR-0238 as ratified, and an earlier
> revision of this section wrongly said it was not.** A deployment that recorded a trust
> act, on a clean conversation with allowance left, binds `closed_loop` `True`; the
> unknown-cost floor (ADR-0016 §4, ADR-0236) or an operator threshold then draws `CONFIRM`
> on a ground route (b) never discharged; and ADR-0244 parks it. **That park is #2232 as it
> stands in the tree today**, and making it answerable is the repair rather than a side
> effect of it. **No stored binding is touched**: `rebind` reads the `True` the trail
> already holds, derives an equal one, and the read runs — which is the same act the
> approval always authorised and could never reach.

> **Normative.** **No second fact is transcribed and no count is opened.** Four is the
> count, `rebind` receives nothing else from `approved`, and a lane that finds a fifth owes
> the ADR that decides it. **`PermissionDecision.authorises` is untouched** and still
> compares the whole binding, `closed_loop` among its members, for no reason special to it.

### 8. The contract for configuration-based authority

> **Normative.** **(a) What the authority covers.** It covers a request whose kind is
> `WEB_SEARCH`, whose binding's `account.reference` equals `Settings.web_search_connection`
> and whose canonical destination set is the one `Settings.web_search_origin` canonicalises
> to — **that account and that origin, and no other.** A request to any other origin, or
> through any other connection, is **not covered**: it takes no route (c), keeps ADR-0181
> §5's floor and ADR-0233's coverage rule, and confirms or is refused exactly as it does
> today. The credential is **not** part of the comparison, because no credential value is in
> a binding at all (ADR-0148 §6) and the connection reference is what names the record the
> credential is read from (ADR-0149 §3).

> **Normative.** **(a′) The authority is read per request, from the configuration the
> running deployment holds, and is never cached, carried or held across a composition.**
> This is ADR-0238 §5's own posture for the trust read, kept: the comparison is taken at the
> instant the request is built, beside the binding's construction, with nothing awaited
> between them.

> **Normative.** **(b) A change to the configured origin or connection ends the authority
> for every later request, and rewrites no recorded decision.** Prospectivity is ADR-0193
> §9's shape, and this ADR claims nothing stronger: a request whose comparison had already
> been taken is not stopped by a configuration change recorded after it, for the reason
> ADR-0193 §9, ADR-0074 §8 and ADR-0007 §4 each give for declining a cross-store
> linearisation. A request built after the change compares against the new values and takes
> route (c) only if it matches them.

> **Normative.** **(b′) An open park bound to a previous configuration is refused at the
> answer, by a mechanism ADR-0244 already provides and this ADR adds nothing to.**
> `EgressBinder.rebind` derives the binding afresh from the **current** registration
> (ADR-0152 §7, ADR-0244 §6 clause 4), so a changed origin or a changed connection makes
> the derived binding unequal to the recorded one, nothing is dispatched, the park stays
> `OPEN`, and the answer is **`OPERATION_CHANGED`** (ADR-0244 §9). That is ADR-0148 §6's
> fourth clause reaching one stage earlier, and its own sentence is the reason: *"a registry
> rebuilt under a different configuration — across a restart, which is exactly when a parked
> `CONFIRM` is answered — refuses the call rather than performing it against another account
> or another endpoint."*

> **Normative.** **(b″) A rotated credential changes nothing, and this is ADR-0148 §6's
> own ruling rather than a new one.** A binding carries the account's identity and
> connection reference and **no credential value**, and §6 states the consequence in terms:
> *"The reference is therefore stable across a rotation, which is what keeps a parked
> `CONFIRM` answerable after one"*. So rotating the secret behind an unchanged reference
> leaves §1's comparison equal, leaves the derived binding equal to the recorded one, and
> leaves standing authority and an open park exactly where they were. **No lane adds a
> check for it.** Whether the rotated credential *works* is the transport's answer at the
> send, and is a `SearchRefusal` rather than an authorisation question.

> **Normative.** **(c) Unconfiguring revokes by leaving no registration, and an open park
> answers `UNAVAILABLE_NOW`.** With `web_search_connection` and `web_search_origin` unset
> the deployment holds no searcher: `WebSearcher.request` is never reached, the servicing
> reports `SearchDisposition.NOT_CONFIGURED`, no request is composed and no authority is
> cited. **`orchestration/parked_reads.py` already answers `UNAVAILABLE_NOW` on exactly that
> fact, before it reads anything per-conversation**, so this limb of the contract is
> **relied upon rather than added**: the park stays `OPEN`, nothing is ruled, nothing is
> dispatched, and the park settles `EXPIRED` on its own deadline under ADR-0244 §10. **No
> lane settles an open park on a configuration read** — ADR-0244 §6's gate clause forbids
> settling an `OPEN` park on the strength of a record it read, and a `Settings` value is
> not an exception to it.

> **Normative.** **(d) The recorded authority is the connection reference on the ruling and
> the origin on the binding, and an auditor reads both off one row.**
> `PermissionRuling.authorised_by` carries the binding's `account.reference` (§2), and the
> binding carries the account's identity and the canonical destination set the origin
> canonicalised to. **So "which configuration authorised this" is answerable from the
> recorded decision alone**, with no `Settings` read, no store read and no join. ADR-0192's
> invocation row carries the same account by its own existing rule and this ADR adds no
> field to it, no member to `InvocationLedger` and no second record.

> **Normative.** **(d′) What the recorded authority does *not* assert.** It does not name a
> user act with an instant, an id or a revocation event, because there is none: a
> configuration has no record in ADR-0193 §1's sense. **An auditor reading a route-(c) row
> learns which account and origin this deployment was configured with when the ruling was
> taken, and nothing about when or by whom that configuration was made.** That is strictly
> less than route (b) records, and it is stated rather than glossed; §13 defers the
> question of a durable, dated record of the configuring act with what fires it.

### 9. Unchanged, by name

> **Normative.** **Each of the following is untouched by every clause of this ADR, binds
> entire, and no lane reads any section above as moving it**: the unknown-cost floor
> (ADR-0016 §4, ADR-0236 §1, §4); the risk and reversibility thresholds, and a `DENY`
> taking its own exit (ADR-0021 §5, ADR-0036 §1); the search deadline (ADR-0241 §1, §4);
> the spend ceiling and the ledger (ADR-0194, ADR-0192); the response bounds (ADR-0231 §5);
> Tier 0's floor (ADR-0199 §3, ADR-0004 §2, §5); the park, one open per conversation, and
> everything ADR-0244 decides about it beyond §6's clause 2 and §9's one limb; ADR-0226 §5's
> audience refusal; ADR-0246 §1's rule that `Placement.reach` does not bind on a chosen
> destination's supply; ADR-0228 §4's planning budget; and ADR-0231 §11's servicing order
> and §16's no-retention sentence.

> **Normative.** **Fetch inherits nothing.** Milestone 32's bounded fetch is a different
> kind, at destinations nobody configured, over content a provider returned. **No clause of
> this ADR reaches it, and the ADR that decides it may not cite any clause of this one as
> precedent for a loosening** — not §1's configuration-as-choosing-act, not §2's route (c),
> not §3's retirements and not §5's removal of a bound. ADR-0238 §16's deferral of
> everything about an `UNCHOSEN` destination stands untouched, and the owner's own sentence
> is the rule: *"Fetch (milestone 32) gets its own rules and inherits none of these
> loosenings."*

### 10. The `core` surface, the version, and what a record written before this decodes to

> **Normative.** **The `core` surface this decision changes is exactly this and no more.**
> In `core/config.py`: `search_calls_per_conversation` is **removed**, and no field is
> added. In `core/types.py`: `ConversationSearchDraw` is **removed**;
> `SearchNotServiced` loses `SEARCH_DISABLED` and `NOT_ADMITTED`; and **no other type gains,
> loses or changes a field, a default or a member** — `EgressBinding`, `CarriedProvenance`,
> `PermissionRuling`, `PermissionDecision`, `BoundAccount`, `CanonicalDestination`,
> `SearchSupply`, `DestinationTrust`, `DestinationTrustRecord`, `ParkedRead`,
> `ReadAnswerOutcome`, `Conversation`, `ConversationTurn` and `ConversationExport` are
> untouched. In `core/protocols.py`: `ConversationStore` loses `search_draw`,
> `admit_search` and `observe_search`, and **no other Protocol changes a member, an
> argument or a return** — `ActionPolicy`, `AuditTrail`, `MemoryStore`, `WebSearcher`,
> `QueryComposer`, `DestinationTrustStore`, `RecipientGrants`, `ParkedReads` and
> `InvocationLedger` are untouched. In `core/errors.py`: nothing.

> **Normative.** **This is a BREAKING contract change and is flagged as one.**
> `ConversationStore` is narrowed, which golden rule 5 makes a decision its own ratified
> ADR must carry ahead of any implementation, and this is that ADR. **No conformance suite
> is added and no triad is owed** — no Protocol is created — and the existing
> `ConversationStore` conformance suite and its canonical fake in `ai_assistant.testing`
> lose the three members' assertions in the same change that removes them.

> **Normative.** **`PROTOCOL_VERSION` moves 35 → 36**, and `wire/envelope.py`'s log gains an
> entry naming this ADR and this reason: `SearchNotServiced` is carried on
> `TurnOutcome.search_not_serviced`, `TurnOutcome` crosses the wire, and a **narrowed**
> vocabulary is a shape change in ADR-0178 §6's sense — a peer at 36 handed
> `"search_disabled"` or `"not_admitted"` by a peer at 35 fails to decode it. **The three
> `ConversationStore` members are not a second ground**: they are in-process reads and
> writes no peer emits, exactly as `wire/envelope.py` records of their addition, and
> removing them emits nothing either. **`ConversationExport.schema_version` stays at 2**,
> ADR-0212 §8 and ADR-0014 §5 are untouched, and no row is minted in ADR-0087 §2c's scalar
> table.

> **Normative.** **The move covers the shape going forward and repairs nothing already
> released.** A hub at 36 never emits the two removed members, so a client at 35 decodes
> everything it is sent; a client at 36 handed an older hub's value fails, which is what the
> version exists to make legible rather than silent.

> **Normative.** **A conversation record written before this decision loses nothing and
> gains nothing.** Its `search_calls` and `all_external_user_chosen` columns stay on disk,
> are read by no code and decide nothing (§5); no back-fill, inference, repair or
> reconstruction is performed on any of them; and a conversation whose flag reads `False`
> searches after this decision exactly as one whose flag reads `True` does, because neither
> is read. **A conversation in progress when the implementing lanes land behaves as this ADR
> rules from its next turn**, with no migration and no carried state.

> **Normative.** **A stored `PermissionDecision` is untouched, and some of them carry
> `closed_loop` `True`.** ADR-0238 permits a route-(b) `ALLOW` on a closed-loop request
> covered by a grant, and `tests/orchestration/test_engine_search_not_serviced.py` drives
> one through the production engine, so *"`False` for every decision this corpus has ever
> written"* would be a false claim and is not made. **No lane back-fills, re-derives,
> repairs or re-validates any stored row**; §7's transcription reads the stored value and
> does not change it; and §2's clause on historical rows says how an auditor tells a
> route-(b) closed-loop row from a route-(c) one.

### 11. What the implementing lanes owe, cut at ADR-0137 §2's seam

> **Normative.** **Four lanes, in the order below, each its own PR.** Lanes 1 and 2 are
> independent of each other and may run in parallel; lane 3 depends on lane 1; lane 4
> depends on lane 3.

> **Normative.** **Lane 1 — the authority, in `permissions/` alone.** §2's route (c) in
> `ThresholdActionPolicy.decide`: the one new constructor argument carrying the configured
> search destination; §2's derived *at the configured provider* fact, taken over the
> request's binding; **both limbs of `_only_the_disclosure_floor` restated over it** (§3),
> which is the change that keeps the floors on a mismatched binding; the `ALLOW` with no
> grant seam consulted, taken **before** `_covering` is reached; `authorised_by` set to the
> binding's `account.reference`; `authorised_subject` unset; and a reason naming the basis
> and no identifier. In `permissions/audit.py`: the route-(b) scope narrowed by
> **`authorised_subject is not None`** — **not** by `closed_loop`, which §2 reserves for
> eligibility — ADR-0193 §6's pairing refusal moved inside that scope, and the route-(c)
> branch admitting a digest-free standing row **only** on `closed_loop` **and** the pointer
> equality and refusing it otherwise. **No `Settings` value reaches the trail.** Every arm of
> §12 that names lane 1 lands in the `AuditTrailContract` suite in the same change. **`app/composition.py` supplies the new
> argument**, which is the one file outside `permissions/` this lane touches and is the
> composition root's own job. **It lands before lane 3 and changes no live behaviour on its
> own**, because no production deployment has a recorded trust act and so nothing yet
> writes `closed_loop` `True` there.

> **Normative.** **Lane 2 — #2232, in `tools/` alone.** §7's fourth transcription in
> `EgressBindingSeam.rebind`, its arm, and the comment beside it replaced rather than left
> stating a premise ADR-0244 falsified. **One line of behaviour and its tests**, and it
> rides alone because it is correct independently of every other lane and closes an open
> defect on the resumable path.

> **Normative.** **Lane 3 — the carried fact, in `orchestration/` alone.** §1's
> registration fact in place of `SearchFooting.trusted`'s two `trust_of` reads, and §4's
> `closed_loop` at `SearchServicer.service`'s binding site, written after
> `WebSearcher.request` has answered a proposal and before `_bound` is called — **the same
> position the current argument occupies, with no await added between that value and the
> `EgressBinding`'s construction.** The composition root already holds the two configured
> values; **the lane adds no `Settings` read below `orchestration`, no store handle, and no
> comparison against a binding.** The budget mechanism is left standing and untouched here
> — it still admits, still folds, and still refuses at the bound — so that this lane's diff
> is the authority fact and nothing else.

> **Normative.** **Lane 4 — the contract removal, and it is the one cross-subsystem change
> this ADR sanctions.** `core/config.py`, `core/types.py`, `core/protocols.py`,
> `memory/conversation_store.py`, `testing/conversations.py`, `orchestration/reads.py`,
> `orchestration/parked_reads.py`, `orchestration/loop.py`, `app/composition.py` and
> `wire/envelope.py`, in one change. **The cut is forced and is named rather than
> improvised**: a Protocol member's removal and the deletion of its implementations, its
> canonical fake, its conformance assertions and its callers are one unit, because any
> smaller cut leaves a tree that does not type-check. This is the same seam ADR-0137 §2
> recognises for a triad, applied to a narrowing rather than an addition, and **no other
> lane of this ADR crosses a subsystem boundary**.

> **Normative.** **Lane 4's contents, enumerated so that nothing rides along.** Remove
> `Settings.search_calls_per_conversation` and its `Settings` tests; remove
> `ConversationSearchDraw`; remove `ConversationStore.search_draw`, `admit_search`,
> `observe_search`, their `SqliteConversationStore` implementations, their
> `FakeConversationStore` implementations and their conformance assertions; remove
> `SearchDisposition.NOT_ADMITTED` and `SearchNotServiced.SEARCH_DISABLED` and
> `NOT_ADMITTED` with the CLI's two `match` arms; delete `SearchFooting`'s `admit`,
> `footing`, `admitted`, `observe`, `clean`, `_place`, `_lower`, `_fold`,
> `minted_user_chosen`, `conversation_episodes`, `selected`, `_lowered`, `max_calls` and
> `conversations`; drop `counts.calls` from ADR-0238 §11's audit event; repoint
> `orchestration/parked_reads.py`'s clause 2 at `ConversationStore.get` and delete its
> `max_calls == 0` limb; and move `PROTOCOL_VERSION` to 36 with its log entry. **The two
> SQLite columns and their migration stay** (§5).

> **Normative.** **Every lane corrects, in its own change, every docstring and comment that
> cites a rule it moved**, including `permissions/policy.py`'s `_FLOORS` note and
> `_only_the_disclosure_floor`'s five bullets, `tools/egress_binder.py`'s `closed_loop`
> comment, `orchestration/reads.py`'s `SearchFooting` and `SearchDisposition` docstrings,
> `core/types.py`'s `SearchNotServiced` docstring and `wire/envelope.py`'s version log. A
> module describing a check the tree does not have is a false statement these decisions
> create, and it is not a second change.

> **Normative.** **No lane re-drives the mechanism on a live hub and none is asked to.** A
> deployment is owed after lane 4, because `PROTOCOL_VERSION` moves; that is the
> dispatcher's act and not a lane's.

> **Normative.** **No lane files or defers anything this ADR has not named.** Findings
> outside a lane's change are issues under `CONTRIBUTING.md`'s triage rule, not growth of
> its PR.

### 12. The representative-input tests this decision owes

> **Normative.** Each arm is a test the owning lane owes, over the **production** policy,
> trail, binder, servicing path and store, and not over a double standing in for one of
> them. **ADR-0238 §15's Arms 1a, 2, 5b and 5c bind in the restated forms below; Arms 3, 4,
> 6 and 6b are replaced or retired as stated; and ADR-0246 §11's arms bind entire.**

> **Normative.** **Arm A — a search planned over outside content is `ALLOW`ed with no grant
> record (lanes 1, 3).** A turn that has read a local file and then searches, on a
> deployment whose `RecipientGrants` store is **empty** and whose `DestinationTrustStore`
> holds **no record**, binds `closed_loop` `True`, draws an `ALLOW` on route (c) whose
> `authorised_by` is the binding's `account.reference` and whose `authorised_subject` is
> unset, is recorded by `AuditTrail.record` rather than refused, and asks the user nothing.
> **The grant seam is consulted zero times**, asserted over the seam and not over the
> ruling.

> **Normative.** **Arm B — a query composed over stored records takes the same route (lanes
> 1, 3).** With the supply carrying memory records, so that the binding's `coverage` is
> `MODEL_ON_EVERY_PATH`, the ruling is the same `ALLOW`, which is the arm that asserts §3's
> second retirement rather than only its first. **Arm B′**: with `planned_with_external_content`
> `False` **and** `coverage` `MODEL_ON_EVERY_PATH`, the same `ALLOW` — so a lane that
> retired only the lineage limb fails here.

> **Normative.** **Arm C — a binding that carries `closed_loop` but is not at the
> configured provider keeps every floor, with a covering grant in the store (lane 1).** The
> binding carries `closed_loop` **`True`** — which §4 makes the value a mismatched
> `WEB_SEARCH` proposal still produces — and its `account.reference` or its canonical
> destination set differs from the policy's configured search destination by one character.
> With `planned_with_external_content` `True` and **a grant covering the request in the
> store**, the ruling is `CONFIRM`, the grant seam is consulted **zero** times, and no
> `ALLOW` of any route is reached. **Arm C₂ — the same over coverage**: the binding carries
> `MODEL_ON_EVERY_PATH` and no external content, and the same mismatch draws the same
> `CONFIRM`. **These two are the arms that fail a lane which put the configuration check
> beside the route rather than inside the floor's limbs.**

> **Normative.** **Arm C′ — a policy with no configured destination reaches nothing (lane
> 1).** Constructed without the new argument, the policy takes the predicate as false for
> every request: an otherwise perfect route-(c) request draws `CONFIRM`, and a route-(b)
> request that never carried `closed_loop` rules exactly as it does at `origin/main`.

> **Normative.** **Arm C″ — the cross-kind arm, restating ADR-0238 §15 Arm 5c**: a
> `send_email` and a non-`WEB_SEARCH` egress call planned over outside content in the same
> conversation each bind `closed_loop` `False` and confirm exactly as today.

> **Normative.** **Arm D — the trail tells the two standing routes apart by the digest
> alone (lane 1).** A non-resolving `ALLOW` with an `egress_binding`, `authorised_by` set
> and **`authorised_subject` set** is validated against the grant store by ADR-0193 §6's
> eight checks exactly as today; one with `authorised_subject` **unset** reads that store
> **zero** times and is refused if and only if its `authorised_by` is not its binding's
> `account.reference`. **Asserted with `closed_loop` `True` on both rows**, so a lane that
> narrowed the scope by `closed_loop` instead fails it. **This replaces ADR-0238 §15 Arm
> 5b's premise** and keeps its `OriginUnrecordedBinding` limb: such a decision is refused by
> name in both cases.

> **Normative.** **Arm D″ — a digest-free standing row of another kind is refused (lane
> 1).** A non-resolving `send_email` `ALLOW` with a valid binding whose `closed_loop` is
> `False`, `authorised_subject` unset and `authorised_by` equal to the binding's
> `account.reference`, with **no grant in the store**, is **refused** by
> `AuditTrail.record`, exactly as it is at `origin/main`. The arm exists because the digest
> alone would have admitted it, which is the hole §2's eligibility conjunct closes, and it
> is asserted for a fetch and a tool call beside the email so that no kind is admitted by
> the shape alone.

> **Normative.** **Arm D′ — the discriminator survives an emptied grant store and an
> identifier collision (lane 1).** A route-(b) row recorded and then read back after
> `RecipientGrantStore.clear()` still reads as route (b) and is not re-validated,
> re-derived, rewritten or refused, which is ADR-0193 §9's requirement. **And with a grant
> whose `id` is byte-identical to the binding's `account.reference`**, a route-(b) row and a
> route-(c) row are still told apart, because the digest and not the pointer decides. The
> arm exists because both reviews of this ADR's second round found the pointer-based reading
> unsound on exactly these two inputs.

> **Normative.** **Arm D‴ — the row ADR-0193 §11 reserves is classified as neither route
> (lane 1).** A stored non-resolving egress `ALLOW` with `authorised_by` set, no
> `authorised_subject`, and a binding whose `closed_loop` is `False` — §11's pre-implementation
> pointer — is read back unchanged, is not re-validated, and is reported by no component as
> a configuration authority. The arm is asserted over the stored row rather than over
> `record`, because `record` refuses that shape going forward and the question here is what
> history reads as.

> **Normative.** **Arm E — a park with `closed_loop` `True` is answerable (lane 2).** A
> `WEB_SEARCH` at the configured provider that draws `CONFIRM` on an independent ground — an
> `UNKNOWN` per-call cost — parks; the answer rebuilds the request, `rebind` derives a
> binding equal to the recorded one, and the read **dispatches**. Asserted to fail before
> the transcription lands. **Arm E′ — a park written under the old binder is unmoved**: a
> park whose recorded binding carries `closed_loop` `False` answers exactly as it does
> today, and the transcription changes no byte of its outcome. **Arm E″ — a pre-existing
> `True` park becomes answerable, and its stored row is not rewritten**: a park recorded
> **before** lane 2, whose binding carries `closed_loop` `True` and whose decision the
> unknown-cost floor drew, is refused with `OPERATION_CHANGED` on the old binder and
> **dispatches** on the new one, with the stored binding byte-identical before and after —
> which is §7's own case and the one Arm E′ does not reach.

> **Normative.** **Arm F — a configuration change refuses an open park (lanes 2, 3).** With
> a park open and the deployment's `web_search_origin` then changed, the answer derives an
> unequal binding, dispatches nothing, leaves the park `OPEN` and returns
> `OPERATION_CHANGED`. **Arm F′ — a rotated credential does not**: with the connection
> reference and origin unchanged and the stored secret replaced, the same park answers and
> the read dispatches.

> **Normative.** **Arm G — unconfiguring turns an open park's answer into
> `UNAVAILABLE_NOW` (lane 4).** With a park open and the deployment holding no search
> registration, the answer rules nothing, dispatches nothing and returns `UNAVAILABLE_NOW`;
> the park is still `OPEN`. The arm exists over the production `parked_reads` path because
> lane 4 deletes the `max_calls == 0` limb beside it and must not disturb this one.

> **Normative.** **Arm H — nothing bounds a conversation's search count (lane 4).** A
> conversation makes more searches than `search_calls_per_conversation`'s former default
> without a refusal, no disposition naming an allowance is reachable, and the turn-level
> bound still holds: a turn whose operation declares a planning budget starts at most two
> planner calls and therefore at most two searches. **This replaces ADR-0238 §15 Arms 3, 6
> and 6b entire**, whose subject is a counter that no longer exists, and **Arm 4 is
> retired** with the filter ADR-0246 §1 removed.

> **Normative.** **Arm H′ — the audit event carries three counts (lane 4).** On a turn
> carrying an admitted `DERIVED` narrowing and an admitted `OWNER_ACT` one, the one event
> under the one key records the supplied count, the withheld count at **zero** and the
> supplied-narrowed count at **two**, each at its true value, carries **the ambient
> correlation identifier and no other identifier**, and carries **no `calls` field at
> all**. This is ADR-0246 §11 Arm F′ in the form §6 leaves it.

> **Normative.** **Arm I — the negative arm, restated over what it now protects (lane 3).**
> A search result, a fetched file or a memory record whose text asks in any terms for a
> different origin, a different account, a wider authority or a suspended floor changes
> neither side of §1's comparison and neither condition of §4; the request binds to the
> configured origin, and `closed_loop` is decided from the configuration and the kind
> alone. **This restates ADR-0238 §15 Arm 3's posture over the facts that remain.**

> **Normative.** **Arm J — a store that cannot be read decides nothing here (lane 3).** With
> the `DestinationTrustStore` raising on every call, a search at the configured provider is
> unaffected, because §1 stops consulting it — which is the arm that asserts the read was
> removed rather than merely made to answer `USER_CHOSEN`.

### 13. Deferred, by name, each with what fires it

- **A per-conversation bound of any kind on searching.** Fired by the owner's own trigger,
  quoted: *"Revisit if planner passes, batching or unattended work expand."* Each of those
  falsifies "every turn is owner-initiated", which is what §5 rests on. **Not fired** by an
  audit showing a conversation searching often, and **not** by a lane finding the absence
  uncomfortable. ADR-0238 §16's rolling-window entry and its per-conversation elapsed-time
  entry are **restated here over the state this ADR leaves** rather than discharged: each
  would now be a bound on a quantity nothing counts, so each takes the ADR that decides
  what to count first.
- **Retiring `SearchNotServiced.TRUST_MISSING` and `AUTHORISATION_AWAITED`, and with them
  the `trust-destinations` act's reachability from the search path** (§6). Both members and
  ADR-0242 §1's act stay ratified and stay in the tree; what has gone is their producer on a
  configured deployment. Fired by an owner ruling on whether the choosing act should be
  retired now that milestone 32's fetch is its only prospective consumer, or by the fetch
  ADR taking it. **Not fired** by a lane finding a member unreachable, which is the finding
  this entry records rather than the trigger.
- **A durable, dated record of the configuring act** (§8(d′)). Route (c) records which
  configuration authorised a call and not when or by whom it was made. Fired by an ADR that
  decides how operator configuration is recorded as an auditable act at all — which is a
  question about `Settings` and not about search. **Not fired** by a lane wanting a
  timestamp.
- **Dropping the two SQLite columns** (§5). Fired by an ADR that decides a `conversations`
  table rebuild, which is the mechanism SQLite requires and which this ADR does not open.
  **Not fired** by a lane finding a dead column untidy.
- **A second search provider**, and everything about ordering several outward sources.
  ADR-0231 §19's deferral is untouched; §1's comparison is written so that such a lane finds
  the rule already stated rather than discovering it is owed.
- **Everything about an `UNCHOSEN` destination, and milestone 32's fetch.** ADR-0238 §16's
  deferral stands untouched and this ADR adds nothing to it (§9).
- **A local-only tier.** ADR-0246 §12's first deferral binds entire and this ADR neither
  takes it nor narrows it. The owner's pass listed the question and left it deferred.
- **A call-budget refund on a denied, cancelled or expired park.** The question the pass
  parked is dissolved rather than answered: there is no admission to refund once §5 lands.
  A later ADR that reintroduces any per-conversation admission owes the refund rule in the
  same change.

### 14. Scope, and what this records against earlier ADRs

> **Normative.** This ADR partially supersedes **nine** ratified ADRs and amends none:
> ADR-0238 in nine scopes, ADR-0244 in three, ADR-0242 in two, ADR-0193 in two, ADR-0148 in
> two, ADR-0181 in one, ADR-0152 in one, ADR-0021 in one, and ADR-0246 in one. Each is
> named on that ADR's `Status` line and in its appended dated note under ADR-0082 §1 and
> §2. **No other ADR's text moves.**

> **Normative.** **Superseded on ADR-0238, and nothing else beyond what ADR-0241, ADR-0242,
> ADR-0245 and ADR-0246 already recorded there.** §1's third clause in the limb that reaches
> a `WEB_SEARCH` request at the configured provider (§1); §5's four-condition definition of
> `closed_loop`, in its second, third and fourth conditions (§4); §5's non-transcription
> clause, in the count it keeps and in its never-resumed premise (§7); §6's first clause, in
> the conditions under which the relaxation is available (§3); §8's `Settings` field clause
> and its ships-with-a-value clause (§5); §8's `ConversationSearchDraw` clause, its
> three-member clause, its signature clause, its atomicity clauses, its creation-value and
> pre-existing-record clauses, its early-fold clauses, its window clauses and its
> monotonicity clause (§5); §11's closure of `SearchDisposition`, in that count alone (§6);
> §11's per-turn record, in its `calls` limb alone (§6); and §13's `core`-surface
> enumeration, in the limbs naming the removed field, type and three members (§10).
> **Relied on as written**: §1's other clauses, §2 entire as ADR-0245 and ADR-0246 left it,
> §3, §4, §5's writer, producer-discard, trust-boundary, window and pre-existing-row
> clauses, §6's remaining clauses, §7, §9, §10, §11's one-event, one-key, counts-only,
> no-identifier and no-trust-in-the-event rules, §12's negative arm, §13's remaining
> clauses, §14, §15's other arms and §16's deferrals.

> **Normative.** **Superseded on ADR-0244, and nothing else.** §6's clause 2 entire, whose
> two facts are replaced by one `get` (§6); §9's definition of `UNAVAILABLE_NOW`, in its
> `search_calls_per_conversation` limb alone (§6); and §12's re-closure of
> `SearchNotServiced` at nine, in that count alone (§6). **Relied on as written**: §§1–5,
> §6's other five clauses and its ordering, §7, §8, §§10–11, §12's remaining clauses, §9's
> other six members and its precedence rule, and §§13–23. §6's *"`trust_of` is not asked
> again"* is relied on and strengthened, and §6's route-(a) clause is relied on as the
> reason route (c) never reaches a resumed call.

> **Normative.** **Superseded on ADR-0242, and nothing else beyond what ADR-0244 already
> recorded there.** §8's closure of `SearchNotServiced` at eight members, in that count
> alone; and §8's two-members-not-one clause for `admit_search`'s refusal, whose subject is
> removed (§6). **Relied on as written**: §1's trust act and its surface, §§2–7, §8's
> remaining clauses including the vocabulary's precedence order and the totality and
> non-injectivity of its mapping, §9's bar on what a statement may say, and §§10–18.

> **Normative.** **Superseded on ADR-0193, and nothing else beyond what ADR-0238 already
> recorded there.** §3's first clause, in its application to a `WEB_SEARCH` request at the
> configured provider, which takes route (c) rather than needing coverage (§1); and §6's
> pairing clause together with the scope of its eight-check invariant, in the limb that
> reaches a non-resolving `ALLOW` whose `authorised_subject` is unset **and whose binding
> carries `closed_loop`** (§2) — the pairing refusal standing entire on every other such
> row, so that a digest-free standing `ALLOW` of any other kind is refused exactly as it is
> today. **Relied on as
> written**: §1's store, §2's establishing act, §3's five comparisons wherever a grant is
> the route, §3's comparison-not-inference rule, §4, §5's payload clause, §6's eight checks
> themselves, §7's check point, §§8–9, §11's rendering bar, and §§12–16. §9's rule that a
> revocation rewrites no recorded decision is **relied on hard**, and is what rules out a
> discriminator that resolves a pointer against the grant store.

> **Normative.** **Superseded on ADR-0148, and nothing else.** §3's first clause, in the
> route enumeration alone, which takes a third route (§2); and §3's second clause, in the
> *"a configured base URL or host"* limb and for a `WEB_SEARCH` request at the configured
> provider alone (§2). **Relied on as written**: §3's other limbs and its remaining clauses,
> including the `SourceGrant` refusal and the clause reserving three questions to the
> standing-grant ADR, which ADR-0193 answered; §1, §2, §§4–7, §6's determinism and
> registry-rebuild clauses, which §8(b′) relies on by name, §8's floors, and §§9–15.

> **Normative.** **Superseded on ADR-0181, and nothing else beyond what ADR-0238 already
> recorded there.** §5's second clause, in its application to a `WEB_SEARCH` request at the
> configured provider (§3). **Relied on as written**: §5's memory-ruling-point clause, its
> separate-binding clause on `decide` and `resolve`, its two-comparisons clause, its
> `authorises` clause and its `ActionPolicy`-contract clause; §§1–4, §§6–12.

> **Normative.** **Superseded on ADR-0152, and nothing else beyond what ADR-0181 and
> ADR-0233 already recorded there.** §7's transcription count alone, which becomes four
> (§7). **Relied on as written**: §7's every other clause, §§1–6 and §§8–16.

> **Normative.** **Superseded on ADR-0246, and nothing else.** §11's Arm F′, in its
> `calls` count alone, the arm being restated over the three counts that remain (§6). Its
> each-at-its-true-value requirement, its `withheld`-at-zero and supplied-narrowed-at-two
> limbs, and its one-identifier-and-no-other rule bind entire. **Relied on as written**:
> §1's rule that `Placement.reach` does not bind at all on a chosen destination's supply,
> §§2-10, §11's other arms, §12's deferrals, §§13-15. §1's trust condition is read through
> ADR-0238 §2's trust clause, whose answer for a `WEB_SEARCH` at the configured provider
> §1 above decides; **no clause of ADR-0246 is read more widely for that.**

> **Normative.** **Superseded on ADR-0021, and nothing else.** §3's clause that a policy
> constructed with no authorisation source leaves `authorised_by` unset, in the limb that
> reaches a request whose binding carries `closed_loop` (§2). **Relied on as written**: §3's
> other clauses, §4's resolution invariant, §5's disclosure floor and its monotonicity
> obligation — which §2 satisfies rather than relaxes, by setting `authorised_by` — §6's
> deferral of standing grants for other actions, and every other section.

> **Normative.** **Discharged rather than superseded.** ADR-0238 §17's record against
> ADR-0074 §9: its three added members go, so ADR-0074 §9's enumeration stands as ADR-0205
> and ADR-0212 left it. **The record is made on ADR-0074's own line under ADR-0070 §4's
> accumulation rule and displaces neither earlier pair**, and no ratified sentence of
> ADR-0074 is rewritten.

> **Normative.** **No record is owed on** ADR-0004, ADR-0007, ADR-0013, ADR-0014, ADR-0016,
> ADR-0021 beyond §3's one limb, ADR-0029, ADR-0036, ADR-0045, ADR-0059, ADR-0070, ADR-0074
> beyond the discharge above, ADR-0082, ADR-0087, ADR-0097, ADR-0098, ADR-0106, ADR-0124,
> ADR-0125, ADR-0126, ADR-0137, ADR-0146, ADR-0149, ADR-0150, ADR-0154, ADR-0155, ADR-0158,
> ADR-0165, ADR-0170, ADR-0178, ADR-0184, ADR-0192, ADR-0194, ADR-0197, ADR-0198, ADR-0199,
> ADR-0203, ADR-0204, ADR-0205, ADR-0208, ADR-0212, ADR-0217, ADR-0223, ADR-0226, ADR-0228,
> ADR-0231, ADR-0233, ADR-0235, ADR-0236, ADR-0237, ADR-0239, ADR-0240, ADR-0241, ADR-0243 or
> ADR-0245, on ADR-0082 §1's test: every sentence each of them wrote stays true
> and none is read more widely. In particular **ADR-0233 §7's absolute clause and §9's four
> conditions are quoted and unnarrowed** (§3); **ADR-0155 §3's second clause is untouched**;
> **ADR-0246 §1's rule binds entire** and §1 above decides only what its trust condition
> answers, its own record above being confined to §11's one count; **ADR-0154's condition 5 and ADR-0231 §8's grammar are relied on** as the pin
> §4's negative arm rests on; and **ADR-0228 §4 is applied rather than amended**, a rule
> applied being a rule relied upon.

> **Normative.** **Additions this ADR makes that contradict no sentence an earlier ADR
> wrote are stacked additions under ADR-0082 §1** and are recorded here and nowhere else:
> §2's route-(c) pointer invariant on the trail, and §8's four contract limbs, none of which
> any ADR forbids.

> **Normative.** **These records are made in this ADR's own change, while it stands
> `Proposed`, which is ADR-0082 §7's rule.** §1's condition is that the superseding ADR
> *exists*, not that it is ratified, and an atomic pair makes a `Status` line pointing at
> nothing unreachable. **And the alternative would cost a round**: ADR-0165 exempts a
> ratification flip only where it is one ADR file and one changed line, so moving eight
> other files' `Status` lines in that commit would forfeit the exemption.

> **Normative.** **Every record is header-only, in ADR-0070 §4's shape.** On each superseded
> ADR the `Status` line takes this ADR's pair — appended to the existing pairs where the
> line already leads with `Partially superseded by`, and taking the leading token with
> `Accepted` dropped where it does not — and the whole record lives in an appended dated
> note. **No ratified sentence of any of the eight is rewritten and no body text outside the
> header is touched.** **Clauses are named by position and never by an `ADR-NNNN` token
> inside a supersession scope**, so that a later reader parsing a scope cannot mistake a
> citation for a supersession pair.

### 15. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Each edit, with §1's test applied: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

- **ADR-0238 §1's third clause** — **yes**, and this is ruling 1. A reader holding only it
  refuses to treat a configuration as a choosing act and services every production search
  at an `UNCHOSEN` destination. **Supersession**, in one limb; the clause's force on every
  other destination and kind is unmoved, and the store it governs is not touched at all.
- **ADR-0238 §5's four conditions, and its non-transcription clause** — **yes**, twice over.
  A reader holding only §5 computes a conjunction of four facts, three of which have no
  subject after this decision, and builds a `rebind` that constructs `False`.
  **Supersession** of the definition and of the transcription premise; the field, its
  default, its writer and its carriage are relied on as written.
- **ADR-0238 §6's first clause** — **yes**. A reader holding it relaxes ADR-0181 §5 only for
  a request meeting four conditions. **Supersession** in the conditions alone; the direction
  of the relaxation and its one-kind scope are unchanged.
- **ADR-0238 §8** — **yes**, and this is ruling 3. A reader holding it builds a `Settings`
  field, a read model, three Protocol members, an atomic increment and two folds.
  **Supersession**, broadly, of a mechanism rather than of a posture: §8's *reasoning* — that
  a per-conversation counter's lifecycle belongs on the conversation record — is neither
  denied nor relied on, there being no counter.
- **ADR-0238 §11's two counts and §13's surface enumeration** — **yes**, narrowly. A reader
  holding them writes a `calls` figure to an event and expects four `core` additions.
  **Supersession** in those limbs; the audit's one-event, one-key, counts-only and
  no-identifier rules are restated and lose nothing.
- **ADR-0244 §6's clause 2 and §9's `UNAVAILABLE_NOW`** — **yes**. A reader holding them
  calls `search_draw` and reads a `Settings` field at the answer, neither of which exists.
  **Supersession**; the fact clause 2 establishes is preserved by a different read, and the
  member keeps its name, value and position.
- **ADR-0242 §8's closure, and ADR-0244 §12's** — **yes**, in the counts alone. A reader
  holding either builds a vocabulary with members no code can produce. **Supersession** of
  two counts; every other property of the vocabulary — order, precedence, totality,
  non-injectivity, the bar on what a statement says — is restated and unmoved.
- **ADR-0193 §3's first clause** — **yes**, narrowly. A reader holding it requires a covering
  grant for every `ALLOW` on an egress request, including one at the configured search
  provider. **Supersession** in that application; the five comparisons and the
  comparison-not-inference rule bind entire wherever a grant is the route.
- **ADR-0193 §6's pairing clause and its invariant's scope** — **yes**. A reader holding
  them refuses a standing-authorisation row that *"names standing authorisation … and
  fingerprints none"*, and validates every non-resolving `ALLOW` naming one against the
  grant store — so they would refuse every route-(c) row twice over. **Supersession** in one
  limb, with a replacement invariant stated beside it rather than a gap left. **What the
  pairing clause bought is kept and reused**: because it refused that shape from the day it
  landed, every route-(b) row in history carries a digest, which is exactly what makes the
  digest a total discriminator needing no store read and no disjoint-namespace assumption.
- **ADR-0148 §3's route enumeration and its configured-host limb** — **yes**, and this is
  the clause a reviewer should check hardest. A reader holding only §3 rules that a
  configured origin is not a user act and authorises no recipient. **Supersession**, for one
  kind and one destination; every other limb of the enumeration keeps its full force, and
  §3's third clause — that no lane reads limb (b) as pre-shaping ADR-0021 §6 — is honoured,
  ADR-0193 having landed and this ADR opening (c) rather than widening (b).
- **ADR-0181 §5's second clause** — **yes**, in one application, exactly as ADR-0238 §6
  already moved it once. **Supersession**; the clause's own last sentence, that a later ADR
  lifting ADR-0154's floor may not lift it for a call carrying
  `planned_with_external_content`, is the sentence being moved a second time, and it is
  moved to a narrower subject than it was first moved to in one respect — one kind, one
  configured destination — and a wider one in another — no lineage condition on the
  conversation. **That widening is the owner's ruling and is not derived here.**
- **ADR-0152 §7's transcription count** — **yes**, and it is the smallest edit in this ADR.
  A reader holding it builds a `rebind` transcribing three facts and refusing every park
  carrying a fourth. **Supersession** of a count, for the third time, with every other
  clause of §7 relied on.
- **ADR-0246 §11's Arm F′, in its `calls` count** — **yes**, narrowly, and it is the arm
  most easily missed because it lives in a different ADR's test list. A reader holding it
  writes a test asserting a field §6 deletes, and the arm's own closing sentence — *"so the
  arm cannot be satisfied by dropping a field §7 keeps"* — reads as forbidding exactly
  that. **Supersession** of one count; the sentence was aimed at a lane dropping a field
  for convenience, and an ADR removing the quantity is the instrument it left open.
- **ADR-0021 §3's sourceless-policy clause** — **yes**, in one limb. A reader holding it
  builds a policy that cites no authorisation when it was given no grant seam, which would
  make route (c) unreachable on exactly the deployments that need it. **Supersession**;
  §5's disclosure floor is **satisfied** by route (c) setting the field, not relaxed, which
  is the same relation ADR-0193 §15 records for route (b).

**Two near misses are named, because each would have been a supersession and each is
avoided by a decision rather than by luck.** `EgressBinding` and `CarriedProvenance` gain
and lose no field, so ADR-0233 §4's shape and ADR-0181 §3's carriage are untouched — §4
redefines a value rather than a surface. And `ConversationExport.schema_version` does not
move, so ADR-0212 §8 and ADR-0014 §5 are untouched — §5 removes row state that was never on
a presented model, which is the property ADR-0238 §8 chose deliberately and which pays for
itself here. **A lane that reverses either decision owes the record it avoids, and says
so.**

### 16. Marking, review and ratification

> **Normative.** This ADR is a **contract-surface decision** — it narrows
> `core/protocols.py` and removes a `core/types.py` model — so it owes **both** the
> adversarial and the architecture review before it ships (ADR-0015 §1, ADR-0020 §2), on one
> committed tree per round, and it is ratified by ADR-0165's one-line flip made with `just
> adr-ratify`. **It merges before any lane implements against it** (golden rule 5,
> ADR-0015).

## Consequences

**A production search starts working.** Today every production search that touches anything
external confirms, and the `trust-destinations` act that would fix it has never been
performed. After this ADR a deployment that has configured a provider searches without
asking, on any turn, whatever the conversation has read — which is the milestone's own
sentence, *"find more about that, taking my preferences into account"*, reaching the state
it was written for by a route the owner chose rather than by the one ADR-0238 designed.

**A structural property is given up, and it is the one ADR-0238 §5 was built to hold.** A
conversation that has read a prompt-injected file can now compose a search query over the
owner's eligible records and send it to the configured provider without asking. What
contains that is the destination and nothing else: the query goes to one origin, pinned by
the registration, and no content can move it. **The owner accepted this disclosure
explicitly** — the same supply already reaches the configured model provider on every turn,
because composing the query is a model call — and this ADR records the acceptance rather
than arguing it is harmless.

**The corpus gets smaller.** One `Settings` field, one `core` model, three Protocol members,
three `SearchDisposition`/`SearchNotServiced` members, two store implementations, a
conformance block, a canonical fake's three methods and roughly half of `SearchFooting` go
away, and with them the early fold, its window, its monotonicity argument and the
concurrency residue ADR-0238 §8 had to state at the size of the call ceiling. **The window
ADR-0238 §8 could only narrow is closed by deletion** rather than by a linearisation nobody
had.

**A conversation is no longer bounded in how much it searches, and that is a real cost.**
The remedy ADR-0238 offered — start a new conversation — goes away with the bound. What
replaces it is per-turn: at most two searches per turn, every turn owner-initiated, under a
per-call deadline and an optional spend ceiling. A deployment that runs unattended work, or
that expands planner passes, has lost a bound it had, and the owner's own trigger for
revisiting is recorded in §13.

**The audit says less about why a search was allowed.** A route-(b) row points at a grant
with an id, an instant and a revocation history; a route-(c) row points at a connection
reference and an origin. An auditor can answer *which configuration authorised this* and
cannot answer *when the owner configured it*. §13 defers the record that would close the
gap.

**Four PRs and a deploy.** The version moves, so the hub is redeployed after lane 4 —
which is the dispatcher's act.

## Alternatives considered

**Keep `search_calls_per_conversation` and only lift the floors.** This was the smaller
change and it was rejected by ruling 3. The bound's purpose was to cap a loop that could
re-search on its own; every turn is owner-initiated, ADR-0228 §4 already caps a turn at two
planner passes, and the per-conversation figure was the one quantity whose exhaustion a
user experiences as the assistant silently going deaf. Keeping it would also have kept
`ConversationSearchDraw`, whose other field retires anyway, leaving a read model with one
integer in it and three Protocol members to maintain it.

**Keep the third closed-loop condition and lift only the lineage floor.** Rejected by
ruling 2, and §3 states the mechanical reason: the coverage limb stops the same queries the
lineage limb stops, so lifting one changes nothing observable. Retiring the third condition
while keeping the flag would have left `all_external_user_chosen` maintained by two folds
for no reader.

**Make configuration mint a `DestinationTrustRecord`.** This would have reached route (b)
with no new route, no trail change and no `authorised_by` question: the configured provider
would simply read `USER_CHOSEN`. It was rejected on two grounds. It falsifies ADR-0238 §1's
*"set by a recorded act of the user and by nothing else"* at the store rather than at one
consumer, so every reader of the store — including ADR-0242's listing surface — would show
the owner a trust record they never made and offer them a revocation that a restart would
undo. And it still leaves the grant missing, so a second synthetic record would be needed
in `RecipientGrants` for the same call.

**Read the configuration as ADR-0148 §3's route (b).** Rejected for the reason §2's closing
paragraph gives: route (b)'s invariant is eight checks against a store, and a configuration
has nothing for them to read. Route (c) states a weaker invariant honestly instead of
making a stronger one vacuous.

**Set `authorised_by` to a synthesised identifier naming the route.** Rejected because a
pointer the policy invents is the exact hazard `_check_authorisation` exists to close.
Using the binding's own `account.reference` gives the trail something it can check with no
store, which is the strongest invariant available to this route.

**Drop the two SQLite columns.** Rejected in §5: SQLite needs a table rebuild, the table is
the one holding every conversation, and two unread integers per row are cheaper than a
destructive migration written for tidiness.

**Remove `TRUST_MISSING` and `AUTHORISATION_AWAITED` too.** Rejected as outside the ruling
(§6). The owner kept the choosing act standing for every other destination; removing the
vocabulary that renders it would prejudge whether it survives milestone 32. The finding is
filed and §13 names what fires it.
