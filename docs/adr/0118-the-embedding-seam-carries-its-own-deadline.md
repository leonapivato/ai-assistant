# 118. The embedding seam carries its own deadline, and an expired embed is a named fault

- Status: Proposed
- Date: 2026-08-08
- **This is the deadline ADR-0111 §4 sent a lane to write.** §4's second clause
  makes a per-operation deadline "a precondition of being chunked at all" and says
  the check "must be checked rather than assumed": "a job whose chunk reaches an
  operation with no deadline is not a job that may be chunked under this ADR, and
  its lane owes that operation a deadline before it may be scheduled." #820 is that
  lane's charter. §1 below performs the check on consolidation's chunk, operation
  by operation; §§2–7 supply the deadline the check finds missing.
- **Surface. This is a substantive contract ADR under ADR-0015 §5, and golden rule
  5 is separately not triggered.** Two different tests, easy to conflate, and this
  bullet is written out because an earlier draft did conflate them and architecture
  review was right to refuse it.

  **ADR-0015 §5's test is met.** It defines a substantive contract ADR as "one
  adding or changing a Protocol **or a `core/` type crossing subsystem
  boundaries**", and §5 below does the second: it adds a class to
  `core/errors.py`, has `models/` raise it, and *obliges* `memory/` to recognise
  and preserve it distinctly. A `core/` type whose identity has to be legible in
  two subsystems to do its job is exactly what that clause names. The consequence
  is procedural and is taken in full — this ships as **its own PR, docs only,
  `Proposed` while it is reviewed and ratified before the implementation PR that
  depends on it** — and **both review lenses are run**.

  **Golden rule 5's test is not met, and this is not a hedge.** This ADR touches
  **no** Protocol in `core/protocols.py` and **no** type in `core/types.py`, and it
  writes no text on `Embedder`: the deadline is a property of the *wired* embedder,
  not of the contract, and §9 argues that at length rather than asserting it. "A
  new `AssistantError` subclass is neither a Protocol nor a `core/types.py` model,
  so golden rule 5 is not triggered" is ADR-0083 §6's ruling verbatim, quoted
  approvingly by ADR-0111's own header for a discriminator of the same shape. What
  turns on it is real rather than nominal: **no triad is owed** — no Protocol
  member, no conformance case, no canonical fake — and `scripts/ship.sh`'s
  automatic architecture requirement, which fires on a diff touching those two
  files, does not fire here. The lens is run by decision, not by the tool.

  **Nothing about golden rule 1 is strained by the class crossing a boundary.**
  Error classes live in `core/errors.py`, and under golden rule 2 everything may
  depend on `core`; `SqliteMemoryStore._embed_one` already catches what `models/`
  raises and translates it. What §5 changes is that the translation preserves a
  distinction instead of discarding one, which adds no dependency in either
  direction.
- **No implementation lands with it.** No `src/`, no `tests/`. This ADR arms no
  job, adds no field to `core/config.py` and writes no code; it decides what the
  implementing lane builds. Enabling any job the scheduler ships disabled stays
  ADR-0111 §11's "implementation lane's act against this text once ratified".
- **#829's leg-8 entry ruling is upstream of this and is not touched.** Its
  requirement 1 makes this decision's *implementation* a precondition of the arming
  moment; its requirement 3 fixes that `Settings.consolidation_interval`, when
  re-added, defaults to `None`. Nothing below re-adds that field, changes that
  default, or brings the arming moment forward.
- **One record is owed under ADR-0082 §1 and this change writes it**, on ADR-0060
  §5's assessment that a cancelled `embed()`'s abandoned worker "wastes CPU and
  finishes; it corrupts nothing". §10 names the sentence, applies the test, and
  states clause by clause what is *not* owed — in particular that **nothing here
  amends ADR-0111 §4**, which deferred this question to a lane by role and now has
  its answer.
- **Durability clause.** Every reference below to ADR-NNNN is to its text as merged
  on 2026-08-08, not to its status on any later day. Where a later ADR changes one
  of them, this ADR is read against the text quoted here and the later ADR's own
  record says what moved. Where an ADR cited here stands `Proposed` — ADR-0089 is
  the one — no clause below rests on its ratification, and the marking form used in
  this document binds as prose if that regime never lands.
- Refs #820, #819, #829, #710, #632.

## Context

### Two premises the charter states, checked against the tree

#820 was written against PR #819's tree and both of its load-bearing tree claims
hold, with one name wrong and one status stale. Recording both, because an ADR
that repeats a charter's error inherits it.

**Holds.** `FastEmbedEmbedder.embed` — in
`src/ai_assistant/models/fastembed_embedder.py` — awaits
`asyncio.to_thread(self._embed_sync, documents)` and nothing else; there is no
deadline in it, around it, or in any caller. `core/config.py` carries no embedding
timeout of any name: its resilience block bounds the model layer
(`model_timeout_seconds`, `model_max_attempts`, `model_backoff_base_seconds`,
`model_backoff_max_seconds`) and stops there. And the write path is as the charter
describes — `MemoryWriteStage.write` reaches `MemoryStore.write_atomic`, whose
`SqliteMemoryStore` implementation calls `_embed_one` once per record before
taking its lock, and `_embed_one` awaits `Embedder.embed`.

