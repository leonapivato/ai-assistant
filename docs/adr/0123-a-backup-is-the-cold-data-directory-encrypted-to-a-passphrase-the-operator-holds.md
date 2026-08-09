# 123. A backup is the cold data directory, encrypted to a passphrase the operator holds off the machine

- Status: Proposed
- Date: 2026-08-09
- **Decides no `core` surface.** No Protocol in `core/protocols.py` changes and no
  type, enum member or constant is added to `core/types.py` (§10). Golden rule 5
  and ADR-0015 §5 therefore do not bind the ordering, and the implementation lane
  this decision briefs is not gated on a contract PR — only on this one.
- **This ADR amends nothing and supersedes nothing.** §12 applies ADR-0082 §1's
  test to each of the seven places where a record looks owed, and records why none
  is.

## Context

### The fragile spot is a fact about the deployment, not a risk assessment

`docs/roadmap.md`'s leg 9 makes backup and restore the leg's first slice rather
than a mid-leg one, and states the reason: "Daily accumulation is about to happen
on one laptop holding the only copy of the store; that is the plan's single
fragile spot, and it is fragile from the day accumulation starts rather than from
the day the leg ends." The operator's ruling behind it is #879, and #882's owner
direction fixes the shape of the remedy: the inhabitation arc completes without a
dedicated always-on machine, so restore's story has to work from one commodity
laptop to another and cannot wait on hardware that does not exist.

Two properties are ruled and are not reopened here. The backup is **encrypted** —
the roadmap's leg 9 entry carries it forward from the later-arc entry it replaced,
and the scheme is this ADR's to choose while the property is not. And the leg's
exit test, which is the ruling's own, is what the artifact has to satisfy:
"losing the laptop does not lose the model."

That exit test is narrower than "losing the laptop loses nothing", and the
difference is load-bearing below. The model is the accumulated Tier 1 record
(ADR-0004 §1). It is not the machine's credentials, and it is not the operational
telemetry.

### There is no ratified layout to snapshot, and the count in the corpus has already drifted

ADR-0083 §2 makes `Settings.data_dir` the hub's data directory and §1 names one
path inside it, `hub.lock`. Beyond those, **ADR-0083 names no file in the data
directory at all** — no layout, no database filename — and where it counts the
stores it says five: ruling 4's "the hub owns the five SQLite databases
exclusively", §10's "the five databases", §12's "five stores read the same way".

`app/composition.py` opens seven today: the trace store, the memory store, the
audit trail, the plan store, the conversation store, the deferral store and the
source-grant store. ADR-0083 is dated and correct as history, and nothing here
asks it to be corrected — ADR-0089 §5 and `CONTRIBUTING.md` → "Cite in form, and
mark what binds" both hold that an older document is a record rather than a defect
to fix. But the drift is a fact
this decision has to be built on rather than around, because it is exactly the
failure mode an enumerating backup has: **the count in the most authoritative
document about the data directory is already wrong by two, and nothing detected
it.** A backup that carries its own list of stores would have been wrong by two in
the same way, and the symptom would have arrived at a restore.

### What the corpus has already decided that bears on this

**The offline-tool shape is settled and has three members.** ADR-0083 §10 —
"Everything else that needs the data goes through the API, or runs while the hub
is stopped. An offline tool … takes the same instance lock, which serialises it
against the hub by construction and needs no new mechanism" — authorises the
shape; ADR-0104 §5 fixes the placement for the re-embedder and ADR-0120 §9 repeats
it for the measures report, which calls itself "the third of that family".

**Export is one-way and import was deferred, twice, by name.** ADR-0007 §3 rules
that `export` "is **one-way** — it reflects what the store holds and will use; it
does not carry embeddings … and importing a snapshot back is out of scope here",
and §5 defers "**Import / restore** of an exported snapshot" outright. ADR-0039
extends the same posture to plans — `PlanStore` has "no `import`, `restore` or
`load`", so "no code in this system ever validates a `PlanExport` it did not just
construct" — and hands the versioning question to a future ADR by name.

**Whole-file restore is already a supported path, and partial restore is already a
fault.** ADR-0064 put the execution-ordinal witness in the plan store's own `meta`
table for exactly this reason: "restoring the database file rolls the counter and
the mark back **together**, so they still agree and the store opens … A witness
kept anywhere else — a sidecar file, a separate table restored on its own
schedule — would turn every restore into a refusal." Its Consequences name
"whole-file backup/restore" among the paths it enumerates and tests. The same
mechanism converts a per-table restore into a `PlanningError`.

**Tier 0 is not in the data directory.** ADR-0004 §3 puts secrets and credentials
in the OS keyring, "never in the memory database, never in a committed file", read
through `SecretStore`.

**Encryption at rest exists and its custody model is the one this artifact cannot
use.** ADR-0004 §4 supports SQLCipher for the memory store with "the key held in
the OS keyring", off by default, and names the cost in as many words: "a lost key
means unrecoverable memory". Its baseline is elsewhere: "**Baseline** protection
assumes the host uses OS full-disk encryption."

