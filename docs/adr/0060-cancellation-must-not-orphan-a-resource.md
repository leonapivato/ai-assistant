# 60. Cancellation must not orphan a resource a seam acquired

- Status: Proposed — to be flipped to `Accepted` on ratification, at merge
- Date: 2026-07-24
- **This is a contract change.** It adds a standing clause to
  `core/protocols.py` that binds every Protocol, and it extends the shared
  conformance suites and canonical fakes of four of them. Golden rule 5 therefore
  applies: this ADR ships as **its own PR, ratified ahead of any
  implementation** (ADR-0015 §5). It is reviewed while still `Proposed`, so a
  finding can still change the decision, and flipped to `Accepted` on merge —
  `CONTRIBUTING.md`, "Contract ADRs land before their implementation". This PR
  is docs-only; the implementation is a separate lane, and until it lands the
  clause is a decision on record and not yet text in `protocols.py`.
- Refs: ADR-0029 §4 (the one cancellation contract we already have), ADR-0054,
  ADR-0057, ADR-0033, ADR-0042 §2, ADR-0056 (adjacent, and deliberately not
  covered — see "What this does not cover").
- Source: `docs/review/architecture-validation-2026-07-24.md`, claim C1, verdict
  ASPIRATIONAL.

## Context

The whole of the project's stated concurrency contract is two sentences in
`CLAUDE.md`:

> I/O-bound methods are `async`. The system composes on one event loop.

That is a scheduling fact. It says nothing about what a caller may assume when
it cancels a call, and nothing about what an implementation owes when it is
cancelled mid-flight. Cancellation safety has instead been derived from first
principles, independently, once per subsystem, each time after a bug:

- **ADR-0054** (`permissions`, `memory`, `planning`) — `async with self._lock:
  await asyncio.to_thread(...)` releases the lock on `CancelledError` while the
  worker thread is still running SQL on the shared connection, so a second
  caller reuses a connection that is still in use. Fixed with a
  `_run_to_completion` helper **duplicated verbatim in all three store
  modules**, because the ADR ruled out a shared home: "a shared home would have
  to be `core` … this change deliberately touches no `core`."
- **ADR-0057** (`context`) — `AssemblingContextProvider.assemble()` awaited a
  bare `asyncio.gather`, which does not yield a cancellation until every child
  finishes, so a source that suppresses `CancelledError` swallowed the caller's
  cancellation whole. Fixed by observing the sources with `asyncio.wait` and
  routing the caller's cancellation through ADR-0033's bounded drain.
- **ADR-0042 §2** (`orchestration`) — the engine façade "must not `close()` an
  owned resource while any underlying operation it started might still touch
  it", and had to state that generally because "the race has more than one
  entry". It ends with the finding in one line: "**Nothing below the façade
  enforces this.**"
- **`models/retry.py`** — a fourth derivation, in prose comments rather than an
  ADR: `_call_inner` distinguishes a provider's own `TimeoutError` from our
  expired deadline by *where* it is caught, and `complete` asks
  `deadline.expired()` because "a provider that swallows that `CancelledError`
  can still return normally". None of it traceable to a stated
  `ModelProvider.complete` guarantee — `protocols.py:64-80` says nothing about
  cancellation.

Every one of those fixes is correct. That four subsystems reached the same class
of conclusion separately, and that three of the ADRs open with the same
disclaimer — "Not a contract change … touches no Protocol" — is the finding. The
reasoning was right and it had nowhere to live.

**One Protocol does state a cancellation contract, and it is the one that
holds.** `ToolInvoker.invoke` (`core/protocols.py:606-684`) says what
`BaseException` does, what happens on expiry, and carries an explicit
`Raises: CancelledError` clause. The enforcement asymmetry follows the text
exactly:

| conformance suite | lines matching `cancel` |
| --- | --- |
| `tests/tools/tool_invoker_contract.py` | 39 |
| `tests/memory/memory_store_contract.py` | 0 |
| `tests/permissions/audit_trail_contract.py` | 0 |
| `tests/context/context_provider_contract.py` | 0 |
| `tests/planning/plan_store_contract.py` | 1 — the phrase "Cancel-then-delete" in a docstring, about a *step* transition, not about `asyncio` |