**Wrong name.** The charter calls the class `FastEmbedTextEmbedder`. The class on
`main` is `FastEmbedEmbedder`; `FastEmbedTextModel` is the loaded-model alias
beside it. One object, two halves of its name transposed.

**Stale status.** The charter's framing inherits ADR-0060 §5's expectation that
`Embedder` conformance is an open follow-up. **#347 is closed**:
`tests/models/embedder_contract.py` exists, carries a cancellation case under
ADR-0060, and is the suite any new `Embedder` implementation is measured against.
That changes nothing this ADR decides and it changes what the implementing lane
inherits, so it is stated rather than discovered.

**One thing the charter's table does not mention, and it matters.**
`SqliteMemoryStore.search` embeds the *query* through the same `_embed_one`. The
unbounded seam is therefore not only under the scheduler's write path; it is under
the interactive read path too, where a hang is a request that never answers. The
charter is scoped to the scheduled jobs because that is where ADR-0111 §4 bites,
not because the exposure stops there — and §8 below is where that distinction is
paid for.

### What the abandoned worker actually does, which is the hinge of the whole decision

A deadline over `embed()` cannot stop the work. `asyncio.to_thread` hands
`_embed_sync` to the running loop's default executor, and a thread cannot be
interrupted: cancelling the awaiting coroutine drops the future and leaves the
thread running. ADR-0060 §5 says exactly this and assessed it as harmless — "The
orphaned worker wastes CPU and finishes; it corrupts nothing" — on the correct
observation that the thread holds nothing whose *safety* another caller depends
on. That assessment is right about safety and silent about capacity, and capacity
is what a deadline turns into the operative axis, in two verified ways.

**The executor is shared with every SQLite store in the process.**
`ai_assistant.memory.sqlite_store`'s `_run_to_completion` — the ADR-0054 helper,
duplicated verbatim in the permissions and planning stores — runs its worker with
`loop.run_in_executor(None, worker)`, the same default pool `asyncio.to_thread`
uses, and submits a *second* job to that pool when it absorbs a cancellation. So a
pool filled by abandoned embedding threads does not degrade embedding; it stalls
every store operation in the hub behind a queue that will not drain.

**A worker abandoned inside the lazy load wedges the seam permanently.**
`FastEmbedEmbedder._loaded` takes `self._load_lock` with a plain `with` and holds
it across `self._backend.load(...)`. A load that never returns holds that
`threading.Lock` forever, and every later `embed` blocks acquiring it — each one
consuming another pool slot, none of them reaching inference. The first expiry
during a cold load is therefore not one lost call; it is the seam.

Neither fact is a reason not to bound the seam. Both are reasons the bound owes a
containment ruling in the same breath, which is §7.

### #829 fixes the order, and this ADR sits inside it

The leg-8 entry ruling keeps consolidation unarmed through a precision baseline
and arms it mid-window as a dated intervention. Its requirement 1 says this
decision's implementation "merges before the arming moment — it is ADR-0111 §4's
precondition and is not waived by this ruling". So the sequence is: this ADR
ratifies, an implementation lane builds against it, and only then is the arming
moment #829 governs even reachable. Nothing here shortens that.

## Decision

### 1. §4's check, performed on consolidation's chunk, and what "bounded by a deadline" means

ADR-0111 §4 obliges a lane to check, and the check is only meaningful if
"bounded by a deadline" has an answer for operations nobody would put a timeout
knob on. §4's own prose supplies the test in the reason it gives for the clause: a
budget "bounds nothing if the boundary can fail to arrive: a provider call that
never returns holds the serial loop for as long as it hangs, and no figure in
`Settings` would say so." What the clause is protecting is *the arrival of the
chunk boundary*. So:

> **Normative.** An operation satisfies ADR-0111 §4's second clause when its
> return is guaranteed either by an explicit deadline it or its caller applies, or
> by construction — the operation is local, waits on nothing that can wedge
> indefinitely, and does work proportional to the chunk it was given. An operation
> whose completion depends on a component that can stop returning without failing
> is bounded only by an explicit deadline, and a lane may not substitute an
> argument for one.

The literal alternative — every operation carries a timeout knob — makes §4
unsatisfiable, because no SQLite call in this tree carries one and none will;
ADR-0111 §4 read itself the same way when it named `model_timeout_seconds` as "the
cost that dominates these jobs" while the chunk it was describing obviously also
reads and writes the store.

Applying that test to a consolidation chunk, operation by operation:

- **`MemoryStore.walk_records`** — bounded by construction. A local SQLite read on
  the store's own connection, work proportional to `scheduler_chunk_size`, over a
  driver whose lock waits carry `sqlite3`'s own default. Nothing in it waits on a
  component that can stop returning.
