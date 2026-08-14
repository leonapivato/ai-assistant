# 149. One component in `tools/` provisions a connection, and the record it writes is the hub's

- Status: Proposed
- Date: 2026-08-13
- **Decides** the two questions ADR-0148 §11's fourth clause and ADR-0148 §13's
  ninth bullet name as undecided — who performs a provisioning act, and where a
  connection record lives — and with them the half of ADR-0125 §12's "a
  provisioning surface" bullet that reaches **an integration credential**. The
  provider key's half stays where ADR-0125 §12's first bullet and #74 put it
  (§13).
- **It answers the contract half of ADR-0126 §6's forward clause**, which
  requires the lane that first gives a component on the hub's machine a Tier 0
  keyring entry to decide, in the same change, how a hub-side delete reaches it
  (#909). §8 supplies the path, its ordering and its completeness. It does **not**
  discharge that clause: who invokes the purge — and whether ADR-0126's own act
  changes to do it — is left to #909, and §6's prohibition on writing such an
  entry stays operative until that lands. §8's precondition carries it forward
  rather than replacing it.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-13**,
  the durability form ADR-0100 established. This decision rests most heavily on
  ADR-0148, ratified the same day, and on ADR-0125 and ADR-0126, whose §8 and §6
  respectively carry the clauses a new holder of a keyring face has to get past; a
  citation that silently means "whatever that ADR says when you read it" is not
  checkable. Where a later ADR changes one of them, this one is read against the
  text named here until an ADR says otherwise.
- **Records for ratification: one dated note appended to ADR-0125's header**,
  applied in the same commit that flips this ADR's `Status` to `Accepted` and not
  before — ADR-0017 §7 requires the operation performed on another ADR to be
  recorded rather than inferred, and writing "discharged by ADR-0149" onto
  ADR-0125 while this ADR is `Proposed` would be the state claim ADR-0019
  forbids. §12 applies ADR-0082 §1's test to every ADR this one touches and shows
  its working. **No `Status` line moves and no ratified text is rewritten.**
- **No implementation lands with it.** No `src/`, no `tests/`, no
  `pyproject.toml`. Nothing implements a provisioning act on the strength of this
  ADR alone: the act is reached through contract surface that does not exist, and
  §10 says what is owed and who owes it.
- **It decides no `core` surface and names one that is owed.** §9 defers the
  shape of that surface, with its firing condition, to the contract ADR that
  decides the operations it serves — the split ADR-0097 §9 made and ADR-0102
  discharged, taken deliberately rather than by resemblance.
- **Its required review set is adversarial *and* architecture.** It decides who
  may hold a write face onto the keyring, where a new durable Tier 1 store lives,
  how a delete right reaches a Tier 0 entry, and the shape a still-undecided
  contract surface has to be able to land into — each answerable from prose
  before an implementation commits to an answer (`CONTRIBUTING.md` → "Contract
  ADRs land before their implementation"). §15 records the set that ran and the
  order it ran in.

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
grants no keyring face, and locates no record. ADR-0148 §11's fourth clause says
so normatively and forbids the obvious shortcut:

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
handed. §5 refuses enumeration outright — no method lists the entries in an
installation — which is why a purge path has to be composed from names something
recorded (§8). §8 then says who holds which face, and its fourth clause is the
one a new holder meets:

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

### The delete right already has an act, and it already named this lane

ADR-0126 §1 makes deleting the owner's data at the hub the destruction of the
resolved `data_dir`, and §2 makes it an offline console entry point in
`service/`. §6 then rules that the act "reaches no keyring", because ADR-0125 §8
keeps `service` out of the seam and §5 refuses enumeration — and it states the
premise that made that acceptable: "No component of this system writes a Tier 0
keyring entry on the hub's machine today, so the act misses no keyring entry."

**This ADR is what makes that premise expire**, and ADR-0126 §6 anticipated it in
a marked clause aimed at exactly this lane:

> The lane that first gives a component on the hub's machine a Tier 0 keyring
> entry owes, in the same change, a decision about how a hub-side delete reaches
> it. That decision is a contract question and not a wiring detail — ADR-0125 §5
> refuses enumeration and puts the deletion path on the consumer that wrote the
> entry, and ADR-0125 §8 keeps `service` out of the seam, so no path exists today
> that this act could take. Until that decision lands, this ADR authorises no such
> entry to be written, and no lane may cite this section as a route to one.

§8 below is that decision. **#909** carries the question and names the three
things ADR-0126 §6 said such a decision would have to weigh.

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
  exist yet rather than relocating one that does, and ADR-0126 §6's premise is
  still true of the tree as this ADR is written.
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
- **ADR-0126's act.** Its unit, its offline placement, its refusals, its ordering
  and its report are that ADR's. §8 supplies the path §6 asked a later lane for;
  it does not route ADR-0126's act to it, because doing so would change §6's
  first clause and that is ADR-0126's to change.
- **ADR-0147 §4's stdio question** (§13).

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
§9 keeps — leaves the record's own seam `tools/`-internal (§3), and leaves every
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

**§12 applies ADR-0082 §1's test to §8 and finds no record owed.** Every sentence
of §8 stays true, and a reader holding only ADR-0125 wires exactly what they
wired before.

### 3. The connection store is the hub's, under `Settings.data_dir`, and it is append-only

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

> **Normative.** The store is **append-only**. Every act on a reference appends an
> entry; no entry is ever updated in place and none is deleted except by the
> wholesale purges §8 governs. The **live connection record** for a reference —
> the one ADR-0148 §6's clauses are about, and the only one any check reads — is
> that reference's latest entry, and a reference whose latest entry is a removal
> (§5) has no live record at all. ADR-0148 §6's compare-and-swap is performed
> against that latest entry: an act appends only if the entry it observed is still
> the latest, and appends nothing otherwise.

> **Normative.** The store is therefore the **record of the act**: what the user
> connected, re-provisioned and disconnected, for which reference, in order. It
> carries the identity, the revision, the provisioning state and the slot ADR-0148
> §6 requires, and no credential value or value derived from one, in any field,
> including the identity (ADR-0148 §6's exclusion clause, applied to the record
> the same clause creates).

> **Normative.** A connection record is a **Tier 1** store (ADR-0004 §1): the
> account identity ADR-0148 §6 requires is a user-recognisable name and may be
> personal data. It is therefore subject to ADR-0004 §6's rights (§8), and to
> ADR-0004 §5's logging rule: no log line, error message or operator diagnostic
> emitted by the provisioner or by a callable carries an account identity. The
> **connection reference** and the **credential slot** are non-secret handles
> chosen by code (ADR-0125 §2) and may be logged.

**Append-only is ADR-0097 §4's shape and it is taken for that section's reason.**
A grant store is append-only because "the record says what the user actually
decided and when", and a store that edits its own history cannot say it. The same
is true here one axis over, and it buys three things at once: it is what §7 offers
as ADR-0004 §7's *recorded* half; it makes §5's revision monotonicity a property
of the store rather than an extra obligation on an implementation; and it keeps
the superseded slots visible to the purge §8 composes, which is what stops a
failed predecessor deletion from becoming an entry nothing can name.

**It costs nothing ADR-0148 §6 relies on, and that is worth checking rather than
asserting.** §6 speaks of *the* connection record, its state, its revision and a
compare-and-swap "on that record"; every one of those is a statement about the
live record, which the third clause above identifies exactly. An act that appends
a new entry only if the entry it observed is still the latest is a
compare-and-swap in §6's own terms — from "the identity, revision and state it
observed" to the new pending entry — and an act whose append is refused "never
held it and writes nothing". Nothing in §6 requires the previous state to be
overwritten, and nothing in it is satisfied less well by a store that keeps it.

**The record is what makes ADR-0004 §6's Tier 0 purge composable, and that is a
consequence rather than a convenience.** ADR-0125 §5 refuses enumeration — no
method lists the entries in an installation — and ADR-0125 §10 draws the
conclusion for a neighbouring lane: "its purge path is composed from names it
recorded rather than discovered". The connection store is that recorded list for
the `INTEGRATION` scope, and §8 is where it is used.

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
> user in the same act that supplies the credential, and is recorded verbatim —
> nothing strips, case-folds or otherwise normalises it, at the surface, in the
> provisioner or in the store. No component infers it from a credential, a slot, a
> reference, an endpoint, a `Settings` value or a remote lookup — the first four
> are ADR-0148 §6's own prohibition and the last is an egress call this system is
> not entitled to make (ADR-0148 §5).

> **Normative.** The act **refuses**, writing nothing, when the supplied identity
> is equal to the supplied credential's plaintext. The comparison is exact, is
> made before the first write, and its diagnostic names neither value.

> **Normative.** An identity is **bounded, single-line printable text**: no
> control character, no line break, and a length bound the implementing lane sets
> and the store enforces. A violation refuses the act and writes nothing. The
> identity is not a `SecretValue`, is not stored through `SecretStore`, and is
> never the source of a `SecretName`'s `key` (ADR-0125 §2's prohibition, which
> binds this direction too).

> **Normative.** The surface renders the identity back to the user as part of the
> act and in every listing (§9), so a value the user typed into the field is a
> value the user sees. No surface accepts an identity it does not display.

> **Normative.** A connection record is **not** a `SourceGrant` (ADR-0097 §1),
> is not written to the grant store, and is not read by `SourceGrants.live`. No
> `GrantScope` member covers connecting an account, and no lane adds one for it.

> **Normative.** A connection **authorises nothing**. It makes a reference
> connectable (ADR-0148 §6) and supplies the credential a callable reads; every
> call under it is still authorised as a whole by ADR-0148 §1 and ruled by
> `ActionPolicy` under ADR-0021. No surface may present connecting an account as
> permission to act with it, and no ruling may rest on the existence of a
> connection.

**The identity is the one value here a user types and the system keeps, so what
stops it being a secret is stated rather than assumed.** §3 forbids a credential
value or a derivative in any field of the record, including the identity, and
ADR-0148 §6 forbids it independently — but a user who pastes a bearer token into
a field labelled "account" satisfies every type and defeats both, putting a Tier
0 value into a Tier 1 store that survives into a backup. Three things answer it,
and none of them pretends to be a detector. The equality refusal catches the one
case that is both plausible and exactly checkable — the same string submitted
twice, which is what a paste into the wrong field produces. The shape bound and
the non-normalisation keep the value a legible name rather than an opaque blob.
And the display clause removes the ingredient the failure needs, which is that
the value be *unseen*: an identity is user-recognisable by ADR-0148 §6's own
definition and appears in every listing, so a token there is visible to the
person who typed it at the moment they type it, which is not true of a
credential.

**What none of that closes is stated in ADR-0148 §6's own posture.** A user
determined to put a secret in the identity field can, and no mechanism in this
system detects it in general — the same line ADR-0148 §6 draws about the party
who writes another account's credential into a slot directly: "That party is the
operator or the user, which is ADR-0021 §1's line exactly — 'a caller falsifying
its own audit trail, not a policy subverting a gate, and no producer can prevent
it'". What the system still owes such a value is the treatment §3 gives every
identity: it reaches no log, no error and no diagnostic (ADR-0004 §5), and it is
destroyed with the store by ADR-0004 §6's delete (§8).

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
from configuration — and, from ADR-0097 §4, the append-only store that records it
(§3). What does not transfer is the *subject* and the *shape of the live state*:

- **The subject differs.** A grant's subject is a reader's declared identity — a
  declared constant, which is what keeps personal data out of it (ADR-0097 §1,
  ADR-0093 §7). A connection's subject is an account, and its identity is
  precisely the user-recognisable value a declared constant may not be. That is
  why §3 rules the store Tier 1 and keeps the identity out of logs, where a grant
  needed no such rule.
- **The live state differs.** A grant is answered by "is there a live grant for
  this source", derived from the record history. ADR-0148 §6 needs more than that:
  a live record with a *mutable-looking* state that an act takes by
  compare-and-swap and moves from *pending* to *active*. §3 supplies both — the
  history and the latest-entry projection — where a `SourceGrantStore` supplies
  only the first and could not be made to supply the second without changing what
  ADR-0097 §4 decided.
- **The axis differs.** `VISION.md` governs reading and acting separately, and
  ADR-0097 §3 quotes it against exactly this merge: "Collapsing the two into one
  notion of 'integration' would either over-restrict reading or under-restrict
  acting." A grant is standing authorisation to *read* a source; a connection is
  the provenance of a credential on the *acting* side, where ADR-0148 makes every
  call individually authorised. Making a connection an authorisation would create
  the standing act-authorisation ADR-0021 §6 defers and §13 keeps deferred.

### 5. Disconnection is a user act, it is prospective, and it never resets a revision

> **Normative.** Disconnecting a reference is **two steps in a fixed order**: a
> **removal entry** is appended to the connection store **first**, after which the
> reference has no live record; the credential slots it deletes are deleted
> **second**. No other order is permitted.

> **Normative.** The slots a disconnection deletes are **every distinct slot named
> by an entry for that reference whose revision is strictly less than that
> disconnection's own removal entry's revision** — the removed record's, and every
> superseded, pending or earlier removed entry's. Deleting only the live record's
> slot does not satisfy this clause, and deleting a slot named by an entry at or
> above its own revision **violates** it: those belong to acts the disconnection
> did not displace.

> **Normative.** A disconnection is **idempotent and re-runnable**. Disconnecting
> a reference that has entries but no live record appends no second removal entry
> and repeats the deletion pass at the latest removal entry's revision, which is
> the remedy for a slot a displaced act wrote after that removal landed (below) or
> for one whose deletion failed. `delete` returns whether an entry was there and
> raises nothing for an absent one (ADR-0125 §4), so a repeat costs nothing and
> asserts nothing.

> **Normative.** Disconnecting a reference the store holds **no entry** for —
> never connected, or a mistyped reference — **writes nothing and deletes
> nothing**: no removal entry is appended, so a typo leaves no tombstone and
> creates no revision sequence, and no deletion pass runs, because there is no
> revision to bound it by. What the client is told is the surface ADR's (§9),
> under the one constraint that it may not report a disconnection that did not
> happen.

> **Normative.** A removal entry carries the reference, the incremented revision
> and the fact that the connection was removed. It carries **no** credential
> value, and it is **not** a connection record in a third provisioning state:
> ADR-0148 §6's states remain exactly *pending* and *active*, and a reference
> whose latest entry is a removal has no live connection record at all, so it is
> not connectable in §6's sense — no `ActionRequest` is built against it, no ruling
> is sought for one, and no callable transmits under it.

> **Normative.** A disconnection **does not reset the reference's revision**. A
> later provisioning act on the same reference takes a revision strictly greater
> than every revision that reference has ever held, so ADR-0148 §6's "A revision
> is never reused and never decreases" holds across disconnection and
> re-connection and not only within one connected life.

> **Normative.** A slot deletion that fails leaves an **unreferenced slot** rather
> than a live credential no record describes; the failure is reported and never
> suppressed, the reference stays disconnected, and the slot stays nameable from
> the entry that recorded it — the store is append-only (§3) — so a re-run and
> §8's purge both still reach it. This is ADR-0148 §6's rule for a predecessor
> slot, applied to the deletion that ends a connection.

> **Normative.** What a disconnection guarantees is that **no live record names
> any slot for that reference**, so no call reads one and none is connectable
> (ADR-0148 §6). It does **not** guarantee that the keyring holds nothing for that
> reference at the instant it returns: a provisioning act displaced by the removal
> may have a `Secrets.set` already in flight, which ADR-0148 §6 rules is "neither
> stopped nor waited for" and which lands in that act's own slot afterwards. No
> surface states the stronger guarantee.

> **Normative.** Such a slot is **named by the store** — the displaced act's
> pending entry recorded it before the write, and §3 keeps that entry — so it is
> reachable by a re-run of the disconnection and by §8's purge, and it is
> reachable by nothing else. No lane holds a lock across a keyring write to
> prevent this, and no lane leaves the slot unnamed.

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
store that dropped the history with the record would restart a re-connected
reference at the first revision, and the ABA sequence §6's revision exists to
refuse becomes reachable through a *conforming* path: connect A at revision 1,
disconnect, connect A again at revision 1, and a credential read spanning the
three sees the same identity and the same revision it started with. That is the
defect §6 spent round 4 closing, arriving through the one act §6 did not
enumerate. §3's append-only store closes it by construction rather than by a
counter an implementation has to remember to keep.

**Disconnecting is a third party to ADR-0148 §6's interleavings, and an earlier
draft deleted one slot where three could exist.** Adversarial review found the
sequence: a re-provisioning appends its pending entry naming a fresh slot,
passes its pre-write re-read, and pauses; a disconnection appends the removal and
deletes "the slot the removed record named" — the pending one, still empty, so
the deletion succeeds trivially; the displaced act's `set` then lands. The user
is told the connection is gone while the keyring holds a credential — and the
*previous* act's slot, which the displaced act would have deleted after its own
activation, was never deleted either, because the draft's disconnection looked at
one entry. Both halves are repaired by the same move: a disconnection deletes
every distinct slot the store names for the reference, and the store names all of
them because it is append-only. **The write that lands afterwards cannot be
prevented from here** — ADR-0148 §6 rules a displaced act's in-flight write
neither stopped nor waited for, and the lock that would serialise it is the one
ADR-0097 §5a examined and refused — so what is bought instead is that the slot is
*named*, which makes the remedy an idempotent re-run and makes §8's purge
complete. Claiming the stronger guarantee is the overclaim ADR-0102 §9 forbids a
client from making, which is why the clause above states the weaker, true form.

**The repair for that had a mirror of its own, and the revision cutoff is what
closes it.** A draft that deleted "every slot the store names for the reference"
read the store at deletion time, so a disconnection whose deletion pass was slow
would delete the slot of a *later* act: the removal lands, the user reconnects,
the new act appends its pending entry and writes its credential, and the earlier
disconnection then deletes it — leaving an activation that succeeds over an empty
slot, which §6 refuses at every call while the user's most recent act reported
success. Adversarial review found it on the round that produced the every-slot
clause. The cutoff is the ownership rule §6 already uses one level up: an act owns
what it displaced and nothing later, and the revision is what says which is which.
It is exactly the reason ADR-0148 §6 gives the revision — "unchanged since I
looked", made answerable by a value that never repeats — applied to a deletion
pass rather than to a credential read.

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
(§12). §6's guarantee clause is likewise unaffected — it guarantees no byte is
transmitted under a credential read across a provisioning act, and refusing when
there is no credential at all is that guarantee's direction, not an exception to
it.

### 7. What ADR-0004 §7 asks of a provisioning act, and what answers it

ADR-0004 §7 is engaged here and is answered rather than assumed away, because a
provisioning act writes a Tier 0 credential and a Tier 1 record and its sentence
reaches both halves: "Access to Tier 0/1 data and every side-effecting tool call
is gated by the `permissions/` layer and recorded in an **audit trail**, making
the assistant's behaviour transparent and reviewable."

> **Normative.** No `ActionPolicy` ruling is sought for a provisioning act, and
> no provisioning act is presented as authorised by a `PermissionDecision`. A
> provisioning act is the owner acting at their own installation through a
> client, not the assistant proposing an action — the distinction ADR-0005 §3
> draws and ADR-0021 §1 records when it says the trail records "that a human
> answered". `permissions/` rules what the assistant proposes.

> **Normative.** The **record** half of ADR-0004 §7 is met by the append-only
> connection store (§3), which is what makes an act transparent and reviewable:
> it says, completely and in order, which reference the user connected,
> re-provisioned or disconnected, under which identity, at which revision, and
> which slot each act wrote. No `AuditTrail` record is written for a provisioning
> act, because an `AuditTrail` record is a permission decision's (ADR-0021 §1)
> and no decision is taken; writing one would be recording a ruling nobody made.

> **Normative.** The act is confined in the sense ADR-0126 §11's replacements
> use: one purpose and one path, performed by §1's component alone, on the
> owner's own installation, over ADR-0084 §1's `0600` socket, with the credential
> coming to rest only in the keyring (§9). Custody of the keyring is the operating
> system's own access control (ADR-0125 §7).

> **Normative.** This is **not an exemption from ADR-0004 §7 and no lane may cite
> it as one.** Nothing here narrows §7, exempts any existing access, or reaches
> any access other than a provisioning act. §7's gate over the *read* of an
> `INTEGRATION` credential is untouched and is additionally constrained by
> position under ADR-0148 §7, which this ADR inherits (§1).

**The corpus has already ratified this reading twice, which is why it is stated
as a reading rather than as a new exemption.** ADR-0097 §9 and ADR-0102's four
operations create, revoke and list a durable Tier 1 store on an explicit user
act, with no `ActionPolicy` ruling and no `AuditTrail` record — and ADR-0097 §11
examined ADR-0004 §7 explicitly and recorded no amendment against it, while
ADR-0102 §11 answers the auditing question by pointing at ADR-0097 §4's
append-only store rather than at the trail. A provisioning act is that act's
sibling: the same user, the same client, the same hub-side store, one tier
further down. If the corpus later decides that §7's gate does reach an act the
owner performs directly, it reaches the grant operations and this one together,
and ADR-0125 §9 has already shaped the seam so that such a gate arrives as a
decorator at the composition root with **no signature in `core/protocols.py`
changing**.

**What is genuinely different from the grant case is the tier, and it is why §3
and §8 exist in the form they do.** A grant record is Tier 1 and reviewable on
its own; a credential is Tier 0 and can be reviewed only through what the record
says about it. So the record carries the slot, the store keeps the history, and
§8 makes the delete right reach the entry — three properties a grant store never
needed and the ones that make "transparent and reviewable" true of an act whose
subject is a secret.

### 8. Deleting the owner's data reaches these entries — the path, its ordering, and what is left to #909

> **Normative.** The deletion path for an `INTEGRATION` keyring entry is the
> provisioner's, and it is the only one: it exposes a **purge** that deletes every
> credential slot the connection store names — the live records' slots and every
> superseded or removed record's slot — and then the entries that named them. No
> other component composes such a path, because ADR-0125 §5 refuses enumeration
> and the connection store is the only durable list of those slots (§3).

> **Normative.** The purge deletes slots **before** anything destroys the
> connection store. A destruction that removed the store first would leave keyring
> entries no component in this system can ever name again — Tier 0 data that is
> unreachable and present, which is the state ADR-0004 §6's "purges Tier 0 and
> Tier 1 together" exists to prevent, and which no later act could repair.

> **Normative.** Ordering alone does not discharge that: **the store's entries are
> removed only once every distinct slot it names has been confirmed deleted or
> confirmed absent.** A slot whose deletion raises (ADR-0125 §7 — a keyring that is
> unreachable, locked or backendless) leaves every entry in place, the failure
> reported and never suppressed, and no part of the purge proceeding past it. A
> partial purge is a failed purge, and it is never reported as a completed one.

> **Normative.** The purge is **idempotent**: it deduplicates the slot names the
> store yields, treats an absent entry as deleted (`delete` raises nothing for one
> — ADR-0125 §4), and re-running it after a failure deletes what remains. Nothing
> in it may be made to depend on a slot being present.

> **Normative.** No component discharging the owner's delete right destroys the
> connection store while any slot the store names is unconfirmed. A delete path
> that would destroy it regardless is one the precondition below keeps unreached.

> **Normative.** The purge is a **whole-installation act and runs with no
> provisioning act concurrent with it**. A coordinator that invokes it is
> responsible for that — trivially so where the act is offline (ADR-0126 §2) — and
> the purge itself carries no revision cutoff, because it is deleting everything
> rather than displacing a state. A coordinator that cannot establish it may not
> invoke the purge, since a provisioning act running underneath it would have its
> credential deleted from beneath a record it had just activated (§5's mirror).

> **Normative.** The purge is scope-confined by construction: the provisioner's
> `SecretStore` instance is bound to `INTEGRATION` and to one installation
> (ADR-0125 §2), so the purge cannot reach a `PROVIDER` or `ENROLMENT` entry or
> another installation's, and it enumerates nothing.

> **Normative.** A coordinator **outside `tools/`** that invokes the purge reaches
> it through a Protocol in `core/protocols.py`, like any other cross-subsystem
> reach (golden rule 1). This ADR neither declares that Protocol nor permits an
> injected concrete provisioner in its place: its shape, and whether it is a seam
> of its own or a member of the one §9 defers, belong to the routing decision
> (#909) together with the choice of coordinator.

> **Normative.** What this ADR fixes about that reach is one thing: **holding such
> a seam is not holding a keyring face** — the distinction ADR-0102 §7 drew about
> the composition root and `SourceGrantStore` — so routing the purge gives no
> component a face ADR-0125 §8 keeps out of the seam, and no lane cites the
> routing as acquiring one.

> **Normative.** **This ADR does not route ADR-0126's act to that purge.** That
> act is offline, is in `service/`, and ADR-0126 §6's first clause states that it
> "reaches no keyring" and "performs no keyring operation"; making it invoke the
> purge would change that clause, and changing it is ADR-0126's to do rather than
> this ADR's (**#909**).

> **Normative.** **No lane provisions a connection in an installation before a
> ratified decision routes the owner's delete right to the purge above.** This is
> a named precondition on the implementing lane, in the form ADR-0021 §3 used on
> the standing-grant ADR and ADR-0097 §9a used on the source-registry lane, and it
> is what keeps ADR-0126 §6's last clause honoured rather than merely cited: until
> it lands, an installation that ran the offline delete would keep credentials the
> owner asked to destroy.

**An earlier draft fixed the ordering and stopped there, which left the failure
path open.** Adversarial review found that "slots before the store" is satisfied
by a purge that attempts every slot, has one deletion raise, and destroys the
store anyway — leaving a credential with no remaining durable name, which is
precisely the unreachable-and-present state the ordering clause exists to
prevent, reached through a conforming implementation. The repair is the
completeness clause, and it is the same instrument ADR-0126 §1 uses for its own
act: check first, refuse whole, destroy nothing while anything is unconfirmed.
Idempotence is what makes refusing whole cheap — the owner re-runs it once the
keyring is reachable, and every already-deleted slot costs one `delete` that
raises nothing.

**What ADR-0126 §6 asked for was a decision, and this is the half of it that is
this lane's.** That clause said the question "is a contract question and not a
wiring detail", because "ADR-0125 §5 refuses enumeration and puts the deletion
path on the consumer that wrote the entry, and ADR-0125 §8 keeps `service` out of
the seam, so no path exists today". The clauses above supply the path, put it on
exactly the consumer ADR-0125 §5 puts it on, fix what it composes from and the
one ordering constraint that cannot be discovered later, and establish that a
coordinator can hold it without acquiring a face. Of the three things ADR-0126 §6
said such a decision would have to weigh, two are answered here — the purge is
composed by the consumer that wrote the entries, and it requires **no** fourth
face and no widened scope enum — and the third, whether the coordinator is the
hub or the offline tool, is left where it belongs, with the ADR that owns the act.

**Answering the third here would have been the overreach, not the diligence.**
ADR-0126 §2 shows the offline placement is forced rather than preferred, §5 makes
the instance lock the act's atomicity, and §6's first clause is marked. An ADR
about who holds a keyring face is not the document that reopens any of that, and
ADR-0126 §6's own forward clause is careful to bind that "the question be
*decided* — by whoever creates it, at the moment they create it — rather than
that it be answered here in a package that may not answer it". The symmetric
restraint is the right one in this direction too.

**The precondition is the honest instrument and it is deliberately blocking.**
ADR-0126 §6 already blocks the entry — "Until that decision lands, this ADR
authorises no such entry to be written" — so a version of this ADR without the
precondition would be authorising, by silence, exactly what that clause forbids.
What the clauses above buy is that the remaining question is small and named: not
"how does a delete reach a keyring entry", which is answered, but "who calls the
purge, and does ADR-0126's act change to do it".

### 9. The user reaches it as a hub operation, and the operation's shape is its own contract ADR

> **Normative.** Connecting, re-provisioning, disconnecting and listing
> connections are **hub operations reached by a client** (ADR-0084, ADR-0097 §9's
> shape). They are implemented in `orchestration`, which delegates each act to the
> provisioner (§1) through a Protocol in `core/protocols.py` (§10).
> `orchestration` holds no keyring face, opens no connection store and performs
> none of ADR-0148 §6's three writes.

> **Normative.** The `AssistantEngine` method signatures for these operations,
> the result types they promote to `core/types.py`, their wire frames and the
> shape of the Protocol §10 names are **not decided here**. They are owed as their
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

### 10. New `core` contract surface, flagged and not landed here

> **Normative.** The **user-facing** half of this decision cannot be implemented
> without one piece of contract surface `core` does not have: a Protocol by which
> `orchestration` reaches the provisioner in `tools/` (§9). It is flagged here
> under golden rule 5 and **is not added by this ADR**. It is not the whole of the
> contract surface this decision's neighbourhood will need — §8's routing decision
> owes whatever seam its coordinator's boundary requires — and no lane reads this
> clause as capping that. It is decided in the contract ADR §9 names — the same
> one that decides the operations it serves, because they are one question — and
> its triad rides with the **primary production implementation** as one lane
> (ADR-0137 §2, `CONTRIBUTING.md` → "Adding a Protocol").

> **Normative.** No credential value appears in that Protocol's return types
> (§9). It carries no `SecretName` a caller could use to reach the keyring by
> another route, and holding it confers no keyring face (§8).

> **Normative.** This ADR adds **no** member to `SecretScope`, changes **no**
> signature on `Secrets` or `SecretStore`, adds no field to `ActionRequest`,
> `PermissionDecision`, `ToolDefinition`, `ToolCall` or `ToolResult`, and adds no
> Protocol for the connection record itself (§3). A lane that finds it needs any
> of those is changing a ratified decision and owes its own ADR.

**One Protocol is the floor for what this ADR places, and it is derived rather
than chosen.** The operations are `AssistantEngine` methods, `AssistantEngine` is
`orchestration`'s (ADR-0102 §7), the act's owner is in `tools/`, and a subsystem
boundary between them is a Protocol by golden rule 1. Every other seam *this ADR
places* falls inside one subsystem: the record's store, the callable's read of
it, ADR-0148 §11(b)'s consultation of it, and the purge's implementation are all
`tools/`-internal, which is the placement's whole economy (§1).

**The purge's *invocation* is the exception, and counting it here would have been
the error.** §8's purge is `tools/`-internal as a mechanism, but whoever calls it
may not be: ADR-0126 §2 puts the owner-delete act in `service/`, so a routing
decision that reaches this purge from that act crosses a subsystem boundary and
owes a Protocol exactly as this one does — golden rule 1 admits no injected
concrete in its place, whatever the composition root is willing to hand over.
Architecture review found an earlier draft claiming one Protocol as the complete
floor while §8 contemplated that second consumer, which is a floor stated over
half the neighbourhood. §8's clauses now put the seam with the decision that
chooses the coordinator, because the seam's shape is not answerable before the
coordinator is, and §13 lists that routing as out of scope rather than counting
its surface here.

### 11. What this ADR does not gate, discharge or authorise

> **Normative.** Nothing here discharges any of ADR-0017 §3's fourteen
> conditions, attests that one holds in code, or designates the `tools/` egress
> seam. `tools/` still transmits nothing, and no lane may cite this ADR toward a
> condition, a designation, or a connection to any counterparty.

> **Normative.** Nothing here closes **#74**, which asks whether ADR-0004 §7's
> Tier 0 gating reaches the model provider credential. ADR-0125 §9's clause stands
> exactly as written — the keyring seam gates nothing and is a storage seam — and
> §7 above is a statement about a provisioning act and about nothing else.

> **Normative.** Nothing here authorises connecting to an MCP server over any
> transport. ADR-0147 §4's fourth and fifth clauses stand undischarged and
> unrelaxed (§13).

**The reason for saying it is ADR-0147 §3's and ADR-0148 §13's:** a document that
supplies the machinery for holding an integration's credential reads like
permission to use one. It is not. What becomes possible when this ADR merges is
that a lane may *write* a credential and a record — and a lane may still not
transmit a byte, because the conditions that gate transmission are ADR-0017 §3's
and none of them moves here.

### 12. This ADR classified under ADR-0070 §1 and ADR-0082 §1

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
  are both untouched. ADR-0149 §3 puts the connection store under
  `Settings.data_dir`, opened by `build_engine`, append-only, with its seam
  `tools/`-internal, so no Protocol is added to `core/protocols.py` for it; §5's
  refusal of enumeration is what makes that store the only composable purge path,
  which ADR-0149 §8 uses to answer the purge-contract half of ADR-0126 §6's
  forward clause. That clause is **not** discharged: its prohibition on writing
  such an entry stands until #909 settles who routes the owner's delete to that
  purge, and ADR-0149 §8 carries it forward as a precondition. **§8 is
  unchanged**: its fourth clause enumerates ten subsystems, `tools/` is not among
  them, and its second clause — about the tool that needs a read face — stays true
  as written (ADR-0149 §2). §1's two faces, §2's scope and installation binding,
  §4's replace-in-place `set` and its concurrency disclaimers, §6's absence rule
  and §7's platform posture are consumed exactly as ratified; §9 is untouched and
  #74 stays open on its own subject. The bullet's **provider key** half is **not**
  discharged: it stays with §12's first bullet, #74 and a `models/` lane
  (ADR-0149 §13). §12's other bullets — rotation and expiry *policy*, the
  `keyring` dependency, backup, and #462 — are unaffected and remain scoped out,
  though ADR-0149 §5 and §6 decide two consequences that meet the backup bullet
  and the rotation bullet at their edges: a disconnection never resets a
  reference's revision, and an active record over an empty slot is refused rather
  than repaired.
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

**ADR-0126 §6 — no record owed, and the clause is answered in part and left
standing.** Its forward clause requires the lane that first gives a component on
the hub's machine a Tier 0 keyring entry to decide, in the same change, how a
hub-side delete reaches it. §8 above decides the contract half — the path, whose
consumer holds it, what it composes from, its ordering and its completeness — and
leaves the routing half to #909. **The clause is therefore not discharged**, and
this ADR does not say it is: its last sentence, that no such entry may be written
until the decision lands, stays operative and §8's precondition is that sentence
carried into this ADR rather than relaxed. A clause partly answered and still
binding is the clearest case there is of one that owes no record. Its other
clauses stay true as written: the act still reaches no keyring, still holds
neither face, still performs no keyring operation and still enumerates nothing,
because §8's fifth clause deliberately does not route it. §6's second clause —
"No component of this system writes a Tier 0 keyring entry on the hub's machine
today" — is a dated statement about the tree, which is still true of the tree (§
*The tree, read rather than remembered*) and which the implementing lane, not
this ADR, makes false; §8's precondition is what keeps that lane from making it
false before the coordinator question is ruled. §6's supersession of ADR-0004 §6
for a Tier 0 credential held *outside* the keyring is self-limiting by its own
terms and is neither cited nor widened here: a slot in the keyring is not what
that clause reaches. ADR-0126 §11's supersession of ADR-0004 §7 is likewise
confined to that act, is not cited here, and §7 above is careful to take nothing
from it (§7's fourth clause).

**ADR-0004 §6 and §7 — no record owed.** §6 is used as given and is served rather
than narrowed: §3 makes the connection store a Tier 1 artifact under `data_dir`
and §8 makes its Tier 0 entries reachable by a purge, which is §6's "purges Tier 0
(keyring entries) and Tier 1 (database rows) together" being made *possible* for
a new entry rather than being qualified. §7 is engaged and answered in §7 above,
with its gate half read as reaching the assistant's accesses rather than the
owner's own acts — the reading ADR-0097 and ADR-0102 already embody, and which
ADR-0097 §11 examined against §7 without recording an amendment — and its record
half supplied by the append-only store. No exemption is claimed, and §7's fourth
clause forbids a lane from reading one.

**ADR-0148 §6, §11 and §13 — no record owed.** §11's fourth clause requires "the
ADR that names its owner", §13's ninth bullet says the owner "wants the producer
§11 defers for", and this ADR names the owner. A condition is not made false by
being answered. §6's clauses are consumed and not restated; §5, §6 and §8 above
add beside them — disconnection, the revision across it, the empty slot and the
purge — and each is a case §6 does not rule on, so no sentence of §6 becomes
false. §3's append-only store satisfies §6's compare-and-swap in §6's own terms
and is checked against it clause by clause in §3. §7's positional read rule is
strengthened in fact and unchanged in text (§1). §11's own deferral of surfaces
(a) and (b) is untouched, and this ADR decides neither.

**ADR-0097 §§1, 3, 4, 8 and 9, and ADR-0102 §§1, 7, 8, 9 and 11 — no record
owed.** They are read as **precedent** and, in §4, as a model this ADR partly
declines. A connection is not a `SourceGrant`, the grant store gains nothing and
loses nothing, `GrantScope` gains no member, no clause about a source's identity
is read wider, and the four grant operations are untouched. ADR-0102 §7's "no
other object in the system holds a `SourceGrantStore`" stays true — the
provisioner holds none.

**ADR-0083 §2, ADR-0084 §§5 and 9, ADR-0016 §§5, 6 and 7, ADR-0029 §§1, 2 and 6,
ADR-0021 §1, ADR-0125 §§1–7 and 9, ADR-0147 §§3 and 4, ADR-0123 — no record
owed.** Each is used as given. A new store under `data_dir` is
`Settings.data_dir` working as ADR-0083 §2 designed it; a new hub operation is
ADR-0084 §5's split working as designed; ADR-0016's registry rules are relied on
and not narrowed; ADR-0029 §6's "no credential value crosses this seam" is
inherited; ADR-0123's backup scope is stated rather than changed, and §6 above
adds the refusal that scope implies rather than asking that lane for anything.

**What would have owed a record and is deliberately not done.** Giving
`orchestration`, `service` or `interfaces` a keyring face (ADR-0125 §8's fourth
clause — §1 refuses that placement on its own merits, not to avoid the record);
routing ADR-0126's act to §8's purge (ADR-0126 §6's first clause — §8's fifth
clause refuses it); adding a `SecretScope` member; changing what a connection
record carries; or reading ADR-0148 §6's states as admitting a third.

### 13. Explicitly out of scope

Scoping something out is a decision, so each carries its reason (ADR-0029 §7's
form).

- **Who invokes §8's purge when the owner deletes everything, and the seam they
  reach it through** — **#909**, and §8's clauses say why neither is answered here
  and what is blocked until they are. The candidate answers ADR-0126 §6 names are
  still the candidates: a coordinator composing each consumer's deletion path, and
  whether that coordinator is the hub or the offline tool. Whichever it is, a
  coordinator outside `tools/` owes a `core` Protocol for the reach (golden rule
  1, §8's fourth clause), and that surface is that decision's rather than §10's.
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
  §11 above adds nothing to ADR-0017 §3's list and relaxes none of it.
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
- **What a connection listing shows, and whether the store's history is exposed
  to the user.** §3 keeps the history because the act's record is what ADR-0004 §7
  asks for (§7) and because §8's purge is composed from it; whether a client
  renders past connections, and under what paging, is the surface ADR's (§9),
  bounded by §9's third clause.
- **Whether a backup carries a connection record** — ADR-0123's scope, stated
  rather than changed. §6 rules what happens when a restored record outlives its
  credential; whether the record is in the backup at all is that lane's.
- **Provisioning from an enrolled device over the remote transport.** ADR-0124 §1
  enumerates the boundaries and a credential crossing to the hub from a remote
  spoke raises questions about that hop this ADR has no producer for. §9's surface
  ADR decides which clients may reach the operations; what this ADR fixes is that
  the credential comes to rest only in the hub's keyring wherever it was typed.
- **Per-tool confinement inside `INTEGRATION`** — ADR-0125 §2's named residual,
  accepted there and not widened here (§2). The fix, if a plugin model ever makes
  it necessary, stays the additive one §2 describes.
- **Transport pinning** (**#83**) and the **payload manifest** (**#57**).
  ADR-0148 §13 owns both; a connection record carries no endpoint and no
  description.

### 14. What the implementing lanes owe

> **Normative.** The lane that lands the provisioner ships, beyond ADR-0148 §14's
> matrix: a test that a disconnection followed by a re-connection on the same
> reference takes a revision strictly greater than every revision that reference
> ever held (§5); a test that a call bound to a reference whose record is active
> and whose slot is empty is refused and transmits nothing (§6); a test that a
> provisioning act appends rather than overwriting, so the store still answers
> what the previous act recorded (§3); a test that the provisioner never calls
> `get`; and a test that a disconnection whose slot deletion fails leaves the
> reference disconnected, reports the failure, and leaves the slot reachable by
> §8's purge (§5).

> **Normative.** That lane also ships the **disconnect interleaving** §5 exists
> for: a re-provisioning that has appended its pending entry and paused, a
> disconnection that lands between that entry and the displaced act's
> `Secrets.set`, and the `set` landing afterwards. The disconnection deletes every
> slot the store then names for the reference — the pending one and the previously
> active one — the reference is left with no live record, and the slot the
> displaced write created is deleted by a re-run of the disconnection and by §8's
> purge. A test that disconnects only a quiescent reference satisfies none of this.

> **Normative.** That lane also ships the **inverse** interleaving §5's revision
> cutoff exists for: a disconnection whose removal entry has landed and whose
> deletion pass has not yet run, a re-provisioning that appends its pending entry
> and writes its credential in that window, and the deletion pass running
> afterwards. The re-provisioned slot survives, the activation lands over a
> credential that is present, and a call under it transmits. An implementation
> that deletes every slot the store names at deletion time fails this test.

> **Normative.** That lane also ships §8's purge with a test that it deletes the
> slot of a superseded, a pending and a removed record as well as of a live one; a
> test that a deletion that raises leaves every store entry in place and the
> failure reported; a test that re-running it after that failure completes; and a
> test that it reaches no entry outside the `INTEGRATION` scope or outside its
> installation (ADR-0125 §2).

> **Normative.** That lane also ships the two degenerate disconnections §5
> defines: one on a reference with entries but no live record, which appends
> nothing and re-runs the deletion pass at the latest removal's revision, and one
> on a reference the store has never held, which writes nothing, deletes nothing
> and leaves the store byte-identical.

> **Normative.** That lane also ships the identity refusals §4 adds: an act whose
> supplied identity equals the supplied credential is refused with nothing
> written, and so is one whose identity carries a control character or a line
> break.

> **Normative.** That lane also ships the import-linter or equivalent mechanical
> confinement that the provisioner's module is the only module under `tools/`
> naming `SecretStore`, in the spirit of ADR-0125 §8's contract confining the
> keyring library to one package — a convention held by review is the state
> ADR-0125 §8 records as having survived from ADR-0004's ratification until a
> third consumer made it blocking.

> **Normative.** No lane implements any of it before the contract ADR §9 names has
> merged (golden rule 5, ADR-0015 §5), and no lane provisions a connection in an
> installation before §8's precondition is met. This ADR merging discharges
> **ADR-0148 §11's fourth clause and no other precondition**: ADR-0126 §6's
> forward clause is answered in part (§8, §12) and its prohibition stands until
> #909 is ruled.

### 15. Marking, review and ratification

- **Marked under ADR-0089 §2, and the marks are the whole of what this ADR
  obligates** (§3 there). Unmarked text — the placement arguments in §1 and §2,
  the classification in §12 and the scope-outs in §13 — is read to determine what
  a marked clause means and supplies no obligation of its own, except where §13's
  bullets restate a marked clause elsewhere by citation.
- **Citations are in ADR-0088 §1's forms**, and no code citation carries a line
  number (§5 there): the modules and symbols named above are named by symbol.
- **Drafted, reviewed and revised while `Proposed`**, with the required set —
  adversarial *and* architecture — run against it in that state, its status
  flipped only once both returned clean on one tree, and both re-run on the
  flipped tree for the coverage reason `CONTRIBUTING.md` → "Finishing an ADR PR"
  gives. Architecture review's first round produced §3's append-only store, §7 and
  §8: the first draft made the store's shape an implementation detail, asserted
  ADR-0004 §7's inapplicability in half a sentence, and promised that deletion
  "purges the record and the credential slot it names together" without a path by
  which any delete surface could reach the slot — the bound-with-nothing-behind-it
  defect ADR-0098 §3 records itself making twice, and ADR-0126 §6's forward clause
  had been written to catch exactly it. Adversarial review's rounds then produced
  §4's identity refusals, §5's every-slot, revision-cutoff and idempotence
  clauses with the honest guarantee beside them, §5's two degenerate
  disconnections, and §8's completeness clause — one family of defect, in which a
  rule was stated over the ordinary case while a conforming implementation could
  satisfy it and still leave a credential in the keyring — and it caught the
  prescribed ratification note still claiming a discharge the rest of the document
  had already withdrawn. Architecture's later round produced §8's fourth clause
  and §10's correction: an earlier draft counted one Protocol as the complete
  contract floor while §8 contemplated a purge coordinator outside `tools/`, which
  golden rule 1 gives a seam of its own. Findings raised after the flip were
  folded the same way. Nothing implements against this ADR until it has merged
  (ADR-0015 §5).

## Consequences

- **ADR-0148 §6 becomes performable.** Its clauses had no party entitled to
  satisfy them; §1 names one, and ADR-0148 §14's test list acquires a subject.
- **ADR-0126 §6's forward clause is answered in part and its remaining question is
  small.** The path exists, its ordering and completeness are fixed, and #909 is
  reduced from "how does a hub-side delete reach a keyring entry" to "who calls
  it". The clause's prohibition is not lifted here, and §8's precondition is what
  keeps it binding on the implementing lane.
- **One subsystem holds the whole connection concept.** The record, its store, its
  readers, its writer and the purge's mechanism are all in `tools/`, so the
  contract surface *this ADR places* is the one the user's act crosses — one
  Protocol instead of the two a different placement would have cost, and no
  supersession of ADR-0125 §8. That is not a claim about the neighbourhood's total:
  §8's routing decision may need a Protocol of its own at whichever subsystem
  boundary its coordinator sits on, and injecting the concrete provisioner across
  such a boundary in order to keep the count at one is what §8's fourth clause
  forbids.
- **`tools/` acquires durable state and a write face onto the keyring**, which it
  did not have. That is the real cost: a subsystem that will host integration code
  now contains the one component that can write an `INTEGRATION` credential. §1's
  confinement clauses and §14's mechanical check are what keep the blast radius at
  one module, and ADR-0125 §2's plugin caveat is the condition under which this
  placement wants revisiting.
- **A connection becomes a user act with the same shape as a grant and a store
  that records it.** An installation cannot acquire a live connection by being
  configured, upgraded or restored, and what the owner connected and disconnected
  is answerable afterwards — which is what §7 offers ADR-0004 §7 in place of an
  audit record no permission decision produced.
- **Two states ADR-0148 §6 left reachable are now refused rather than
  reconciled** — a re-connected reference reusing a revision, and an active record
  over an empty slot. Both are cheap to hold and neither was detectable by the
  checks §6 already specifies.
- **Leg 12's actuator work now waits on two decisions rather than one.** The
  surface ADR §9 names, and #909's coordinator ruling that §8's precondition
  binds. Neither is invented here: the first is ADR-0084 §5's split and the second
  is ADR-0126 §6's own clause, which already forbade the entry until it lands.
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
  is a declared constant, the live state ADR-0148 §6 requires is not one a grant
  store can express, and `VISION.md` governs reading and acting separately.
  Attractive because it would have reused a ratified store and surface;
  unavailable because ADR-0148 §6's checks read a record a `SourceGrantStore`
  cannot be. What *is* taken from it is ADR-0097 §4's append-only shape (§3).
- **A live-record-only store, with a retained revision counter and no history.**
  The first draft's answer, and refused for two reasons found in review: it left
  ADR-0004 §7's recording half unanswered for a Tier 0 write, and it left a failed
  predecessor deletion holding a slot no record names — an entry §8's purge could
  not compose. Append-only costs a row and answers both.
- **Superseding ADR-0004 §7 for the provisioning act**, in ADR-0126 §11's
  instrument. Refused in §7: §7's gate is unavailable to ADR-0126's act because no
  policy layer is running, which is what made a supersession the honest instrument
  there. Here the act runs inside a live hub, the reading it takes is the one the
  grant operations already embody, and claiming an exemption would put on the
  record a narrowing of a safety clause that this ADR does not need and could not
  confine.
- **Routing ADR-0126's offline act to §8's purge**, which would close the delete
  question outright. Refused in §8: it changes ADR-0126 §6's first marked clause,
  and ADR-0126 §6 is explicit that the deciding lane should not answer in a
  package that may not answer it. The precondition is the instrument that leaves
  that ruling where it belongs while refusing to ship an unpurgeable credential.
- **Serialising a disconnection against an in-flight provisioning write**, so
  that a disconnection could promise the keyring holds nothing for the reference.
  Refused in §5: it needs a lock held across a keyring write, which is the
  mechanism ADR-0097 §5a examined and refused — "a permission withdrawal waiting
  on the thing it is withdrawing" — and which ADR-0148 §6 forecloses by ruling a
  displaced act's write neither stopped nor waited for. Naming the slot and making
  the remedy idempotent buys the property that matters, which is that no such
  entry is unreachable.
- **Deciding the engine operations here**, so that one ADR unblocks the
  implementation entirely. Refused in §9 on ADR-0084 §5's split and ADR-0073 §4's
  producer test: `AssistantEngine` is a closed graph with a wire encoding, and the
  arguments a connect operation needs are exactly what a first real integration
  would tell us.
