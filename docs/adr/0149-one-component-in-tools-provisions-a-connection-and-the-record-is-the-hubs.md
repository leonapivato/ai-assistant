# 149. One component in `tools/` provisions a connection, and the record it writes is the hub's

- Status: Proposed
- Date: 2026-08-13
- **Decides** the two questions ADR-0148 §11's fourth clause and ADR-0148 §13's
  ninth bullet name as undecided — who performs a provisioning act, and where a
  connection record lives — and with them the half of ADR-0125 §12's "a
  provisioning surface" bullet that reaches **an integration credential**. The
  provider key's half stays where ADR-0125 §12's first bullet and #74 put it
  (§11).
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-13**,
  the durability form ADR-0100 established. This decision rests most heavily on
  ADR-0148, ratified the same day, and on ADR-0125, whose §8 carries the clause
  a new holder of a keyring face has to get past; a citation that silently means
  "whatever that ADR says when you read it" is not checkable. Where a later ADR
  changes one of them, this one is read against the text named here until an ADR
  says otherwise.
- **Records for ratification: one dated note appended to ADR-0125's header**,
  applied in the same commit that flips this ADR's `Status` to `Accepted` and not
  before — ADR-0017 §7 requires the operation performed on another ADR to be
  recorded rather than inferred, and writing "discharged by ADR-0149" onto
  ADR-0125 while this ADR is `Proposed` would be the state claim ADR-0019
  forbids. §10 applies ADR-0082 §1's test to every ADR this one touches and shows
  its working. **No `Status` line moves and no ratified text is rewritten.**
- **No implementation lands with it.** No `src/`, no `tests/`, no
  `pyproject.toml`. Nothing implements a provisioning act on the strength of this
  ADR alone: the act is reached through contract surface that does not exist, and
  §8 says what is owed and who owes it.
- **It decides no `core` surface and names one that is owed.** §7 defers the
  shape of that surface, with its firing condition, to the contract ADR that
  decides the operations it serves — the split ADR-0097 §9 made and ADR-0102
  discharged, taken deliberately rather than by resemblance.
- **Its required review set is adversarial *and* architecture.** It decides who
  may hold a write face onto the keyring, where a new durable Tier 1 store lives,
  and the shape a still-undecided contract surface has to be able to land into —
  each answerable from prose before an implementation commits to an answer
  (`CONTRIBUTING.md` → "Contract ADRs land before their implementation"). §13
  records the set that ran and the order it ran in.

## Context

### What ADR-0148 §6 fixed, and the one thing it could not

ADR-0148 §6 decided the **semantics** of provisioning in unusual detail, because
its authorisation-time checks read what a provisioning act writes and an act
performed any other way makes those checks unsound. A connection record carries
an account **identity**, a monotonic **revision**, a **provisioning state** that
is *pending* or *active*, and the **credential slot** — a `SecretName`
(ADR-0125 §2) — that the act which wrote the record wrote its credential to. An
act is three writes in a fixed order: the record first as *pending*, the
credential second, the record *active* third. At most one act owns a record at a
time and it takes ownership by a compare-and-swap on that record. The activation
is itself a compare-and-swap, and it is the write that decides which credential
is live. A displaced act's late write lands in a slot no live record names. An
act deletes its predecessor's slot once its own activation has landed.

What §6 does not say is **whose hands** perform any of it. It names no component,
grants no keyring face, and locates no record. §11's fourth clause says so
normatively and forbids the obvious shortcut:

> Neither surface is the **provisioning act's owner**, and this ADR gives no
> component a keyring face. Who holds an `INTEGRATION`-scoped `SecretStore`
> (ADR-0125 §1, §2) to perform §6's credential write and its predecessor
> deletion, and where a connection record lives, are ADR-0125 §12's undecided
> provisioning surface and are not decided here (§13). No lane reads §6 as
> authorising a component to hold a face ADR-0125 §8 does not give it, and no
> lane implements a provisioning act before the ADR that names its owner has
> merged.

This is that ADR. Until it merges, ADR-0148 §6 is a specification with no party
entitled to satisfy it, and every mechanism §6 exists to protect is unreachable —
including the ones ADR-0148 §14 requires the implementing lanes to test.

### What ADR-0125 already binds, and the clause a new holder has to get past

ADR-0125 §1 splits the keyring seam into two faces: `Secrets` reads,
`SecretStore` extends it and adds `set` and `delete`. §2 binds an instance to one
installation and one `SecretScope`, so a consumer reaches only the scope it was
handed. §8 then says who holds which face — and its fourth clause is the one a
new holder meets:

> No other subsystem holds either face. `orchestration`, `memory`, `context`,
> `planning`, `permissions`, `learning`, `readers`, `evaluation`, `service` and
> `interfaces` hold neither, and none of them may acquire one without the ADR §2
> requires for a fourth scope.

The enumeration is exhaustive of what it names and it is closed against those ten
subsystems. It does not name `tools/`, and it does not name `tools/` because
§8's second clause has already spoken about it: "`tools/` holds `Secrets` at the
tool that needs one, by injection, for `INTEGRATION`-scoped reads. `ToolRegistry`
and `ToolInvoker` hold neither face." §2's own reasoning calls the scope words in
this section "mechanical, not advisory". §12's provisioning bullet then scopes
out the surface this ADR decides, in terms that reach "a provider key **or an
integration credential**".

### The tree, read rather than remembered

Checked on the branch this ADR was written on, at `origin/main`:

- `core/protocols.py` declares `Secrets` and `SecretStore`; `core/types.py`
  carries `SecretName`, `SecretScope` and `SecretValue`. The seam is contracted
  and implemented: `ai_assistant.secret_store` holds the concrete keyring
  backing, behind the import-linter contracts `the secret store depends on core
  and nothing else`, `no subsystem imports the secret store` and `the keyring
  library is confined to the secret store`.
- **No `INTEGRATION`-scoped instance is wired anywhere.** `build_engine` in
  `ai_assistant.app.composition` constructs neither face, and no module under
  `tools/` names one. So this ADR grants a face to a component that does not
  exist yet rather than relocating one that does.
- `tools/` holds `registry.py`, `invocation.py`, `builtin.py` and `egress.py`.
  The last is the seam ADR-0147 §3 named, and it is deliberately empty: it holds
  no client, no connection and no constant, and `tools/` transmits nothing.