- **`ModelProvider.complete`** — bounded by an explicit deadline.
  `model_timeout_seconds`, applied per attempt by `RetryingProvider`, which is
  where `models/retry.py` says the deadline lives "not in the adapter … [because]
  every provider gets it uniformly".
- **The chunk's writes, reaching `Embedder.embed`** — **unbounded**. The failing
  leg, and the whole of #820.
- **The store write itself, `MemoryStore.write_atomic`** — bounded by
  construction, on the same reading as `walk_records`, and once the embedding
  ahead of it is bounded, the whole of what `write_atomic` still does on the
  caller's behalf is local.

The check therefore comes out one-legged: consolidation is admissible under §4
exactly when `Embedder.embed` acquires a deadline, and this ADR gives it one.

**This clause is a stacked addition to ADR-0111 §4, not an amendment of it.** §4's
obligation neither grows nor shrinks: a lane must still check every operation and
must still supply a deadline where one is missing. What this clause supplies is
what §4 gave no instruction about — how to judge an operation nobody would put a
knob on — which is the shape ADR-0082 §1 classifies as stacked. §10 argues it
against the test rather than asserting it.

### 2. The deadline lives at the `Embedder` seam, in a wrapper the composition root wires

#820 enumerated three places for it. All three are refused, and the fourth is the
corpus's own answer to the identical problem one seam over.

> **Normative.** The deadline over an embedding call is applied by a decorating
> `Embedder` in `models/` that wraps any inner `Embedder`, delegates `model_id`
> and `dimensions` unchanged, and bounds `embed`. It is not applied inside
> `FastEmbedEmbedder`, not inside any `MemoryStore`, and not at a scheduled job's
> own boundary.

> **Normative.** The composition root wires no unbounded `Embedder` into anything
> the hub can reach. `ai_assistant.app.composition`'s `_build_embedder` returns the
> wrapped embedder for every `EmbedderKind`, and every consumer it hands an
> embedder to — the memory store and `build_reembedder` alike — receives that one.

**Why not inside `FastEmbedEmbedder`.** It is the adapter, and `models/retry.py`
already recorded why the deadline does not go in the adapter: "every provider gets
it uniformly". A deadline inside the fastembed class binds one implementation and
re-opens the hole for the next one, and it makes the bound invisible to a reader
of the seam. It would also be the only bounded `Embedder` in a codebase that ships
two.

**Why not at the `MemoryStore` seam.** It bounds one store's callers rather than
the seam, so a second `MemoryStore` re-opens the hole, and `Reembedder._embed` —
which awaits the same contract through its own translation — is left out. It also
puts a `models/` concern on `memory/`'s door: the store would own a deadline over
an injected contract whose cost profile it cannot know. ADR-0060 §4 is adjacent and
worth not misreading: it refuses a `timeout` *parameter* on a store method, on the
ground that "the caller keeps its own deadline — the store's obligation is to
*honour* it". A store minting its own deadline over its collaborator is the same
instinct wearing different clothes.

**Why not at the job's boundary, and this one is refused by ADR-0111 §4 itself.**
A deadline at the job wraps the whole chunk, not the operation, so when it fires it
fires mid-chunk — and §4's first clause says "the budget is checked only at a chunk
boundary, so **no chunk is abandoned part-way**". §4 also says in terms that it
"adds no cancellation mechanism and does not reach inside a chunk". Worse, a
cancellation delivered into a chunk mid-write lands on a store call whose effect is
then indeterminate to the caller under ADR-0060 §1's third clause — trading a
bounded hang for an unbounded ambiguity. And it would bound only the job that asked,
leaving the calendar-reader ingestion job, which is armable today and writes through
the same stage, exactly as hangable as before.

**Why a decorator is the right fourth answer.** It is `RetryingProvider`'s shape,
chosen for `ModelProvider` for the reason that transfers unchanged: resilience
"composes with any implementation … without either side knowing about the other".
It bounds the *seam*, so every caller — the store's writes, the store's `search`,
the migration — is bounded by one object, and a future `Embedder` is bounded on the
day it is wired rather than on the day someone remembers.

### 3. One attempt. No retry, and no backoff

> **Normative.** The bounded embedder makes exactly one attempt per `embed` call.
> It does not retry an expired or failed embedding, and it applies no backoff.

`RetryingProvider` retries because a remote provider fails transiently; an
on-device ONNX runtime does not. Retrying here buys nothing and costs precisely
what §7 is about: each retry against a wedged backend abandons another worker on a
shared pool, so a retry policy multiplies the blast radius of the one failure mode
the deadline exists to survive. ADR-0111 §6's ruling for the scheduler is the same
shape and its reasoning transfers — "the interval is already the backoff", and a
failure that recurs should stay as loud on the tenth interval as on the first.

### 4. `Settings` gains one field, and it is a ceiling on pathology

