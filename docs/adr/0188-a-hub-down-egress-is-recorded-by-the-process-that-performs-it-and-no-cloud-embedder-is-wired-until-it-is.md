# 188. A hub-down egress is recorded by the process that performs it, in a file the hub does not own, and no cloud embedder is wired until it is

- Status: Proposed
- Date: 2026-08-23

## Context

[ADR-0104](0104-re-embedding-is-an-offline-build-and-swap-resumable-and-cloud-refusing.md)
§4 authorises the largest single egress act this system can perform. The
re-embedding migration refuses any embedding target it does not positively
identify as on-device, and an operator lifts that refusal by passing a flag whose
name states the act — `--upload-entire-memory-store`. On the authorised path every
Tier 1 record the user has ever accumulated is sent to a third party.

ADR-0104's own Consequences name what it left open, and #747 holds it:

> **The §4 egress is not recorded in the audit trail**, and that residue is named
> rather than closed: ADR-0004 §7 puts side-effecting acts in the audit trail, and
> the audit store belongs to the hub, which is stopped by construction while this
> runs. The flag and the unconditional disclosure are what stands in for it. Filed
> as a follow-up to settle if and when a cloud `Embedder` is actually built.

**The residue is structural rather than an oversight, and the structure is
ratified.** [ADR-0083](0083-the-hub-is-a-resident-process.md) ruling 4 is that
"the hub owns the five SQLite databases exclusively. The API is the only door; no
other process opens them" — the count has grown since and the *exclusivity* is what
binds — and its §10 gives this migration its discharge by name:
"An offline tool — the re-embedding migration (#425) is the first and for now the
only one — takes the same instance lock, which serialises it against the hub by
construction and needs no new mechanism." ADR-0104 §5 makes that binding — the
migration takes `<data_dir>/hub.lock` before it opens any store and holds it until
it exits. So the hub is *stopped* for the whole of the act, and the store that
would record it is the hub's.