- Nothing in the tree holds a connection record, an account identity, or a
  credential slot. There is no integration to connect.

### Every reader ADR-0148 §6 names is already inside `tools/`

This is the fact the placement turns on, and it is read out of §6 rather than
chosen. Three parties consult a connection record:

- **the callable**, which reads "the identity, revision, provisioning state and
  slot recorded for the bound reference" and then calls `Secrets.get` for that
  slot with no `await` between the two — and re-reads them after. A callable is
  reached by `ToolInvoker.invoke` (ADR-0029 §1), which puts it inside `tools/`,
  and ADR-0029 §1 is explicit that how it is reached "is `tools/`-internal, and
  this ADR does not contract it";
- **ADR-0148 §11(b)'s seam**, which refuses to build an `ActionRequest` against a
  reference that is not connectable — a seam ADR-0148 §11 places in `tools/`
  because "every part of which is integration-specific knowledge living in
  `tools/`";
- **the provisioning act itself**, which takes the record by compare-and-swap and
  re-reads it before each of its two remaining writes.

Two of the three are already in `tools/` by ratified decisions this ADR may not
disturb. Only the third is open.

### What this ADR is not allowed to settle

- **ADR-0148 §6's semantics.** The record's fields, the write order, the
  compare-and-swap, the interrupted-act rule and every check the callable
  performs are ratified. This ADR consumes them and contradicts none; where it
  adds, it adds beside them and says so (§5, §6).
- **The two `core` surfaces ADR-0148 §11 names.** (a) the egress binding and
  (b) the seam that supplies it are each "decided in a contract ADR of its own",
  and neither is this one.
- **ADR-0017 §3's conditions, and the designation of the `tools/` egress seam.**
  Nothing here attests a condition, designates a seam, or authorises a byte to
  leave the device.
- **ADR-0147 §4's stdio question** (§11).
- **Whether a credential read is a permission subject** — #74, left exactly where
  ADR-0125 §9 left it (§9).

## Decision

### 1. The provisioning act is performed by one component in `tools/`, and it holds the only `INTEGRATION`-scoped `SecretStore`

> **Normative.** ADR-0148 §6's provisioning act is performed by **one component
> in `tools/`** — the *connection provisioner* — and by nothing else. It holds an
> `INTEGRATION`-scoped `SecretStore` (ADR-0125 §1, §2) by injection from the
> composition root, and it is the only holder of a `SecretStore` for that scope
> in the system.

> **Normative.** The provisioner lives in one module under `ai_assistant.tools`
> that is **not** `ai_assistant.tools.egress`, is not `registry.py` and is not
> `invocation.py`. Its name is the implementing lane's, which also adds it to
> `CLAUDE.md`'s architecture map if that map names modules at that granularity.

