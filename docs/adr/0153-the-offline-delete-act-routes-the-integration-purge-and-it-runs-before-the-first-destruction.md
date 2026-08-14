# 153. The offline delete act routes the integration purge, and it runs before the first destruction

- Status: Proposed
- Date: 2026-08-14
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-14**,
  the durability form ADR-0100 established and ADR-0125, ADR-0126, ADR-0149 and
  ADR-0151 each followed. ADR-0126 **will be edited by this change, in its
  ratification commit** (the records bullet below), and ADR-0149 and
  ADR-0151 were ratified in the last six days; a citation that silently means
  "whatever this ADR says when you read it" is not checkable. Where a later ADR
  changes one of them, this one is read against the text named here until an ADR
  says otherwise.
- **This ADR partially supersedes ADR-0126, in six limbs across five sections.**
  Every limb is one sentence-fragment, every one
  of them says the delete act reaches no keyring or needs no contract to do its
  job, and every one is narrowed to exactly the `INTEGRATION` scope and exactly the
  seam §2 places: §3's cross-boundary injection clause, §6's first and second
  clauses, §7's "no keyring is reached" limb, §8's `core/protocols.py` limb, and
  §11's "destroying the resolved `data_dir` and nothing else" limb. §10 applies
  ADR-0070 §1's test to each and states what survives, which is nearly all of all
  five sections — including the whole of §6's supersession of ADR-0004 §6 for the
  environment-held provider credential, the whole of §5's ordering, and the whole
  of §2's placement. No ratified text of ADR-0126 is rewritten; its `Status` line
  and its appended dated note are the whole of the record (ADR-0070 §1, ADR-0082
  §1 and §2).
- **Records for ratification: ADR-0126's `Status` line and one appended dated
  note**, applied in the same commit that flips this ADR's `Status` to `Accepted`
  and not before — ADR-0017 §7 requires the operation performed on another ADR to be
  recorded rather than inferred, and writing "Partially superseded by ADR-0153" onto
  a live ADR while this one is `Proposed` would name an unratified document as a
  superseder, which is the state claim ADR-0019 forbids. ADR-0149's header bullet
  took this form for the same reason one ADR earlier, and it is followed rather than
  re-derived. §10 applies ADR-0082 §1's test to every ADR this one touches, shows
  its working, and carries **the exact text of both halves** so that what will be
  written is reviewable while this ADR is still `Proposed`. ADR-0126's `Status` line
  has no leading token today and therefore takes one (ADR-0082 §2).

  **This defers no substance past review, and the objection is answered rather than
  waved away because both reviewers raised it from opposite sides.** Three things
  answer it. `CONTRIBUTING.md` → "Finishing an ADR PR" step 3 requires the whole
  required set to be **re-run on the flipped tree** — "not a judgement call and not
  a symptom of anything" — so the ratification commit is reviewed by both lenses,
  and "Trivial ADR edits" is scoped by its own words to a review *of the edit
  itself* rather than to coverage. §10 carries the exact text of both halves now, in
  a fence, so what will be written is read while this ADR is `Proposed` — which is
  the state a finding can still change it in — rather than first seen at the flip.
  And the judgement ADR-0082 §1 actually places is the **classification**, which it
  requires "in the later ADR's text, which is where it is reviewed": that is §10,
  and it is in this change from the first commit.

  **The leading token is what makes the ordering matter rather than merely tidy.**
  ADR-0082 §2 and `docs/adr/template.md` put `Partially superseded by` at the head
  of the line and **drop `Accepted`**, so that "a prefix match on 'Accepted' cannot
  misread the replaced part as live". Written before ratification, that line would
  stop ADR-0126 reading as `Accepted` at all, on the authority of a document nothing
  has ratified — a live decision demoted by a draft. That is a worse state than the
  one deferring it creates, and it is the concrete form of the state claim ADR-0019
  forbids.
- **No implementation lands with it.** No `src/`, no `tests/`, no
  `pyproject.toml`. §8 sequences the two lanes that build against it.
- **It decides `core` surface.** One Protocol in `core/protocols.py`,
  `ConnectionPurger`, with two members. No type, no constant, no enum member, no
  error class, and no `PROTOCOL_VERSION` change. §7 is the complete list, in
  ADR-0150 §2's form, and it is flagged under golden rule 5 rather than landed
  here.
- **Its required review set is adversarial *and* architecture.** It places a
  Protocol, it partially supersedes six limbs of an ADR ratified four days after
  the one it routes into, and its whole subject is an ordering whose failure modes
  are answerable from prose before an implementation commits to an answer
  (`CONTRIBUTING.md` → "Contract ADRs land before their implementation"). §11
  records what each review produced.

## Context

### ADR-0126 §6 reserved a question, and two later ADRs answered all of it but one part

ADR-0126 §6's last marked clause is the reservation:

```text
> **Normative.** The lane that first gives a component on the hub's machine a Tier
> 0 keyring entry owes, in the same change, a decision about how a hub-side delete
> reaches it. That decision is a contract question and not a wiring detail — ADR-0125
> §5 refuses enumeration and puts the deletion path on the consumer that wrote the
> entry, and ADR-0125 §8 keeps `service` out of the seam, so no path exists today
> that this act could take. Until that decision lands, this ADR authorises no such
> entry to be written, and no lane may cite this section as a route to one.
```

Its unmarked prose names three things such a decision would weigh: whether the
purge is **composed** by each consumer or performed by a single holder, whether
the **coordinator** is the hub or the offline tool, and whether either needs a
**fourth face or a widened scope enum**. **#909** carries the reservation.

**ADR-0149 §8 answered the first and the third.** The deletion path for an
`INTEGRATION` keyring entry is the provisioner's and is the only one; it deletes
every credential slot the connection store names and then the entries that named
them; it needs no fourth face and no fourth scope member, because the
provisioner's `SecretStore` instance is already bound to `INTEGRATION` and to one
installation (ADR-0125 §2). Its fourth clause left the seam's shape — "whether it
is a seam of its own or a member of the one §9 defers" — to #909 "together with
the choice of coordinator", and its tenth clause fixed the one thing that makes
either shape available: **holding such a seam is not holding a keyring face.**

**ADR-0151 §14 declined the rest and narrowed its cost.** It places
`ConnectionProvisioner` with five members, states that the five-member enumeration
"is not a bar on" a purge member, and offers the cost difference: a hub
coordinator already reaches the provisioner through that Protocol and would pay
one member; an offline coordinator is in `service/` and pays a new seam. It says
in as many words that this is "a cost difference, not a decision".

**So exactly one question is left, and it is a placement question wearing a
contract question's clothes.** Who invokes ADR-0149 §8's purge, through what, and
where in the act's order does it sit — and what does ADR-0126 §6's first clause
become once something does.

### The tree, read rather than remembered

Every ADR above was written while the delete act was an intention. It is not one
any more, and this section is what the routing is designed against.

- **`ai-assistant-purge` has shipped.** `pyproject.toml` declares
  `ai-assistant-purge = "ai_assistant.service.purge:main"` beside the seven other
  offline scripts, and `src/ai_assistant/service/purge.py` implements ADR-0126 §1
  through §7 whole: the mount-point refusal off `/proc/self/mountinfo`, the
  descriptor-relative removability preflight, the instance lock held across the
  entire act, `devices.db` first with its sidecars and the stop-the-act exemption,
  the depth-first destruction of everything else, and the two statements.
  ADR-0126 §9's prerequisite is met — `DEVICE_PURGE_ACT` in that module names
  `assistant device unenrol`, which `interfaces/cli.py` ships.
- **Its locked body is five steps in a fixed order.** `_run_locked` runs
  `_live_enrolments`, then `_refuse_unremovable`, then `_state_before`, then
  `_confirm`, then `_destroy`, then `_state_after`. Every refusal-producing check
  precedes the confirmation, and `_destroy` is the first thing that removes
  anything. That shape is what makes §3 below a one-step insertion rather than a
  redesign.
- **The act holds no keyring face and says so in prose.** Its imports are
  `core.config`, `core.errors`, and six modules of its own package; there is no
  `ai_assistant.secret_store` import. `_state_before` prints, under "what this act
  does not reach:", the line beginning `no keyring.` — ADR-0126 §6's fourth clause
  discharged as shipped text. That line is what §5 replaces.