The canonical fakes split the same way: `testing/invoker.py` is the only fake in
`ai_assistant.testing` that mentions `CancelledError` at all, tracking
`Task.cancelling()` deltas because its Protocol demands it. `FakeMemoryStore`,
`FakePlanStore`, `FakeAuditTrail` and `FakeContextProvider` model no cancellation
behaviour, because nothing requires them to.

So the ADR-0054 fix is pinned only by implementation-specific tests. A fourth
`MemoryStore` or `AuditTrail` backend can reintroduce exactly that bug, pass the
shared conformance suite, and the suite's passing is the false confidence — the
one thing `core/protocols.py` exists to prevent.

The question this records: **what does a caller of any Protocol method get to
assume when it cancels the call, and what does the implementation owe in
return.**

## Decision

### 1. One rule, stated once, at module level

We will state a single standing obligation in `core/protocols.py`'s module
docstring, binding on every Protocol in the file:

> **A method that acquires a resource must not orphan it under cancellation.**
> If a method acquires anything whose safety outlives the coroutine — a
> connection, a lock, a spawned task, a file handle, a transaction — then at the
> moment `CancelledError` leaves that method, every such resource is either
> released, or still held exclusively by work the method started and can observe
> finishing. Never released while that work is still using it; never left held
> with nothing running that will release it.
>
> **A cancellation delivered from outside the call is delivered onward, never
> absorbed.** A method may defer delivery while it makes its resources safe, but
> it re-raises; it never converts such a cancellation into a return value, and
> never lets a collaborator's suppressed cancellation stand in for its own.
> Where delivery is deferred, the wait is on something the implementation can
> observe completing, and the deferral is bounded or documented as unbounded.
>
> *From outside* is load-bearing. A cancellation a method **issues itself**, to
> enforce a deadline it owns, is its own control flow and may be classified into
> a return value — that is exactly what `ToolInvoker.invoke` does on expiry
> (ADR-0029 §4), and what its `Raises: CancelledError` clause distinguishes when
> it says the seam does not convert a task "cancelled from outside". The
> resource clause above is unconditional and binds both cases; only the
> propagation clause turns on provenance.
>
> **A cancelled call's effect is indeterminate to the caller.** A cancelled
> write may or may not have committed. The caller may assume neither, and in
> particular may not assume the write did not land.
>
> The rule is cooperative and is stated in the weaker, true form: no seam can
> stop work that declines to be cancelled. What the rule buys is that the
> *resource* is safe and the cancellation *arrives*, not that the work stops.

The three clauses are one rule seen from three sides, and each is already law
somewhere in the tree — the first is ADR-0054's invariant, the second is
ADR-0057's, the third is ADR-0054's "a committed cancelled write stays
committed" consequence read from the caller's end. What is new is that they are
written where an implementer of a *new* backend will find them.

The third clause is worth its own sentence precisely because ADR-0054 makes the
naive assumption wrong. Its helper runs the worker to completion before
re-raising, so a write cancelled after the worker reached `COMMIT` **is** durably
written. "I cancelled it, so it did not happen" is a live source of bugs today,
not a hypothetical one.

### 2. No filler clauses

We will **not** write a cancellation paragraph on every Protocol. `Planner`,
`MemoryPolicy`, `FeedbackProcessor` and `ToolRegistry` acquire nothing that
outlives their coroutine; the rule is vacuous for them **by construction**, and
saying so seam by seam is how a contract file becomes unread. A rule that mostly
says "nothing to do here" trains readers to skip it, and then it is not there
when it bites.

Vacuous is a claim about the seam, so it is made only where it is checkable.
`Embedder` is **not** on that list — `FastEmbedEmbedder.embed` hands
`_embed_sync` to `asyncio.to_thread`, and a cancelled `embed()` abandons a
worker thread that keeps running (§5).

The four Protocols whose conformance suites gain cancellation cases (§3) each
carry a **one-sentence pointer** to the module clause — not a restatement. A
Protocol whose suite tests an obligation should say where that obligation is
written; divergent local paraphrases of one rule are the failure mode, so the
pointer must point and not re-say.

### 3. Enforcement is scoped to the four resource-owning Protocols

