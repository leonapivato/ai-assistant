# 104. Re-embedding is an offline build-and-swap: resumable, verified, and cloud-refusing

- Status: Proposed
- Date: 2026-08-05

## Context

[ADR-0006](0006-embedding-seam.md) §4 tags every
stored vector with the embedding model that produced it, so a store opened
against a different embedder is detected rather than silently ranked on
incomparable vectors. `SqliteMemoryStore._verify_or_init_meta` implements that
check inside `__init__`, and since [ADR-0083](0083-the-hub-is-a-resident-process.md)
§6 it raises `IncompatibleStateError` — a **deployment** fault, exit `78`,
supervisor stays down.

The detection is right and stays. What is missing is the other half ADR-0006 §4
promised in the same sentence: the metadata exists so the store can "drive that
migration", and there is no migration to drive. The gap is live rather than
theoretical. #425 records it: an installation whose `memory.db` was written under
`HashingEmbedder` — the composition root's previous default — becomes unstartable
the moment `Settings.embedder` defaults to the vendored on-device model
(`EmbedderKind.ON_DEVICE`, ADR-0006 §2, [ADR-0024](0024-the-embedding-model-is-a-build-input.md)).
The only escapes today are deleting the database, which destroys the accumulated
evidence the product exists to hold, and pinning `ASSISTANT_EMBEDDER=hashing`,
which keeps the deployment on non-semantic retrieval with no way forward.

**Placement is already ratified and is not reopened here.** ADR-0083 §10 names
this migration by name: "An offline tool — the re-embedding migration (#425) is
the first and for now the only one — takes the same instance lock, which
serialises it against the hub by construction and needs no new mechanism." So the
tool runs with the hub stopped and holds `<data_dir>/hub.lock` (§1) for its whole
run. Ruling 4's "the hub is the only process that opens the databases" is a
statement about *concurrent* openers, and the lock is what §10 offers as the
discharge; nothing below widens it.

What is *not* on any record is **how** the migration behaves, and three questions
have to be answered before anything is written:

1. **Where the re-embedded records are built.** In place, or beside the live
   store. A store carrying two model ids is exactly the state ADR-0006 §4 exists
   to make impossible, and an in-place rewrite passes through that state for as
   long as it runs.
2. **What happens when it is interrupted.** Months of records re-embedded by a
   CPU-bound on-device model is a long-running job on ordinary hardware. A laptop
   lid, a power cut, or `Ctrl-C` is not an exceptional case for a job of that
   length; it is the expected one.
3. **What happens when the target embedder is a cloud one.** ADR-0006 §2 makes
   cloud embedding opt-in, and [ADR-0004](0004-privacy-and-data-handling.md) §2
   makes egress minimal and confined to endpoints the user chose. Neither was
   written with this act in view: a migration to a cloud embedder ships the
   **entire memory store** — every Tier 1 record the user has ever accumulated —
   to a third party in one uninterruptible burst. That is an egress event of a
   different order from a single request's context, and inheriting the general
   posture would let it happen because a configuration variable happened to be
   set.

No cloud `Embedder` exists in the tree today: `EmbedderKind` has exactly two
members, both on-device. Deciding §4 now is therefore deliberate — the rule is
cheap to state while the case is hypothetical and expensive to retrofit once a
cloud embedder is a configuration away.

## Decision

### 1. The migration builds a new store beside the live one and swaps it in

> **Normative.** The re-embedding migration writes every re-embedded record into
> a new database file in the live store's own directory and modifies no byte of
> the live store's file. The live store is replaced by a single atomic rename,
> and only after §3's verification has passed in full.

The alternative — rewriting vectors in place — was rejected on the state it
passes through rather than on cost. Halfway through an in-place rewrite the store
holds vectors from two embedding spaces under one `meta` row, which is the
condition ADR-0006 §4's tagging exists to make detectable and which, by
construction, it *cannot* detect: the tag is per store, not per vector. Every
search served from that store is silently wrong, and there is no reading of the
file that says so. Build-and-swap never produces that state on any path,
including a crash: the live store is either the old one or the new one, and both
are internally consistent.

The work file is a sibling of the live store rather than a temporary directory,
because `os.replace` is atomic only within one filesystem and same-directory is
the only placement that guarantees it without probing.

> **Normative.** The migration reads only `rowid`, `id`, `kind` and the stored
> JSON from the live store, copies the `rowid`, `id`, `kind` and JSON verbatim,
> and re-derives every other column of the destination row from that JSON. Only
> the vectors are recomputed.

