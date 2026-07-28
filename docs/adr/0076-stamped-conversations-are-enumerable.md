# 76. A stamped conversation is enumerable, so a crashed deletion can be finished

- Status: Accepted
- Date: 2026-07-28
- **This ADR partially supersedes ADR-0074**, in the scope named in §1: §9's
  `ConversationStore` obligation set, and the reach of its stamped-conversation
  exclusion. Everything else ADR-0074 decided stands and is untouched — §8's
  deletion protocol and its grace, §7's retention, §9's coordinator ruling and its
  two sweeps, the export split, and §9.1–§9.5's five ratified semantics.
  ADR-0074's Status line records the supersession per ADR-0070 §4; **no ratified
  body text of ADR-0074 is rewritten** (ADR-0070 §1). **Both files land in one
  change**, so ADR-0074's Status never points at an ADR that is absent —
  ADR-0070 §1's condition on recording a supersession is that the superseding ADR
  *exists*, and the failure it forbids ("with no such ADR") is unreachable when
  the pair is atomic. This is ADR-0075's header reading, now precedented on
  `main`: ADR-0005 carries `Partially superseded by ADR-0075` and did so while
  ADR-0075 was still `Proposed`. The `Proposed` → `Accepted` flip is the
  ratifying edit at merge (ADR-0015 §5; `CONTRIBUTING.md`, "Trivial ADR edits"),
  and ADR-0070 §1 keeps the repair path open besides: a marked supersession that
  never landed is restored by correcting the Status line, which changes no
  decision.
- **This is a contract change** (golden rule 5): one method on an existing
  Protocol, plus one **subclass** of the error that Protocol already raises. No
  new Protocol and no new `core` type — §2 is deliberately shaped so that none is
  owed. It ships as its own docs-only PR, reviewed while `Proposed`, and both
  land with the lane that owns ADR-0074 §9's items 5–6 (§3).