> **Normative.** The provisioner is **not a tool**. No `ToolDefinition` binds it,
> it is never registered in a `ToolRegistry`, it is not reachable through
> `ToolInvoker.invoke`, no callable holds a reference to it, and no plan step and
> no model-authored value reaches it (ADR-0102 §8's prohibitions, transposed).

> **Normative.** The provisioner calls `set` and `delete` and **never calls
> `get`**. It reads no credential value, and no credential value it wrote is read
> back by it or returned by any operation it serves. ADR-0148 §7's rule — that an
> `INTEGRATION`-scoped credential is read only from inside a callable reached by
> `ToolInvoker.invoke`, after ADR-0029 §2's three seam checks — is therefore
> untouched by this ADR and is inherited exactly as written.

> **Normative.** The provisioning act performs **no network I/O and launches no
> subprocess**: it opens no socket, contacts no service to verify an identity or
> a credential, and reaches no MCP server. ADR-0147 §3's rule confining transport
> to the egress seam binds it like every other module under `tools/`, and this
> ADR neither designates that seam nor relaxes any condition of ADR-0017 §3.

> **Normative.** No component acquires an `INTEGRATION`-scoped `SecretStore` on
> the strength of this ADR other than the provisioner. A tool keeps `Secrets` and
> nothing wider (ADR-0125 §8), `ToolRegistry` and `ToolInvoker` keep neither
> face, and the ten subsystems ADR-0125 §8's fourth clause enumerates keep
> neither.

**Placing it anywhere else costs two Protocols and a supersession, and buys
nothing.** The alternative with the strongest precedent is `orchestration`, where
ADR-0102 §7 put the grant operations in one object holding a `SourceGrantStore`.
Follow it here and the record's other two readers — the callable and ADR-0148
§11(b)'s seam, both in `tools/` — must reach the connection record across a
subsystem boundary, which golden rule 1 makes a Protocol in `core/protocols.py`,
and ADR-0097 §3's own reasoning makes it **two**: a reading face for the parties
that must not write, and a writing face for the one that does. Two Protocols are
two triads (`tests/core/test_protocol_triad.py` enforces it with no exemption
available). And `orchestration` holding a `SecretStore` contradicts ADR-0125 §8's
fourth clause in terms, which is a change to what §8 decided and therefore a
partial supersession of it (ADR-0070 §1), not a stacked addition. Putting the
writer where the readers already are costs **one** Protocol — the user-facing one
§7 keeps — leaves the record's own seam `tools/`-internal (§3), and leaves every
sentence of ADR-0125 §8 true (§2).

**A leaf package outside every subsystem was the other candidate and it is
refused for the same reason.** ADR-0125 §8's fifth clause uses that shape for the
keyring *implementation*, and `readers/`, `evaluation/` and `secret_store/` each
earn it by having no subsystem consumer. A connection provisioner has two
consumers inside `tools/` on day one, so the leaf shape would create precisely
the cross-package seam the placement exists to avoid, and would do it while
splitting one concept across two packages.

**Why the provisioner is not simply the tool.** ADR-0125 §8 hands `Secrets` to
"the tool that needs one", and the tempting economy is to let that tool provision
itself. It is refused on ADR-0097 §3's argument, which is the same argument one
level down: a component that can write its own credential is a component that can
be handed one by anything that can reach it, and the whole of ADR-0148 §6's
identity binding rests on the credential under a slot being the one a *user act*
put there. Removing `set` and `delete` from what a tool's dependency can express
is a type rather than a promise, and it is what ADR-0125 §1 already bought when
it split the faces.

### 2. How this squares with ADR-0125 §8, stated rather than assumed

**§8's fourth clause does not reach `tools/`, and that is not a loophole — it is
the clause's own structure.** "No other subsystem holds either face" is *other*
than the three the preceding clauses named: `models/`, `tools/`, and the wire
client. The enumeration that follows then lists exactly the ten remaining
subsystems, and `tools/` is absent from it because §8's second clause had already
spoken about `tools/`. Reading the absence as an oversight would require reading
`models/` out of the enumeration as an oversight too — and §8's first clause
tells us what §8 does when it means to deny a write face to a subsystem it has
already addressed: "It does not hold `SecretStore`; provisioning a provider
credential is not `models/`'s." No such sentence was written about `tools/`.

**ADR-0125 is a marked ADR, so ADR-0089 §3 decides what it obligates.** Its
marked clauses are the whole of its obligations; unmarked text is read to
determine what a marked clause *means* and never supplies one. §8's marked
clauses say what `models/`, `tools/`, the wire client and the ten enumerated
subsystems hold; the surrounding prose explains why. Nothing marked in ADR-0125
forbids a component in `tools/` a `SecretStore` bound to `INTEGRATION`.

**Nor does the section's title, which is the strongest counter-reading.** "no
second path to the keyring" is made concrete by two marked clauses, and both are
satisfied here: one concrete keyring-backed implementation exists in a leaf
package no subsystem imports and reaches every consumer by injection — the
provisioner receives an instance and constructs none — and "no lane may add a new
path to a Tier 0 credential — an environment read, a file read, or a direct
keyring import". This ADR adds no path. It adds a **holder** of the contracted
one, which is the act ADR-0125 §12 scoped out for a later ADR to perform and
ADR-0148 §13 confirms is "that ADR's to do rather than this one's".

**The residual §2 already named is not widened.** ADR-0125 §2 accepts that
"within `INTEGRATION`, one tool can read another's credential", because tools are
code in this repository behind ADR-0016's registry rather than third-party
plugins. §1's confinement clauses keep the *write* face narrower than that
accepted read: exactly one module holds it, it is not a tool, and nothing a model
or a plan steers can reach it. What changes if that premise changes — a plugin
model, or an MCP server admitted as a tool author — is that both the residual and
this placement want revisiting, and ADR-0125 §2 already says the fix would be
additive: a capability narrower than a scope, handed out at the same wiring
point.

**§10 applies ADR-0082 §1's test to §8 and finds no record owed.** Every sentence
of §8 stays true, and a reader holding only ADR-0125 wires exactly what they
wired before.

### 3. The connection record is the hub's, under `Settings.data_dir`, and its store is `tools/`-internal

> **Normative.** The connection record ADR-0148 §6 specifies is **durable
> hub-side state under `Settings.data_dir`** (ADR-0083 §2), held in a store
> opened by `build_engine` with owner-only permissions and closed with the other
> stores it opens. It is never a `Settings` field, never a file the user is asked
> to edit, never client-side state, and never carried in a plan, a conversation
> or a trace.

> **Normative.** That store is implemented in `tools/` and its seam is
> `tools/`-internal. This ADR adds **no** Protocol to `core/protocols.py` for
> reading or writing a connection record, and no lane adds one on the strength of
> it: every party ADR-0148 §6 lets consult a record is inside `tools/`, and a
> `core` seam between two modules of one subsystem is surface with no boundary to
> hold.

> **Normative.** A connection record is a **Tier 1** store (ADR-0004 §1): the
> account identity ADR-0148 §6 requires is a user-recognisable name and may be
> personal data. It is therefore subject to ADR-0004 §6's rights — the deletion
> path purges the record **and** the credential slot it names together — and to
> ADR-0004 §5's logging rule: no log line, error message or operator diagnostic
> emitted by the provisioner or by a callable carries an account identity. The
> **connection reference** and the **credential slot** are non-secret handles
> chosen by code (ADR-0125 §2) and may be logged.

> **Normative.** A connection record holds **no credential value** and no value
> derived from one, in any field, including the identity (ADR-0148 §6's
> exclusion clause, applied to the record the same clause creates).

**The record is what makes ADR-0004 §6's Tier 0 purge composable, and that is a
consequence worth stating.** ADR-0125 §5 refuses enumeration — no method lists
the entries in an installation — and ADR-0125 §10 draws the conclusion for a
neighbouring lane: "its purge path is composed from names it recorded rather than
discovered". The connection record is that recorded list for the `INTEGRATION`
scope. A design that kept the slot only in memory, or reconstructed it from a
convention, would leave the keyring holding entries nothing can name, which is
exactly the state ADR-0004 §6's "purges Tier 0 and Tier 1 together" cannot be
satisfied from.

**`build_engine` opens it for ADR-0102 §7's reason, unchanged.** Every other Tier
1 store in this system — memory, the audit trail, plans, conversations, the
deferral queue, the grant store — appears in `build_engine`'s `closers` list, and
putting the seventh somewhere else would be a second wiring convention bought for
nothing. That the composition root constructs the store does not make it a
*holder* in ADR-0125 §8's or ADR-0097 §9's sense: §8's clauses are about which
component may name `set`, and ADR-0097 §3 already contemplated exactly this
wiring in its own words.

**The store is not the registry, and nothing here makes the registry
persistent.** ADR-0016 §6 keeps the registry in-memory and holding configuration
rather than personal data, and ADR-0016 §7 defers a persistent registry. A
connection record is not a `ToolDefinition`, is not keyed by a tool id, and is
not read by `find`; the registry stays exactly as ratified, rebuilt each run.

**One resident process does not relieve the compare-and-swap.** ADR-0083 §1 puts
one hub per data directory and §10 enforces exclusivity, so two provisioning acts
race inside one process today rather than across two. ADR-0148 §6 states the
compare-and-swap over the record regardless, and the store provides it durably
rather than by relying on the event loop: the property §6 needs is that a
displacing act's activation is *observable* to the act it displaced, and an
in-process convention would stop being true the first time anything outside the
hub writes the store.

### 4. A connection is created only by an explicit user act, and it is not a grant

> **Normative.** A connection is created, re-provisioned and disconnected
> **only** by an explicit user act through a client (ADR-0084). No `Settings`
> value, existing configuration, upgrade, migration, first run, backup restore,
> scheduler job (ADR-0083 §7), plan step, tool, callable or model may create,
> re-provision or disconnect one, and none may supply the account identity or the
> credential for one.

> **Normative.** The **account identity** ADR-0148 §6 binds is supplied by the
> user in the same act that supplies the credential, and is recorded verbatim. No
> component infers it from a credential, a slot, a reference, an endpoint, a
> `Settings` value or a remote lookup — the first four are ADR-0148 §6's own
> prohibition and the last is an egress call this system is not entitled to make
> (ADR-0148 §5).

> **Normative.** A connection record is **not** a `SourceGrant` (ADR-0097 §1),
> is not written to the grant store, and is not read by `SourceGrants.live`. No
> `GrantScope` member covers connecting an account, and no lane adds one for it.

> **Normative.** A connection **authorises nothing**. It makes a reference
> connectable (ADR-0148 §6) and supplies the credential a callable reads; every
> call under it is still authorised as a whole by ADR-0148 §1 and ruled by
> `ActionPolicy` under ADR-0021. No surface may present connecting an account as
> permission to act with it, and no ruling may rest on the existence of a
> connection.

**"Configuration is not consent" binds connecting, and this is where it is most
tempting to break.** ADR-0097 §8 forbids minting a grant "from a `Settings`
value, an existing source path, an already-ingested belief, an upgrade, a
migration, or a first run", and its reasoning transfers without adjustment: an
installation that acquires a live connection because a key was found in the
environment, or because an upgrade migrated one, holds a connection record with
no user act behind it — and ADR-0148 §6's whole identity binding then attests
something nobody asserted. The cost is the same small cost ADR-0097 §8 accepted:
today no integration exists, so the population that must perform one act is
empty.

**A connection is not grant-shaped, and saying which parts do and do not transfer
is the point of naming it.** What transfers is the *act*: a recorded user
decision, hub-side, reached through a client, unavailable to a model, unmintable
from configuration. What does not transfer is the *record*:

- **The subject differs.** A grant's subject is a reader's declared identity — a
  declared constant, which is what keeps personal data out of it (ADR-0097 §1,
  ADR-0093 §7). A connection's subject is an account, and its identity is
  precisely the user-recognisable value a declared constant may not be. That is
  why §3 rules the store Tier 1 and keeps the identity out of logs, where a grant
  needed no such rule.
- **The mutation semantics differ, and cannot be reconciled.** A grant store is
  append-only and a revocation is a new record (ADR-0097 §4). ADR-0148 §6
  requires a *live* record that an act takes by compare-and-swap and mutates
  through two states. A store cannot be both without deciding which one ADR-0148
  §6's checks read, and §6 already decided: they read the record.
- **The axis differs.** `VISION.md` governs reading and acting separately, and
  ADR-0097 §3 quotes it against exactly this merge: "Collapsing the two into one
  notion of 'integration' would either over-restrict reading or under-restrict
  acting." A grant is standing authorisation to *read* a source; a connection is
  the provenance of a credential on the *acting* side, where ADR-0148 makes every
  call individually authorised. Making a connection an authorisation would create
  the standing act-authorisation ADR-0021 §6 defers and §11 keeps deferred.

**Nothing here is gated by `permissions/`, and that is deliberate.** A
provisioning act is the user acting, not the assistant proposing — the shape
ADR-0021 §1 has the audit trail record as "a human answered". Grants are not
ruled by `ActionPolicy` either (ADR-0102 carries no gate), for the same reason.
What stays open and untouched is the *other* question: whether a credential
**read** is a permission subject is #74's, and ADR-0125 §9 keeps it open (§9).

### 5. Disconnection is a user act, it is prospective, and it never resets a revision

> **Normative.** Disconnecting a reference is **two writes in a fixed order**:
> the connection record ceases to be live **first**, and the credential slot it
> named is deleted **second**. No other order is permitted.

> **Normative.** After the first write the reference is **not connectable** in
> ADR-0148 §6's sense — no `ActionRequest` is built against it, no ruling is
> sought for one, and no callable transmits under it — and the disconnection
> introduces **no third provisioning state**: ADR-0148 §6's states remain exactly
> *pending* and *active*, and a disconnected reference has no live record at all.

> **Normative.** A disconnection **does not reset the reference's revision**. The
> store retains, durably and per reference, the highest revision it has ever
> issued for that reference, and a later provisioning act on the same reference
> takes a revision strictly greater than it. ADR-0148 §6's "A revision is never
> reused and never decreases" holds across disconnection and re-connection, not
> only within one connected life.

> **Normative.** A slot deletion that fails leaves an **unreferenced slot** rather
> than a live credential no record describes; the failure is reported and never
> suppressed, and the reference stays disconnected. This is ADR-0148 §6's rule for
> a predecessor slot, applied to the deletion that ends a connection.

> **Normative.** A disconnection is **prospective**. It does not wait for, cancel
> or report a transmission already in flight, and **no surface may present it as
> having stopped one** (ADR-0102 §9's rule, and ADR-0148 §6's own clause that no
> lane holds a lease across the transport's write). A parked confirmation against
> a disconnected reference is refused when it resumes, by connectability.

**The order is ADR-0037 §2's argument, which ADR-0148 §6 already applied to the
opposite pair.** Deleting the credential first would leave a window in which a
live, *active* record names a slot holding nothing — a state a caller reads as
connected and discovers empty at the credential read. Removing the record first
leaves the mirror window: an unreferenced slot, which no call reads and which
ADR-0148 §6 already names as the tolerable side of exactly this trade. Err in the
direction the reader can detect.

**The revision clause closes a gap ADR-0148 §6 leaves open by construction, and
it is a gap with teeth.** §6 states monotonicity over "that reference" and
requires the taking act's compare-and-swap to observe "the identity, revision and
state" — which says nothing about a reference whose record has been removed. A
store that dropped the counter with the record would restart a re-connected
reference at the first revision, and the ABA sequence §6's revision exists to
refuse becomes reachable through a *conforming* path: connect A at revision 1,
disconnect, connect A again at revision 1, and a credential read spanning the
three sees the same identity and the same revision it started with. That is the
defect §6 spent round 4 closing, arriving through the one act §6 did not
enumerate. Retaining the counter costs a durable integer per reference and no
history.

**Keeping the counter is not keeping a history, and the difference is a data
right.** What survives a disconnection is a reference and a number, neither of
which is personal data (§3). A full history of connected accounts would keep
identities after the user disconnected them, which is durable Tier 1 data with an
ADR-0004 §6 obligation and no consumer asking for it — ADR-0148 §6's checks read
only the live record. §11 scopes the history out rather than buying it here.

### 6. An active record over an empty slot is refused, and nothing repairs it automatically

> **Normative.** Where a callable reads the record for a connectable reference and
> `Secrets.get` for the slot that record names returns `None` (ADR-0125 §4, §6 —
> absence is a return value and not an error), the call is **refused and nothing
> is transmitted**. No component treats an absent credential as a reason to
> activate a record, to roll one back, to fall back to another slot, to read an
> environment variable or a file, or to re-provision; the remedy is for the user
> to run the provisioning act again, which increments the revision and re-enters
> at *pending* (ADR-0148 §6).

> **Normative.** A keyring that is unreachable, locked or has no backend is not an
> absent credential (ADR-0125 §7): the error propagates, the call is refused, and
> no lane converts it into the case above.

**This state is reachable without anyone doing anything wrong, which is why it is
ruled rather than left to an implementation.** ADR-0123 backs up the cold data
directory and the keyring is not in it, and ADR-0125 §12 draws the consequence:
"a restored installation holds no Tier 0 entry and the owner re-provisions." Once
a connection record lives *in* the data directory, a restore produces an
**active** record naming a slot the keyring does not hold — every check ADR-0148
§6 specifies passes, because each compares the record against the binding or
against itself, and none of them inspects whether the slot holds anything. The
refusal has to be stated at the read, and it is the same refusal ADR-0148 §6
gives the interrupted act: the state is refused rather than reconciled.

**It is a stacked addition to ADR-0148 §6 and not a change to it.** §6 rules what
happens when the record disagrees with the binding or with itself; it is silent
on an empty slot, and nothing in it becomes false or over-wide by this clause
(§10). §6's guarantee clause is likewise unaffected — it guarantees no byte is
transmitted under a credential read across a provisioning act, and refusing when
there is no credential at all is that guarantee's direction, not an exception to
it.

### 7. The user reaches it as a hub operation, and the operation's shape is its own contract ADR

> **Normative.** Connecting, re-provisioning, disconnecting and listing
> connections are **hub operations reached by a client** (ADR-0084, ADR-0097 §9's
> shape). They are implemented in `orchestration`, which delegates each act to the
> provisioner (§1) through a Protocol in `core/protocols.py` (§8).
> `orchestration` holds no keyring face, opens no connection store and performs
> none of ADR-0148 §6's three writes.

> **Normative.** The `AssistantEngine` method signatures for these operations,
> the result types they promote to `core/types.py`, their wire frames and the
> shape of the Protocol §8 names are **not decided here**. They are owed as their
> own contract ADR, on ADR-0084 §5's step-1/step-2 split, ratified and merged
> before any client or any implementation is built against them. **Its firing
> condition is this ADR merging.**

> **Normative.** Whatever shape that ADR chooses, these properties hold and it may
> not choose otherwise: no response carries a credential value or any value
> derived from one; the credential travels only in the request that performs the
> act and comes to rest only in the keyring, reaching no log, no audit record, no
> conversation, no plan, no trace and no error message; no operation is bound by a
> `ToolDefinition` or reachable by a plan step; a refusal names the reference and
> not the identity (§3); and the act's three writes stay the provisioner's,
> performed in ADR-0148 §6's order, with `orchestration` neither reordering,
> splitting nor retrying them.

> **Normative.** A CLI command for any of these is a client of the operation
> (ADR-0084 §5). `interfaces/` stays a thin adapter, holds no keyring face, and
> builds no engine (golden rule 3).

**The split is ADR-0097 §9's, taken because the same two reasons apply
unchanged.** That clause deferred "the `AssistantEngine` method signatures for
these operations, the promoted result types, and their wire frames" to their own
contract ADR and ADR-0102 discharged it. `AssistantEngine` is a ratified closed
graph with a byte-level wire encoding attached (ADR-0085, ADR-0087); deciding
methods on it inside an ADR about who holds a keyring face would be exactly the
pre-emption ADR-0084 §5 separated. And the surface wants a **producer** —
ADR-0073 §4's standing test, which ADR-0148 §11, ADR-0146 §8 and ADR-0125 §9 each
applied to their own deferred surface. There is no integration in the tree to
connect (§ *The tree, read rather than remembered*), so what a connect operation
must carry beyond a reference, an identity and a credential — an endpoint, a
scope list, an account chooser — is a guess today and an observation once one
exists.

**What keeps this from being a deferral wearing a decision's clothes.** ADR-0148
§11 names the test and this ADR meets it in the same way: every property the
deferred surface must have is fixed above, and the two questions ADR-0148 §11's
fourth clause actually asked — who holds the face, and where the record lives —
are answered here in terms an implementation can act on without asking a
follow-up. What is left open is the signature, and a contract ADR that satisfies
the clauses above is free to choose it; one that does not is changing this
decision.

**Listing is on the list for ADR-0102 §1's reason.** A user who can connect must
be able to see what is connected — otherwise the only record of which account is
live is one the user cannot read, which defeats §4's informed-act property the
same way ADR-0102 §3 argues a client must not derive the grantable set from the
granted one. Whether it is one operation or several is the surface ADR's.

### 8. New `core` contract surface, flagged and not landed here

> **Normative.** This decision cannot be implemented without one piece of contract
> surface `core` does not have: a Protocol by which `orchestration` reaches the
> provisioner in `tools/` (§7). It is flagged here under golden rule 5 and **is
> not added by this ADR**. It is decided in the contract ADR §7 names — the same
> one that decides the operations it serves, because they are one question — and
> its triad rides with the **primary production implementation** as one lane
> (ADR-0137 §2, `CONTRIBUTING.md` → "Adding a Protocol").

> **Normative.** No credential value appears in that Protocol's return types
> (§7). It carries no `SecretName` a caller could use to reach the keyring by
> another route, and holding it confers no keyring face.

> **Normative.** This ADR adds **no** member to `SecretScope`, changes **no**
> signature on `Secrets` or `SecretStore`, adds no field to `ActionRequest`,
> `PermissionDecision`, `ToolDefinition`, `ToolCall` or `ToolResult`, and adds no
> Protocol for the connection record itself (§3). A lane that finds it needs any
> of those is changing a ratified decision and owes its own ADR.

**One Protocol is the floor and it is derived rather than chosen.** The operations
are `AssistantEngine` methods, `AssistantEngine` is `orchestration`'s (ADR-0102
§7), the act's owner is in `tools/`, and a subsystem boundary between them is a
Protocol by golden rule 1. Every other seam this decision needs falls inside one
subsystem: the record's store, the callable's read of it, and ADR-0148 §11(b)'s
consultation of it are all `tools/`-internal, which is the placement's whole
economy (§1).

### 9. What this ADR does not gate, discharge or authorise

> **Normative.** Nothing here discharges any of ADR-0017 §3's fourteen
> conditions, attests that one holds in code, or designates the `tools/` egress
> seam. `tools/` still transmits nothing, and no lane may cite this ADR toward a
> condition, a designation, or a connection to any counterparty.

> **Normative.** Nothing here gates a credential read, narrows ADR-0004 §7, or
> closes #74. ADR-0125 §9's clause stands exactly as written: this is a storage
> and provenance decision, not an authorisation seam, and the provisioner
> consults no policy and writes no audit record.

> **Normative.** Nothing here authorises connecting to an MCP server over any
> transport. ADR-0147 §4's fourth and fifth clauses stand undischarged and
> unrelaxed (§11).

**The reason for saying it is ADR-0147 §3's and ADR-0148 §13's:** a document that
supplies the machinery for holding an integration's credential reads like
permission to use one. It is not. What becomes possible when this ADR merges is
that a lane may *write* a credential and a record — and a lane may still not
transmit a byte, because the conditions that gate transmission are ADR-0017 §3's
and none of them moves here.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds? Where the
answer is no, "no record is owed against it at all, on `Status` or in a note", and
the change is recorded in the ADR that makes it and nowhere else. ADR-0146 §10,
ADR-0147 §11 and ADR-0148 §12 are the worked precedents for this section's form.
Each ADR below was read for **what it is relied on for**, which is ADR-0084 §12's
semantic method rather than a phrase search.

**ADR-0125 §12 — a record is owed, as a dated note, and it is the only edit this
change makes to another ADR.** §12's bullet reads: "**A provisioning surface.**
Nothing here mints a command that sets a provider key or an integration
credential. `SecretStore` is the seam such a command would use, and today no code
holds it for a `PROVIDER` scope." Its first two sentences stay true and its third
is a dated observation about the tree. What fails ADR-0070 §1's test is the
*bullet's function*: a scope-out bullet tells a reader that a question is
unowned, and a lane holding only ADR-0125 would read this one as an invitation to
decide the integration half — which is now decided, by this ADR, with an owner
and a placement that lane may not choose again. Acting differently is exactly
what such a reader does. The note therefore records the discharge and its
boundary, and records that the **provider** half is not discharged. This is the
form ADR-0016's header carries for its own discharged §7 deferrals (ADR-0029,
ADR-0144, ADR-0145).