**One store is under an absolute no-egress clause.** ADR-0119 §12: "No
`EvaluationTrace` leaves the device, by any route, under any setting. There is no
opt-in that enables trace egress, and this ADR creates no designated seam under
ADR-0017." That is written over an *object* rather than over a component, and
"by any route" is wider than anything ADR-0017 §1 says.

**Egress is a device-crossing test stated over components.** ADR-0017 §1: "User
data may leave the device only from `models/` or from a designated integration
seam inside `tools/`; every other egress is a bug." ADR-0084 §1 reads it as a
device test — a loopback listener "engages neither clause" while "a hub on a
dedicated machine serving a spoke on a laptop *is* user data leaving the device".
Neither text says anything about an operator carrying their own file to their own
other machine; the question is unaddressed rather than decided.

### The question nobody has answered is custody, and it is the one that decides everything

ADR-0004 §4's model — a key in the OS keyring — is correct for a database that
never leaves the machine and is exactly wrong for a backup, because the machine is
what the backup exists to survive losing. A key that lives only on the laptop being
backed up protects nothing that matters: the thief gets the artifact without the
key, which is the case encryption is for, and the owner whose laptop died gets the
artifact without the key too, which is the case the backup is for. Getting this
wrong produces an artifact that passes every test and is worthless on the day it
is needed.

This is also the first honest test of `VISION.md`'s portable context-graph claim,
which nothing in the system has yet had to satisfy.

## Decision

### 1. A backup is a cold copy of the whole data directory, not a set of per-store exports

> **Normative.** A backup's unit is the hub's data directory. The backup tool
> copies every regular file under `Settings.data_dir`, at any depth, byte for byte
> and under its path relative to that directory, except what §3 excludes. It
> carries no list of stores and opens no store to produce the copy.

> **Normative.** The backup tool refuses, before copying anything, if the data
> directory holds an entry that is neither a regular file, nor a directory, nor one
> §3 excludes by name — a symbolic link included. It never follows a symbolic
> link.

> **Normative.** Restoring a backup restores every file the artifact carries. The
> tool offers no way to restore a subset of them, and no way to restore part of any
> one file.

**Per-store exports are the wrong artifact, and the corpus says so three times
rather than once.** `MemoryStore.export` "does not carry embeddings", so a store
rebuilt from one cannot serve search until every record has been re-embedded — an
unbounded CPU-bound job whose own ADR describes it as "one on-device embedding per
record" with time "not bounded and … not meant to be" (ADR-0104). It also excludes
expired-but-unpurged rows (ADR-0007 §3), so a round trip silently forgets records
the store still holds. And nothing in the system can read an export back:
ADR-0007 §5 defers import, ADR-0039 records that "no code in this system ever
validates a `PlanExport` it did not just construct" and that "a v1 export is not
readable by this contract at any version". Building disaster recovery on a surface
with no reader, no embeddings and a lossy filter is three decisions this ADR would
have to take that the corpus has deliberately left open.

**The file copy has a reader already, and it is the one that is tested.** ADR-0064
chose the plan store's witness placement so that "restoring the database file rolls
the counter and the mark back **together**", and enumerates whole-file
backup/restore among the paths its tests cover. This decision uses the path that
was designed for it rather than opening the one that was closed.

**Cross-store consistency is obtained by construction and not defended.** The seven
stores carry real references across their files — a `ConversationTurn` names an
`EpisodicMemory` by `episode_id` and the two live in different databases — and
ADR-0083 §12 records that exclusivity does not close ADR-0074 §8's cross-store
window under a process death. A per-store scheme reading seven stores in sequence
would introduce a *second*, larger skew of its own, between the first store read
and the last — a window opened by the scheme itself, present on every run, and
proportional to the time seven stores take to read. A file copy opens no such
window of its own: the only writer that could produce one is a writer outside the
tool, and §2 is what stops the hub from being it and what refuses a copy that a
non-cooperating writer disturbed anyway.

The residual is stated rather than claimed away. A backup taken after a process
death captures whatever cross-store state that death left, faithfully; it does not
repair it. ADR-0083 §3's start-time sweep is what repairs it, and it runs on the
restored directory the first time a hub starts against it, exactly as it runs after
any other crash.

**Not enumerating is the point of the clause, not a simplification of it.** An
inclusion list fails silently and in the unsafe direction: a store added by a later
lane without a corresponding edit here is absent from every backup taken
afterwards, and the absence surfaces at the restore, which is the worst available
moment. ADR-0083's own count is the evidence that this is not hypothetical. §3's
exclusions fail in the other direction — a store added later is *included* by
default, which costs artifact size and never costs data.

### 2. The backup runs offline under the hub's instance lock, and refuses a source it cannot show stayed still

> **Normative.** The backup tool takes `<data_dir>/hub.lock` before it reads any
> file in the data directory and holds it until it exits. A contended lock is
> refused immediately, with a diagnostic naming the data directory and the lock
> path; the tool does not retry.

