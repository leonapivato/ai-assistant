# 219. A `MemoryStore` write is made conditional on a store-authored revision, and a stale one is refused

- Status: Proposed
- Date: 2026-08-29
- **This is a contract change on `MemoryStore`.** It adds one field to
  `MemoryBase` and one to `MemoryWrite` in `core/types.py`, one member to
  `MemoryWriteMode`, and one error to `core/errors.py`. **No signature in
  `core/protocols.py` moves** — `write_atomic` keeps the parameters and the return
  type ADR-0046 §1 gave it — but the **behavioural contract of the `MemoryStore`
  Protocol** does: every implementation must honour a mode it did not have to
  honour before, and must author a field it did not have to author before. Golden
  rule 5 reaches a change to what an implementation must do and not only to how it
  is called (ADR-0217 §7's reading of the same rule, applied here to a different
  Protocol), so this ADR is its own PR, ratified and merged before anything
  implements against it, and it owes **both** lenses — adversarial and
  architecture (ADR-0015 §1). It adds **no new Protocol**, no member to any
  Protocol, no `Settings` field, no `RoutableOperation` member, no member of the
  promoted `AssistantEngine` surface, and — §6 — it does **not** move
  `PROTOCOL_VERSION`.
- **This ADR supersedes nothing and amends nothing.** §9 applies ADR-0070 §1's
  test to ADR-0046, ADR-0045, ADR-0108, ADR-0028 and ADR-0217 clause by clause and
  finds every sentence of each still true, so no header-only record is owed on any
  of them and none is written.
- **Durability clause.** Every quotation below — from an ADR, from
  `core/types.py`, from `core/errors.py`, from `memory/`, or from an issue — is of
  its text as it stood at this ADR's base, `1331dae3`, and not of its text on any
  later day. ADR-0217 is quoted from PR #1811's branch at `647c1e95`, which is not
  yet on `main`; where that text moves before it merges, this ADR is read against
  the text quoted here and that ADR's own record says what moved. This is
  ADR-0143's clause, taken for its reason.

## Context

### The window, and why nothing has closed it

`MemoryIngestor.ingest` is a read–modify–write: it searches for conflicts,
snapshots a target, folds a proposal into that snapshot, and writes the result
back at the target's id. Its own docstring states the race in terms — "Interleaved,
two ingests both snapshot the same target before either writes, and the second
``add`` silently discards the first — with both callers handed a healthy result."
That is issue #248.

Issue #262 serialised the sequence on an `asyncio.Lock` held by the ingestor, and
`ingest`'s docstring is explicit about what that does not cover:

- "**Only this ingestor.** Two ``MemoryIngestor`` instances over one store hold two
  different locks and race exactly as before."
- "**Only this process.** An in-process lock says nothing about two processes
  sharing a store file. Closing that needs a compare-and-swap on the store itself —
  a ``MemoryStore`` contract change, tracked as issue #104 with issue #248."

ADR-0046 designed the atomic write-set and ruled, in §5, that it is not that
compare-and-swap: "It makes a **write-set** atomic. The conflict `search` that
produced the records happened *before* the batch is assembled and is not inside
it, so a concurrent writer that changed `T` between the read and the
`write_atomic` is still lost. Atomic-write-set is orthogonal to read-modify-write
isolation." It then re-scoped the issue and named the gate:

> #248 stays open, re-scoped from "closed by #104" to "a compare-and-swap
> extension of `write_atomic` (a `MemoryRecord` concurrency token plus an
> `IF_UNCHANGED` mode), gated on a consumer that runs two writers on one store."

and

> If a composition ever does run two writers on one store, closing #248 is that
> lane's trigger — either a store CAS (the extension below) or a tested
> single-writer invariant — not a claim this ADR can make for it now.

### The consumer now exists, and it took the first arm

ADR-0217 §7 adds `AssistantEngine.guard` and `AssistantEngine.unguard` — acts that
read a record, decide a precedence from the placement it carries, and write. That
section rules that they fire ADR-0046 §5's trigger and that the second arm is
unavailable: "#262's serialisation is an `asyncio.Lock` 'held by that one ingestor'
and is reachable through no declared seam; and neither `MemoryStore` nor
`MemoryWriter` offers a conditional or a placement-only write. An act is therefore
**a second writer on one store**". It then gates itself:

> **No implementation of §7's two acts lands on a tree whose `MemoryStore` cannot
> make the act's write conditional on the record being unchanged since the act read
> it.**

and defers the design here, by name: "#248 owns it — 'a `MemoryRecord` concurrency
token plus an `IF_UNCHANGED` mode' — and its ADR decides the member, the token and
the conflict's error" (§12).

**What is at risk in the new consumer is not what was at risk in the old one.**
ADR-0217 §7 states it: "What is at risk here is not a lost content merge but a lost
**narrowing**: a derivation landing between an act's read and its write,
overwritten by a stale `unguard`, is exactly the laundering §3's precedence refuses
whenever it can see it." A lost merge is a defect; a lost narrowing is a
disclosure.

### The one force that argued against it, weighed against what has happened since

ADR-0046 §5's reason for not building the token was not that it is the wrong
shape — §Alternatives calls it "the `PlanStore.commit_transition` shape" and says
it "would close #248's residual — the multi-ingestor in-process race and the
cross-process one alike". It was cost, and consumer:

