# 78. A deferred memory decision is a durable question the user answers

- Status: Proposed
- Date: 2026-07-28
- **This is a contract change, and it is flagged as such (golden rule 5).** New
  `core` surface: a `DeferralStore` Protocol, a `DeferredProposal` record with its
  state enum, the `UserConfirmation`, `DeferralClaim` and `DeferralAdmission`
  values, one field added
  to `MemoryUpdateProposal`, one added to `MemoryIngestResult`, and a
  `DeferralStoreError`. It ships **no
  code**: it merges as its own PR ahead of any implementation and carries the
  architecture review as well as the adversarial one.
- **Takes up two deferrals that named an owner rather than a decision.**
  [ADR-0050](0050-resolving-the-full-contradiction-set.md) §3 left "the
  confirmation-driven supersession flow for #245 (surfacing the `ASK_USER`,
  applying recency on the answer). Spans interfaces/permissions; out of the memory
  lane." [ADR-0045](0045-memory-records-carry-a-validity-window.md) §10 left
  "#245's policy behaviour and any narrowing of `_refuse_unsafe_fold` clause 1
  (§5, §7)… decided in the policy lane on a contradiction signal, not here", where
  §7 named the two acceptable gates as "a real contradiction signal, **or explicit
  user confirmation**". This ADR is that lane. It decides the confirmation gate;
  it does **not** invent a contradiction signal, which stays deferred (§11).
- **Closes the design gap issue #423 reports.** Its north star is the roadmap's
  leg 4 exit test: *"a deferred question reaches the user instead of vanishing."*
- **Amends on ratification:** ADR-0045 §5 clause 1 and ADR-0050 §1's
  `USER_ASSERTED` hold-out, each narrowed by a stated exception for a *confirmed*
  retirement and otherwise standing verbatim (§5); ADR-0028 §8's conformance list,
  which gains two clauses (§4, §5). These are amendments rather than supersessions
  under [ADR-0070](0070-amendment-and-supersession-rules.md)'s test — the rule
  stands and gains a named exception. The edits are **not** made by this change:
  writing "amended by ADR-0078" onto a ratified ADR while ADR-0078 is only proposed
  is the state claim [ADR-0019](0019-no-state-claims-in-living-documents.md)
  forbids. §10 gives their exact form.
- **Binds to [ADR-0079](0079-a-correction-resolves-every-conflict-it-is-shown.md)
  (merged, `Accepted`), which names this ADR as the resolution mechanism and states
  the one thing that binds it:** "whatever commits an `ASK_USER` resolution as a
  `SUPERSEDE` carries §1's obligation, at §1's own reach and not beyond it… If
  ADR-0078 chooses to resolve by re-ingesting the held proposal, it inherits §1 and
  its reach together" (§2). **This ADR resolves by re-ingesting** (§5), so it takes
  that route deliberately and the obligation is discharged by construction rather
  than owed as an argument. ADR-0079 §2's ordering — completeness, then the ruling,
  then retirement, with a deferral winning and retiring nothing on its way — is the
  law §5's confirmed path obeys at every step.
- **Inherits [ADR-0080](0080-retiring-a-producer-set-bounded-validity-window.md)
  (merged, `Accepted`) by the same route.** It partially superseded ADR-0045 §4
  step 1 — a producer-set bounded window is **clamped** on retirement, with a
  narrow refusal for what cannot be represented — and §6 binds this ADR in terms:
  "whoever commits an `ASK_USER` resolution inherits this rule with §1's… ADR-0078
  owns that mechanism". Because §5 resolves by re-ingesting, the rule arrives with
  the applier and needs nothing restated. ADR-0080 §5 also **answers**, rather than
  defers, the write-time window question §6 previously filed against #306.
- **[ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) (the observer)
  is merged, `Accepted`,** and it names this ADR as the owner of the mechanism
  while supplying the one property that mechanism needs: "a deferred proposal is
  self-contained, so that a durable pending state can hold it without the producer
  changing… The producer therefore neither retries a deferral, nor escalates it,
  nor rewrites the proposal to avoid it, nor holds it to re-submit" (§4). §1's
  store relies on exactly that, and §3 states the wiring obligation running the
  other way. ADR-0077 §4 is also blunt about the state of the world this ADR
  changes — "No component persists a deferred proposal: the ruling is reported on
  the observe outcome and the process then exits, so that particular deferral is
  gone" — which is the same drop §Context traces, reached from the observer's side
  rather than `learn`'s.

## Context

[ADR-0005](0005-memory-model.md) §3 ratified five policy outcomes on a memory
proposal — "accept, reject, merge (into an existing record), **ask the user**
(defer for confirmation), or store temporarily (accept with an expiration)". Four
of them have an effect. The fifth has never had a resolution path, and no ADR ever
decided what one would look like.

**The drop site, traced.** `MemoryIngestor._apply`
(`src/ai_assistant/memory/ingest.py:503-533`) matches on the ruling. `ACCEPT`,
`STORE_TEMPORARY`, `REINFORCE` and `SUPERSEDE` each write; the wildcard arm is the
terminus:

```python
            case _:  # REJECT, ASK_USER — nothing is written.
                return None
```

— `ingest.py:532-533`. `_ingest` (`ingest.py:474-483`) then returns
`MemoryIngestResult(decision=decision, record_id=None)`, and the proposal object
goes out of scope. `LearningLoop.learn` (`orchestration/loop.py:287-324`) does not
inspect the ruling at all — `loop.py:324` is
`return tuple([await self._writer.ingest(proposal) for proposal in proposals])` —
and `Engine._learn` (`orchestration/engine.py:1627-1630`) translates the ruling to
`LearnDecision.DEFERRED` (`engine.py:363-364`) for rendering. **Nothing anywhere
retains the proposal.** The CLI says so in a comment that is the honest confession
of a dead end (`interfaces/cli.py:91-96`):

```python
    # ASK_USER writes nothing, and there is no memory-confirmation flow yet (memory
    # decisions are not what `assistant resume` recovers — that is permission action
    # confirmations, ADR-0052). So say plainly it was not stored and cannot be
    # confirmed from here, rather than implying a follow-up that does not exist (#422
    # review).
    LearnDecision.DEFERRED: "Not stored — this needs review, which cannot be done from here yet.",
```