- **Refs:** ADR-0074 §8 (the deletion protocol, the tombstone, the grace, and
  "run by the deleting call, **at engine start**"), §9 (the obligation set, the
  coordinator ruling, `episodes_to_purge`'s ids-only shape and the argument for
  it, the stamped-conversation exclusion, §9.4's exclusion set), §7 (retention
  reclaim, which finds its work through `recent`); ADR-0070 §1 (the
  amend-versus-supersede test this ADR is filed under), §3 (partial supersession
  is the sanctioned form), §4 (the status vocabulary); ADR-0073 §2 (the paging
  posture this inherits), §8 (the precedent that a Protocol *change* states its
  suite obligations as the next lane's); ADR-0004 §6 (the deletion right this
  protects); `CONTRIBUTING.md` ("Adding a Protocol" — "the triad is what a
  Protocol *change* is measured against too"); #447 (the gap this closes).

## Context

#447 records the gap, found while implementing ADR-0074 §9 items 1–4. Compressed
rather than re-derived:

ADR-0074 §8 makes a deletion a three-step protocol — stamp the conversation,
destroy the episodes its index names, drop the record — and says the reclaim that
finishes it runs "by the deleting call, **at engine start**, and later by the
hub's scheduler (leg 5)". The tombstone exists precisely so a crash between steps
is survivable: "the stamped record and its index are still there, still naming
every episode id involved."

**But nothing can find it.** §9's ratified obligation set gives the store no read
that returns a stamped conversation. `get`, `recent`, `export` and `turns` all
exclude one by design; `episodes_to_purge` and `drop_if_eligible` both take a
`conversation_id` the caller must already hold. So a process that dies between
step 1 and step 3 leaves a tombstone that no later run can rediscover.

The user-visible outcome is still correct — the stamp hides the conversation from
every read and refuses every append, so the deletion *looks* done and the right
under ADR-0004 §6 is honoured. What is lost is the sweep: the episodes the index
names are never destroyed, and the index itself outlives its grace indefinitely.
That is exactly the residue §8's grace and reclaim exist to reclaim, made
permanent by the absence of a way to enumerate the work.

Retention reclaim (§7) does not have this problem: it looks for *unstamped* idle
conversations, and `recent` enumerates those.

**Two alternatives were considered and ruled against** (#447 listed three;
adjudication is recorded here):

- **The coordinator persists its own list of pending deletions.** Cheaper, and
  wrong for ADR-0074's own reason: it is a second record of a fact the tombstone
  already holds, and "two records of one fact … drift" is precisely why §9 put
  conversation membership in the index rather than on the record. It would also
  have to be durable and crash-safe itself — a third store, invented to avoid
  reading the second.
- **Leave it to leg 5's scheduler.** It defers nothing: leg 5 would need the same
  read, and until it exists every crashed deletion leaks its episodes for good.

## Decision

### 1. What is replaced, and why this is a supersession rather than an amendment

Applying ADR-0070 §1's test — *would a reader act differently?* — to ADR-0074 §9:

**The obligation set is exhaustive on its face.** §9 says `core/protocols.py`
"gains **one** Protocol, `ConversationStore`, **owing:**" and then enumerates
eleven obligations, and closes with "**What is ratified is the obligation set**
and the semantics above; the exact spelling ships with the triad." A reader
implementing that Protocol today implements those eleven and no more; after this
ADR they implement twelve. **They act differently.** That is a change to what was
decided, so it is a supersession — partial, because only the obligation set and
one clause about it are replaced.

**The second replaced clause is the reach of the exclusion.** §9 says "**So no
read returns a stamped conversation's rows at all — not even the sweep's.**" A
reader asking "may any caller learn that conversation X is stamped?" answers *no*
today and *yes, the sweep may* after this ADR. Also changed, also a decision.

**What is *not* replaced, stated so the boundary is exact:**

- **§9.4's exclusion set is untouched, verbatim.** "A stamped conversation is
  absent from every read that presents it — `get`, `recent`, `export`, `turns`
  and both reverse lookups — while `episodes_to_purge` still yields the ids the
  sweeps must destroy." §2's method presents nothing: it is the same kind of
  carve-out §9 already made for `episodes_to_purge`, drawn on the same
  distinction between a read that *presents* a conversation and one that hands a
  sweep the identifiers it must act on. **No other read's stamped-exclusion
  changes, in either direction.**
- **§8's protocol, its tombstone and its grace** — unchanged in every particular.
  This ADR adds no step and re-times nothing.
- **§9's coordinator ruling** — unchanged. Cross-store sequences still belong to
  the `orchestration` lifecycle stage; this only lets that stage *find* the work
  §8 already assigned it.
- **§7's retention reclaim** — unchanged, and still finds its work through
  `recent`.
- **§9.1–§9.5's five ratified semantics** — the unique parked binding, the
  ordinal invariant, bounded-and-ordered reads, the mutation exclusion, and the
  standing module clauses. §2 inherits the third and the fifth rather than
  altering them.

ADR-0074's Status line records this per ADR-0070 §4, and an appended dated note
names the scope. Nothing below its header is rewritten.

### 2. `ConversationStore` owes one more read: the stamped conversations, ids only

**`stamped_conversation_ids`** — a bounded, cursor-paged read returning the ids
of conversations that are stamped deleted and not yet dropped. Spelling is the
implementing lane's as always (§9's rule); what is ratified is below.

**It returns ids and nothing else.** Not `Conversation` records, not the stamp
instant, not turn counts — the same shape and the same argument §9 makes for
`episodes_to_purge`: "Returning only what the work needs removes the exposure
instead of labelling it." A record-returning read would be a general resurrection
of everything §8 spent its deletion protocol hiding, bought for a caller that
needs an id to pass to two methods it already has.