The note, appended after ADR-0125's existing header bullets in the ratification
commit:

```text
- Note (2026-08-13): §12's **provisioning surface** bullet is discharged **in
  part** by ADR-0149, for the `INTEGRATION` scope only. ADR-0149 §1 gives one
  component in `tools/` — the connection provisioner, which is not a tool and is
  not reachable by `ToolInvoker` — the only `INTEGRATION`-scoped `SecretStore` in
  the system, to perform ADR-0148 §6's credential write and its predecessor
  deletion; it calls `set` and `delete` and never `get`, so §8's rule that a tool
  holds `Secrets` and nothing wider, and ADR-0148 §7's positional rule for reads,
  are both untouched. ADR-0149 §3 puts the connection record under
  `Settings.data_dir`, opened by `build_engine`, with its store seam
  `tools/`-internal, so no Protocol is added to `core/protocols.py` for it. **§8
  is unchanged**: its fourth clause enumerates ten subsystems, `tools/` is not
  among them, and its second clause — about the tool that needs a read face —
  stays true as written (ADR-0149 §2). §1's two faces, §2's scope and
  installation binding, §4's replace-in-place `set` and its concurrency
  disclaimers, §5's refusal of enumeration, §6's absence rule and §7's platform
  posture are consumed exactly as ratified; §9 is untouched and #74 stays open.
  The bullet's **provider key** half is **not** discharged: it stays with §12's
  first bullet, #74 and a `models/` lane (ADR-0149 §11). §12's other bullets —
  rotation and expiry *policy*, the `keyring` dependency, backup, and #462 — are
  unaffected and remain scoped out, though ADR-0149 §5 and §6 decide two
  consequences that meet the backup bullet and the rotation bullet at their
  edges: a disconnection never resets a reference's revision, and an active
  record over an empty slot is refused rather than repaired.
```