`docs/roadmap.md` schedules the answer: milestone 24 lists "authorised cloud
egress in the audit trail (#747)" beside the read-side ledger, and its exit is
that "every read of a source and every egress is reconstructible from the audit
trail alone, origin included."

### What has landed since #747 was filed

[ADR-0185](0185-every-attempt-to-read-a-source-is-recorded-refusals-included-and-the-trails-bound-has-no-unlimited-spelling.md)
rules the read half and, in §10, says what "the audit trail" means for the
milestone:

> **Normative.** For milestone 24, "the audit trail" is the **pair** of durable
> permission records: `AuditTrail`, which holds what the permission layer decided
> about acts on the world, and `SourceReadTrail`, which holds what this system
> read from it. The two partition the subject — a read is never a
> `PermissionDecision` and an egress is never a `SourceReadRecord` — and neither
> answers the other's half.

Its Alternatives section refuses, by name, the move a reader reaches for first:

> **Record reads in the existing `AuditTrail`.** Refused for ADR-0097 §4's reason
> applied to a read: `PermissionDecision.tool` is a required `ToolDefinition`, a
> read has no declaration, and synthesising one puts a fabricated record into the
> one store whose premise is that its records are not fabricated.

[ADR-0186](0186-the-audit-trail-reaches-the-user-as-a-bounded-listing-and-an-unbounded-export-and-a-row-states-what-was-decided.md)
rules how the trail reaches the user, and its §8 states what no surface may do
with a row — including:

> **Normative.** No surface presents a decision as a transmission. The trail bounds
> resolutions and not executions (ADR-0021 §4), so a resolved `ALLOW` says a call was
> permitted and says nothing about whether, or how many times, it ran. No surface
> renders a row as "sent", "read", "delivered" or any other word for an event. #1503
> carries the consequence for milestone 24's exit wording.

**#1503 is open and held for the owner's milestone-24 exit ruling.** It records
that the trail bounds resolutions and not executions
([ADR-0021](0021-permission-model.md) §4), so a reader can reconstruct every
egress *decision* and cannot reconstruct whether any call happened. Its two shapes
are that the exit wording is read as "every egress decision", or that the
invocation contract gains a consume-on-execution step and the trail gains an
invocation record. Neither is decided, and §6 below states why this ADR is
unaffected by which way it goes.

### The tree as it stands, read rather than remembered

- `EmbedderKind` in `core/config.py` has exactly two members, `ON_DEVICE` and
  `HASHING`, both on-device. No cloud `Embedder` exists anywhere under `src/`; the
  implementations are `HashingEmbedder`, `FastEmbedEmbedder` and the
  `BoundedEmbedder` wrapper.
- ADR-0104 §4's allow-list is `_ON_DEVICE_EMBEDDERS` in `app/composition.py`,
  `frozenset({EmbedderKind.ON_DEVICE, EmbedderKind.HASHING})` — currently the whole
  enum, so `build_reembedder`'s refusal branch is **unreachable on `main`**.
- The disclosure and the run live in `service/reembed.py`'s `_run_locked`, which
  prints the store, the source and target model ids and dimensions, and the record
  count, and only then calls `Reembedder.run`. `--dry-run` returns after the
  disclosure and before that call.
- `memory/reembed.py`'s `Reembedder` receives an `Embedder` and cannot tell what
  it is. That is ADR-0104 §4's own sentence — "`memory/` receives an `Embedder`
  and cannot tell, and must not be asked to guess" — and it decides §2 below.
- **`SourceReadTrail` and `SourceReadRecord` are ADR-0185's owed contract surface
  and are not in the tree yet** (ADR-0185 §12; the implementing lane is in flight).
  This ADR cites them as the ratified decision they are, and no clause here depends
  on their existing.
- **Nothing in the tree folds an artifact left by another process into a store at
  startup.** `Engine.start`'s reconciliations are store-to-store within the one
  process, the offline restore tool publishes a whole staged directory by rename,
  and the re-embedder's own `.reembed` and `.pre-reembed` artifacts are read only by
  a later run of the same tool. There is no precedent, which §2 and Alternatives
  both bear on.

So there is nothing to record today, and there is nothing that could record it.
Deciding now is the same deliberateness ADR-0104 §4 exercised: the rule is cheap
to state while the case is hypothetical and expensive to retrofit once a cloud
embedder is a configuration away.

### One thing that is settled and is not reopened

**The boundary question.** [ADR-0017](0017-egress-boundaries.md) §1 rules that
"user data may leave the device only from `models/` or from a designated
integration seam inside `tools/`; every other egress is a bug." A cloud `Embedder`
is `models/`' by golden rule 4 and by ADR-0006 §2, so this egress leaves from the
boundary ADR-0004 §2 already authorises. What #747 holds open is not whether the
act may happen — ADR-0104 §4 decided that — but what records it when it does.

### The three candidates #747 lists

1. the migration writes to the audit store directly while it holds the instance
   lock, which puts an audit writer outside the hub for the first time;
2. the migration leaves a record beside the store that the hub folds into the
   audit trail on its next start;
3. the flag plus §4's unconditional disclosure is ruled sufficient, and ADR-0004 §7
   is amended to say so for hub-stopped acts.

This ADR takes the first half of (2) and refuses its second half, refuses (1) and
refuses (3). Alternatives considered gives each its reason.

## Decision

### 1. The subject is an execution with no resolution, and that is why neither existing trail can hold it

> **Normative.** The authorised egress ADR-0104 §4 permits is recorded. It is
> recorded neither as a `PermissionDecision` in `AuditTrail` nor as a
> `SourceReadRecord` in `SourceReadTrail`, and no lane synthesises either shape for
> it.

Three reasons, each already ratified somewhere else.

**A fabricated declaration.** `PermissionDecision.tool` is a required
`ToolDefinition`. The migration is not a tool call: nothing registered it, nothing
declared its costs or its tier reach, and the plan machinery is not running. ADR-0185's
Alternatives refused exactly this move for a read — "synthesising one puts a
fabricated record into the one store whose premise is that its records are not
fabricated" — and the sentence is about the store, so it carries to any producer
that has no declaration to offer.

**The partition.** ADR-0185 §10's first clause is explicit that "an egress is never
a `SourceReadRecord`", which closes the other trail without further argument. This
act is also not a read of a source in any sense: it sends the store outward.

**The one a reader will not expect, and the one that decides it.** ADR-0021 §4 is
that the trail bounds *resolutions*, not executions. Every row in `AuditTrail`
states that a question was settled. This act is the exact inverse: an execution
that will never have a resolution, because the layer that resolves questions is
not running and never ruled on it. A row for it would be the first row in that
store for which the store's own semantics is false — and ADR-0186 §8's third
clause, written to stop a *surface* claiming a transmission, would then be
forbidding the truthful rendering of the one row where "sent" is the fact. Putting
this act in `AuditTrail` does not extend the trail; it falsifies it.

### 2. The composition root resolves it and the entry point writes it, at the act, under the lock it already holds

> **Normative.** The record is written by the process that performs the egress,
> while it holds `<data_dir>/hub.lock`. No other process writes it, and no process
> writes it later on that process's behalf.

> **Normative.** The record is produced from the same resolution that lifted
> ADR-0104 §4's refusal — the target being absent from the composition root's
> allow-list **and** the operator's flag — and no layer infers it from the flag
> alone. A run whose target is on-device writes no record however the flag was
> passed, and a run that returns before the first record leaves the device — a
> refusal, an empty store, an up-to-date store, `--dry-run` — writes none either.

> **Normative.** `memory/` is not asked to produce it. The migration mechanism
> receives an `Embedder` and is not given a way to tell what it is.

**Why the actor and not the hub.** Deferring the write to the hub's next start
means the fact exists nowhere durable in the window between the egress and that
start, and the window is unbounded: the operator may not start the hub for weeks,
may replace the machine, may decide on the strength of the migration's own output
to delete the data directory, or may never start it again. A record whose
existence is conditional on a later process running is not a record of the act; it
is an intention to record it. And a row the hub composed from a file another
process wrote is hearsay in the one place first-hand-ness is the whole value.

**Why the flag is not the trigger.** `build_reembedder` refuses only when the
target is absent from `_ON_DEVICE_EMBEDDERS` **and** the flag is unset; an operator
who passes the flag on an ordinary on-device migration gets an ordinary on-device
migration. A record minted from `args.upload_entire_memory_store` would therefore
assert an egress that did not happen, in a record whose only value is that it
asserts one that did. This clause exists because that is the cheapest bug to write
and the hardest to notice: the false record is indistinguishable from a true one.

**Why this does not disturb ADR-0083 ruling 4.** The record is not one of the
databases the hub owns, and §3 makes it not a database at all. The migration
already opens the memory store under ADR-0083 §10's discharge; this adds no second
opener and no second door.

### 3. The record is a file, deliberately, and not a store

> **Normative.** The record lives in a single append-only, line-delimited file in
> the data directory, beside the databases and not among them —
> `<data_dir>/offline-egress.jsonl` — with owner-only permissions. It is not a
> SQLite database, gains no Protocol, no `core/` type and no conformance suite, and
> nothing in `src/ai_assistant/` imports it to read.

> **Normative.** The file holds **events**, one per line. A run contributes an
> `opened` event and, if it reaches its exit, a `sealed` event; the two carry the
> same run identifier and **together are that run's record**. A line once written is
> never rewritten, truncated or removed, and nothing in the file is amended in place
> — the seal is a second line, not an edit of the first.

> **Normative.** Nothing prunes it. It has no row cap, no retention duration and no
> eviction rule, and no lane adds one on the strength of ADR-0185 §6. The user's
> ADR-0004 §6 erasure right over it is deletion of the whole file, which is
> ADR-0021 §4's shape read one file over: the user may burn the book; nobody may
> tear out a page.

**A database would have to be the hub's, and that is the thing that cannot be.**
ADR-0083 ruling 4 says the hub owns its databases exclusively and no other process
opens them. A record written while the hub is stopped, by a process that is not
the hub, cannot live in a store held to that rule without an exception to it — and
the exception would be granted for a store whose only writer is the exempt process,
which is a store the rule was never about. A file sidesteps the question rather
than arguing it.

**Two events rather than one mutable object, and the reason is the same one that
makes this a file.** A record that had to be *revised* at the end of the run would
need either an in-place rewrite — which is the property an audit record exists to
deny, and which a crash between the read and the write can lose entirely — or a
store that can update a row, which §2's ownership problem forbids. Appending a
second line costs neither, and it makes §5's hard case self-describing rather than
inferred: a run identifier with an `opened` line and no `sealed` one **is** the
unsealed record, legible to anyone reading the file with no schema to consult.

**The arithmetic supports it and is worth stating.** There is exactly one writer,
it holds an exclusive lock for the whole of its run, and the number of events an
installation accumulates over its lifetime is at most twice the number of times an
operator deliberately re-embedded to a cloud target — a handful, not a stream. `AuditTrail`'s
atomic write-once check exists because two concurrent resolutions can race
(ADR-0021 §4); there is no second writer here to race with. ADR-0185 §6's row cap
exists because reads arrive on an interval; these do not arrive at all unless a
human types a flag. A store would buy a bound nothing needs, a query nothing asks,
and a database ADR-0123's counting hazard would then have to count.

**Line-delimited and human-readable, because for now the file *is* the surface.**
§7 defers a rendered surface; until one exists, the record has to be legible to the
operator who wrote it and copyable by the user exercising ADR-0004 §6's export
right. A line per event in a text file satisfies both without a mechanism.

### 4. What the record carries, and what "reconstructible" means for an act performed while the hub is down

> **Normative.** "Reconstructible", for an act performed while the hub is stopped,
> means the record is **complete at the moment of the act and readable without the
> hub**. No clause of this ADR makes reconstructibility depend on a later process
> running, on the hub starting again, or on any store being opened.

> **Normative.** The `opened` event carries, and yields from itself alone: the run
> identifier; the configured target — the `EmbedderKind` member, the target
> `model_id` and the recipient the configuration names; the source store's path and
> its recorded `model_id`; the authorisation — that an operator passed
> `--upload-entire-memory-store` at a command line — and the instant it was taken;
> the counts ADR-0104 §4's disclosure had already stated, being the records in the
> store and the records still outstanding; and the instant at which sending was
> entered.

> **Normative.** The `sealed` event carries the same run identifier, the outcome,
> the count actually embedded, the count carried over from an earlier run, and the
> instant of the seal. It restates nothing the `opened` event already carries; a
> reader joins the two on the run identifier.

> **Normative.** The `opened` event asserts that the sending was **entered**, never
> that any byte reached the recipient, and no lane, surface or measurement reads it
> as the latter. Whether a first request left, arrived, or failed inside the
> embedder is not determinable from this side, and the record does not claim it.

> **Normative.** The record carries **no content**. Not a memory record, not its
> text, not a vector, not a digest of one, not an identifier of one. ADR-0004 §5,
> ADR-0093 §8 and ADR-0185 §10's first declared narrowing bind here verbatim: what
> the record is an account of is the *access*, and a record that carried content
> would be a copy of the user's store beside the user's store.

> **Normative.** The record states that **no permission ruling exists for this
> act**, and states it positively rather than by omitting a field. A reader of the
> record is never left to infer whether the ruling is missing or absent.

**The last clause is ADR-0184's shape, one store over.** ADR-0184 minted a value
for a decision recorded before the origin field was legible precisely so that "the
absence is its own value" — a reader can tell "this was never recorded" from "this
was recorded as false". The same failure is available here in a sharper form: a
record silent about permissions invites a later reader, or a later surface, to
conclude that the act was ruled on and the row is elsewhere. It was not ruled on by
anything. That is the most important single fact about this act and it is written
down rather than left to the shape of the file.

**Two narrowings, declared rather than glossed**, the discipline ADR-0185 §10 and
ADR-0181 §8 used before it. Reconstructibility here does not include what was sent
— that is the content clause, and it is refused outright. And it does not include
what the recipient did with it, which is outside anything this system observes.

**The unit is a run, not a migration.** ADR-0104 §2 makes the migration resumable,
so a second invocation sends only the records still outstanding. Each invocation
that enters sending is its own egress and gets its own run identifier and its own
pair of events, carrying its own counts. Folding two runs into one record would
misstate both.

### 5. Write-ahead, then seal; an unsealed record is not an absent one

> **Normative.** The `opened` event is appended and flushed to durable storage
> **before the first record leaves the device**. The append is not conditional on
> the run succeeding, on any send succeeding, or on the seal ever being reached.

> **Normative.** An `opened` event that cannot be appended and flushed **refuses the
> run**, before anything leaves the device, with a diagnostic naming the file and the
> underlying failure. No lane makes the write best-effort, warns and proceeds, or
> falls back to a second location: an egress this system cannot record is an egress
> it does not perform.

> **Normative.** The `sealed` event is appended at exit on every path the process
> survives — a completed run, a failure raised out of the embedder or the store, and
> a `KeyboardInterrupt`.

> **Normative.** "Sealed" and "unsealed" are properties of **the file**, never of
> what the writing process knew or intended. A run is sealed when the file holds a
> complete, well-formed `sealed` line carrying that run's identifier, and unsealed
> otherwise. A line that is incomplete or malformed is not an event: a reader ignores
> it, and the run it would have belonged to is unsealed.

> **Normative.** A run is therefore left unsealed by a path that ends the process
> without running its exit — `SIGKILL`, a power cut, a kernel panic — and by a seal
> that could not be appended at all or reached the file only in part. A failure to
> append is reported to the operator on standard error, naming the file.

> **Normative.** A seal that was appended but whose durability the filesystem will
> not confirm **is a seal**. The run reads as sealed, and the operator is warned on
> standard error that the line may not survive a power loss until the filesystem next
> syncs — ADR-0104 §3's shape for a swap that happened but could not be flushed, and
> the same words it already prints. Neither that warning nor a failed append turns a
> migration that completed into one that failed: the record's durability and the run's
> outcome are separate facts.

> **Normative.** A run whose `opened` event stands with no `sealed` event
> reconstructs as *authorised, sending entered, extent undeterminable* — never as no
> egress, and never as a completed one, **and this reading does not vary with why the
> seal is missing**. No lane, no surface and no exit measurement treats a missing seal
> as the absence of an act, and none infers the extent from the `opened` event's
> disclosed counts, which state what was *authorised* and not what was sent.

**The order is the whole of it.** A record written at the commit point records
nothing when the run is killed halfway, which is the case that matters most: an
operator who loses power after twelve thousand records have been sent has had
twelve thousand records sent. The disclosure ADR-0104 §4 requires already sits at
exactly this point — `service/reembed.py`'s `_run_locked` prints the store, the
models and the counts and only then calls `Reembedder.run` — so the write-ahead
point is a moment the design already has, not one this ADR invents.

**The two write failures are treated differently, and the asymmetry is the whole
design rather than an inconsistency.** A failed `opened` write happens while nothing
has left the device, so refusing costs the operator a retry and loses nothing — the
migration is resumable by ADR-0104 §2, and the disclosure has already told them what
they were authorising. A failed `sealed` write happens after records have been sent,
where there is nothing left to refuse: the egress is in the past, and aborting the
process would only discard the run's remaining work. What is available in the second
case is to say so, which the clause requires, and to leave the record in the one state
that is true — unsealed, meaning the extent is not known from the file. Treating a
seal failure as fatal would trade a recoverable ignorance for an unrecoverable one.

**Sealedness is read off the file and not off the process's belief, which is what
keeps the two answers from disagreeing.** A `sealed` line that was appended but not
confirmed durable is *in the file*, so a reader joins it to its `opened` line and gets
the outcome and the counts; calling that run unsealed because the writer's `fsync`
returned an error would give one answer to the process and a different one to anyone
who opened the file a second later. The warning is about the future — the line may not
survive a power loss — and if it does not survive, the file after the restart holds no
seal and the run is unsealed then, by the same rule, with no reinterpretation
required. Requiring completeness and well-formedness is what makes that rule total: a
torn final line from an interrupted write is not half a seal, it is not an event at
all.

**A seal that cannot be written is why the unsealed reading may not be refined.**
It would be tempting to let a surface say "this run completed, we merely failed to
record it", on the strength of the process having reached its exit. Nothing durable
supports that sentence: the claim would rest on a report printed to a terminal, which
is exactly the substitute for a record that Alternatives refuses ADR-0104 §4's
disclosure for. So the file's reading is fixed by what the file holds.

**Stating the indeterminacy rather than resolving it is ADR-0185 §1's move.** There,
a `FAILED` read leaves opened-ness undeterminable and §10 excludes it from the
reconstruction claim rather than asserting it either way. Here a `SIGKILL` or a
power cut leaves the extent undeterminable in the same fashion, and the same answer
applies: say what is known, refuse to say what is not, and make sure the shape that
is known — *this began* — is the one that survives.

### 6. How this relates to #1503, and what it does not pre-empt

> **Normative.** This ADR decides nothing about whether an egress that **was**
> resolved by the permission layer gains an execution record, and no lane cites it
> for that. #1503 owns that question and the milestone-24 exit ruling owns the
> reading of the exit's wording.

**The two cases are separated by a property, not by a preference.** #1503 is about
acts that have a resolution and whose execution the trail cannot confirm: a
resolved `ALLOW` that ran once, ran twice or never ran leaves the same rows. This
act has an execution and will never have a resolution — the permission layer was
not running and no row for it exists or ever will. The sets do not overlap, and a
mechanism for one is not a mechanism for the other.

**It stands whichever way #1503 goes.** If the exit is read as "every egress
*decision* is reconstructible", this act contributes no decision and the reading
leaves it untouched — but the obligation to record it does not come from the exit
wording, it comes from ADR-0004 §7, which is about side-effecting acts and does not
turn on whether the permission layer saw them. If instead the invocation contract
gains a consume-on-execution step and the trail gains an invocation record, that
row is minted at the invocation seam (ADR-0016 §7, ADR-0014 §7's exactly-once debt)
by a running hub against a resolution that exists. Nothing about it reaches a
process running with the hub stopped and no resolution to consume.

### 7. What no surface may do with this record, and why no surface is decided here

> **Normative.** This record is not a `PermissionDecision`. No surface renders it
> through any operation ADR-0186 decides, lists it among the rows of a listing or an
> export, counts it in a bound stated over those rows, or presents it as a ruling.

> **Normative.** No user-facing surface for this record is decided here. It is
> deferred, and it fires with the same lane that lifts §8's gate.

ADR-0186 §8's bars are stated over rows of the store its §1 governs, and every one
of them stays exactly as ratified: nothing here adds a row to that store, so nothing
here puts a transmission where §8's third clause forbids one. The first clause above
is the converse bar, and it exists because the tempting shortcut for a future surface
is to merge the two lists — at which point either this record is rendered as a
ruling, which is false, or the rulings are rendered as transmissions, which §8
forbids.

**Deferring the surface leaves nothing unreachable.** §3's file is in the data
directory, is human-readable, and is copied by the same act that exports it, so
ADR-0004 §6 is satisfied for this record to the same extent it is for the file's
neighbours. What a rendered surface would add is convenience, and it should be
designed together with whatever else the milestone-24 exit ruling and #1503 leave
standing, rather than ahead of them.

### 8. The gate that fires the implementation, and it is the same gate that closes the residue

> **Normative.** No `EmbedderKind` member whose `Embedder` sends text off the
> device is added to ADR-0104 §4's composition-root allow-list, and no such member is
> given a construction branch that could be reached with the flag set, until §§2–5's
> record is implemented and covered by tests. The implementing lane is fired by the
> first cloud `Embedder`, and until it fires nothing here is owed.

This is what makes the residue **closed** rather than merely scheduled. ADR-0104 §4
already refuses every member absent from the allow-list, so the act is unreachable
today; this clause says the allow-list may not be widened to reach it while the
record is missing. There is no window in which an authorised hub-down cloud egress
can happen unrecorded, because there is no window in which it can happen.

It is stated as a bar on the allow-list rather than as a task on a backlog for the
reason ADR-0104 §4 gave for the allow-list itself: a member "added later is refused
until somebody adds it deliberately", and the deliberate act is exactly where a
condition is cheap to enforce and impossible to forget.

**This narrows nothing ADR-0104 §4 decided, and the distinction is worth stating
here rather than only in §10.** §4's authorised path is untouched: the act stays
authorisable, the flag still lifts the refusal, the disclosure still precedes the
first record, and an operator who reaches the path gets exactly the migration §4
describes. What acquires a precondition is the *widening of the allow-list* — an act
§4 mentions only to say what happens when it has **not** been performed ("a member
added later is refused until somebody adds it deliberately"). That sentence is a
statement about the mechanism's fail-closed default, not a grant of permission to
widen, and §4 nowhere says that deliberateness is the only condition that will ever
attach. So no clause of §4 becomes false and none is read more widely; another
obligation is joined to it from here. §10 applies ADR-0082 §1's test to it in terms.

### 9. What this pre-registers for milestone 24

> **Normative.** This lane pre-registers **one figure and no live arm**: the number
> of authorised hub-down cloud egresses performed without a §§2–5 record is **zero**,
> and it is zero by construction because §8's gate makes the act unreachable. A run
> that reported milestone 24's exit met or unmet on the strength of this ADR would be
> reporting on an act the tree cannot perform.

> **Normative.** ADR-0185 §10's pair stays the pair for milestone 24's exit as it
> will actually be measured. Whether "the audit trail" acquires a third member is
> the question of the lane §8 fires, and it is not decided here.

ADR-0187 §7 set the obligation to say what a lane pre-registers rather than leave a
gap someone later reads as an omission, and this is the honest answer: the roadmap
lists #747 under milestone 24 because that is where the decision was scheduled, and
the decision is a rule about a future act. The second clause is the reason no record
is owed on ADR-0185 — §10's sentence stays true for every act the milestone can
measure, and the moment it would stop being true is the moment §8's gate lifts, when
the lane that lifts it will be the one holding the question.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**No record is owed on any earlier ADR: every change here is a stacked addition.**
ADR-0082 §1's test is whether a reader holding only the earlier ADR would now act
differently or read one of its clauses more widely.

- **ADR-0104.** §4's three normative clauses are untouched — the refusal, the
  exhaustive construction, the flag and the disclosure all bind exactly as ratified,
  and a reader of §4 alone still refuses every absent member, still refuses a member
  with no construction branch, and still requires the flag before an authorised run
  proceeds. §8 above joins a condition to the *widening of the allow-list*. **The
  one sentence of §4 that touches widening is the place to apply ADR-0082 §1's
  test**, and it is applied rather than asserted: "The allow-list is enumerated by
  name, so a member added later is refused until somebody adds it deliberately."
  That is a statement of the mechanism's fail-closed default — it says what happens
  to a member nobody has added — and it neither grants permission to widen nor
  declares deliberateness the only condition that may ever attach. After §8 the
  sentence is still true word for word, and a reader acting on it does the same
  thing: refuse the unlisted member. So the earlier ADR's sentences "all stay true,
  merely joined by another obligation stated elsewhere", which is ADR-0082 §1's own
  description of a stacked addition, and no record is owed.

  **This is deliberately not declared a partial supersession.** ADR-0070 §3's shape
  requires that a *part of the earlier decision be replaced*, and §8 replaces
  nothing: the allow-list mechanism, the refusal, the exhaustive construction, the
  flag and the disclosure all continue to operate exactly as ratified, and §8 above
  says so in terms. ADR-0082 §1 is explicit that "the test controls, not the label",
  so marking ADR-0104 `Partially superseded` while every clause of it still binds
  would put a wrong record on a live decision — which is the failure ADR-0082 §1
  names, arriving from the cautious direction rather than the careless one.

  **The absence of a record here is a finding, not a deferral.** Were one owed, it
  would be written in this change and not left for ratification: ADR-0184 §11 puts a
  record in the commit that authors the clause it records, because "a record and the
  clause it records are one judgement", and ADR-0186 §13 works that placement rule
  through for a case where it came out the other way. So a reader should take this
  section's conclusion as load-bearing — the test was applied to a named sentence and
  came out "stacked addition" — rather than as a step this lane postponed.

  The Consequences bullet #747 quotes describes a state and imposes nothing —
  ADR-0104 is a marked ADR, and ADR-0089 §3 is that unmarked text supplies no
  obligation — and it stays a true account of what ADR-0104 itself decided. It is
  also the sentence that invited this ADR.
- **ADR-0185.** §10's pair stays the pair (§9's second clause), and its Alternatives
  reasoning is *used* here rather than narrowed. Nothing is added to
  `SourceReadTrail` and no clause of §§1–14 is read more widely.
- **ADR-0186.** §8's bars are stated over rows of the store its §1 governs; §7 above
  adds a converse bar over a different artefact and takes nothing away. A reader
  holding ADR-0186 alone renders the same rows the same way.
- **ADR-0021.** §4 is quoted and relied on. `AuditTrail` gains no method, no row
  shape and no writer, and its write-once and atomicity clauses are untouched.
- **ADR-0004.** §7's recording half acquires a discharge for one act; its sentence
  stays true and every other obligation under it stays open. §2's residency clause
  and §6's erasure right are satisfied by §3 and neither is narrowed.
- **ADR-0083.** Ruling 4 and §10 are the ground §2 and §3 stand on. No database is
  added, no second opener is created, and the lock discharge is used as written.
- **ADR-0017.** §1 is cited for the boundary and not touched; this ADR decides a
  record, not a permission to transmit.

**No `core/` surface is decided.** No Protocol, no `core/types.py` model, no field
on an existing one, no enum member. Golden rule 5 is not engaged, ADR-0015 §5's
contract-ADR clause does not bind, and the required review set for this PR is the
adversarial lens alone.

## Consequences

**Easier.** ADR-0104's named residue closes, and it closes in the direction that
costs nothing today: #747's question has an answer, and the answer is enforced by a
gate rather than by an intention. The implementing lane, when a cloud `Embedder`
arrives, inherits a decided shape instead of re-deriving one under time pressure
beside a feature. And "what left this machine, and on whose say-so" acquires an
answer for the one act in the system for which the permission layer is structurally
unable to give one.

**Harder.** The data directory gains a file that is not a database and is not the
hub's, which is a second kind of durable artefact for an operator to know about and
for any future backup or export tooling to remember. A future surface that wants to
show the user "everything that left" now has two sources with different shapes and
no join between them — the same shapelessness ADR-0185 §10 already recorded between
a read row and an egress row, arriving a third time. And §2's second clause is a
constraint the implementing lane must carry through a layer boundary: the fact that
the refusal was lifted lives at the composition root, and the write happens at the
entry point, so the two have to be connected deliberately rather than by reading the
flag twice.

**What would trigger revisiting this.** A cloud `Embedder` landing, which is §8's
gate and the moment every clause here stops being hypothetical. A second offline
tool — ADR-0083 §10 says the re-embedding migration is "the first and for now the
only one" — which would make this a class rather than a case, and at which point the
file's shape deserves to be decided for the class. A consumer that needs to *read*
this record programmatically, which is when §3's "no Protocol" trade goes the other
way. And either resolution of #1503, which would give the corpus a second answer to
"what records an execution" and is where the two should be reconciled.

## Alternatives considered

**The migration writes to the audit store directly while it holds the lock**
(#747's first candidate). Refused on §1's fabricated-declaration ground, which is
fatal on its own: there is no `ToolDefinition` and inventing one poisons the store's
premise. It also puts a writer of the permission layer's store outside
`permissions/` — ADR-0004 §7 gives that store to `permissions/` — and it opens a
database ADR-0083 ruling 4 gives to the hub, for a benefit §3 shows is unneeded.

**The hub folds a left-behind artifact into the audit trail at its next start**
(#747's second candidate, and the shape a reader is most likely to propose). Its
first half is adopted: the migration does leave a durable record beside the store.
Its second half is refused twice. The fabricated declaration is unchanged by who
performs the fabrication — the hub composing a `PermissionDecision` from a file is
still a `PermissionDecision` no permission layer decided, and it is hearsay rather
than first-hand, which is a strictly worse record than the file it was built from.
And it makes the record's arrival conditional on the hub starting again, which §2
shows is unbounded and may never happen. It would also be the tree's first
startup-time ingestion of another process's artifact — Context records that no such
pattern exists — so the cost is a new class of startup step, on the path ADR-0083 §6
already makes fail-closed, for a record §3 shows needs no store. There is a real
cost to the refusal — the surface ADR-0186 built would have rendered the row for
free — and §7 pays it knowingly.

**The flag plus ADR-0104 §4's disclosure is ruled sufficient, and ADR-0004 §7 is
amended for hub-stopped acts** (#747's third candidate). Refused. A disclosure
printed to a terminal that has since been closed is not a record of anything: it
cannot be exported, cannot be read after the fact, and is gone the moment the
scrollback is. And the amendment would create a class of side-effecting act that
escapes the audit obligation *by being performed at the right moment*, which is an
exception shaped like an incentive. ADR-0004 §7 is better served by an act that
records itself than by a clause saying it need not.

**A durable store of its own — a twelfth database in the data directory — with a
Protocol, a conformance suite and a canonical
fake.** Refused for now, and §3 gives the arithmetic: one writer under an exclusive
lock, no reader, no query, no bound, and a handful of events in a lifetime. A
Protocol with no consumer is machinery ahead of demand, it is a `core/protocols.py`
change owing its own ADR under golden rule 5, and it reintroduces the ownership
problem the file exists to sidestep. The trigger is named in Consequences: the first
consumer that must read this record programmatically.

**Refuse the cloud target permanently and delete ADR-0104 §4's authorised path.**
Refused as out of scope and as relitigation. ADR-0104 §4 decided that the act is
authorisable by an operator who is told exactly what they are authorising, and this
ADR is about what records it, not about whether it may happen. §8 constrains *when*
the path becomes reachable and does not close it.

**Record the act, but only on success.** Refused by §5, and it is worth naming
separately because it is the natural way to write the code. The case the record
exists for is precisely the one where the run did not finish: an interrupted upload
has already sent everything it sent, and a record written at the commit point
records nothing about it.