- **The keyring seam has shipped.** `secret_store/store.py` carries
  `KeyringSecretStore`, constructed with a `scope` and an `installation`;
  `secret_store/backend.py` carries `KeyringBackend`, `select_backend` and
  `PROTECTED_BACKEND_MODULES`. `core/protocols.py` carries `Secrets` and
  `SecretStore`; `core/types.py` carries `SecretScope`, closed at `PROVIDER`,
  `INTEGRATION` and `ENROLMENT`. **Neither Protocol nor the backend has any
  listing member**, and `Secrets`' own docstring states ADR-0125 §5 normatively.
- **No hub-side component holds a Tier 0 keyring entry today, which is still
  true.** The only production construction of `KeyringSecretStore` is
  `_enrolment_secrets` in `interfaces/cli.py`, at `SecretScope.ENROLMENT` — the
  device's own keyring on the device's own machine, which ADR-0126 §6's sixth
  clause already excludes from this act and ADR-0124 §8 already governs.
- **`ConnectionProvisioner` does not exist.** Nothing in `src/` or `tests/`
  defines or names it, nothing under `tools/` is a provisioner, and `core/types.py`
  carries no connection type. ADR-0151's implementation lane has not landed.

**The one thing that has changed since ADR-0126 was written is the most useful
one.** Its §6 could only bind a future lane to decide; the decision now has a
shipped act with a known five-step body to attach to, so the routing can be stated
as a position in an order rather than as a shape to be invented later.

### The state this decision exists to make unreachable

ADR-0149 §3 puts the connection store under `Settings.data_dir`, and ADR-0149 §8's
first clause makes that store the **only** durable list of the credential slots the
provisioner wrote — because ADR-0125 §5 refuses enumeration, so nothing can
discover a slot it did not record.

The delete act destroys the contents of `Settings.data_dir`. Those two sentences
together describe a trap: an act that destroys the store before the slots are gone
leaves Tier 0 credentials in the owner's keyring that **no component of this system
can ever name again**. Not by re-running the act, not by a hub, not by a later
lane. ADR-0149 §8's second clause names it — "Tier 0 data that is unreachable and
present, which is the state ADR-0004 §6's 'purges Tier 0 and Tier 1 together'
exists to prevent, and which no later act could repair" — and its fifth clause
forbids any component discharging the delete right from reaching it.

Every ordering rule below is that clause, worked through against the shipped act.

### What this ADR is not allowed to settle

- **The purge's mechanism.** ADR-0149 §8 fixed what it deletes, in what order,
  what completeness it owes, and that it is idempotent and scope-confined. Nothing
  here re-opens any of it, and §2's seam is a way to *call* it.
- **The five connection operations.** ADR-0151 decided them. This ADR adds no
  `AssistantEngine` method — ADR-0126 §2's prohibition on one for this act stands
  whole — and changes none.
- **Per-connection removal.** `disconnect_account` and ADR-0149 §5's deletion pass
  are the owner's per-reference path and are untouched (§9).
- **The provider credential.** #74 stays open, and ADR-0126 §6's supersession of
  ADR-0004 §6 for the environment-held provider key stands exactly as ratified
  (§9, §10).

## Decision

### 1. The coordinator is ADR-0126's offline act, and a hub-side coordinator is refused

> **Normative.** The component that invokes ADR-0149 §8's purge is the offline
> whole-installation delete act ADR-0126 §1 and §2 define — `ai-assistant-purge`,
> in `ai_assistant/service/`, running with the hub stopped and holding the instance
> lock. No other component invokes it as part of discharging ADR-0004 §6's delete
> right.

> **Normative.** No part of the hub performs, schedules or triggers the purge as a
> whole-installation act, and no `AssistantEngine` method, no wire operation, no
> `assistant` CLI command and no act on `<data_dir>/admin.sock` carries it.
> ADR-0126 §2's four clauses bind this step exactly as they bind every other step
> of the act.

> **Normative.** The delete right is discharged by **one** act and one command. No
> lane may split it into a hub-side phase and an offline phase, or require the
> owner to run two commands in order, whatever their order.

**A hub coordinator is refused on ADR-0126's own rejected alternative, and the
argument is stronger here than it was there.** That ADR considered "revoke first
through the running hub, then stop it, then destroy the directory" and refused it
because "'as part of the same act' would become a claim about two commands an
operator runs in order. The window between them is unbounded and the failure in it
is silent: an operator who runs the first and not the second has revoked every
device and deleted nothing, with no record anywhere that the act was begun."

Transpose it. An operator who runs a hub-side credential purge and not the offline
delete has destroyed their integration credentials and kept all their data — a bad
outcome, recoverable by running the second command. An operator who runs the
offline delete and not the hub-side purge has destroyed the connection store, which
is the only index into the keyring, and their credentials are now unreachable and
present **forever**. The first failure ADR-0126 refused was recoverable in both
directions; this one is not, in one direction, and it is the direction an operator
reaching for `ai-assistant-purge` takes by default.

**The instance lock is the second reason, and ADR-0149 §8 named it in advance.**
Its sixth clause requires the purge to run "with no provisioning act concurrent
with it" and puts the burden on the coordinator — "trivially so where the act is
offline (ADR-0126 §2)". A hub-side coordinator has to establish that property
inside a running process that is simultaneously serving the operation that
provisions, and nothing in ADR-0151's surface offers it a lock or a quiesce. The
offline act establishes it by construction: `InstanceLock` is held from before the
purge until after the last destruction, no hub can start, and no provisioning act
exists to race. A clause ADR-0149 §8 called trivial for one placement is an
unbuilt mechanism for the other.

**The third reason is that the hub cannot do the rest of the act anyway.**
ADR-0126 §2's whole argument is that a running hub cannot destroy the directory it
holds open, which is why the act is offline and why §2 calls the placement forced
rather than preferred. A hub-side coordinator therefore cannot *be* the delete act;
it can only be a phase of it, which is what the first argument refuses.

**What is given up is the cheaper seam, and ADR-0151 §14 priced it honestly.** A
hub coordinator would have paid one member on a Protocol that has to exist anyway;
this pays a second Protocol and a second triad. That is a real cost and it is the
right one to pay: the state the cheaper option risks is the only unrepairable state
in this neighbourhood, and a contract seam is cheap by comparison with a class of
Tier 0 data that nothing can ever name.

### 2. The seam is a new two-member Protocol, not a sixth member on `ConnectionProvisioner`

> **Normative.** `core/protocols.py` gains **one** Protocol, `ConnectionPurger`,
> the seam by which the offline delete act reaches ADR-0149 §8's purge. It carries
> exactly two members, with these signatures:

```python
@runtime_checkable
class ConnectionPurger(Protocol):
    async def connected(self) -> tuple[ConnectedAccount, ...]: ...

    async def purge(self) -> None: ...
```

> **Normative.** `ConnectionPurger` is `@runtime_checkable`, so
> `isinstance(subject, ConnectionPurger)` answers rather than raising, and §8's
> suite asserts it. `ConnectionProvisioner` is not made runtime-checkable by this
> ADR and ADR-0151 §10's declaration is unchanged.

> **Normative.** `connected` answers with the live connection record for every
> reference the store holds one for, in ADR-0149 §3's sense of *live* — the
> reference's latest entry, where that entry is not a removal. It writes nothing,
> deletes nothing and reads no credential value. It is the same question
> `ConnectionProvisioner.connected` answers, with the same signature and the same
> semantics, and one implementation satisfies both faces with **one** method; no
> lane gives them divergent behaviour.

> **Normative.** `purge` performs ADR-0149 §8's purge and returns nothing. There is
> no success value, because ADR-0149 §8's third clause rules that a partial purge is
> a failed purge: the call either completes — every distinct slot the store names
> confirmed deleted or confirmed absent, and the entries then removed — or it
> raises, and no value distinguishes a lesser outcome.