**ADR-0125 §8 — no record owed, and this is the one that needs the argument.**
§2 above is the working. §8's four marked clauses each stay true after this ADR:
`models/` still holds `Secrets` and not `SecretStore`; `tools/` still holds
`Secrets` at the tool that needs one, and `ToolRegistry` and `ToolInvoker` still
hold neither face; the wire client's enrolment paths are untouched; and the ten
enumerated subsystems still hold neither and still may not acquire one. A reader
holding only ADR-0125 §8 wires precisely what they wired before and reads no
clause of it more widely — what they do not find in it is an answer about a
component §8 never addressed, which is the deferral §12 recorded rather than a
sentence §8 wrote. Under ADR-0082 §1 that is a **stacked addition**: an
obligation that contradicts no sentence the earlier ADR wrote, recorded in the
ADR that makes it and nowhere else. The reasoning is exposed here rather than
asserted because a reviewer is entitled to check it, and ADR-0082 §1 gives them
the way to overturn it — by naming the sentence of §8 that becomes false or
over-wide.

**ADR-0148 §6, §11 and §13 — no record owed.** §11's fourth clause requires "the
ADR that names its owner", §13's ninth bullet says the owner "wants the producer
§11 defers for", and this ADR names the owner. A condition "is not made false or
over-wide by being answered" (ADR-0147 §11's formulation, adopted by ADR-0146
§10): a lane holding only ADR-0148 still finds §6's semantics, still finds no
component authorised by §6 itself, and still needs the later ADR §11 requires.
§6's clauses are consumed and not restated; §5 and §6 above add beside them —
disconnection, the revision across it, and the empty slot — and each is a case §6
does not rule on, so no sentence of §6 becomes false. §7's positional read rule is
strengthened in fact and unchanged in text (§1). §11's own deferral of surfaces
(a) and (b) is untouched, and this ADR decides neither.