> **Normative.** `Settings` gains `embedding_timeout_seconds`, a real number
> defaulting to `30.0`, refused at load unless it is exactly a real number that is
> finite and strictly positive — the `_RealSetting` shape with `gt=0` and
> `allow_inf_nan=False` that `model_timeout_seconds` already carries, for the
> reason `core/config.py` already states: infinity "would silently disable the
> deadline".

> **Normative.** The deadline covers the whole of one `embed` call, including a
> lazy model load performed inside it. A bound that excludes the operation that
> touches the filesystem is a bound with a hole exactly where the seam wedges.

**Thirty seconds, and the figure is argued rather than picked.** It must clear a
cold ONNX session initialisation on a slow disk plus one inference with headroom,
because `FastEmbedEmbedder` loads lazily inside `embed` and a deadline that fires
on an ordinary cold start would break the first write after every hub restart —
converting a startup cost into a recurring fault. It must not be so large that the
bound is nominal. It is a ceiling on pathology and not a latency target, which is
the same posture `model_timeout_seconds` takes at 60 for a remote call; naming a
figure rather than "bounded" follows ADR-0074 §9.3.

**What the field makes computable, stated plainly, because the arithmetic
surprises.** ADR-0111 §4 asks an operator to compute a chunk's true bound as the
per-record cost times the chunk's records. With `scheduler_chunk_size` at 50 the
embedding leg contributes up to 50 × 30s in the worst case — real, and smaller than
the model leg the same chunk already carries at `max_attempts × timeout + backoff`
per record. **The deadline does not make a chunk fast; it makes a chunk finite.**
The slow case is bounded by that product and is the operator's to size; the
pathological case — a backend that stops returning — is bounded by this field and
was previously bounded by nothing. Only the second was ADR-0111 §4's complaint.

**And in the pathological case the run's real cost is one deadline, not fifty**,
because ADR-0111 §5 halts a run at the first chunk it cannot record as done: an
expired embed fails its write, the chunk is not recorded, and the run returns. That
is §5 doing its job, and it is also what bounds §7's leak.

### 5. Expiry raises its own class, and that class survives the store

> **Normative.** An expired embedding raises a dedicated `AssistantError` subclass
> that names the deadline, distinct from every class an embedder raises for a
> backend fault and from every class a store raises for a store fault. Nothing
> downstream may identify the condition from message text.

> **Normative.** A component that translates an embedder fault into its own error
> vocabulary translates an expiry into a correspondingly distinct class of that
> vocabulary, preserving the original as the cause. The condition is legible at
> every boundary it crosses, or it is legible nowhere.

**The second clause exists because the first is not sufficient, and the tree shows
why.** `SqliteMemoryStore._embed_one` catches `Exception` from the embedder and
re-raises `MemoryStoreError` with the message `f"embedder failed: {exc}"`;
`Reembedder._embed` does the same, deliberately, "the shape
`SqliteMemoryStore._embed_one` already uses, applied to a batch". Both translations
are right — an injected contract's faults must not leak through a store's
documented boundary — and both flatten a well-classed timeout into the one class a
broken disk also raises. A discriminator that dies one frame above where it was
raised is not a discriminator.

**The ground is ADR-0083 §6's, and it is quoted rather than paraphrased because
this is the same defect.** §6 records that `_verify_or_init_meta`'s refusal "is a
`MemoryStoreError` — a subsystem error from below the disk line — so the entry
point cannot tell 'this deployment cannot serve this store' from 'this disk is
broken' without matching on a message string", and that "the remedy was a class".
Replace the two conditions with "the embedding backend has stopped returning" and
"this disk is broken" and the sentence is unchanged.

**On ADR-0111 §9, this ADR is careful about what it is entitled to.** §9's clause
requires a *refusal* to be distinguishable from a *fault*, by class. An expired
embed is a fault, so §9's clause does not literally compel anything here. What
transfers is §9's reasoning — "Class, not message, because the corpus has already
paid for the alternative" — applied to a fault/fault distinction §9 did not reach.
Stating that as an extension rather than an application matters: a lane told that
§9 compels this would go looking for a clause that is not there.

**Which class, and where it is defined, is the implementing lane's.** ADR-0111 §9
declined the same choice in the same words — "Whether the discriminator is a
marker base class or an explicit tuple is a code decision this ADR does not take;
what it takes is that a discriminator must exist and must not be a message" — and
the natural home is `core/errors.py`, where every class in this tree lives and
which every subsystem may import without touching golden rule 1.

### 6. An expired embed is a fault, and must never be filed as a refusal

> **Normative.** An expired embedding is recorded as a fault. It is not added to
> the class list ADR-0111 §9 reserves for refusals the corpus rules correct for a
> deployment's configuration, and no clause of this ADR makes it quieter on
> repetition.

The temptation is real: a deadline expiring every interval looks like the
every-interval refusal ADR-0097 §5 ratified as correct behaviour, and filing it
there would stop it paging anybody. It is the opposite condition. A refusal is
correct behaviour under a configuration an operator chose; a wedged embedding
backend is a hub that has stopped being able to remember anything, and §5's halt
means it is also a job making no progress. ADR-0111 §6 rejected exponential backoff
partly because it "would make the refusal quieter over time — the opposite of what
an operator needs"; mis-filing a fault as a refusal does the same thing in one step.

