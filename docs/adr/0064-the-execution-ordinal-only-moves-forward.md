# 64. The execution ordinal only moves forward, and the store proves it

- Status: Accepted
- Date: 2026-07-24
- **Not a contract change.** This ADR touches no Protocol in
  `core/protocols.py`, no `core` type, and no `Settings` field. It changes the
  *persistence model* of one implementation, `SqlitePlanStore`, so that a
  guarantee ADR-0049 §3 already claims is actually checked rather than assumed.
  Golden rule 5's separate-PR ratification does not apply, so this ADR is
  **Accepted on merge**, landed together with the implementation.
- **Amends no ratified text.** ADR-0049 §3 already says the ordinal is
  "monotonic within one incarnation, never reset". This ADR does not change that
  claim; it records how the store now *enforces* it and what it deliberately does
  not defend against.

## Context

ADR-0044 §1 makes it normative that an execution id is never handed to a second
execution for the life of the audit trail: a parked `AWAITING_APPROVAL` step is
recovered by asking the trail for `pending_confirmation(execution_id, step_id)`,
so a reused id lets a stale confirmation from an earlier execution resolve a
freshly-created one. `SqlitePlanStore` discharges that with a composite id,
`{plan_id}-exec-{pid}-{nonce}-{ordinal}` (ADR-0049 §3), whose three parts divide
the work:

- the **pid** and the per-incarnation **nonce** cover every cross-process and
  cross-instance case — independent construction, restart, `fork`;
- the **ordinal**, a durable `meta("exec_counter")` row, covers what they cannot:
  *intra-incarnation* uniqueness. Within one running store object the pid and
  nonce are constants, so the ordinal is the only thing distinguishing two ids.

That division makes the ordinal's monotonicity load-bearing, and nothing checked
it. `exec_counter` is a single mutable row read-incremented at each allocation.
Anything with write access to the database file can lower it — a hand-edit, a
"reset the counter" script, a partial restore of one table, a third-party
migration tool — and the store then re-mints ordinals it has already issued.
Within one incarnation that produces a **byte-identical** id (issue #356,
reproduced on `main` before this change):

```text
first id            : p1-exec-1087458-N-1
counter after clear : 1        (ADR-0049 §3: never reset)
counter rolled back : 0
after rollback      : p1-exec-1087458-N-1
SAME ID REISSUED    : True
```

Two things already narrow the exposure, and they are worth stating because they
are also what makes the remaining case the *dangerous* one:

- **`executions.id` is a PRIMARY KEY.** If the earlier execution's row is still
  present, the re-mint fails loudly as a `PlanningError` wrapping
  `UNIQUE constraint failed`. The reissue only *succeeds silently* once that row
  is gone — after `clear()` or `delete_goal()`, which are precisely the
  operations ADR-0049 §3 says the counter must outlive.
- **Across a reopen the nonce covers it.** A new store object mints a fresh
  `uuid4().hex`, so a counter rewound while the file is closed yields different
  ids on the next incarnation.

So the silent case is narrow — same running process, an outside write landing
between a `clear`/`delete_goal` and a later `start_execution` — but it corrupts
an audit-relevant invariant with **no signal at all**. Issue #356 asked whether a
store should defend against a file-level writer at all, given that writer can
equally rewrite the `data` blobs. That is the question this ADR answers.

The obvious in-memory fix — remember the highest ordinal this object has issued
and refuse anything below it — is correctly scoped but records nothing. It cannot
tell a later reader that the file was tampered with, and it is a check the store
cannot make at open, where ADR-0049 §1 puts every other "this is not a file I can
vouch for" refusal.

## Decision

**We will make the monotonicity of `exec_counter` a checkable property of the
database, by keeping a durable high-water mark beside it, and refuse a store
whose counter has fallen below that mark.**

### 1. The mark, and where it lives