**ADR-0097 §§1, 3, 8 and 9, and ADR-0102 §§1, 7, 8 and 9 — no record owed.** They
are read as **precedent** and, in §4, as a model this ADR partly declines. A
connection is not a `SourceGrant`, the grant store gains nothing and loses
nothing, `GrantScope` gains no member, no clause about a source's identity is
read wider, and the four grant operations are untouched. ADR-0102 §7's "no other
object in the system holds a `SourceGrantStore`" stays true — the provisioner
holds none.

**ADR-0083 §2, ADR-0084 §§5 and 9, ADR-0004 §§1, 5, 6 and 7, ADR-0016 §§5, 6 and
7, ADR-0029 §§1, 2 and 6, ADR-0021 §1, ADR-0125 §§1–7 and 9, ADR-0147 §§3 and 4,
ADR-0123 — no record owed.** Each is used as given. A new store under `data_dir`
is `Settings.data_dir` working as ADR-0083 §2 designed it; a new hub operation is
ADR-0084 §5's split working as designed; ADR-0016's registry rules are relied on
and not narrowed; ADR-0029 §6's "no credential value crosses this seam" is
inherited; ADR-0123's backup scope is stated rather than changed, and §6 above
adds the refusal that scope implies rather than asking that lane for anything.

**What would have owed a record and is deliberately not done.** Giving
`orchestration`, `service` or `interfaces` a keyring face (that is ADR-0125 §8's
fourth clause and would be a partial supersession — §1 explains why it is refused
on its own merits, not to avoid the record); adding a `SecretScope` member;
changing what a connection record carries; or reading ADR-0148 §6's states as
admitting a third.