The shared conformance suites and canonical fakes for **`MemoryStore`,
`AuditTrail`, `ContextProvider` and `PlanStore`** gain cancellation cases.
`CONTRIBUTING.md` requires it — "the triad is what a Protocol *change* is
measured against too — extend the suite in the same change, so the new
obligation is enforced rather than assumed."

Those four and not others because each has a production implementation that
already owns the resource the rule is about: `SqliteMemoryStore`,
`SqliteAuditTrail` and `SqlitePlanStore` each serialise one `sqlite3` connection
behind an `asyncio.Lock` (the ADR-0054 pattern), and `AssemblingContextProvider`
spawns per-source tasks it must drain (ADR-0033/0057). They are exactly the
seams where the rule has already been broken once.

`MemoryWriter` is not on the list: `ingest` holds nothing itself and discharges
its obligation through the store beneath it, so testing it there would test the
store twice.

`FakeToolInvoker`'s `Task.cancelling()`-delta technique is the reference for how
a fake models this without a real resource.

**Each case must establish resource safety, not merely propagation.** Test
*design* is the implementation lane's, but the property is not, because the
weakest reading of §3 is a case that asserts `CancelledError` escapes and
nothing more — and that case passes the **pre-ADR-0054 code**, which raised
`CancelledError` correctly and released the lock anyway. A propagation-only
suite would certify exactly the bug this ADR exists to catch. The minimum each
suite must establish:

- For `MemoryStore`, `AuditTrail` and `PlanStore`: with an operation blocked
  mid-flight, cancelling the awaiting task must not let a **second** call reach
  the resource until the first operation's work has actually finished — and once
  it has, both operations' effects are intact and the store still serves reads.
  It is the second caller that makes it a test of the invariant; a single
  cancelled call in isolation cannot distinguish the fixed code from the broken
  code.
- For `ContextProvider`: with a source that *suppresses* its own cancellation,
  a caller's cancellation of `assemble()` must still surface within the drain
  bound rather than being deferred until that source finishes — **and** the
  straggler it leaves behind must stay observed until it completes. Promptness
  alone is not enough: an implementation that cancels the source, waits out the
  budget, drops its last reference and re-raises passes a promptness-only case
  while orphaning exactly what the rule forbids, since `asyncio` holds only weak
  references to running tasks and a dropped one can be collected mid-flight.
  This is why `AssemblingContextProvider` keeps `_abandoned` as a strong
  reference set and `_forget_abandoned` as a done-callback that consumes the
  late outcome (ADR-0033 §3). A well-behaved source distinguishes neither
  property.

  This one needs a note on how it is observed, because `assemble()` alone does
  not expose it, and the obvious cheap answer is unsound. **Absence of an
  event-loop exception report is not proof of observation:** a straggler that is
  dropped and then *succeeds* reports nothing at all, so a provider that
  abandons its reference and re-raises promptly passes any "nothing was logged"
  assertion. The case is therefore built from a positive signal and a hook:

  1. **Drive the straggler to fail**, and require that the implementation
     retrieved and recorded that late outcome. A failure is the one outcome that
     leaves a trace when it goes unobserved, and recording it is exactly what
     `_forget_abandoned` promises. This catches drop-and-forget.
  2. **Require a documented hook for quiescence** — a way for the suite to await
     the implementation's outstanding abandoned work — because retention against
     mid-flight collection has no positive signal reachable through `assemble()`
     at all. This is a real, if small, obligation on anything the suite is
     handed, and naming it is better than pretending the property is free to
     observe.

  The hook is a requirement of the **conformance suite**, expressed through its
  fixture; it does **not** go on the `ContextProvider` Protocol. A test-only
  affordance on the production seam would buy observability by widening the
  contract every consumer depends on, which is the trade this file exists to
  refuse.

Anything beyond that minimum — how the block is coordinated, what the fakes
stand in for — is the implementation lane's.

### 4. What carries over from `ToolInvoker`, and what does not

`ToolInvoker.invoke` is the model, but it was designed around a seam that owns
its own deadline (ADR-0029 §4), so it does not transfer wholesale.

**Carries over:**

- An **externally delivered** `CancelledError` propagates and is never converted
  into a result — "`BaseException` propagates unchanged … must not be swallowed
  into a result". This is the general rule's second clause, and `invoke`'s own
  split between a task "cancelled from outside" and an expiry it triggers itself
  is where that clause's provenance qualifier comes from.