> **Normative.** The backup tool refuses, before copying anything, if any SQLite
> sidecar — a `-journal`, `-wal` or `-shm` file — lies beside any file it would
> copy. The diagnostic names the sidecar and states the remedy: start the hub and
> stop it cleanly, then run the backup again.

> **Normative.** For each file it copies, the backup tool records the device,
> inode, byte length and modification time before reading it and — for a SQLite
> database — SQLite's own file change counter. After the whole copy completes it
> re-reads all of them, and refuses the backup if any has changed. No artifact is
> written on that refusal.

This is ADR-0104 §5's clause with the subject changed, and every term of its
reasoning transfers: the holder of a contended lock is a hub that is meant to be
running, the operator's next act is to stop it, and retrying would turn a one-line
instruction into a wait. ADR-0083 §1's bounded retry is for a second *hub*, whose
holder may be draining under a supervisor that restarts it; neither condition
applies to an operator-invoked tool.

**The sidecar refusal is about consistency of the copy, not of a rename, and that
is why it is one check here where ADR-0104 §3 needs two.** A `-journal` beside a
database means a process is writing now or died mid-transaction; copying the
database without it yields a torn file, and copying both yields a pair whose
recovery is a coin flip against whether the copy caught them in order. ADR-0104's
second check — refusing a store whose header says WAL — is aimed at a hazard this
tool does not have: renaming over a database whose `-wal` holds committed pages
orphans those pages, whereas a cleanly closed WAL database has checkpointed
everything into the main file and has no `-wal` beside it to find. The sidecar
check therefore covers the copy on its own, under WAL or the rollback journal that
ADR-0083 §12 currently keeps.

**The lock does not make the directory quiescent, and the third clause is what
narrows the gap rather than papering over it.** ADR-0083 §1 says outright that the
lock is "**advisory**" and "stops a second *hub*, not an arbitrary process", so a
`sqlite3` shell somebody left open on their own machine can write to a file after
the sidecar scan has passed and while the copy is running — and the sidecar it
creates while doing so appears after the one moment the scan looked. The
before-and-after fingerprint is the same instrument ADR-0104 §2 uses against the
same hazard, applied per file across the copy instead of across a resumption, and
its stat fields are insufficient for the same reason ADR-0104 gives — a same-sized
write inside one timestamp tick moves none of them — which is why SQLite's file
change counter is read beside them.

**It narrows the window; it does not close it, and it is not offered as closing
it.** A writer that modifies a file and restores its length, mtime and change
counter defeats it, and a write landing between the final re-read and the artifact
being sealed is outside it. This is ADR-0104 §3's disposition stated in its own
terms rather than a stronger claim made quietly: what the check actually catches is
a non-cooperating opener on a single-user machine, which is the likely case here as
it was there. The direction is deliberately conservative — a false refusal costs a
rerun, and a false acceptance costs a backup that is torn in a way no restore can
detect, because a torn file's own digest is computed from the torn bytes.

**Refusing after a crash is the right answer even though it is the moment an
operator most wants a backup.** The remedy in the diagnostic is short and it is
the same act that makes the store consistent: a hub started against a hot journal
rolls it back, and a hub stopped cleanly leaves no sidecar. Copying a torn database
and calling it a backup would be worse than refusing, because the fault would be
discovered at the restore instead of at the backup.

**An online snapshot was available and is foreclosed rather than disfavoured.**
Reading the seven databases from a second process while the hub serves would
require that second process to open them, and ADR-0083 ruling 4 — "the hub is the
only process that opens the … databases, and the API is the only door" — forbids
exactly that. Taking it would need an amendment to ADR-0083, to buy per-database
consistency while still leaving the cross-store skew §1 describes.

### 3. Two files are excluded, each by the clause that requires it, and the list is a refusal list

> **Normative.** The backup excludes the trace store. No `EvaluationTrace`, and no
> file holding one, enters a backup artifact.

> **Normative.** The backup excludes `hub.lock` and `hub.sock`.

> **Normative.** A later lane that places in the data directory a file subject to a
> clause forbidding it to leave the device returns to this decision and adds it to
> the exclusions above. Until it does, this ADR authorises no such file to be
> written there.

**The trace store is excluded because ADR-0119 §12 is absolute and this ADR does
not narrow it.** "No `EvaluationTrace` leaves the device, by any route, under any
setting" is stated over an object rather than a component, so the reading that
rescues a loopback socket in ADR-0084 §1 — that the rule governs what code
transmits — is not available here: an artifact whose whole purpose is to be carried
to another machine is a route. Reading "by any route" more narrowly, to admit an
encrypted file the operator carries, would be narrowing a ratified clause this ADR
does not supersede, which is the move ADR-0017 §5 exists to refuse.