Copying the blob verbatim is load-bearing: re-serialising the record would make
the migration a content change — a different pydantic version emits different
JSON for the same model — and a migration that rewrites evidence while claiming
to reindex it is the one thing this must not do. Preserving `rowid` matters for a
reason that is easy to miss: `SqliteMemoryStore.export` orders by `rowid`, so a
migration that renumbered rows would silently reorder a data-rights export
(ADR-0004 §6, [ADR-0007](0007-memory-data-rights.md) §3).

**Re-deriving rather than copying the remaining columns is what lets the
migration run on a store the current build has never opened**, and it takes
nothing on faith to do so. `SqliteMemoryStore` states the invariant already —
"the blob stays the truth and the column is a derived index" — and its own
`_migrate_records` backfills those columns from the blob for exactly this reason.
The four columns this migration reads are the four that have existed since the
schema's first version, so a store predating `expires_at`, `valid_until` or
`about_person` is migrated without its schema having to be brought forward first
— which matters because bringing it forward means *writing to the live store*,
and the clause above forbids that. A store carrying a hashing tag is by
definition an old store, so this is the ordinary case and not a corner.

**Every row is copied, expired ones included**, and the read filters stay where
they are. [ADR-0103](0103-confidence-is-two-quantities-evidence-and-currency.md)
§1 binds every leg 7 decision — none of them may "delete, expire, elide or weaken
a belief, or the evidence behind a belief, in order to reclaim storage" — and a
migration that quietly dropped what `search` would not have returned would be
doing exactly that under cover of a reindex. Re-embedding changes how records are
found, and nothing about which of them the store holds.

**Re-embedding reads content, never the old vectors**, which is what makes the
source embedder unnecessary — and therefore what lets a deployment migrate *off*
an embedder it can no longer construct at all.

### 2. Resumability is a property of the design, not a recovery path

> **Normative.** The migration commits in chunks. Each chunk's record rows, their
> vectors, and the cursor naming the last source `rowid` copied are written in
> one transaction on the work store, so the recorded cursor can never claim
> progress the work store does not hold.

> **Normative.** A run resumes an existing work store only when that store's
> recorded embedding model and dimensions both equal the target embedder's **and**
> its recorded fingerprint of the live store equals the live store's current
> fingerprint. Otherwise the work store and its SQLite sidecars are discarded and
> the migration restarts from the beginning.

The fingerprint is `st_dev`, `st_ino`, `st_size` and `st_mtime_ns` of the live
store, **plus SQLite's own file change counter** — the four header bytes SQLite
increments whenever it unlocks a database it has modified. The stat fields alone
are not enough, and the reason is ordinary rather than exotic: `st_mtime_ns`
reports the filesystem's timestamp *resolution*, not a promise that two writes a
microsecond apart get different values, so a same-sized update inside one
timestamp tick leaves all four unchanged. The change counter moves on a write
that changes neither the file's length nor any timestamp. Its job is to notice that the hub ran between two attempts and changed the
source underneath a half-built copy — a record updated or deleted below the
cursor is not revisited by a resumed scan, so the copy would be stale in a way no
later chunk corrects. The check is deliberately conservative: it re-runs the whole
migration on any doubt, and the cost of a false restart is CPU, while the cost of
a false resume is a corrupt store. It is also **not** trusted as the last word —
§3's verification re-reads both stores in full and does not consult it.

> **Normative.** The cursor is absent from the work store's `meta` until the
> first chunk commits; it is never initialised to a sentinel.

There is no integer to use as one. `rowid` is an explicit `INTEGER PRIMARY KEY`
here, so it starts at `-2**63` and SQLite has nothing below that to compare
against — which makes the obvious sentinel, `0`, silently skip every row at or
below it. Such a row cannot be written through the store's own API, but it can
exist in a file, and the failure it produced was a verification complaint about
counts rather than anything an operator could act on.

> **Normative.** The cursor and fingerprint are recorded in the work store's own
> `meta` table and are deleted, in the same transaction that records the final
> chunk's completion, before the swap. The verification in §3 asserts that the
> swapped-in store's `meta` holds the two store keys and nothing else.

Migration scaffolding surviving into the live store would be inert but would also
be a second place where the store's identity is written down. Deleting it before
the swap and asserting the deletion is cheaper than reasoning about that later.

### 3. Nothing is swapped in that has not been verified against the source

> **Normative.** Before the swap, the migration verifies all of: the work store's
> `meta` records the target embedder's model id and dimensions and no other key;
> the work store's record rows correspond one for one with the live store's, in
> `rowid` order, equal on `rowid`, `id`, `kind` and the stored JSON; every derived
> column of a work row equals the value re-derived from that row's own JSON; and
> the work store holds exactly one vector row per record row. A verification
> failure aborts the migration with the live store untouched.