**The stamp instant is deliberately not returned either, and this is the one
place the shape is smaller than it first looks.** The obvious design hands back
`(id, deleted_at)` so the caller can tell which tombstones have outlived their
grace. It is wrong twice over. `drop_if_eligible` **already re-checks the grace
under the per-conversation exclusion** (§9.4), so a caller pre-filtering on
`deleted_at` would be deciding eligibility on a reading taken *outside* the
exclusion — the exact hazard §9.4 forbids, reintroduced one layer up. And the
sweep does not want the filter anyway: §8's step 2 destroys the episodes of a
stamped conversation **whether or not** its grace has elapsed; only step 3 is
conditional, and step 3 is `drop_if_eligible`, which judges for itself. So the
enumeration yields every stamped conversation regardless of grace, and the grace
stays exactly where ADR-0074 put it.

**It is bounded and cursor-paged, modelled on `episodes_to_purge`** (§9's
"complete and walkable, not only tails"): a bounded `limit`, and an exclusive
`after_id` cursor that is an id from the previous batch. Walk by calling again
with the last id received, until a batch comes back empty. The deletion sweep
**must drain to an empty batch**, for the reason §9 gives the purge walk:
finishing one batch and stopping is the failure that clause exists to forbid.

**The default batch is named here, and it is 100.** ADR-0074 §9.3 is explicit
that "the defaults are named, not left to the implementation" — "a 'bounded
default' with no figure is two conforming stores handing the same continuation
different history, and a conformance suite with nothing to assert" — so a
"finite configured batch" would not have discharged the rule this ADR says it
inherits. It is a **fixed figure and not a `Settings` field**: unlike §7's
retention horizon this expresses no user policy, and unlike §5's replay window it
sizes no prompt. It is a round-trip-versus-memory trade on a walk that always
runs to exhaustion, so the number is only ever a performance detail, and there is
no reading of it a user could want to change. 100 matches the batch the purge
walk it is walked beside uses, which leaves one figure to reason about rather
than two for the same sweep.

**The order is `id` ascending, and the cursor is placed lexically against it —
not by looking the row up.** `after_id` names a *position in the id space*, so
the next batch is every stamped id ordering strictly after that string. An id
that names no row is therefore a perfectly good cursor and is **not** an error.

**That is a correctness requirement, not a simplification, and it is what makes
this walk differ from `episodes_to_purge`'s.** The purge walk can place its
cursor by lookup because §9 guarantees its rows survive the whole traversal:
"Nothing is removed until the record is dropped." **This walk has the opposite
property — its rows are removed by the very sweep that is walking them.** The
ordinary sequence is: take a batch, destroy each conversation's episodes, call
`drop_if_eligible`, then ask for the next batch using the last id received — by
which time that row may be gone, dropped by this sweep a moment earlier or by a
second one. A cursor resolved by looking the row up would be unplaceable exactly
when the sweep is working correctly, and a `(deleted_at, id)` order would compound
it: the store cannot recover a dropped row's stamp instant to place the cursor
after it. So the ordering key must be one the **caller already carries**, and `id`
is the only such value this method returns.

Ordering by `deleted_at` — oldest tombstone first, which reads as the useful
priority — is declined for that reason and not for taste. It is also worth little:
the sweep must drain to an empty batch and act on every conversation it finds, so
the order is about a stable traversal rather than about doing the most overdue
work first.

**Reading it removes nothing**, exactly as `episodes_to_purge` removes nothing.
A row leaves when `drop_if_eligible` succeeds and not before, so the sweep stays
**idempotent by re-walking**: a run that dies part-way is re-run from the
beginning, and every conversation it revisits is one whose drop is a no-op or
whose episodes are already gone. A lexical cursor is what keeps that true for a
*resumed* walk as well as a restarted one.

**Paging arguments carry ADR-0073 §2's posture unchanged** — out of range is a
`ValueError`, and `limit=0` is an empty batch. `after_id` carries no such refusal,
per the paragraphs above: there is nothing for the store to fail to place.