**The cost is real and it is named rather than minimised.** Losing the laptop
loses the measurement history — leg 8's measures, and with them the before-and-after
evidence of #829's consolidation arming, which is a one-shot natural experiment
that cannot be re-run. What makes this the right trade rather than merely the
compliant one is that the leg's exit test is "losing the laptop does not lose the
**model**", and a trace is by ADR-0119's own construction not the model: it
"references what it is about and never contains it", it is Tier 2, and it is
already subject to a retention horizon that deletes it in the ordinary course. A
store the system is designed to forget is not one a disaster-recovery artifact must
preserve. If that trade stops being acceptable, the remedy is an ADR revisiting
ADR-0119 §12, not a wider backup taken under a narrower reading of it.

**A restored directory with no trace store is a ratified state, not a gap.** The
hub creates the store on start, and ADR-0120 §8 already rules what the measures
report does over the result: "Over an **empty** retained stream the report states
that the stream is empty, states no measure and no diagnostic, and applies no
window validation."

**The lock and the socket are excluded because they are process state and not
data.** ADR-0083 §1 makes the lock an advisory `flock` whose meaning is entirely in
the kernel — "a held lock always means a live holder" — so the file's bytes grant
nothing, and the pid the holder writes into it is a diagnostic hint that a restored
copy would make stale. `hub.sock` is not a regular file at all, and ADR-0083 §14
item 6 already makes removing it part of shutdown; it is named here rather than
left to §1's copy rule because §1's second clause refuses an entry that is neither
a regular file nor a directory, and a socket left behind by a killed hub would
otherwise refuse every backup taken before the next clean start.

**The forward clause is what keeps the exclusion list from being the enumeration
§1 rejected.** It binds the lane that would create the problem rather than
requiring this list to anticipate it, and it fails in the safe direction if that
lane forgets: the file is backed up, which costs size and possibly an egress
question, rather than silently dropped.

### 4. The artifact is one encrypted file in the age v1 format

> **Normative.** A backup artifact is a single regular file: a `tar` stream of the
> copied files and the §6 manifest, encrypted whole in the **age version 1** format
> with an scrypt passphrase recipient. The tool writes no other artifact and no
> plaintext copy of the stream.

> **Normative.** The tool depends on no executable outside the Python environment
> to write or to read an artifact. Any library it uses to do so clears
> `CONTRIBUTING.md`'s Python 3.14 filter — `requires-python` and a real wheel,
> checked at pin time — and its adoption carries the justification that document
> requires.

> **Normative.** Before this decision's implementation is complete, an artifact
> written by this tool is decrypted and unpacked by an independent implementation
> of the age format, and an artifact written by that implementation is read by this
> tool. That check is a development obligation and never a runtime dependency.

**A single authenticated file is what makes tampering and truncation a refusal
rather than a bad restore.** age's construction authenticates its header and every
chunk of its payload, and marks the final chunk, so a truncated artifact, a flipped
byte and a spliced-in chunk all fail to decrypt instead of yielding a shorter or
altered directory. That covers the integrity half of "verify before replace"
(§8) with the format rather than with a check somebody has to remember to run.

**Adopting a standard format rather than defining one is the whole of the choice,
and the reason is recovery, not taste.** The plausible alternatives each fail on
the machine where it matters:

- *A container format of our own.* Same implementation cost, same chunked-AEAD
  reasoning to get right, and one property strictly worse: nothing but this project
  can open it. A recovery machine with a working `age` or `rage` binary can open an
  age file when this tool is the thing that is missing, and a format nobody else
  implements has no such fallback.
- *Shelling out to `age`, `gpg` or `openssl`.* Puts an external binary on the
  restore path, which is the one path that runs on a machine whose software the
  operator has not finished installing. A dependency that is present when the backup
  is taken and absent when it is needed is not a dependency that has been paid for.
- *SQLCipher, the corpus's existing encryption.* Wrong object and wrong custody: it
  encrypts a live database in place with a keyring-held key (ADR-0004 §4), produces
  no portable artifact, covers one store of seven, and its Python bindings are a
  3.14 wheel question this ADR would be taking on for nothing.

**The interoperability check is a normative clause because it is the only thing
that converts the compatibility claim into a fact.** An implementation of age v1
that round-trips against itself proves nothing about the recovery path the format
was chosen for; one that round-trips against a foreign implementation proves the
whole of it. Running it in development and not at runtime is what keeps the second
bullet above true.

### 5. The key is a passphrase the operator holds off the machine, and never machine-bound material alone

> **Normative.** The artifact's key is derived from a passphrase. The tool never
> derives a key from machine-bound material — a keyring-generated secret, a host
> identifier, a file in the data directory — whether alone or as the sole secret
> input.

> **Normative.** Where the tool generates a passphrase rather than receiving one,
> it displays that passphrase to the operator in the run that generates it, and
> refuses to write the artifact if it cannot. It generates a passphrase at most
> once for a given store of cached passphrases.

> **Normative.** The tool may cache the passphrase in the OS keyring so a later run
> is unattended. It never treats the cache as the passphrase's custodian: every run
> that uses a cached passphrase states that a passphrase held only on this machine
> does not survive the loss of this machine.

> **Normative.** Restore never reads the OS keyring, and never requires anything
> from the machine that took the backup.

