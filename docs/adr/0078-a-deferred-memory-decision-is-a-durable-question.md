# 78. A deferred memory decision is a durable question the user answers

- Status: Proposed
- Date: 2026-07-28
- **This is a contract change, and it is flagged as such (golden rule 5).** New
  `core` surface: a `DeferralStore` Protocol, a `DeferredProposal` record with its
  state enum, a `UserConfirmation` value, one field added to `MemoryUpdateProposal`,
  one added to `MemoryIngestResult`, and a `DeferralStoreError`. It ships **no
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
- **In-flight siblings, referenced but not designed here.** ADR-0077 (the observer)
  names this ADR as the resolution mechanism for the proposals it mass-produces;
  it owes this decision nothing but "a proposal that can wait", and §3 states the
  one obligation it inherits. ADR-0079 (the contradiction surplus, #313/#314) is
  adjacent law on a disjoint question. Neither is a dependency of this one.

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
accepting the proposal would have given. Deferral content is never logged; a log
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
  asked"); `deferred_at`; `expires_at` — the answerability deadline, **stamped onto
  the record at deferral** from the lifetime in force, following ADR-0059 §1's
  ruling that a confirmation's lifetime is fixed on the record rather than
  recomputed from a live setting; `question_key`, the dedup key (§7); `state`; and,
  once claimed, `answered_at` and `outcome_record_id` (the id the accepted apply
  left live, or `None`).
- **`DeferralState`** — a `StrEnum`: `PENDING`, `APPLYING`, `ACCEPTED`, `REJECTED`,
  `STALE`. There is **no `EXPIRED` member**: expiry is read-time-relative and never
  stamped, exactly as `MemoryRecord.expires_at` is (ADR-0007 §3, ADR-0045 §6), so
  no sweep is needed to make a question stop being answerable. `STALE` *is* stored,
  because it records that an answer arrived and was refused — §6 says why the two
  are different facts.
- **`UserConfirmation`** — a frozen value carrying `deferral_id`, `confirmed_at`,
  and `retires: tuple[str, ...]`, the record ids the answer authorises retiring
  (§5). It is a value rather than a naked field because it is *authority*, and
  authority that can be inspected is authority that can be bounded.

**`core/types.py` also gains two fields on existing types**, both defaulted so the
change is additive and no existing producer moves:

- `MemoryUpdateProposal.confirmation: UserConfirmation | None = None` (beside
  `conflicts`, `types.py:642-645`).
- `MemoryIngestResult.conflicts: tuple[str, ...] = ()` (`types.py:725`) — §4.

**`core/protocols.py` gains one Protocol, `DeferralStore`**, `@runtime_checkable`
like every other, owing:

- **`defer(deferred) -> str | None`** — admit a question. **Key-idempotent**: if a
  deferral **the key still speaks for** carries the same `question_key`, that
  deferral's id is returned and nothing is inserted — the reconciliation ADR-0052
  §2 ratified for parked confirmations ("a binding already named by an entry reuses
  that entry's handle instead of minting a second"). A key "still speaks for" a
  deferral that is answerable (`PENDING`, not past `expires_at`), being applied
  (`APPLYING`), or `REJECTED` within its retention (§7's no-nagging rule). A key
  whose only match is *expired-and-unanswered*, `ACCEPTED` or `STALE` does **not**
  collide: the question lapsed or was settled, and a fresh proposal deserves a fresh
  question. It returns **`None` in exactly one case** — the answerable queue is at
  its cap and the question was not admitted (§7). One nullable return, one meaning;
  the duplicate path never yields `None`.
- **`get(deferral_id) -> DeferredProposal | None`.**
- **`claim(deferral_id) -> DeferredProposal | None`** — a compare-and-set from
  `PENDING` to `APPLYING`, atomic with its own read, refusing a deferral past
  `expires_at`. Returns the claimed record, or `None` when the deferral is absent,
  expired, or not `PENDING`. **Nothing may apply an answer without holding a
  claim** (§5, §9): this is what makes an answer apply at most once under
  concurrency, and it is the ADR-0044 §2 "a binding resolves once" invariant moved
  one step earlier so that it covers the *apply*, not only the bookkeeping.
- **`release(deferral_id) -> bool`** — the inverse compare-and-set, `APPLYING` back
  to `PENDING`, for an apply that is known not to have landed (§9). Explicit and
  user-driven; there is deliberately **no timeout that releases a claim on its own**
  — that is the lease ADR-0074 §9 declines, and a lease here would re-apply an
  answer nobody re-gave.
- **`pending(*, limit=50, offset=0) -> list[DeferredProposal]`** — the answerable
  questions: `state is PENDING` **and** not past `expires_at`, judged against the
  store's own clock reading, read-time-relatively as every `MemoryStore` read is
  (ADR-0045 §6). Bounded by default for the reason ADR-0073 §2's
  bounded-default guarantee exists, as ADR-0073 §8 states it: it "keeps an unbounded
  read of a Tier 1 store from being what a caller gets by saying nothing".
  **One page is judged against one clock reading** — the clause
  ADR-0073 §8 makes explicit for `list_beliefs`, and it matters here for the same
  reason: a row dropped mid-scan shifts every subsequent offset. Total order: by
  `deferred_at` **ascending**, `id` ascending as tie-break (§7 argues the
  direction).
- **`resolve(deferral_id, *, state, answered_at, record_id) -> bool`** — the
  terminal compare-and-set, atomic with its own read. It succeeds from `APPLYING`
  to `ACCEPTED`/`STALE` (the apply happened, or was refused as stale), and from
  `PENDING` to `REJECTED` (a rejection writes nothing, so it needs no claim).
  Returns `False` from any other state, including a second attempt. It must be
  atomic within the store for the reason ADR-0074 §9 gives for its conditional drop:
  "a drop that merely trusted its caller's earlier reading would be the race
  reintroduced one layer up."
- **`delete(deferral_id) -> bool`** and **`clear() -> int`** — ADR-0007's data
  rights, shaped as `MemoryStore.delete`/`clear` (`protocols.py:442`, `:453`).
- **`export() -> list[DeferredProposal]`** — ADR-0004 §6. A plain list of the frozen
  type the caller serialises with `model_dump(mode="json")`, matching
  `MemoryStore.export` (`protocols.py:461`) and `AuditTrail.export`
  (`protocols.py:1278`) rather than minting a bespoke export type: this store has
  one collection, so `PlanExport`/`ConversationExport`'s reason for existing does
  not apply.
- **`purge() -> int`** — shaped as `MemoryStore.purge_expired`
  (`protocols.py:474`), and it must cover **both** kinds of finished row, because
  covering only one is how sensitive content outlives its promised horizon: a
  deferral whose terminal state is older than the configured lifetime, **and** a
  deferral still `PENDING` or `APPLYING` whose `expires_at` is older than that same
  lifetime. The second is the one a purge naturally omits — an unanswered question
  never transitions, so a purge keyed on terminal states alone would keep an
  unanswered secret-tier proposal on disk forever while §1 and §6 promise the
  opposite. Correctness does not depend on `purge` running (expiry is read-time
  relative), but §1's Tier-0 exposure cap does.

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

**Four clauses the suite must carry are named here**, because they are the ones a
suite of small explicit cases naturally omits and each is a claim this ADR makes
that would otherwise be prose:

1. **`claim` admits exactly one of two concurrent callers.** Two `claim`s on one
   `PENDING` deferral yield one record and one `None`, driven through the
   store-suspension hook the other contracts already use for their compare-and-set
   clauses rather than by hoping a sequential test observes a race. This is §9's
   whole guarantee; asserting only that a single `claim` succeeds tests nothing
   about it.
2. **`resolve` refuses every state but the one it names** — including a second
   attempt, and including `PENDING` for `ACCEPTED` (an accept that skipped its
   claim must not commit bookkeeping for an apply nothing authorised).
3. **`purge` removes an expired-and-unanswered deferral**, seeded through an
   injected clock, and not merely a `REJECTED` one. §6's Tier-0 exposure cap is
   exactly this clause; without it an implementation that purges terminal rows only
   passes everything else on this list while keeping secret-tier content forever.
4. **`defer` collides on the key and only on the key.** Two proposals differing
   *only* in `provenance.source`, and two differing only in `sensitivity`, must both
   admit as separate questions (§7), while an identical repeat collides and does not
   refresh the deadline. A suite that varies only `content` certifies a weaker key
   than the one ratified.

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

**It is a property of the write stage, not of `learn`.** `LearningLoop.learn` is
today's only path to `ingest`, but the observer (ADR-0077) is a second producer.
The obligation ADR-0077's lane inherits is exactly one sentence: **a proposal
reaches memory through the orchestration write stage, not through a `MemoryWriter`
handle of its own.** A producer holding the writer directly gets the ratified
policy and applier and silently loses the queue — the drop this ADR ends, restored
by a wiring choice.

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
  question at all.
- **The write is atomic**, by ADR-0046's `write_atomic` (`protocols.py:283`) with
  `INSERT_IF_ABSENT` for the correction (`types.py:574-581`), as ADR-0045 §8 ruled
  and ADR-0050 §1 applies to a multi-target retirement.

**Two narrowings are needed, and each is the discharge of a stated deferral rather
than a new liberty.**

**(a) `DefaultMemoryPolicy` gains one rule, ahead of every existing rule.** A
proposal carrying a `confirmation` is not deferred again: it rules `SUPERSEDE` on
the first id in `confirmation.retires` that is present in the live conflict set,
and `ACCEPT` when none is. Without it the secret-tier arm (`policy.py:155-159`)
and the assertion arm (`policy.py:73`) would re-defer the answer to the question
they just asked, forever — the loop is the reason the rule must come first rather
than last.

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
retired. Everything else in §1 stands, including the `EXTERNAL` hold-out and the
`conflict_limit` bound.

**The authority is bounded by what was shown, and this is the load-bearing
clause.** `retires` is a **ceiling, not an instruction**:

- A conflict the user was shown that has since been retired or deleted simply is
  not in the live set; the apply proceeds without it. Authorising a retirement that
  is already moot costs nothing.
- A conflict the user was **never shown** — one that appeared between the question
  and the answer — is not covered by the ceiling. The policy therefore defers
  again, minting a fresh question over the new set. That is correct rather than
  annoying: the user answered about the records they saw, and a system that
  extended their answer to a record they did not see would be forging consent.
  §7's dedup does not suppress it, because a different conflict set is a different
  `question_key`.
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
guarantee back. So the exception carries three checks of its own, all of them
performable at the boundary with what the writer already holds:

1. The ruling is `SUPERSEDE`. A `REINFORCE` onto an assertion stays refused under
   clause 1 whatever the confirmation says — folding at the target's id would
   rewrite the user's own words, which no answer authorises.
2. The target id is in `confirmation.retires`.
3. **The target id is also among the conflicts this very ingest resolved** (§4).
   This is the check that makes the value more than a password: a confirmation
   cannot authorise retiring a record the current ruling was not even made against,
   so an answer cannot be replayed onto a different proposal or a different topic.

**What no in-process value can do, stated plainly rather than implied.** None of
this makes the confirmation unforgeable, and this ADR does not claim it does. Any
subsystem holding the injected `MemoryStore` can already call `write_atomic`
(`protocols.py:283`) and close any window it likes; a floor on the writer is not a
security boundary against arbitrary in-process code and never was. What it *is* —
and what the three checks above restore — is a guarantee that **no ruling reaches a
user assertion by inference**: not from a policy's judgement, not from topical
similarity, not from a confirmation that belongs to another question. The remaining
step, that a claimed confirmation corresponds to a deferral a user actually
answered, is enforced one layer up by §9's claim: the answer path is the only
producer of a `UserConfirmation`, and it cannot run without having taken the
deferral from `PENDING` to `APPLYING` first. That is the "coordinator-owned
operation that binds the accepted answer to the stored deferral" this arrangement
rests on, and it is a mechanism rather than a convention.

**ADR-0028 §8's conformance suite gains its second clause**, in three parts: a
`SUPERSEDE` naming a `USER_ASSERTED` target **raises** without a covering
`confirmation`, **raises** with a confirmation whose `retires` does not name that
target *or* whose named target is absent from the resolved conflicts, and
**applies** only when all three checks hold. A suite asserting only the refusal
certifies the gate as shut; one asserting only the pass certifies nothing about the
floor; one omitting the mismatch cases certifies a password rather than a bound
authority.

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

### 7. Volume: dedup by question, a cap that refuses rather than evicts, oldest first

The observer will produce proposals continuously and some fraction will be ruled
`ASK_USER`. Three rules keep the queue dignified at that rate. None of them designs
the observer.

**Dedup on a `question_key`.** Proposal ids are minted per proposal, so id equality
is useless. The key is derived deterministically from every input that makes two
questions *materially* the same one: **the proposed record's `kind`, its canonical
`content`, its `provenance.source`, the proposal's `sensitivity`, and the frozen
conflict-id set.**

Source and sensitivity are on that list for a reason worth stating, because a key
over content and conflicts alone looks sufficient and is not. An `OBSERVED`
proposal and a later `USER_ASSERTED` proposal can carry identical content against
identical conflicts and are **not** the same question: the first asks "shall I keep
what I worked out?", the second is the user telling us directly. Collapsing them
would show the user the observation, and accepting it would store an `OBSERVED`
record at `confidence < 1.0` (ADR-0072 §3) while the assertion the user actually
made was silently discarded — the exact drop this ADR exists to end, reintroduced
by the mechanism meant to keep the queue tidy. Sensitivity rides along for the same
reason at a smaller scale: a `SECRET` and a `PERSONAL` proposal ask different
questions of the user even when the words match. A different conflict set is
likewise a different question, and §5's bounded authority depends on it.

`defer` is idempotent on the key (§2): a second arrival returns the existing
deferral's id and **does not refresh its deadline**. Refreshing would let a chatty
producer keep a question alive indefinitely by re-proposing, which is the opposite
of a lifetime.

**A rejected key is not re-asked while it is retained.** A producer re-proposing
something the user declined gets no new question. This is the one place this ADR
deliberately does *not* surface something, and the distinction matters: the
question **reached the user and was answered**. Asking again is not honesty, it is
nagging. The window is bounded — it is §6's retention, one lifetime — so a genuine
change of mind is reachable by waiting, and an immediate one is reachable by
`learn`, which proposes afresh and is the ratified correction path (ADR-0073 §6:
"inspection adds no second correction path"; nor does this).

**A cap that refuses new questions and keeps old ones.** The **answerable** queue —
`PENDING` and not past `expires_at`, the same set `pending` returns — is bounded by
a configured maximum. Lapsed and resolved rows awaiting `purge` do not count
against it, so a queue cannot be held shut by questions nobody can answer. At the
cap `defer` returns `None` and the proposal is not
enqueued; the refusal is **reported, not swallowed** — it reaches the caller, so
`learn` renders it and the surface can say the queue is full. Eviction is rejected:
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
`answer(question_id, *, accept: bool) -> AnswerOutcome` — plus the two §9 needs to
keep an interrupted apply from being stranded silently: the enumeration also
surfaces deferrals left `APPLYING`, in their own state and never mixed in with the
answerable ones, and a `retry(question_id)` relays `DeferralStore.release`. A state
the surface refused to show would be a question that vanished after all, which is
the failure this ADR is about. `Question` is a **frozen
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
- for an `APPLYING` question, **that an answer was begun and not finished**, with
  the warning §9 requires: retrying may write a second correction if the first
  landed.

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
3. **`resolve`** moves `APPLYING` to `ACCEPTED` (or `STALE`, §6) with the resulting
   record id.

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

**The residue that remains is a crash inside the claim, and it is visible.** A
process that dies between `claim` and `resolve` leaves the deferral `APPLYING`,
which `pending` does not return and `claim` will not re-take. Two things follow,
and neither is silent:

- The question is **not** presented as answerable, so nothing re-applies it — there
  is no background retry and no timeout that releases a claim on its own (§2
  declines the lease ADR-0074 §9 declines).
- It is **shown**, in its own state, by the listing surface (§8). The system says it
  began applying an answer and did not finish, which is the truth. The user may
  `release` it back to `PENDING` and answer again, or `delete` it.

**Only that explicit release can produce a duplicate**, and the ADR is honest that
it can: if the crash happened *after* the `ingest` landed, a release-and-re-answer
sees the retired target already gone from the live conflict set, rules `ACCEPT`
under §5(a), and writes a second correction. Three things bound it, and they are
why it is filed rather than solved here:

- It takes a crash **and** an explicit human release **and** a second human answer,
  against a question the surface has already flagged as ambiguous.
- Nothing is destroyed and no answer is lost. The direction is
  duplicate-and-visible, never lost-and-silent — the one-way-residue standard
  ADR-0074 §9 holds its composed export to.
- The duplicate **self-heals into visibility**: two live contradictory assertions
  are exactly what `_rule_on_assertion` (`policy.py:36`) defers on, so the next
  proposal on the topic raises a question rather than compounding quietly.

Closing even that needs a cross-store transaction (leg 5) or a predetermined
correction id, which would move id-minting out of the applier and break ADR-0045
§4's fresh-id obligation. Filed (§11), not attempted.

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
   **Two integration assertions come with the answer path**, both on injected
   clocks and deterministic suspension rather than timing: two concurrent
   `answer(id, accept=True)` calls leave **one** correction in the store and report
   the loser as not-open (§9); and an accept whose proposal's validity window has
   closed writes nothing and stamps `STALE` (§6). Neither belongs in the store's
   conformance suite — they are properties of the sequence, and the sequence lives
   here.
4. A production `DeferralStore` alongside the existing SQLite stores, under the
   same `data_dir` plumbing and file permissions (ADR-0004), wired in the
   composition root and joined to the façade's ordered shutdown (ADR-0042 §2).
5. `deferral_ttl` and the queue cap in `core.config.Settings` (§6, §7).
6. The façade methods, the `Question` DTO and the CLI commands (§8), including the
   `APPLYING` rendering and its retry warning.
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
- **How the hub delivers a question** — push, notification, per-spoke delivery
  state (§8). Owner: leg 5's local-API and service ADRs.
- **What the observer proposes and at what rate** (§7). Owner: ADR-0077. This ADR
  fixes only the queue's behaviour under load.
- **The over-`conflict_limit` surplus (#313) and the universal-`MemoryWriter`
  promotion of full-set retirement (#314).** Adjacent law, disjoint decision.
  Owner: ADR-0079.
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
  argues for in §1 rather than assumes. Four `core` types (one Protocol, one
  record, one state enum, one value), two added fields, one error class, and a
  triad with two bindings.
- **A fourth store in the composition root**, with its own file, its own
  retention, its own export and delete obligations under ADR-0004/ADR-0007, and its
  own place in the ordered shutdown.
- **Two ratified refusals gain an exception each** (§5). Every exception to a
  fail-closed rule is a place a future change can widen carelessly, which is why
  the exception is keyed on an explicit value carried on the proposal rather than
  on an inferred condition, and why the conformance suite pins both halves.
- **The accept path is three calls across two stores** (§9). Concurrency is closed
  by the claim, but a crash inside it still leaves an `APPLYING` deferral the user
  has to dispose of, and the surface has to render a state that means "I do not know
  whether this landed". Closing that needs leg 5's cross-store transaction.
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
  three checks §5 requires are what a boundary can actually verify, and §5 is
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
- **Release a stale `APPLYING` claim on a timeout.** Rejected (§2, §9): a lease is
  what ADR-0074 §9 declines for conversations, and here it is worse — expiring a
  claim would re-present a question whose answer may already have landed, so a
  timer would manufacture the duplicate that an explicit, warned `retry` at least
  makes the user's informed choice.
- **Surface pending questions inside `assistant beliefs`.** Rejected (§1, §8):
  ADR-0073 §3 is that inspection reads live beliefs only, and a question is not a
  belief of any band. Listing one there would claim the system holds something it
  explicitly declined to hold.