> Adding one — a `MemoryWriteMode.IF_UNCHANGED` or an `expected_version` à la
> `commit_transition` — would need a concurrency token on `MemoryRecord`.
> `MemoryRecord` has no version field, and ADR-0045 weighed and *avoided* the blast
> radius of adding envelope fields ("construction sites across `memory`,
> `learning`, `orchestration`, the two canonical fakes, and every test").

The consumer half is now discharged by ADR-0217 §7. The blast-radius half is
answered by ADR-0045's own record, and it is answered against the way ADR-0046 §5
reads it. The quoted phrase is from ADR-0045's *Context*, where it is listed among
"The forces against"; ADR-0045 then added an envelope field anyway and recorded in
its Consequences what the force actually cost:

> `MemoryBase` gains a field (additive, defaulted, so no construction site breaks)

Three further envelope fields have landed on the same footing since — `about_person`
(ADR-0100 §2), `topics` (ADR-0213 §1) and `placement` (ADR-0217 §1) — and none of
them touched a construction site, because a defaulted additive field is not
construction-site work. So the force ADR-0046 §5 cites is real about a *required*
envelope field and inert about a defaulted one, and the corpus has four
demonstrations of the difference.

**What is not lifted is the other bar.** ADR-0046 §5 also rules out reusing an
existing field: "Overloading `Provenance.last_updated` as the token is barred too:
ADR-0045 §3 keeps it 'renaming nothing and changing no value.'" §1 below keeps that
bar and adds an independent reason for it.

### What the corpus already has for exactly this problem

`PlanStore.commit_transition` is a compare-and-swap on a durable store, ratified in
ADR-0014 §5 and shipped. `ExecutionState`'s docstring states the property:

> ``version`` is the optimistic-concurrency token: a write succeeds only if the
> stored version still matches the one the writer read, so two workers cannot both
> claim the same step and run a non-idempotent tool twice (ADR-0014 §5).

and the expectation rides the *command*, not the state: `StepTransition` carries
`expected_version: int = Field(ge=0, description="Version the caller computed this
against.")`, and a lost race raises `StaleExecutionError`, "a distinct, catchable,
recoverable-and-retryable failure under the general store error" in ADR-0046 §4's
own words about it. This ADR takes that shape rather than inventing one.

`SqliteMemoryStore` can already carry it. `_transaction`'s docstring: "``IMMEDIATE``
takes the write lock up front, so a read-then-write mutation cannot interleave with
another writer's — which is how this store's rowid lookups hold **across processes**
and not merely across coroutines on one loop." The compare and the write land inside
that transaction, which is why the cross-process half of #248's residual closes
rather than merely narrowing.

## Decision

### 1. The token is a store-authored `revision` on `MemoryBase`

> **Normative.** `MemoryBase` gains one field, `revision: int`, defaulting to `0`
> and constrained `ge=0`. It is the record's concurrency token: the stamp the store
> issued for the write that stored this row.

> **Normative.** The field is **store-authored**. A store assigns it, and a
> submitted record's value is never persisted: `add` and every `write_atomic`
> element discard whatever `revision` the record they are handed carries. No
> producer, applier, policy, writer or client sets it, and no implementation reads a
> submitted `revision` for any purpose other than nothing.

> **Normative.** The assignment rule is one clause and it is **never-reissued
> within the store**: every write that stores a row — `add` and each of
> `write_atomic`'s modes alike, on every implementation — stamps it with a value the
> store has never issued before and will never issue again for the life of that
> store, whatever id it is stored at and whatever was stored there previously. A
> store issues from any source that satisfies that; it is not obliged to issue in any
> particular order, and it is not a per-id count.

> **Normative.** `0` is issued by no store and is the field's default, so a record
> no store has stored is distinguishable from every record a store has stored, and no
> caller-constructed default can equal a stored value. Every issued value is
> **positive**.

> **Normative.** **"For the life of that store" is scoped by durability**, in the
> shape ADR-0046 §4 scoped its two atomicity obligations. For a **durable** store it
> is the life of the data the store holds: the issuer's state is persisted beside the
> records and survives a close, a process restart and a crash, so a stamp issued
> before a restart is never issued again after one. For a **non-durable** store it is
> the life of the object, and the obligation is vacuous beyond it — a restart
> destroys every record the store held, so there is nothing left for a stale
> expectation to land on, and requiring more would be a contract term nothing can
> satisfy or test.

> **Normative.** **`clear` destroys records and never the issuer**, on every
> implementation, durable or not. `clear` is a bulk erase of what the store holds; an
> issuer reset by it would reissue every stamp it had already issued, which is the
> ABA hole above arriving through a different door. The same binds any other bulk
> operation a later lane adds: nothing but the destruction of the store itself resets
> an issuer, and a durable store may not reconstruct one from the rows currently
> present.

> **Normative.** Every read that returns a record returns the `revision` the store
> holds for that row: `get`, `get_many`, `search`, `list_beliefs`, `export` and
> `walk_records`. A record a store returns carries a revision that was true of the
> row at the instant the read observed it, and a record no store has stored carries
> the default.

> **Normative.** The operative property, which is what a conditional write is
> decided against, is **inequality and never ordering**: two records carry equal
> revisions only where they are the same stored row, unrewritten, between the two
> reads that observed them. No caller compares two revisions with `<`, infers an
> interval or an age from their difference, reads one as a count of anything, or
> derives from two revisions which of the two writes happened first. That an
> implementation reaches never-reissued by issuing from a monotonic sequence is the
> mechanism, not the promise, and nothing may be built on it.

> **Normative.** **A deleted-and-recreated id is a changed record, and the stamp
> makes it one.** `delete` destroys a row; a row stored again at that id takes a
> fresh stamp the store has never issued, so an `IF_UNCHANGED` expecting the
> destroyed row's stamp is **refused**. This is why the stamp is never-reissued
> rather than a per-id counter, and the case is exactly why: `MemoryStore.delete` is
> unconditional and `add` takes a **producer-owned** id — an external system's
> identifier is that system's idempotency key (ADR-0038 §2a) — so a delete followed
> by an ordinary `add` or `UPSERT` at the same id needs no re-mint and no
> `INSERT_IF_ABSENT`, and a per-id counter that restarted would let a stale write
> land on the replacement. Nothing about this rule obliges a store to retain
> anything of a deleted record: what survives a delete is the store's issuer, which
> holds no record, no id and no content.

**On the envelope, and this is ADR-0045 §2's own placement rule applied rather than
worked around.** §2 put `validity` on `MemoryBase` because "The window is a
lifecycle property of *the record's life in the store*, set operationally by the
applier", and refused `Provenance` because "Putting a store-set lifecycle field on
`Provenance`, whose every other field is set by the *producer* of the belief, would
mix two authorships." A revision is the purest case of the class §2 admits: not
merely store-*set* but store-*authored*, and about the row's life and nothing else.

**A field the machinery authors and the producer does not is already on this
envelope.** `MemoryBase.score` is described `"Relevance score, populated by
retrieval; None when stored."` — a field whose value is supplied by the machinery on
one path and meaningless on the other. `revision` is its mirror image: supplied on
the write path, read on the read path, and never authored by whoever constructed the
record. That a record from `search` carries both a score and a live revision is the
useful consequence: a caller that read through retrieval holds a token it may write
against, with no second read.

**`Provenance.last_updated` is refused on a ground of its own, beyond ADR-0046 §5's
citation.** Two writes inside one clock reading are indistinguishable in it, so an
instant cannot carry the inequality above; and not every write moves it — ADR-0217
§7's `unguard` writes "the instant of the act" into a placement without touching the
belief's revision stamp, so a token read off `last_updated` would report *unchanged*
across exactly the write this ADR exists to catch. The bar ADR-0045 §3 sets is kept,
and it is not the only reason to keep it.

**Not persisted inside the record's payload.** The revision is a property of the row
the store holds, not of the bytes a producer wrote, and an implementation stores it
beside the record rather than inside it. Two things follow, and both are why the
clause is here: an `UPSERT` writing a full replacement — ADR-0046 §3's "an upsert is
a full replacement rather than a merge, rewriting every column and not only the
payload" — cannot carry a stale revision in as part of the payload it replaces; and
a store that already round-trips a record's fields through one serialised blob needs
a column beside it rather than a rewritten blob, which is what makes the migration
mechanical (§10).

### 2. The mode is `IF_UNCHANGED`, and the expectation rides the write, not the record

> **Normative.** `MemoryWriteMode` gains a third member, `IF_UNCHANGED`. An element
> in that mode is applied only where the id names a stored row whose `revision`
> equals the expectation the element carries; otherwise the write is refused under
> §3.

> **Normative.** `MemoryWrite` gains one field, `expected_revision: int | None`,
> defaulting to `None` and constrained `ge=0` where stated. It carries the revision
> of the record the caller read and computed this write against — `StepTransition`'s
> `"Version the caller computed this against."`, for a memory record.

> **Normative.** A model validator on `MemoryWrite` refuses, at construction, an
> element whose `expected_revision` is `None` in `IF_UNCHANGED` mode, and one whose
> `expected_revision` is not `None` in any other mode. The two states are the only
> two, and neither is reachable at write time.

**The expectation is on the element and not read off `write.record.revision`, and
the difference is a silent default.** A caller assembling an `IF_UNCHANGED` write
from a record it read would carry the right value by construction; a caller
assembling one from a record it built — which is what a fold does, and what
ADR-0045 §4's applier does for the correction `P` — would carry the field's default
of `0` and silently expect "the row has never been rewritten". That is a fail-open
expectation on the exact path this mode exists to guard, and the separate field a
validator requires makes it unreachable. §1's value space closes the same case a
second time from the other side — `0` is issued by no store, so an expectation of
`0` matches no stored row and would refuse rather than land — and the two are stated
as two because neither should be the only one: the validator catches the caller's
mistake at construction, where it is diagnosable, rather than at a write that
mysteriously always refuses. It is also the ratified shape: `ExecutionState` carries
`version` and `StepTransition` carries `expected_version`, and the reason they are
two fields is this one.

**`MemoryWrite` is frozen and stays frozen**, for the reason its docstring gives —
"a value that governs whether records are *skipped* must not be reconstructible by
accident from something that happens to be a string" — which now governs a second
field whose absence changes the write's meaning.

**Three modes and not a fourth.** `IF_UNCHANGED` is a conditional **replacement**:
it requires the row present, so it does not overlap `INSERT_IF_ABSENT`, which
requires it absent, or `UPSERT`, which requires nothing. There is no
"insert-or-swap" mode, because no consumer wants one: ADR-0217 §7's acts write a
record they just read, and the ingestor's fold writes a target it just found.

**`add` is untouched and stays unconditional.** ADR-0046 §1 makes `write_atomic` the
batch door and `add` the single-write one; a conditional single write would be a
second spelling of a one-element batch, which ADR-0046 §2 already admits ("A batch
of one is legal and degenerates to a single atomic write"). One door for the
conditional write is what keeps the two doors from disagreeing.

### 3. Refusal: a distinct error, the record named, and nothing committed

> **Normative.** `core/errors.py` gains one error, `MemoryStoreStaleError`,
> subclassing `MemoryStoreError`. It is raised where an `IF_UNCHANGED` element's id
> names a stored row whose `revision` differs from the element's
> `expected_revision`, **and** where its id names no stored row at all. Its message
> names the record id, the expectation, and what the store found — the stored
> revision, or that the id named nothing.

> **Normative.** It does **not** subclass `MemoryStoreConflictError`, and no
> implementation raises `MemoryStoreConflictError` for a stale conditional write.
> The two carry different remedies and a caller branches on them differently.

> **Normative.** A refusal commits nothing, and ADR-0046 §4's all-or-nothing is kept
> whole rather than qualified: one stale element fails the **whole batch**, exactly
> as an `INSERT_IF_ABSENT` collision does, and no record the batch named is added,
> overwritten or removed. `get`, `search` and `export` return what they would have
> returned had the batch not run.

> **Normative.** The comparison and the write are **one indivisible step** inside
> the batch's transaction, and on a durable backend that transaction excludes a
> concurrent writer — including one in another process — for the whole of it.
> A store that read the stored revision, released, and then wrote would reproduce the
> very window this mode closes, one layer down. `SqliteMemoryStore` satisfies this
> with the `BEGIN IMMEDIATE` its `_transaction` already takes.

> **Normative.** The remedy is **re-read and re-decide**, never re-apply. A caller
> that meets this refusal reads the record again and derives its write from the
> value the record now carries; it never resubmits a payload computed over the
> snapshot the store just rejected. Every retry is bounded — a fixed number of
> attempts stated by the caller's own decision — and no implementation loops
> unboundedly.

**A distinct class is earned here, and ADR-0108 §4's test is the reason.** That
section declined a new error for a cross-kind collision because "There is no second
branch for a caller to take, and a subclass with one caller and one branch is
surface with no consumer", and because `MemoryStoreConflictError` was "specifically
wrong here: its documented remedy is 're-mint and retry'". Both halves come out the
other way for this refusal. The second branch exists and is ratified before the
error is: ADR-0217 §7 rules that on a conflict "the act reads it again and applies §3's
precedence to the value it now carries", and that a second conflict aborts — a
caller distinguishing "the record moved, re-read" from "the store is broken". And
`MemoryStoreConflictError`'s remedy is wrong in the same way ADR-0108 §4 found it
wrong: re-minting an id is precisely what a caller must *not* do here, since the id
is the one thing about this write that is right.

**Under `MemoryStoreError`, so nothing downstream gains an error.** ADR-0046 §4's
reason for putting `MemoryStoreConflictError` there holds unchanged — "the writer
boundary already documents `MemoryStoreError` as the only error that crosses the
seam, ADR-0028 §5" — and it is load-bearing for the first consumer: ADR-0217 §7
rules that an act exhausting its retry "raises `MemoryStoreError`, which both
members **already declare** — 'where reading or writing memory failed' — so neither
operation gains an error, and §7's exhaustive `Raises` list is unmoved." That
sentence stays true only while this error is a `MemoryStoreError`, which is why the
subclassing is normative rather than a convention.

**The absent id is the same failure and not a different one.** A row deleted between
the read and the write is a lost update of the starkest kind, and answering it with
a silent no-op, or with a `None` return, would hand the caller the healthy result
ADR-0046 §5 says the old race handed both callers. It is a refusal, under the same
error, with the message saying which of the two it was.

### 4. What `IF_UNCHANGED` inherits, stated so no implementer derives it

> **Normative.** ADR-0108 §4's cross-kind refusal binds `IF_UNCHANGED` exactly as it
> binds `add` and `UPSERT`: where the id names a stored record of a different
> `kind`, the write is refused with `MemoryStoreError` and nothing is committed.
> Order is unobservable — a batch that is both cross-kind and stale is refused
> either way and commits nothing — and an implementation may check in either order.

> **Normative.** "Names a stored row" is **physical presence** in ADR-0046 §3's
> sense, unchanged: an expired or window-closed row is present, so it satisfies
> `IF_UNCHANGED`'s presence requirement and its revision is the one compared. This
> is what lets a window-close be conditional, which is the write ADR-0045 §4's
> applier makes onto a target it read.

> **Normative.** ADR-0046 §3's repeated-id rejection is unchanged and reaches
> `IF_UNCHANGED` elements: a batch naming one id twice is refused as
> `MemoryStoreError` before the transaction opens, whatever modes those two elements
> carry.

ADR-0108 §4 makes the cross-kind rule bind "every upsert-capable door on every
implementation" and argues that stating it only at `add` would be "the same
false-shelter shape one layer up". A third mode that overwrites a stored row is a
third door by that reasoning, so the clause is restated here rather than left to be
inferred — and it costs the shipped store nothing, since `_persist_record` is where
both existing doors already meet it.

### 5. Who uses it: ADR-0217's acts, and the fold that #248 is about

> **Normative.** ADR-0217 §7's `guard` and `unguard` perform their write through
> `IF_UNCHANGED`, on the revision of the record read in the call that writes it.
> That is the gate §7 states — "No implementation of §7's two acts lands on a tree
> whose `MemoryStore` cannot make the act's write conditional on the record being
> unchanged since the act read it" — and this ADR supplies the mode it names and
> nothing about the acts themselves.

> **Normative.** ADR-0217 §7's bound composes with §3 unchanged and this ADR neither
> widens nor narrows it: an act makes its attempt, and on `MemoryStoreStaleError`
> exactly one re-read and one further attempt, and a second refusal propagates. No
> clause here obliges an act to retry more, and none permits it.

> **Normative.** `MemoryIngestor.ingest`'s fold path writes its target with
> `IF_UNCHANGED`, expecting the revision of the record the fold was derived from.
> This is what closes #248 rather than merely enabling it. A `REINFORCE` writes the
> merged record at `decision.target_id` conditionally; a `SUPERSEDE` makes its
> window-close of the retained target conditional and leaves the paired
> `INSERT_IF_ABSENT` of the correction exactly as ADR-0045 §4 and ADR-0046 §2 shape
> it, so the batch stays the two elements those sections describe.

> **Normative.** On refusal the ingestor re-runs its **whole** read–modify–write
> once — conflict detection, the policy's ruling, and the fold — against the store as
> it now stands, and never re-applies a merge computed over the rejected snapshot.
> The bound is two attempts in all, matching ADR-0217 §7's; a second refusal
> propagates as the `MemoryStoreError` it is, and is not converted into a healthy
> `MemoryIngestResult`.

> **Normative.** #262's per-ingestor `asyncio.Lock` is **kept**. It is not made
> redundant by this mode and no lane removes it under this ADR: it is the only thing
> serialising the injected policy's `decide` within one ingestor, and it keeps the
> common case off the retry path entirely. Whether it can be narrowed or dropped is
> a question for a lane that measures it, not a consequence of this decision.

**Why the ingestor is decided here and not deferred.** #248 is an issue about the
fold, and ADR-0046 §5 re-scoped it to this mechanism rather than to a different
defect. An ADR that added the mechanism and left the fold unconditional would leave
#248 exactly as open as it is today, with its own closure depending on a lane nobody
had committed to — and would make the store's new mode surface with one consumer
that is itself unmerged. Deciding it here costs no `core` surface: the fold's write
already goes through `write_atomic`, so the change is which mode two call sites pass
and what they do with a refusal.

**Why the retry is a re-run and not a re-submit.** A fold is not idempotent in the
way ADR-0217's acts are. `guard` and `unguard` write a value that is a function of
the record read, so re-deciding over a re-read record is the whole of their retry;
a merge folds a proposal into a *snapshot*, and re-submitting that merged payload
against a moved target is the lost update wearing a conditional write's clothes.
The re-run also re-asks the policy, which is the only way the ruling stays derived
from the state the write lands on — the property #262's lock buys within one
ingestor, restored across ingestors and across processes.

**What closes, and when.** With the fold conditional, both residuals ADR-0046 §5
named close: two `MemoryIngestor` instances over one store no longer race, because
neither can write over a revision the other moved; and two processes sharing a store
file no longer race, because §3's indivisibility clause holds the compare and the
write inside a transaction that excludes the other process's writer. **#248 closes
when that change lands, not when this ADR merges** — this ADR decides the mechanism,
and §10 orders the changes.

### 6. Scope: the `core` surface, and `PROTOCOL_VERSION` does not move

> **Normative.** The `core` change is exactly: `MemoryBase` gains `revision`;
> `MemoryWrite` gains `expected_revision`; `MemoryWriteMode` gains `IF_UNCHANGED`;
> `core/errors.py` gains `MemoryStoreStaleError`. **`core/protocols.py` gains no
> Protocol and no member**, and no method's signature or return type moves —
> `write_atomic`'s docstring grows the mode and the error, which is a statement of
> the contract it already had a place for. There is no `Settings` field, no
> `ContextFacet`, no `RoutableOperation` member and no member of the promoted
> `AssistantEngine` surface.

> **Normative.** `PROTOCOL_VERSION` does not move for this change.

> **Normative.** The revision is **store-authored and hub-local**: no client, spoke
> or gateway sets one, and no component reads a revision off a wire-received record
> to decide anything. A later decision that gives any client, spoke or gateway a
> rule keyed on a revision **as received over the wire** owes ADR-0124 §9's test
> afresh in its own text and may not cite this section as having answered it.

**ADR-0124 §9's test is applied rather than asserted past**, in the form ADR-0213
§11 applied it to the same envelope. §9's rule is that "`PROTOCOL_VERSION` is bumped
by any change after which a frame a conforming peer at the new version may send
would be refused by a conforming peer at the old version, or would be accepted by it
with a different meaning."

`MemoryRecord` **is** wire-carried: `TurnResult.memories` is
`tuple[MemoryRecord, ...]`, inside `TurnOutcome`. Both directions are checked.

- **A new hub to an old peer.** `MemoryBase` carries
  `model_config = ConfigDict(frozen=True)` and does not set `extra="forbid"`, and
  `revision` has a default, so an older peer decoding a newer hub's record ignores a
  member it does not know. That is ADR-0213 §11's ruling on the same envelope, on a
  change of the same shape.
- **A new peer to an old hub.** The direction does not exist: no `AssistantEngine`
  method takes a `MemoryRecord` or a `MemoryBase` as an argument, and
  `wire/surface.METHODS` is derived from that Protocol. `MemoryUpdateProposal`,
  which does carry a `MemoryRecord`, crosses the `MemoryWriter` seam and not the
  wire.
- **A new peer decoding an old hub's record.** It reads the default `0` on a row
  whose stored revision is higher. Nothing acts on that: a conditional write is a
  `MemoryStore` operation, `MemoryStore` is not the promoted surface, and no client
  holds a store. The clause above keeps it that way rather than assuming it.

**This is the addition case and not ADR-0217 §9's.** That section bumps because a
member is *removed* from a wire-carried type and "its default is *read*" with a
disclosure consequence; it says in terms that "no lane cites this section as
authority for bumping on an addition alone". Nothing is removed here, no field
changes meaning, and the value carries no disclosure. ADR-0181 §3's field, which did
bump, was in ADR-0213 §11's words `required with no default on a model that sets
extra="forbid"` — neither of which is true of this one.

### 7. Conformance: the arms the shared suite gains

> **Normative.** `MemoryStoreContract` — the shared suite every implementation is
> bound to, the two canonical fakes and `SqliteMemoryStore` included — gains an arm
> for each of the following, and an implementation that fails one is
> non-conformant. Each is stated as an observable of the contract, not of a backend.

> **Normative.** **A stale expectation is refused.** Read a record, store a second
> write at its id, then submit an `IF_UNCHANGED` element carrying the first read's
> revision: `MemoryStoreStaleError`, and the stored record is the second write's,
> unchanged.

> **Normative.** **A fresh expectation succeeds.** Read a record and submit an
> `IF_UNCHANGED` element carrying its revision: the write lands, and a subsequent
> read returns the new content with a revision that differs from the one submitted.

> **Normative.** **A refusal commits nothing.** A batch of one stale `IF_UNCHANGED`
> element and one otherwise-valid element writes neither, and every read returns
> what it would have returned had the batch not run — ADR-0046 §4's obligation, over
> the new mode.

> **Normative.** **An absent id is refused.** An `IF_UNCHANGED` element whose id
> names no stored row raises `MemoryStoreStaleError` and writes nothing, including
> where the row was deleted after the caller read it.

> **Normative.** **The revision is store-authored.** A record submitted with a
> non-default `revision` is stored at the revision the assignment rule gives it, and
> a read returns that, not the submitted value.

> **Normative.** **The revision moves on every write path.** A record stored, then
> stored again at the same id through `add`, through `UPSERT`, and through
> `IF_UNCHANGED`, reads back with a different revision after each — the inequality
> §1 promises, asserted on each of the three doors rather than on one.

> **Normative.** **Every record-returning read carries the same revision**, asserted
> over each read by name rather than over an unspecified one: a record stored and
> then rewritten is read back through `get`, `get_many`, `search`, `list_beliefs`,
> `export` and `walk_records`, and all six return the same non-default revision, and
> a conditional write carrying the revision each of them returned lands. The arm is
> parameterised over the six because the failure it exists to catch is per-path: a
> store holding the revision outside the payload it decodes can overlay it correctly
> on one read and return the model default on the five that decode the payload
> directly, and a caller that read through `search` would then meet
> `MemoryStoreStaleError` on a write that is not stale.

> **Normative.** **A deleted-and-recreated id refuses.** Read a record, `delete` it,
> store a different same-kind record at that id through plain `add`, then submit an
> `IF_UNCHANGED` element carrying the first read's revision: `MemoryStoreStaleError`,
> and the replacement stands unmodified. The recreation is made through `add` and not
> through `INSERT_IF_ABSENT` deliberately — the hole §1's never-reissued clause
> closes is exactly the one a mode-dependent bound would leave open.

> **Normative.** **Both refusals stay distinguishable.** An `INSERT_IF_ABSENT`
> collision raises `MemoryStoreConflictError` and a stale `IF_UNCHANGED` raises
> `MemoryStoreStaleError`, and neither is catchable as the other.

> **Normative.** **The fake and the durable store agree**, which is what binding the
> suite to all three achieves and is not a separate arm: every clause above runs
> against `FakeMemoryStore`, `InMemoryMemoryStore` and `SqliteMemoryStore` through
> the existing `TestFakeMemoryStoreContract`, `TestInMemoryMemoryStoreContract` and
> `TestSqliteMemoryStoreContract` bindings.

> **Normative.** **The issuer survives `clear`**, on every store: read a record,
> `clear` the store, store a record at the same id, and an `IF_UNCHANGED` carrying
> the pre-`clear` revision is refused. Asserted for every binding, because the
> obligation is not a durability one — an issuer reset by `clear` reissues within one
> object's life.

> **Normative.** **The issuer survives a reopen**, `SqliteMemoryStore`'s own test:
> read a record, close the store, reopen it on the same file, `delete` the record and
> store a different one at that id, and an `IF_UNCHANGED` carrying the first read's
> revision is refused. It sits beside the migration test that plants a legacy row
> with a `rowid` at or below zero and asserts it reads back at a positive revision.

> **Normative.** **`MemoryWrite`'s two invalid states are refused at construction**,
> asserted in `core`'s own type tests rather than in the store suite, because they
> never reach a store: an `IF_UNCHANGED` element with `expected_revision=None`, a
> non-`IF_UNCHANGED` element with an `expected_revision` set, and a negative
> `expected_revision`, each a construction-time `ValidationError`. Without these an
> implementation passes every arm above while accepting an `IF_UNCHANGED` element
> carrying no expectation, which reaches write time with nothing to compare and
> fails — or worse, does not — in a way this ADR does not describe.

> **Normative.** **The cross-process arm is `SqliteMemoryStore`'s own test and not a
> contract arm.** Two connections on one file, one committing between the other's
> read and its conditional write, with the conditional write refused — asserted where
> the guarantee lives, because a non-durable store has no second process and a
> contract clause it cannot satisfy is the trap ADR-0046 §4 avoided by scoping
> durability obligations to durable backends.

> **Normative.** **The ingestor's re-run is `MemoryIngestor`'s own test and not a
> `MemoryWriterContract` arm** (§5). The property needs a store the test perturbs
> between the writer's read and its write; `MemoryWriterContract` binds
> implementations against a store the suite does not drive that way, and an arm that
> could not fail there would certify nothing. ADR-0028 §8's list is untouched.

### 8. What this ADR does not decide

> **Normative.** **A transaction spanning `search`.** ADR-0046 §Alternatives weighed
> "A transaction *handle* spanning reads and writes" and rejected it on surface;
> nothing here revives it. The conditional write closes the same window at a
> fraction of the surface, and a read-spanning transaction stays undecided with no
> firing condition minted for it.

> **Normative.** **A conditional `delete`.** No caller has asked for one. Fires with
> a consumer that must destroy a record only if it has not changed — ADR-0073 §5's
> show-then-delete window is the candidate, and ADR-0217 §7 is explicit that its own
> read discipline "stands beside the gate and is not a substitute for it", which is
> the same distinction. Deciding it needs that consumer's lane.

> **Normative.** **Anything about a placement's semantics.** ADR-0217 owns what
> `guard` and `unguard` write, what §3's precedence admits and what a refusal
> returns; this ADR supplies a mode and says nothing about the value written through
> it.

> **Normative.** **Removing or narrowing #262's lock** (§5).

> **Normative.** **A revision on any store other than `MemoryStore`.** The
> conversation, notification, deferral and plan stores are untouched;
> `PlanStore.commit_transition` already has its own token and this ADR neither
> restates nor changes it.

> **Normative.** **Exposing a revision on any client-facing surface.** `Belief` and
> `BeliefSummary` gain nothing — `Belief`'s docstring already says it is
> "Deliberately **not** a raw :class:`MemoryRecord`" — and no rendering of a
> revision is authorised anywhere.

### 9. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's, applied to the earlier ADR's text: "Would a
reader holding only the earlier ADR now act differently, or read one of its clauses
more widely than it now holds?" It is applied below to each ADR this one builds on,
and it comes out "no" every time, so no record is owed anywhere and none is written.

**Against ADR-0046 no record is owed, and the case is the one ADR-0217 §13 already
ruled on.** §5's ruling is that `write_atomic` does not close #248 — true after this
ADR as before, since what closes it is a mode `write_atomic` did not have. §5's
re-scoping sentence describes the shape this ADR builds and the gate it fires; a
deferral naming a firing condition is not made false by the condition firing, which
is what a firing condition is for. §6's "Deferred with #248 until a consumer runs
two writers on one store" stays true of ADR-0046, which still decides no
compare-and-swap. And #248 is still open on the day this merges (§5, §10). The
precedent is direct: ADR-0217 §7 fired the very same trigger of the very same
section, and its §13 records nothing against ADR-0046.

**Against ADR-0045 no record is owed.** §3's `last_updated` ruling is *kept* by §1
rather than narrowed — this ADR refuses the overload §3's sentence bars. §2's
placement rule is applied, not amended. §10's "#104 closes it alongside the
atomicity primitive" was already narrowed by ADR-0046 and carries ADR-0045's dated
record of that; this ADR narrows nothing further. The blast-radius sentence this ADR
argues with is in ADR-0045's *Context*, among "The forces against" — it is not a
clause a reader could disobey, and §Consequences' "additive, defaulted, so no
construction site breaks" is ADR-0045's own reading of what the force cost. A reader
holding only ADR-0045 acts identically.

**Against ADR-0108 no record is owed.** §4's cross-kind refusal is *satisfied* by §4
above at a door §4 did not enumerate, which is what "every upsert-capable door on
every implementation" is for; the enumeration "`add` and `write_atomic`'s `UPSERT`
mode alike" names the doors that existed, and reading it as an exhaustive list would
be the "false-shelter shape" §4 exists to refuse. §4's declining of a new error
class is about a cross-kind collision and stays true of one; §3 above applies §4's
own test to a different refusal and shows it comes out the other way, which is using
the test rather than changing it.

**Against ADR-0028 no record is owed.** §5's "`MemoryStoreError` as the only error
that crosses the seam" is satisfied, not widened: the new error is a
`MemoryStoreError`. §8's conformance list is untouched — §7 above puts the
ingestor's arm in the ingestor's own tests and says why — and §8's own sentence that
the suite "deliberately does **not** fix … the fold's own rule" stays true.

**Against ADR-0217 no record is owed.** It gates itself on a conditional write and
defers the design to "#248's own ADR"; this ADR supplies exactly that and changes no
sentence of it. §7's `Raises` list is unmoved because §3 puts the new error under
`MemoryStoreError`, which §7's own words require. §9's enumeration of what ADR-0217
changes in `core` stays exhaustive of *that* ADR's change and says so in terms —
"The enumeration above is of what *this* ADR changes." §12's deferral fires as
written. This is a stacked addition, recorded here and nowhere else.

**Against ADR-0014 no record is owed.** §5's compare-and-swap on `PlanStore` is
cited as the precedent this ADR's shape follows and is not touched; nothing here
changes `ExecutionState`, `StepTransition` or `StaleExecutionError`.

**Against ADR-0213 no record is owed.** §11's version ruling stays true of the
change it ruled on — a defaulted addition to `MemoryBase` — and §6 above applies it
to a change of the same shape rather than restating or widening it. Its `topics`
field and this ADR's `revision` are two additive members on one envelope, deciding
different questions and read at different sites.

### 10. What the implementing lane owes, and the order

> **Normative.** The `core` change and every implementation of it land in **one**
> change: `core/types.py`'s three additions, `core/errors.py`'s error,
> `write_atomic`'s docstring in `core/protocols.py`, `SqliteMemoryStore`,
> `InMemoryMemoryStore`, `FakeMemoryStore`, and §7's conformance arms with the
> `SqliteMemoryStore` cross-process test. A tree that accepts an `IF_UNCHANGED`
> element some implementation silently applies unconditionally is a fail-open window
> on the mode this ADR exists to add, which is why the mode and its honouring are
> atomic in the sense ADR-0217 §7 uses the word.

> **Normative.** The SQLite migration is **mechanical and additive**: a `revision`
> column on `records`, in the shape ADR-0045 §9 gave the `validity` columns, plus
> the store's issuer. No row is rewritten and no record's payload changes.

> **Normative.** The backfill **issues** a stamp for every existing row from the
> store's own issuer, in one ordered pass, and persists the issuer at the last value
> it handed out. It may **not** backfill `0`, and it may **not** derive a stamp from
> `records.rowid`. `0` is reserved by §1 for a record no store has stored, so a
> backfilled `0` would make a caller-constructed default expectation match a real
> row — the fail-open case §2 closes twice, reintroduced by the migration. And a
> `rowid` is a signed 64-bit integer that a legacy table can hold *negative*: this
> store carries a case planting exactly that
> (`test_a_walk_yields_a_legacy_record_whose_rowid_is_below_zero`), because "``rowid``
> was only issued by ``AUTOINCREMENT`` from ADR-0114 onwards", so a rowid-derived
> stamp would breach both `ge=0` and §1's positivity on rows the store is obliged to
> keep. The pass is the shape `_backfill_valid_from` already runs for ADR-0045 §9's
> column, and for the same reason it states: "There is no sentinel below every
> possible ``rowid`` to seed with, so the first page takes no bound at all and the
> cursor starts from what it actually found."

> **Normative.** The migration and the column land inside `_setup`'s
> `BEGIN IMMEDIATE`, as every migration in that store already does, so the column,
> the backfilled stamps and the persisted issuer commit together or not at all. A
> half-backfilled column would leave some rows at the reserved `0`, which is the
> state §1 forbids.

> **Normative.** The ingestor change (§5) is a **second change**, after the first,
> and it is what closes #248. It carries the two call sites, the bounded re-run, and
> the ingestor tests §7 places there. It is separated from the first because the
> first is complete and correct on its own and is the gate ADR-0217 §7 names, while
> the second is a `memory/`-internal behaviour change with its own tests.

> **Normative.** Against ADR-0217's own ordering, this ADR is the entry §11 places
> as "#248's conditional write, in its own ADR", and the change above is its
> implementation. Both land before ADR-0217 §7's two acts. Nothing here reorders
> ADR-0217 §11's earlier entries, and no lane reads this section as licence to widen
> any of the changes it names.

> **Normative.** No lane implementing this ADR adds a Protocol member, a `Settings`
> field, a wire operation or a client-facing rendering. Anything not named above is
> a change of its own.

## Consequences

- **#248's residual closes, both halves.** With the fold conditional, two
  `MemoryIngestor` instances over one store and two processes sharing a store file
  both stop losing updates — the two cases `ingest`'s own docstring names as
  uncovered, and the two ADR-0046 §5 called "any two writers not sharing that lock".
- **ADR-0217 §7's gate opens.** Its two acts become implementable, and the lost
  *narrowing* it names — a derivation overwritten by a stale `unguard` — becomes a
  refusal the act re-decides against rather than a silent widening.
- **This is a breaking `core` change**, flagged per golden rule 5, and it is
  *behaviourally* breaking rather than structurally: no signature moves, but every
  `MemoryStore` implementation must author a field and honour a mode, so a store
  outside this repository written against ADR-0046 would be non-conformant until it
  does. That is why it is an ADR, why it merges alone ahead of any implementation,
  and why it carries the architecture review as well as the adversarial one.
- **Every record grows one small integer** and every store gains a never-reissuing
  issuer, in memory and in one SQLite column. The
  read path gains nothing to compute; the write path gains one lookup the shipped
  store already makes, since `_persist_record`'s `SELECT` is where the row is found
  for the insert-versus-update decision and for ADR-0108 §4's kind check.
- **A new failure a caller must handle.** Any caller adopting `IF_UNCHANGED` takes on
  a refusal and a bounded retry, and a caller that adopts the mode without the retry
  turns a lost update into a raised error — better, but not the outcome. §5 states
  the retry for both first consumers so neither lane invents one.
- **What would trigger revisiting this.** A consumer that needs the conditional write
  to span a `search` (§8's first deferral); a consumer that needs a conditional
  `delete` (§8's second); or a measurement showing the fold's re-run rate high enough
  that re-asking the policy on every conflict is the dominant cost, which would be an
  argument about #262's lock rather than about this mode.

## Alternatives considered

- **A content digest of the stored record, computed by a pure `core` function, with
  no envelope field.** Zero blast radius and no store-authored field. Rejected on two
  counts. It has an ABA hole by construction — a record changed and changed back
  reads as unchanged — which is benign only where the caller's decision is a pure
  function of the observed content, and neither the fold nor a later consumer is
  obliged to be. And the digest's definition becomes contract: `score` is populated
  by retrieval and `None` when stored, so a record read through `search` would digest
  differently from the same row read through `get` unless the exclusion is written
  into `core` and every implementation reproduces it exactly. A store-authored,
  never-reissued stamp has neither problem.
- **A per-id counter, restarting at `0` when an id is stored after a delete.** The
  narrower mechanism, and the shape `ExecutionState.version` has. Rejected on the
  ABA hole it leaves, which is not hypothetical here: `MemoryStore.delete` is
  unconditional and `MemoryBase.id` is producer-owned — an external system's
  identifier is that system's idempotency key (ADR-0038 §2a) — so a re-sync that
  deletes a record and stores a new one at the same id through an ordinary `add` or
  `UPSERT` restarts the counter, and a conditional write held over that gap lands on
  the replacement it was never decided against. Bounding it by requiring
  `INSERT_IF_ABSENT` for the recreation does not work: nothing obliges `add` or
  `UPSERT` to be that mode, and a rule that holds only where every other writer opts
  in is not a store guarantee. `ExecutionState`'s id is minted by the tracker and is
  nobody's foreign key, which is why the same shape is sound there and is not here.
  A never-reissued stamp closes the case at the cost of the counter's one readable
  property, which §1 forbids reading anyway.
- **Comparing the whole record: `MemoryWrite` carries the `expected` record and the
  store compares it against the stored one.** No new envelope field, and the
  expectation says exactly what the caller means. Rejected: it carries a whole
  record's bytes per element, and it inherits the `score` trap above in its sharpest
  form — a record read through `search` is never equal to the stored row, so the
  most natural way to obtain a record to write against would silently always refuse.
- **The expectation read off `write.record.revision` rather than a separate field.**
  One field instead of two. Rejected in §2: a caller that builds rather than reads
  its record carries the default `0` and silently expects an unrewritten row, which
  is a fail-open expectation on exactly this path. `StepTransition.expected_version`
  is the ratified shape and it is two fields for this reason.
- **`Provenance.last_updated` as the token.** No new field at all. Rejected in §1,
  and barred independently by ADR-0046 §5 on ADR-0045 §3's ground. The added reason
  is decisive on its own: an instant cannot separate two writes inside one clock
  reading, and not every write moves it — ADR-0217 §7's `unguard` is a write that
  need not.
- **An opaque `str` token instead of an `int`.** It would forbid arithmetic by type,
  which §1's inequality-not-ordering clause has to forbid by rule instead. Rejected
  for symmetry with `ExecutionState.version` and `StepTransition.expected_version`,
  which are the corpus's answer to the identical problem; a second spelling of one
  concept in one repository is a cost paid at every reading, and the rule that a
  revision is compared and never ordered is one sentence.
- **A conditional `add` as well as a conditional batch element.** Rejected in §2: a
  one-element batch is already legal and ADR-0046 §2 says so, and two doors into one
  conditional write is two places for them to disagree.
- **Leaving the fold unconditional and closing only ADR-0217's window.** Smaller, and
  arguably the minimum the gate demands. Rejected in §5: #248 is an issue about the
  fold, ADR-0046 §5 re-scoped *it* to this mechanism, and an ADR that added the
  mechanism without the consumer the issue is about would leave #248 open with
  nothing scheduled — surface whose only consumer is an ADR that has not merged.
- **A `MemoryStore.transaction()` handle spanning the conflict `search` and the
  write.** It closes the window at its source rather than at the write. Rejected as
  ADR-0046 §Alternatives rejected it, on surface: "a transaction context object,
  every read and write re-exposed on it, an isolation-level contract, and an
  in-memory fake that must emulate read isolation, not just write atomicity". That
  section's closing reason holds here too — a handle "buys the unneeded half" —
  and §8 records it as undecided rather than refused for good.