> **Normative.** `ConnectionPurger` carries **no** member that writes, provisions,
> re-provisions or disconnects, no member that reads a credential value, and no
> member that names a `SecretName` in any argument or return type. Holding it
> confers no keyring face (ADR-0149 §8's tenth clause), and no lane cites holding
> it as acquiring one.

> **Normative.** `ConnectionProvisioner` gains **no** purge member and no other
> member. ADR-0151 §10's five-member enumeration stands exactly as ratified, and
> this ADR exercises the freedom ADR-0151 §14's third clause reserved by declaring
> a seam of its own rather than by taking the member.

> **Normative.** The **primary production implementation** of `ConnectionPurger` is
> the connection provisioner in `tools/` (ADR-0149 §1, ADR-0149 §8's first clause),
> and no second implementation exists in production. `service/` reaches it by
> injection from the composition root and constructs neither it, nor a
> `SecretStore`, nor a connection store (golden rule 1, ADR-0126 §3).

**A sixth member on `ConnectionProvisioner` was the cheap answer and it hands the
wrong capability to the wrong component.** The holder here is an offline,
irreversible, destructive tool. Handing it `ConnectionProvisioner` would let it
name `provision`, `reprovision` and `disconnect` — so the one component in the
system whose entire purpose is destroying an installation would also be able to
create a connection in one. Nothing would call it and nothing would notice; the
capability would simply be expressible.

**That is ADR-0125 §1's argument and ADR-0149 §1's, arriving a third time.**
ADR-0125 split `Secrets` from `SecretStore` because "a tool holding a three-method
store can delete the device's enrolment credential, and nothing in the type system
or the review process would notice … With the split, the tool's dependency cannot
express the call." ADR-0149 §1 refused to let a tool provision itself on the same
ground: "Removing `set` and `delete` from what a tool's dependency can express is a
type rather than a promise." The corpus has now paid for the narrow face twice for
this exact reason, and paying for it a third time is consistency rather than
novelty.

**There is a second, structural reason the five members do not transfer.**
`ConnectionProvisioner`'s other four members are operations on a **running** hub,
and their contracts are stated about one: ADR-0151 §7's four provisioning
outcomes, ADR-0148 §6's compare-and-swap and its permitted interleavings, and
ADR-0151 §9's paging. The offline act runs with the hub stopped and with no
concurrent act by construction. Handing it members whose ratified semantics are
about interleavings that cannot occur would be handing it a contract nobody has
read against its situation.

**`connected` is on this face rather than derived elsewhere, because §5's statement
needs it and nothing else can supply it.** The offline act has no engine, no hub
and no client, so `connected_accounts` (ADR-0151 §2) is unreachable to it; and
after the act the connection store is gone, so a statement composed afterwards
names nothing. It is exactly ADR-0126 §7's argument for stating the device list
before the destruction, applied to a second class of custodian the act cannot
reach.

**Naming it identically to `ConnectionProvisioner.connected` is deliberate.** One
object satisfies both Protocols structurally with one method, which is the shape
ADR-0125 §1 chose for `Secrets` and `SecretStore` — "one object satisfies both
structurally, so a composition root hands each consumer the face its job needs
without needing two classes." Two names for one answer would invite two
implementations and a drift between them, and a reader comparing the two faces
would have to check whether the difference in name meant a difference in meaning.

**The decorator is on `ConnectionPurger` and the claim it supports reaches that
face and no other.** ADR-0125 §1 made both `Secrets` and `SecretStore`
`@runtime_checkable` and ADR-0125 §11 spends two suite obligations on the resulting
`isinstance` checks, which is the precedent for making a *new* face checkable when
a suite is going to assert it — and §8's suite asserts exactly one, against
`ConnectionPurger`. `ConnectionProvisioner` is ADR-0151 §10's declaration, this ADR
changes nothing about it (§7), and ADR-0151 §16's suite asks for no `isinstance`
against it; so no clause here may be read as making it checkable, and no lane may
write `isinstance(subject, ConnectionProvisioner)`, which against a bare `Protocol`
raises `TypeError` rather than answering. That asymmetry is the reason the decorator
is stated in a marked clause rather than left to the block: without it, §8's suite
obligation would not fail, it would error.

**The Protocols are not made to inherit from one another, and that is the point.**
`SecretStore(Secrets, Protocol)` inherits because the wide face genuinely *is* the
narrow face plus writes. Here neither face contains the other: the purger has
`purge`, which the provisioner must not have (or the engine could purge an
installation from a client), and the provisioner has four members the purger must
not have. Two disjoint faces over one implementation is the honest declaration, and
what a consumer holds is then decided by what the composition root hands it rather
than by a subset relation between two Protocols.

### 3. Where the purge sits in the act, and what every interruption leaves

> **Normative.** The act invokes `ConnectionPurger.purge` **after** the owner's
> confirmation (ADR-0126 §7) and **before** the first destruction of any entry in
> `data_dir`. It is not invoked before the confirmation, because it destroys Tier 0
> data and ADR-0126 §7 rules that the act destroys nothing until the owner confirms.

> **Normative.** Every refusal-producing check of ADR-0126 §1 — the descendant
> mount-point refusal, the refusal when mount points cannot be enumerated, and the
> removability preflight — runs and passes **before** the purge is invoked, so a
> refusal costs the owner nothing and leaves the keyring exactly as it was.

> **Normative.** The act reads the live connections through
> `ConnectionPurger.connected` **before** it makes ADR-0126 §7's first statement,
> and holds what it read for the restatement afterwards (§5). It re-reads nothing
> after the purge.

> **Normative.** The act holds the instance lock across the purge, as it does
> across every other step (ADR-0126 §5). That is what discharges ADR-0149 §8's
> sixth clause: nothing can start a hub, so no provisioning act is concurrent with
> the purge.

> **Normative.** ADR-0126 §5's ordering inside `data_dir` is unchanged. `devices.db`
> is still the **first entry the act destroys**, and its sidecars still follow it
> before any other entry. The purge is not a destruction of an entry in `data_dir`
> and does not displace that ordering; it precedes the whole of it.

> **Normative.** Whatever the act opens in order to reach the purge — the
> connection store, and the objects the composition root builds around it — is
> **closed before the first destruction begins**. The act does not destroy a file it
> is holding open.

**The order is forced at both ends, and the two ends are forced by different
rules.** It is after the confirmation because ADR-0126 §7 admits no destruction
before one and a keyring deletion is a destruction. It is before the first
destruction because the connection store lives in `data_dir` and is the only index
into the keyring — the trap the Context names, and ADR-0149 §8's fifth clause
stated as an obligation on any component discharging the delete right.

**Putting it after the preflights costs nothing and buys the whole refusal path.**
The shipped act already refuses on a descendant mount point and on an unremovable
directory before it confirms, and `lost+found` makes the second a real case rather
than a theoretical one. An implementation that purged the keyring first and then hit
that refusal would leave an owner with every credential deleted, every byte of data
intact, and a diagnostic about a directory mode — which is a worse outcome than
either completing or refusing.

**Closing the store before the destruction is where the obvious implementation goes
wrong**, and it is ADR-0126 §2's own central argument arriving one layer down: "A
running hub cannot delete the directory it is holding open … unlinking their files
under a live process leaves a hub writing to descriptors whose paths are gone."
An act that held the connection store open across `_destroy` would be doing exactly
that to itself, in a tool whose entire premise is that nothing else is.

**Every reachable partial state, and what each leaves.** ADR-0148 §6 and ADR-0149
§5 each name what their crash windows leave rather than claiming atomicity, and
this act claims none either (ADR-0126 §5's third clause). Read in order, the
windows are:

- **Interrupted during the purge**, some slots deleted. The connection store still
  names every slot, the deleted ones included, because ADR-0149 §8's third clause
  keeps the entries in place until every slot is confirmed. `delete` raises nothing
  for an absent entry (ADR-0125 §4), so a re-run deletes the remainder and confirms
  the rest. **Nothing is orphaned; `data_dir` is untouched; every enrolment is still
  live.** The owner re-runs the command.
- **Interrupted after the purge, before the first destruction.** The keyring holds
  no `INTEGRATION` entry for this installation; `data_dir` is intact, including a
  connection store with no entries. A re-run purges nothing and destroys everything.
  **Nothing is orphaned; every enrolment is still live**, which is correct because
  ADR-0126 §5's guarantee is about what survives the first *destruction* and none has
  happened.
- **Interrupted after `devices.db` and before the rest.** ADR-0126 §5's existing
  state, unchanged: no enrolment is live and everything that survives is data no
  device can reach — and now, additionally, no integration credential survives. The
  owner re-runs.
- **Interrupted anywhere later.** ADR-0126 §1's best-effort continuation, unchanged.

**The state this ordering makes unreachable is the one the Context names**, and it
is worth stating as the negative because it is the only one a re-run cannot repair:
there is no reachable interruption after which the connection store is gone and a
slot it named survives. The store is destroyed only by `_destroy`, `_destroy` runs
only after `purge` returned, and `purge` returns only having confirmed every slot.

### 4. A failed purge destroys nothing, and no argument widens the act

> **Normative.** Where `ConnectionPurger.purge` raises for any reason, the act
> **destroys nothing**, reports the failure with a diagnostic naming the condition,
> and exits with a failure status classified as every other refusal of this act is
> (`classify`, in `ai_assistant.service.exits`). It does not continue on a best-effort
> basis, and it does not destroy `data_dir` while leaving the connection store.

> **Normative.** A failure to read the connection store at all — through `connected`
> or inside `purge` — is treated identically: the act destroys nothing and reports.
> An unreadable index is the case in which proceeding guarantees the unrepairable
> state rather than risking it.

> **Normative.** No argument, flag, environment variable or `Settings` value lets
> the act proceed past a failed or unavailable purge, skip it, or run without it.
> ADR-0126 §11's first replacement — one purpose and one path, "with no argument
> that widens it" — binds this step, and an override would be that argument
> exactly.

> **Normative.** The act does **not** treat an unavailable keyring as an absent
> one. `SecretStoreUnavailableError` is a failure of the purge and is reported as
> the deployment condition it is (ADR-0125 §7), never as "there was nothing to
> purge".

**Refusing whole is ADR-0126 §1's own instrument, applied where it matters most.**
That section already refuses before destroying anything on a mount point and on an
unremovable directory, and already carves `devices.db` out of best-effort
continuation because for that one entry "the safe failure is to have destroyed
nothing". The connection store is the second such entry and for a stronger reason:
a failed `devices.db` leaves a state the owner can re-run out of, and a destroyed
index leaves one nobody can.

**The installation that never provisioned a connection is unaffected, which is
what keeps this from blocking the delete right in general.** ADR-0125 §7 rules that
"Constructing an implementation touches no keyring. The backend is resolved on the
first call." A purge over a store that names no slot makes no keyring call, so it
cannot fail on an absent, locked or backendless keyring. Every installation shipped
to date is in that population, and a headless box with no keyring at all — #879's
box — runs this act exactly as it does today.

**Where the store *does* name slots, the keyring is one the owner used**, so a
failure there is a condition of their own machine that they can clear: unlock it,
start the agent, re-run. That is ADR-0125 §7's stated posture — "the fault is
legible until they do" — and the same one ADR-0084 §9 takes for a hub that is down.

**The residue is real and is named rather than smoothed over.** An installation
whose keyring backend has become permanently unavailable, or whose connection store
cannot be read, cannot complete this act, and this ADR supplies no override. Three
things bound it. The owner's data right is not extinguished — deleting the directory
is something they can do at their own machine with their own tools, which is where
ADR-0126 §11 already locates custody. ADR-0149 §8's third clause is what forbids
the purge to proceed past a raising deletion, and relaxing that is that ADR's to do,
not this one's. And an override would be a flag whose only function is to
manufacture the one state the whole section exists to prevent, which is not a
remedy the owner would choose if the flag's help text were honest about it.

### 5. The report is stated scope by scope, and the connections are named before

> **Normative.** ADR-0126 §7's first statement, made before anything is destroyed
> and before the confirmation, states for **each member of `SecretScope`** whether
> this act reaches that scope, and where it does not, why not and what the owner
> must do instead. A scope the act does not reach is stated as not reached; a scope
> it reaches is stated as reached, in the terms the clauses below fix.

> **Normative.** For `INTEGRATION` the statement says the act deletes every
> credential this installation's connection store names, and names each live
> connection by its **connection reference** and its **account identity** as the
> record holds them. That list is complete: every live record, with no bound, no
> page and no omission count, for ADR-0126 §7's reason.

> **Normative.** The statement says, in the same place, that deleting a credential
> here **does not revoke it at the service that issued it**, and that revoking it
> is an act at that service. The act may not present the removal of a local
> credential as the withdrawal of an authorisation held elsewhere.

> **Normative.** For `PROVIDER` the statement is unchanged: the credential the
> operator holds in their environment or a shell profile is not in the keyring, is
> not in `data_dir`, and is not removed by this act (ADR-0126 §6's fourth clause,
> which stands whole). For `ENROLMENT` the statement is unchanged: the act reaches
> nothing on an enrolled device, and ADR-0126 §7's device list and the act at each
> device carry it.

> **Normative.** The report **may not describe a keyring as swept**, and ADR-0126
> §6's fourth clause is unchanged in that limb: nothing enumerates, and what the act
> deletes is the set of names the connection store recorded. It may not describe
> Tier 0 as purged, because `PROVIDER` and `ENROLMENT` are not.

> **Normative.** After the act, the restatement repeats the connection list and the
> non-revocation sentence from what was read before the purge (§3), so a session
> scrolled past the first statement still carries what the owner must do next. It
> re-reads nothing; the store it would read is gone.

> **Normative.** No `SecretName`, credential slot or credential value appears in
> either statement, and neither statement is a log line: ADR-0004 §5's logging rule
> and ADR-0149 §3's rule that no log, error or operator diagnostic carries an account
> identity are untouched, and no implementation routes these statements through
> `structlog`.

**Stating the scopes one by one is what makes ADR-0125 §5's second clause
checkable.** That clause — "No lane may present a purge that skips a scope as
complete" — is today a sentence a report can satisfy by saying nothing about a
scope. A report indexed by `SecretScope`'s closed enum cannot: every member owes a
row, and a member added by a future ADR (which ADR-0125 §2 requires to be a
contract decision) is a row the report owes without this section being edited
again. That is the same instrument ADR-0125 §11 used to bind its suite to §6's
list of derivations rather than to a copy of it.

**Naming the connections is ADR-0126 §7's device argument, and the parallel is
exact.** The device list is stated first and completely because "the record naming
the devices is gone" afterwards and the owner must visit each one. The connection
list is in identical case: the store naming the accounts is destroyed by the same
act, and the owner must go to each service and revoke. A report composed afterwards
would name nothing, which is the failure §7 exists to prevent, arriving at a second
custodian.

**Naming the *identity* rather than only the reference is what makes the list
usable.** ADR-0151 §3 makes the reference a minted handle; ADR-0148 §6 makes the
identity "the durable, user-recognisable name of the account itself". An owner
holding a list of minted identifiers cannot act on it. Both are non-secret — the
reference by ADR-0149 §3 and the identity by ADR-0148 §6, which binds it as one of
two "non-secret facts" — so naming both discloses nothing the record did not
already hold in a Tier 1 store.

**Only *live* connections are named, and superseded or removed ones are purged
silently.** The purge deletes every slot the store names, including those of
superseded and removed entries (ADR-0149 §8's first clause, ADR-0149 §5's deletion
pass), and that is right — an unreferenced slot is still a credential. But an
account the owner already disconnected is one they have already dealt with, and
listing it back at them under "accounts you must still revoke" would restate a
completed decision as an outstanding obligation. The list answers "what is still
connected", which is the question the owner is about to lose the ability to ask.

**The non-revocation sentence is the honesty obligation this section adds, and it
is the one an implementation would most naturally omit.** Deleting an OAuth refresh
token from a keyring does not revoke it at the issuer; the token stays live until
someone revokes it there. ADR-0126 §7's clause forbidding the act to "present
itself as having purged everything" reaches that squarely, and this is the same
instrument ADR-0126 §6 already used for the environment-held provider key — "say
what was not purged, and say what the owner must do about it". What the act cannot
supply is the *act at each service*, the way ADR-0126 §7 supplies one per device:
no integration exists, ADR-0017 §3's egress seam is undesignated, and this system
holds no endpoint it is entitled to name. So the statement names the accounts and
the obligation, and does not invent a URL.

### 6. What `service` still does not hold, and what it now does

> **Normative.** `service` holds **neither face of ADR-0125's seam**. It names
> neither `Secrets` nor `SecretStore`, cannot name `get`, `set` or `delete`, and no
> annotation anywhere in `ai_assistant/service/` mentions either Protocol.
> ADR-0125 §8's fourth clause stays true of `service` word for word, and this ADR
> seeks no exemption from it and adds no member to `SecretScope`.

> **Normative.** The act **enumerates nothing**. ADR-0125 §5 is obeyed rather than
> narrowed: the slots the purge deletes are the names the connection store recorded,
> which is ADR-0125 §5's own prescribed composition — "composed from the names its
> holders know" — and no listing member exists on either keyring Protocol or on
> `KeyringBackend` to do otherwise.

> **Normative.** The act performs **no keyring operation directly**. What it does is
> invoke one member of one Protocol whose implementation performs them, which
> ADR-0149 §8's tenth clause rules is not holding a keyring face. What is superseded
> of ADR-0126 §6's first clause is exactly its first two sentences, and exactly as
> they reach that invocation (§10).

> **Normative.** `service` imports no subsystem directly. It reaches
> `ConnectionPurger` as a Protocol in `core`, receives the implementation by
> injection from `app` (which ADR-0083 §8 permits `service` to import), and imports
> no module of `tools/` (golden rule 1). ADR-0126 §3's first clause is unchanged.

**This is the section that shows the supersession is narrow rather than the whole
of §6.** ADR-0126 §6's first clause is four assertions in one sentence, and three of
them survive: `service` holds neither face, nothing is enumerated, and no exemption
is sought under ADR-0125 §2. What gives way is "The act reaches no keyring" and
"performs no keyring operation", and only in the sense of *causing* one across a
seam that ADR-0149 §8 already ruled is not a face.

**ADR-0149 §8's tenth clause is doing real work here and it is not a formality.**
It says holding the routing seam "gives no component a face ADR-0125 §8 keeps out
of the seam, and no lane cites the routing as acquiring one" — which is the
distinction ADR-0102 §7 drew about a composition root and `SourceGrantStore`, and
ADR-0151 §10 relied on for `orchestration`. Without it, this decision would be
seeking ADR-0125 §2's fourth-scope exemption for `service`, which ADR-0126 §6's
last sentence explicitly declined to seek and which would be a much larger change
than a routing.

### 7. Exactly which `core` names change

This section is a classification of the change being made and is not normative
(ADR-0089 §1). The obligations are in the sections it points at.

| Name | Where | What |
|---|---|---|
| `ConnectionPurger` | `core/protocols.py`, new | Two members, `connected` and `purge`. The seam by which the offline delete act reaches ADR-0149 §8's purge (§2). |
| `ConnectedAccount` | — | **Not this ADR's.** ADR-0151 §4 promotes it. `ConnectionPurger.connected` returns it unchanged; no field is added, removed or reinterpreted, and §2 says why it is reused rather than a narrower type minted. |
| `ConnectionProvisioner` | — | **Unchanged.** ADR-0151 §10's five members stand. No purge member is added (§2). |
| `Secrets`, `SecretStore` | — | **Unchanged.** No signature changes, no member added, and no listing member (ADR-0125 §1, §5). |
| `SecretScope` | — | **Unchanged.** No fourth member (ADR-0125 §2). |
| `AssistantEngine` | — | **Unchanged.** No method is added for this act, which is ADR-0126 §2's prohibition standing rather than a choice made here. |
| `core/types.py` | — | **Unchanged.** No type, no constant, no enum member. |
| `core/errors.py` | — | **Unchanged.** The failures §4 governs are `SecretStoreError`, `SecretStoreUnavailableError` (ADR-0125 §6) and `ConnectionStoreError` (ADR-0151 §2a), all of which exist or are already claimed. |
| `PROTOCOL_VERSION` | — | **Unchanged.** |

> **Normative.** The `core` names this ADR authorises a lane to add or change are
> exactly one: the new Protocol `ConnectionPurger` in `core/protocols.py`, with the
> two members §2 declares and no others. No type, constant or enum member is added
> to `core/types.py`; no class is added to `core/errors.py`; no member is added to
> `ConnectionProvisioner`, `Secrets`, `SecretStore` or `AssistantEngine`; no member
> is added to `SecretScope`; and `PROTOCOL_VERSION` is unchanged. A change beyond
> this list is a change to this decision and needs its own ADR (golden rule 5).

**The version rule is examined and found unmet, in the pattern ADR-0084 §12 set
and ADR-0123 §11, ADR-0126 §8 and ADR-0151 each followed.** ADR-0124 §9 bumps
`PROTOCOL_VERSION` for a change to the encoding of a wire-carried value, a change
to a wire-carried `core` type, or any change to the promoted surface's method set
or a method's arguments or results. This adds a Protocol reached in-process by an
offline console script. No frame changes, no wire-carried type changes, and the
promoted surface is untouched — which follows from ADR-0126 §2's prohibition rather
than from a coincidence.

**The name intersects nothing.** It is checked against ADR-0150 §2's binding
family (`DestinationProtocol`, `DiscloserProvenance`, `EgressDestination`,
`CanonicalDestination`, `EgressSpan`, `BoundAccount`, `EgressBinding`), against
ADR-0151's provisioner family (`ConnectionProvisioner`, `ProvisioningState`,
`ConnectedAccount`, `ConnectionAct`, `ACCOUNT_IDENTITY_MAX_BYTES`,
`CONNECTION_REFERENCE_MAX_BYTES` and its seven error classes), and against the
tree, where `grep` over `core/` finds no `Connection`-prefixed symbol at all. It is
on the **`service`→`tools`** boundary, which no other in-flight decision reaches.

### 8. What this discharges, what it adds, and the order the lanes land in

> **Normative.** ADR-0126 §6's last clause is **discharged**. This ADR is the
> decision it required, and its prohibition — "Until that decision lands, this ADR
> authorises no such entry to be written" — lapses on its own terms **for the
> `INTEGRATION` scope only**, on this ADR merging.

> **Normative.** For every other scope that clause stays live and unrelaxed. A lane
> that gives a component on the hub's machine a `PROVIDER` keyring entry, or an
> entry under a scope member a future ADR adds, owes its own routing decision under
> that clause, and no lane cites this ADR as having answered it. §2's purge is
> scope-confined by construction (ADR-0149 §8's seventh clause) and reaches no
> scope but `INTEGRATION`.

> **Normative.** ADR-0149 §8's precondition — "No lane provisions a connection in an
> installation before a ratified decision routes the owner's delete right to that
> purge" — is **discharged** by this ADR merging, which is the condition that clause
> states.

> **Normative.** One precondition replaces it, and it is about implementation
> rather than ratification: **no lane makes a connect or re-provision operation
> reachable in an installation before the routing §3 requires is present in
> `ai_assistant/service/purge.py`.** Whether that is one lane or two is the
> dispatcher's, provided the order holds. Until it does, an installation could
> acquire an `INTEGRATION` credential that its shipped delete act does not reach,
> which is the state ADR-0126 §6 forbids arriving one lane later.

> **Normative.** `ConnectionPurger`'s triad — the Protocol, its shared conformance
> suite, and a canonical fake in `ai_assistant.testing` with the concrete
> `Test…Contract` subclass — lands with its **primary production implementation**,
> the provisioner in `tools/`, as one unit of work (ADR-0137 §2, `CONTRIBUTING.md`
> → "Adding a Protocol"). No lane splits the triad, and no lane lands the Protocol
> ahead of an implementation.

> **Normative.** That triad rides in the lane ADR-0151 §15 names, because that lane
> builds the provisioner and the provisioner is this Protocol's implementation.
> ADR-0151 §15's enumeration is not narrowed, contradicted or re-opened: everything
> it lists still lands in one lane and one PR, and this adds a second Protocol and
> its triad to the same one.

> **Normative.** The conformance suite proves, at minimum: `connected` returns
> every live record and no reference whose latest entry is a removal; `purge` over
> a store naming no slot completes and touches no keyring; `purge` deletes every
> distinct slot the store names including a superseded one and a removed one, then
> removes the entries; a `purge` whose slot deletion raises leaves **every** entry
> in place and re-raises; `purge` is idempotent, so a second call after a failure
> completes and a second call after a success does nothing and raises nothing; the
> subject satisfies `ConnectionPurger` by `isinstance`; and no credential value,
> `SecretName` or slot appears in any return value or in any error the subject
> raises.

> **Normative.** The **routing lane** pins §3's and §4's obligations against
> `ai-assistant-purge` itself, and the conformance suite above does not discharge
> them: a suite binds implementations of `ConnectionPurger` and cannot reach the
> act. Driving the act with a purger that raises is deterministic, so these are
> ordinary tests rather than an integration burden. It pins, at minimum: a
> `connected` that raises leaves **every** entry in `data_dir` present, including
> `devices.db`, and the act exits with a failure status whose diagnostic names the
> condition; a `purge` that raises after the confirmation does the same; a `purge`
> that raises is followed by no destruction of any kind, best-effort included; a
> completed `purge` is followed by ADR-0126 §5's ordering unchanged, with
> `devices.db` the first entry destroyed; the connection store and everything opened
> to reach it are closed before the first destruction; every refusal-producing check
> of ADR-0126 §1 refuses without the purge having been invoked at all; and the
> statement made before the confirmation carries a row per `SecretScope` member and
> every live connection's reference and identity.

**The second clause exists because the first cannot reach the failure that
matters.** §4's obligations are on the act, not on the seam, and a conformance
suite is bound to subjects that satisfy the Protocol. An implementation whose
`purge` raised and which then destroyed `data_dir` anyway would pass every
obligation the suite above carries while producing exactly the unrepairable state
this ADR exists to prevent — which is the gap ADR-0149 §8 found in its own earlier
draft, where "slots before the store" was satisfied by a purge that destroyed the
store after a deletion raised. The repair is the same instrument: name the failure
path as a test obligation on the lane that owns the code the failure lives in.

**Discharging the precondition by ratification is what ADR-0149 §8's clause
literally says, and the implementation precondition is what makes it honest.**
That clause is worded around a *ratified decision* because the alternative — waiting
for an implementation — would have held the provisioner lane hostage to a delete act
that did not exist when it was written. The act exists now, so the honest reading is
that ratification unblocks the *contract* and the shipped routing unblocks the
*installation*, and the second clause above says so rather than leaving a lane to
infer it.

**The residue between the two is bounded and is worth naming.** A connection
provisioned before the routing ships would be reachable by ADR-0151 §2's
`disconnect_account`, which deletes every slot for that reference (ADR-0149 §5's
deletion pass) — so the owner has a per-connection removal path from the day the
provisioner ships, and what waits on the routing is the whole-installation act. The
precondition above means that residue is never entered, and the per-connection path
is why it would be survivable if it were.

**Keeping the scope-by-scope prohibition alive is the clause a later lane is most
likely to misread.** ADR-0126 §6's forward clause is naturally read as one gate that
one decision opens. It is not: it is a gate per keyring entry class, and this
decision routes exactly one. A lane moving the provider credential into the keyring
under #74 would find `service` still holding no face, the purge still bound to
`INTEGRATION`, and nothing composed for `PROVIDER` — and §5's scope-by-scope report
is what keeps that visible to the owner in the meantime.

### 9. What this does not decide

> **Normative.** This ADR decides nothing about **per-connection removal**.
> ADR-0149 §5 and ADR-0151 §8's `disconnect_account` are unchanged, this act is not
> a disconnection, and it appends no removal entry and takes no revision: it
> destroys the store rather than recording in it (ADR-0149 §8's sixth clause, whose
> "no revision cutoff" this act relies on).

> **Normative.** This ADR does not close **#74** and does not move the provider
> credential. ADR-0126 §6's supersession of ADR-0004 §6 for a Tier 0 credential held
> outside the keyring stands exactly as ratified, including its self-limiting clause,
> and ADR-0125 §8's finding that the environment read is pre-existing and unauthorised
> is untouched.

> **Normative.** This ADR reaches **no backup artifact**. ADR-0126 §10's clause
> stands, ADR-0125 §12 already records that a backup carries no keyring entry, and
> the case of a restored store naming slots the keyring does not hold is already
> answered without a new rule: `delete` returns `False` for an absent entry
> (ADR-0125 §4), which the purge treats as confirmed absent (ADR-0149 §8's fourth
> clause), and ADR-0149 §6 governs an active record over an empty slot.

> **Normative.** This ADR designates no seam under ADR-0017 §3, discharges none of
> its conditions, and authorises no transmission. It opens no network connection and
> the purge performs no I/O beyond the keyring and the connection store (ADR-0149
> §1).

> **Normative.** This ADR does not fire either of ADR-0101 §7's conditions and is
> not ADR-0101 §1's subject-scoped erasure, for the reason ADR-0126 §10 already
> gives. It decides no retention rule and authorises no scheduled or automatic
> invocation of the act (ADR-0126 §10, unchanged).

> **Normative.** This ADR does not foreclose a future in-session delete surface. It
> refuses a *split* act (§1); an ADR that later gives the whole act an in-session
> form owes what ADR-0126 §3 already names — a way for the promoted surface to be
> reachable from loopback and not from the remote listener — and would then decide
> this routing again for that form.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in this ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds? Every ADR
this one relies on was read for **what it is relied on for**, which is ADR-0084
§12's semantic method rather than a phrase search.

**Six limbs of ADR-0126 are partially superseded**, recorded on its `Status` line —
which carries no leading token today and therefore takes one (ADR-0082 §2) — and in
its appended dated note. Both halves are written **in the ratification commit and
not before**, for the reason the header bullet gives; the exact text of each is
below, so it is reviewable while this ADR is `Proposed`. Six is the honest count
because ADR-0126 asserted its no-keyring premise in six places, which is itself the
measure of how load-bearing that premise was. Each limb is one sentence-fragment,
each is narrowed to the `INTEGRATION` scope and to §2's seam, and none of them
changes what the act destroys inside `data_dir`.

The `Status` line, replacing ADR-0126's `- Status: Accepted` and leaving its
separate `- Accepted: 2026-08-10` line untouched:

```text
- Status: Partially superseded by ADR-0153 (§3's cross-boundary-injection clause,
  §6's first and second clauses, §7's "no keyring is reached" limb, §8's
  `core/protocols.py` limb and §11's "destroying the resolved `data_dir` and
  nothing else" limb — each only as this act reaches ADR-0149 §8's `INTEGRATION`
  purge)
```

The dated note, appended after that line and before ADR-0126's existing header
bullets:

```text
- Partially superseded: <ratification date> by ADR-0153 — **six limbs, one scope,
  one seam, and the forward clause that asked for this is discharged for
  `INTEGRATION` alone.** §6's last clause bound "the lane that first gives a
  component on the hub's machine a Tier 0 keyring entry" to decide how a hub-side
  delete reaches it. ADR-0149 §1 is that component, ADR-0149 §8 supplied the purge
  and left the coordinator open, and ADR-0153 routes this act to it.

  **Replaced — §6's first clause, its first two sentences only.** "The act reaches
  no keyring" and "performs no keyring operation". The act now invokes
  `ConnectionPurger.purge` (ADR-0153 §2) after the owner's confirmation and before
  the first destruction of any entry in `data_dir` (ADR-0153 §3).

  **Replaced — §6's second clause.** "No component of this system writes a Tier 0
  keyring entry on the hub's machine today, so the act misses no keyring entry."
  Its premise is what ADR-0149 §1 makes false.

  **Replaced — §3's second clause, one limb.** "or across any package boundary for
  this act". The act receives a `ConnectionPurger` by injection from `app`. Its
  other limb — "No callback is injected into `Engine`" — stands absolutely, and
  #903's expected seam is still not built.

  **Replaced — §7's first clause, one limb.** "that no keyring is reached". Every
  other limb stands, and ADR-0153 §5 extends the statement rather than replacing
  it: a row per `SecretScope` member, the live connections named by reference and
  identity, and the sentence that deleting a credential here does not revoke it at
  the service that issued it.

  **Replaced — §8's first clause, one limb.** "No Protocol in `core/protocols.py`
  changes". One is added — `ConnectionPurger`, two members. The clause's other
  limbs stand: nothing is added to `core/types.py` and `PROTOCOL_VERSION` is
  unchanged.

  **Replaced — §11's second clause, one limb.** "destroying the resolved `data_dir`
  and nothing else". The act also deletes the `INTEGRATION` credential slots that
  directory's own store names. The rest of that replacement stands and ADR-0153 §4
  binds the new step to it — one purpose, one path, no argument that widens it, the
  operating system's own custody, the kernel's lock, and the owner's confirmation
  against the resolved path.

  **Not replaced — everything else, which is nearly all of all five sections and
  the whole of the rest of the ADR.** The act still holds neither face of ADR-0125's
  seam, still enumerates nothing, and still seeks no exemption under ADR-0125 §2.
  §6's supersession of ADR-0004 §6 for the environment-held provider credential
  stands whole, self-limiting clause included, and §6's `ENROLMENT` clause stands.
  §1's destruction rules, §2's placement and its four prohibitions, §5's ordering
  and lock, §9's prerequisite, §10's five exclusions and §12's records are all
  untouched — ADR-0153 §10 applies ADR-0070 §1's test to each and shows why.
```

**ADR-0126 §6, first clause — "The act reaches no keyring" and "performs no keyring
operation".** ADR-0070 §1's test: a reader holding only §6 would build the shipped
act with no route to a keyring at all, and on being handed a `ConnectionPurger`
would refuse it as forbidden. That is the first limb met. **Not replaced**: "It
holds neither face of ADR-0125's seam" (§6 above), "and enumerates nothing" (§6
above), and the whole of the sentence declining ADR-0125 §2's exemption.

**ADR-0126 §6, second clause — "so the act misses no keyring entry".** Its premise
is that no component writes a hub-side Tier 0 keyring entry, which is true today and
which ADR-0149 §1 makes false for the provisioner. A reader holding only this clause
would ship a delete act that misses every integration credential and believe it
missed none. **Not replaced**: the clause's own distinction between a statement about
the keyring and a statement about Tier 0, which §5's scope-by-scope report carries
forward rather than discards.

**ADR-0126 §3, second clause — "or across any package boundary for this act".** A
reader holding only §3 would build the act with no injected dependency crossing a
package boundary, and after this ADR one does. **Not replaced**: "No callback is
injected into `Engine`", which stands absolutely — the engine is not running, is not
involved, and gains nothing; and #903's expected seam is still not built, because
what crosses here is a Protocol the act consumes, not a callback into the engine.
**Not replaced**: §3's first clause whole, including "it needs no callback, no
injection point and no new contract to do so", which is scoped by its own words to
reaching the enrolment record and the instance lock and stays true of both.

**ADR-0126 §7, first clause — the limb "that no keyring is reached".** A reader
holding only §7 would print that sentence in the pre-act statement, and it would be
false. **Not replaced**: every other limb of that clause — the resolved `data_dir`,
the complete device list by overlay identity, the act at each device, the statement
that a hub-side delete cannot reach any of them, the environment-held provider
credential, and the backup artifact — all of which §5 keeps and extends rather than
replaces. **Not replaced**: §7's remaining six clauses, including the confirmation
against the resolved path, the completeness of the device list, the refusal to create
the enrolment record in order to report on it, and the three things the report may
not claim.

**ADR-0126 §8, first clause — the limb "No Protocol in `core/protocols.py`
changes".** A reader holding only §8 would build the act asking for no contract
surface and would treat one as out of bounds. **Not replaced**: "No type, enum member
or constant is added to `core/types.py`", which this ADR also adds none of;
"`PROTOCOL_VERSION` is unchanged", which §7 checks and confirms; and §8's second and
third clauses whole — no engine method, no wire operation, no CLI command, no
`admin.sock` act, no ADR-0017 §3 designation, no boundary added to ADR-0124 §1's
enumeration, and no network connection.

**ADR-0126 §11, second clause — the limb "destroying the resolved `data_dir` and
nothing else".** A reader holding only §11 would read the act's confinement as
bounded by the directory, and after this ADR it also deletes the `INTEGRATION`
credential slots that directory's own store names. **Not replaced**: the rest of that
replacement, which is what makes the ADR-0004 §7 exemption earned — one purpose, one
path, no argument that widens it (§4 binds the new step to it), the operating
system's own access control, the owner-only data directory, the kernel's instance
lock, and the owner's confirmation against the resolved path taken in person before
anything is destroyed. **Not replaced**: §11's first, third and fourth clauses whole
— the exemption reaches this act and no other, no record of the act survives inside
this system, and ADR-0124 §6's exemption is neither cited nor widened. The step this
ADR adds writes no audit record and leaves none.

**ADR-0126 §1, §2, §5, §9, §10 and §12 — no record owed**, and each is checked
rather than assumed.

- **§1.** Every clause is about what the act destroys *inside* `data_dir`, and none
  of them is made false: the unit is still the directory, the exception is still the
  lock file alone, symbolic links are still destroyed as links, the mount and
  removability refusals still bind (§3 requires them to run first), the best-effort
  continuation and the `devices.db` carve-out are unchanged, and the successful
  end-state is unchanged. §1's "it opens no store to empty it" is a statement about
  how the act discharges the *destruction* — that it is not a set of per-store
  `clear` calls — and it stays true: the act opens no store, the entry removal
  happens inside the provisioner behind a seam, and the store file is destroyed by the
  directory destruction like every other entry. A reader acts identically. Stacked
  addition.
- **§2.** All four clauses stand and §1 above restates two of them for this step:
  the act is still an offline console entry point in `service/`, still takes the lock
  and refuses when something holds it, still is carried by no socket act, engine
  method or wire operation, and is still never performed, scheduled or triggered by
  the hub.
- **§5.** Unchanged and relied on. `devices.db` is still the first entry the act
  destroys and the sidecars still follow it before any other entry, because the purge
  is not the destruction of an entry in `data_dir`; the lock is still held from before
  the first destruction until after the last, and §3 extends the hold backwards over
  the purge, which strengthens the guarantee rather than narrowing it; and the third
  clause's disclaimer that the act is not atomic against a crash is what §3's window
  enumeration follows.
- **§9.** Its prerequisite is met rather than changed: `assistant device unenrol`
  ships, the report names it, and this ADR neither descopes nor redesigns it.
- **§10.** Every clause stands, and §9 above restates the two a reader might think
  this ADR reaches.
- **§12.** A record of records; nothing in it becomes false. Its ADR-0004 §6 bullet
  already says **#909** "is the separate question of how the act would reach one
  there, and it is not this record" — which is this ADR, arriving where that bullet
  said it would.

**ADR-0125 §5 and §8 — no record owed, and §6 above is written to keep it that
way.** §5's marked clauses are obeyed rather than narrowed: nothing enumerates, the
purge is composed from recorded names, and §5's report clause is not merely honoured
but made mechanically checkable by §5 above. §8's fourth clause is that `service`
holds neither face, and it stays true word for word — the act names neither Protocol
and cannot name a keyring method (§6 above). This is the same treatment ADR-0126 §12
records for these two sections and ADR-0149 §12 records again, and it is unchanged
here.

**ADR-0149 §8 — no record owed.** Every clause is consumed exactly as ratified. Its
first, second, third, fourth and seventh clauses are the purge's mechanism and are
untouched. Its fifth clause — no component destroys the connection store while any
slot is unconfirmed — is what §3 and §4 above implement. Its sixth clause's
coordinator obligation is discharged by the instance lock, in the form that clause
itself calls trivial. Its eighth clause required a coordinator outside `tools/` to
reach the purge "through a Protocol in `core/protocols.py`", and §2 declares exactly
that; its ninth clause reserved the choice between a seam of its own and a member of
ADR-0151 §10's Protocol, and §2 takes the first of the two options it offered. Its
tenth clause is relied on and restated. Its eleventh clause — "This ADR does not
route ADR-0126's act to that purge … (**#909**)" — stays true of ADR-0149; this ADR
does the routing, which is what that clause said would happen elsewhere. Its twelfth
clause is discharged by §8 above, on the condition that clause states. A reader
holding only ADR-0149 acts identically. Stacked addition.

**ADR-0151 §10, §14 and §15 — no record owed.** §10's five members are unchanged
and §2 adds none. §14's first clause says ADR-0151 does not decide who invokes the
purge and leaves it to #909, which stays true — this ADR is #909's answer, not a
change to ADR-0151. §14's second clause carries ADR-0149 §8's precondition forward
"unrelaxed"; §8 above discharges it on the condition ADR-0149 stated, and adds a
stricter implementation-ordering precondition in its place, so nothing ADR-0151 §14
required becomes easier. §14's third clause states that the five-member enumeration
"is not a bar" on a purge member and that #909 "stays free to add a member to it **or
to declare a seam of its own**"; §2 exercises the second freedom, which is the clause
working rather than being narrowed. §15's clause requires ADR-0151's surface to land
in one lane and one PR, and §8 above puts a second Protocol and its triad into that
same lane — the list stays complete for what it enumerates and everything on it still
lands together. A reader holding only ADR-0151 acts identically. Stacked addition.

**ADR-0148 §6, ADR-0004 §6 and §7, ADR-0083, ADR-0084, ADR-0102, ADR-0123 — no
record owed.** ADR-0148 §6's binding, ordering and compare-and-swap are about a
provisioning act and no clause of them reaches a purge. ADR-0004 §6's Tier 0 half
becomes *more* discharged rather than differently discharged: the keyring-held
`INTEGRATION` set now has a route, which is what §6 always granted and ADR-0126 §6
recorded as unmet mechanism rather than as a narrowed right. ADR-0004 §7 stays where
ADR-0126 §11 put it, narrowed for this act alone and against replacements §4 binds
the new step to. ADR-0083 §8's import rule is obeyed. ADR-0084 §5's split is
untouched — no client operation is added. ADR-0102's four grant operations are not
reached. ADR-0123's backup is untouched (§9).

### 11. Marking, review and ratification

This is a **marked** ADR under ADR-0089 §2: its marked clauses are the whole of
what it obligates, and unmarked text is read to determine what a marked clause
means and never supplies an obligation (ADR-0089 §3). §7's table and this section
are classifications of the change and are not normative (ADR-0089 §1).

Its required review set is **adversarial and architecture**, because it decides a
contract surface (`CONTRIBUTING.md` → "Stop when the required reviews are green").
It was drafted, reviewed and revised while `Proposed`; its status was flipped only
once both required reviews returned clean on one tree; and both were re-run on the
flipped tree, which `CONTRIBUTING.md` → "Finishing an ADR PR" step 3 obliges and
ADR-0130 §12 and ADR-0136 §7 each record as the route they took. Nothing implements
against this decision until this PR merges (ADR-0015 §5, golden rule 5).

## Consequences

- **ADR-0126 §6's forward clause is discharged for one scope and stays live for the
  rest**, so the hub may hold an `INTEGRATION` keyring entry and may still not hold a
  `PROVIDER` one. The blocked provisioning implementation is unblocked; #74's is not.
- **ADR-0149 §8's precondition lifts on this merging**, and a stricter one replaces
  it: the routing must be *in* `service/purge.py` before a connect operation is
  reachable in an installation (§8). A lane that ships the five operations without it
  breaches this ADR rather than merely falling short of a hope in it.
- **The delete act gains one step and one dependency**, and the dependency is a
  Protocol rather than a subsystem import, so `lint-imports`' "nothing imports the
  service" contract and golden rule 1 are both satisfied by the same shape that
  satisfies them everywhere else.
- **`core/protocols.py` gains a second connection Protocol**, which is one more than
  ADR-0149 §10 forecast when it named "a Protocol by which `orchestration` reaches
  the provisioner" and then corrected itself to say that was "not the whole of the
  contract surface this decision's neighbourhood will need". This is the rest of it,
  and the neighbourhood is now closed: two faces, two consumers, one implementation.
- **The report grows a scope table and a connection list**, which makes ADR-0125 §5's
  no-skipped-scope clause checkable for the first time and gives the owner the one
  thing they otherwise lose with the store — which accounts they must go and revoke.
- **An installation whose keyring is unreachable cannot complete the act** where its
  connection store names a slot, and no flag overrides that (§4). Installations with
  no connections — every one shipped to date, and every headless deployment — are
  unaffected, because a purge over an empty store makes no keyring call.
- **A hub-side, in-session delete stays foreclosed by ADR-0124 §6 rather than by this
  ADR**, and §9's last clause says what a later decision would owe. What this ADR
  forecloses is only the *split* act, and it does so because the unrepairable failure
  lives in the window between two commands.
- **Revisit if** the provider credential moves into the keyring (#74 — a second
  routing is then owed, not an extension of this one), if a fourth `SecretScope`
  member lands, if ADR-0149 §8's completeness clause is ever relaxed so that a partial
  purge becomes reportable, or if a decision gives the whole delete act an in-session
  form.

## Alternatives considered

**A sixth member on `ConnectionProvisioner`, held by the offline act.** The
cheapest answer, explicitly left available by ADR-0151 §14's third clause, and
refused because of what it hands over rather than what it costs: the offline
destructive tool would be able to name `provision`, `reprovision` and `disconnect`,
so the one component whose purpose is destroying an installation could create a
connection in one. It would also hand it four members whose ratified semantics —
ADR-0151 §7's outcomes, ADR-0148 §6's interleavings — are stated about a running hub
that this act requires to be stopped. ADR-0125 §1 and ADR-0149 §1 each paid for the
narrow face on the identical argument; this is the third time and the answer does not
change.

**The hub as coordinator, with the offline act unchanged.** ADR-0151 §14 priced
this as the cheaper seam and it is. It is refused in §1 on ADR-0126's own rejected
two-phase alternative, sharpened: the failure in the window between two commands is
not symmetric here, because an operator who runs only the offline delete destroys the
sole index into the keyring and produces the one state ADR-0149 §8's second clause
calls unrepairable. It also has to invent the quiesce ADR-0149 §8's sixth clause
requires, which the instance lock supplies for free on the other side.

**The purge walking the `INTEGRATION` scope directly through `secret_store`.** The
shape #909's own text lists first, and it is dead twice over rather than once.
ADR-0125 §5 refuses enumeration and no listing member exists on `Secrets`,
`SecretStore` or `KeyringBackend`, so there is nothing to walk; and ADR-0125 §8's
fourth clause forbids `service` either face, so there would be nothing to walk it
with. ADR-0126 §6 already worked this out and filed **#909** rather than seeking the
exemption, and nothing since has made it available.

**`purge` returning what it purged, instead of `connected` plus `purge`.** One
member instead of two, and the report composed from the return value. Refused for
ADR-0126 §7's reason exactly: a statement composed after the destruction is the one
a crash strands, and here the crash window is the purge itself. The owner must learn
which accounts to revoke *before* anything is deleted, and only a read before the act
can tell them.

**A narrower return type than `ConnectedAccount` — a reference-and-identity pair
minted here.** Cleaner in one sense: the report needs neither the state nor the
revision. Refused because it would put a second `core` type in `core/types.py` for a
projection of one that already exists, which §7's list would then have to
authorise; because ADR-0151 §4 already rules `ConnectedAccount` "the hub's live
connection record", which is precisely what `connected` answers with; and because a
second type would have to be kept in step with the first by hand. §5 bounds what the
statement *renders* instead, which is the cheaper half of the same discipline.

**An override flag for an unreachable keyring — `--skip-keyring`, or a
`--force`.** It would let an owner whose keyring backend is permanently gone still
exercise the delete right, which is a real cost §4 names rather than hides. Refused
because ADR-0126 §11's first replacement forbids "an argument that widens it" and the
ADR-0004 §7 exemption is granted against that replacement; because the flag's only
function is to manufacture the unrepairable state deliberately; and because the
owner's remedy for a directory they can no longer purge through this act is one they
hold outside this system, at their own machine, which is where ADR-0126 §11 already
locates custody.

**Destroying everything except the connection store when the purge fails.** A
middle path: honour ADR-0149 §8's fifth clause literally by preserving only the store,
and take the rest of the delete right. Refused because ADR-0126 §5 requires
`devices.db` to be destroyed first, so the act would revoke every enrolment and then
stop, leaving an installation with no enrolments, no data, one store file and a live
credential — a partial state with no ordering that recovers it, produced in service of
a right the owner can exercise more completely by clearing the keyring fault and
re-running.