### 7. The deadline stops the waiting, not the work — and the abandoned worker is contained

> **Normative.** A deadline over an embedding stops the caller waiting; it does
> not stop the worker. An implementation may not represent an expiry as the work
> having been abandoned, and a caller may not assume the embedding did not happen.

That is ADR-0029 §4's cooperative limit and ADR-0060 §1's third clause, restated
where this seam will be read. It is also what makes the deadline *sufficient* for
ADR-0111 §4: the scheduler's serial loop runs on the event loop, and a call that
stops waiting returns control to it. The chunk boundary arrives, the run budget is
checked, and the loop is released — which is the whole of what §4 asked for, bought
without pretending the ONNX thread died.

> **Normative.** Abandoned embedding workers may not exhaust the executor the
> SQLite stores share. The bounded embedder's work runs where its exhaustion is
> contained to embedding, so a wedged backend degrades embedding into a repeating,
> named fault and leaves every other subsystem's worker-thread capacity intact.

> **Normative.** Hub shutdown does not block on an abandoned embedding worker. A
> containment mechanism that makes process exit wait on a thread that will not
> return has moved the hang rather than bounded it.

**Both clauses are consequences this ADR creates and therefore owes.** The Context
above establishes the two verified facts: the default executor is shared with
`_run_to_completion` in three stores, and a worker abandoned inside
`FastEmbedEmbedder._loaded` holds a `threading.Lock` that every later call blocks
on. Without containment, the decision above converts "one job hangs the loop" into
"the hub slowly stops being able to touch any database" — quieter, later, and
harder to read, which is a worse fault than the one it replaced.

**The mechanism is the lane's, on the same division ADR-0111 §9 used for its
discriminator — but the two clauses together are a narrower gate than either
alone, and this ADR does not pretend the obvious shape passes it.** A thread pool
the embedder owns satisfies the containment clause and, in its obvious form,
**fails the shutdown one**: `concurrent.futures.thread` registers an `atexit` hook
that joins every worker, so one wedged thread turns a hub that will not embed into
a hub that will not stop, which is what ADR-0083 §4's two-phase shutdown and
`shutdown_drain_seconds` exist to avoid. Naming that as a satisfying shape would
have handed the lane a mechanism that breaks a clause four lines above it.

**What the two clauses admit, stated as constraints rather than as a choice:**

- **A thread-based mechanism must be one nothing joins at exit** — daemon workers
  the interpreter abandons, rather than a pool whose shutdown waits. It contains
  the capacity and it never reclaims the wedged worker: the thread survives until
  the process does.
- **A mechanism that refuses rather than queues** — a bound on outstanding
  embedding calls, above whatever runs them — satisfies both clauses on its own
  terms, because a refusal allocates nothing to be joined. It is the cheapest
  shape and it still leaves the wedged worker where it is.
- **Only process isolation can end the wedged work**, because only a process can
  be killed. It is the heaviest option, it is the one that actually reclaims the
  ONNX runtime, and this ADR neither requires nor forecloses it.

The first two contain the blast radius and leave the seam dead until a restart —
which §7's closing paragraph already accepts as the remedy. The third is the only
one that does better, and whether that is worth its cost is the lane's call with
the profile in hand, not a judgement this ADR can make from here.

**Under either in-process mechanism, recovery from a fully wedged seam is a hub
restart, and that is accepted.** Once a load has wedged under `_load_lock`, no
mechanism that shares the process recovers the seam — the lock is held by a thread
nothing can interrupt. What containment buys is that the hub stays up, keeps
serving everything that is not embedding, and says the same nameable thing every
interval until an operator acts. ADR-0083 §5 maps a hub's exits into "come back"
and "stay down", so a restart is a legible remedy rather than a lost state, and a
seam that fails loudly every interval is what makes an operator reach for it.

### 8. What the bound reaches, and why that is wider than §4 compels

> **Normative.** The bound applies to every call through the `Embedder` seam,
> whatever the caller. It is not conditioned on the caller being a scheduled job,
> a chunked job, or a job at all.

ADR-0111 §4's second clause is scoped to chunked jobs, and this ADR does not widen
it. §4 is the *occasion* for the deadline, not the *extent* of the exposure, and
the extent is checked here rather than assumed:

- **`retention_purge`** — outside the clause twice over. It is not chunked, and it
  does not embed: `SqliteMemoryStore.purge_expired` deletes rows and their vectors
  and reaches no `Embedder`. ADR-0111 §10 already recorded the first half for
  ADR-0076 §2, "and §4's bound is scoped to chunked jobs precisely so it cannot".
- **`conversation_sweep`** — the same, on the same two grounds. `sweep_deletions`
  finishes a deletion; nothing in it embeds.