Verification re-reads rather than re-checking a counter, because the failures
worth catching are the ones the writing code would not notice — a chunk lost to
an interrupted transaction the cursor nonetheless survived, a source mutated
between attempts, a `vec_records` row that failed to insert. A count comparison
would pass every one of them. The derived columns are checked against the blob
beside them rather than against the source, because the blob is what §1 makes
authoritative and because the source may not carry those columns at all.

> **Normative.** Immediately before the rename, the migration re-reads the live
> store's fingerprint and refuses if it differs from the one the run started
> with.

Verification and the rename are two steps, and a write landing between them would
be thrown away by the rename with nothing reporting it. This narrows that window
from the length of a full re-read to the microseconds between a `stat` and a
`rename`; it does not close it, and it is not offered as closing it. What closes
it for the hub is the instance lock — but the lock is advisory, which ADR-0083
§10 states in as many words, so it does not stop a `sqlite3` shell somebody left
open on their own machine. That is the case this actually catches, and on a
single-user machine it is the likely one.

> **Normative.** Immediately before the rename, the migration hard-links the live
> store to `<store>.pre-reembed`. If that path already exists and is not a link to
> the live store's own inode, the migration refuses and does nothing.

> **Normative.** A failure to flush the rename to disk is reported as an
> unconfirmed durability, never as a failed migration, and the migration is
> reported as having happened.

Directory `fsync` is refused outright on some filesystems, which is a property of
the mount rather than a fault of the run — and past the rename the migration
*has* happened. An operator told "the swap did not happen", over a store that now
carries the new tag, would go looking for a store that no longer exists. So the
two facts are reported separately: the swap succeeded, and its durability could
not be confirmed until the filesystem next syncs.

Retaining it is also the only reading ADR-0103 §1 leaves open. A migration that
deleted the pre-migration store to save a copy's worth of disk would be removing
the evidence behind every belief in it for no warrant other than store size,
which that clause forbids in as many words. The disk cost is named in the
Consequences instead, where it belongs.

The retained original is not belt-and-braces for the swap — the swap is atomic —
it is for the case verification cannot cover: a target embedder that turns out to
be the wrong choice, or a re-embedded store whose retrieval quality is worse than
what it replaced. Deleting it is the operator's act, not the tool's. The hard
link is what keeps the retention free (one inode, no copy) and keeps the swap a
single atomic step; a path that exists but names a different inode is somebody
else's file and is never overwritten.

> **Normative.** Before it opens the live store, the migration refuses if a
> SQLite sidecar (`-journal`, `-wal`, `-shm`) lies beside it; and once open, it
> refuses a store whose journal mode is WAL. Both refusals happen before any
> record is embedded.

Two checks because the hazard has two shapes and one check catches only one of
them. Renaming over a database whose `-wal` holds committed pages orphans those
pages against a *different* database, and nothing downstream can detect that.

A sidecar beside a cleanly closed store means a process is using the file now or
one died holding it, so it is checked *before* the open — after the open it would
be this migration's own. It catches what the instance lock cannot, the lock being
advisory (ADR-0083 §1). Journal mode, by contrast, lives in the database header
and survives a close, so a WAL store presents as sidecar-free until it is opened;
it is therefore read from the open connection. WAL is deferred by ADR-0083 §12
with reasons and tracked as #505, so no store this build wrote is in it — this is
the check that establishes that rather than assuming it.

### 4. A cloud embedding target is refused unless the operator names the egress

> **Normative.** The migration refuses any embedding target it does not
> positively identify as running on the user's own device. Identification is by
> an explicit allow-list of `EmbedderKind` members held at the composition root;
> a member absent from that list is refused. The allow-list is enumerated by
> name, so a member added later is refused until somebody adds it deliberately.

Fail-closed, and by enumeration rather than by a predicate on the embedder. A
predicate would need a new capability on the `Embedder` Protocol — a contract
change this decision does not need and golden rule 5 would make its own ADR — and
it would put the answer in the hands of whoever implements the embedder rather
than in the hands of the decision. The allow-list lives at the composition root
because that is where the embedder is *chosen*: `memory/` receives an `Embedder`
and cannot tell, and must not be asked to guess.

> **Normative.** A refused target proceeds only when the operator passes an
> explicit flag whose name states that the whole memory store is uploaded. The
> refusal itself names the act — that every record in the store would be sent, and
> which configured embedder would receive it. On the authorised path the tool
> prints the target model id and the record count before the first record is
> embedded.

The flag names the act rather than the mechanism (`--upload-entire-memory-store`,
not `--allow-cloud`), because the thing an operator must consent to is the size
of the egress and not the topology. The refusal carrying the disclosure is what
makes the refusal path useful rather than merely obstructive: an operator who runs
the tool and is stopped has already been told what they would be authorising. The
count arrives only on the authorised path because obtaining it means opening the
store, and the refusal deliberately precedes that.