**This is the clause the artifact's usefulness rests on.** ADR-0004 §4's custody
model is right for its object and wrong for this one, and the failure is silent in
both directions that matter: an artifact encrypted to a keyring-held key looks
identical to a correct one on the day it is written, and is undecryptable on the
day the laptop it was written on stops booting. The property this ADR needs is that
the artifact and its key have independent fates, and the only custodian with a fate
independent of the machine is the person.

**The keyring cache is permitted because the alternative is worse than the risk.**
A backup that requires a human at a prompt is a backup an operator takes twice and
then stops taking, and an unautomatable tool cannot satisfy leg 9's exit test over
any span of ordinary days (§10 puts the scheduling itself outside the hub). A
cached passphrase is a Tier 0 secret in the OS keyring, which is precisely where
ADR-0004 §3 puts one, so the cache breaks no rule. What it must not do is become
the *only* copy, and the disclosure clause is what keeps the operator's obligation
in front of them rather than in this document.

**Displaying a generated passphrase is a refusal, not a courtesy.** A tool that
generates a key, files it in the keyring and reports success has produced an
artifact whose only key is on the machine the artifact exists to survive — the
exact failure this section is about, arrived at by a convenience. Refusing to write
the artifact when the passphrase cannot be shown is the fail-closed form.

### 6. The artifact carries a manifest, and it carries no Tier 0

> **Normative.** The artifact contains a manifest recording: the artifact format
> version; the instant the backup was taken; the project version that wrote it; and
> for each copied file its name, its byte length and a SHA-256 digest of its
> contents.

> **Normative.** The manifest carries no record content, no record identifier, no
> subject and no correlation identifier.

> **Normative.** The backup tool reads no secret store, and no Tier 0 value enters
> a backup artifact — including the passphrase, the key derived from it, and any
> material from which either could be recovered.

**The manifest answers completeness and provenance; it deliberately does not
answer integrity.** §4's format already makes a corrupted artifact undecryptable,
so per-file digests are not what catches a flipped bit. What they catch is the
question a restore actually has to answer — *is what I just materialised what was
put in* — and what the version and instant catch is §8's refusal and the
operator's "which backup is this". Recording it explicitly is cheaper than
inferring it from a directory listing, and it is what lets §9's verification make a
statement rather than an assumption.

**No Tier 0 is a property of §1's copy rule and is checked rather than assumed.**
ADR-0004 §3 keeps secrets in the OS keyring, so a copy of the data directory
reaches none of them; the tool reads no keyring except §5's passphrase cache, and
that value is an input to the encryption and never a member of the plaintext.
§3's forward clause is what keeps the property true as the directory grows.

**The consequence is that a restored directory is not a working installation, and
that is the correct trade.** The hub comes up with the accumulated model intact and
its provider credentials absent; the operator re-provisions those from wherever
they keep them. What is bought is that a stolen or lost artifact yields no API key,
no OAuth token and no refresh token — the tier whose compromise reaches services
the assistant has nothing to do with. ADR-0004 §6 makes deletion span Tier 0 and
Tier 1 "together"; this artifact deliberately spans one, because deletion and
recovery are not symmetric acts and the asymmetry runs in the safe direction.

### 7. Restore builds a fresh data directory and replaces nothing

> **Normative.** Restore materialises into a target directory that is absent or
> empty, and refuses any other target. It never merges into, writes over, or
> deletes an existing data directory.

> **Normative.** Restore takes `<data_dir>/hub.lock` in the target directory before
> it materialises anything and holds it until it exits, on the same terms as §2.

> **Normative.** Restore leaves no partial directory behind. Where it refuses or
> fails after materialising anything, it removes what it materialised.

**Refusing a non-empty target is ADR-0104 §1's build-and-swap with the swap left to
the operator.** Nothing that exists is modified, so there is no path — including a
crash — on which a half-restored directory replaces a real one; the operator who
wants the restored directory in the live path moves it there, and the directory it
displaces is still on disk to be examined. That is the same disposition ADR-0104 §3
takes with the retained pre-migration store, and it is right for the same reason:
the case verification cannot cover is the one where the restore was the wrong act.

**Taking the lock on the target is not ceremony.** A supervisor configured to
restart the hub is watching a path, and a directory that appears under it is a
directory a hub will start against — mid-materialisation if nothing stops it.
The lock is what stops it, using the mechanism ADR-0083 §1 already provides rather
than a new one.

### 8. Restore verifies what it can settle, and leaves to the hub what the hub already refuses

> **Normative.** Restore refuses an artifact whose recorded format version is
> greater than the version the tool implements, naming both versions.

> **Normative.** Restore refuses any archive member that is not a regular file, and
> any member whose name is absolute, contains a parent-directory component, or
> resolves outside the target directory. It creates no symbolic link, no device and
> no hard link, and follows none while materialising.

