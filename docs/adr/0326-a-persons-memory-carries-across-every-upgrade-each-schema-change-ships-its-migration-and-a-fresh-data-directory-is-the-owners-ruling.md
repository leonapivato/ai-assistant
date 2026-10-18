# 326. A person's memory carries across every upgrade: each schema change ships its migration, and a fresh data directory is the owner's ruling

- Status: Accepted
- Date: 2026-10-18
- Scope: every store a person's hub keeps under `Settings.data_dir`, every change to `main` that changes one, and every deploy to a person's hub. Tracker: [#3134](https://github.com/leonapivato/ai-assistant/issues/3134), acceptance [#3133](https://github.com/leonapivato/ai-assistant/issues/3133).
- Dependency: ADR-0049, ADR-0123, ADR-0309 and ADR-0314, as their status lines leave them.
- Authorization: the owner ruled on 2026-10-18 that memory carries across upgrades from that day, and that the rule has its own ADR ([#879, the ruling](https://github.com/leonapivato/ai-assistant/issues/879#issuecomment-6252766646)). The dispatcher assigned 0326 for Hosted setup A1. This decision states that ruling and settles only what it leaves open (§2, §5:3, §8).
- **Not a contract-surface decision.** It changes no `core` surface, no Protocol and no wire shape. It binds how later changes treat stored files, and the deploy.
- **Supersedes nothing and amends nothing** (§10). No header record is written on any earlier ADR.

## Context

### The ruling

The owner's ruling of 2026-10-18 on #879 lets hubs be hosted for other people, one hub per
person, on a box the owner operates. Among the terms each person is told in plain words:

```text
Memory carries across upgrades, from 2026-10-18. Every cutover keeps the data
directory, and every schema change ships its migration. A fresh directory takes
the owner's explicit ruling, case by case. Its own ADR states the rule.
```

This is that ADR. #3134 lists what it states: a cutover carries the data directory; every
store schema change ships an in-place migration from the version it replaces, with a test
that opens a file that version wrote; a store refuses only what it cannot upgrade; a fresh
data directory takes the owner's explicit ruling, case by case; a deploy takes an encrypted
backup with ADR-0123's tool before it installs; and a check in CI opens the previous
release's data directory.

The owner's own hub has served `data-m44` since the cutover ADR-0309 §6:1 rules, and the
ruling has that directory carried over when the hub moves to the new box. Other people's
hubs will start empty and are never reset on an upgrade.

### What the corpus did until now

Every cutover since M36 started the hub on a fresh data directory, and the stores were
built to require it:

- ADR-0275 §12 minted the episode-record format marker, `EPISODE_RECORD_FORMAT` in
  `memory/_episode_format.py`, and had the M36 cutover start on a fresh directory. Each
  later change to the episode record advanced the marker "on ADR-0275 §12's mechanism",
  with no migration and a refusal of the older store: ADR-0276 §7:2, ADR-0280 §7:2,
  ADR-0281 §6:5, ADR-0283 §12:1, ADR-0284 §9:1, ADR-0286 §13:1 and ADR-0318 §7:1 among
  them. `check_format` refuses every other format with `IncompatibleStateError`.
- ADR-0309 §6:1 took M42, the phases and the authority milestone live in one deploy on a
  fresh data directory, and ADR-0309 §6:4 reads: "No lane writes a migration, a reader or
  a shim for a store written before the cutover." ADR-0321 §9:2 and ADR-0322 §6:2 rode
  the same deploy.
- Members were removed from closed enumerations as recorded exceptions to *added to and
  never renamed*, on the ground that the data directory was fresh (ADR-0309 §3:6,
  ADR-0318 §5:5).

Each of those clauses is scoped to one deploy, and every one of those deploys has happened.
None of them states a standing rule for the next change, so this decision replaces none of
them (§10). What ends is the practice they shared.

### The stores today

Surveyed at `origin/main` `618ddf41`, which is the commit the live hub runs. Every version
below is also the version at `303153fb`, the commit ADR-0309 §6:1's deploy installed on
2026-10-16, except the Telegram intake store, which was added after it at version 1. So
`data-m44` was written at exactly these versions, and every refusal of an older version
today is a refusal of a file written before that deploy.

| Store | Label and version | A file at another version |
| --- | --- | --- |
| Memory, `memory/sqlite_store.py` | `EPISODE_RECORD_FORMAT` 12 | Refused by `check_format`. Older table shapes are brought forward on open by `SqliteMemoryStore._migrate_records` and `SqliteMemoryStore._migrate_walk_key` |
| Conversations, `memory/conversation_store.py` | `EPISODE_RECORD_FORMAT` 12 | Refused by `check_format`. `SqliteConversationStore._migrate_search_draw` adds two columns to an older table |
| Stories, `memory/story_store.py` | `PRAGMA user_version` 5 | Versions 1 to 4 are migrated in place (`_migrate`, `_migrate_3`). Any other is refused |
| Plans, `planning/sqlite_store.py` | `meta` `schema_version` 12 | Refused, older or newer, citing ADR-0309 §6 and ADR-0321 §9:2 |
| Audit, `permissions/audit.py` | `meta` `schema_version` 6 | Refused, older or newer, citing ADR-0309 §6:4 (`SqliteAuditTrail._check_schema_version`) |
| Grants, reads, connections, traces | `meta` `schema_version` 1 | Refused. None has changed schema |
| Telegram intake, `memory/telegram_intake.py` | `PRAGMA user_version` 1 | Refused |
| Notifications, the outbox, devices | No label | `memory/notification_store.py` and `memory/notification_outbox.py` create their tables if absent. `service/enrolment.py` backfills its roster on every open, with no version |
| The diagnostic record, `diagnostics/` | No label | JSON lines, read by nothing in the package (ADR-0314 §3:1, §6:1), kept 30 days by default (ADR-0314 §7:1) |

So the plan store's and the audit trail's refusals reach only files from before ADR-0309
§6:1's deploy, as ADR-0309 §6:4 does. Neither store has changed schema since. Their next
schema change is the first that must upgrade rather than refuse.

### What "release" can mean here

There are no numbered releases. A deploy installs whatever commit of `main` the operator
built, and `scripts/deploy_hub.py` records it in a marker on the box. Neither a lane nor CI
can see that marker, and two deploys may be one commit apart or a hundred. A rule written
against "the deployed commit" could not be followed by the change it binds.

What every pull request can see is the commit of `main` it merges onto. If each schema
change upgrades from the version on that commit, and CI proves that the head opens a
directory the base wrote, then by induction each merged head since the cutover opens a
directory any earlier merged head wrote, whichever of them were deployed. Two conditions
make that hold. The commit deployed to a person's hub is itself a merged head, so its
schema is in the chain. And it is a pull request's *last* commit: the repository merges by
*Rebase and merge* (`CONTRIBUTING.md`), so a pull request's earlier commits land on `main`
too, and nothing checks an upgrade from the schema one of them writes.

### The case the owner knows is coming

The learning walk's Part 1 decides what a memory is, and it may reshape the memory records
rather than only add to them. Under this rule the answer is a conversion of every stored
record, or the one fresh directory the owner rules for that case, with the backup of the
old directory taken first (§9). Part 1's migration is not designed here.

## Decision

We will keep every person's data directory across every upgrade. Each schema change ships
its in-place upgrade and a test against a file the previous code wrote. A store refuses only
what it cannot upgrade. A deploy backs the directory up before it installs, CI proves each
change opens what its base wrote, and only the owner rules a fresh directory.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree and
> the owner's authorization to ratify stands. An assigned number or a green review alone
> does not change its status.

> **Normative.** This decision binds every change that merges to `main` after it merges
> `Accepted`, and every deploy to a person's hub from then on.

> **Normative.** The deploy's backup (§6) and the upgrade check (§7) are each built by
> their own lane after this decision merges `Accepted`, as #3135 and #3136 track.

### 2. Terms

> **Normative.** A **person's hub** is a hub that keeps a person's own memory: the
> owner's hub, and each hub hosted for another person under the #879 ruling. A test hub,
> and any hub a test or an acceptance run sets up, is not one.

> **Normative.** A **store** is any file the hub writes under `Settings.data_dir` and
> reads again on a later start, with its SQLite sidecars. The instance lock, the sockets
> and the diagnostic record (§8) are not stores.

> **Normative.** A **schema change** is a pull request to `main` that changes the shape of
> what a store writes, or how it reads a file the code at the previous release wrote: its
> tables, columns, indexes or label, the shape of a value it serialises (a `core` model it
> stores among them), or the members of a closed enumeration a stored value names.

> **Normative.** A **release** is the last commit of a pull request merged to `main`. The
> earlier commits of the same pull request are not releases. For a given pull request, the
> **previous release** is the commit of `main` it merges onto.

> **Normative.** The **version a schema change replaces** is the schema the store's code
> writes at the previous release.

> **Normative.** A **cutover** is any deploy that installs a build on a person's hub.

### 3. A cutover carries the data directory

> **Normative.** A cutover restarts the hub on the same `Settings.data_dir` it served
> before the install, holding every file the earlier build left there.

> **Normative.** A deploy to a person's hub installs a release, built from a clean tree.

> **Normative.** Moving a person's hub to another machine carries its data directory by
> restoring a backup of it there (ADR-0123 §7). The restored directory is the carried
> directory, not a fresh one.

> **Normative.** A person's hub starts on a data directory that does not hold its
> earlier build's files only on the owner's explicit ruling for that hub and that deploy,
> recorded on a GitHub issue before the deploy. An ADR, a brief or a lane does not make
> that ruling in the owner's place.

> **Normative.** A deploy onto a fresh data directory takes §6's backup of the directory
> it leaves and deletes nothing. Deleting the old directory is a separate act.

### 4. Every schema change ships its upgrade

> **Normative.** Every schema change to a store ships, in the same pull request, an
> in-place upgrade of a file at the version it replaces.

> **Normative.** Every schema change to a store ships, in the same pull request, a test
> that opens a file the store's code at the previous release wrote, upgrades it, and reads
> back every record it holds. That file is written by that code, not assembled by hand,
> and is kept in the tree beside the test.

> **Normative.** The upgrade runs when the store opens, before it admits a read or a
> write, and either completes or leaves the file as it found it.

> **Normative.** An upgrade carries every record the file holds. What a conversion
> cannot carry whole is not dropped or cut silently: dropping it takes the owner's ruling
> under §3:4, as a fresh directory does.

> **Normative.** Upgrades chain. A build opens a file written by any release since
> ADR-0309 §6:1's deploy by applying, in order, each upgrade from that file's version.

> **Normative.** No change removes an upgrade from the tree unless the owner has ruled,
> on an issue, that no person's hub holds a file at the version it upgrades from.

> **Normative.** Advancing `EPISODE_RECORD_FORMAT`, or any other store's label, so that
> an older file is refused rather than upgraded is a fresh data directory, and takes the
> owner's ruling under §3:4.

Where a file at the version replaced reads correctly as it stands, as it does when a field
is added with a default, the upgrade is empty and the test is still owed. How an upgrade
tells one version from another is the change's own. A store with a label
reads it. A store with none tells the shapes apart from the file, as the device roster's
backfill in `service/enrolment.py` does, or gains a label in its first schema change.

### 5. A store refuses only what it cannot upgrade

> **Normative.** A store refuses to open a file only where its label is newer than its
> code understands, where it was written before ADR-0309 §6:1's deploy, or where it is
> damaged, which is to say it is not a file any release of that store wrote. Every other
> file it upgrades and opens.

> **Normative.** ADR-0309 §6:4 reaches only a store written before ADR-0309 §6:1's
> deploy, and never one written at or after it.

> **Normative.** ADR-0049 §1's refusal of a database whose `schema_version` is newer than
> the code understands binds every store: no build opens a file whose label is newer than
> the one its own code writes.

> **Normative.** A deploy that must be undone either installs a later build that opens
> the directory, or restores the backup §6 took into a new path (ADR-0123 §7:2) and
> serves the earlier build from it. An earlier build is never started on a directory a
> later build has served, unless no schema change lies between the two releases.

The plan store's refusal of a version below 12 and the audit trail's of one below 6 stand
under §5:1, as refusals of files from before ADR-0309 §6:1's deploy. Each store's next
schema change upgrades from the version it writes now.

### 6. A deploy backs the directory up before it installs

> **Normative.** A deploy to a person's hub that has served a data directory stops the
> hub, backs up that directory with ADR-0123's tool, and installs only once that backup is
> written and verified (ADR-0123 §9:1).

> **Normative.** A backup that fails, or that is reported written but unverified, stops
> the deploy before the install, and the hub is restarted on its earlier build.

> **Normative.** The artifact is kept outside the data directory, at a path the deploy
> reports, at least until a later deploy's backup has been verified.

> **Normative.** The deploy's backup excludes what ADR-0123 §3 and ADR-0314 §7:5 exclude.
> This decision adds no exclusion and removes none.

### 7. CI proves each change opens what its base wrote

> **Normative.** A required check on every pull request to `main` writes a data
> directory with the build at the pull request's base, through every store a person's hub
> keeps, and opens it with the build at its head.

> **Normative.** The upgrade check fails where any store refuses that directory, or reads
> back other than what the base build wrote, carried as the head's upgrades carry it.

> **Normative.** A pull request that adds a store adds it to the upgrade check.

### 8. The diagnostic record

> **Normative.** The diagnostic record is not a store under this decision: a change to
> the shape of its entries owes no upgrade and no test, and the upgrade check does not
> open it.

The record is in the data directory, so a cutover carries it like every other file there,
and its window keeps deleting it (ADR-0314 §7:2). A backup excludes it (ADR-0314 §7:5), so a
restored or moved hub starts with no diagnostic record. That is the window's own trade: a
backup outlives the window, and the record holds raw outside text the window exists to
delete. Nothing in the package reads an entry back (ADR-0314 §3:1), so an older line can
break no part of the hub. The record carries in place, but nothing promises it is readable
across a change.

### 9. Reshaping the memory records

A change that reshapes stored memory records, the learning walk's Part 1 among them, is a
schema change like any other. It ships a conversion of every stored record into the new
shape (§4:1, §4:4), or the owner rules a fresh directory for that case (§3:4), with §6's
backup of the directory it leaves (§3:5). That change designs its own conversion.

### 10. Relationship to earlier decisions

This decision supersedes and amends nothing, so it writes no header record on an earlier
ADR. Every earlier clause that started a hub on a fresh directory, or refused an older
store, is scoped to one deploy that has happened: ADR-0275 §12:1, ADR-0276 §7:2,
ADR-0280 §7:2, ADR-0281 §6:5, ADR-0283 §12:1, ADR-0284 §9:1, ADR-0286 §13:1 and §13:3,
ADR-0308 §7:3, ADR-0309 §6:1 and §6:4, ADR-0318 §7:1, ADR-0321 §9:2 and ADR-0322 §6:2.
Each stays true of the deploy it governed. §4:7 and §5:2 settle how the next change reads
them. ADR-0049 §1's newer-label refusal, ADR-0123 and ADR-0314 §7:5 are used as they
stand.

## Consequences

- **A person's memory survives an upgrade.** That is what makes hosting other people's hubs
  possible on the #879 terms. `data-m44` becomes long-lived, and the move to the new box
  restores it there.
- **Every schema change costs more.** A field removed from a `core` model a store
  serialises, a member removed from a stored enumeration, a table dropped: each now ships a
  conversion and a fixture written by the previous code, where it used to ship a refusal
  and a fresh directory. Clean-ups like ADR-0318's or ADR-0320's get dearer, and some will
  be cheaper to leave in place. The recorded exceptions to *added to and never renamed*
  that rested on a fresh directory are not available any more.
- **Upgrades accumulate.** Every upgrade stays until the owner rules its version gone
  (§4:6), so old code paths outlive the shapes they convert.
- **A rollback costs what was written since the install.** An earlier build cannot open an
  upgraded directory (§5:3). Undoing a deploy means rolling forward or restoring the
  pre-install backup, which loses everything written after it (§5:4).
- **A box move carries less than an in-place cutover.** A backup carries no trace store
  (ADR-0123 §3:1) and no diagnostic record (ADR-0314 §7:5), and the credentials the OS
  keyring holds are outside the data directory, so a moved hub's connections need their
  credentials again.
- **Follow-on work.** #3135 builds §6 into `scripts/deploy_hub.py`. #3136 builds §7. A
  pointer to this rule from `CONTRIBUTING.md`, where a lane changing a store would look, is
  a later change.
- **Revisit** if the hub gains numbered releases, which would let "release" mean something
  narrower than every merged pull request, or if the cost of carrying upgrades outweighs what
  a reset would cost the people whose hubs these are. Either is a new ADR, not an edit of
  this one.