**One error class is narrowed, because a sweep cannot otherwise tell "already
done" from "broken".** ADR-0074 §9 rules that every method raises
`ConversationStoreError` for a store fault "and refuses an unknown conversation
as §1 requires". Both arrive as the same class today, and that is exactly enough
to break the walk this ADR enables: sweeper A enumerates conversation `C`,
sweeper B — or the deleting call, or the scheduler — finishes `C` and drops it,
and A's next `episodes_to_purge(C)` raises. A cannot distinguish that from a
failing database, so it either aborts a start-up sweep that was working
perfectly, or swallows real store faults to avoid doing so.

So `ConversationStoreError` gains a subclass for the one case — an id the store
does not know. This is **additive, not a second replacement of §9**: a subclass
*is* a `ConversationStoreError`, so every existing `except ConversationStoreError`
still catches it and §9's sentence stays true as written. It is precisely the
shape `MemoryStoreConflictError` already has under `MemoryStoreError`, and for
the reason `core/errors.py` records there — it lets a caller "distinguish 'id
collided, mint again' from 'the store is broken, abort'". Here it lets the sweep
distinguish *someone else already finished this one* from *stop*.

**The sweep's obligation follows from it, and is ratified here rather than left
to the implementer:** an enumerated id that is unknown by the time the stage acts
on it is a **no-op — the stage moves to the next id**, because a conversation
that is gone is a deletion that completed. Every other `ConversationStoreError`
aborts the sweep and is reported. That is what makes "duplicated sweeps are safe"
true rather than merely plausible, and it is the half `drop_if_eligible`'s
re-check does not cover: the re-check makes a *duplicated drop* harmless, and
this makes a duplicated *walk* harmless.

### 3. Who may call it — and why the contract cannot say so

The caller is the **`orchestration` capture/lifecycle stage**, the sweep owner
§9's coordinator ruling names. It is **not a user-facing surface**: the CLI never
shows a stamped conversation, and nothing in this ADR makes one showable.

**That restriction is a wiring fact and a review concern, not an enforceable
one**, and ADR-0074 §9 is explicit about why: "A `core` Protocol is a
cross-subsystem contract, so a method exists for *every* injected consumer —
naming one `sweep_turns` documents an intent the contract cannot enforce." The
same is true here, so this ADR does not pretend otherwise and does not try to buy
safety with a name.

What *is* enforceable is the return shape (§2) and the untouched exclusion
(§1): a caller that obtains this list learns which ids are stamped and can learn
nothing else about them — `get` still answers `None`, `recent` and `export` still
omit them, `turns` and both reverse lookups still refuse. The CLI's silence
follows from those unchanged reads rather than from a promise about who calls
what.

### 4. The implementation obligation lands with ADR-0074 §9's items 5–6