> **Normative.** After materialising and before reporting success, restore verifies
> that the set of regular files present under the target directory, excluding the
> `hub.lock` its own §7 lock created, equals the manifest's set exactly; that each
> file's length and SHA-256 digest equal the manifest's; and that every restored
> SQLite database passes SQLite's own integrity check. Any failure is a refusal
> under §7's third clause.

> **Normative.** Restore performs no check of a store's schema, of its embedding
> model identity, or of any other compatibility between the restored content and
> the build that will serve it.

**The version rule is asymmetric on purpose.** A newer artifact may carry files
and conventions this tool does not know, and materialising them and reporting
success would be asserting a compatibility nobody established — so a greater
format version is refused. An older or equal one is accepted, because bringing a
store forward is a job the system already owns and duplicating it here would mean
two implementations of it that can disagree.

**The one file the manifest cannot describe is the lock the restore itself
creates.** `InstanceLock.acquire` opens the lock path with `O_CREAT`, and
`InstanceLock.release` deliberately does not unlink it — "Removing it would let a
contender that has already opened the same inode take a lock on a file no longer at
that path" — so a target directory that satisfies §7's emptiness rule holds exactly
one file the moment the lock is taken, and holds it still while this check runs.
Excluding it by name is the whole of the reconciliation, and it is stated here
rather than left to an implementer to discover as a restore that refuses itself.

**Leaving compatibility to the hub is a composition, not an omission, and the
mechanism it defers to is legible.** A restored store the running build cannot
serve is detected at startup: ADR-0006 §4 tags every stored vector with the model
that produced it, and ADR-0083 §6 turns a mismatch into an `IncompatibleStateError`
— a deployment fault, exit `78`, supervisor stays down — with ADR-0104 as the
remedy the operator then runs. A restore that tried to answer the same question
would have to reimplement that detection over a directory it has not opened, and
would refuse restores the hub would have handled. Refusing later and legibly beats
refusing earlier and approximately.

**The archive-member rule exists because unpacking an archive is the operation with
the history.** A member named with a parent-directory component, an absolute path
or a symbolic link writes outside the target directory, and this artifact is
unpacked on a machine in a recovery state where a surprise write is least likely to
be noticed. §1's rules put only regular files under relative paths into an artifact,
so the restriction costs nothing an honest artifact needs. What earns it its place
is that the check is on **what was received**, not on what §1 was supposed to have
sent: the artifact arrives from wherever the operator kept it, and an authenticated
format proves it is unmodified since it was written, never that it was written by
this tool.

### 9. A backup is proved by restoring it, and the drill is on a second machine

> **Normative.** After writing an artifact, the backup tool verifies it by
> decrypting it and materialising it into a temporary directory, applying every
> check §8 requires, and removes that directory afterwards. A verification failure
> is reported as a failed backup.

> **Normative.** Where the tool cannot complete that verification for a reason that
> is not a failure of the artifact — no room for the temporary copy, a refused
> temporary directory — it reports the backup as **written but unverified**, names
> the reason, and does not report it as failed.

> **Normative.** This decision is not discharged until an artifact has been restored
> on a machine other than the one that wrote it, by an operator supplying the
> passphrase from their own custody, and a hub has served the restored directory.

**Verifying by restoring is the only verification that answers the question.** A
checksum over a file proves the file is the file; it does not prove the artifact
decrypts, that the archive unpacks, that the manifest matches or that seven
databases open. Each of those has failed in somebody's backup system, and each is
cheap to test at the moment the artifact is written — where a failure costs a rerun
— rather than at the moment it is needed. The cost is a second full copy while the
verification runs, which is the trade ADR-0104 already priced for a personal store
of text and vectors, and it is bounded by the same reasoning.

**Reporting an unverifiable backup as unverified rather than failed is ADR-0104
§3's disposition and it is right for the same reason.** The artifact exists; an
operator told the backup failed would delete it or take another, and what actually
happened is that a check could not run. Two facts, reported separately.

**The drill is normative because the leg's exit test is a claim about a machine
nobody has tried.** Everything above is verifiable on the laptop that wrote the
artifact, and everything above would still pass if the passphrase were irretrievable
or the format unreadable off this host — the two failures the whole design is aimed
at. #882's owner direction supplies the machine: leg 9 is validated with a second
commodity device the owner already has, so this drill needs no hardware that does
not exist. #883 already places the drill in the implementation lane's acceptance;
this clause is what makes it an obligation of the decision rather than of one
lane's checklist.

**The drill does not interact with #829's measurement window and no clause here
constrains it.** Restoring into a fresh directory on another machine touches
neither the live store nor the trace stream, and taking a backup stops and starts
the hub, which is not a configuration change and so partitions no window under
ADR-0120 §8. The residue is that a stopped hub accumulates nothing while the backup
runs, which ADR-0120 §8 already treats as ordinary — "a hub that was down for part
of it" is a declared residue there, not a fault. What #879 keeps out of the window
is the box migration, and this ADR neither performs one nor schedules one.

### 10. The tools are the fourth member of the offline family, and the hub never takes a backup