**Two producers already reach that arm**, and they ask different questions.
`DefaultMemoryPolicy.decide` defers **secret-tier data** unconditionally
(`memory/policy.py:155-159`, "secret-tier data requires explicit user
confirmation") and defers a **non-asserted proposal that contradicts an assertion**
(`policy.py:164-168`). `_rule_on_assertion` (`policy.py:36`) defers an **assertion
contradicting a prior assertion** (`policy.py:73`, "contradicts a prior user
assertion; defer to the user (ADR-0050)"). The first asks "may I keep this?"; the
other two ask "which of these two do you hold?".

**A ratified claim is currently false in the code.** ADR-0050 §2 states that on an
assertion-versus-assertion conflict, "`ASK_USER` writes nothing (existing applier
behaviour), so the earlier assertion stays live and the incoming one is **held
pending the user's answer, not dropped**." Nothing holds it. It is dropped. The
sentence describes the system this ADR is here to build, written as though it
already existed — which is precisely why the gap survived three ADRs that all
touched it.

**The permission side solved the same shape and is worth reading before departing
from it.** A parked `CONFIRM` is durable because it was already *recorded* into the
`AuditTrail` for another reason, and ADR-0044 §3 added one query,
`pending_confirmation(execution_id, step_id)`, to find it again — "this keeps the
fact where the record is." ADR-0052 §1 then had the façade enumerate parked
executions and re-mint continuations, and the CLI grew `resume`. Recovery there
cost **no new store**, because the durable record already existed.

That is exactly what does not hold here. An `ASK_USER` is defined by the fact that
**nothing was written** — ADR-0022 §4 ("`REJECT` and `ASK_USER` write nothing, and
are reported with a `None` record id") and ADR-0028 §8 restate it as a
`MemoryWriter` conformance obligation. There is no side record to query back. And
ADR-0028 already ruled out solving it inside the writer, in terms this ADR must
honour rather than relitigate: a conforming writer may be many things but "**not** a
writer that *queues* a proposal for later: `ingest` returns the id written, and §8
requires an `ACCEPT` to have stored the record by the time it returns, so deferral
would need a result type that can say 'not yet' and this one cannot."

**The forces.**

- The assistant is becoming a resident service (roadmap leg 5). A question that
  lives in a turn dies with the process; the exit test is about *reaching the
  user*, which a per-turn variable cannot promise.
- Volume is coming. The observer (ADR-0077) will produce `OBSERVED`/`INFERRED`
  proposals continuously, and the second producer above — a derived proposal
  contradicting an assertion — is one the observer will hit routinely. A queue
  that is dignified at one question a week and humiliating at forty a day is not a
  design.
- The apply is not free. The answer "yes, the new one holds" must retire a
  `USER_ASSERTED` record, and the writer floor forbids exactly that today
  (`ingest.py:111-151`, clause 1: "nothing, of any source, under either ruling,
  may fold onto an assertion"). The confirmation gate ADR-0045 §7 named is the
  only ratified way through it, and nobody has built it.
- New contract surface is expensive and a new store is heavier still. It has to
  earn itself against reusing what exists.

## Decision

### 1. A deferred proposal is a question, not a belief — and it gets its own durable store

**What it is.** An `ASK_USER` ruling produces a *question about a candidate
belief*. It is deliberately **not** a belief of any band. `band_of`
([ADR-0072](0072-the-profile-and-the-inferred-model-are-bands-of-one-store.md) §2)
classifies a `MemorySource` into `ASSERTED`/`DERIVED`/`ATTESTED`, and applying it to
the proposal's record says only which band it *would enter if accepted* — not what
the system holds. Three consequences follow and are ratified here, because each is
a way the queue could otherwise leak into the user model:

- It is **never returned by retrieval**. It is not in the `MemoryStore`, so
  `search` cannot reach it and no plan or prompt is assembled from it.
- It is **never listed as a belief**. ADR-0073 §3 is that inspection reads live
  beliefs only; a pending question appearing in `assistant beliefs` would claim the
  system holds something it explicitly declined to hold.
- It **contributes no confidence and no evidence** to anything. A question is not
  weak evidence for its own answer.

**Where it lives: a new `DeferralStore`, and the alternatives are rejected on the
record.** A new store is the heaviest option available, so it is argued rather than
assumed.

- **Not the `MemoryStore`.** Tempting, because ADR-0045 §2's `Validity` window can
  express "not live" and the record would then be hidden from `get`/`search`
  (ADR-0045 §6). It fails on four counts, any one of them fatal. It contradicts the
  ratified obligation that `ASK_USER` **writes nothing** (ADR-0028 §8) — the
  conformance suite pins it and the whole propose/dispose principle (ADR-0005 §3)
  is that the policy disposes *before* anything is stored. A retired-window record
  is still returned by `export` (ADR-0045 §6), so an unconfirmed proposal would
  appear in the user's own data export as something the assistant holds. It carries
  none of the question — the proposal's `rationale`, `sensitivity`, resolved
  conflicts and the policy's `reason` are not `MemoryRecord` fields. And it would
  make the store's records a mix of beliefs and non-beliefs, which is the exact
  distinction ADR-0072/ADR-0073 spent two ADRs making legible.
- **Not the `AuditTrail`.** Its record is a `PermissionDecision` about an action a
  tool would take (ADR-0021), keyed by an `(execution_id, step_id)` binding
  (ADR-0044 §1-§2). A memory deferral has no execution and no step; hosting one
  would mean minting a fake binding, and the trail's single-resolution invariant
  would then govern a fact it knows nothing about. Issue #423 makes the same
  observation from the user's side: `assistant resume` recovers permission
  confirmations, "not memory-decision deferrals — different machinery."
- **Not the `ConversationStore`.** Its vocabulary is conversations, turns and
  episodes (ADR-0074 §9). `learn` is not a turn, and the observer's proposals arise
  from no live conversation at all.
- **Not a field or a table hung off an existing store's Protocol.** Every candidate
  above would need its host to answer questions about the other store — which
  golden rule 1 forbids and ADR-0074 §9 already ruled on in the same shape ("a
  `ConversationStore` asked to reclaim would have to reach into memory to answer
  its own precondition").

So it is its own store, and it is small: one record type, ten methods (§2),
against `ConversationStore`'s thirteen. It earns the surface because the thing it
persists — a question the system asked and has not been answered — genuinely exists
nowhere today.

**It is Tier 1 personal data at minimum, and sometimes Tier 0.** The proposal
carries the user's own words, and the secret-tier arm (`policy.py:155-159`) means
the queue can hold `DataTier.SECRET` content. The store therefore inherits every
obligation the `MemoryStore` carries under [ADR-0004](0004-privacy-and-data-handling.md)
and [ADR-0007](0007-memory-data-rights.md) — the same data directory and file
permissions, inclusion in export, destructible on request — and §6's finite
lifetime is load-bearing for it rather than merely tidy: it is a **cap on how long
unresolved sensitive content sits unanswered**, which is a tighter guarantee than
accepting the proposal would have given. The cap holds for every state but one: a
deferral interrupted mid-apply is never swept, because sweeping it can orphan a
committed memory write (§2, §9). It is instead *shown* until the user disposes of
it, which is a worse guarantee stated honestly rather than a better one claimed
falsely. Deferral content is never logged; a log
line names the deferral id (the posture
[ADR-0055](0055-context-source-name-is-safe-to-log.md) sets for a comparable
question about what is safe to emit).

### 2. The contract surface owed, stated precisely

**`core/types.py` gains:**

- **`DeferredProposal`** — a frozen pydantic model
  ([ADR-0068](0068-freeze-the-shared-record-graph.md)), every instant timezone-aware
  (ADR-0023, ADR-0030), carrying: its own `id`; the `proposal`
  (`MemoryUpdateProposal`) verbatim, *including* the `conflicts` ids resolved at
  ruling time (§4); the `decision` (`MemoryDecision`, whose `kind` is `ASK_USER` and
  whose non-optional `reason` is what the surface renders as "why you are being
  asked"); `deferred_at`; **`retention`** — the lifetime in force *at admission*,
  a duration or `None`; and `expires_at`, the answerability deadline, which is
  `deferred_at + retention` (or `None`). Both are **stamped onto the record at
  deferral**, following ADR-0059 §1's ruling that a confirmation's lifetime is fixed
  on the record rather than recomputed from a live setting.

  **The duration is stored as well as the instant, and that is not redundancy.**
  `expires_at` answers "is this still answerable?" and is fixed at admission.
  The *other* deadline — how long a resolved question's record is kept (§2's
  `purge`, §7's no-nagging rule) — is anchored on `answered_at`, which is not known
  until the answer arrives, so it can only be computed later. Computing it from the
  **live** setting is what an earlier revision did, and it breaks the very rule
  `expires_at` follows: defer under a 30-day lifetime, reject tomorrow, shorten the
  setting to a day, and the rejected key is dropped 29 days early and the user is
  re-asked a question they already declined — a retention the user never chose,
  differing between two processes reading different config. So the duration rides
  on the record and `purge` reads it there. Live configuration governs questions
  admitted from now on; it never reaches back.

  `None` in either field is the user's deliberate "ask me forever" (§6): the
  question never lapses and its record is never purged, the way `episode_retention`
  reads `None` as "keep forever… the user's deliberate choice"
  (`core/config.py:382-384`).

  **A model validator enforces the pair, because "is" is not a constraint.** Saying
  `expires_at` *is* `deferred_at + retention` describes an honest caller; `defer`
  takes a caller-supplied `core` model, so the contract has to refuse a dishonest
  one. In the shape `MemoryDecision._outcome_fields_are_consistent`
  (`types.py:696-719`) already uses: `retention` is positive or `None`; the two
  fields are `None` **together or not at all**; and when both are set, `expires_at`
  equals `deferred_at + retention` exactly. Without it a secret-tier question can
  be admitted with a one-day `retention` and `expires_at=None`, and a literal
  implementation keeps it answerable forever and never purges it — §1's finite
  exposure cap defeated by a record the contract accepted.

  Then: `state`; once
  claimed, `claimed_at` — but **not** the claim token, which no read republishes
  (`claim`, below); `predecessor_id`, the question this one succeeds when it was
  raised by a re-deferral (`defer`, below), `None` otherwise; and, once resolved,
  `answered_at`,
  `outcome_record_id` (the id the accepted apply left live, or `None`) and
  `successor_id` (the question a `REDEFERRED` answer raised, or `None`).

  **The deadline is half-open, and the boundary instant is fixed here rather than
  left to each backend.** A question is answerable while `now < expires_at`; **at**
  `expires_at` it is not. That is `Validity.is_live_at`'s own convention — "``True``
  iff ``valid_from <= now < valid_until``" (`types.py:471-476`) — and the reason to
  adopt it is consistency rather than preference: two deadline notions in one memory
  system that disagree at the instant they name is a defect waiting for the first
  test that lands exactly on it. Unstated, one store writes `expires_at <= now` and
  another `< now`, and they hide the same question one instant apart. **Every**
  operation that consults the deadline uses this comparison — `pending`, `claim`,
  the cap count, the key's reach, and `purge`.
- **`DeferralState`** — a `StrEnum`: `PENDING`, `APPLYING`, `ACCEPTED`, `REJECTED`,
  `STALE`, `REDEFERRED`. The last is the terminal state of a claimed answer whose
  re-ingest surfaced an assertion the user was never shown (§5a step 1): the answer
  was used — it produced a successor question — and the record names that successor
  so the chain is walkable. Without it a re-deferred answer has no legal transition
  out of `APPLYING` and strands. There is **no `EXPIRED` member**: expiry is
  read-time-relative and never
  stamped, exactly as `MemoryRecord.expires_at` is (ADR-0007 §3, ADR-0045 §6), so
  no sweep is needed to make a question stop being answerable. `STALE` *is* stored,
  because it records that an answer arrived and was refused — §6 says why the two
  are different facts.
- **`DeferralClaim`** — a frozen value carrying the claimed `deferral` and the
  `claim_id` token `claim` minted for it. One value rather than two strings a caller
  could swap, for the reason ADR-0074 §9 gives `ParkedBinding`.
- **`DeferralAdmission`** — a frozen value carrying `outcome` (admitted /
  suppressed / refused) and `deferral: DeferredProposal | None`, with the validator
  above. It crosses the Protocol boundary, so `CLAUDE.md`'s rule makes it a `core`
  pydantic model rather than a tuple.
- **`UserConfirmation`** — a frozen value carrying `deferral_id`,
  `proposal_fingerprint`, `confirmed_at`, and `retires: tuple[str, ...]`, the record
  ids the answer authorises retiring (§5). The fingerprint is what **binds the
  authority to the proposal it was given for**: without it a confirmation is a
  bearer token that any proposal sharing a conflicting assertion could present
  (§5b check 4). It is a value rather than a naked field because it is *authority*,
  and authority that can be inspected is authority that can be bounded.
- **The fingerprint is §7's key minus its conflict set** — the digest over the
  canonical projection of the proposed record plus the proposal's `sensitivity` —
  so `question_key` is exactly `digest(proposal_fingerprint, sorted conflict ids)`.
  Splitting it that way is what makes the binding checkable: the **writer can
  recompute the fingerprint from the proposal in its hand**, while it cannot
  recompute the key, whose conflict set was frozen when the question was asked and
  is not the live one. It also binds to *what was asked about* rather than to a
  minted identifier — a proposal's record `id` is caller-minted and unique only
  once stored, so two unpersisted proposals with different content can carry the
  same one, and an id-based binding would let a confirmation for one authorise the
  other. The fingerprint cannot: different content, different fingerprint.

**`core/types.py` also gains two fields on existing types**, both defaulted so the
change is additive and no existing producer moves:

- `MemoryUpdateProposal.confirmation: UserConfirmation | None = None` (beside
  `conflicts`, `types.py:642-645`).
- `MemoryIngestResult.conflicts: tuple[str, ...] = ()` (`types.py:725`) — §4.

**And two computed properties on `MemoryUpdateProposal`** — `proposal_fingerprint`
and `question_key`, both `Sha256Hex` (§7). Properties rather than fields, for the
reason `parameters_digest` is one (`types.py:2653-2682`); the store indexes the key
and no caller supplies either. `DeferredProposal` therefore carries no key of its
own: the question's identity is a function of the proposal it holds, so the two
cannot disagree.

**`core/protocols.py` gains one Protocol, `DeferralStore`**, `@runtime_checkable`
like every other, owing:

- **`defer(deferred, *, successor_to_claim=None) -> DeferralAdmission`** — admit a
  question, returning **what happened and the deferral that now holds it**.
  **Key-idempotent**: if a deferral **the key
  still speaks for** carries the same `question_key`, the admission is *suppressed*
  and carries that deferral, and nothing is inserted — the reconciliation ADR-0052
  §2 ratified for parked
  confirmations ("a binding already named by an entry reuses that entry's handle
  instead of minting a second"). A key "still speaks for" a deferral that is
  answerable (`PENDING`, before `expires_at`), being applied (`APPLYING`), or
  `REJECTED` within its retention (§7's no-nagging rule). A key whose only match is
  *lapsed-and-unanswered*, `ACCEPTED`, `STALE` or `REDEFERRED` does **not** collide:
  the question lapsed, was settled, or was replaced by the successor it names, and a
  fresh proposal deserves a fresh question.

  **It says whether it admitted anything, rather than leaving that to be
  inferred.** Both a fresh admission and a key suppression are successes, and the
  caller must tell them apart to render §7's suppression guidance at all. Two
  weaker shapes were tried and both are wrong: a bare id makes the two
  indistinguishable, and comparing the returned id to the one the caller minted
  fails the moment a caller *retries with the same id* — a legitimate pattern after
  an uncertain failure — because the key-idempotent path then returns a row whose
  id equals the supplied one while being `REJECTED` or `APPLYING`, and the
  coordinator would announce a newly parked question over a suppressed one. So the
  disposition is carried explicitly.

  **An `APPLYING` key blocks until its row is deleted, and only until then.** It
  has to block while an apply may still be running, or a re-proposal admits a twin
  question whose later answer writes the second correction the claim exists to
  prevent. And `delete` is the *only* thing that stops it, because `purge` never
  removes an `APPLYING` row at any age (below) — so a key stranded by a crash blocks
  until the user disposes of the question, which is precisely why §9's recovery
  makes that disposal its **first** step rather than an afterthought.

  **An id already present is a hard error, not an overwrite.** Key idempotency is
  about the *question*; a caller-minted `id` colliding with a stored row carrying a
  *different* key is a separate event and the contract must say which, or a
  dict-backed fake silently overwrites someone else's pending question while SQLite
  raises a primary-key error and the two disagree about whether a question still
  exists. So `defer` **inserts only if the id is absent** and otherwise raises
  `DeferralStoreError`, committing nothing — insert-if-absent in ADR-0046 §3's
  sense, where "absent" is *physical presence* rather than read-visibility, so a
  resolved or lapsed row still blocks the id.

  **The id check comes first, and the precedence is stated because the two rules
  can both fire.** A call carrying id `a` and key `K2`, against a store holding
  `(a, K1)` and `(b, K2)`, is simultaneously a key duplicate of `b` and a physical
  collision on `a`; unstated, a dict-backed fake takes the suppression path while a
  SQL-shaped one raises, and the suite certifies both. The id collision wins,
  because it is a **caller-side minting fault** and the suppression path would hide
  it: the caller would be handed back a different question, under an id it believes
  it just minted and now believes it owns. A fault that is reported can be fixed; a
  fault absorbed into a plausible-looking success is found later, by someone else.
  The coordinator mints ids, as it does for `MemoryRecord`, and ADR-0074 §9's
  `start` takes the same position for a conversation id, with
  retry-on-collision at the minting site.

  **`DeferralAdmission` has exactly three shapes**, and its validator pins them the
  way `MemoryDecision._outcome_fields_are_consistent` (`types.py:696-719`) pins a
  ruling's: *admitted* carries the new deferral; *suppressed* carries the existing
  one the key spoke for; *refused* carries nothing and means the answerable queue
  was at its cap (§7). A physical id collision is not among them — it raises
  (above) rather than returning a fourth shape nobody would check for.

  **A re-deferral does not consult the cap, and the exemption is held by a
  capability rather than named by an id.** `defer` takes one more argument —
  `successor_to_claim: str | None = None`, **the parent's `claim_id`** (§5a step 1,
  §9). When it is given, the cap is not consulted.

  **Naming the parent by its deferral id would not have worked, and the reason is
  the point.** An earlier revision did exactly that and called the three checks
  below sufficient. They are not: `interrupted` publishes the ids of `APPLYING`
  rows to any caller (below), so an id proves only that *some* answer is in flight,
  not that this caller is the one applying it. Anything holding such an id could
  admit an unrelated question past a full queue and stamp a live parent's
  `successor_id`, and that parent's real answer would then either strand — its
  successor slot taken — or resolve `ACCEPTED` while pointing at a question it never
  raised. The **`claim_id` is the capability**: it is minted by `claim`, returned to
  that caller alone, and — the part that makes it worth anything — **it is on no
  other read.** `get`, `pending`, `interrupted` and `export` return
  `DeferredProposal`s, which do not carry it (§2's record fields; `claimed_at` is
  there, so a surface can still say *when* an answer was begun). Holding the token
  is holding the claim.

  **The successor names its own parent, so the token authorises rather than
  identifies.** A capability alone still leaves the store unable to tell *which*
  question a successor belongs to: two answers claimed concurrently, and a
  coordinator that passes Q2's token while enqueuing Q1's successor, satisfies
  every check about the token and stamps the wrong parent. So the link is on the
  record: `DeferredProposal` carries `predecessor_id` (§2), the successor says what
  it succeeds, and the token says the caller may say it. The pair is symmetric —
  parent `successor_id` ↔ child `predecessor_id` — which is also what makes the
  chain walkable from either end for the surface.

  The store validates all of it in the same atomic operation as the admission,
  raising `DeferralStoreError` and changing nothing if any condition fails: the
  token must name a stored claim; **that claim's deferral must be the one
  `deferred.predecessor_id` names**; the deferral must still be **`APPLYING`**; and
  it must not already carry a `successor_id`. The two arguments must also agree on
  presence — a `predecessor_id` without a token, or a token without one, is a
  malformed call and raises. On success the store stamps that `successor_id` in the
  same commit, which is what makes the last condition enforceable and gives
  `resolve`'s `REDEFERRED` transition durable state to check rather than the
  caller's word.

  That is what bounds it. One successor per claim, one claim per question, and every
  question admitted under the cap — so the answerable queue can exceed its
  configured maximum only by the number of answers currently in flight, and it
  returns under it as each resolves. Without the exemption the alternative is worse
  in a way the cap was never meant to buy: a claimed answer with nowhere to go, and
  a newly-surfaced assertion never asked about — the exact drop this ADR ends.
  ADR-0052 §2 settled the same question in the same direction for parked
  confirmations: "recovery presents parks that already happened and are already
  durable, so it does not consult that ceiling — refusing to surface an
  already-parked step would strand it".

  Dedup still applies to a successor; its key differs by construction, since its
  conflict set does.
  **Admission is one atomic operation** — the key lookup, the answerable-count
  check and the insert commit or fail together, like `claim` and `resolve` below and
  for the same reason. Left non-atomic, two concurrent producers each see room at
  capacity-minus-one and the cap is exceeded, or two same-key calls each see no
  match and the queue holds the same question twice. The observer is precisely a
  concurrent producer, so this is a live condition rather than a theoretical one.
- **`get(deferral_id) -> DeferredProposal | None`.**
- **`claim(deferral_id) -> DeferralClaim | None`** — a compare-and-set from
  `PENDING` to `APPLYING`, atomic with its own read, refusing a deferral past
  `expires_at`. It **mints a fresh `claim_id`**, stamps `claimed_at`, and returns a
  `DeferralClaim` — the claimed `DeferredProposal` **and** the token; `None` when
  the deferral is absent, expired, or not `PENDING`. **Nothing may apply an answer
  without holding a claim** (§5, §9): this is what makes an answer apply at most
  once under concurrency, and it is the ADR-0044 §2 "a binding resolves once"
  invariant moved one step earlier so that it covers the *apply*, not only the
  bookkeeping.

  **The token comes back here and nowhere else**, which is what lets it stand as
  the capability `resolve` and `successor_to_claim` both key on (above). It is not
  a field of `DeferredProposal`, so no read republishes it and `export` cannot leak
  it — a capability is not the user's data, and an export that carried one would
  hand the ability to resolve a live claim to anything that reads the file.
- **There is no `release`, and its absence is a decision.** A claim is never
  returned to `PENDING` — not on a timeout (the lease ADR-0074 §9 declines) and not
  on request. An operation that re-opened a claim would have to be callable by
  something that is *not* the claim holder, since the holder of a crashed claim is
  gone; and a caller who can re-open a claim can re-open a **live** one, letting a
  third party apply the same answer while the first apply is still in flight — the
  duplicate write the claim exists to prevent, restored by the recovery mechanism.
  §9 states what a stranded claim does instead.
- **`pending(*, limit=50, offset=0) -> list[DeferredProposal]`** — the answerable
  questions: `state is PENDING` **and** before `expires_at` (§2's half-open comparison), judged against the
  store's own clock reading, read-time-relatively as every `MemoryStore` read is
  (ADR-0045 §6). Bounded by default for the reason ADR-0073 §2's
  bounded-default guarantee exists, as ADR-0073 §8 states it: it "keeps an unbounded
  read of a Tier 1 store from being what a caller gets by saying nothing".
  **One page is judged against one clock reading** — the clause
  ADR-0073 §8 makes explicit for `list_beliefs`, and it matters here for the same
  reason: a row dropped mid-scan shifts every subsequent offset. Total order: by
  `deferred_at` **ascending**, `id` ascending as tie-break (§7 argues the
  direction). A row whose `expires_at` is `None` never lapses out of this read.

  **`limit` and `offset` are `int` — a `bool` is not a count — and carry ADR-0073
  §2's explicit range, `0 <= value < 2**63`. Type and range are both refused before
  the first `await`.** Not a detail, and the range alone is not enough: `limit=-1`
  is SQLite's spelling for *no limit*, so an unvalidated negative turns the bounded
  read of a Tier 1 — sometimes Tier 0 — queue into an unbounded one; a value past
  the 64-bit bound surfaces a driver `OverflowError` instead of a
  `DeferralStoreError`; and `1.5` satisfies the range while a SQL driver refuses to
  bind it and an in-memory fake slices happily with it, so two conforming stores
  disagree about what the call even means. `True` is an `int` subclass and is
  refused for the reason ADR-0022 §4a already gives for `conflict_limit` — "a
  `bool` is not a count". ADR-0073 §8 makes the range refusals at **both** ends a
  named conformance obligation for `list_beliefs`; this read is the same shape,
  inherits them, and adds the type check the numeric range cannot express.
- **`interrupted(*, limit=50, offset=0) -> list[DeferredProposal]`** — the same
  bounded, ordered enumeration over `APPLYING` rows, under the same order, the same
  bounded default and the same argument range. It exists because §8 requires
  the surface to *show* an interrupted answer and §9 makes disposing of it the
  user's first recovery step, and after a restart the façade holds no id to `get`
  by: without this read the stranded question is unreachable, which is the vanishing
  this ADR is about, one state along. A **second enumeration** rather than a state
  filter on `pending`, following [ADR-0076](0076-stamped-conversations-are-enumerable.md)'s
  precedent for exactly this shape and ADR-0073 §9's reason for declining an
  `include_retired` axis: two different questions behind one flag is one argument
  doing two jobs, and the answerable queue is the read every caller wants by
  default.
- **`resolve(deferral_id, *, claim_id, state, answered_at, record_id=None,
  successor_id=None) -> bool`** — the terminal compare-and-set, atomic with its own
  read. It succeeds from `APPLYING` to **any** terminal state — `ACCEPTED`,
  `REJECTED`, `STALE` or `REDEFERRED` — **only when `claim_id` matches the token
  `claim` minted for it**, and from `PENDING` to `REJECTED` with `claim_id=None`
  (an unclaimed rejection writes nothing, so it needs no claim).

  **The two ids are separate parameters, not one overloaded slot.** An earlier
  revision said a `REDEFERRED` resolution "names the successor in place of
  `record_id`" while the payload rules forbade `record_id` on that state — an
  instruction to pass a value through a parameter the same contract says must be
  absent, which a fake would read as the successor and a SQL store would reject.
  Two names, each meaning one thing. A `REDEFERRED` resolution's `successor_id`
  must equal the one the store already stamped when it admitted that successor
  (above), so the transition is checked against durable state rather than trusting
  the caller to name the right question.

  **An unclaimed rejection is subject to the deadline too.** `PENDING → REJECTED`
  carries the same `now < expires_at` predicate every other operation does (§2's
  half-open comparison), and fails past it. Without that, a client that displayed
  the question a moment before it lapsed can reject it a moment after, and the
  lapsed row becomes a **retained `REJECTED` key** that suppresses a fresh
  identical proposal — the one outcome §7 says a lapsed key must not have. A
  question that is no longer answerable is no longer *rejectable*; the two are the
  same statement.

  **Every terminal state must be reachable from `APPLYING`, and `REJECTED` is the
  one an earlier revision omitted.** `MemoryWriter` takes an injected
  `MemoryPolicy`, and a conforming policy that is not `DefaultMemoryPolicy` may
  rule `REJECT` on a confirmed proposal — the writer's own contract lists it
  (ADR-0028 §8). An accept whose ingest returns `REJECT` then has no legal
  transition and strands forever. So the mapping from ingest outcome to terminal
  state is **total**, in the shape `_learn_decision` (`engine.py:345-366`) already
  uses for the same class of exhaustiveness: `ACCEPT`/`STORE_TEMPORARY`/
  `REINFORCE`/`SUPERSEDE` → `ACCEPTED` with the record id; `ASK_USER` →
  `REDEFERRED` with the successor's; `REJECT` → `REJECTED`; and the coordinator's
  own pre-ingest window check → `STALE` without an ingest at all (§6).

  **Each terminal state carries its own required payload, and the other's is
  forbidden**, in exactly the shape `MemoryDecision._outcome_fields_are_consistent`
  (`types.py:696-719`) already enforces for a ruling: `ACCEPTED` requires
  `record_id` and no successor; `REDEFERRED` requires `successor_id` and no record
  id; `REJECTED` and `STALE` require neither and permit neither. Without it a valid
  claim can resolve `ACCEPTED` with no record id at all, and the question then
  renders as applied while naming nothing that was written — a terminal state that
  lies, reached through the one call whose whole job is to record what happened.
  A malformed combination is refused, not silently normalised.

  `False` from any other state, on a mismatched or absent `claim_id`, and on
  a second attempt. The `claim_id` is what keeps the bookkeeping bound to the apply
  that actually ran: without it a caller who never applied anything could stamp a
  question `ACCEPTED`. It must be atomic within the store for the reason ADR-0074 §9
  gives for its conditional drop: "a drop that merely trusted its caller's earlier
  reading would be the race reintroduced one layer up."
- **`delete(deferral_id) -> bool`** and **`clear() -> int`** — ADR-0007's data
  rights, shaped as `MemoryStore.delete`/`clear` (`protocols.py:442`, `:453`), and
  **unconditional**: no state refuses them. ADR-0073 §9 declines a *band*-conditional
  delete because "it makes a data right conditional on a classification the system
  assigned", and a state-conditional one is the same mistake with an internal label
  instead of a band.

  **An `APPLYING` row is deletable too, and `purge` still may not touch one — the
  difference is who is acting, and it is the whole distinction.** A `delete` is the
  user destroying their own Tier 1 record, which ADR-0007 makes unconditional and
  ADR-0073 §6 already rules on: "the record is *destroyed*, unconditionally… losing
  the history is what they asked for". A `purge` is the system sweeping on a timer.
  If an in-flight `ingest` then commits, its `resolve` finds nothing and returns
  `False` — which after a `delete` means *the question was disposed of while the
  answer was being applied*, a true statement the coordinator reports (§9), and
  after a sweep would mean *the system quietly destroyed the only record that an
  answer was ever given*. The first is a consequence the user chose; the second is
  one nobody chose, which is why §2's `purge` excludes the state and `delete` does
  not.

  Deleting destroys the `question_key` with the row, which is what makes §9's
  recovery reachable.
- **`export() -> list[DeferredProposal]`** — ADR-0004 §6. A plain list of the frozen
  type the caller serialises with `model_dump(mode="json")`, matching
  `MemoryStore.export` (`protocols.py:461`) and `AuditTrail.export`
  (`protocols.py:1278`) rather than minting a bespoke export type: this store has
  one collection, so `PlanExport`/`ConversationExport`'s reason for existing does
  not apply.
- **`purge() -> int`** — shaped as `MemoryStore.purge_expired`
  (`protocols.py:474`), with **two named anchors and the same "a deadline is
  reached at the instant it names" convention** the answerability comparison uses
  (above). A row is purgeable when:

  - it is **terminal**, its `retention` is not `None`, and
    `answered_at + retention <= now`; or
  - it is **`PENDING`**, its `expires_at` is not `None`, and `expires_at <= now`.

  **Both read the record, never the live setting** — `retention` is the duration
  stamped at admission (above), so a configuration change never reaches back and
  shortens or extends a question already asked. And `retention is None` is a
  complete answer rather than an undefined expression: **a terminal row admitted
  under "ask me forever" is never purged**, which is the same choice its `PENDING`
  sibling makes and the same one the user made. A rule that only worked for finite
  durations would leave an implementation to raise or invent behaviour at exactly
  the setting the user chose deliberately.

  Both are inclusive at the instant, the same rule as answerability seen from the
  other side. **The two anchors are different on purpose, and the asymmetry is the
  decision.** A *terminal* row is retained for one further lifetime because
  something depends on it surviving: §7's no-nagging rule reads a `REJECTED` key to
  refuse re-asking, and that is the whole retention argument. A *lapsed* row has no
  such dependant — its key stopped speaking the instant it lapsed (§2), so nothing
  reads it and nothing is served by keeping it. Giving it the same grace, as an
  earlier revision did by symmetry, held an unanswered secret-tier proposal for
  **twice** the configured lifetime while §1 called that lifetime the cap on how
  long unresolved sensitive content sits. Retention has to be argued per state, not
  applied uniformly because the two lines look alike.

  So the `PENDING` clause is what makes §1's cap true, and it is the one a purge
  naturally omits: an unanswered question never transitions (expiry is not a state,
  above), so a purge keyed on terminal states alone keeps a lapsed secret-tier
  proposal forever.
  **It never removes an `APPLYING` row, at any age.** That row is the only durable
  record that an answer was begun; destroying it while its `ingest` is still
  running — a slow embed, a stalled store — would let the memory write commit
  against a question that no longer exists, so `resolve` fails and the fact that an
  answer was given survives nowhere. A sweep may not make that decision; a user
  may, and does, through `delete` (below). Correctness does not depend on `purge`
  running, but §1's exposure cap does, for every state except `APPLYING`.

Both `Sequence`-typed arguments and every mutable input are observed **before the
first `await`** ([ADR-0065](0065-a-call-observes-its-inputs-before-its-first-await.md));
this ADR cannot exempt a new Protocol from it.

**`core/errors.py` gains `DeferralStoreError`** in the `AssistantError` hierarchy,
for the reason ADR-0074 §9 added `ConversationStoreError`: every seam raises from
it and no existing class fits — a question is not memory, planning, context or
audit.

**The triad is owed by the implementing change, not by this one.** Per
`CONTRIBUTING.md` → "Adding a Protocol", in one change: the Protocol; a shared
`DeferralStoreContract` suite; and a canonical `FakeDeferralStore` in
`ai_assistant.testing` **plus** the concrete subclass that runs the suite against it
(the abstract base collects nothing on its own). And, per ADR-0028 §8's stated
convention, **a binding for the production store too** — a suite bound only to the
fake certifies the double while the real store drifts.
`tests/core/test_protocol_triad.py` enforces the first three mechanically.

**Nineteen clauses the suite must carry are named here**, because they are the ones a
suite of small explicit cases naturally omits and each is a claim this ADR makes
that would otherwise be prose:

1. **`claim` admits exactly one of two concurrent callers.** Two `claim`s on one
   `PENDING` deferral yield one record and one `None`, driven through the
   store-suspension hook the other contracts already use for their compare-and-set
   clauses rather than by hoping a sequential test observes a race. This is §9's
   whole guarantee; asserting only that a single `claim` succeeds tests nothing
   about it.
2. **`defer`'s admission is atomic**, driven the same way: two concurrent
   same-key calls leave **one** row, and two concurrent distinct calls at
   capacity-minus-one admit exactly one. A sequential test passes against a
   read-then-insert implementation and certifies nothing.
3. **`defer` raises on a physical id collision and mutates nothing** — a new
   deferral whose `id` matches a stored row carrying a **different** key, checked
   against a `PENDING` row and against a terminal one. Without it a dict-backed
   fake overwrites and a SQL store raises, and the suite certifies two different
   contracts. **And the intersection**: an input that is *both* a key duplicate of
   one row and an id collision with another **raises**, changing nothing (§2's
   precedence). Two clauses that each pass in isolation say nothing about which
   wins when both apply, and that is the input on which two backends diverge.
4. **`DeferralAdmission` reports the right outcome for a same-id, same-key
   retry** (§2), in `PENDING`, `REJECTED` and `APPLYING`: *suppressed*, never
   *admitted*. This is the case an id comparison got wrong, and a suite that only
   ever retries with a fresh id never reaches it.
5. **`successor_to_claim` admits past a full queue and only from a live claim, for
   the parent the successor names** (§2). At the cap, a **valid token whose claim
   is on the `APPLYING` deferral the successor's `predecessor_id` names** admits
   and stamps that parent's `successor_id`. Six refusals, each changing nothing: an
   **unknown token**; a token whose parent has since been **resolved**; a token
   whose parent **already carries a successor**; a **well-formed token for another
   live claim** — two questions claimed concurrently, the successor naming one and
   the token naming the other; a `predecessor_id` **with no token**; and a token
   **with no `predecessor_id`**. The fourth is the one a suite naturally omits and
   the one the two arguments exist together to catch: a suite that only ever passes
   the token it just received, for the parent it just claimed, certifies neither.
6. **`resolve` refuses every state but the one it names, and every `claim_id` but
   the one the record carries** — a second attempt, an `ACCEPTED` from `PENDING`
   (an accept that skipped its claim must not commit bookkeeping for an apply
   nothing authorised), and an `APPLYING` row addressed with a stale or absent
   `claim_id`.
7. **`purge` removes a lapsed `PENDING` deferral at `expires_at`** — seeded through
   an injected clock — **retains a `REJECTED` one until `answered_at + retention`,
   leaves an `APPLYING` one however old it is, and `delete` removes that same
   `APPLYING` row.** Four cases pulling in different directions, which is exactly
   why an implementation gets one wrong: the first is §1's exposure cap, the second
   is §7's no-nagging rule, the third is §9's guard on the record of an answer, and
   the fourth is ADR-0007's unconditional data right. A suite that applies one grace
   to every finished row passes the second and fails the first.
8. **`purge` reads the stored `retention`, not the live setting** (§2): a deferral
   admitted under one lifetime, resolved, and then judged after the setting has
   **changed** is still purged on the duration it was admitted with. Nothing else
   in the suite varies configuration between admission and resolution, so nothing
   else reaches this — and an implementation that reads the setting passes every
   other purge clause.
9. **`defer` collides on the key and only on the key.** Two proposals differing
   *only* in `provenance.source`, and two differing only in `sensitivity`, must both
   admit as separate questions (§7), while an identical repeat collides and does not
   refresh the deadline. A suite that varies only `content` certifies a weaker key
   than the one ratified.
10. **An expired, an `ACCEPTED`, a `STALE` and a `REDEFERRED` key do not collide; a
   `REJECTED` one within retention, and an `APPLYING` one, do** (§2, §7). These are
   the differences between "we asked and you declined", "that question lapsed", and
   "an answer to that may be committing right now", and a suite that tests only the
   live collision leaves all of them unpinned.
11. **The deadline boundary is driven at the instant itself** (§2), on an injected
    clock: a deferral read at exactly `expires_at` is **not** answerable — absent
    from `pending`, refused by `claim`, outside the cap count, no longer speaking
    for its key — and one read an instant before it is answerable on all four. The
    listed clock cases otherwise step well past the deadline and never touch the
    comparison that two backends actually spell differently. **And `purge`'s own two
    boundaries at their instants** (§2): a terminal row exactly at
    `answered_at + retention`, and a lapsed `PENDING` row exactly at
    `expires_at` — each purged at equality and each retained one instant before.
    The two anchors differ, so a suite that drives one and infers the other proves
    nothing about the one that carries §1's exposure cap.
12. **A deferral admitted under "ask me forever" never lapses and is never purged**
    (§2, §6): with `expires_at=None`, `pending` returns it after any clock advance,
    `claim` takes it, its key still collides, and `purge` leaves it — **and, once
    `REJECTED`, `purge` still leaves it**, because `retention` is `None` too. Five
    assertions, because an implementation that coerces `None` to a sentinel passes
    the first three and fails the rest, and one that handles only the `PENDING`
    half raises or invents behaviour on the terminal one.
13. **`interrupted` enumerates `APPLYING` rows** in the same total order and with the
   same bounded default as `pending`, and the two reads are **disjoint**: no row
   appears in both. A store that returned an interrupted question among the
   answerable ones would offer the user a claim that cannot be taken.
14. **Both reads refuse `limit`/`offset` outside `0 <= value < 2**63`, at both
    ends, and refuse a non-`int` or a `bool` before any await** (§2) — a float, a
    string and `True`, each of which either satisfies the range or passes an
    `isinstance(x, int)` check while meaning something no two backends agree on.
    A **non-zero `offset` asserts the returned ids** rather than the page length —
    ADR-0073 §8's own warning, that an implementation ignoring `offset` returns a
    full ordered page every time and passes a length-only assertion for good. And
    the **default `limit` is exercised with more than 50 matching rows**, for §8's
    other reason: an implementation defaulting to unbounded satisfies every
    explicit-limit case while breaking the bounded-default guarantee.
15. **`resolve` refuses each malformed terminal payload** (§2): `ACCEPTED` without a
    `record_id`, `ACCEPTED` carrying a `successor_id`, `REDEFERRED` without a
    `successor_id`, `REDEFERRED` carrying a `record_id`, `REDEFERRED` naming a
    successor other than the one the store stamped, and `REJECTED`/`STALE` carrying
    either. Six cases, because the transition tests pass against a store that
    writes whatever payload it is handed, and the two ids are separate parameters
    precisely so each of these is expressible rather than ambiguous.
16. **An unclaimed rejection past the deadline fails** (§2): `resolve(state=REJECTED,
    claim_id=None)` succeeds an instant before `expires_at` and fails at it, and the
    lapsed row's key still does not collide afterwards. Without the second half the
    clause proves the refusal without proving what the refusal is *for* — that a
    question nobody could answer cannot become a retained `REJECTED` key that
    suppresses the next honest proposal.
17. **`DeferredProposal` refuses an inconsistent deadline pair** (§2): a positive
    `retention` with `expires_at=None`, a `None` `retention` with an `expires_at`,
    a non-positive `retention`, and an `expires_at` that is not exactly
    `deferred_at + retention`. Every listed case elsewhere constructs an honest
    pair, so nothing else reaches the record that defeats §1's exposure cap while
    being perfectly well-typed.
18. **The fingerprint and the key agree across independently built inputs** (§7):
    a proposal reconstructed field-by-field from a serialised form fingerprints
    identically to the original, and a confirmation issued against the first
    verifies against the second. This is the parity the confirmed path depends on
    and the one a suite that always hashes the same in-memory object never tests —
    the failure it guards is not a mismatch on some input but a mismatch on
    *every* input, i.e. no asserted conflict ever confirmable.
19. **The key is a canonical projection** (§7), which needs a case per excluded
    field and a case per collection. Two proposals differing *only* in `validity`
    admit as separate questions; two differing only in `id`, only in `score`, or
    only in `provenance.last_updated` **collide**; two whose `evidence` or whose
    frozen conflict-id set differ only in **order**, or only in a **repeated
    member**, collide; and two
    `ProceduralMemory` proposals whose `steps` differ only in **order** do
    **not** — they are different workflows. The last pair is the one a suite
    written with tidy fixtures never reaches, since the sequences it builds happen
    to be in the same order every time, and it is the pair that decides whether
    the canonicalisation is a criterion or a blanket sort: a blanket sort passes
    every other clause on this list while letting a pending "back up, then delete"
    suppress "delete, then back up".

### 3. The enqueue is the coordinator's, and two composition-root obligations come with it

`MemoryWriter.ingest` (`protocols.py:531`) does not change, and does not learn to
queue — ADR-0028's Consequences ruled that out and this ADR agrees with the ruling
rather than working around it. Instead the **orchestration write stage** — which
already holds the `MemoryWriter` by injection and now also holds the
`DeferralStore` — observes `result.decision.kind is ASK_USER` and enqueues.

This is ADR-0074 §9's coordinator rule applied unchanged: "the two-store sequence
belongs to a coordinator, not to either store… `orchestration` is the one place
that legitimately holds both handles by injection." Neither store may hold the
other (golden rule 1), and the sequence spans both.

**What it enqueues is a snapshot, not the proposal it was handed, and the
difference is the whole point of §4.** `MemoryIngestor` resolves conflicts onto its
*own* copy (`ingest.py:477-479`), so the caller's proposal still carries an empty
`conflicts` when `ingest` returns. The stage must therefore build the
`DeferredProposal` around a proposal whose `conflicts` is **exactly
`result.conflicts`** — the ids the policy actually ruled against (§4). Enqueuing
the untouched original is the failure this obligation exists to name: it satisfies
every store and writer conformance clause, and it produces a question that shows
the user no conflicting assertion, an answer whose `retires` is empty, and a
re-ingest that finds that assertion outside the authority and **re-defers** (§5a
step 1). The user answers, and is asked again. §10's end-to-end assertion drives
exactly that path.

**It is a property of the write stage, not of `learn`.** `LearningLoop.learn` is
today's only path to `ingest`, and ADR-0077's observer is the second producer. The
obligation its implementing lane inherits is exactly one sentence: **a proposal
reaches memory through the orchestration write stage, not through a `MemoryWriter`
handle of its own.** A producer holding the writer directly gets the ratified
policy and applier and silently loses the queue — the drop this ADR ends, restored
by a wiring choice.

That obligation is affordable because ADR-0077 §4 already pays its half: a deferred
proposal is **self-contained**, so the stage can hold it without holding anything
of the producer, and the producer "neither retries a deferral, nor escalates it,
nor rewrites the proposal to avoid it, nor holds it to re-submit". A producer that
did any of those would be a second, unratified resolution path racing this one.

**Two composition-root obligations, stated rather than assumed**, in the form
ADR-0028 §4 established for the same class of hazard — the shape ADR-0052 §1
describes as "a composition-root single-instance obligation… no type expresses it":

1. The `DeferralStore` the write stage enqueues into is the **same instance** the
   façade enumerates from. A second instance queues questions nobody can answer.
2. The `MemoryWriter` an answer applies through writes to the **same
   `MemoryStore`** whose records the question's frozen conflict set names. This is
   ADR-0028 §4's existing same-store obligation, and the answer path is a second
   place it must hold: applying a confirmed retirement against a different store
   would retire nothing while reporting success.
3. **The answer path is the only producer of a `UserConfirmation`**, and it
   produces one only from a deferral it has claimed (§9). This is the obligation
   §5's bounded authority rests on, and unlike the first two it is not merely a
   wiring rule: a second producer of confirmations is a second thing that can
   authorise retiring a user's assertion, which is the one authority in this system
   that has never been delegable.

### 4. The ruling must carry back what it was ruled against

`MemoryIngestResult` gains `conflicts: tuple[str, ...]` — the ids the policy was
shown, defaulting to `()`.

ADR-0028 §3 declined this and named the exact condition for revisiting: "If a
consumer ever needs to *show* a user what a proposal contradicted, that is a change
to the result type, decided then, with a use case in hand." **This is that use
case**, and it is stronger than presentation: §5 makes the shown set the *bound on
what the answer authorises*, so the ids are load-bearing for correctness, not
decoration.

The value already exists one frame in. `MemoryIngestor._ingest` resolves conflicts
and stamps them onto its own copy of the proposal (`ingest.py:477-479`) before
calling the policy — but that copy is local and the result carries only `decision`
and `record_id`, so the caller's proposal still has an empty `conflicts`. Nothing
new is computed; a value that already crosses the policy seam now also crosses the
writer seam.

**The alternative is worse and is rejected explicitly.** Having the coordinator
re-detect conflicts is re-deriving `_detect_conflicts` in `orchestration` — the
duplication ADR-0028 §4 deleted and must not reintroduce. Re-detecting them
*later*, at answer time, is worse still: the set would have moved, and the user
would have been shown one thing and authorised another.

ADR-0028 §8's conformance suite gains one clause: **`ingest` returns the conflict
ids it resolved, on every ruling**, so an implementation that computes them
internally and drops them fails. It is not a claim about *which* records conflict —
that stays `MemoryIngestor`'s tuning and is still excluded (§8's existing
exclusions stand).

### 5. Accepting applies the proposal through the ratified path, under a bounded authority

An accepted question is re-submitted through **the same write path**, not through a
second one. The coordinator first **claims** the deferral (§2, §9) — which both
proves it was open and makes this the only apply of it — then rebuilds the proposal
from the claimed `DeferredProposal` with one addition: a `UserConfirmation` naming
the deferral and carrying `retires`, set to **exactly the conflict ids the question
froze and the surface showed**. It then calls `MemoryWriter.ingest`. Conflict
detection, the policy, the atomic applier and the full-set retirement rule all run
unchanged.

Three ratified rules govern what happens next, and they are cited rather than
restated:

- **The precedence rule is recency**, from ADR-0050 §2: "once a contradiction is
  confirmed… the later assertion supersedes the earlier, closing its window and
  keeping it in `export`." That is the ruling this ADR causes; it does not invent
  it.
- **The mechanics are ADR-0045 §4's**, as amended onto ADR-0028 §8: a `SUPERSEDE`
  leaves the target *retained with a closed validity window* and writes the
  correction at a **new id absent from the store**, returned as
  `MemoryIngestResult.record_id`. Nothing is destroyed; the user's earlier
  assertion stays in `export`, which is what made ADR-0050 §2 willing to ask the
  question at all. **How that window is closed is now ADR-0080's**, which
  partially superseded ADR-0045 §4 step 1: a producer-set bounded window is
  **clamped**, with a narrow refusal for the case it cannot represent. This ADR
  inherits that rule exactly as ADR-0080 §6 says any resolution mechanism does —
  "whoever commits an `ASK_USER` resolution inherits this rule with [ADR-0079]
  §1's" — and it inherits it by the same route as everything else: **the confirmed
  answer is a re-ingest**, so the ratified applier applies it. There is no second
  supersession path here for a rule to be forgotten on.
- **The write is atomic**, by ADR-0046's `write_atomic` (`protocols.py:283`) with
  `INSERT_IF_ABSENT` for the correction (`types.py:574-581`), as ADR-0045 §8 ruled
  and ADR-0050 §1 applies to a multi-target retirement.

**Two narrowings are needed, and each is the discharge of a stated deferral rather
than a new liberty.**

**(a) `DefaultMemoryPolicy` gains one rule, ahead of every existing rule.** A
proposal carrying a `confirmation` is judged in three steps, in this order:

1. If the live conflict set holds a `USER_ASSERTED` record **not** named in
   `confirmation.retires`, rule `ASK_USER` — an assertion the user was never shown
   is outside the answer's authority, and committing beside it is the #245 gap
   (ADR-0050 §2). The answer becomes a **re-deferral** (§9), not a write.
2. Otherwise rule `SUPERSEDE` on the first id in `confirmation.retires` that is
   present in the live conflict set.
3. Otherwise rule `ACCEPT`.

The rule must come **first** because both the secret-tier arm
(`policy.py:155-159`) and the assertion arm (`policy.py:73`) would otherwise
re-defer the answer to the question they just asked, forever. Step 1 is what keeps
that precedence from becoming a blanket override: the confirmed path skips the
questions already answered, not the ones not yet asked.

This is ADR-0079 §2's ordering, unchanged, on the confirmed path: the set is
complete before the ruling, the ruling is made on the whole set, and **only a
`SUPERSEDE` retires anything** — so a re-deferred answer leaves the store exactly
as it was and "retires nothing on its way". Sweeping the covered inferences while
asking about the newly-surfaced assertion is refused for ADR-0079 §2's own reason:
it would commit part of a correction the user has not yet confirmed.

**(b) `_refuse_unsafe_fold` clause 1 is narrowed by exception, not lifted.** Today
it refuses any fold onto a `USER_ASSERTED` target unconditionally
(`ingest.py:111-151`), because "the conflict signal is topical similarity, not
contradiction… and is too weak to retire a record the user gave us". That
justification is exactly and only about the *signal*. Clause 1 therefore stands
verbatim in every case except one: **a `SUPERSEDE` whose target id appears in the
incoming proposal's `confirmation.retires` is permitted**, because there the signal
is not topical similarity — it is the user's answer, which ADR-0045 §7 named as one
of the two acceptable gates. Clause 2 (a `USER_ASSERTED` proposal onto an
`EXTERNAL` target, `REINFORCE` only) is untouched.

Likewise **ADR-0050 §1's `USER_ASSERTED` hold-out from the retirement set is
narrowed to the same exception**: the applier still never sweeps an asserted
conflict in on similarity, but an asserted conflict *named in `retires`* is
retired. Everything else in ADR-0050 §1 stands, including the `EXTERNAL` hold-out.
Its over-limit surplus clause is deliberately not cited anywhere here: ADR-0079 §1
replaced it, re-founding `conflict_limit` as a **ceiling rather than a truncation**,
and the confirmed path inherits that reach with everything else it inherits by
re-ingesting (ADR-0079 §2).

**The authority is bounded by what was shown — and the bound is over *assertions*,
not over every conflict.** This is the load-bearing clause and it must be stated at
exactly the right width, because too wide contradicts ADR-0038 and too narrow
forges consent.

`retires` is a **ceiling on the clause-1 exception** (§5b): it authorises retiring
records that could not otherwise be retired at all — `USER_ASSERTED` ones. It says
nothing about derived beliefs, because a user assertion has *never* needed
permission to overturn an inference. ADR-0050 §Alternatives rejects asking about
those in terms: "an inference is a derived belief a user correction is *entitled* to
overturn without asking (ADR-0038's whole point)." So:

- **A derived conflict that appeared after the question was frozen is retired**, by
  ADR-0050 §1's ratified full-set rule, with no confirmation involved. It is exactly
  what a plain `learn` correction would have done to it a moment earlier. Requiring
  a fresh question for it would make the confirmed path *stricter* than the
  unconfirmed one and leave the store holding beliefs it was just corrected about —
  the #244 defect ADR-0050 §1 exists to close.
- **An asserted conflict the user was never shown blocks the apply.** If the live
  conflict set holds a `USER_ASSERTED` record not named in `retires`, the policy
  rules `ASK_USER` again and a fresh question is minted over the new set (§5a).
  Superseding the covered assertion while committing beside the uncovered one is
  the #245 gap reached by a new path, and it is the case where extending the user's
  answer to a record they did not see would forge consent. §7's dedup does not
  suppress the new question, because a different conflict set is a different
  `question_key`. The writer floor refuses the same fold independently (§5b, check
  2), so the guard holds even under an injected policy that ignores this rule.
- A conflict the user *was* shown that has since been retired or deleted simply is
  not in the live set; the apply proceeds without it. Authorising a retirement that
  is already moot costs nothing.
- `retires` is empty for the secret-tier arm, which asks "may I keep this at all?"
  and authorises no retirement. `UserConfirmation` being a value rather than a bare
  `tuple[str, ...] | None` is what keeps that case from reading as "no confirmation"
  under a truthiness check — the silent re-deferral that encoding would produce. It
  is the same class of misread `MemoryWrite` is frozen to prevent
  (`types.py:592-599`).

**What the floor checks, and what it cannot.** An earlier draft of this section
left `confirmation` entirely unverified and called that a coordinator convention.
That was too weak, because it misread what the floor is for. `_refuse_unsafe_fold`
lives at the writer boundary precisely so that it does not depend on anyone's good
behaviour: "a policy reaches the ingestor through an injected seam and any
conforming implementation may rule differently. The refusal therefore lives here,
at the boundary that performs the write, rather than in the policy that recommends
it" (`ingest.py:135-139`). A gate that opens on an unexamined field hands that
guarantee back. So the exception carries four checks of its own, all of them
performable at the boundary with what the writer already holds:

1. The ruling is `SUPERSEDE`. A `REINFORCE` onto an assertion stays refused under
   clause 1 whatever the confirmation says — folding at the target's id would
   rewrite the user's own words, which no answer authorises.
2. The target id is in `confirmation.retires`.
3. The target id is also among the conflicts this very ingest resolved (§4). A
   confirmation cannot authorise retiring a record the current ruling was not even
   made against.
4. **`confirmation.proposal_fingerprint` equals the fingerprint recomputed from
   the proposal being ingested** (§2). This is the check that stops the value being
   a bearer token, and it is the one an earlier revision was missing: checks 1–3 all
   pass when a confirmation given for question Q1 is presented with a *different*
   proposal Q2 that happens to conflict with the same assertion, and the user's
   answer to Q1 would then retire it on Q2's behalf.

   **It is a fingerprint rather than the proposed record's id**, because an id
   binding is not a binding: `MemoryRecord.id` is caller-minted and unique only
   among *stored* records, so two unpersisted proposals with entirely different
   content can carry the same one, and a `SUPERSEDE` mints a fresh output id so no
   storage collision would stop the unauthorised retirement either. A digest over
   what the proposal *says* has no such gap. The binding holds by construction on
   the honest path: §5's coordinator rebuilds the proposal from the claimed
   `DeferredProposal`, so what it fingerprints is what the question was asked about.

**What no in-process value can do, stated plainly rather than implied.** None of
this makes the confirmation unforgeable, and this ADR does not claim it does. Any
subsystem holding the injected `MemoryStore` can already call `write_atomic`
(`protocols.py:283`) and close any window it likes; a floor on the writer is not a
security boundary against arbitrary in-process code and never was. What it *is* —
and what the four checks above restore — is a guarantee that **no ruling reaches a
user assertion by inference**: not from a policy's judgement, not from topical
similarity, not from a confirmation that belongs to another question. The remaining
step, that a claimed confirmation corresponds to a deferral a user actually
answered, is enforced one layer up by §9's claim: the answer path is the only
producer of a `UserConfirmation`, and it cannot run without having taken the
deferral from `PENDING` to `APPLYING` first. That is the "coordinator-owned
operation that binds the accepted answer to the stored deferral" this arrangement
rests on, and it is a mechanism rather than a convention.

**ADR-0028 §8's conformance suite gains its second clause**, in four parts. A
`SUPERSEDE` naming a `USER_ASSERTED` target **raises**: without a covering
`confirmation`; with one whose `retires` does not name that target, or whose named
target is absent from the resolved conflicts; and — the case that would otherwise
go untested — **with a confirmation issued for a different proposal**, exercised by
presenting one question's confirmation alongside a second proposal that conflicts
with the same assertion. That last case needs the two proposals to **share a
proposed record id and differ in content**, because that is exactly the input an
id-based binding waves through and a fingerprint refuses; a suite that varies the
id instead passes against the weaker binding this ADR rejected. It **applies** only
when all four checks hold. A suite asserting only the refusal certifies the gate as
shut; one asserting only the pass certifies nothing about the floor; one omitting
the mismatch cases certifies a bearer token rather than a bound authority.

### 6. Rejecting, expiring, and going stale — three endings, three meanings

**Reject** stamps the deferral `REJECTED` with `answered_at`, writes nothing to
memory, and **retains the record** until §2's `purge`. Retention is not
sentimentality; it is what makes §7's dedup honest. Without it a chatty producer
re-proposes the same thing tomorrow and the user is asked a question they already
declined. Retaining a *question* is also not the same as retaining a *belief*: ADR-0073
§6's "kept versus destroyed" contrast is about beliefs, and nothing here was ever
one. A user who wants the record of having been asked destroyed uses
`DeferralStore.delete` (§2).

**Expire, and it is not a state transition.** A deferral carries `expires_at`,
stamped at deferral from a configured lifetime. Past it the question is not
presented by `pending`, `claim` refuses it, and so no answer can be applied. The
row keeps its stored `state` of `PENDING`: expiry is **read-time-relative and never
stamped**, exactly as `MemoryRecord.expires_at` is (ADR-0007 §3, ADR-0045 §6), so
nothing has to run for a question to stop being answerable and there is no sweep
whose failure re-opens one.

**That choice puts a load on `purge`, and §2 states it rather than leaving it to be
inferred.** An unanswered question never reaches a terminal state, so a `purge`
keyed on terminal states alone would keep every lapsed question — including a
`DataTier.SECRET` proposal — on disk forever, while §1 promises the lifetime is a
cap on how long unresolved sensitive content sits. `purge` therefore covers
expired-and-unanswered rows as well as terminal ones (§2), and the conformance
suite drives the case (§10).

**The lifetime is finite by default, and that is the whole decision.** The codebase
holds both shapes and the choice between them is exactly the mistake ADR-0074 §7
warned about in `core/config.py:373-385`: `confirmation_ttl` defaults to `None`
(`config.py:361-365`), meaning a parked confirmation never goes stale, while
`episode_retention` defaults to `timedelta(days=30)` (`config.py:393-401`) because
the `None` default "would mean unbounded episodic retention". A memory deferral
belongs with the second. A permission confirmation gates an action **the user just
asked for** and is worthless once stale; a memory deferral is generated **by the
system**, at whatever rate the observer runs, and a never-expiring queue of
machine-asked questions is precisely the undignified pile §7 exists to prevent. So:
a `deferral_ttl` setting, positive, defaulting to a finite duration, with `None`
reachable only as the user's deliberate "ask me forever" choice.

**`None` is a real value with stated behaviour, not a gap.** A question deferred
under `deferral_ttl=None` carries `expires_at=None`, and every operation that
compares against a deadline treats it as never reached: `pending` keeps returning
it, `claim` accepts it, its key keeps speaking for it, and — the one that must be
said out loud — **`purge` never removes it**, since it has no horizon to be past.
Left unstated, one implementation would store a sentinel far-future instant and
another a `None`, and two conforming stores would disagree about whether a question
still exists; §2 makes the field optional and this the rule, and the conformance
suite drives the `None` case through all four. The consequence is the one the user
chose, in the same words `core/config.py:382-384` already uses for
`episode_retention`: `None` means keep it forever, and it is deliberate. §1's
exposure cap is a promise about the *default*, and it says so.

**Stale is not expired, and the difference is the proposal's own clock.** A
proposal's record carries its own validity window (`MemoryBase.validity`,
`types.py:498`, ADR-0045 §2). If that window is **not open at the answer instant**,
accepting would write a record that is already retired — a belief born dead. The
answer path therefore checks it and, when closed, refuses the apply and stamps the
deferral `STALE`. Two independent deadlines, both of which must hold: `expires_at`
says *the question* went unanswered too long; `STALE` says *the answer arrived, and
the thing it was about no longer applies*. Collapsing them would tell a user who
answered promptly that they were too slow — and `STALE` is stored where expiry is
not, because it records something that *happened*: a person answered and the system
declined to act. That is worth keeping; a question nobody answered is not.

This reads the **envelope** window only. Reconciling `SemanticMemory.valid_until`
with it is ADR-0045 §10's open item and is not touched here (§11).

**The check is at the answer, not at the write, and this ADR says so rather than
implying a guarantee it does not deliver.** The coordinator reads the window when
the answer arrives; `MemoryIngestor` does not re-read it before storing, so a
window that closes *during* the apply — between the check and the `write_atomic` —
still lands a record that every subsequent read hides. Three things make that the
right place to stop:

- **Nothing is lost, and nothing is inconsistent.** The record is written, retained,
  and in `export`; it is merely not live. That is the ordinary read-time-relative
  behaviour the memory model already has, and ADR-0028's amendment describes the
  same class of outcome for supersession in the same terms — "a read-time-filtering
  property, not a supersession bug".
- **The write boundary deliberately does not check, and that is now ratified rather
  than pending.** [ADR-0080](0080-retiring-a-producer-set-bounded-validity-window.md)
  §5 answers "whether `MemoryStore` should refuse a producer-set bounded envelope
  window at write time" — **no**, on ADR-0045 §6's ratified posture, and it records
  that as answered rather than deferred. So the check this ADR performs at the
  answer is not a stopgap standing in for one the write path will grow: it is the
  only place such a check belongs, and it exists here because a *question* going
  stale between asking and answering is a product fact about the user's answer, not
  a storage rule.
- **A store-authoritative instant is a different question with a different owner.**
  Issue **#460**, split out of #306 by ADR-0080 §9, is the absolute
  clock-coherence-independent guarantee; it is a `MemoryStore` lane. Nothing here
  waits on it.

### 7. Volume: dedup by question, a cap that refuses rather than evicts, oldest first

The observer will produce proposals continuously and some fraction will be ruled
`ASK_USER`. Three rules keep the queue dignified at that rate. None of them designs
the observer.

**Dedup on a `question_key`, defined by a criterion and an exclusion list rather
than by an inventory of what counts.** In two layers, because §5's writer check
needs the inner one on its own:

- the **`proposal_fingerprint`** — a digest over a **canonical projection** of the
  proposed `MemoryRecord`, plus the proposal's `sensitivity`;
- the **`question_key`** — `digest(proposal_fingerprint, sorted conflict ids)`.

The writer can recompute the fingerprint from a proposal it holds and cannot
recompute the key, whose conflict set was frozen when the question was asked (§5b
check 4).

**Both are computed properties of `MemoryUpdateProposal`, not fields anyone
supplies, and both use the encoding this repository has already ratified.** That is
`PermissionDecision.parameters_digest`'s arrangement, adopted wholesale because it
was designed for this exact hazard and argues itself better than a restatement
would: SHA-256 over `_canonical_json`'s ADR-0021 §1 form (`ensure_ascii=False`,
UTF-8, keys ordered), typed `Sha256Hex`, and computed **on the model that owns the
data** — because "a `str` field each caller filled in would be a canonicalisation
per caller, and two that disagreed would produce a false mismatch at execution —
which reads as an attack rather than as a bug" (`types.py:2653-2682`).

The failure that argument prevents is precisely the one here. The coordinator
fingerprints at admission and the writer recomputes at answer time; two *specified*
implementations of "a deterministic digest over a canonical projection" — one over
`model_dump(mode="json")`, one over a Python repr — are each deterministic, disagree
on every input, and the symptom is that **no asserted conflict can ever be
confirmed**, with the confirmed apply refusing at check 4 for a proposal that is
honestly the one asked about. One property on one model cannot come apart from
itself. `question_key` is likewise a property, delegating to the fingerprint and
the proposal's own frozen `conflicts`, so the store indexes a value it never has to
be told.

The projection is the whole record minus the fields that are *bookkeeping about the
record rather than the belief it states*, and there are exactly three:

- **`id`** — identity, minted per proposal, so including it makes the key match
  nothing at all.
- **`score`** — `None` on a stored record and populated only by retrieval
  (ADR-0005 §1); it says how a search ranked something, not what is believed.
- **`provenance.last_updated`** — **transaction time**, which ADR-0045 §3 clarified
  it to be. It is when the record was written, not what it says. Including it is
  the failure mode this criterion exists to catch and an earlier revision walked
  straight into: two identical observations produced a minute apart carry different
  stamps, so every one of them is a new question and the user is nagged by the
  mechanism whose job is to stop that.

Everything else stays in, and where a field is arguable the criterion decides it
rather than taste. `confidence` is **in**: a belief offered weakly and the same
words offered strongly are different things to be asked to accept
(ADR-0072 §6 makes confidence the producer's belief strength). A producer that
jitters its confidence across re-observations of one thing is emitting genuinely
different proposals, and stabilising that is ADR-0077's obligation, not something
this key should paper over.

**Canonical normalises the order of collections that are *sets in meaning*, and
preserves it everywhere else.** The criterion is whether reordering the members
changes what the record says.

- **Normalised — sorted *and deduplicated* — `Provenance.evidence` and the frozen
  conflict-id set.** Both are bags of references — "references (e.g. episode ids)
  supporting this record" — where membership is the content and position is an
  artefact of how they were gathered. Conflict detection ranks by score, so two
  equal-scored conflicts come back `(A, B)` on one call and `(B, A)` on the next;
  digesting the raw sequence would mint two keys for one question, the same nag as
  a transaction stamp, from ordering. **Deduplication is the same argument, not an
  extra one**: if membership is the content, then `("episode-1",)` and
  `("episode-1", "episode-1")` state the same support, and a normalisation that
  sorted without deduplicating would let a repeated id do exactly what a reordered
  one would — admit a second question for a set the user has already been asked
  about. Sorting alone answers half the criterion.
- **Preserved: `ProceduralMemory.steps`, and every other ordered field.** A
  workflow *is* its order. "Back up the database, then delete it" and "delete the
  database, then back it up" are the same three words and opposite instructions,
  and sorting them would let a pending version of one **suppress** the other —
  the queue silently swallowing a materially different, potentially destructive
  procedure on the grounds that it looked alike. That is the rule this key exists
  to enforce, broken by the mechanism meant to enforce it.

The criterion is stated rather than the list, for the same reason the exclusions
are: `EpisodicMemory.participants` reads as set-like and `steps` does not, and the
next ordered field should be classified by asking the question rather than by
finding this paragraph. Where a field's meaning is genuinely ambiguous, **preserve
the order** — the cost of preserving it is a duplicate question the user can
dismiss, and the cost of normalising it wrongly is a question they never see.

The shape of this rule is the decision, not a shorthand for a list. An enumerated
key looked sufficient in an earlier revision and omitted the `validity` window, so
two proposals with identical words — one expiring tomorrow, one open-ended —
collapsed into one question, and answering it stored a belief that dies tomorrow
while the durable one was never asked about. That was not a missing entry but the
wrong shape: **anything that changes what accepting would store changes what the
user is being asked**, and an inventory has to be extended by whoever adds the next
field, in a file they are not editing. An exclusion list with a stated criterion
classifies the next field for them.

Two consequences are worth naming. An `OBSERVED` proposal and a later `USER_ASSERTED` one with identical
content are **not** the same question — the first asks "shall I keep what I worked
out?", the second is the user telling us directly, and collapsing them would show
the user the observation while silently discarding the assertion, which is the drop
this ADR exists to end reintroduced by the mechanism meant to keep the queue tidy.
And a `SECRET` and a `PERSONAL` proposal ask different questions even when the words
match, which is why `sensitivity` is in the key although it is not part of the
record. A different conflict set is likewise a different question, and §5's bounded
authority depends on it.

`defer` is idempotent on the key (§2): a second arrival is admitted as **nothing**,
and comes back as a *suppressed* `DeferralAdmission` whose `deferral` is the
existing question — never as a bare id, which is the shape §2 replaced and which a
caller reading this section alone would otherwise write. Its deadline is **not
refreshed**: refreshing would let a chatty producer keep a question alive
indefinitely by re-proposing, which is the opposite of a lifetime.

**A rejected key is not re-asked while it is retained.** A producer re-proposing
something the user declined gets no new question. This is the one place this ADR
deliberately does *not* surface something, and the distinction matters: the
question **reached the user and was answered**. Asking again is not honesty, it is
nagging.

**Suppression is reported, not silent, and that is what makes it reversible.**
`defer` returns a `DeferralAdmission` (§2), and the coordinator branches on its
`outcome` — never on an id comparison, which is the shape §2 rejects:

- **admitted** — the question was parked; render that, with its id.
- **suppressed** — an existing question stands in the way, and the admission's
  `deferral` says **which and in what state**: for a `REJECTED` row, "you declined
  this on <date>; forget that question to be asked again"; for an `APPLYING` one,
  §9's first recovery step.
- **refused** — the queue is full and there is **no deferral to read at all**. The
  line names the queue rather than a question: answer or clear some of what is
  waiting, and re-submit. Reaching for `admission.deferral` here is the dereference
  the three-shape validator exists to make impossible to write by accident.

`learn` renders whichever line applies, so the user is never left holding a
correction the system quietly swallowed — and that includes the full-queue case,
which is the one an implementation is most likely to leave as a silent no-op.

That is a correction to an earlier revision of this section, which claimed an
immediate change of mind was "reachable by `learn`". It is not, for an *identical*
re-proposal: `learn` produces the same key, `defer` hands back the rejected row, and
that row is not `PENDING` so it cannot be answered — permanently, under
`deferral_ttl=None`. The reversal path is therefore **stated as two steps, the same
shape as §9's**: forget the prior question, then `learn` again. Waiting out the
retention works too, when there is one. `learn` remains the only correction path
(ADR-0073 §6: "inspection adds no second correction path"; nor does this) — what
changes is that the surface says what is standing in its way.

**A cap that refuses new questions and keeps old ones — and it is strictly
positive.** A cap of `0` is at capacity before its first admission, so every
`ASK_USER` proposal is refused and the drop this ADR exists to end returns in full,
by configuration, while the system reports health. That is precisely the class of
value ADR-0022 §4a refuses at construction because it "disables a stage while the
loop keeps reporting health", and `core/config.py` already refuses its siblings the
same way (`confirmation_ttl` and `conversation_tombstone_grace` both carry
`gt=timedelta(0)`). So the cap is `gt=0`, refused at load rather than per
admission. There is no "unlimited" spelling: an uncapped queue is what §7 exists to
prevent, and `deferral_ttl`'s `None` is already the deliberate "ask me forever"
escape at the other axis.

The **answerable** queue —
`PENDING` and before `expires_at`, the same set `pending` returns — is bounded by
a configured maximum. Lapsed and resolved rows awaiting `purge` do not count
against it, so a queue cannot be held shut by questions nobody can answer. At the
cap `defer` returns a **refused** `DeferralAdmission` carrying no deferral, and the
proposal is not enqueued; the refusal is **reported, not swallowed** — it reaches
the caller, so `learn` renders it and the surface says the queue is full. Eviction is rejected:
dropping the oldest question to make room for a newer one is the silent vanishing
this ADR exists to end, performed by the mechanism meant to prevent it. Refusing the
*new* one is safe in a way evicting the old one is not, because the producer still
holds it and can re-propose — the observer re-observes, and a user can re-`learn` —
whereas an evicted question is gone with no producer left to notice. And a full
queue is itself the signal the user must act on.

**Oldest first.** `pending` orders by `deferred_at` ascending, `id` ascending as
tie-break (a total order, as ADR-0073 §2 requires of an enumeration). The head of
the queue is then the question closest to expiring and the one whose admission is
blocking a newer one, so the cap and the lifetime are both legible from the first
page rather than discoverable only by paging to the end.

### 8. How the question reaches the user, and how the hub adds push without a contract change

Per [ADR-0042](0042-the-interface-adapter-contract.md) §1 the seam is the concrete
`orchestration` façade, which is **not** contract surface — so the names below are
ratified as *shape*, not spelling, in ADR-0073 §7's form.

**Façade:** an enumeration of open questions and a single answering call —
`questions(*, limit, offset) -> tuple[Question, ...]` and
`answer(question_id, *, accept: bool) -> AnswerOutcome` — plus what §9 needs to
keep an interrupted apply from being stranded silently: `interrupted_questions(*,
limit, offset)` relays `DeferralStore.interrupted` (§2) so a restarted process can
reach a stranded question it holds no id for, and `forget_question(question_id)`
relays `DeferralStore.delete` for the user disposing of one. The two enumerations
stay separate all the way to the surface, never merged into one list: an
interrupted question is not answerable, and offering it beside the ones that are
would present a claim that cannot be taken. A state the surface refused to show
would be a question that vanished after all, which is the failure this ADR is
about. There is deliberately **no "retry" verb**: re-opening a claim is what §2
declines, and the recovery a user actually has is §9's two steps — dispose of it,
then read the belief (`assistant beliefs`) and `learn` it again if it is missing.
`Question` is a **frozen
`orchestration` dataclass** beside `Belief`, `Confirmation` and `TurnOutcome`, for
their reason (ADR-0042 §1: it crosses no *subsystem* boundary, only `interfaces`)
and for ADR-0073 §7's deciding reason — **`band_of` is applied here, once, in the
engine**, so no adapter classifies anything.

**What the surface must convey per question**, in ADR-0073 §4's spirit:

- the proposed content and kind, and the band it **would** enter if accepted —
  worded as a conditional, never as a belief held (§1);
- **why it is being asked**: `MemoryDecision.reason`, which is non-optional;
- **what accepting would retire**: the frozen conflict ids resolved to their
  content through the ratified `MemoryStore.get`. Because `get` hides closed
  windows (ADR-0045 §6), a conflict retired since the question was asked does not
  resolve, and renders as *no longer held* rather than being omitted — the user
  should be told that the thing they would be overruling is already gone. This list
  is not decoration: it is the exact scope the answer authorises (§5);
- **when it was asked and when it goes stale**;
- for an `APPLYING` question, **that an answer was begun and its outcome is not
  recorded**, and §9's two steps in order: dispose of it, then check the belief and
  correct again if it is missing. Not "retry" — the system does not know whether
  the write landed, and a verb that implies it does would be the one dishonest line
  on this surface.

**An answer that re-defers says so, and points at the successor.** `AnswerOutcome`
distinguishes *applied*, *rejected*, *stale* and *re-deferred*, and the last
carries the new question's id so the user is handed the next question rather than
being told their answer went nowhere (§5a step 1). Rendering a re-deferral as a
failure would be the same lie in a smaller place.

**CLI (`interfaces/cli.py`, beside `ask`/`resume`/`learn`/`beliefs`):** a listing
command and an answering command taking a question id and an accept/reject choice.
Both obey the existing adapter rules unchanged (ADR-0042 §7): one error boundary
per command, engine-supplied text neutralised on render, the façade closed on exit.

**Answering is binary. There is no third "neither — here's the real answer" verb.**
An amendment is a new proposal, and `learn` already is one (ADR-0073 §6). A free-text
answer would be a second correction path wearing a confirmation's clothes.

**Three reaches, and the minimal set that meets the exit test.**

1. **At the moment of deferral**, `learn` says the question was parked and how to
   answer it, carrying the deferral id. This is the reach that closes issue #423's
   own scenario: the user submits feedback, is told it is deferred, and is pointed
   at the answer. It requires the façade's learn DTO to carry the deferral id —
   an `orchestration` widening, not a contract change (ADR-0042 §1) — and it makes
   `cli.py:96`'s "which cannot be done from here yet" false, which §10 lists as an
   obligation.
2. **On demand**, by the listing command. This is the only reach for a question
   raised by the observer, where no `learn` call was in flight to render anything.
3. **Not injected into `respond`.** A turn answers the user's request; interleaving
   an unrelated interrogation into every turn is the "blanket interrogation"
   ADR-0038 §5 feared, and it would make a turn's content depend on queue depth.
   Declined, with the count-on-every-turn variant declined with it (§11 files it).

**The hub adds push without touching this contract.** What leg 5 needs is a
durable, ordered, bounded enumeration with a resolve-once CAS — which is exactly
§2. A scheduler that polls `pending` and delivers is a *reader*; delivery adds no
field here. Delivery state ("was it sent? seen?") is deliberately **not** on
`DeferredProposal`: it is a transport concern, it differs per spoke, and putting it
on the record would make a memory decision carry a notification's bookkeeping.

### 9. Claim, then apply — and the residue that remains runs one way

Applying an accepted question spans two stores that share no transaction —
ADR-0028 §7 established that "atomicity has to come from the store", and a
cross-store transaction is what ADR-0074 §11 defers to leg 5. So the sequence is
ruled here, and what it does and does not guarantee is stated rather than
discovered.

**The sequence is `claim` → `ingest` → `resolve`.**

1. **`claim`** takes the deferral from `PENDING` to `APPLYING`, atomically within
   the deferral store (§2). Failing it — the deferral is absent, expired, or no
   longer `PENDING` — ends the answer with "that question is not open", and nothing
   is written.
2. **`ingest`** applies the proposal under §5, carrying the `UserConfirmation` the
   claim authorises.
3. **`resolve`** moves `APPLYING` to the terminal state the ingest produced, with
   the id that state carries: `ACCEPTED` with the record written, `STALE` when the
   window had closed before the answer (§6), or `REDEFERRED` when the ingest ruled
   `ASK_USER` again (§5a step 1).

**A re-deferral is a completed answer, not a failed one.** When the re-ingest
surfaces a `USER_ASSERTED` conflict outside the answer's authority, the policy rules
`ASK_USER`, nothing is written, and the coordinator **enqueues the successor first
— the successor carrying `predecessor_id` set to the question being answered, and
`defer(successor, successor_to_claim=<the token `claim` gave it>)`, §2 — and then
resolves the original to `REDEFERRED` naming it**. It already holds that token; the
whole sequence runs inside one claim. That order
matters for the same reason step 2 precedes step 3 everywhere else: a crash after
resolving but before enqueuing would leave a question marked handled with no
successor, which is the silent drop wearing a terminal state. Crashing the other way
leaves the original `APPLYING` and the successor already asked — visible, and
recoverable by §9's two steps. The successor is admitted regardless of the queue cap
(§2), so a full queue cannot strand a claimed answer — and because the store
validates the claim token against a parent that is genuinely `APPLYING` and has no
successor yet, that exemption cannot be reached from anywhere but here.

**The claim is what makes an answer apply at most once.** Without it, two
concurrent answers — two CLI invocations, and routinely two spokes once the hub
lands — both read a `PENDING` deferral, both call `ingest`, and **both write**;
only one then wins the terminal compare-and-set, and the loser is reported as
"already answered" while its memory mutation stands. That is a duplicate correction
with no crash anywhere, produced by ordinary concurrent use. Claiming first turns
it into a lost race that writes nothing, which is the only acceptable direction.
This is why the single-resolution invariant is placed **before** the apply rather
than after it: ADR-0044 §2 puts it on the resolution because a permission
resolution *is* the write, whereas here the write is a separate call and a CAS that
only guards the bookkeeping guards the wrong thing.

**A rejection needs no claim**, because it writes nothing: `resolve` goes straight
from `PENDING` to `REJECTED`, and a concurrent second rejection simply returns
`False`.

**A claim is one-way, and that is what keeps the guarantee true after a crash.** A
process that dies between `claim` and `resolve` leaves the deferral `APPLYING`
forever: `pending` does not return it, `claim` will not re-take it, `purge` will not
sweep it (§2), and there is no `release` that would put it back. Nothing in the
system can apply that question a second time — not a timer, not a sweep, not a
second client, not the same user asking twice.

**The design deliberately trades recovery for the guarantee, and the trade is the
right way round.** A recovery verb — release, lease, timeout, retry — has to be
callable by something that is not the dead claim holder, and anything that can
re-open a *stranded* claim can re-open a **live** one, letting a second apply run
alongside the first. That is the duplicate the claim exists to prevent, restored by
the mechanism meant to repair it. So the answer is applied at most once, full stop,
and the cost is paid where it can be seen.

**What the user is left with is a question in a stated, honest state, and a
two-step recovery.** The listing shows it (§8): an answer was begun and its outcome
was never recorded. The system does **not** know whether the memory write landed —
that is the actual epistemic situation and the surface says so rather than
guessing. The recovery uses only ratified verbs, and it is **two steps, in order**:

1. **Dispose of the stranded question** (`forget_question`, §8 → `delete`, §2).
   This is not optional bookkeeping and the ordering is the whole point: while the
   row lives it holds its `question_key`, so a re-proposal of the same correction
   would collide with it and be handed back an id nothing can claim. Deleting
   destroys the key with the content, which unblocks the key.
2. **Read the belief and correct it if it is missing** — `assistant beliefs`
   (ADR-0073), then `learn`, the correction path ADR-0073 §6 says is the only one.
   A re-proposal now admits a fresh question, or lands directly if the conflict it
   would have contradicted is already retired.

The surface states both steps on the stranded question itself, because a recovery
the user has to infer from a Protocol's dedup rule is not a recovery.

**A `resolve` that finds nothing is reported, not raised — and what it reports
comes from the ingest, not from the failure.** If the question was deleted while
its answer was being applied, `resolve` returns `False`. The coordinator still
holds the `MemoryIngestResult`, and **that** is what it reports: the record written
and its id, or that the answer was re-deferred, or that nothing was written. The
`False` adds one clause — "the question is gone" — and nothing else. Reading a
committed write out of a failed bookkeeping call would be the ADR's own honesty
rule broken at the last step: a re-deferred answer writes nothing (§5a step 1), so
"the change was made" would be false for exactly the case that most needs the
truth.

**The residue, precisely, and it is a bookkeeping loss rather than a data one.**
After a crash inside a claim, one question's outcome is unrecorded until the user
disposes of it. Nothing is destroyed, no answer is applied twice, and no memory
write is orphaned — the write either committed or did not, and either way the
store's own contents are consistent and readable. The direction is
*unrecorded-and-visible*, never lost-and-silent, which is the one-way-residue
standard ADR-0074 §9 holds its composed export to.

Closing even that needs the cross-store transaction leg 5 owes (ADR-0074 §11), at
which point claim and apply commit together and the state cannot exist. Filed
(§11), not attempted.

### 10. What ratification edits, and what the implementing lane owes

Recorded in the form ADR-0028 §6 applied — a qualified `Status` line plus a dated
header note, with no ratified text rewritten (ADR-0001's append-only rule). This
ADR merges as `Proposed`, so **the edits are not made by this change** (ADR-0019).
On ratification:

- **ADR-0045** — `Status` qualified with "§5 clause 1 amended by ADR-0078"; a dated
  note recording that clause 1's refusal of a fold onto a `USER_ASSERTED` target
  stands verbatim **except** for a `SUPERSEDE` whose target is named in the
  incoming proposal's `confirmation.retires`, which is the "explicit user
  confirmation" gate §7 itself named. Clause 2 and everything else stand.
- **ADR-0050** — `Status` qualified with "§1's `USER_ASSERTED` hold-out amended by
  ADR-0078"; a dated note recording the same exception for the retirement set, and
  that §2's "held pending the user's answer, not dropped" now has a mechanism
  behind it. §1's `EXTERNAL` hold-out, its `conflict_limit` bound and its filed
  residual (#313) are untouched.
- **ADR-0028** — `Status` qualified with "§8 amended by ADR-0078"; a dated note
  recording the two conformance clauses §4 and §5 add. §8's other exclusions stand.

**The implementing lane owes**, beyond §2's triad:

1. The two `core` field additions (§2), both defaulted, and the conformance clauses
   they imply (§4, §5).
2. `DefaultMemoryPolicy`'s confirmation rule and the `_refuse_unsafe_fold`
   narrowing (§5). The refusal helper's signature widens to see the proposal's
   confirmation, not only the incoming record (`ingest.py:111-113`).
3. The write-stage enqueue and the answer path, in `orchestration`, with §3's two
   composition-root obligations enforced by a test rather than requested in prose —
   the standard ADR-0028 §4 set when it made
   `test_a_learned_preference_is_reused_on_a_later_turn` carry its same-store rule.
   **Seven integration assertions come with the answer path**, all on injected
   clocks and deterministic suspension rather than timing. The first is the one the
   rest depend on and the one no store or writer test can reach: **a `learn` whose
   proposal conflicts with a prior user assertion produces a question that shows
   that assertion, and answering it accept lands the correction — in one round, with
   no re-deferral.** That is the whole feature, end to end, and it is the assertion
   that fails when the write stage enqueues the caller's proposal instead of a
   snapshot carrying `result.conflicts` (§3). Then: two concurrent
   `answer(id, accept=True)` calls leave **one** correction in the store and report
   the loser as not-open (§9); an accept suspended inside `ingest` while a `purge`
   runs still finds its row and resolves against it (§2's `APPLYING` exclusion); an
   accept suspended inside `ingest` while `forget_question` deletes the same
   deferral commits its memory write, reports the disposal, and **does not raise**
   (§2, §9);
   §9's two-step recovery end to end — crash after `claim`, `delete`, then a
   re-`learn` that **admits a new question** rather than colliding with the
   stranded key; an accept whose proposal's validity window has closed before
   the answer writes nothing and stamps `STALE` (§6); and a `learn` against a
   **full queue**, asserting the user is told the queue is full rather than getting
   silence — the `refused` branch of §7, which is the one an implementation is most
   likely to leave as a no-op because nothing raises. None belongs in the store's
   conformance suite — they are properties of the sequence, and the sequence lives
   here.

   **Two more cover the re-deferral path** (§5a step 1, §9), which is the one with
   no legal transition before this revision: an accept whose re-ingest meets a
   newly-appeared unshown `USER_ASSERTED` conflict **writes nothing**, enqueues a
   successor, and resolves the original `REDEFERRED` naming it; and **the same case
   with the answerable queue already full** still admits the successor and still
   resolves, because a re-deferral does not consult the cap (§2). The second is
   the assertion that would have caught the stranded-claim hole, so it is named
   rather than left to be inferred from the first.

   **And two more.** One for the outcome mapping's totality: an accept driven
   through a `MemoryWriter` whose injected policy rules `REJECT` resolves the claim
   to `REJECTED` rather than leaving it `APPLYING` (§2) — a conforming policy that
   is not `DefaultMemoryPolicy` is the only thing that reaches it, which is exactly
   why it needs a test rather than an argument. One for §7's reversal path, end to
   end and under `deferral_ttl=None`: reject a question, `learn` the identical
   correction, assert the user is **told which prior question stands in the way**,
   forget it, `learn` again, and assert a fresh question is admitted. That is the
   claim an earlier revision made and could not keep, so it is pinned rather than
   described.
4. A production `DeferralStore` alongside the existing SQLite stores, under the
   same `data_dir` plumbing and file permissions (ADR-0004), wired in the
   composition root and joined to the façade's ordered shutdown (ADR-0042 §2).
5. `deferral_ttl` and the queue cap in `core.config.Settings` (§6, §7), the cap
   `gt=0` and both refused at load, with load-time tests for zero and negative
   values as `confirmation_ttl` already has. **`deferral_ttl` is read exactly once
   per question, at admission**, and stamped onto the record as `retention` and
   `expires_at` (§2); no later operation consults the setting.
6. The façade methods, the `Question` DTO and the CLI commands (§8), including the
   separate interrupted enumeration, the `APPLYING` rendering and the disposal
   verb (§9), the re-deferred `AnswerOutcome` that hands the user the successor
   question, and no verb that claims to retry an apply. **A restart test**: the
   stranded question is reachable through `interrupted_questions` in a process that
   never held its id.
7. A home for `purge`. It does not get a new one: the roadmap's leg 5 already names
   the hub's internal scheduler as "the home for `purge_expired` (ADR-0007),
   confirmation deadlines (ADR-0059)…", so this store's purge is wired wherever
   `purge_expired` is wired and inherits the same fate. Inventing a second sweeping
   mechanism for one store would be the thing that has to be undone at leg 5.
8. **The `learn` rendering, which this decision makes false.**
   `interfaces/cli.py:96` says the deferral "cannot be done from here yet" and the
   comment above it (`cli.py:91-95`) states no flow exists. Both must change in the
   same lane, and the test asserting the current wording
   (`tests/interfaces/test_cli.py:596`,
   `test_render_learn_marks_a_deferred_ruling_as_not_stored`) inverts with them.
   Leaving an honest
   message that has become a lie is the specific failure ADR-0019 is about.

### 11. What this ADR does not decide

- **A real contradiction signal.** Still ADR-0045 §7's and ADR-0050 §3's open
  deferral. This ADR builds the *other* gate §7 named; it does not narrow the
  question that triggers one. If a signal lands, fewer questions are asked and
  nothing here changes. Owner: the policy lane.
- **A validity check at the memory write boundary** (§6). Not deferred here —
  **answered "no" by ADR-0080 §5**, which this ADR relies on rather than reopens.
  The residue it leaves (a window closing *during* an apply lands a record every
  later read hides) is the memory model's ordinary read-time-relative behaviour,
  and the absolute-hide half is issue **#460**, a `MemoryStore` lane (ADR-0080 §9).
- **How the hub delivers a question** — push, notification, per-spoke delivery
  state (§8). Owner: leg 5's local-API and service ADRs.
- **What the observer proposes and at what rate** (§7). Decided by ADR-0077, now
  merged. This ADR fixes only the queue's behaviour under the load that produces,
  and it deliberately does not reach back across the seam: a proposal whose
  `confidence` jitters between re-observations of one thing keys as a new question
  each time (§7), and stabilising that is the producer's job, not the queue's.
- **The over-limit surplus (#313) and the universal-`MemoryWriter` promotion of
  full-set retirement (#314).** Decided, and merged, by ADR-0079 §§1 and 3. This
  ADR inherits both by re-ingesting (§5, ADR-0079 §2) and re-decides neither.
- **Cross-store atomicity between the deferral store and `MemoryStore`** (§9).
  Owner: leg 5, with ADR-0074 §11's cross-store transaction.
- **Reconciling `SemanticMemory.valid_until` with the envelope window** (§6). Still
  ADR-0045 §10's item; untouched.
- **Whether `DefaultMemoryPolicy` adopts `EXTERNAL` supersession.** Untouched;
  still ADR-0045 §5/§7's deferred choice.
- **Surfacing a pending-question count on every turn** (§8). Declined for now
  rather than refused; revisit when the hub can push, at which point the question
  is what a spoke shows, not what `respond` returns. Filed.
- **Unifying this surface with `assistant resume`.** Different records, different
  machinery, different authority (issue #423's own observation). A single
  "things awaiting you" view is a UX question for the hub's client, not a contract
  question. Filed.
- **Rendering *why* a derived proposal was made** — resolving `Provenance.evidence`
  into readable text. That is ADR-0073 §10's open half of #431, and it gates the
  observer's first shipping producer, not this queue.

## Consequences

**Easier.**

- **A deferred question reaches the user instead of vanishing** — leg 4's exit
  test, as a mechanism rather than a claim. Every one of the five ADR-0005 §3
  outcomes now has an effect, which is the same completeness ADR-0028 gave `MERGE`.
- **ADR-0050 §2 becomes true.** "The incoming one is held pending the user's
  answer, not dropped" describes the system after this lands; today it describes
  nothing.
- **The confirmation gate ADR-0045 §7 named exists.** Two ADRs deferred
  assertion-versus-assertion resolution to it and neither could build it, because
  there was nowhere for the question to wait.
- **The queue is honest at volume before the observer runs at volume**, which is
  the ordering roadmap leg 4 asks for: dedup, a finite lifetime, a refusing cap,
  and an oldest-first order that makes all three legible.
- **The hub inherits a surface it can push from** without a contract change (§8).

**Harder.**

- **New `core` contract surface, and a new store**, which is the cost this ADR
  argues for in §1 rather than assumes: one Protocol, five `core/types.py`
  additions (the record, its state enum, and the three values `UserConfirmation`,
  `DeferralClaim` and `DeferralAdmission`), two added fields on existing types, one
  error class, and a
  triad with two bindings.
- **A fourth store in the composition root**, with its own file, its own
  retention, its own export and delete obligations under ADR-0004/ADR-0007, and its
  own place in the ordered shutdown.
- **Two ratified refusals gain an exception each** (§5). Every exception to a
  fail-closed rule is a place a future change can widen carelessly, which is why
  the exception is keyed on an explicit value carried on the proposal rather than
  on an inferred condition, and why the conformance suite pins both halves.
- **The accept path is three calls across two stores** (§9). Concurrency is closed
  by the one-way claim, and the price is a state with no repair: a crash inside a
  claim strands the question, the surface must render "an answer was begun and its
  outcome is not recorded", and the user's recovery is to look and correct again.
  Closing that needs leg 5's cross-store transaction.
- **`purge` cannot promise a horizon for one state** (§1, §2). An interrupted claim
  outlives its lifetime until someone deletes it, because sweeping it can orphan a
  committed write.
- **A queue can be full**, which is a state the user must be told about and a
  producer must handle. A refusing cap is a worse experience than an infinite queue
  right up until the infinite queue arrives.

**Revisit when** a real contradiction signal lands (fewer questions are asked, and
§5's gate could tighten), when the hub can push (§8's reach 3 and the on-turn count
become spoke questions), when a cross-store transaction exists (§9 closes), or when
a second question producer outside `memory` wants the same queue — the first real
test of whether `DeferralStore` encodes a contract or one policy's outcome.

## Alternatives considered

- **Store the pending proposal in the `MemoryStore` with a closed or future
  validity window.** Rejected (§1): it contradicts the ratified obligation that
  `ASK_USER` writes nothing (ADR-0028 §8), it would surface an unconfirmed proposal
  in the user's `export` (ADR-0045 §6), it carries none of the question, and it
  mixes beliefs with non-beliefs in the one store ADR-0072/ADR-0073 made legible.
- **Reuse the `AuditTrail`, as the permission side does.** Rejected (§1): its
  record is a `PermissionDecision` keyed by an execution/step binding a memory
  deferral does not have. The permission side needed no new store because the
  record already existed for another reason; here nothing was written at all, which
  is the definition of the ruling.
- **Let `MemoryWriter.ingest` queue the proposal.** Rejected, and it was rejected
  before this ADR: ADR-0028's Consequences state that deferral "would need a result
  type that can say 'not yet' and this one cannot". Growing the result type to say
  it would make every writer a queue and put the answer path inside `memory`, where
  it cannot reach the user.
- **Grow `MemoryDecisionKind` with a sixth "deferred-and-parked" member.**
  Rejected: `ASK_USER` already means what it means (ADR-0005 §3); the missing thing
  was never the ruling's vocabulary but a place for the proposal to wait. A new
  member would break every exhaustive match in the codebase to express nothing new.
- **Encode the confirmation as `confirmed_retirements: tuple[str, ...] | None` and
  skip the `UserConfirmation` value.** Rejected (§5): `()` (confirmed, retires
  nothing — the secret-tier case) and `None` (not confirmed) differ only by
  identity, and one truthiness check turns a confirmed secret-tier answer back into
  an infinite re-deferral — the same class of misread `MemoryWrite` is frozen to
  prevent (`types.py:592-599`).
- **Carry `confirmation` as trusted metadata and check nothing at the writer.**
  Rejected (§5): it was this ADR's own earlier draft, and it misread what
  `_refuse_unsafe_fold` is for. The floor exists because "any conforming
  implementation may rule differently" (`ingest.py:135-139`); a gate that opens on
  an unexamined field returns that guarantee to the caller's good intentions. The
  four checks §5 requires are what a boundary can actually verify, and §5 is
  explicit about what remains beyond them.
- **Let the answer retire every asserted conflict live at answer time, not only the
  ones shown.** Rejected (§5): the user answered about the records they saw.
  Extending that answer to records they did not see is forging consent, and it
  would re-open on the confirmation path precisely the destruction ADR-0045 §5's
  clause 1 exists to prevent.
- **Evict the oldest question when the queue is full.** Rejected (§7): it performs
  the silent vanishing this ADR exists to end, inside the mechanism meant to
  prevent it. Refusing the newest is recoverable — its producer still holds it —
  while an evicted question has no producer left to notice.
- **Refresh a duplicate question's deadline on re-proposal.** Rejected (§7): a
  producer that re-proposes on a schedule would keep a question alive forever,
  which is a lifetime in name only.
- **Re-ask a rejected question when the producer proposes it again.** Rejected
  (§7): the question reached the user and was answered. A change of mind is
  reachable immediately through `learn`, which is the ratified correction path
  (ADR-0073 §6).
- **Resolve the deferral terminally first, then apply.** Rejected (§9): a crash
  between them leaves the question `ACCEPTED` and nothing written — the silent drop,
  with a receipt saying it was handled. The claim gets the concurrency guarantee a
  terminal-first order would have given without inheriting its failure direction:
  an interrupted claim is visible and re-openable, an interrupted lie is not.
- **Apply first and rely on the terminal compare-and-set alone.** Rejected (§9):
  this was the earlier draft, and it is wrong for a reason that has nothing to do
  with crashes. Two ordinary concurrent answers both pass the read, both write, and
  only the bookkeeping is serialised — a duplicate correction produced by normal
  use, which no residue paragraph about process death would have covered.
- **Any way to re-open a claim — `release`, a retry verb, a lease, a timeout.**
  Rejected (§2, §9), and this is the sharpest trade in the ADR. Every one of them
  must be callable by something that is not the dead claim holder, and anything
  that can re-open a stranded claim can re-open a **live** one: a second client
  applies the same answer while the first apply is still in flight, and the claim's
  entire guarantee evaporates through the door meant for recovery. Binding release
  to a claim token does not help, because the token of a crashed claim is exactly
  what nobody holds. So a claim is one-way, the interrupted state is shown rather
  than repaired, and the user's recovery is `learn` — which is the ratified
  correction path anyway (ADR-0073 §6).
- **Refuse `delete` on an `APPLYING` row, to protect the in-flight apply.**
  Rejected (§2): it makes ADR-0007's data right conditional on an internal state the
  system assigned, which is ADR-0073 §9's objection to a band-conditional delete
  with a different label. And it would be permanent for a *stranded* claim, so a
  user could never destroy an interrupted secret-tier question. The consequence a
  refusal was protecting against — `resolve` finding nothing — is reported rather
  than prevented (§9).
- **Give a deleted `APPLYING` row a content-free tombstone so the late `resolve`
  lands.** Rejected: `DeferredProposal` would need every field optional to express
  a row with no proposal and no ruling, and the tombstone would record an outcome
  for a question the user destroyed — keeping a trace of exactly what they asked to
  be rid of. ADR-0074 §8's tombstone earns its keep because a conversation's index
  must catch a late write to *other* durable state; here the late write commits on
  its own and is visible in `assistant beliefs`, so there is nothing to catch.
- **Purge a long-abandoned `APPLYING` row along with the lapsed `PENDING` ones.**
  Rejected (§2): the row is the only durable trace that an answer was begun, and a
  sweep that removes it while its `ingest` is still running — a slow embed is
  enough — lets the memory write commit against a question that no longer exists.
  A committed change with nowhere to record it is worse than a stale row, so the
  exposure cap §1 promises is narrowed for that one state and the narrowing is
  stated rather than quietly broken.
- **Surface pending questions inside `assistant beliefs`.** Rejected (§1, §8):
  ADR-0073 §3 is that inspection reads live beliefs only, and a question is not a
  belief of any band. Listing one there would claim the system holds something it
  explicitly declined to hold.