This **changes** an existing Protocol rather than adding one, so no new triad is
owed — but `CONTRIBUTING.md` is explicit that the discipline carries over ("The
triad is what a Protocol *change* is measured against too — extend the suite in
the same change, so the new obligation is enforced rather than assumed") and
equally explicit that the mechanical check will not catch its absence ("add a
method to an existing Protocol and leave its suite alone and the gate stays
green"). So it is stated as an obligation, following ADR-0073 §8's precedent for
exactly this shape.

**The method, both implementations, and the conformance clauses land as one unit
with the items 5–6 lane** — the stage that consumes it. Splitting them is the
dispatcher's call and not an author's default: ADR-0073 §8 set that precedent,
and the reason is sharper here, since a method with no caller and no suite is the
deferral "Adding a Protocol" exists to prevent.

The shared suite gains a clause for **each** of these:

1. **A stamped conversation is enumerated**, and an **unstamped** one is not —
   the pair, so an implementation returning everything passes neither half alone.
2. **A dropped conversation is not enumerated**, which is the trivially-true half
   worth pinning because it is what makes the walk terminate.
3. **Grace is not a filter here.** A conversation stamped a moment ago appears in
   the enumeration; `drop_if_eligible` is what refuses it. An implementation that
   pre-filtered on the grace would hide exactly the tombstones whose episodes step
   2 must still destroy.
4. **A crashed deletion is rediscoverable** — the clause this ADR exists for.
   Stamp a conversation, do *not* drop it (the interrupted §8 sequence), and
   assert the enumeration finds it, that `episodes_to_purge` still names its
   episodes, and that `drop_if_eligible` finishes it once the grace has elapsed.
   For the persistent store, across a **reopen**, since "at engine start" is the
   case the gap was found in.
5. **The multi-batch walk** — more stamped conversations than one batch, drained
   to an empty batch, each visited exactly once. §9's own multi-batch clause is
   the model, and the single-batch fixture is what proves nothing.
6. **The walk survives its own drops**, which is the clause §2's lexical cursor
   exists for: take a batch, `drop_if_eligible` every conversation in it, then
   continue with `after_id` set to the last id received — **whose row is now
   gone** — and assert the walk reaches the rest and terminates. An
   implementation resolving the cursor by lookup passes every other clause here
   and stalls after the first page in ordinary use. Assert it for a second
   sweeper too: a row dropped by *another* caller between batches is the same
   case arriving from outside.
7. **The order is `id` ascending**, and the **default batch is 100**, exercised
   with more than that many stamped conversations so the figure is really
   asserted — ADR-0073 §8's argument that a suite testing only small explicit
   values never reaches either, and §9.3's that an unasserted default is two
   stores answering differently.
8. **The paging posture** — out of range refused, `limit=0` empty; and an
   `after_id` naming no row **positions the walk rather than raising**, which is
   the negative half of clause 6.
9. **The exclusion is unchanged for every other read**, asserted on the *same*
   conversation while it is enumerable here: `get` is `None`, `recent` and
   `export` omit it, `turns` and both reverse lookups refuse or return `None`.
   That pair is what keeps this method from becoming a way around the front door.
10. **An unknown id raises the narrow subclass**, on every method that refuses
    one — `mark_active`, `append`, `turns`, `episodes_to_purge` — and a store
    *fault* still raises the base class. Both halves, since a subclass nothing
    distinguishes buys the sweep nothing and a subclass raised for everything
    buys it less than nothing.

**And one test that is not a store test at all, in `tests/orchestration/`:**
**engine start-up consumes this read and finishes the deletion.** Persist an
interrupted §8 sequence — a stamped conversation with its episodes still in the
`MemoryStore` — reopen both stores, start the lifecycle stage, and assert that it
enumerates the tombstone, destroys those episodes, and drops the index once the
grace has elapsed. Every clause above can pass against a method **nothing calls**,
which would leave precisely the residue this ADR exists to remove; ADR-0074 §9
already puts cross-store sequences in that lane's tests, and this is the one that
proves the wiring rather than the store.

**And its companion: a sweep continues past a conversation someone else
finished.** Two sweepers over one pair of stores; the first enumerates a batch,
the second completes and drops one of the ids in it, and the first then reaches
that id. Assert it treats the `UnknownConversationError` as a no-op, **carries on
to the remaining ids**, and that a genuine store fault still aborts and is
reported. Without this the start-up sweep is abandoned by the very concurrency
`drop_if_eligible`'s re-check was supposed to make safe — and the ids after it in
the batch are the ones that stay unreclaimed.

### 5. What this ADR does not decide

- **Multi-process exclusion** (#446). Two engines, or two processes, sweeping the
  same stamped conversation at once is the same question ADR-0074 §11 defers to
  leg 5's concurrent-access posture, and this method inherits the answer rather
  than changing it. What §2 *does* settle is the pair that makes a duplicated
  sweep harmless rather than merely unlikely: `drop_if_eligible`'s re-check under
  the exclusion for the drop, and the unknown-id no-op for the walk. Neither is a
  claim about *ordering* two sweepers, which is what #446 is actually about.
- **Who runs the sweep, and when.** ADR-0074 §8 already says: the deleting call,
  engine start, and later the hub's scheduler. **Leg 5 inherits this method
  unchanged** — a scheduler is a second caller of the same read, not a reason to
  design a different one.
- **Un-stamping, or any resurrection of a stamped conversation.** There is no
  such operation and this ADR does not add one; a stamp is terminal, and the only
  transition out of it is the drop.
- **Anything about retention reclaim** (§7), which is unstamped by definition and
  finds its work through `recent`.
- **A count, a "how much is pending" surface, or a user-facing view of deletion
  progress.** All three are judgements with no consumer, which is ADR-0074 §10's
  standard for declining.

## Consequences

- **§8's protocol becomes finishable, which is what it always claimed to be.**
  The tombstone was already durable and already named every episode involved; the
  only thing missing was a way to find it. A crashed deletion now costs a
  re-walk rather than an unbounded leak of the episodes it had not yet destroyed.
- **The contract grows by one method and no types.** §2's ids-only shape is what
  keeps a fifth `core` type off the table, and the `(id, deleted_at)` design that
  would have needed one is rejected on its own merits (§2), not for economy.
- **The stamped conversation is now visible to exactly one caller, and only as an
  id.** That is a real widening of §9's exclusion and this ADR says so rather
  than filing it as a clarification. What bounds it is the return shape and the
  five reads that still refuse — not a name, and not a promise about callers,
  because §9 already showed a `core` Protocol cannot make either stick.
- **The items 5–6 lane grows by one method, one error subclass, ten conformance
  clauses and two orchestration tests**, and gains the case that would otherwise
  have been unwritable: an interrupted §8 sequence, resumed at start-up.
- **Revisit if** leg 5's process model makes two concurrent sweeps ordinary
  rather than exceptional, if a deletion ever needs to report progress to the
  user, or if the enumeration turns out to want the grace filter after all —
  which would mean `drop_if_eligible`'s re-check had stopped being the place
  eligibility is decided, and would be that change's problem to argue.

## Alternatives considered

- **The coordinator keeps its own durable list of pending deletions.** Rejected
  in Context. Two records of one fact, drifting; and it needs its own crash-safe
  store to avoid reading the one that already exists.
- **Defer to leg 5.** Rejected in Context. Every crashed deletion leaks until
  then, and leg 5 needs this method anyway.
- **Return `Conversation` records.** Rejected in §2. It resurrects, for one
  caller, everything §8's stamp exists to hide — and the caller needs an id.
- **Return `(id, deleted_at)` so the caller can skip tombstones still in grace.**
  Rejected in §2, and it is the tempting one. It duplicates a decision
  `drop_if_eligible` already makes under the exclusion, invites the caller to
  make it *outside* the exclusion, and buys a filter the sweep does not want,
  since step 2 destroys episodes regardless of grace.
- **Ordering by `deleted_at` with an `after_id` cursor placed by lookup.**
  Rejected in §2, and it was this ADR's first answer — both review personas found
  it independently, which is what a `Proposed` ADR is reviewed for. The sweep
  *drops the rows it is walking*, so the cursor row is routinely gone by the next
  call, and a dropped row's stamp instant is unrecoverable besides. The walk would
  stall after its first page exactly when the sweep was working correctly. Unlike
  `episodes_to_purge`, whose rows §9 guarantees survive the traversal, this one
  needs an ordering key the caller carries and a cursor that needs no row.
- **An `include_stamped` flag on `recent`.** Rejected: one flag, two questions —
  the widening ADR-0073 §1 and §3 refused twice and ADR-0074 §9 cites in refusing
  a conversation axis on the belief reads. `recent` answers "which conversation
  should I continue?"; this answers "what deletion did I leave unfinished?", and
  a listing that can return a conversation the user deleted is a listing whose
  every caller must remember to filter.
- **Naming it for its caller — `pending_deletions`, `sweep_conversations`.**
  Rejected on ADR-0074 §9's own ground: a name documents an intent the contract
  cannot enforce. The name here describes what comes back, and the *return shape*
  does the work a restrictive name could not.
- **Enumerating stamped conversations through `episodes_to_purge` by passing no
  conversation id.** Rejected: it overloads a method whose whole ratified value
  is that it returns episode ids for one conversation, and it would have to
  return two different kinds of id depending on its argument.