> **Normative.** Backup and restore each have their own console entry point in
> `ai_assistant/service/`, beside `ai-assistant-hub`, `ai-assistant-reembed` and
> `ai-assistant-measures`, and neither is an `assistant` subcommand.

> **Normative.** The mechanism lives in `ai_assistant/service/` and imports no
> subsystem directly.

> **Normative.** No `AssistantEngine` method, no wire operation and no `assistant`
> CLI command is created for taking or restoring a backup.

> **Normative.** No Protocol in `core/protocols.py` changes, and no type, enum
> member or constant is added to `core/types.py`.

> **Normative.** No part of the hub takes, verifies or restores a backup, and the
> hub never stops itself to allow one. Backup and restore are acts an operator
> invokes.

**The placement is forced rather than chosen, and ADR-0120 §9's argument transfers
term for term.** The entry point must take the instance lock; the lock is
`service/lock.py`; `lint-imports`' "nothing imports the service" contract means the
entry point has to *be* in `service/`; and `service` may import `app` and `core`
(ADR-0083 §8), which is how the other three reach their mechanisms. ADR-0084 §6's
reasoning forecloses the `assistant` subcommand independently: a subcommand lives in
`interfaces`, which would then have to import `service`.

**The mechanism is in `service/` rather than in a subsystem, and that is a
consequence of §1 rather than a preference.** ADR-0104 put the re-embedder in
`memory/` and ADR-0120 put the measures in `evaluation/` because each operates on
one subsystem's store through that subsystem's code. A whole-directory copy opens
no store and belongs to no subsystem: its subject is `Settings.data_dir`, which is
the hub's (ADR-0083 §2), and its whole vocabulary is files, a lock and an archive.
Routing it through the composition root would mean building an engine to copy files
that no engine touches. This is the shape §1 buys — the backup needs no embedder,
no store implementation and no wiring, which is also why it can run against a data
directory this build has never opened.

**"Never automatic" is narrower here than in ADR-0104 §6, and the difference is
deliberate.** ADR-0104 refuses automation because re-embedding spends hours of CPU
on a judgement only a human can make. Backup is the opposite case: an unautomated
backup is the backup that lapses, and leg 9's exit test is about ordinary days
rather than about one deliberate act. What the clause forbids is the *hub*
scheduling it — a resident process that stops itself is a process that decides to be
unavailable, and ADR-0083's supervisor would fight it. A scheduler outside the hub
that stops it, runs the tool and starts it is a deployment arrangement this ADR
permits and does not design, and §5's cached passphrase is what makes it possible.

**The residue is named: whether such a schedule exists is not something this
decision can guarantee.** A tool that can be scheduled and is not is a backup that
lapses, and no clause here detects that. §9's drill establishes that recovery works;
it does not establish that a recent artifact exists on the day it is needed.

### 11. Where the artifact may be written, and what this does not authorise

> **Normative.** The backup tool writes the artifact to a local filesystem path the
> operator names. It opens no network connection, and it transmits the artifact
> nowhere.

> **Normative.** The backup tool refuses a destination inside the data directory it
> is copying.

> **Normative.** This ADR designates no seam under ADR-0017 §1, creates no opt-in
> that would enable egress, and authorises no component to transmit a backup
> artifact.

**The tool is cloud-refusing in the same posture ADR-0120 §10 takes, and for a
sharper reason.** A destination this tool could upload to is a destination a
configuration mistake could reach, and the artifact is the entire Tier 1 store in
one file — the largest single egress the system could perform. Writing to a local
path and stopping there means the act of moving the artifact off the machine is the
operator's, performed with their own tools, with their own knowledge of where it
lands.

**Which is where ADR-0017 §1 sits with respect to this decision, stated plainly
rather than left to inference.** §1 governs components: "User data may leave the
device only from `models/` or from a designated integration seam inside `tools/`."
No component here transmits anything, so the clause is examined and found unmet —
the pattern ADR-0084 §12 records for a loopback listener. What ADR-0017 does not
address, in either direction, is an operator carrying their own file to their own
other machine, and this ADR does not decide it either: it makes the tool incapable
of the act ADR-0017 governs, and leaves the operator's act where the corpus leaves
it. Encryption is what makes that silence tolerable. The artifact is built to be
carried somewhere ADR-0004 §4's baseline — "assumes the host uses OS full-disk
encryption" — does not travel, and §4 and §5 are what replace the protection the
baseline stops providing at the edge of the machine.

**Refusing a destination inside the source is a small rule about a real mistake.**
A backup written into the directory it copies grows the next backup, and is on the
disk whose loss is the event it exists for.

### 12. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1's test is whether a reader holding only the earlier ADR would now act
differently, or read one of its clauses more widely than it now holds. Applied to
each place a record looks owed, it comes out "no record" seven times, and the
reasons are not the same reason.

- **ADR-0007 §5** defers "**Import / restore** of an exported snapshot", and that
  deferral is untouched. This ADR restores a *file copy*, never an export; ADR-0007
  §3's `export` keeps every property it has, and the import path it declined to
  contract is still uncontracted. A reader of ADR-0007 acts identically.