This is a rule about **this act**, not a new general posture. ADR-0004 §2 as
amended by [ADR-0017](0017-egress-boundaries.md) §1 is
untouched, and ADR-0006 §2's opt-in cloud embedder stays exactly as opt-in as it
was. What is added is that *configuring* a cloud embedder is not by itself
consent to ship the accumulated store to it, because those are decisions of
different size taken at different moments.

### 5. The mechanism is `memory`'s, the wiring is the composition root's, and the entry point is the service's

> **Normative.** The migration mechanism lives in `memory/`; the embedder and the
> migration are wired together in `app/composition.py`; and the console entry
> point lives in `ai_assistant/service/` and imports no subsystem directly.

This falls out of rules already in force rather than adding one, and it is stated
because the two obvious shortcuts both breach something. The entry point must
take the instance lock, which lives in `ai_assistant/service/lock.py`, and
`lint-imports`' "nothing imports the service" contract means the entry point has
to *be* in `service/`. `service/` in turn "may import `app` … and `core`" (ADR-0083
§8) — the same clause the readers contract already reads as exclusive — so it
reaches `memory` the way it reaches every subsystem, through the composition
root. Putting the command on `interfaces/cli.py` is foreclosed twice over: by
that same rule, and by ADR-0084 §6's reasoning for why the hub is its own console
script.

> **Normative.** The migration takes `<data_dir>/hub.lock` before it opens any
> store and holds it until it exits. A contended lock is refused immediately, with
> a diagnostic naming the data directory and the lock path; the migration does not
> retry.

ADR-0083 §1 gives a losing *hub* a few seconds of retry because the holder may be
draining and the supervisor's restart is automatic. Neither applies here: the
holder of a contended lock, from this tool's point of view, is a hub that is
meant to be running, and the operator's next act is to stop it. Retrying would
turn a one-line instruction into a wait.

### 6. Re-embedding is never automatic

> **Normative.** No part of the system runs this migration on its own. The hub's
> refusal to start on a model-id mismatch stands unchanged, and re-embedding is
> an act an operator invokes.

An automatic migration at startup would convert a legible refusal (ADR-0083 §6, a
`78` with an operator action) into an opaque multi-hour startup, and it would
spend the machine's CPU on a decision — that this store should follow this
configuration change — that only a human is in a position to take. It would also
make the §4 refusal unreachable in the one case it exists for.

## Consequences

- **#425 closes**, and the escape it names as data loss stops being an escape. An
  upgraded installation with a hashing-tagged store runs one command with the hub
  stopped and starts.
- **Disk.** The migration needs room for a second copy of the store while it
  runs, and leaves a third — the retained original — until the operator deletes
  it. For a personal store of text plus vectors this is the right trade against
  the alternative, which is a rewrite that can corrupt, and ADR-0103 §1 rules out
  buying the space back by dropping anything.
- **Time is not bounded and is not meant to be.** The cost is one on-device
  embedding per record, and §2 is the answer to the length rather than an attempt
  to shorten it. Progress is reported as it goes, so an operator can tell a slow
  run from a stuck one.
- **The §4 egress is not recorded in the audit trail**, and that residue is named
  rather than closed: ADR-0004 §7 puts side-effecting acts in the audit trail, and
  the audit store belongs to the hub, which is stopped by construction while this
  runs. The flag and the unconditional disclosure are what stands in for it. Filed
  as a follow-up to settle if and when a cloud `Embedder` is actually built.
- **#136 does not close and is not touched.** It asks for `Embedder.model_id` to
  become a behavioural fingerprint so that a tokenizer or preprocessing change
  moves it — work in `models/` on ADR-0006 §4's *detection* half. This ADR decides
  the *remedy* half. They meet only in that a sharper `model_id` makes this
  migration fire more often and correctly.
- **Nothing in ADR-0103 is disturbed.** Its §1 governs this decision and this
  decision complies: every row is copied, the original is retained, and the only
  thing this ADR discards is migration scaffolding. Its §2's split of confidence
  into evidence-strength and currency lives inside each record's JSON, which §1
  above copies verbatim, so a store migrated by this tool carries whatever the
  fold semantics wrote and this migration has no opinion about it.
- **Revisit if** exclusivity is relaxed (ADR-0083 §12's condition), which would
  make the instance lock insufficient to serialise this tool against the hub; if a
  cloud `Embedder` is implemented, which is when §4 stops being hypothetical and
  the audit residue above needs an answer; or if the store grows large enough that
  a second full copy is not a reasonable ask, at which point the trade in §1
  deserves re-measuring rather than re-arguing.