### 11. Explicitly out of scope

Scoping something out is a decision, so each carries its reason (ADR-0029 §7's
form).

- **The provider key's provisioning surface** — ADR-0125 §12's first bullet and
  **#74**. A provider credential has no connection record, no account identity,
  no per-call binding and no callable position: none of ADR-0148 §6's machinery
  has a subject there, and what it actually needs is pydantic-ai's provider
  construction to accept an injected key, which ADR-0062 §2 records as the
  boundary that shaped `_check_provider_importable`. ADR-0125 §8's first clause
  already rules the direction — provisioning a provider credential is not
  `models/`'s — and scheduling it stays with #74 and a `models/` lane.
- **The ADR ADR-0147 §4 requires before an MCP server is connected to over a
  stdio transport.** This is not it, and the reason is that the two questions do
  not overlap: ADR-0147 §4's fifth clause owes "what bounds the recipient, what an
  operator's claim about it is worth, and what is recorded" about a program this
  repository did not write, whose open input is containment (**#1112**). This ADR
  decides which of *our* components holds a face onto *our* keyring and where
  *our* store lives, and nothing about containing a foreign process bears on
  either. The owner question is answerable without it for the same reason it was
  answerable without a producer: ADR-0148 §6 already fixed what the act does, so
  what remained was placement. That ADR-0149 makes it possible to *hold* a
  credential for a server does not make it possible to *reach* one — ADR-0147 §4's
  fourth clause forbids connecting over any transport until it is authorised, and
  §9 above adds nothing to §3's list and relaxes none of it.
- **Standing grants** (ADR-0021 §6). A connection authorises nothing (§4), so it
  is not the relief valve §6 defers and does not pre-shape it. ADR-0148 §3's
  fourth clause adds two questions that ADR must answer before an egress recipient
  may rest on a standing authorisation, and both stay where ADR-0148 §13 left
  them.
- **ADR-0148 §11's surfaces (a) and (b)** — the egress binding and the seam that
  supplies it. Each is its own contract ADR by §11's second clause, decided with a
  producer in hand. This ADR consumes the fact that (b) lives in `tools/` for its
  placement argument (§1) and decides nothing about either shape.
- **An interactive authorisation flow — OAuth or any redirect-based exchange.**
  It is an egress call to the provider, so it needs a designated seam, a
  destination canonicalisation and a ruling (ADR-0148 §§1, 2, 5) that do not exist
  yet, plus a loopback listener whose reach ADR-0084 §1 did not decide. §4's
  identity and credential arrive from the user; a flow that obtains them from a
  service is a later decision with strictly more machinery behind it.
- **Rotation, expiry and re-provisioning *policy*** — ADR-0125 §12's third
  bullet, unchanged. This ADR says what a re-provisioning *is* (an act with
  ADR-0148 §6's shape, performed by §1's owner, on a user's initiative) and says
  nothing about when one is due, whether an expiry is tracked, or whether anything
  reminds the user. Nothing automatic may perform one (§4).
- **A history of connections.** §5 keeps a revision counter and no more. Retaining
  disconnected accounts' identities is durable Tier 1 data with an ADR-0004 §6
  obligation and, today, no consumer: ADR-0148 §6's checks read only the live
  record and no surface asks what was connected last year. A lane that finds a
  consumer decides it then, and §5's counter is what keeps that decision additive.
- **Whether a backup carries a connection record** — ADR-0123's scope, stated
  rather than changed. §6 rules what happens when a restored record outlives its
  credential; whether the record is in the backup at all is that lane's.
- **Provisioning from an enrolled device over the remote transport.** ADR-0124 §1
  enumerates the boundaries and a credential crossing to the hub from a remote
  spoke raises questions about that hop this ADR has no producer for. §7's surface
  ADR decides which clients may reach the operations; what this ADR fixes is that
  the credential comes to rest only in the hub's keyring wherever it was typed.
- **Per-tool confinement inside `INTEGRATION`** — ADR-0125 §2's named residual,
  accepted there and not widened here (§2). The fix, if a plugin model ever makes
  it necessary, stays the additive one §2 describes.
- **Transport pinning** (**#83**) and the **payload manifest** (**#57**).
  ADR-0148 §13 owns both; a connection record carries no endpoint and no
  description.

### 12. What the implementing lanes owe

> **Normative.** The lane that lands the provisioner ships, beyond ADR-0148 §14's
> matrix: a test that a disconnection followed by a re-connection on the same
> reference takes a revision strictly greater than every revision that reference
> ever held (§5); a test that a call bound to a reference whose record is active
> and whose slot is empty is refused and transmits nothing (§6); a test that the
> provisioner never calls `get`; and a test that a disconnection whose slot
> deletion fails leaves the reference disconnected and reports the failure (§5).

> **Normative.** That lane also ships the import-linter or equivalent mechanical
> confinement that the provisioner's module is the only module under `tools/`
> naming `SecretStore`, in the spirit of ADR-0125 §8's contract confining the
> keyring library to one package — a convention held by review is the state
> ADR-0125 §8 records as having survived from ADR-0004's ratification until a
> third consumer made it blocking.

> **Normative.** No lane implements any of it before the contract ADR §7 names has
> merged (golden rule 5, ADR-0015 §5). This ADR merging discharges ADR-0148 §11's
> fourth clause and no other precondition.

### 13. Marking, review and ratification

- **Marked under ADR-0089 §2, and the marks are the whole of what this ADR
  obligates** (§3 there). Unmarked text — the placement arguments in §1 and §2,
  the classification in §10 and the scope-outs in §11 — is read to determine what
  a marked clause means and supplies no obligation of its own, except where §11's
  bullets restate a marked clause elsewhere by citation.
- **Citations are in ADR-0088 §1's forms**, and no code citation carries a line
  number (§5 there): the modules and symbols named above are named by symbol.
- **Drafted, reviewed and revised while `Proposed`**, with the required set —
  adversarial *and* architecture — run against it in that state, its status
  flipped only once both returned clean on one tree, and both re-run on the
  flipped tree for the coverage reason `CONTRIBUTING.md` → "Finishing an ADR PR"
  gives. Findings raised after the flip were folded the same way. Nothing
  implements against this ADR until it has merged (ADR-0015 §5).

## Consequences

- **ADR-0148 §6 becomes performable.** Its clauses had no party entitled to
  satisfy them; §1 names one, and ADR-0148 §14's test list acquires a subject.
- **One subsystem holds the whole connection concept.** The record, its store, its
  readers and its writer are all in `tools/`, so the only contract surface this
  decision adds is the one the user's act crosses — one Protocol instead of the
  two a different placement would have cost, and no supersession of ADR-0125 §8.
- **`tools/` acquires durable state and a write face onto the keyring**, which it
  did not have. That is the real cost: a subsystem that will host integration code
  now contains the one component that can write an `INTEGRATION` credential. §1's
  confinement clauses and §12's mechanical check are what keep the blast radius at
  one module, and ADR-0125 §2's plugin caveat is the condition under which this
  placement wants revisiting.
- **A connection becomes a user act with the same shape as a grant and none of its
  record semantics.** An installation cannot acquire a live connection by being
  configured, upgraded or restored, which closes the route by which ADR-0148 §6's
  identity binding would attest something nobody asserted.
- **Two states ADR-0148 §6 left reachable are now refused rather than
  reconciled** — a re-connected reference reusing a revision, and an active record
  over an empty slot. Both are cheap to hold and neither was detectable by the
  checks §6 already specifies.
- **The chain to leg 12's exit gains one ADR and no more.** The surface ADR §7
  names decides the operations and the Protocol together; ADR-0148 §11's (a) and
  (b), the designating ADR and ADR-0147 §4's authorising ADR are unchanged in
  number and in scope.
- **Nothing transmits.** `tools/egress` stays empty and every one of ADR-0017 §3's
  conditions stays undischarged.

## Alternatives considered

- **The provisioning operations in `orchestration`, holding the `SecretStore` and
  the connection store, on ADR-0102 §7's precedent.** The closest thing to a
  ratified template, and refused in §1: it costs two `core` Protocols and two
  triads for the record, because the record's other readers are in `tools/`, and
  it contradicts ADR-0125 §8's fourth clause, which is a partial supersession
  rather than a stacked addition. It would also put the compare-and-swap that
  ADR-0148 §6 makes load-bearing on the far side of a boundary from the party that
  must re-read it between writes.
- **A leaf package outside every subsystem**, on ADR-0125 §8's shape for the
  keyring implementation. Refused in §1: that shape earns its place when no
  subsystem is a consumer, and here two consumers are inside `tools/` on day one.
- **The tool provisions itself**, with `SecretStore` handed to the tool that needs
  the credential. Refused in §1 on ADR-0097 §3's argument: the split between a
  reading and a writing face is what makes "only a user act writes this
  credential" a type rather than a promise, and collapsing it hands every tool the
  ability to author the credential its own identity binding rests on.
- **A connection as a `SourceGrant` with a third `GrantScope` member.** Refused in
  §4 on three independent grounds — the subject is personal data where a grant's
  is a declared constant, the store's mutation semantics are append-only where
  ADR-0148 §6 requires a live record taken by compare-and-swap, and `VISION.md`
  governs reading and acting separately. Attractive because it would have reused a
  ratified store and surface; unavailable because ADR-0148 §6's checks read a
  record that a grant store cannot be.
- **A `core` Protocol pair for the connection record**, mirroring
  `SourceGrants`/`SourceGrantStore`, so the record is a first-class contract.
  Refused in §3: with writer and readers in one subsystem it is a boundary with
  nothing on the other side, and ADR-0029 §1 already rules the callable's reach
  `tools/`-internal. If a future consumer outside `tools/` appears — a
  connections screen served from another subsystem, say — promoting the seam is
  additive and is that lane's decision.
- **Deciding the engine operations here**, so that one ADR unblocks the
  implementation entirely. Refused in §7 on ADR-0084 §5's split and ADR-0073 §4's
  producer test: `AssistantEngine` is a closed graph with a wire encoding, and the
  arguments a connect operation needs are exactly what a first real integration
  would tell us.
- **Letting a disconnection erase the reference's counter**, which is the simpler
  store. Refused in §5: it reopens the ABA sequence ADR-0148 §6's revision exists
  to refuse, through a conforming path.