- **Observation and calendar-reader ingestion** — **inside the exposure and
  outside the clause.** Both write through `MemoryWriteStage` to `write_atomic`
  and therefore embed; neither is chunked, so §4's second clause does not bind
  them. The calendar reader is armable today. A fix scoped to what §4 compels
  would leave an armable job able to hold ADR-0083 §7's serial loop indefinitely,
  which is the same defect with a different job's name on it.
- **`SqliteMemoryStore.search`** — the interactive read path, bounded here as a
  consequence of bounding the seam rather than as a separate decision. Its failure
  mode changes: a query whose embedding is pathologically slow now fails with a
  named class instead of never answering. That is the trade, and at the default it
  is not close.
- **`Reembedder`** — bounded because it is wired from the same composition root,
  though ADR-0104 §6 keeps the migration outside the scheduler entirely, so no
  clause of ADR-0111 ever reached it.

Nothing above makes any of these jobs chunked, changes any interval, or arms
anything.

### 9. Golden rule 5 is not triggered, and no text is written on `Embedder`

> **Normative.** This decision changes no Protocol in `core/protocols.py`. The
> `Embedder` Protocol's members, signatures and exchanged types are untouched, and
> no sentence is added to it.

The question is not whether a deadline is important; it is whether a *caller of
`Embedder`* must now assume something it could not assume before. It must not.
`Embedder.embed` documents no `Raises:` clause and promises no bound today, and a
caller that assumed one would already have been wrong — `FastEmbedEmbedder` raises
`ModelError` from a path the Protocol never mentions. Adding a bounded
implementation alongside the two that exist adds no obligation to the contract and
removes none.

**The guarantee ADR-0111 §4 actually needs is about a deployment, not a
contract.** §4 asks whether the operations *this job performs* are bounded. That is
a fact about what is wired, and `app/` is "the only place concretes are wired"
(`CLAUDE.md`), which is why §2's second clause is stated over `_build_embedder`
rather than over the Protocol. A clause in `protocols.py` would not even establish
it: a Protocol cannot compel a composition root to wire the implementation that
honours it.

**ADR-0060 §2 is the precedent and it is directly on point.** It refused to write a
cancellation paragraph on every Protocol — "a rule that mostly says 'nothing to do
here' trains readers to skip it, and then it is not there when it bites" — and
named `Embedder` specifically as bound by the module-level rule without any
`Embedder`-local text. A deadline sentence on `Embedder` would be that filler
clause, and it would be false besides: `HashingEmbedder` is bounded by
construction and applies no deadline at all.

> **Normative.** The bounded embedder is an `Embedder` implementation and is
> measured against the shared conformance suite in
> `tests/models/embedder_contract.py`, which #347 landed. This ADR adds no case to
> that suite, because it adds no obligation to the contract the suite enforces.

### 10. Amendment records under ADR-0082 §1

ADR-0082 §1 puts the judgement in the later ADR's text and states the test:
would a reader holding only the earlier ADR "now act differently, or read one of
its clauses more widely than it now holds". Applied clause by clause.

**One record is owed, and this change writes it.**

**ADR-0060 §5.** Its sentences about `Embedder` are an *assessment of
consequence*, not a deferral: "The orphaned worker wastes CPU and finishes; it
corrupts nothing", and "the gap is real but currently benign". A reader holding
only ADR-0060 would read those as covering an abandoned worker however it came to
be abandoned, and would put a deadline over `embed` with no guard — which is the
decision this ADR makes and then has to contain. Both halves narrow. "Finishes" is
true of the case §5 had in mind and false of the case a deadline exists to fire in;
"corrupts nothing" is true on the safety axis §5 was reasoning about and silent on
the capacity axis, where the shared default executor makes an unfinishing worker
everybody's problem. The test is met on the "read more widely" limb, which is the
limb ADR-0111 §10 recorded ADR-0083 §7 on. **ADR-0060's own Revisit condition names
this arrival** — "Revisit if a seam grows a genuinely unbounded synchronous
operation" — and the answer §7 above gives is containment at the seam rather than
the numeric ceiling on the bounded-deferral clause that the Revisit anticipated;
recording that is the point of the record.

**This is an amendment and not a supersession** under ADR-0070 §1. Everything
ADR-0060 *decided* is untouched and relied on: §1's three clauses in full — the
resource clause is satisfied here rather than strained, because a self-issued
deadline is expressly "its own control flow" under §1's provenance qualifier, and
the third clause is quoted by §7 above; §3's scope of four conformance suites;
§5's ruling that `Embedder` is "bound and unenforced rather than silent"; and §5's
finding that the abandoned worker is not the ADR-0054 bug, which stays exactly true
and is why §7's clauses are about capacity and not about safety. ADR-0060's
`Status` is plain `Accepted` with no leading token, so under ADR-0082 §2 the
qualifier belongs on that line and the dated note goes below it.

**No record is owed on:**