A second `meta` row, `exec_high_water`, holds the highest value `exec_counter`
has ever reached. It is written in the **same transaction** as every counter
increment (`_next_ordinal` runs inside the allocation's `BEGIN IMMEDIATE`), so in
a file only this store has written the two are always equal.

**It lives in `meta` deliberately, and that placement is the whole trade.** The
refusal below is the first in this store that fires on a *well-formed* database —
one row per key, valid integer, primary key intact — a file an earlier version
would have opened. Putting the witness in the same table as the value it
witnesses is what keeps that refusal aimed at tampering rather than at ordinary
operations: restoring the database file rolls the counter and the mark back
**together**, so they still agree and the store opens. The restore also removes
the executions that consumed the higher ordinals, so re-issuing those ordinals
collides with nothing — and the reopened store mints a fresh nonce anyway, so the
*ids* differ regardless. A witness kept anywhere else — a sidecar file, a
separate table restored on its own schedule — would turn every restore into a
refusal. That is checked by a test, not just asserted here.

The mark is **not** derivable from the records. `MAX(created_seq)` over
`executions` is exactly what `clear()`/`delete_goal()` erase, which is *why*
`exec_counter` is a separate, never-reset key in the first place; a witness
computed from the records would be erased alongside the thing it witnesses.

### 2. Where the check fires: at open *and* at every allocation

Both, and for different reasons.

**At open**, inside `_verify_or_init_meta`, before any record table is created,
read or written — the posture ADR-0049 §1 already takes for `schema_version`. A
counter below its mark means the file's ordinal is no longer the one this store
maintained. Opening it and failing later, at whatever allocation happens to hit
it, would report the fault far from its cause; refusing at open makes it loud and
diagnosable. This is also the only site that catches a rewind performed while the
file was closed — where the nonce means no id is reused, but `created_seq` is now
non-monotonic, so `active_executions`' and `export`'s "oldest first" quietly
stops being true.

**At allocation**, inside `_next_ordinal` — and *this* is the site that closes
issue #356. The open establishes nothing an outside writer cannot undo a moment
later, which is the same reasoning PR #355 used to harden both read sites against
an ambiguous counter. The rewind that actually reissues an id happens
mid-session, after the open has validated, so an open-time check alone would not
have caught the reproduction above.

### 3. A lagging mark is levelled up, not refused

Only `counter < mark` is refused. A mark *below* the counter is not a rewind: no
ordinal has been issued twice. This is what a mixed-version deployment looks like
— an older build advancing the counter without the witness — and it must not
refuse. It is levelled up instead, and promoting it is not a repair: the counter
is the highest ordinal issued, so that is what the high water is.

**The levelling happens at the open, eagerly, and that is load-bearing.** Left to
the next allocation, a lagging mark is a standing hole: an outside writer that
rewinds the counter *down to meet the stale mark* leaves the two agreeing, so
`counter >= mark` passes a rewind straight through. Bringing them level at the
open means that for the rest of the session any rewind falls below the mark — so
§2's allocation-time test stays sound without re-scanning the records at every
allocation.

### 4. The records corroborate the counter, and a pre-mark database is backfilled

**The two markers alone cannot catch every rewind, so the open also checks the
counter against the records.** Every execution stores in `created_seq` the ordinal
it was allocated with, written by the same transaction that advanced the counter,
and `clear`/`delete_goal` only ever *remove* rows. So
`MAX(created_seq) <= exec_counter` holds for every file this store wrote, and a
violation is corruption whatever the mark says. Two cases need it, both reproduced
before the check existed:

- **A deleted mark**, which is indistinguishable from one that was never written,
  so the backfill below would otherwise launder a two-row tamper — drop the mark,
  lower the counter — into a fresh, agreeing pair.
- **A lagging mark met by a rewound counter** (§3), where the two agree at a value
  the file has long since passed.

Both end the same way: a second execution allocated a `created_seq` an existing
one already holds, so `active_executions`/`export` silently stop being the
oldest-first order the contract requires. Note what is *not* at stake — neither
case reuses an execution **id**, because a reopened store mints a fresh nonce
(ADR-0049 §3). The durable ordering is the casualty, and it is enough.

The records are **not** a substitute for the mark and never *raise* the counter:
they are precisely what `clear`/`delete_goal` erase, which is why ADR-0049 §3
keeps the ordinal in `meta` at all. They can only refuse — and where no execution
survives there is nothing to corroborate *and* nothing to corrupt (§5). The cost
is one aggregate read per open, never per allocation.

**Beneath all of it, `executions.created_seq` is declared UNIQUE.** The markers
are read at two points in time, and between them the file can change: a writer
that does not maintain the mark — a concurrently running older build, most
plausibly — can advance the counter after this store has opened, and a subsequent
one-row rewind then leaves counter and mark agreeing at a value the file has
already passed. No amount of re-reading the two `meta` rows sees that, and
re-scanning `executions` on every allocation would put a full table scan on the
hot path of the operation this store exists to make cheap.

Declaring the constraint costs nothing and is not a new invariant: every
allocation takes `created_seq` from the counter it increments in the same
`BEGIN IMMEDIATE` transaction, so it is already unique for every file this store
wrote. Saying so makes ADR-0049 §1's oldest-first ordering a property of the
*schema* rather than a convention the counter is trusted to keep — the same
relationship the enforced foreign keys have to `save_plan`'s app-level orphan
check. Whatever route a second row at one ordinal arrives by, SQLite refuses it.

It does not make the mark redundant, and the mark does not make it redundant. The
index cannot catch #356's original reproduction — `clear()` removes the row the
duplicate would have collided with, which is exactly what made that reissue
silent — and the mark cannot catch a stale-mark window it never observes. Each
covers what the other cannot. A file that *already* holds duplicate ordinals is
refused at the open, since nothing here can decide which of two rows at one
ordinal came first.

**A database predating the mark is stamped, not refused.** Every plan store
written before this change has a counter and no mark. Making a durable record
unopenable by the code that wrote it is a far worse failure than the one the mark
prevents, and it is the same call `SqliteAuditTrail` made for its marker-less
databases (#346). The stamp is sound rather than merely lenient — the pre-existing
counter *is* the highest ordinal that file has issued, because that is exactly
what the earlier code maintained — so it records what is already true, and the
corroboration above is what stops that trust being exploitable.

Following #346's ordering, the corroboration and the stamp both run **after** the
record schema is created, inside the same setup transaction. That is what puts
`executions` in scope at all, and it means a create that fails rolls the mark back
with it, leaving an unlabelled database the next open will stamp correctly rather
than one falsely labelled by an open that never completed. The `counter >= mark`
refusal stays *ahead* of the record tables, where §2 puts it.

The alternative considered and rejected was durable provenance — bumping
`schema_version` to 2 so a missing mark is refusable on a file expected to carry
one. It works, but it makes an older build refuse the file outright, and an older
build opening a post-ADR-0064 file is *harmless*: it advances the counter without
the witness, which §3 levels up on the next open. Paying a downgrade refusal to
detect a case the records already detect is the worse trade — and it would not
have caught the lagging-mark case at all.

### 5. What this does not defend against, and why that is the right line

**The mark is a consistency witness, not a tamper-proof seal.** A writer who
lowers *both* rows **and** leaves no execution behind to corroborate (§4) is
undetectable, and no scheme confined to the same file could be otherwise: the
same writer can rewrite the `data` blobs, forge whole executions, or delete the
file. This store's threat model is not an adversary with write access — it is
**accident and partial corruption**: a hand-edit of one row, a script that
"resets" the counter, a table-level restore, a bug in a migration tool. Every one
of those moves the counter and leaves the mark, and every one of them is now a
`PlanningError` instead of a silently reissued id.

It is worth being exact about what the residual case costs, because it is less
than it looks. A rewind performed while the file is **closed** does not reissue an
execution id at all: the reopened store mints a fresh nonce, which is the job
ADR-0049 §3 assigns it, and the reproduction in the Context above needs one
running incarnation for precisely that reason. What a closed-file rewind corrupts
is the durable *ordering* — two executions at one `created_seq` — which §4's
corroboration catches wherever there is an execution left to be out of order
with.

That is the answer to issue #356's open question, recorded so it is not re-raised:
the store does *not* attempt to defend an audit-relevant invariant against a
hostile file-level writer, and does not pretend to. It converts the realistic,
accidental version of the failure from silent corruption into a refusal at a
named seam.

## Consequences

- **A refusal that no earlier version produced.** A well-formed database with a
  rewound counter now fails to open, and a mid-session rewind fails the next
  `start_execution`, both with `PlanningError`. This is a deliberate behaviour
  change; §1's placement of the mark is what bounds it to files whose markers, or
  whose markers and records, actually disagree.
- **Ordinary operation is unaffected**, and the paths that could plausibly have
  regressed are enumerated and tested: whole-file backup/restore, `clear()` and
  `delete_goal()` (which never touch `meta`), a `:memory:` store, two processes
  allocating on one file (serialised by the same write lock the counter already
  relies on), and a store predating the mark.
- **One extra `UPDATE` per allocation**, inside a transaction already open and
  already writing the counter, plus one `MAX(created_seq)` aggregate per *open*.
  No new lock, no new round trip, and nothing added to the allocation's read path.
- **A unique index on `executions.created_seq`.** Created `IF NOT EXISTS` like the
  rest of the schema, so it is additive and idempotent and needs no schema-version
  bump; it also speeds the `ORDER BY created_seq` that `active_executions` and
  `export` already run. A pre-existing database that already holds duplicate
  ordinals will not open — the only such database is one this invariant was
  already broken on.
- **ADR-0049 §3's ordinal claim is now enforced rather than assumed.** Its text
  stands unchanged; this is the mechanism behind it.
- **Revisit when** a second on-disk schema version arrives — the mark is a `meta`
  row like `schema_version` and migrates the same way — or if the threat model in
  §5 ever widens to a hostile writer, at which point the answer is signing or
  externalising the record, not a second row in the same file.