- The cooperative limit: "what the deadline buys is that the seam stops waiting,
  not that the tool stops working … a tool that suppresses its own cancellation
  can outlive it, and no seam can prevent that". The general rule inherits both
  the limit and the discipline of stating the guarantee in the weaker form.
- Indeterminacy after an interrupted side effect — ADR-0029 §4 reaches ADR-0014
  §4's case "through a deadline rather than through a crash". The third clause
  is the same idea for a seam that raises instead of returning a classification.

**Does not carry over:**

- **The seam owning the deadline.** `invoke` takes a required keyword-only
  `timeout` and carries an `ASYNC109` waiver, because ADR-0029 §4's reason is
  specific: a caller's `asyncio.wait_for` "cancels the invoker mid-await, so the
  invoker never reaches the code that classifies the outcome", and classification
  is the only form in which `INDETERMINATE` can be reported at all. A store
  classifies nothing, so an outer cancellation destroys nothing; there is no
  ambiguity to lose. **We will not add a `timeout` parameter to any store
  method.** The caller keeps its own deadline — the store's obligation is to
  *honour* it, which is precisely ADR-0057's property.
- **The `FAILED`-vs-`INDETERMINATE` classification rule.** It reads
  `side_effecting` and `idempotency` off the registry's `ToolDefinition`; no
  other seam has that metadata or a result type to put the answer in.
- **The `CANCELLED` and `TIMED_OUT` failure kinds.** `ToolFailure` vocabulary,
  and `TIMED_OUT` is reserved to a seam that owns a deadline (ADR-0029 §4,
  as amended by ADR-0032).

### 5. What this does not cover

**ADR-0056's snapshot obligation is a different axis and is not folded in.**
`SqliteMemoryStore.add`'s torn write is caused by a *caller mutating its own
record while the coroutine is suspended* — input ownership across a suspension
point, with no cancellation anywhere in it. The validation source groups it with
ADR-0054 and ADR-0057 as "the same class of cancellation bug"; on reading the
three, that grouping does not hold. What ADR-0056 shares with them is only the
root cause one level up — reasoning about what may happen at an `await` was not
in any contract — and ADR-0056 explicitly leaves universalising its rule to a
separate lane. This ADR does not take that lane. Promoting call-time-snapshot to
a universal `MemoryWriter`/`MemoryStore` obligation remains open, tracked as
issue #348.

**`ModelProvider` and `Embedder` are bound by the rule but gain no conformance
cases here.** The rule is stated at module level, so it binds them the moment it
lands; they are deferred on *enforcement*, not exempted from the obligation.
That distinction is the whole point of stating the rule generally — scoping the
**rule** to the four suites, rather than only its enforcement, would leave a
fifth resource-owning seam unbound, which is the hole this ADR exists to close.

The objection to answer is `CONTRIBUTING.md`'s "the triad is what a Protocol
*change* is measured against too — extend the suite in the same change, so the
new obligation is enforced rather than assumed", read as: a clause that binds
thirteen Protocols owes thirteen suite extensions. We do not read it that way,
for two reasons. First, **no Protocol's surface changes here** — not a method,
not a signature, not an exchanged type. That rule governs a Protocol whose own
shape moved, and its remedy (extend *its* suite) has no referent for a clause
that adds no member to anything. Second, **binding does not imply fully
enforceable in this codebase, and never has**: ADR-0029 §4's cooperative limit —
"no seam can prevent" a callable that suppresses its own cancellation — is
binding contract text that no conformance suite can enforce, because the thing
it rules out is undetectable from outside. A contract is what is written; a
suite *samples* it. Insisting the two be coextensive would either shrink every
contract to what a test can catch, or forbid stating a true general rule at all.

That said, the enforcement gap is **incompleteness, not safety**. `Embedder` is
a live case (below), and issue #347 is a debt against this contract rather than a
nice-to-have — this rule is not fully enforced until it closes. Which lane closes
it is a scoping call for whoever sequences the work, not a judgement this ADR
makes.