- **ADR-0111 §4.** Its second clause names a lane by role — "its lane owes that
  operation a deadline before it may be scheduled" — and #820 is that lane's
  charter. Supplying the answer to a question an earlier ADR deferred to you is
  ADR-0083 §15's stacked addition: "the deferring sentence stays true and now has
  an answer." §1 above adds one thing §4 did not have, a test for what counts as
  bounded, and that is the shape ADR-0082 §1 classifies as stacked — it "supplies
  an instruction where §4 gave none rather than replacing one it gave". §4's
  obligation is unchanged in extent: every operation is still checked, and a
  missing deadline still disqualifies the job. Nothing here makes a job chunkable
  that §4 refused, because §4 refused consolidation for the embedder and this ADR
  bounds the embedder.
- **ADR-0111 §5, §8, §9 and §11.** §5's halt is relied on and unchanged — §4's
  arithmetic above depends on it. §8's serial loop is what the deadline protects.
  §9 is extended by analogy in §5 above and its clause is not read more widely: a
  fault is still a fault, and §6 above refuses the one move that would widen §9's
  refusal list. §11's "enabling any job the scheduler ships disabled is an
  implementation lane's act" is preserved verbatim by this ADR arming nothing.
- **ADR-0083 §7.** Its job table is untouched, no interval changes, and the serial
  loop's starvation acceptance is neither widened nor narrowed — ADR-0111 §4
  already bounded it and this ADR makes that bound real rather than restating it.
- **ADR-0083 §6.** §5 above borrows its reasoning about class-versus-message and
  changes none of its rules; no state fault is added, and no build refuses to
  start over anything here.
- **ADR-0097 §5.** Its ratified every-interval refusal is untouched, and §6 above
  is careful to keep an expired embed out of that category rather than to
  reclassify anything already in it.
- **ADR-0104.** §6 keeps the migration outside the scheduler and this ADR does not
  schedule it; `Reembedder` gains a bound as a consequence of wiring, which
  obligates nothing ADR-0104 decided and makes no sentence of it false.
- **ADR-0006 and ADR-0024.** The wrapper delegates `model_id` and `dimensions`
  unchanged, so the embedding-space identity ADR-0006 §4 ranks on and ADR-0024 §6
  pins is untouched; nothing here selects, downloads or substitutes a model.
- **ADR-0029 §4 and ADR-0054.** §7 above restates ADR-0029 §4's cooperative limit
  and ADR-0054's helper is quoted as evidence about the shared executor; neither
  ADR's clauses acquire, lose or alter an obligation.
- **ADR-0076 §2.** §8 above confirms the sweep stays outside every clause, which
  is what ADR-0111 §10 already recorded.

**The record is well-formed from the moment it is written**, on ADR-0083 §15's
ground: "The existence condition is that the naming ADR ships in the same change,
not that it has ratified." The note on ADR-0060 names ADR-0118 and ships in this
change; if this ADR does not land, neither does the note.

**The record is append-only and narrow.** ADR-0070 §1 permits the `Status` header
edit and the appended dated note and nothing else, so no sentence of ADR-0060 is
rewritten — §5's assessment stands as written and the note records what has become
narrower and why.

### 11. What this ADR does not decide

- **When consolidation is armed.** #829 owns the arming moment and its dating, and
  ADR-0111 §11 owns the act. This ADR removes a precondition; it does not
  discharge #829's requirement 1, which is met by the *implementation* lane.
- **`Settings.consolidation_interval`'s default.** #829's requirement 3 fixes it at
  `None`, and this ADR neither re-adds the field nor touches that ruling.
- **How the bounded embedder is composed with anything else in `models/`** — a
  retry wrapper, a router — beyond §3's ruling that this one does not retry.
- **The containment mechanism**, and the executor's size if that is the shape
  chosen (§7).
- **The exact class name and module of the expiry error**, and the corresponding
  class in each translating vocabulary (§5).
- **Any conformance case for `Embedder`.** #347 closed the suite this seam is
  measured against and §9 adds nothing to it.
- **`Engine._tracked`'s second operational record.** #710 stays open and is closed
  by its own lane; §6 above only refuses to file an expiry as a refusal, which is
  orthogonal to how many records a raising job emits.
- **Whether any other unbounded seam exists.** §1's test is stated so a future
  chunked job's lane can apply it; this ADR applies it only to consolidation's
  chunk.

## Consequences

**Consolidation becomes admissible under ADR-0111 §4 once the implementation
lands**, and the admissibility is now checkable rather than asserted: §1 lists the
chunk's operations and says which bound holds each one. That is the last of §4's
preconditions; what remains between here and an armed job is #829's ordering, which
is a measurement decision rather than a correctness one.

**Two jobs that were never in §4's scope get bounded anyway**, because the bound is
at the seam. Observation and calendar-reader ingestion both write through the same
stage, and the calendar reader is armable today — so the exposure that #820 names
for a job nobody can schedule is closed for the one job an operator can arm this
afternoon.