- **ADR-0039** hands a future ADR the question of whether an import path accepts a
  v1 `PlanExport`. Not answered here, for the same reason: nothing in this decision
  reads an export.
- **ADR-0004 §4** decides encryption at rest for a live store. This decides
  encryption of a different object with a different custodian and leaves §4's
  SQLCipher option exactly as opt-in, and exactly as keyring-keyed, as it was. A
  stacked addition, recorded here and nowhere else.
- **ADR-0004 §2's residency clause** — "All persistent data lives on the user's
  machine … No cloud storage by default" — is not engaged. §11 makes the tool write
  to a local path and transmit nothing.
- **ADR-0017 §1** is examined in §11 and found unmet. ADR-0083 §15 and ADR-0084 §12
  both record that examining a clause and finding it unmet changes nothing.
- **ADR-0119 §12** is complied with, not narrowed: §3 excludes the trace store
  precisely so that no reading of §12 has to be stretched.
- **ADR-0083** authorises this tool's shape in §10 and this ADR adds a fourth
  member to the family §10 opened, which contradicts no sentence ADR-0083 wrote.
  ADR-0083's count of five databases is a dated observation rather than a clause,
  and §1 above is built so that neither the count nor its drift matters; nothing
  here asks a reader of ADR-0083 to read any clause of it differently.

### 13. What this ADR does not decide

- **The user-facing export right.** #692 records that ADR-0004 §6's export right
  has no surface — no `AssistantEngine` method and no CLI command — and that the
  lane closing it owes the subject dimension as well. That is a user surface over a
  data right; this is an operational artifact with no contract surface and no user
  in its loop. Neither closes the other, and this ADR takes no position on #692's
  open questions.
- **Where an operator keeps artifacts, and how many.** Rotation, retention of old
  artifacts and the medium they live on are operating acts. §11 fixes where the tool
  writes and refuses; everything past that is the operator's.
- **Whether the hub's databases should be encrypted at rest.** ADR-0004 §4 decides
  it and this ADR does not revisit it.
- **The hop, and anything a remote spoke changes about any of this.** Leg 9's
  ADR-0017 §1 decision is its own lane's. If a hop lands, whether a backup may
  travel over it is that decision's question and not one this ADR pre-answers.
- **The dedicated-box migration.** #879 makes it an operating act — "a
  data-directory copy under ADR-0083's layout, run whenever hardware exists" —
  gated on #829's window. A migration is not a backup: it moves a directory rather
  than producing a portable artifact, and nothing in §9 or §11 constrains it.

## Consequences

- **Leg 9's first slice becomes buildable from this document alone.** The
  implementation lane needs a lock, a directory walk, `tarfile`, an age
  implementation and SQLite's integrity check, and it needs no subsystem, no
  engine, no embedder and no contract change.
- **Taking a backup costs a hub restart, and the restart's one visible effect is
  already ratified.** Continuation tokens are process-scoped and do not survive
  (ADR-0083 §14 item 7), so a token minted before a backup yields the unknown-continuation
  refusal ADR-0084 §7 defines, with `pending_confirmations()` as the remedy.
  Nothing else in the hub's state is in memory.
- **One new runtime dependency, and `CONTRIBUTING.md` calls a foundational one an
  ADR's business** — which is what §4's second clause discharges. The lane picks
  the library against the 3.14 wheel filter and justifies it in the change; what
  this ADR fixes is the format it must produce, so a later swap of library is not a
  swap of artifact.
- **The artifact is roughly the size of the data directory**, and a data directory
  holding a retained `<store>.pre-reembed` (ADR-0104 §3) is roughly twice the size
  of its stores. The retained copy is a hard link on disk and a second full copy in
  the archive; §6's manifest is what makes that visible as file sizes rather than as
  an unexplained doubling, and ADR-0104 already makes deleting it the operator's
  act.
- **A restore correctly invalidates an interrupted re-embed.** ADR-0104 §2 resumes a
  work store only when its recorded fingerprint of the live store still matches;
  restoring changes the live store's device, inode and mtime, so a work store
  carried in the artifact is discarded and the migration restarts, which is the
  conservative direction that clause was written for.
- **The measurement history is not protected**, per §3, and the evidence for
  #829's one-shot experiment lives only on the laptop until ADR-0119 §12 is
  revisited.
- **A backup nobody schedules still lapses.** §10 puts scheduling outside the hub
  deliberately, and no clause here detects its absence.
- **Revisit if** WAL lands (#505 — a `-wal` beside a store becomes an ordinary
  steady state and §2's refusal would need re-reading against it); if ADR-0119 §12
  is revisited, which is when the trace store's exclusion should be re-argued rather
  than re-asserted; if the store grows past the point where a full second copy for
  §9's verification is a reasonable ask, which is the same threshold ADR-0104's
  Consequences name; or if a user-facing export surface lands from #692, at which
  point the relationship between the two artifacts is worth stating once rather than
  left to two ADRs that each disclaim the other.
