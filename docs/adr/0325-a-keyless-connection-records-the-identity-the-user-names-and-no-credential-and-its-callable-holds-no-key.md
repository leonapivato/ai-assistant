# 325. A keyless connection records the identity the user names and no credential, and its callable holds no key

- Status: Proposed
- Date: 2026-10-17
- Scope: `tools/`, the connection model: a connection shape for an outside source that needs no credential, reusable by every such source. Tracker: [#2396](https://github.com/leonapivato/ai-assistant/issues/2396), batch [#3113](https://github.com/leonapivato/ai-assistant/issues/3113).
- Dependency: ADR-0148, ADR-0149 and ADR-0151, as their status lines leave them, and ADR-0125, which this decision does not touch.
- Authorization: the dispatcher assigned 0325 for batch #3113 and scoped it to #2396's four points.
- **Changes `core`, so it is a contract-surface decision and a breaking change under `CLAUDE.md` golden rule 5.** `AssistantEngine` gains one method and `ConnectionProvisioner` one member (§5). No type, error class, constant or field in `core/types.py` or `core/errors.py` changes. The promoted method set changes, so `PROTOCOL_VERSION` advances (§5:4).
- **Partially supersedes**, each in the scope §7 states:
  [ADR-0148](0148-an-egress-call-is-authorised-as-one-whole-and-nothing-in-it-moves-after-the-ruling.md),
  [ADR-0149](0149-one-component-in-tools-provisions-a-connection-and-the-record-is-the-hubs.md) and
  [ADR-0151](0151-the-connection-surface-is-five-engine-operations-and-the-reference-is-minted.md).

## Context

**The gap.** Every connection this corpus admits carries a credential. A source that needs
no key at all cannot be registered, and three ratified texts close it from both ends:

- ADR-0148 §6:5's third pre-transmit condition has the callable read *"under the slot that
  record names"*, so a callable with nothing to read cannot meet it.
- ADR-0149 §4:2 has the identity supplied *"in the same act that supplies the credential"*,
  so a user with no credential would have to invent one, a false record in the connection
  store.
- The tree implements exactly that, at `origin/main` `abf4e206`.
  `tools/connection_store.py`'s `ConnectionEntry._is_one_shape_or_the_other` makes the
  identity, the state and the slot travel together. `tools/provisioning.py`'s
  `KeyringConnectionProvisioner._act`, which both `provision` and `reprovision` call,
  always mints a slot and writes the credential into it before the activation.
  `tools/egress_binder.py`'s `EgressBindingSeam._connectable_account` refuses a reference
  whose record is not `ACTIVE`. (#2396 names a `_provision` function in
  `tools/provisioning.py`; there is none now, and `_act` is the path it meant.)

**Where it came from.** ADR-0260 met the gap first and declined to close it: amending the
egress floor inside a decision about the weather was the ground both review lenses blocked
PR #2384 on. ADR-0260 §14 names Open-Meteo as the intended first real forecast provider and
gates it on #2396, and `tools/forecast.py` ships a reference provider that *"accepts a
credential and does not use it"* until then.

**What already holds and is used as given.** The binding carries the account's identity
and its connection reference, and no slot (ADR-0148 §6:2, §6:3, §6:9). Connectability is an
`ACTIVE` record (§6:16). The binder reads the record's connectability and identity and
nothing else (ADR-0152 §10), and `_connectable_account` never looks at the slot. Every
credentialed callable at the designated seam already refuses a record that names no slot:
the `_slot_of` methods in `tools/egress.py` and `tools/booking.py` refuse when
`entry.slot is None`. A tool receives a `Secrets` face by injection only where it needs one
(ADR-0125 §8).

**What #2396 proposed, and the one place it is tightened here.** #2396 had §6:5's third
condition read *"and it reads under the slot that record names, **where it names one**"*.
Read as written, that lets a **credentialed** callable handed a slotless record satisfy the
condition by reading nothing and then transmit with no credential. The code refuses that
case today, but the reworded clause would no longer require it to. §2 states the condition
over the callable's shape instead, so each shape refuses the other's record.

## Decision

We will admit a connection that the user makes by naming it, with no credential: one
`ACTIVE` record with no slot, written in one act. Its callable is built with no key and
refuses a record that has one, and a callable built with a key refuses a record that has
none. Nothing else in the egress floor moves.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the adversarial and architecture
> reviews `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree.

> **Normative.** No lane implements this decision until it has merged `Accepted`
> (ADR-0015 §5, golden rule 5).

### 2. The shape, and the callable's third condition

> **Normative.** A **keyless connection** is a connection whose live record carries an
> identity, the `ACTIVE` state and no credential slot. A **keyless integration** is one
> whose callable is constructed with no `Secrets` face.

> **Normative.** Whether an integration is keyless is fixed by its own code where the
> composition root constructs its callable. It is never read from a connection record, a
> binding, a `Settings` value or a remote answer.

> **Normative.** ADR-0148 §6:5's third condition reads: the connection reference the
> binding carries names the connection record the callable consults, and that record's shape
> is the callable's. A callable holding a `Secrets` face reads under the slot the record
> names and refuses a record that names none. A keyless callable reads no credential and
> refuses a record that names a slot.

> **Normative.** The other three conditions of ADR-0148 §6:5 bind every keyless callable
> unchanged: the bound reference is connectable, the endpoint the binding carries is the
> configured one, and the identity currently recorded for the reference equals the
> identity the binding carries.

> **Normative.** A keyless callable reads the identity, revision, state and slot recorded
> for the bound reference **once**, as the last read of that record before its first byte
> is transmitted, and refuses unless the four conditions hold against what that read
> returned. Nothing it
> decides is carried over from an earlier call, an earlier stage or the binding seam's own
> read.

> **Normative.** A provisioning act that lands after that read is ADR-0148 §6:21's case:
> it neither retracts the authorisation nor stops a transmission already begun, and no
> lane holds a lease or a lock from that read across the transport's write.

> **Normative.** ADR-0148 §1 to §5, §6:1 to §6:4, §6:6, §6:16 and §6:22 to §6:28, §7, §8
> and §9, as their status line leaves them, bind a call under a keyless connection exactly
> as they bind any other egress call. The binding gains no member and loses none.

**Why the callable's shape and not the record's.** A record is data the provisioning act
writes, and the act is reachable by the user through two operations. A callable's
construction is code at the composition root. Deciding the shape from the record would let a
re-provisioning change what a callable does. Deciding it from the callable lets a
mismatched record be refused, which is ADR-0148 §6's posture throughout: a state that says
what it is gets refused by a check that does not have to guess.

**Why one read and not two.** ADR-0148 §6:18 and §6:19 bracket the credential read because
`Secrets.get` awaits, and a provisioning act can land inside that wait. With no credential
there is nothing to bracket. One read stands where §6:19's re-read stands, and the revision
has nothing to be compared across. A substitution of the account is still refused by the
identity comparison, and a credential added under the reference is refused by the shape.

**Why a keyless callable refuses a record with a slot rather than ignoring it.** Ignoring it
would be harmless to the egress floor, because the credential would never be read. It would
also leave a credential in the keyring that no call reads while the user believes it is in
use. The refusal makes that state visible, and the remedy is the user's.

### 3. The record and the act

> **Normative.** `ConnectionEntry` admits a provisioning entry carrying an identity and the
> `ACTIVE` state with no slot. An entry carrying an identity and the `PENDING` state with no
> slot stays unconstructible, and a removal entry stays the one carrying none of the
> three.

> **Normative.** A **keyless provisioning act** is one write: the reference's first entry,
> appended `ACTIVE` with the identity the user supplied, revision 1 and no slot. The store's
> refusal of an append that would introduce a reference it already holds (ADR-0151 §3:2) is
> the act's compare-and-swap.

> **Normative.** A keyless provisioning act calls neither `set` nor `delete` on the keyring
> and reads nothing from it. It is performed by the connection provisioner (ADR-0149 §1:1)
> and by nothing else.

> **Normative.** A keyless provisioning act always writes under a reference it mints
> (ADR-0151 §3), and is never performed on a reference the store already holds. No
> operation re-provisions a reference into the keyless shape.

> **Normative.** A keyless provisioning act returns only when its write has landed, with
> `state=ACTIVE`, the identity supplied in that call, and revision 1.

> **Normative.** A keyless provisioning act whose write fails rather than returning raises
> `ConnectionStoreError` carrying no reference. The client reports the outcome as not known,
> as ADR-0151 §7:5 has it report `connect_account`'s, and resolves it by reading
> `connected_accounts`. No other failure class is raised by the act.

> **Normative.** A keyless reference is otherwise an ordinary reference. `disconnect_account`
> disconnects it under ADR-0149 §5 unchanged, and `reprovision_account` re-provisions it under
> ADR-0148 §6's three writes unchanged, after which it names a slot and a keyless callable
> bound to it refuses.

**Why one write.** The pending state exists for one window: the record ahead of the keyring
while the credential write is in flight (ADR-0148 §6's round 7). A keyless act has no
credential write, so pending would describe a window that does not exist and would leave an
interrupted act needing a re-run for nothing. Writing `ACTIVE` at once keeps every property
§6 bought with the state. An act that has not completed leaves no record, and none is ever
marked active over a credential the act did not write.

**Why only a fresh reference.** Every displacement case in ADR-0148 §6 and ADR-0151 §7
comes from two acts on one reference. A keyless act on a minted reference cannot lose a
compare-and-swap to another act and has no predecessor slot to delete. So it never touches
the keyring, and it adds no row to ADR-0151 §7's outcome table. Changing a source from
keyless to credentialed stays possible through `reprovision_account`. The reverse change is a
new keyless connection and a disconnection of the old one, which are two acts the store
already records separately.

### 4. The user act

> **Normative.** A keyless connection is created only by an explicit user act through a
> client, and ADR-0149 §4:1 binds it as written: no `Settings` value, configuration, upgrade,
> migration, first run, backup restore, scheduler job, plan step, tool, callable or model
> creates one or supplies its identity.

> **Normative.** The identity of a keyless connection is the name the user gives it, for
> the source as they recognise it. It is supplied by the user in the keyless act, which
> supplies no credential, and is recorded verbatim. No component infers it from a
> reference, an endpoint, an origin, a `Settings` value or a remote lookup, and no client
> fills it in from configuration.

> **Normative.** ADR-0151 §5's refusals bind the keyless act's identity, locally and before
> any I/O, in every implementation: `UnusableIdentityError` when its UTF-8 encoding exceeds
> `ACCOUNT_IDENTITY_MAX_BYTES` or it contains a control character or a line break.

> **Normative.** A client offers the keyless act only as a choice the user makes for a
> connection with no credential. No client performs it because a credential was not
> supplied, was blank or was refused, and no client falls back to it from `connect_account`.

> **Normative.** Every client that accepts the identity displays it to the user as part of
> the act, and every operation that returns it returns it byte for byte (ADR-0151 §5:4).

**What the identity is.** ADR-0148 §6:3 calls it *"the durable, user-recognisable name of the
account itself, recorded when that account was connected"*. A keyless source has no account
on its side, so what the user names is their own use of that source, for example
"Open-Meteo". The identity still does its job in the binding. The approver sees it, and a
reference re-pointed to another use under another name is refused by the identity
comparison. ADR-0149 §4:3's refusal of an identity equal to the credential has nothing to
compare on this act, and nothing replaces it: the risk it addresses, a token pasted into the
identity field, needs a token, and the keyless act asks for none.

**Why a separate operation and not an optional credential.** ADR-0151 §1 kept
`connect_account` and `reprovision_account` apart so that the mistake a user actually makes
is unreachable rather than merely visible. The same reasoning applies here. With an optional
credential, a user who forgot their key would get a working-looking connection that every
credentialed callable then refuses. A separate operation makes leaving out the credential a
choice the user makes on purpose. It also leaves every existing signature, failure table and
`credential` clause of ADR-0151 word for word as ratified.

### 5. The contract surface

> **Normative.** `AssistantEngine` gains
> `async def connect_keyless_account(self, *, identity: NonBlankEncodableText) -> ConnectedAccount`.
> It takes no reference and no credential, and accepts neither under another name. It
> declares `UnusableIdentityError`, `ConnectionStoreError` and `OversizedValueError`, and
> nothing else.

> **Normative.** `ConnectionProvisioner` gains
> `async def provision_keyless(self, *, identity: NonBlankEncodableText) -> ConnectedAccount`,
> which declares `ConnectionStoreError` and nothing else, as ADR-0151 §10:5 has the seam
> declare the engine's failures less the ones the engine refuses first.

> **Normative.** No member of `core/types.py` or `core/errors.py` changes. `ConnectedAccount`
> and `ConnectionAct` carry a keyless connection in their existing four and three fields,
> and no field says which shape a connection is.

> **Normative.** The change to the promoted method set advances `PROTOCOL_VERSION` under
> ADR-0124 §9's first limb, in the change that adds the method.

> **Normative.** The new operation is on ADR-0151's connection surface, and ADR-0151 §12 and
> §13:1 to §13:3 bind it as they bind the five: no ruling, no trail, not presented as an
> authorisation; no `ToolDefinition`, plan step, model-authored value or scheduler job
> reaches it; it adds no `Settings` field; and it is served over ADR-0084 §1's loopback
> socket only, so `wire/server.py`'s `CONNECTION_METHODS` names it.

> **Normative.** The implementation lands in one lane and one PR: the `AssistantEngine`
> method with its conformance-suite additions, its canonical fake and `HubEngineClient`'s;
> the `ConnectionProvisioner` member with its conformance suite and canonical fake; and the
> provisioner, the store's admitted shape and the engine wiring in `tools/` and
> `orchestration/` (ADR-0137 §2, ADR-0151 §15:2). A CLI command is a separate change.

> **Normative.** The implementing lane adds tests that a keyless callable refuses a record
> naming a slot, that a credentialed callable refuses a record naming none, that a keyless
> act writes one entry and makes no keyring call, and that `ConnectionEntry` refuses a
> slotless pending entry.

**Why the browser does not get it here.** ADR-0177 §1:1 is a closed enumeration of what a
browser reaches, and its 2026-08-24 note records that a method added to the promoted surface
is outside the browser until an ADR puts it inside. This decision does not put it there.

**Why loopback-only, although no credential crosses.** ADR-0151 §13:3 grounds the loopback
rule in the credential's hop, and the keyless act carries none. Serving it on the remote
listener could therefore be argued for. It is not decided here, because the five
connection operations would then sit on two different transport rules, and the gain is
small.

### 6. What is not decided here

> **Normative.** This decision settles nothing about the following, and no lane cites it
> toward any of them.

- **The Open-Meteo adapter.** Replacing `tools/forecast.py`'s reference provider with a
  keyless one is a later lane. It owes the records against ADR-0260 §4:3 (*"A `Forecaster`
  holds the credential"*) and §6:2's *before the credential is read*, which this decision
  leaves standing.
- **The forecast as a pull**, which is another lane's decision.
- **Re-provisioning in place into the keyless shape, or relabelling a keyless connection.**
  Fired by a source whose label the user needs to change while configuration names it.
- **Telling the two shapes apart on the surface**, a field on `ConnectedAccount`. Fired by a
  client that needs to show the user which connections hold a key.
- **The keyless act in the browser, and on the remote listener.** Fired by the lane that
  wants either.

### 7. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0148 §6:5 | Its third condition, replaced by §2:3 for every callable. The other three bind unchanged (§2:4) |
| ADR-0148 §6:7 | As it reaches a keyless record and act: the record carries no slot and the act writes none (§3:1–§3:2) |
| ADR-0148 §6:8 | As it reaches a keyless act: one write, not three (§3:2) |
| ADR-0148 §6:9 | Its slot limb, as it reaches a keyless record: there is no slot to obtain or read under (§2:3) |
| ADR-0148 §6:11 | Its *to pending … and its own slot* limb, as it reaches a keyless act: the act's one append lands `ACTIVE` with no slot (§3:2) |
| ADR-0148 §6:13, §6:14 | As they reach a keyless act: it has no credential write to re-read before and no activation separate from its one write (§3:2) |
| ADR-0148 §6:17 | Its first sentence, as it reaches a keyless act: there is no third write and no pending state to be left in (§3:2, §3:5) |
| ADR-0148 §6:18–§6:20 | Nothing: they bind a callable that reads a credential, and a keyless callable reads none. §2:5 states its one read |
| ADR-0148 §6:10, §6:15, §6:16, §6:21, §6:22 | Nothing: a keyless act has no predecessor slot and no credential write, connectability is unchanged, and §2:6 applies §6:21 |
| ADR-0149 §3:4 | Its *and the slot* limb, as it reaches a keyless record (§3:1) |
| ADR-0149 §4:2 | Its *in the same act that supplies the credential*, for the keyless act: the identity is supplied in an act that supplies none (§4:2). *Recorded verbatim* and the inference bar stand |
| ADR-0149 §4:7 | Its *and supplies the credential a callable reads* limb, as it reaches a keyless connection. *A connection authorises nothing* stands |
| ADR-0149 §1, §4:1, §4:3–§4:6, §5, §6, §8 | Nothing: the provisioner performs the act, and the equality refusal, the slot rules, disconnection and the purge have no slot to act on |
| ADR-0151 §1:1 | *Exactly these five methods*: there are six, the sixth being §5:1's |
| ADR-0151 §3:1 | *At the moment `connect_account` writes the reference's first record, and by nothing else*: the keyless act mints too (§3:4) |
| ADR-0151 §7:3 | As it reaches a keyless act: its one write is a first write, classified by the first bullet alone (§3:6) |
| ADR-0151 §7:11 | Its *activates a record whose credential write it did not itself perform* limb, as it reaches a keyless act's own record (§3:2). Every other limb stands |
| ADR-0151 §10:2 | *Exactly five members*: there are six, the sixth being §5:2's. §10:7 anticipated a later ADR adding one |
| ADR-0151 §2a, §5, §6, §12, §13 | Nothing: each stays true of the five it names, and §4:3 and §5:5 bind the sixth |
| ADR-0177 §1 | Nothing: its closed enumeration governs the new method, which it does not name (its 2026-08-24 note) |
| ADR-0260 §4:3, §6:2 | Nothing here: the forecast integration stays credentialed until the adapter lane (§6) |
| ADR-0273 §3:1 | Nothing: the booking integration holds a `Secrets` face, so §2:3 asks of it what ADR-0148 §6:5 asked |
| ADR-0125 | Nothing: no scope, face or signature changes, a keyless callable holds no face, and a keyless act calls the keyring not at all |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0148, ADR-0149 and ADR-0151, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect on
> this ADR's ratification.

## Consequences

**What becomes possible.**
- A source that needs no key can be connected by the user, bound at the designated seam and
  called under the full per-call floor, with no invented credential in the store or the
  keyring.
- The first such source is Open-Meteo, for the forecast (ADR-0260 §14). Its terms limit the
  free API to non-commercial use ("You may only use the free API services for non-commercial
  purposes", open-meteo.com/en/terms, read 2026-10-17). A commercial deployment would need
  its paid plan, and with it a credential, which is the credentialed shape this decision
  leaves as it was.
- Every later keyless source, such as a tide, air-quality or transit source, uses the same
  shape without a decision of its own.

**What it costs.**
- One more engine method and seam member, and a wire version bump.
- A keyless connection and a credentialed one look the same in `connected_accounts`, so the
  user tells them apart by the name they gave.
- Moving a source from a key to no key is two acts, not one.

**What would make us revisit it.** A keyless source that turns out to need some per-user
secret after all, or a need to show the user which connections hold a key.

## Alternatives considered

- **An optional credential on `connect_account` and `reprovision_account`.** Rejected (§4):
  it makes a forgotten key look like a keyless connection, and it rewrites ADR-0151's
  signatures and failure tables.
- **#2396's wording, *"where it names one"*.** Rejected (Context): it lets a credentialed
  callable meet the condition by reading nothing.
- **Pending then active, as two writes.** Rejected (§3): the pending state covers a
  credential write the keyless act does not make.
- **A keyless callable that ignores a slot.** Rejected (§2): it hides an unused credential.
- **A placeholder credential.** Rejected: it is the false record #2396 names, a Tier 0 value
  that means nothing in the keyring, and an identity check against a value that is not a
  secret.
