# 65. A call observes its inputs at one instant, before its first await

- Status: Accepted, §4 amended 2026-07-25 (its `ModelProvider` row was false)
- Date: 2026-07-24
- Amended: 2026-07-25 (§4 — `ModelProvider` was listed as "bound and already
  satisfied". It was bound and **violated**: the survey behind that row read
  `PydanticAIProvider` and missed the two wrapper providers, both of which
  re-read the caller's `Sequence` after suspending. See the amendment; §3's
  enforcement scope is unchanged.)
- **This is a contract change.** It adds a second standing clause to
  `core/protocols.py`'s module docstring, binding on every Protocol in the file,
  and it extends the shared conformance suites and canonical fakes of two of
  them. Golden rule 5 therefore applies: this ADR ships as **its own PR,
  ratified ahead of any implementation** (ADR-0015 §5). It is reviewed while
  still `Proposed`, so a finding can still change the decision, and flipped to
  `Accepted` on merge — `CONTRIBUTING.md`, "Contract ADRs land before their
  implementation". This PR is docs-only; the implementation is a separate lane
  (issue #366), and until it lands the clause is a decision on record and not
  yet text in `protocols.py`.
- Refs: ADR-0056 (the deferral this answers), ADR-0046 §3, ADR-0045 §4,
  ADR-0060 (the adjacent rule, deliberately a *different* axis — see §5),
  ADR-0028 §2.
- Source: issue #348.

## Context

ADR-0056 fixed a torn write in `SqliteMemoryStore.add` (#286): the method
embedded a record's content, awaited the embedder, and then serialised the
record, so a caller that kept a reference to the submitted record and mutated it
while the coroutine was suspended could make the persisted JSON, the row `id`
and the persisted vector describe three different versions of one record. The
fix was to deep-copy on the coroutine's first line and derive everything from
that one snapshot.

ADR-0056 declined to universalise the rule:

> **We deliberately keep this a `SqliteMemoryStore` behaviour, not a universal
> `MemoryWriter` obligation.**

and noted the obligation as deferred. Two things about that deferral are worth
recording before answering it. It pointed at "the shape of issue #314", but #314
is `MemoryWriter` SUPERSEDE conflict-set parity — a different obligation
entirely — so the deferral had no tracking issue of its own until #348. And it
named `MemoryWriter`, while the method it is about, `add`, is on `MemoryStore`;
`MemoryWriter` carries only `ingest`. The imprecision is small but it is
symptomatic: the deferral did not know how wide its own subject was.

The question this records: **is "a call observes its inputs at one instant,
before its first await" an obligation of the contracts, or one implementation's
private behaviour?**

### What the tree actually looks like

The issue frames the gap as *latent* — `InMemoryMemoryStore` and
`FakeMemoryStore` both `model_copy(deep=True)` on store and have no await
between reading a record and storing it, so nothing tears today. That is true,
and it is true only of `MemoryStore`. Surveying the whole contract file changes
the answer.

**Eight methods on seven Protocols take an argument that is mutable all the way
down** — checked mechanically against `model_config["frozen"]`, transitively
through every field:

| seam | mutable argument |
| --- | --- |
| `MemoryStore.add` | `MemoryRecord` |
| `MemoryStore.write_atomic` | `Sequence[MemoryWrite]` — the container, and each frozen `MemoryWrite`'s mutable `record` |
| `MemoryWriter.ingest` | `MemoryUpdateProposal` |
| `MemoryPolicy.decide` | `MemoryUpdateProposal`, `Sequence[MemoryRecord]` |
| `Planner.plan` | `Goal`, `CurrentContext`, `Sequence[MemoryRecord]` |
| `PlanStore.save_goal` | `Goal` |
| `ModelProvider.complete` | `Sequence[Message]` |
| `FeedbackProcessor.process` | `FeedbackEvent` |

Of the rest: `ContextProvider.assemble()` takes no arguments at all, and
`ToolInvoker`, `ToolRegistry`, `ActionPolicy`, `AuditTrail` and the remaining
ten `PlanStore` methods exchange deeply-frozen types or plain strings. Two —
`Embedder.embed(texts: Sequence[str])` and `MemoryStore.search(..., kinds:
Sequence[MemoryKind] | None)` — take a **mutable container of immutable
elements**, which is a weaker case worth naming rather than glossing: re-reading
such an argument after suspending can change *which* values the call sees, but
no single value can tear underneath it.

`MemoryWrite` deserves its own line, because it is the trap. It is
`frozen=True`, and it holds a `MemoryRecord` that is not. `frozen` stops field
*reassignment*, not mutation of what the field points at — a fact `core/types.py`
already states in its own comments. So "the argument is frozen" is not, on its
own, evidence that a seam is safe.

**Five implementations have already derived this rule independently, and gave
four different reasons for it:**

- `SqliteMemoryStore.write_atomic` snapshots every record before its first await
  so a mid-flight mutation cannot change the id its duplicate-id check validated
  (ADR-0046 §3).
- `SqliteMemoryStore.add` snapshots for the torn write (ADR-0056, #286).
- `SqlitePlanStore.save_goal` snapshots via `_revalidated_goal` on its first
  line — reasoned as *revalidation*, to stop a mutated-past-its-validators
  `Goal` poisoning every later decode, with the mid-flight property a
  side-effect of where the call happened to be placed.
- `InMemoryMemoryStore.add` and `FakeMemoryStore.add` deep-copy on store,
  reasoned as post-call isolation.
- `FastEmbedEmbedder.embed` opens with `documents = list(texts)` — the first
  statement of the coroutine, before the model load and the worker-thread await
  — materialising the caller's sequence so nothing downstream reads it again.
  Reasoned as neither of the above; it is simply what you do before handing a
  sequence to a thread.

Five derivations, four rationales, no shared statement. That is the ADR-0060
pattern exactly: the reasoning was right each time and it had nowhere to live.
It is also why the clause below states a *property* rather than "deep-copy your
record" — these five discharge it four different ways, and all four are correct.

**And two seams read a mutable argument after suspending, today, unfixed.**
Both verified against the source, both filed rather than fixed here:

- `MemoryIngestor.ingest` (issue #366) reads `proposal.proposed` before
  `store.search`, again inside the injected `MemoryPolicy.decide`, and a third
  time in `_apply`, which is the read that gets written. The intermediate
  `proposal.model_copy(update={"conflicts": ...})` is **shallow**, so it shares
  the caller's `proposed` object rather than detaching it. The damage is not a
  torn record — the store beneath snapshots its own input — it is a semantic
  desync one level up: `_retirement_set` closes the windows of beliefs that
  contradict the content searched at the *first* read, while the record
  installed comes from the *third*. `FakeMemoryWriter.ingest` has the identical
  shape.
- `ModelBackedPlanner._build_plan` reads `goal.id` into the plan's `goal_id`
  *after* `await self._model.complete(...)` (issue #367), so a `Goal` mutated
  during the model call yields a frozen, auditable `ActionPlan` naming a goal
  the model never saw. `SqlitePlanStore.save_goal`'s `return goal.id` is the
  same defect in miniature — the row is written from the snapshot, only the
  returned id escapes it, which is precisely the read ADR-0056 moved when it
  changed `add`'s last line to `return snapshot.id`.

No in-tree caller exploits any of this. `orchestration/loop.py:287` ingests
proposals built fresh by `FeedbackProcessor.process` and keeps no aliased
reference. That is a property of today's callers, not of the contract.

### The suite already appears to cover this, and does not

`tests/memory/memory_store_contract.py` has carried
`test_stored_records_are_isolated_from_caller_mutation` since ADR-0045's commit
`7c82a0c` — an ancestor of ADR-0056's fix `d9534d4`. It stores a record, mutates
the caller's own object, and asserts the stored copy is unaffected.

It mutates **after `add` returns**. The pre-ADR-0056 `add` serialised the record
into SQLite before returning, so nothing done afterwards could reach the
committed row: the torn code passed this case, on every backend, for the whole
time the tear was live. A case named for caller-mutation isolation certified
exactly the bug it is named for.

This is the strongest single fact in the file. It is ADR-0060 §3's warning about
a propagation-only cancellation case, in the wild and already shipped: the
weakest reading of "isolate the stored record from the caller" is a post-call
assertion, and a post-call assertion cannot distinguish a store that snapshots
from one that tears.

### This is not ADR-0060's axis

`docs/review/architecture-validation-2026-07-24.md` (claim C1) groups ADR-0056's
torn write with ADR-0054's and ADR-0057's cancellation bugs as one class. **That
grouping is wrong**, and ADR-0060 §5 already said so; this ADR states the
distinction rather than inheriting it.

ADR-0060 is about *cancellation orphaning a resource the implementation
acquired*. ADR-0056's tear involves no cancellation anywhere: nothing is
cancelled, nothing is orphaned, and the object at risk is the **caller's**, not
the implementation's. The two rules even have different vacuity sets, which is
the cleanest proof they are different rules: `AuditTrail` is one of the four
seams ADR-0060 enforces and is completely vacuous here (its inputs are deeply
frozen), while `Planner` is one of the four ADR-0060 §2 names as holding nothing
— and is a live instance of *this* rule (issue #367).

What the two genuinely share is only the root cause one level up: **what may
happen at an `await` was never written into any contract.** ADR-0060 wrote down
one half of that. This ADR writes down the other.

## Decision

### 1. Yes — it is a contract obligation, stated once at module level

We will state a second standing obligation in `core/protocols.py`'s module
docstring, alongside ADR-0060's cancellation clause, binding on every Protocol
in the file:

> **A call observes its inputs at one instant, before its first await.**
>
> Arguments belong to the caller, several types crossing these seams are mutable,
> and a `Sequence` argument is a container the caller may still be holding. So
> everything one call derives from one argument — what it stores, what it
> computes, what it returns — comes from **one** observation of that argument. A
> caller that mutates what it passed while the call is suspended may make the
> call act on the wrong version; it must never make one result describe two
> different versions.
>
> Three ways to discharge this, and the choice is the implementation's: do not
> suspend; do not read an argument again after suspending; or take a snapshot on
> the coroutine's first executed line — before the first `await` — and read only
> the snapshot thereafter, the returned value included. A snapshot must be deep
> enough to cover everything the call goes on to read. A frozen argument is not
> a discharge on its own: `MemoryWrite` is frozen and holds a mutable
> `MemoryRecord`.
>
> The boundary is the coroutine's **first executed line**, not the call
> expression. Calling an `async def` only builds a coroutine, so a mutation made
> after construction and before the first await is captured whole. That is not a
> tear — the caller gets the state as of the moment the work began — and no
> invocation-time capture is claimed (ADR-0056).
>
> **The caller's side.** A caller may not assume a mid-flight mutation was
> ignored, nor that it was honoured. What it is owed is that the outcome is
> *coherent*, not that it reflects any chosen version. Mutating an argument
> across a call still in flight remains a caller error; this rule bounds the
> damage rather than blessing the practice.
>
> Silent where a method does not suspend, or where its arguments are immutable
> all the way down — which is most of this file.

The rule states a **property, not a mechanism**, for the reason ADR-0060 gives
for keeping `_run_to_completion` out of `core`: "the contract states the
obligation; the mechanism stays the implementation's." `model_copy(deep=True)`
is one discharge. Rendering everything into a request before the first await, as
`ModelProvider.complete`'s implementations do, is another and costs nothing. A
future store on a native async driver may need neither.

**Read-once, not copy-always** is the load-bearing choice. An unconditional
"snapshot your input" clause would force `InMemoryMemoryStore.add` and every
non-suspending method to deep-copy for nothing, and a rule that mostly says "do
useless work here" is a rule readers learn to skip — ADR-0060 §2's argument,
applied to cost rather than to verbosity.

### 2. Why module level, and not on `MemoryStore`/`MemoryWriter`

ADR-0060 answered this structural question once, for a different rule, and its
reasoning — "divergent local paraphrases of one rule are the failure mode" —
transfers. But it should not be adopted by reflex, so here is the argument on
this rule's own facts.

**The scope the issue asks about is factually too narrow.** #348 asks whether
this is a `MemoryStore`/`MemoryWriter` obligation. The survey in Context says
no: seven Protocols take a mutable argument, and the two *unfixed* instances are
in `MemoryWriter` **and `Planner`**. A clause written on `MemoryStore` and
`MemoryWriter` would leave `ModelBackedPlanner`'s post-await `goal.id` read
outside the contract, and it would leave it outside on the strength of a scope
decision made before anyone looked.

**Enumeration has already failed here once.** Three of the four existing
snapshots were reasoned locally and reached three different justifications; the
fourth seam, `save_goal`, got the snapshot right and the return value wrong,
because "revalidate before persisting" does not imply "and read nothing else
afterwards". Per-seam statements are per-seam chances to state a slightly
different rule — which is the paraphrase failure mode already in progress, not a
hypothetical one.

**The two rules' vacuity sets differ**, so neither can be scoped from the
other's list. ADR-0060 enforces on `MemoryStore`, `AuditTrail`, `ContextProvider`
and `PlanStore`; of those, `AuditTrail` is wholly vacuous here (its arguments
are deeply frozen) and `ContextProvider` more so still — `assemble()` takes no
arguments at all. `Planner` and `MemoryPolicy` are vacuous there and live here.
A rule stated at module level binds seams nobody enumerated; a rule stated
per-Protocol binds the seams whoever wrote it happened to think of.

**And the shape has a precedent that fits.** The module docstring will carry two
clauses about what may happen at an `await` — one about a resource the
implementation acquires, one about an object the caller owns. They belong
together, and stating the second in a different *form* from the first would
imply a distinction that does not exist.

Following ADR-0060 §2, the Protocols whose suites gain cases (§3) carry a
**one-sentence pointer** to the module clause, not a restatement. The pointer
must point and not re-say.

### 3. Enforcement is scoped to `MemoryStore` and `MemoryWriter`

The shared conformance suites and canonical fakes the implementation lane owes,
stated exactly so the follow-up is bounded:

| suite | fake | production implementations it must hold for |
| --- | --- | --- |
| `tests/memory/memory_store_contract.py` | `FakeMemoryStore` (`testing/memory.py`) | `SqliteMemoryStore`, `InMemoryMemoryStore` |
| `tests/memory/memory_writer_contract.py` | `FakeMemoryWriter` (`testing/writer.py`) | `MemoryIngestor` |

Those two because they are where the rule has been broken: `MemoryStore` is the
seam ADR-0056 fixed and the one whose suite currently gives false confidence,
and `MemoryWriter` is the one live, unfixed instance inside `memory` (#366). The
lane therefore also **fixes `MemoryIngestor.ingest`** — a suite case without the
fix is a red gate, so the fix and the case are one change.

**Each case must establish mid-flight observation, not post-call isolation.**
This is not a note about test style; it is the whole content of the enforcement,
for the reason §"The suite already appears to cover this" documents: the existing
post-call case passed on the torn code. The minimum each suite must establish:

- For `MemoryStore`, **two cases — one for `add`, one for `write_atomic`.** With
  the write suspended mid-flight, mutate the caller-held record from inside that
  suspension, then assert every part of what the store committed agrees with
  **one** version of the input.

  For `add` that is: the returned id names the row that was written, and the
  stored content is the content the vector was computed from.

  `write_atomic` needs its own case and is not a rewording of the first, because
  it carries three obligations `add` does not. Its argument is a caller-owned
  **`Sequence`** — the container is mutable whatever its elements are, which the
  clause calls out specifically. Its elements are the `MemoryWrite`s whose
  `frozen=True` does *not* freeze the `MemoryRecord` inside them — this ADR's own
  headline example of why "the argument is frozen" is not a discharge. And its
  duplicate-id check (ADR-0046 §3) validates ids that must be the *same* ids
  subsequently written, so a backend that revalidates pre-await and rereads
  post-await can pass validation on one batch and commit another. The case must
  therefore establish that the returned ids, the persisted records and vectors,
  the duplicate-id rejection and the all-or-nothing boundary all rest on one
  observation of the batch. A store could snapshot correctly in `add` and tear
  here; `SqliteMemoryStore` snapshots both, but nothing in a suite that tests only
  `add` would have said so.

  **How the suite suspends an arbitrary backend needs deciding here, because the
  obvious answer does not generalise.** `SqliteMemoryStore`'s lever is its
  injected `Embedder`, but no `Embedder` is on the `MemoryStore` Protocol:
  `InMemoryMemoryStore` has none, and a future async-driver backend would suspend
  on something else entirely. A case written around `FakeEmbedder` would enforce
  the rule for one backend and vacuously pass for every other — which is the
  false-confidence failure this ADR exists to end, reintroduced one level down.

  So the suite requires a **mid-write suspension hook, supplied through its
  fixture**, exactly as it already requires `store_factory` for the case the
  fixed `store` fixture cannot express. An implementation's test module overrides
  it either with a handle the case can synchronise on, or with an explicit
  declaration that this backend performs no `await` between reading its input and
  committing it — in which case the case reduces to the post-call assertion,
  correctly, because a store with no suspension window has no window to tear in.
  `SqliteMemoryStore` supplies the handle through its embedder;
  `InMemoryMemoryStore` and `FakeMemoryStore` declare the second.

  **The hook's position is part of its contract, not the implementer's choice.**
  "Blocks the write" is under-determined and would let a test module defeat its
  own case: a hook fired at method *entry* lets the mutation land before the
  method has read anything, so the store observes one coherent mutated version,
  the case passes, and a tear at the real suspension window survives untested.
  The hook must fire at **the method's own first suspension point** — its first
  `await` — and resume when the case releases it. That position is well-defined
  for every implementation, conforming or not, and it is well-defined *without*
  reference to where the implementation reads its input, which matters because a
  conforming implementation has no second read to position against. It is also
  exactly the boundary the clause draws: a conforming store has snapshotted
  before that point and cannot be reached by the mutation, while pre-ADR-0056
  `add` — content read, embedder awaited, id and JSON read after — is torn by it.
  Entry is the wrong side of that boundary, and the clause already says why: a
  mutation before the first await is captured whole and is not a tear.

  The hook is a requirement of the **conformance suite**, expressed through its
  fixture; it does **not** go on the `MemoryStore` Protocol. ADR-0060 §3 settled
  this trade for its own quiescence hook and the reasoning is unchanged: a
  test-only affordance on the production seam buys observability by widening the
  contract every consumer depends on. It is a real, if small, obligation on
  anything the suite is handed, and naming it is better than pretending the
  property is free to observe.
- For `MemoryWriter`: with the injected `MemoryPolicy` suspending inside
  `decide`, mutate the caller-held `proposal.proposed`, then assert the ruling,
  the conflict set it was derived from, and the record written all describe one
  version of the proposal. A writer that retires beliefs contradicting content it
  did not store fails this; today's `MemoryIngestor` does.

  **This one needs no new hook**, and the asymmetry with `MemoryStore` above is
  worth stating rather than leaving as an inconsistency. `MemoryWriter`'s suite
  already builds its subject through `make_writer`, a factory the suite hands
  *its own* store and policy to — a shape forced on it because a writer hides
  both (ADR-0028 §4). So the suite can inject a `MemoryPolicy` that suspends
  inside `decide` and every conforming writer must reach it; the existing
  `test_conflicts_are_resolved_before_the_policy_is_asked` already depends on
  that. The lever is general here because the collaborator is on the *suite's*
  side of the seam, and it is not general for `MemoryStore` because no
  collaborator is.

  It needs no position clause either, for the same reason: `decide`'s position is
  fixed by the contract rather than chosen by the implementer. `ingest` resolves
  conflicts itself and rules on them, so a suspension inside `decide` necessarily
  falls after the conflict read and before the write — which is the window the
  case needs. That ordering is not an assumption about `MemoryIngestor`; it is
  what the suite case named above already enforces on every conforming writer.

The existing post-call case stays. It tests a real and different property —
that the store does not alias the caller's object into its own state — and
retiring it would lose that.

Test *design* beyond this minimum is the implementation lane's: how the
suspension is coordinated, what the fakes stand in for.

### 4. What the implementation lane does **not** do

`Planner` and `PlanStore` are **bound and unenforced**, not exempt. The clause is
at module level, so it binds them the day it lands; §3 defers their conformance
cases and their two verified fixes to issue #367, a `planning` lane. This is the
same distinction ADR-0060 §5 draws for `Embedder` and `ModelProvider`, and for
the same reason: one subsystem per change, and `planning` is not `memory`.

`MemoryPolicy`, `ModelProvider`, `FeedbackProcessor` and `Embedder` are bound
and already satisfied, so they gain no cases and no issue — but for three
different reasons, which is worth separating rather than lumping.
`DefaultMemoryPolicy.decide` and `LearningLoop.process` contain no `await` at
all, so the rule is vacuous for them. `PydanticAIProvider.complete` converts the
conversation with `_to_model_messages(messages)` before its first await and
never reads `messages` again, and `FastEmbedEmbedder.embed` materialises
`list(texts)` on its first line — both *discharge* the rule rather than escape
it. `MemoryPolicy` is the one to watch: ADR-0028 makes it an injected seam, and
a model-backed policy would give it the widest suspension window in the write
path overnight — while conforming, since nothing about it would have to change
except that the clause would start to bite.

The objection ADR-0060 §5 answers applies here unchanged and is not re-argued:
`CONTRIBUTING.md`'s "extend the suite in the same change" governs a Protocol
whose own shape moved, and no Protocol's surface moves here — not a method, not
a signature, not an exchanged type. A contract is what is written; a suite
samples it.

### 5. What this does not cover

**The reverse direction: a method mutating its caller's argument.** Nothing in
the tree does — every transformation goes through `model_copy` — and forbidding
it is a real obligation, but it is a *different* one and #348 does not ask it.
Not decided here.

**What a method hands *back*.** `MemoryStore.get` returns a deep copy so a
caller mutating the result cannot reach stored state; that is established
behaviour, already covered by the second half of the existing isolation case,
and this clause does not restate it.

**Cancellation.** ADR-0060, and a different axis (§"This is not ADR-0060's
axis").

### Rejected

- **No — leave it a `SqliteMemoryStore` behaviour.** The strongest form of this
  is: the gap is latent, and contract text nothing enforces is decoration. It
  fails on the facts. The gap is latent only in `MemoryStore`; `MemoryWriter`
  and `Planner` have live instances (#366, #367). And the *enforcement* half of
  the objection is backwards here — there is already a conformance case that
  looks like it enforces this and does not, so the status quo is not "unenforced"
  but "falsely certified", which is the one thing `core/protocols.py` exists to
  prevent.
- **Freeze the types instead** — make `MemoryRecord`, `MemoryUpdateProposal`,
  `Goal`, `CurrentContext` and `Message` `frozen=True`, so there is no mutation
  to observe. Rejected on sufficiency before size: `frozen` stops field
  reassignment, not mutation of what a field points at, so it would have to be
  deep and total to close anything — and `MemoryWrite`, frozen today around a
  mutable `MemoryRecord`, is the counter-example already in the file. It also
  does nothing for the `Sequence` arguments, where the container itself is the
  caller's and mutable whatever its elements are. A rule about *when* an input is
  observed is orthogonal to whether it can change, and would still be needed.
  Deep-freezing `core`'s mutable models may well be worth doing; it is a large
  `core/types.py` change with its own blast radius and needs its own ADR, not a
  paragraph in this one.
- **A per-Protocol clause on `MemoryStore` and `MemoryWriter`.** §2 — the survey
  refutes the scope, and the four existing local derivations are the paraphrase
  failure mode already happening.
- **A shared snapshot helper in `core`.** Rejected for exactly ADR-0060's
  reason: it would make every subsystem depend on one *mechanism* instead of on
  the *obligation*, and there are at least three valid mechanisms (§1).

## Consequences

- **A new backend has something to conform to, and a suite that fails if it does
  not.** The #286 tear becomes something the gate catches on a second awaiting
  writer rather than something that writer's author rediscovers — which is what
  ADR-0056 said would be needed "if a second awaiting writer appears". One has:
  `MemoryIngestor` is not a store, but it is a writer that reads its input across
  two awaits.
- **The existing `MemoryStore` isolation case is revealed as partial, and is
  kept.** It tests non-aliasing, which is real. What changes is that it is no
  longer the only caller-mutation case, so it can no longer be mistaken for
  coverage of the mid-flight window.
- **`core/protocols.py`'s module docstring will carry two standing clauses.**
  ADR-0060's cancellation rule is being implemented concurrently and is not yet
  merged; this ADR does not assume its exact wording. The implementation lane
  should place the two clauses together, in the order they were ratified, and
  match whatever form ADR-0060's landed in rather than reformatting it. If
  ADR-0060's implementation has not merged when this one starts, the clause lands
  on its own and the second is inserted alongside it later — the two are
  independent text.
- **Four ADRs are retrospectively grounded and none of them change.** ADR-0046
  §3, ADR-0056 and ADR-0045 §4 stand exactly as ratified; their snapshots stop
  being three local judgement calls and become one contract honoured three times.
- **Two `planning` defects are now contract violations rather than curiosities**
  (#367). They were reachable before this ADR and nothing about them changes
  today; what changes is that fixing them is discharging an obligation rather
  than a matter of taste.
- **A cost, stated plainly.** Two conformance suites gain a case that needs a
  collaborator to suspend on demand, which is more machinery than a post-call
  assertion. That machinery is the enforcement; the cheap version of this case is
  the one that already shipped and certified the bug.
- **Revisit** if `core`'s exchanged types are deep-frozen — the clause would
  survive for the `Sequence` arguments but its scope would shrink sharply — or if
  a seam appears whose argument is genuinely too large to snapshot, where
  "read it once" and "copy it" stop being interchangeable in practice.

## Amendment (2026-07-25): §4's `ModelProvider` row was false

**What §4 claimed.** That "`MemoryPolicy`, `ModelProvider`, `FeedbackProcessor`
and `Embedder` are bound and already satisfied, so they gain no cases and no
issue", resting for `ModelProvider` on one sentence about one implementation:
`PydanticAIProvider.complete` "converts the conversation with
`_to_model_messages(messages)` before its first await and never reads `messages`
again".

**Why it was wrong.** That sentence is true and stays true —
`src/ai_assistant/models/provider.py:386` renders the history and the first
await is at `:389`, with no later read of `messages`. The error is the *scope* of
the survey behind it: it took one implementation of the seam for the seam.
`models/` holds three `ModelProvider`s, and the other two are wrappers that hand
the caller's `Sequence` to a collaborator **after** a previous await has
returned. Verified against the source, at the line numbers they carried when
this amendment was written:

- `RetryingProvider.complete` (`src/ai_assistant/models/retry.py:252-259`) loops
  `while True` and passes the caller's `messages` to `self._call_inner` on every
  attempt, i.e. after the previous attempt's `await` returned.
- `RoutingProvider.complete` (`src/ai_assistant/models/routing.py:239-247`)
  passes the caller's `messages` to each route's provider in turn, after the
  previous route's `await` has failed.

The Context table above had the seam right — `ModelProvider.complete` is listed
there as taking a mutable `Sequence[Message]` — so the survey held the question
and mis-answered it. The mechanism is the one §2's "Enumeration has already
failed here once" warns about, one level down: an enumeration that stops at the
first implementation it finds.

**What is true instead.** `ModelProvider` was **bound and violated**, in two
implementations, from the moment the clause landed — §4's `Planner`/`PlanStore`
category, not its "already satisfied" one. A caller appending a `Message` while
attempt 1 (or route 1) was suspended made the next attempt answer a different
conversation, and the single `Message` returned was attributed to one
`complete`. The other three rows survive re-checking: `DefaultMemoryPolicy.decide`
and `LearningLoop.process` still contain no `await`, `FastEmbedEmbedder.embed`
still opens with `list(texts)`, `HashingEmbedder.embed` has no `await`, and
`FakeModelProvider.complete` — the only `ModelProvider` outside `models/` — has
none either.

**What changed as a result.** Issue #380 fixed both wrappers, each by
snapshotting the conversation on `complete`'s first executed line — the
container *and* its elements (`[m.model_copy(deep=True) for m in messages]`).
Copying only the container is not enough, and the reason is worth recording
because the first cut of the fix did exactly that: `Message` is a non-frozen
model, so a turn's `content` or `role` can be rewritten in place without the
list changing, and "the inner provider takes its own observation" does not
discharge the wrapper — it only means each attempt observes a *different*
version, which is the desync this ADR's Context already describes one level up
from a store that snapshots correctly. `role` makes it concrete: flipped to
`ASSISTANT` between two attempts it converts a retryable transient failure into
a non-retryable malformed-argument `ModelError` (ADR-0066 §1) about a history
that was well-formed when the call began — and under `RoutingProvider` that
error is non-routable, so it truncates the remaining fallback order.

Both fixes are pinned by mid-flight regression cases under `tests/models/`,
parametrised over an appended turn and a rewritten one. The caller's
conversation is mutated from inside the inner provider's suspension, not after
the call returns, for the reason §"The suite already appears to cover this, and
does not" gives.

**§3 is unchanged.** Enforcement stays scoped to `MemoryStore` and
`MemoryWriter`; `ModelProvider`'s new cases are `models`-local and the shared
`ModelProvider` conformance suite gains nothing. Widening §3 to a third seam
would be a change to what every implementation of that Protocol owes, and needs
its own ADR rather than a paragraph here. What this amendment corrects is a
false premise, not a scope.
