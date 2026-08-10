# 126. Deleting the owner's data destroys the cold data directory, and the enrolment record goes first

- Status: Accepted
- Date: 2026-08-10
- Accepted: 2026-08-10
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-10**,
  the durability form ADR-0100 established and ADR-0125 followed. Four of the ADRs
  this decision rests on — ADR-0004, ADR-0007, ADR-0017 and ADR-0124 — carry
  supersession or amendment records written within the last three weeks, two of
  them within the last two days, and ADR-0123's and ADR-0125's implementations
  landed on `main` while this decision was in review, and a citation that silently means "whatever this
  ADR says when you read it" is not checkable. Where a later ADR changes one of
  them, this one is read against the text named here until an ADR says otherwise.
- **This ADR partially supersedes ADR-0124 and ADR-0004, and all three records
  land in this change.** Each is one clause, and each is scoped to the one act this
  ADR defines. **ADR-0124 §6's** "A revocation is recorded rather than erasing the
  enrolment it revokes", only as it reaches the act that destroys the enrolment
  record itself (§4). **ADR-0004 §6's** Tier 0 purge clause, only as it reaches a
  Tier 0 credential held on the hub's machine outside the OS keyring — today the
  provider key the SDK reads from the environment (§6). **ADR-0004 §7's** gating
  clause, only for that act, because `permissions/` runs inside a hub this act
  requires to be stopped and the audit trail is a file it destroys (§11). §12
  applies ADR-0070 §1's test to each and states what survives, which is nearly all
  of all three sections — every other sentence of ADR-0124 §6, the whole of its §8
  including both clauses this ADR exists to give a home to, every other right
  ADR-0004 §6 grants, and every part of §7 that governs any other access. No
  ratified text of either ADR is rewritten; each `Status` line and its appended
  dated note are the whole of the record (ADR-0070 §1, ADR-0082 §1 and §2).
- **No implementation lands with it.** No `src/`, no `tests/`. The tool §2 rules
  is a separate lane, briefed against this text once it merges, and §9 sequences it
  behind a prerequisite that does not exist yet.
- **No `core` surface is decided.** No Protocol in `core/protocols.py` changes, no
  type, enum member or constant is added to `core/types.py`, and
  `PROTOCOL_VERSION` is untouched. §8 states that as a ruling rather than leaving
  it to be inferred, because ADR-0124 §10 requires a lane that finds it needs
  either to stop and owe its own contract ADR — this is that ADR, and its answer is
  that neither is needed.