**A hung embedding backend becomes a legible, repeating fault instead of a silent
stop.** It has a class, it is a fault rather than a refusal, it recurs every
interval at the same volume, and it stops the run under ADR-0111 §5 rather than
holding the loop. An operator reading the hub's log sees the same nameable thing
each hour, which is what ADR-0083 §6's legibility posture asks for.

**What gets harder: an expiry is now a thing the tree must carry across three
boundaries.** §5's second clause obliges every component that translates embedder
faults to translate this one distinguishably — `SqliteMemoryStore._embed_one` and
`Reembedder._embed` today — and each of those is a place a later change can quietly
flatten it back into `MemoryStoreError`. The discriminator's value is exactly the
discipline of keeping it, and there is no mechanical check that it survives.

**What gets harder: the containment clause is a real constraint on a small change,
and the shutdown clause rules out the shape most readers reach for first.** The
obvious implementation of a deadline is four lines, and §7 makes it more than that,
because the obvious implementation trades a hang on the scheduler loop for a slow
starvation of every store in the process. Then the shutdown clause disqualifies the
obvious containment — an owned `ThreadPoolExecutor`, whose `atexit` join turns a
wedged worker into a hub that will not stop — and leaves the lane three shapes, of
which the two cheap ones contain the fault without ever reclaiming the worker. That
is a genuine cost of this decision and not an oversight in it: bounding a seam
whose work cannot be interrupted buys legibility, not recovery.

**Search's failure mode changes**, from a query that never answers to one that
fails with a named class after the deadline. That is strictly better and it is
still a change: a deployment on very slow hardware could see a search fail where it
previously only felt slow, and the remedy is the field rather than a code change.

**Two implementation lanes are visible from here, and they are not one lane.** The
bounded embedder and its `Settings` field are `models/` plus `core/`; the
translation clause in §5 lands in `memory/`. Whoever sequences the work owns that
split; CLAUDE.md's one-subsystem rule is the reason it is named here rather than
assumed away.

**What would trigger revisiting this.** An `Embedder` whose backend is remote,
which would reopen §3's no-retry ruling because a network embedding fails
transiently the way a model call does; measurement showing the 30-second default is
either routinely hit or never approached; an executor-sharing change in the stores
that makes §7's containment unnecessary or insufficient; or a second `Embedder`
acquiring something the event loop releases, which ADR-0060 §5 already names as the
condition that makes the whole seam ADR-0054's bug again.

## Alternatives considered

**A deadline inside `FastEmbedEmbedder`.** Rejected in §2. It is the adapter, it
binds one of two shipped implementations, and `models/retry.py` already recorded
why the deadline does not live there.

**A deadline at the `MemoryStore` seam.** Rejected in §2. It bounds a store's
callers rather than the seam, misses `Reembedder`, and makes a store the owner of a
deadline over a collaborator whose cost profile it cannot know.

**A deadline at each chunked job's boundary.** Rejected in §2, and refused by
ADR-0111 §4's own first clause: it fires mid-chunk, which abandons a chunk part-way
and leaves a store write's effect indeterminate under ADR-0060 §1. It also bounds
only the job that asks, which leaves the armable ingestion job unbounded.

**Reading ADR-0111 §4 literally, so that a local SQLite call also owes a knob.**
Rejected in §1. It makes §4 unsatisfiable by any job, and §4 did not read itself
that way when it named `model_timeout_seconds` as the chunk's dominant cost while
describing a chunk that plainly also reads and writes the store.

**A `Raises:` clause and a deadline sentence on `Embedder` in `core/protocols.py`.**
Rejected in §9. It would trigger golden rule 5 for a guarantee the Protocol cannot
deliver — a contract cannot compel a composition root to wire the implementation
that honours it — and it is ADR-0060 §2's filler clause, false of `HashingEmbedder`
on the day it was written.

**Reusing `ModelTimeoutError` for the expiry.** Tempting, since it exists, is a
`ModelError`, and means "the deadline expired". Declined because its documented
subject is a provider that "did not respond within the deadline (HTTP 408 or a
timeout)", and because `models/retry.py` already gives it a precise job —
distinguishing *our* deadline from a provider's own, which is a distinction the
embedder does not have. Overloading it would make the one class that currently
means "the model provider timed out" also mean "the local embedding runtime
wedged", which are different remedies. The implementing lane may still reach for a
shared base; what §5 forbids is a shared *class* that erases the difference.

**Filing an expiry as an ADR-0111 §9 refusal.** Rejected in §6. It would make a hub
that has stopped being able to remember anything look like a hub configured the way
its operator chose.

**Retrying an expired embedding.** Rejected in §3. Against a wedged backend each
retry abandons another worker on a shared pool, so the mechanism meant to survive
the failure amplifies it.

**Bounding the seam and saying nothing about the abandoned worker.** The shortest
version of this ADR, and the one that trades a fault an operator can see for one
they cannot. Rejected in §7: the default executor is shared with every SQLite
store's `_run_to_completion`, so the unguarded version converts a hung job into a
hub that slowly cannot touch any database, which is quieter, later and harder to
diagnose than what it replaced.