The deferral is a judgement about what a case would currently buy, and it is
weakest for `Embedder`, so state its position exactly. `FastEmbedEmbedder.embed`
awaits `asyncio.to_thread(self._embed_sync, documents)`, so a cancelled `embed()`
does abandon a running worker — the rule is live for it, not vacuous. What it
does **not** have is the ADR-0054 failure. `_load_lock` serialises the *lazy
load* only — `_embed_sync` calls `_loaded()`, which returns the model and
releases the lock, and the inference in `_collected` then runs **unlocked and
concurrent**, resting on the backend's documented thread-safety rather than on
mutual exclusion. So there is no event-loop-held lock to release early: the lock
is a `threading.Lock` taken and dropped inside the worker, where an unwinding
`CancelledError` on the event loop cannot reach it, and the resource a second
caller shares is one the backend promises is safe to share. The orphaned worker
wastes CPU and finishes; it corrupts nothing. So the
gap is real but currently benign, which is a reason to file it rather than a
reason to call it closed — and the moment an `Embedder` acquires something the
event loop releases, it is the ADR-0054 bug again.

`ModelProvider` is further out: its production implementations delegate resource
ownership to `pydantic-ai` and its HTTP client rather than owning a connection we
release, and `models/retry.py`'s derivation is about *deadline attribution* —
telling a provider's `TimeoutError` from ours — which the rule does not speak to.

Extending both suites is a real follow-up, filed as issue #347 rather than
folded in.

**Nothing is promoted into `core` as code.** A shared home for ADR-0054's
`_run_to_completion` is the obvious next thought and we reject it: `core` holds
contracts, types, config and errors, and a concurrency utility there would make
every subsystem depend on one *mechanism* instead of on the *obligation*.
ADR-0054 weighed at least two valid mechanisms (a shield, a serial worker), and a
future backend on a real async driver — with no worker thread to outlive
anything — needs neither. The contract states the obligation; the mechanism stays
the implementation's. The cost is that ADR-0054's verbatim triplication stands,
which is a real and accepted cost, now at least justified by a rule rather than
only by a boundary.

### Rejected

- **Leave it as `CLAUDE.md` prose.** Prose without a conformance suite is what
  produced 39-versus-0. A rule nothing runs is a rule a new backend passes
  without honouring.
- **A cancellation clause on every Protocol method.** §2.
- **Mirror `ToolInvoker` wholesale, giving stores a `timeout`.** §4 — a large
  contract change (every method on four Protocols) buying a guarantee the seam
  has no way to report.

## Consequences

- **A new durable backend now has a written contract to conform to**, and a
  shared suite that fails if it does not. The ADR-0054 bug becomes something the
  gate catches on a fourth store rather than something the fourth store's author
  rediscovers.
- **Four suites and four canonical fakes get more complex.** The fakes must model
  cancellation without a real resource — `FakeToolInvoker` shows the shape, and
  it is today the only fake in `ai_assistant.testing` that mentions
  `CancelledError` at all. That cost is the enforcement; a fake that models
  nothing is what §3 exists to end.
- **The three prior ADRs are retrospectively grounded and none of them change.**
  ADR-0054, ADR-0057 and ADR-0033 stand exactly as ratified; their reasoning is
  now the contract's, not each subsystem's private derivation. ADR-0042 §2's
  "nothing below the façade enforces this" becomes false once the implementation
  lands — the façade's ordering obligation is unchanged, but it is no longer the
  only thing holding the line.
- **Vacuous where it should be.** `Planner`, `MemoryPolicy`,
  `FeedbackProcessor` and `ToolRegistry` are untouched and gain no text.
  `Embedder` is bound and unenforced rather than vacuous (§5) — a distinction
  the first draft of this ADR got wrong, and the reason §2 now states vacuity
  only where it is checkable.
- **Two things stay open, on purpose.** ADR-0056's universal snapshot obligation
  (issue #348) and `ModelProvider`/`Embedder` conformance (issue #347), each
  filed rather than absorbed here. Both are deferrals of *enforcement*; neither
  is a seam the rule fails to bind.
- **Revisit** if a seam grows a genuinely unbounded synchronous operation — the
  bounded-deferral clause would then need a numeric ceiling rather than "wait for
  the work you started" — or if a store arrives on a native async driver, where
  the rule holds but every mechanism behind it changes.