- **Its required review set is adversarial *and* architecture.** The decision sits
  on a package boundary that `lint-imports` enforces mechanically, it disposes of a
  seam a filed issue expected to exist, and it partially supersedes a clause
  ratified the day before — the edge cases are answerable from prose, before an
  implementation commits to an answer (`CONTRIBUTING.md` → "Contract ADRs land
  before their implementation"). **Both ran against this decision while it was
  `Proposed`, and both changed it.** Adversarial produced §1's symbolic-link and
  mount-point clauses, §5's ordering *inside* the enrolment group, and §4's and
  §7's treatment of an installation that never configured a remote listener;
  architecture produced §6's whole shape — an earlier draft had the act holding a
  `SecretStore`, which ADR-0125 §8 forbids `service` — and §11, which an earlier
  draft did not have at all. Each is recorded at the clause it changed rather than
  only here.

## Context

### Two ratified clauses name an act the tree does not have

ADR-0124 §8 carries two normative clauses that the server-half lane (PR #902)
could not implement and filed as **#903**:

```text
> **Normative.** Deleting the owner's data at the hub revokes every enrolment as
> part of the same act, so no device is left holding a credential to a store that
> no longer exists.

> **Normative.** A delete performed at the hub reports what it did not purge: the
> devices whose local credential it could not reach, and the act at each that
> purges it. It may not present itself as having purged everything.
```

Both are obligations on "a delete performed at the hub". Nothing in the tree
performs one. The clauses are therefore not unimplemented so much as unattached:
there is no act for them to be true of, and the first lane that builds one would
be deciding, silently and in passing, what ADR-0004 §6's delete right *is*.

### What the tree actually holds, checked rather than remembered

- **`AssistantEngine` carries nineteen methods and none of them deletes the
  store.** `forget`, `forget_question` and `forget_conversation` each destroy one
  named thing. ADR-0085 §1 ratified fifteen; the surface has grown by four since,
  which is worth stating because the corpus's "sixteenth method" arguments
  (ADR-0124 §9, and `service/admin.py`'s own docstring) are about the *next* one,
  whatever its ordinal.
- **`MemoryStore.clear` exists on the Protocol and has no operator-facing caller.**
  Its docstring says why: it "empties the store's own (Tier 1) rows only; it is not
  a whole-system erase (ADR-0007 §4)". `PlanStore`, `AuditTrail`, `SourceGrantStore`
  and `DeferralStore` each carry a `clear` in the same position, equally uncalled.
- **The CLI has `forget`, `forget-conversation` and `forget-question`, each with a
  show-then-confirm ceremony, and no whole-store command.** No `shutil.rmtree` of a
  data directory exists anywhere in `src/`.
- **Seven console scripts ship**: `assistant`, `ai-assistant-hub`,
  `ai-assistant-reembed`, `ai-assistant-measures`, `ai-assistant-device`,
  `ai-assistant-backup` and `ai-assistant-restore`. Each carries a comment in
  `pyproject.toml` recording that it is a separate script because ADR-0083 §8
  forbids anything importing `service`. The last two landed while this ADR was in
  review, so ADR-0123 §10's "fourth member of the offline family" now names shipped
  code rather than a ratified intention, and §2 below is the fifth.
- **The enrolment record is `<data_dir>/devices.db`**, one table, with a partial
  unique index enforcing ADR-0124 §6's one-live-enrolment rule. `EnrolmentStore`
  offers `enrol`, `revoke`, `recent_enrolments`, `known_identities` and
  `live_verifiers`. **It has no delete and no purge**: `revoke` is
  `UPDATE enrolments SET revoked_at = ?`, and the module's own docstring records
  that "the record only ever grows".
- **`<data_dir>/admin.sock` carries exactly three acts** — `enrol`, `revoke`,
  `list` — reached by `ai-assistant-device` on the hub's own machine. Its module
  docstring bounds its own growth: "It carries no engine call and never will: the
  surface below is three acts on the enrolment record and nothing else."
- **ADR-0124 §8's device-side unenrolment act does not exist.** PR #902 records it
  as deferred with the rest of the client half, and the tree agrees: no `unenrol`
  act on `ai-assistant-device` and no client that reads a credential. ADR-0125's
  triad landed while this ADR was in review, so `core/protocols.py` now carries
  `Secrets` and `SecretStore` and `core/types.py` carries `SecretName`,
  `SecretScope` and `SecretValue` — but the concrete keyring-backed implementation
  ADR-0125 §8 requires has not landed, **there is no `keyring` import anywhere in
  `src/`**, and no production module holds either face.
- **No hub-side component writes a keyring entry today.** The provider credential
  is read from the process environment by the provider SDK, which ADR-0125 §8
  records as pre-existing and not authorised by it; no tool transmits anything, so
  ADR-0017 §3's seam is undesignated and holds no credential; and ADR-0004 §4's
  application-level encryption key is off by default and unwired (ADR-0125 §12).

### Three deferrals converge here, and one of them named this act eight decisions ago

**ADR-0007 §5 deferred "Cross-tier 'delete everything' (keyring + database)"** and
§4 said the coordinator was "future work", with no condition naming when it fires.
ADR-0124 §8 is that condition arriving from an unexpected direction: it does not
ask for the coordinator, it *assumes* one and puts two obligations on it.

**ADR-0101 §7 deferred the subject-scoped erasure and disclosure jointly**, put
neither on `AssistantEngine`, and named two conditions that fire it — both about
the export right. **#692** records that ADR-0004 §6's export right has no user
surface at all. Neither is this decision: an unscoped delete of everything is not
ADR-0101 §1's subject-scoped erasure, and §10 below says so in a marked clause so
that no lane reads this as firing either condition.

### The seam #903 expected, and why it is the thing to test rather than to build

#903 states the problem as a boundary: "The delete surface is the engine's, in
`orchestration`, and its rendering is in `interfaces`. The enrolment record is the
hub's, in `service` … `orchestration` cannot reach the record", and names the
seam — "plausibly a callback the composition root injects, plausibly something
else" — as the decision.

The tree supports the boundary half exactly. `lint-imports`' contract "nothing
imports the service" lists every top-level package as a source module and
`ai_assistant.service` as the forbidden one; `DeviceRegistry` is built in
`service/hub.py`, one layer above the composition root, and `app` cannot see it.
The shape a callback would take already exists in three places —
`Engine(closers=[…])`, `GrantOperations(id_factory=…, clock=…)` — so a lane could
build it without argument.

What is *not* established is the premise the seam rests on: that the delete
surface is the engine's. Nothing in the corpus puts it there. ADR-0004 §6 grants a
right and names no surface; ADR-0007 §4 scopes `MemoryStore.clear` to one store and
sends the coordinator to "a higher layer"; ADR-0101 §7 declines to put even a
*scoped* erasure on `AssistantEngine`. So the seam is a consequence of a placement
nobody chose, and the placement is what this ADR has to decide first.

### The two shapes the corpus already has for a hub-local act, and what each is for

**An act inside the running hub, reached over a hub-local control socket.** PR
#902 built this for revocation, and its reasoning is right for that act: ADR-0124
§8 makes revoking a device close the connections that device holds, and an offline
tool runs only with the hub stopped, where there are none. Revoking one device is
also something the owner does *while continuing to use the assistant* — a lost
laptop should not cost a restart.

**An offline tool taking the hub's instance lock, in `service/`.** ADR-0104 §5,
ADR-0120 §9 and ADR-0123 §10 each chose this, and ADR-0123 §10's argument is the
general one: the tool's subject is `Settings.data_dir`, the lock is
`service/lock.py`, `lint-imports` means the entry point has to *be* in `service/`,
and `service` may import `app` and `core` (ADR-0083 §8), which is how each of them
reaches its mechanism. ADR-0123 §1 goes further and rules the *unit*: a backup is
"a cold copy of the whole data directory, not a set of per-store exports".

This decision has to say which shape the delete takes, and it cannot answer by
analogy, because the delete resembles the first in what it must do to enrolments
and the second in what it must do to the data.

## Decision

### 1. Deleting the owner's data at the hub is the destruction of the cold data directory

> **Normative.** The act ADR-0124 §8 calls "deleting the owner's data at the hub"
> is the destruction of the contents of the resolved `Settings.data_dir`. Its unit
> is the directory, not a set of per-store `clear` calls, and it is the act that
> discharges ADR-0004 §6's delete right on the hub's own machine.

> **Normative.** The act destroys every entry in the resolved `data_dir`, to any
> depth, with exactly one exception: the instance lock file the act itself is
> holding (§5). It carries no inclusion list and no exclusion list beyond that one
> entry, and it opens no store to empty it.

> **Normative.** The act never follows a symbolic link. A symbolic link found
> anywhere under `data_dir` is destroyed as the link it is, and what it names is
> not read, not descended into and not destroyed. Every decision about an entry's
> type is made on the entry itself and never on what it resolves to.

> **Normative.** The act destroys nothing whose path is outside the resolved
> `data_dir`. That is the obligation; the two clauses below are how it is met and
> do not narrow it.

> **Normative.** The act refuses, before destroying anything, if any directory
> *strictly beneath* `data_dir` is a mount point of any kind — a mount of another
> filesystem, and equally a bind mount whose source is on the same one — with a
> diagnostic naming that path. `data_dir` itself being a mount point is not a
> refusal and is a supported deployment.

> **Normative.** Where the platform gives an implementation no way to enumerate
> its mount points, the act refuses to run rather than proceeding on a test it
> knows to be incomplete.

> **Normative.** Before it destroys anything, the act checks that every entry it
> found is one it can destroy: every directory it must descend into readable and
> writable by the process, and every entry's parent directory writable. It refuses,
> destroying nothing, with a diagnostic naming each path that fails and what about
> it fails.

> **Normative.** Where a destruction nevertheless fails once the act has begun, the
> act destroys everything else it can, then reports every path that remains and why,
> and exits with a failure status. It may not report the delete as complete, it may
> not pass over an entry silently, and it does not stop at the first failure.

> **Normative.** `devices.db` is the one exception to the clause above. Where it
> exists and its destruction fails, the act destroys **nothing further**, reports
> that it destroyed nothing and why, and exits with a failure status. Best-effort
> continuation begins only once the enrolment record has gone.

> **Normative.** On a successful act the data directory itself survives, holding
> nothing but the instance lock file the act is holding (§5), with the permissions
> ADR-0083 §3's preparation gives it. A hub started afterwards finds an installation
> with no data in it, which is the state a first start already handles, and not a
> missing or malformed directory. On a failed act it holds, in addition, exactly the
> entries the report names.

**The unit is forced by the same argument ADR-0123 §1 made, pointed the other
way.** A backup assembled from per-store exports is incomplete the moment a lane
adds a store and forgets the list; a delete assembled from per-store `clear` calls
is incomplete in exactly the same way, and its incompleteness is a privacy failure
rather than a durability one. There are seven SQLite stores wired at the
composition root today and the count has drifted twice in the corpus already
(ADR-0123's Context records it). A rule stated over the directory cannot drift,
and it needs no lane to remember anything.

**Emptying tables is not deleting data, and the difference is not pedantic.**
`clear` on the five stores that have one leaves the files, their schemas, their
free pages and their write-ahead logs; SQLite does not zero a deleted row, and a
`-wal` holding committed pages of exactly the records the owner asked to destroy
would survive every one of those calls. It also reaches nothing that is not a
store: `hub.sock` is gone at shutdown but a killed hub leaves it, and the trace
store, the audit trail and the enrolment record are each governed by their own
rules about what may be removed. Destroying the directory's contents is the only
form of the act with one meaning.

**A rule stated over a directory has to say what a directory can contain, and the
destructive form of the rule cannot borrow ADR-0123 §1's answer unchanged.** That
section refuses to copy a data directory holding "an entry that is neither a
regular file, nor a directory, nor one §3 excludes by name — a symbolic link
included", and "never follows a symbolic link". Refusing is the right answer for a
*copy*, which can simply not be taken; refusing every unexpected entry here would
let one stray link block the exercise of a data right indefinitely. So the two
clauses above split what ADR-0123 §1 joined: a link is destroyed rather than
refused, because it is an entry in the directory the owner asked to empty, and it
is destroyed **as a link**, because what it names is not.

**Following one is the failure that would be unrecoverable, and it is not
hypothetical.** `data_dir/x -> /home/owner/photos` turns "destroy every entry, to
any depth" into the destruction of a directory the owner never named and this act
has no claim on. The same reasoning extends one step further than symbolic links,
which is why the mount-point clauses are separate: a directory mounted under
`data_dir` is storage the directory names rather than holds, its contents were not
put there by this installation, and unlinking through it is the same error with no
link to notice. Refusal is right *there* — unlike a stray link, a mount point is a
deliberate deployment arrangement, so the operator can unmount and rerun, and the
diagnostic tells them which path to deal with. Refusing before destroying anything
is the strictly safer direction and is ADR-0123 §2's own posture.

**The bind mount is named because the obvious test does not catch it, and an
unnamed false negative here is the whole failure.** `mount --bind /home/owner/photos
<data_dir>/photos` produces a mount point whose source is on the same device as
`data_dir`, so a rule phrased over *filesystems* does not reach it and a check that
compares a directory's device with its parent's — which is what a portable
`ismount` reduces to — returns false for it. Everything under it would then be
destroyed while the act satisfied a clause about not leaving its filesystem. So the
boundary the obligation is stated over is `data_dir` itself, the filesystem is not
mentioned in it, and an implementation consults the platform's own mount table
rather than inferring one from `stat`. The refusal-when-unenumerable clause is the
conservative close: an act that cannot see its own boundary does not get to guess
where it is.

**The refusal reaches only *beneath* the boundary, and the difference is a whole
supported deployment.** `ASSISTANT_DATA_DIR` pointed at the root of a dedicated
local volume is a mount point, and it is a good arrangement rather than a
suspicious one — ADR-0123's Context is about exactly the operator who cares where
this data sits. A refusal phrased over "at or under" would deny the delete right to
that installation for a property that threatens nothing: a mount point *at* the
boundary is the boundary, and destroying everything inside it is the act. What the
clause is for is a mount point that lets the act reach storage the boundary does
not contain, and only a descendant can do that.

**Permitting the volume root is what makes the removability check owed, and
`lost+found` is the case that showed it.** `mkfs` puts a root-owned, mode-`0700`
`lost+found` at the root of an ext filesystem, and it survives an operator
`chown`ing that root to themselves — which `service/datadir.prepare` then accepts.
The act cannot read into that directory to empty it, so an implementation walking
the tree meets a `PermissionError` partway through, having already destroyed the
enrolment record and most of the stores. The two clauses above turn that into a
refusal before anything is destroyed, which is ADR-0123 §2's posture applied where
it matters more: a backup that fails halfway has copied nothing anyone relies on,
and a delete that fails halfway has destroyed data and reported nothing. The
diagnostic names the path, and the operator's remedy is theirs to choose —
commonly, pointing `ASSISTANT_DATA_DIR` at a child directory of the mount rather
than at its root.

**Continuing past a late failure rather than stopping is the choice worth
defending, and it follows from what the owner asked for.** They asked for their
data to be gone; stopping at the first entry that resists would leave behind
everything the act had not reached yet, for the sake of a tidier failure. So the
act destroys what it can, and the honesty obligation is carried where it belongs —
in a report that names every path that remains, and a failure status. That is the
same trade §7 makes for devices: the act does what it can reach, and says exactly
what it did not.

**`devices.db` is exempt from that trade because for it the trade runs the other
way, and §5 is where the reason is argued in full.** Best effort past a failed
enrolment record reconstructs precisely the state §5's ordering exists to make
unreachable: live verifiers on disk and the stores around them gone, so the next
hub start rebuilds empty stores and admits every enrolled device to them — "a
device left holding a credential to a store that no longer exists", which is the
outcome ADR-0124 §8 forbids, produced by the act meant to satisfy it. A permission
preflight makes the case rare and does not make it impossible: an immutable
attribute or an I/O error is not a permission. So for exactly one entry the safe
failure is to have destroyed nothing, and the owner reruns the act once they have
dealt with the file the report names.

**The one thing per-store `clear` does that this does not is run without stopping
the hub, and §2 is where that is paid for rather than avoided.**

### 2. It is an offline console entry point in `service/`, and the control socket cannot carry it

> **Normative.** The act has its own console entry point in
> `ai_assistant/service/`, named `ai-assistant-purge`, beside `ai-assistant-hub`,
> `ai-assistant-reembed`, `ai-assistant-measures`, `ai-assistant-device`,
> `ai-assistant-backup` and `ai-assistant-restore`. It is not an `assistant`
> subcommand.

> **Normative.** It runs with the hub stopped. It takes the hub's instance lock
> before it destroys anything and holds it for the whole act, and it refuses —
> destroying nothing — when something else holds it.

> **Normative.** No act on `<data_dir>/admin.sock` performs it, no
> `AssistantEngine` method performs it, and no wire operation carries it.

> **Normative.** No part of the hub performs, schedules or triggers it, and the
> hub never stops itself to allow one. It is an act the owner invokes.

**A running hub cannot delete the directory it is holding open**, and that alone
decides the shape. Seven SQLite connections, a trace store, the enrolment record
and a bound socket all live in it; unlinking their files under a live process
leaves a hub writing to descriptors whose paths are gone, which is neither a delete
the owner can trust nor a state ADR-0083 §6's fault classification has a name for.

**PR #902's argument for the control socket is right and does not transfer, and
saying exactly where it stops is the point.** Its reasoning is that "revoking a
device closes any connection that device currently holds", and an offline
lock-taking tool "would be a tool that runs only while the hub is stopped, so there
would never be a connection to close". That is correct about **revoking one
device**, which is an act on a record while the hub keeps serving everyone else.
It is not an argument about **destroying the record's store**, where the clause is
satisfied in the strongest available form rather than vacated: a stopped hub holds
no connection from any device, so after this act no device holds one, which is what
§8's clause asks for. The lock is what makes that stable — nothing can start a hub
and admit a device while the act runs.

**The control socket could not carry it even if a running hub could.** Its own
docstring bounds it to "three acts on the enrolment record and nothing else", and
an act that destroyed the data directory would be none of the three and not on the
record. Growing that surface to reach seven stores it deliberately never touches
would make the control socket a second engine, which is the thing ADR-0084 §6 and
ADR-0085 §3 divide the system to prevent.

**And it may not be an `AssistantEngine` method, which is a prohibition rather
than a preference.** `wire/surface.py` derives the wire's method set from
`vars(AssistantEngine)`, so a twentieth method is *automatically* reachable from
any connection the hub admits — including, since ADR-0124 §7, a connection from an
enrolled device across the remote transport. ADR-0124 §6's first normative clause
forbids exactly that: "No connection to the remote listener may create, extend or
modify an enrolment." An engine-side delete that revokes every enrolment is a
remote connection modifying every enrolment there is, and no per-method listener
policy exists to stop it — the promoted surface has none, and inventing one would
be a much larger contract decision than this act needs. The version rule
(ADR-0124 §9) and ADR-0085 §3 would both bind as well, and both are beside the
point: the method is refused before either is reached.

**The name is ADR-0004 §6's verb and ADR-0124 §8's, taken deliberately.** §6 says
a delete "purges Tier 0 … and Tier 1 … together"; §8's second clause says the
delete "reports what it did not **purge**". The corpus's other uses of the word —
`MemoryStore.purge_expired`, `DeferralStore.purge`, `TraceRetention.purge_before`,
the `retention_purge` scheduler job — are retention reclaim inside one store, and
nothing here renames any of them; a console script and a store method share no
namespace, and the two senses are already both in the corpus with the ADRs holding
this one. What the name must not be is `erase`, which ADR-0101 uses throughout for
the subject-scoped operation §10 keeps separate from this act.

### 3. There is no seam, because the act is where the record already is

> **Normative.** The mechanism lives in `ai_assistant/service/` and imports no
> subsystem directly. It reaches the enrolment record through
> `service/enrolment.py` and the instance lock through `service/lock.py`, as
> modules in its own package, and it needs no callback, no injection point and no
> new contract to do so.

> **Normative.** No callback is injected into `Engine`, into the composition root,
> or across any package boundary for this act. #903's expected seam is not built,
> because §2's placement removes the boundary it was to cross.

**This is ADR-0123 §3's principle applied one level up.** That section had a
backup tool needing three names it did not own, and rather than restating them it
read each "from the module that already owns that name", concluding that "the
authority on a name is whoever establishes it". The same reasoning, applied to an
act rather than a name, says the authority on the enrolment record is the package
that holds it — so the act that must reach the record belongs in that package, and
an act placed elsewhere is one that has to be given a way back in.

**#903's premise is where the seam came from, and it is worth saying plainly that
the premise was reasonable and is still wrong.** It reads "the delete surface is
the engine's", which is true of every delete the tree has — `forget`,
`forget_question`, `forget_conversation` are all engine methods with CLI
renderings, and generalising from three is what anyone would do. But those destroy
one named record inside a store the engine owns, and this act destroys the
directory the stores are in, which the engine does not own and cannot open twice.
Once the act moves to where its subject is, the boundary #903 identified is
correct and simply is not crossed.

**What is given up by this is real and is named.** A delete the owner performs
from the client, over the socket, in the same session where they decided to do it,
is a better surface than one that requires stopping the hub and running a second
command. This decision does not deliver it and does not foreclose it: what
forecloses it is ADR-0124 §6's clause about remote connections and enrolments, and
a future decision that wants an in-session delete owes a way for the promoted
surface to be reachable from loopback and not from the remote listener. That is a
`wire` decision, it is not this one, and no lane may read this section as having
decided it either way.

### 4. Every enrolment is revoked because the record ceases to exist

> **Normative.** The act revokes every enrolment by destroying `devices.db` and
> its SQLite sidecars, with ADR-0124 §8's full finality: afterwards no credential
> verifies against anything, because there is no verifier and no record to verify
> against. It writes no revocation row first, and it retains nothing of the
> record.

> **Normative.** An installation that has never configured a remote listener holds
> no enrolment record, and there the clause above is satisfied with nothing to
> destroy. The act neither creates the record nor treats its absence as a fault.

> **Normative.** ADR-0124 §6's clause that "a revocation is recorded rather than
> erasing the enrolment it revokes" is superseded **only** as it reaches this act.
> Every revocation performed by any other means — the control socket's `revoke`,
> and the rotation §6 folds into `enrol` — still records rather than erases, and
> no lane may cite this clause to erase an enrolment in any other circumstance.

> **Normative.** "As part of the same act" is satisfied by the enrolment record
> being inside `data_dir` and destroyed by the same act that destroys everything
> else there, under one instance lock. No separate revocation step exists that a
> failure could leave undone.

**The two clauses cannot both be honoured, and the conflict is this act's alone.**
ADR-0124 §6 requires a revocation to leave a durable row saying what the owner
decided and when. ADR-0004 §6 — in the half ADR-0124 §8 explicitly left untouched
— grants "the purge of every Tier 0 and Tier 1 artifact on the hub's own machine".
A delete that revoked by recording would leave behind, in a file the owner asked to
destroy, every device they ever enrolled, the instant each was enrolled, and the
instant each was revoked. That is Tier 1 personal data about the owner's machines
and habits, surviving the exercise of the right that exists to remove it. The two
sentences are in direct contradiction for this act and for no other, so one of them
has to give, and it is not the data right.

**Destroying the record is not a weaker form of revoking than recording one; it is
a stronger one, and §8's own words say so.** Its clause is "so no device is left
holding a credential to a store that no longer exists" — and after this act the
store literally no longer exists, which is the only circumstance in which that
sentence is true rather than figurative. §8's finality clauses are satisfied
term for term: the credential "verifies against nothing" because nothing survives
to verify it; no connection is held because no hub is running; and no frame is
written to the device because there is no process to write one.

**§6's stated purpose survives the supersession, which is what makes it narrow.**
The purpose is "so the record says what the owner actually decided and when" —
protection against an implementation quietly dropping a row and leaving the owner's
decision unrecorded. Here the owner's decision *is* that nothing survives, and a
record of it would be the residue rather than the evidence. The mischief §6 aims
at is an erasure the owner did not ask for; this is the one they did. §12 records
the supersession and applies ADR-0070 §1's test to it.

**What is not superseded, and a lane will be tempted to think it is.** §6's
uniqueness rule, the credential's shape and disclosure, the verifier-only
retention, the record's placement in `data_dir`, the hub-local enrolment
requirement and the remote-connection prohibition are all untouched, and so is
every clause of §8. This decision removes one sentence's reach over one act.

### 5. The instance lock is the atomicity, and the enrolment record goes first

> **Normative.** Where `devices.db` exists, it is the **first** entry the act
> destroys. Its SQLite sidecars — its `-journal`, `-wal` and `-shm`, each matched
> exactly as that path's name followed by the suffix — are destroyed immediately
> after it, before any other entry in the data directory. Where it does not exist,
> the act creates nothing and this ordering places nothing; the rest of the act is
> unchanged.

> **Normative.** The act holds the instance lock from before the first destruction
> until after the last. It does not destroy the lock file it holds, and the lock
> file's survival is not a shortfall the report must confess: ADR-0123 §3 already
> rules that "the file's bytes grant nothing" and that the pid inside it is a
> diagnostic hint, so it is process state rather than the owner's data.

> **Normative.** The act is not atomic against a crash, and no clause here claims
> it is. What the ordering guarantees is the *direction* of every reachable partial
> state: after the first destruction succeeds, no enrolment is live, and everything
> that survives a crash is data no device can reach.

**"As part of the same act" is a claim about what can be observed between two
things, and a lock is what makes it true.** ADR-0083 §1 puts one hub per data
directory behind an advisory `flock` whose meaning is entirely in the kernel, and
ADR-0123 §2 already uses it to serialise an offline tool against the hub. While
this act holds it, no hub can start, so there is no process that could read a
half-destroyed directory, admit a device against a record that is gone, or serve a
store that is not. The interval in which the act is incomplete is an interval in
which nothing is running to observe it.

**The order is the one place a crash could produce a genuinely bad state, and it
has a right answer.** Destroying the stores first and crashing before `devices.db`
leaves live enrolments against a hub that will start, rebuild empty stores, and
admit every enrolled device — devices holding credentials to a store that is gone,
which is the exact outcome §8's clause exists to prevent, produced by the act meant
to satisfy it. Destroying `devices.db` first and crashing leaves data on disk that
no device can reach and no credential opens; the owner reruns the command. Both
failures are bad, one of them is recoverable by repeating the act, and only one of
them contradicts a ratified clause.

**The sidecars are named because a database is not one file**, which is ADR-0123
§3's finding in its own words: a `-wal` left by a crashed hub "holds committed
pages" of the store it belongs to. For a backup that meant an exclusion had to
reach them; here it means the destruction has to, and for the same reason —
`devices.db-wal` can hold a live verifier after `devices.db` is gone.

**Which is also why the order inside that group is fixed rather than left as a
set.** "Destroy the record and its sidecars before anything else" is satisfied by
an implementation that unlinks `devices.db-wal` first and crashes, leaving
`devices.db` — a readable database holding live verifiers — and the guarantee above
false at the one instant it exists to cover. The main file is what a hub opens and
what `live_verifiers` reads, so it is what has to go first; a `-wal` left without
it is pages no process in this system can open as a database, and the rerun removes
it. The group is ordered by which file makes an enrolment live, not by which file
is largest or listed first.

### 6. The act reaches no keyring, and the Tier 0 credential it cannot reach is reported rather than counted as purged

> **Normative.** The act reaches no keyring. It holds neither face of ADR-0125's
> seam, performs no keyring operation, and enumerates nothing. ADR-0125 §8 names
> `service` among the packages that "hold neither" and forbids any of them
> acquiring one without the ADR §2 requires; this act is in `service`, and this ADR
> does not seek that exemption.

> **Normative.** No component of this system writes a Tier 0 keyring entry on the
> hub's machine today, so the act misses no keyring entry. That is a statement
> about the keyring and not about Tier 0, which ADR-0004 §1 defines as
> credentials — "OAuth tokens, API keys, refresh tokens" — wherever they sit.

> **Normative.** ADR-0004 §6's clause that "deleting the user's data purges Tier 0
> (keyring entries) and Tier 1 (database rows) together" is superseded **only** as
> it reaches a Tier 0 credential held on the hub's own machine outside the OS
> keyring. Today that is exactly one thing: the model provider credential the
> provider SDK reads from the process environment. The act does not remove it, and
> the two clauses below stand in the clause's place. Everything else §6 grants —
> view, export, delete, retention rules, and the purge of every Tier 1 artifact and
> every keyring-held Tier 0 artifact on that machine — is untouched.

> **Normative.** The report names that credential as not purged: that a credential
> the operator holds in their environment or a shell profile is not in the keyring,
> is not in `data_dir`, and is not removed by this act, and that removing it is an
> act at the place they set it. It may not describe Tier 0 as purged, and may not
> describe a keyring as swept (§7).

> **Normative.** This supersession is self-limiting. It reaches only a Tier 0
> credential held outside the keyring, so it lapses for any credential a later lane
> moves into the keyring under ADR-0004 §3, and no lane may cite it to hold a new
> credential outside one — ADR-0125 §8 forbids that independently, and this clause
> does not soften it.

> **Normative.** The `ENROLMENT` scope is not reached by this act. ADR-0125 §5
> rules that the hub holds neither face of that seam for enrolment purposes, and
> ADR-0124 §8 supersedes ADR-0004 §6 precisely as it reaches an enrolled device's
> keyring entry — which is what §7's report is for.

> **Normative.** The lane that first gives a component on the hub's machine a Tier
> 0 keyring entry owes, in the same change, a decision about how a hub-side delete
> reaches it. That decision is a contract question and not a wiring detail — ADR-0125
> §5 refuses enumeration and puts the deletion path on the consumer that wrote the
> entry, and ADR-0125 §8 keeps `service` out of the seam, so no path exists today
> that this act could take. Until that decision lands, this ADR authorises no such
> entry to be written, and no lane may cite this section as a route to one.

**"No keyring entry" and "no Tier 0" are different claims, and an earlier draft of
this section made the second while checking only the first.** The keyring half is
checkable and true: the tree has no `keyring` import, ADR-0125's concrete
implementation has not landed, `tools/` transmits nothing so ADR-0017 §3's seam is
undesignated and holds no credential, and ADR-0004 §4's application-level
encryption key is off by default with no wiring (ADR-0125 §12). Nor is there a
component that *could* write one: ADR-0125 §8 gives `models/` only the reading face
and says in as many words that "provisioning a provider credential is not
`models/`'s". But ADR-0004 §1 defines Tier 0 by what a value *is*, not by where it
is kept, and the provider credential is an API key on the hub's own machine that
this act leaves exactly where it found it. Declaring §6's Tier 0 half discharged on
that evidence was reading §6's parenthetical "(keyring entries)" as its scope when
it is its assumption — the assumption ADR-0004 §3 makes and the tree does not yet
meet.

**So the instrument is a supersession, and it is the one ADR-0124 §8 already used
on this exact sentence for a different unreachable place.** That section narrowed
§6's Tier 0 purge as it reaches an enrolled device's keyring entry, because a hub
cannot reach another machine, and replaced it with a report the owner reads. The
credential in the operator's own environment is the same shape of unreachable, one
machine closer: not another device, but another custodian — a shell profile this
system did not write and must not edit. The replacements are the same instrument
too, because there is only one honest one: say what was not purged, and say what
the owner must do about it.

**The cause is pre-existing and the reach is not, which is why filing it would have
been the wrong move.** ADR-0125 §8 records that the environment read "is
pre-existing and is not authorised by this ADR", and **#74** is open on it. This
ADR does not create that read and does not make it worse. What it creates is a
*delete* — and ADR-0124 §6 is categorical that "a known violation does not
authorise adding another": shipping an act that a ratified clause says purges Tier
0, when it does not, changes what that clause governs. A clause requiring the act
to purge the credential instead would be contracting an obligation nothing can meet
— the failure ADR-0016 §5 names and ADR-0125 §4 twice declines to repeat — since
the only implementation is editing the operator's shell profile.

**The forward clause is deliberately not the shape ADR-0123 §3's is, and the
difference is the whole finding this section was rewritten for.** That section
could tell a later lane to "add it to the exclusions above" because a backup tool
in `service/` may read a path constant from anywhere. This one cannot tell a later
lane to add a deletion to this act, because a deletion requires holding
`SecretStore`, and ADR-0125 §8 forbids `service` to hold it. An instruction to do
it anyway would be this ADR directing a lane to breach a clause ratified the day
before. So what the forward clause binds is that the question be *decided* — by
whoever creates it, at the moment they create it — rather than that it be answered
here in a package that may not answer it.

**What that decision will have to weigh is named so the lane does not start
cold**, and none of it is decided here: whether the purge is composed by each
consumer offering its own deletion path to a coordinator, whether the coordinator
is the hub rather than an offline tool, and whether either requires a fourth face
or a widened scope enum. **#909** carries it, filed from this lane.

**The credential in the operator's environment is the one thing this cannot reach
and must not be silent about.** A provider key exported from a shell profile is not
a keyring entry, is not inside `data_dir`, and is not something a process can
remove from a file it does not know about. §7 requires the report to say so. This
is not a gap this ADR opens: it is ADR-0125 §8's pre-existing finding, surfaced at
the one moment the owner is entitled to know about it.

### 7. The report: stated before the act, restated after, and three things it may not claim

> **Normative.** Before it destroys anything, the act states: the resolved
> `data_dir` it will destroy; every device holding a live enrolment at that
> instant, by its overlay identity as the record holds it; for each such device,
> the act at that device that purges its local credential; that a hub-side delete
> cannot reach any of them; that no keyring is reached, so a Tier 0 credential the
> operator holds in their environment is not removed by it (§6); and that a backup
> artifact taken under ADR-0123 is not reached.

> **Normative.** It destroys nothing until the owner confirms against that
> statement. A non-interactive confirmation names the resolved `data_dir` the act
> will destroy; a bare affirmative flag does not satisfy this clause.

> **Normative.** After the act, it restates the device list and the act at each,
> so that a session scrolled past the first statement still carries what the owner
> must do next.

> **Normative.** The device list is complete. It enumerates every live enrolment
> with no bound, no page and no omission count, which is why the act reads the
> enrolment record directly rather than through the control socket's bounded
> `list`.

> **Normative.** The act never creates the enrolment record in order to report on
> it. Where `devices.db` is absent the device list is empty and the report says so
> plainly — that this installation has enrolled no device — rather than omitting
> the subject.

> **Normative.** The report may not present the act as having purged everything;
> may not present it as reaching anything on an enrolled device; and may not
> present the revocation as retracting what a device already holds. What a device
> received before the act, it keeps — ADR-0124 §8's prospective rule is unchanged
> and is stated to the owner rather than implied.

> **Normative.** The report is text the act writes to its own output. This ADR
> adds no type for it — not to `core/types.py`, not to any Protocol — and no report
> of this act crosses a subsystem or process boundary.

**Stating the device list *before* the destruction is the clause that carries the
obligation, and the reason is the crash.** After the act, the record naming the
devices is gone; an implementation that composed its report from the record and
printed it at the end would, on a crash between the two, destroy the enrolment
record and leave the owner with no way to learn which devices they must still
visit. The statement made first survives that, because it has already been read.
The restatement afterwards is a convenience; the first statement is the guarantee.

**Completeness is why the act does not reuse the surface that already lists
devices.** The control socket's `list` bounds its answer at `LISTING_LIMIT` and
returns an `omitted` count, which is correct for an operator browsing enrolments
and wrong here: a report that named the first two hundred devices and counted the
rest would be a delete presenting itself as complete for every device it did not
name, which is the second clause of §8 breached by a paging default. Reading the
record directly costs nothing — the act is already in `service/` and already
opening that file to destroy it.

**The absent record is a real installation and not an edge case, which is why it
is ruled rather than left to an implementation's judgement.** `service/hub.py`
builds the `EnrolmentStore` only when `Settings.hub_remote_address` is configured,
so every loopback-only hub — which is every hub the corpus has shipped so far
(ADR-0124 §1's Context, and the hop is unimplemented on the client side) — holds
a full data directory and no `devices.db`. The trap is that `EnrolmentStore`
*creates* the file it is pointed at: an implementation that opened the record in
order to compose §7's list would write a database in the moment before destroying
everything, which is both absurd and, on a crashed run, a file left behind that the
installation never had. Saying the list is empty costs a stat.

**Confirmation is required because this act has no undo and one recovery.** The
only way back from it is restoring a backup (ADR-0123 §9), and a backup taken
before the act contains exactly the data the act destroyed. ADR-0073 §5 requires a
surface not to "represent a deletion as more final than it is, nor as less final";
here the true statement is maximally final, so the ceremony has to match, and it
has to be defeasible only by an operator who names the directory. Every per-item
delete in the CLI already shows what it will destroy before destroying it; this is
the same discipline at the scale where it matters most.

**The backup clause is the one an implementation would most naturally omit, and it
is the one that most cleanly breaches §8's second sentence.** ADR-0123 §11 requires
the artifact to be written outside `data_dir`, so after this act a complete
encrypted copy of everything it destroyed may still be sitting on the operator's
disk or in their off-machine custody. A report that did not say so would be
presenting the act as having purged everything, which the clause forbids in as many
words. This ADR does not reach the artifact — §10 — so saying so is the whole of
what it can do, and it is enough.

**Naming the act at each device is where §8's second clause has teeth**, and it is
why §9 sequences this behind something that does not exist yet.

### 8. No contract surface, and the version rule is examined rather than assumed

> **Normative.** No Protocol in `core/protocols.py` changes. No type, enum member
> or constant is added to `core/types.py`. `PROTOCOL_VERSION` is unchanged, and no
> lane implementing this decision changes it.

> **Normative.** No `AssistantEngine` method, no wire operation, no `assistant`
> CLI command and no `<data_dir>/admin.sock` act is created for this act.

> **Normative.** This ADR designates no seam under ADR-0017 §3, adds no boundary
> to ADR-0124 §1's enumeration, and authorises no component to transmit anything.
> The act opens no network connection.

**ADR-0124 §10 required a lane that needed `core` surface to stop and owe its own
contract ADR; this is that ADR, and the answer it returns is that none is needed.**
That is worth stating as a ruling rather than leaving as an absence, because the
issue that produced this lane expected the opposite. What removed the need was §2's
placement: an act inside `service/` reaching `service/enrolment.py` crosses no
contract, and a report printed to a terminal crosses no boundary that a shared type
would exist to describe.

**The version rule is examined and found unmet, in the pattern ADR-0084 §12 set
and ADR-0123 §11 followed.** ADR-0124 §9 bumps `PROTOCOL_VERSION` for "a change to
the encoding of a wire-carried value", "a change to a wire-carried `core` type" and
"any change to the promoted surface's method set or to a method's arguments or
results". This adds a console script. No frame changes, no `core` type changes, and
the promoted surface's method set is untouched — which is a consequence of §2's
prohibition rather than a coincidence, since the shape that *would* have bumped is
precisely the one ADR-0124 §6 forbids.

**The `PurgeReport` precedent is the right one for §7's report and is followed
rather than restated.** `orchestration/engine.py` carries a plain dataclass for the
retention sweep's result, with a comment recording that it is "maintenance surface
on a concrete class in `orchestration` (ADR-0083 §8), not something that crosses a
subsystem boundary". §7's report crosses even less: not a subsystem boundary and
not a process boundary, only the boundary between a program and the terminal it
prints to.

### 9. This cannot ship before the device-side unenrolment act exists

> **Normative.** No lane implements this decision before ADR-0124 §8's device-side
> unenrolment act exists in the tree. §7's report must name, for each device, the
> act at that device that purges its local credential, and a report that cannot
> name one does not satisfy ADR-0124 §8's second clause.

> **Normative.** Ratifying this ADR authorises no implementation lane on its own,
> and no lane may cite it to ship a delete surface whose report names an act that
> does not exist or offers the owner nothing to do.

**The prerequisite is real and its queue is already known.** The client half of
ADR-0124 is sequenced behind the `Secrets`/`SecretStore` triad (ADR-0125), which is
in flight; the unenrolment act ships with it, because removing the credential from
the device's keyring is what that act does. So the order is: the triad, the client
half including unenrolment, then this.

**Shipping earlier was considered and refused.** A purge tool that named no act
would satisfy §8's first clause and breach its second, and the breach is the one
that matters to the owner: they would read that their data was deleted, that some
devices were not reached, and that there is nothing they can do about it. #903
already records the residual for the period before either lands, and it is bounded
in ADR-0124 §8's own words — "a revoked credential verifies against nothing and the
hub identity beside it is not a secret, so an entry stranded on an unreachable
device opens no door". Waiting costs the delete right nothing it has today, because
today it has no surface at all.

**What this clause does not do is make the delete right hostage to the client
half indefinitely.** If the sequencing changes — if the unenrolment act is
descoped, or lands in a different shape — the remedy is an ADR revisiting this
clause, not a lane deciding on its own that a report naming nothing is good enough.

### 10. What this does not decide

> **Normative.** This ADR decides nothing about the export right. #692's gap is
> untouched, and no clause here is a surface for ADR-0004 §6's export, scoped or
> unscoped.

> **Normative.** This ADR does not fire either of ADR-0101 §7's two conditions,
> and no lane may read it as having done so. Both are about the export right; this
> act is a delete, and an unscoped destruction of everything is not ADR-0101 §1's
> subject-scoped erasure. ADR-0101 §8's symmetry clause binds §1's two operations
> and is untouched by an act that is neither of them.

> **Normative.** This ADR does not design ADR-0124 §8's device-side unenrolment
> act. It requires that act to exist (§9) and names it in the report (§7), and
> ADR-0124 §8 remains its sole authority.

> **Normative.** This ADR reaches no backup artifact. ADR-0123 is unmoved: the act
> destroys the contents of `data_dir`, an artifact is written outside it by §11 of
> that ADR, and nothing here destroys, invalidates or reads one.

> **Normative.** This ADR decides no retention rule. ADR-0007 §2's read-time
> expiry and the `retention_purge` job are untouched, and nothing here is a
> retention mechanism.

> **Normative.** This ADR authorises no scheduled or automatic invocation of the
> act, by the hub or by anything else. ADR-0123 §10 permits an external scheduler
> to stop the hub and run a *backup*; nothing in that permission reaches an
> irreversible destruction, and no lane may generalise it here.

**The ADR-0101 boundary is the one worth being exact about, because the two acts
share a word and nothing else.** ADR-0101 §1's erasure destroys the records that
state a matching subject label, and its §6 requires a surface to state, every time,
that it covers only records whose subject was stated. That disclosure is
meaningless for an act that destroys the whole directory: there is no unreached
remainder inside the store to confess. Conversely §7's report confesses a remainder
ADR-0101's erasure never has — devices on other machines. They are different acts
with different honesty obligations, and a lane that implemented one by citing the
other would get both wrong.

### 11. ADR-0004 §7's gate cannot reach this act, so it is superseded for it rather than left engaged and unmet

> **Normative.** ADR-0004 §7's gating clause is superseded **only** for this act —
> the offline whole-installation delete §1 and §2 define, performed by the owner at
> the hub's own machine with the hub stopped — and for nothing else. Every other
> Tier 0 and Tier 1 access, in the hub and in every other tool, stays under §7
> unchanged, and no lane may cite this clause to widen the exemption to a second
> access.

> **Normative.** Three replacements stand in the exemption's place, and an
> implementation that omits any of them does not have it: the act is confined to one
> purpose and one path, destroying the resolved `data_dir` and nothing else, with no
> argument that widens it; custody is the operating system's own access control — the
> data directory is owner-only at `0700` (ADR-0083 §3), the act runs as the owner's
> own user, and the instance lock is the kernel's (ADR-0083 §1); and the owner's
> confirmation against the resolved path (§7) is taken before anything is destroyed,
> in person, at that machine.

> **Normative.** No record of the act survives inside this system, and that is
> required rather than tolerated. The act writes no audit record anywhere, and no
> lane may make it write one that outlives the directory it destroys.

> **Normative.** This ADR does not cite ADR-0124 §6's exemption, does not widen it,
> and does not rest on it. That clause is confined to a client's bootstrap
> credential read and stays so; this is a separate access with its own argument,
> and if that argument is rejected this exemption falls with it.

**Both halves of §7 are structurally unavailable here, and neither is unavailable
by choice.** `permissions/` runs inside the hub and the audit trail is a Tier 1
store the hub owns exclusively (ADR-0083). This act runs with the hub stopped —
which §2 shows is forced rather than preferred — so there is no policy layer
running to consult. And the audit trail is `<data_dir>/audit.db`: a record of the
act would be written into a file the act removes moments later, which is not a
record but a rounding error.

**Building the gate anyway was considered and it produces nothing.** `service` may
import `app` (ADR-0083 §8), so the tool could construct a permission policy through
the composition root rather than reaching a subsystem directly, and §3's "imports no
subsystem directly" would survive. What it would evaluate is a request from the
owner, at their own terminal, on their own machine, for an act §7 already requires
them to confirm by naming the directory — and ADR-0004 §7's own words make the gate
"transparent and reviewable", a property supplied by a record that here cannot
exist. It would be ceremony that consumes a decision and writes it to a file it is
about to unlink.

**The audit residue is not merely impossible, it is forbidden, and that is what
makes the supersession principled rather than convenient.** A durable record saying
"the owner destroyed everything on this date" is Tier 1 data about the owner,
surviving in a system they asked to hold nothing. It is §4's argument about the
enrolment record, arriving a second time on a different file: the two clauses
ADR-0004 grants — a gate that records, and a purge that leaves nothing — cannot both
hold for the act that empties the installation, and the one that gives way is the
one whose whole purpose is to make *later* accesses reviewable.

**What is lost is real and is named rather than smoothed over, in ADR-0124 §6's
posture.** An OS permission on a directory is custody, not a policy decision
traceable to an answer about *this* access; a confirmation at a terminal is
evidence only to the person who gave it; and nothing anywhere in this system will
afterwards be able to say the act happened. The owner's own shell history and their
own machine's logs are outside this system and are not offered as a substitute.
That is the price of an act whose purpose is to leave nothing behind, it is bounded
to one act on one path, and it is paid visibly here rather than deferred to an issue
that would make it look temporary.

**#74 is untouched.** It asks whether §7's gate reaches the model provider
credential, and this ADR neither answers it nor moves it; ADR-0125 §9 says the same
of its own seam.

### 12. Records under ADR-0070 §1 and ADR-0082 §1

**ADR-0124 §6 — partially superseded, one clause, and the record lands in this
change.** The clause is "A revocation is recorded rather than erasing the enrolment
it revokes, so the record says what the owner actually decided and when."
ADR-0070 §1's test: a reader holding only §6 would read it as governing every act
that ends an enrolment, and would implement §4 above by writing a revocation row
into a file the same act then destroys — or worse, by preserving the record through
the delete so that the row survives to be read. That is the clause "read more
widely than it now holds", which is ADR-0070 §1's second limb and requires a
supersession rather than an amendment. It is narrow in the way ADR-0124 §8's own
supersession of ADR-0004 §6 is narrow: one act, named, with everything else of the
section standing. ADR-0124's `Status` line gains the pair and its appended dated
note carries the record (ADR-0082 §1 and §2).

**ADR-0004 §7 — partially superseded, one clause, one act, and the record lands in
this change alongside §6's.** The clause is "Access to Tier 0/1 data and every side-effecting tool
call is gated by the `permissions/` layer and recorded in an **audit trail**".
ADR-0070 §1's test: a reader holding only §7 would read it as reaching this act,
and would either build a gate that evaluates nothing against a policy layer that is
not running, or write an audit record into the file the act is about to unlink —
and on discovering neither is possible would conclude the act may not exist. That is
a clause read more widely than it now holds, ADR-0070 §1's second limb. §11 above
carries the argument and the three replacements. ADR-0004's `Status` line is not a
leading-token line, so under ADR-0082 §2 the pair accumulates on it and the dated
note carries the record; both are written in this change.

**ADR-0004 §6 — partially superseded, one clause, one place a credential can sit,
and the record lands in this change.** The clause is "Deleting the user's data
purges Tier 0 (keyring entries) and Tier 1 (database rows) together", already
narrowed once by ADR-0124 §8 as it reaches an enrolled device. ADR-0070 §1's test:
a reader holding only §6 would believe this act purged every Tier 0 credential on
the hub's machine, and would be wrong about the provider key the SDK reads from the
process environment — a clause read more widely than it now holds, ADR-0070 §1's
second limb. §6 above carries the argument and the replacement, which is that the
act names the credential it did not purge and the act at which the owner removes
it. It is narrow in the same way ADR-0124 §8's was: one unreachable custodian,
named, with the whole of the rest of §6 standing — view, export, delete, retention
rules, every Tier 1 artifact, and every Tier 0 artifact that *is* in the keyring.
It is also self-limiting, lapsing for any credential a later lane moves into the
keyring. **#909** is the separate question of how the act would reach one there,
and it is not this record.

**ADR-0007 §4 and §5 — no record owed.** §4 says `MemoryStore.clear` "is not a
whole-system erase" and that "the cross-tier coordinator is future work"; §5 defers
"Cross-tier 'delete everything' (keyring + database)". Both sentences stay true:
`clear` is still not a whole-system erase, and the coordinator this ADR supplies is
the future work §4 pointed at, arriving rather than being redefined. A reader
acts identically. Stacked addition.

**ADR-0123 §10 — no record owed.** Its clause gives backup and restore "their own
console entry point in `ai_assistant/service/`, beside `ai-assistant-hub`,
`ai-assistant-reembed` and `ai-assistant-measures`", and calls them "the fourth
member of the offline family". Both remain accurate statements about backup and
restore and about the family as it stood; a fifth member joining does not make
either false, and nothing in §10 closes the family. Stacked addition. §3's forward
clause about a *new file in the data directory* is likewise untouched: this ADR
places no file there.

**ADR-0125 §5 and §8 — no record owed, and §6 above was rewritten to keep it that
way.** §5's marked clause is obeyed rather than narrowed: no enumeration is
performed, and the report does not present a skipped scope as complete. §8's clause
that `service` holds neither face is obeyed by the act reaching no keyring at all.
An earlier draft of §6 required the act to delete each hub-side holder's entries
"through the seam ADR-0125 §1 declares", which would have put a `SecretStore` in
`service` and made §8's sentence false for this act — architecture review named it,
and the answer was to obey the clause and file the open question as **#909**, not to
claim an exemption. Stacked addition.

**ADR-0101 — no record owed.** §10 above states that neither of §7's conditions
fires and that §8's symmetry clause is untouched. No sentence of ADR-0101 becomes
false or over-wide; a reader acts identically.

**ADR-0085 §3 — no record owed.** The promoted surface is unchanged. §2's
prohibition on an engine method means §3's method set neither grows nor changes,
so nothing in it is read differently.

## Consequences

- **ADR-0004 §6's delete right gets its first whole-installation surface**, and
  ADR-0007 §5's cross-tier deferral — open since 2026-07-17 — is discharged by an
  act rather than by another deferral.
- **#903's seam is not built, and the issue closes on a decision rather than an
  implementation.** No callback crosses `app`, no contract is added, and
  `lint-imports`' "nothing imports the service" contract is satisfied by placement
  instead of by indirection.
- **The offline family gains a fifth member** and, with ADR-0123's pair, a shape:
  an act whose subject is `Settings.data_dir` is an offline console script in
  `service/` taking the instance lock. Three ADRs have now reached that placement
  independently, and a fourth lane should treat it as the default rather than
  re-deriving it.
- **The delete right requires stopping the hub**, which is a worse surface than an
  in-session command and is the accepted cost of §2. A future decision that wants
  the better surface owes a way for the promoted surface to be reachable from
  loopback and not from the remote listener; nothing here forecloses it and
  nothing here supplies it.
- **The act is sequenced behind the client half of ADR-0124** (§9), so the leg that
  lands it is the one that lands unenrolment. A lane briefed on this ADR before
  that exists has nothing to build.
- **A crash mid-act leaves a partially destroyed data directory**, recoverable by
  rerunning the command and never by a hub, since the ordering guarantees no
  enrolment survives the first successful destruction. There is no resume, and none
  is designed: the act is idempotent by being repeatable.
- **`devices.db` is now a file two ratified rules govern in opposite directions** —
  ADR-0124 §6 says a revocation never erases it, this ADR says one act destroys it
  — and an implementation that conflates them breaches one of them. §4's second
  clause is what a reviewer checks against.
- **ADR-0004 §6's Tier 0 half is not discharged on the hub's machine, and the ADR
  says so instead of counting an empty keyring as an empty tier.** Two different
  states sit under one clause. The *keyring-held* set is empty today, so the act
  misses nothing there — and it has no mechanism behind it either, so the moment
  something writes an entry the purge path becomes a contract question, because
  ADR-0125 §5 puts deletion on the consumer and §8 keeps `service` out of the seam;
  **#909** carries that and only that. The *environment-held* provider credential
  is Tier 0, is on that machine, and stays after the act — which §6 partially
  supersedes ADR-0004 §6 for, against a replacement the implementing lane owes: the
  report names it as not purged and names where the owner removes it. A purge that
  omitted that line would breach a clause of this ADR, not merely fall short of a
  hope in it.
- **Revisit if** the delete right acquires an in-session surface, if a component on
  the hub's machine starts holding a Tier 0 keyring entry (#909 fires first), if
  ADR-0124 §8's device-side unenrolment act is descoped (§9), or if a
  later decision puts a file in the data directory that must survive a delete —
  which this ADR does not contemplate and which would need its own exclusion and
  its own argument.

## Alternatives considered

**An `AssistantEngine` method with a `core` report type, and a callback injected
at the composition root.** This is #903's expected shape and it is refused by
ADR-0124 §6's first clause rather than on taste: `wire/surface.py` derives the wire
method set from the Protocol, so the method would be callable from an enrolled
device across the remote transport, and a remote connection modifying every
enrolment is exactly what that clause forbids. It would also bump
`PROTOCOL_VERSION` (ADR-0124 §9), promote a report type into `core/types.py` for a
value that crosses no boundary, and require a callback edge from `service` through
`app` into `Engine` to reach a record that a tool in `service/` can simply open.

**A fourth act on `<data_dir>/admin.sock`.** Attractive because the socket is
already hub-local, already owner-only, and already the place device acts happen —
and it would satisfy §8's connection clause actively rather than vacuously. It
fails on the act's subject: a running hub cannot destroy the directory it holds
open, so the act would have to be per-store `clear` calls, which §1 shows is not a
delete. It would also contradict the socket's own ratified-in-code boundary
("three acts on the enrolment record and nothing else") and make the control
socket a second engine.

**Delete-by-`clear`: call every store's `clear` and revoke every enrolment.** This
is the shape that needs no new placement and no supersession, and it is why it was
taken seriously. It leaves file contents, free pages and write-ahead logs on disk;
it reaches only stores that have a `clear` and drifts the moment a lane adds one;
and it cannot purge the enrolment record at all, because ADR-0124 §6 forbids
erasing an enrolment — so the owner's device history would survive their delete.
The last of those is not a quality gap but a contradiction of ADR-0004 §6, and it
is what forced §4's supersession rather than avoided it.

**Revoke first through the running hub, then stop it, then destroy the directory.**
A two-phase act: the control socket revokes every enrolment and closes every
connection while the hub runs, then the offline tool destroys the directory. It
satisfies both §8 clauses with nothing to argue, and it is refused because "as part
of the same act" would become a claim about two commands an operator runs in order.
The window between them is unbounded and the failure in it is silent: an operator
who runs the first and not the second has revoked every device and deleted nothing,
with no record anywhere that the act was begun. §5's ordering achieves the same
guarantee inside one lock with no window to leave open.

**Purging Tier 0 from inside the act, by giving the tool a `SecretStore`.** This
is what §6 said in an earlier draft, and it is the shape a reader arrives at from
ADR-0125 §5 alone — "every consumer that writes an entry owes a path that deletes
it" reads like an instruction to compose the deletions somewhere, and this act is
the obvious somewhere. It is refused because ADR-0125 §8 names `service` among the
packages that hold neither face and forbids acquiring one without the ADR its §2
requires. Seeking that exemption here would be a `core` decision arriving inside an
ADR about a directory, which is the move golden rule 5 and ADR-0124 §10 both exist
to stop. What §6 does instead is obey both clauses, record that the set they govern
is empty today, and bind the lane that first makes it non-empty to decide the
question (**#909**) rather than inherit a tool that cannot answer it.

**Naming the tool `ai-assistant-erase`.** Shorter and unambiguous against the
retention senses of "purge" in the tree. Refused because ADR-0101 uses "erasure"
throughout for the subject-scoped operation §10 keeps separate, and a console script
called `erase` would be the natural name for that operation's surface if it ever
lands — a collision between two acts with different reach and different honesty
obligations is worse than a vocabulary overlap with four store methods that share no
namespace with it.
