# 151. The connection surface is five engine operations, and the reference is minted rather than typed

- Status: Proposed
- Date: 2026-08-14
- **Decides the surface ADR-0149 §9 names as owed**, on the firing condition §9's
  second clause states — "Its firing condition is this ADR merging" — which
  ADR-0149's merge met. `AssistantEngine` gains **five** methods —
  `connect_account`, `reprovision_account`, `disconnect_account`,
  `connected_accounts` and `recent_connection_acts` — `core/types.py` gains
  **three** types and one constant, and `core/errors.py` gains **four** classes.
  It also decides the shape of the Protocol ADR-0149 §10 flags, by which
  `orchestration` reaches the provisioner in `tools/`. No code ships with it.
- **Flagged as a breaking change under golden rule 5.** The implementing lane
  changes `core/protocols.py` (five methods on `AssistantEngine`, which every
  structural implementation must then carry, plus one new Protocol),
  `core/types.py` and `core/errors.py`. This ADR is therefore ratified and merged
  as its own PR before anything implements against it (ADR-0015 §5).
- **Required review set: adversarial *and* architecture.** The PR carrying it is
  prose only and touches neither floor path, so `ship.sh`'s architecture gate does
  not fire on the diff; the set is taken because the *decision* is `core` surface,
  which is what `CONTRIBUTING.md` → "Stop when the required reviews are green"
  requires of "the ADR deciding that surface", and what ADR-0102 and ADR-0149 each
  declared for the same reason. §19 records the set that ran.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-14**,
  the durability form ADR-0100 established and ADR-0149's header repeats. This
  decision rests most heavily on ADR-0149, ADR-0148 §6, ADR-0102 and ADR-0085; a
  citation that silently means "whatever that ADR says when you read it" is not
  checkable. Where a later ADR changes one of them, this one is read against the
  text named here until an ADR says otherwise.
- **It does not decide #909, and it says so in terms** (§14). ADR-0149 §8's
  precondition — that no lane provisions a connection in an installation before a
  ratified decision routes the owner's delete right to §8's purge — is carried
  forward unrelaxed, and this ADR adds no route around it. The Protocol §15 places
  carries no purge member, and §14 records that this leaves #909 free to add one
  rather than foreclosing it.
- **No implementation lands with it.** No `src/`, no `tests/`, no
  `pyproject.toml`. §16 says what is owed and who owes it.
- **It amends no earlier ADR and supersedes none.** §17 applies ADR-0070 §1's test
  and ADR-0082 §1's record rule at the seven places where the opposite reading is
  available, and shows its working at each.

## Context

### What ADR-0149 §9 handed over, and what it fixed first

ADR-0149 §9's first clause is normative that connecting, re-provisioning,
disconnecting and listing connections are **hub operations reached by a client**,
implemented in `orchestration`, which "delegates each act to the provisioner (§1)
through a Protocol in `core/protocols.py` (§10)" and which "holds no keyring face,
opens no connection store and performs none of ADR-0148 §6's three writes".

What it deliberately did not decide is the shape. Its second clause routes "the
`AssistantEngine` method signatures for these operations, the result types they
promote to `core/types.py`, their wire frames and the shape of the Protocol §10
names" to this ADR, on ADR-0084 §5's step-1/step-2 split — the same split ADR-0097
§9 made and ADR-0102 discharged.

Its third clause fixes five properties this ADR may not choose otherwise, and they
are quoted here rather than paraphrased because §17 has to be checkable against
them:

> **Normative.** Whatever shape that ADR chooses, these properties hold and it may
> not choose otherwise: no response carries a credential value or any value
> derived from one; the credential travels only in the request that performs the
> act and comes to rest only in the keyring, reaching no log, no audit record, no
> conversation, no plan, no trace and no error message; no operation is bound by a
> `ToolDefinition` or reachable by a plan step; a refusal names the reference and
> not the identity (§3); and the act's three writes stay the provisioner's,
> performed in ADR-0148 §6's order, with `orchestration` neither reordering,
> splitting nor retrying them.

ADR-0149 §10 adds two more that reach this ADR's Protocol directly: no credential
value appears in its return types, and it "carries no `SecretName` a caller could
use to reach the keyring by another route, and holding it confers no keyring
face".

### The act this surface drives, and what about it is already ratified

ADR-0148 §6 fixed the semantics in unusual detail and this ADR consumes them
whole. A connection record carries an account **identity**, a monotonic
**revision**, a **provisioning state** that is *pending* or *active*, and the
**credential slot** the act which wrote it wrote its credential to. Provisioning
or re-provisioning is **three writes in a fixed order** — the record first as
*pending*, the credential second, the record *active* third. At most one act owns
a record at a time and takes it by a **compare-and-swap**; the activation is
itself a compare-and-swap; a displaced act's late write lands in a slot no live
record names; an act deletes its predecessor's slot once its own activation has
landed; and an act interrupted before its third write leaves the reference
*pending* and therefore **not connectable**, which is "refused rather than
reconciled".

ADR-0149 §5 adds the disconnection ADR-0148 §6 does not rule on: a **removal
entry** first, the slots second; every distinct slot named by an entry whose
revision is strictly below the removal's; idempotent and re-runnable; nothing
written at all for a reference the store has never held; no reset of the revision;
and a slot deletion that fails leaves the reference disconnected with the failure
"reported and never suppressed". ADR-0149 §6 rules that an active record over an
empty slot is refused at the read and repaired by nothing.

None of that is re-decided here. What this ADR owes is the surface through which a
person causes it and sees it, and every place that surface could overclaim about
it.

### The tree, read rather than remembered

Checked on the branch this ADR was written on, at `origin/main`:

- `AssistantEngine` in `core/protocols.py` carries **twenty-six** methods, the
  longest of them `set_notification_preferences` at 28 bytes. `core/types.py`'s
  promoted-surface comment and `wire/surface.py`'s module docstring each still say
  "nineteen methods", which is a count claim two lanes older than the tree; it is
  not this ADR's to fix and §16 files it rather than absorbing it.
- `SecretValue`, `SecretName`, `SecretScope`, `Identifier`, `DurableIdentifier`,
  `NonBlankEncodableText`, `EncodableText` and `DEFAULT_PAGE_SIZE` all exist in
  `core/types.py`. `SECRET_VALUE_MAX_BYTES` is **1024**, and `secret_value`
  refuses a blank, unencodable or oversized plaintext with `ValueError` and a
  message naming neither the value nor its length (ADR-0125 §3, §6).
- **`SecretStr` has no canonical wire form.** `project` in `wire/codec.py` is a
  total dispatch over the value space that ends in `TypeError` for a type it has
  no form for, and `SecretStr` is not a `str` subclass, so it lands there.
  `HubEngineClient._call` runs `project` over the arguments **before the socket is
  opened**, so the refusal is local and loud rather than deferred. What a
  `TypeAdapter` over `SecretValue` would have done instead is the hazard this
  fact removes: `dump_json` renders it `"**********"`, so a codec that had gone
  through pydantic's serialiser would have sent the redaction as if it were the
  secret, and the hub would have written ten asterisks into the keyring while
  every in-process test passed.
- Inbound, `TypeAdapter(SecretValue).validate_python("hunter2")` yields a
  `SecretStr` whose `get_secret_value()` is `"hunter2"`, so the declared
  annotation is enough to reconstitute the value the client unwrapped.
- `core/logging.py` redacts by key name and `_SENSITIVE_KEY_PARTS` contains
  `credential`, which is the mechanism ADR-0124 §6 leans on when it forbids "a
  name that redaction misses".
- `wire/server.py` logs a connection's reason and an exception's class name and
  **logs no payload**. `wire/surface.py` derives `METHODS` by reflection over the
  Protocol and `wire/errors.py` derives an error code from the exception class's
  own name, so the server half and the error registry are total by construction —
  the finding ADR-0102 §12 item 5 recorded and which still holds.
- Nothing in the tree holds a connection record, a connection store, a
  provisioner, or an `INTEGRATION`-scoped instance of either keyring face.
  `tools/egress.py` is empty. **There is no integration to connect.**

### The grant surface is the nearest precedent, and exactly one of its four operations has no analogue here

ADR-0102 derived four operations from ADR-0097 §9: three acts and an enumeration
of what may be granted, "so a client offers a choice among declared identities
rather than a free-text field". That fourth operation is the one this surface
cannot have, and the reason is structural rather than a matter of taste.

A grant's subject is a **reader the hub holds**, whose identity is a declared
constant existing before any user act (ADR-0093 §7), so a set to choose from
exists to be enumerated. A connection's subject is an **account**, and ADR-0148
§6 makes the dependency run the other way: "An account whose identity was never
recorded is not connectable, **no tool is registered against it**", and "A tool
registered at the seam is bound to at most one connected account". Registration
follows connection. So there is no declared set of connectable things to offer,
and nothing else in the tree declares one either.

That leaves the reference — the handle ADR-0148 §6 says "names that account's
connection record and nothing else" — with nowhere to come from except the user's
keyboard or the hub's own minting. ADR-0149 §3's marked clause settles it:

> **Normative.** … The **connection reference** and the **credential slot** are
> non-secret handles chosen by code (ADR-0125 §2) and may be logged.

A value chosen by code is not a value a user types, and a value the corpus
licenses to be logged cannot be one a user typed — ADR-0149 §3's whole point in
that clause is that the reference may be logged *because* the identity beside it
may not. §3 below takes the only reading that satisfies it.

### An honest statement of what this ADR is not allowed to settle

- **ADR-0148 §6's semantics and ADR-0149 §§1, 3, 4, 5, 6, 7 and 8.** Consumed,
  never re-decided. Where this ADR adds, it adds beside them and §17 shows the
  test.
- **Who invokes ADR-0149 §8's purge, and the seam they reach it through.** §8's
  fourth clause puts both with #909 "together with the choice of coordinator", and
  §14 leaves them there rather than deciding half of a pair.
- **ADR-0148 §11's surfaces (a) and (b)** — the egress binding and the seam that
  supplies it. Each is its own contract ADR, and neither is this one.
- **What an integration is.** No endpoint, no scope list, no service taxonomy and
  no account chooser (§18). ADR-0149 §9 names each as "a guess today and an
  observation once one exists", and the tree still holds no integration.
- **ADR-0017 §3's conditions.** Nothing here discharges one, attests one, or
  designates the `tools/` egress seam.

## Decision

We will put five operations on `AssistantEngine` — one that connects an account
under a reference the hub mints, one that re-provisions an existing reference, one
that disconnects, one that says what is connected now and one that says what was
done — with the credential carried only by the two acts that write it, the
identity refused rather than normalised, and every partial outcome reported as the
half that landed rather than as a success or a failure.

### 1. Five operations, and five is derived rather than preferred

> **Normative.** The client surface for connections is exactly these five methods
> on `AssistantEngine`: `connect_account`, `reprovision_account`,
> `disconnect_account`, `connected_accounts` and `recent_connection_acts`, with
> §2's signatures. No other operation on any surface performs, or reports the
> outcome of, a provisioning act or a disconnection.

**The count comes from ADR-0149 §9's first clause and ADR-0139 §1, in that
order.** §9 names four things — "Connecting, re-provisioning, disconnecting and
listing connections" — and says of the last that "Whether it is one operation or
several is the surface ADR's". Three of the five are §9's first three acts. The
remaining two are its fourth, split by ADR-0139 §1's rule that a surface answering
two different questions keeps them apart: *what is connected now* is answered from
the store's live records, *what was done* is answered from its history, and
neither is derivable from the other (§9 below shows why the derivation is unsound
rather than merely redundant).

**Connecting and re-provisioning are two operations over one act, and the fold was
tested.** ADR-0148 §6 gives them one shape — "Provisioning **or re-provisioning** a
connected account is three writes in a fixed order" — so the tempting economy is
one method whose reference argument is optional, meaning "mint one" when absent.
It is refused on ADR-0085 §9's ground that the per-method failures are part of the
contract: a fresh connection cannot fail with an unknown reference and cannot lose
a compare-and-swap, because its reference is minted and no other act can be
holding it, while a re-provisioning can do both. A folded method declares the
union and tells a caller nothing about which half applies to the call it is
making. Two methods also make the mistake a user actually makes — meaning to
replace a credential and creating a second connection instead — unreachable rather
than merely visible: `reprovision_account` refuses a reference the store does not
hold, and `connect_account` cannot be aimed at one at all.

**Nothing else is folded, and each fold was tested.** `disconnect_account` cannot
be `reprovision_account` with an absent credential, because ADR-0125 §3 refuses a
blank `SecretValue` at construction and because ADR-0149 §5's disconnection is a
different act with a different write order. A combined "replace this account with
that one" is refused for ADR-0102 §1's reason applied to ADR-0149 §5: a
disconnection and a provisioning act are two records the store keeps separately,
and a surface that issued both under one name would be presenting as atomic a pair
ADR-0139 §4 already ruled must report each half's outcome separately.

### 2. The five signatures

**Every annotation is spelled out**, in ADR-0085 §3's form and under its §2
convention: the subject of a call is positional and every other argument is
keyword-only. `Identifier`, `NonBlankEncodableText`, `SecretValue` and
`DEFAULT_PAGE_SIZE` are `core/types.py`'s existing names; `ConnectedAccount`,
`ConnectionAct` and `ACCOUNT_IDENTITY_MAX_BYTES` are §4's and §5's additions.

```python
async def connect_account(
    self, *, identity: NonBlankEncodableText, credential: SecretValue
) -> ConnectedAccount: ...


async def reprovision_account(
    self,
    reference: Identifier,
    *,
    identity: NonBlankEncodableText,
    credential: SecretValue,
) -> ConnectedAccount: ...


async def disconnect_account(self, reference: Identifier) -> ConnectedAccount | None: ...


async def connected_accounts(self) -> tuple[ConnectedAccount, ...]: ...


async def recent_connection_acts(
    self, *, limit: int = DEFAULT_PAGE_SIZE
) -> tuple[ConnectionAct, ...]: ...
```

**Docstrings are omitted here and are not optional in the Protocol**, exactly as
ADR-0085 §3 and ADR-0102 §2 each state for their own block.

> **Normative.** `connect_account` takes **no** reference argument, and no
> implementation accepts one under another name or through another route. Its
> reference is minted (§3).

> **Normative.** The `identity` argument is `NonBlankEncodableText`, which rejects
> a blank value and normalises nothing. No implementation of any operation on this
> surface may strip, case-fold, case-normalise, Unicode-normalise or otherwise
> alter a caller-supplied `identity` at any point — not at the surface, not in
> `orchestration`, not in the provisioner and not in the store. This is ADR-0149
> §4's non-normalisation clause bound to the annotation that could otherwise
> defeat it.

**`Identifier` is the wrong type for `identity`, and it is the type an author
reaches for first.** ADR-0102 §2 records the mechanism in full: `Identifier`'s
validator returns a stripped value, `wire/surface.py`'s `argument_adapter`
validates each argument against the Protocol's own annotation before dispatch, and
the in-process engine is handed the string unvalidated — so the two
implementations would disagree about a value both are handed, which is ADR-0084
§4's substitutability failure arriving through an annotation. Here it would also
be a ratified clause defeated one layer below the clause: ADR-0149 §4 forbids
normalisation "at the surface" in as many words, and an annotation that
normalises is the surface doing it.

**The reference arguments are `Identifier` and that is not the same call.**
ADR-0085 §3c rules that "Every id argument is `Identifier`", and its stated
argument — that a client "must be comparing values of the same type" as the field
it addresses — applies exactly, because §3 makes a reference a minted id no user
authors. The strengthening §3c buys for an id is harmless where nothing was typed;
ADR-0102 §2 declined it only for a value "whose whole contract is exact comparison
against a declared constant", which a minted reference is not.

#### 2a. The declared failures, and the four new error classes

ADR-0085 §9 makes the per-method failures part of the contract, "A Protocol whose
methods raise unnamed exceptions is not a contract a conformance suite can hold
anyone to". They are declared here rather than left to the lane, with
`OversizedValueError` assumed throughout in §9's own form.

> **Normative.** The five operations declare exactly these failures, plus
> `OversizedValueError` on every one of them:
>
> | Method | Declares |
> | --- | --- |
> | `connect_account` | `ValueError`, `UnusableIdentityError`, `ConnectionStoreError`, `SecretStoreError` |
> | `reprovision_account` | `ValueError`, `UnusableIdentityError`, `UnknownConnectionError`, `DisplacedProvisioningError`, `ConnectionStoreError`, `SecretStoreError` |
> | `disconnect_account` | `ValueError`, `ConnectionStoreError`, `SecretStoreError` |
> | `connected_accounts` | `ConnectionStoreError` |
> | `recent_connection_acts` | `ValueError`, `ConnectionStoreError` |

> **Normative.** `core/errors.py` gains four classes: `ConnectionStoreError`, a
> direct subclass of `AssistantError`, raised when the connection store could not
> be read or written; `UnknownConnectionError` and `DisplacedProvisioningError`,
> each a direct subclass of `ConnectionStoreError`; and `UnusableIdentityError`, a
> direct subclass of `AssistantError`. None of them defines an `__init__`, none
> carries structured state, and none names the supplied identity, the supplied
> credential, any part or derivation of either, or a filesystem path.

> **Normative.** A refusal raised by any operation on this surface **names the
> reference where the call carries one**, and **never** names the identity or the
> credential — ADR-0149 §9's refusal rule, applied at both of its limbs, and
> ADR-0149 §3's split between a loggable handle and a Tier 1 value.
> `reprovision_account` and `disconnect_account` therefore name the reference they
> were given, in the message and in what the hub logs.

> **Normative.** `connect_account`'s refusals name **no** reference, because there
> is none to name: §3 mints one only as the reference's first record is written,
> and every refusal above writes nothing. This is a consequence of the mint rather
> than a narrowing of ADR-0149 §9 — its prohibition on naming the identity binds
> `connect_account` exactly as it binds the other four — and §17 shows the test
> rather than asserting it.

**A per-store error class is this corpus's settled convention rather than a new
one.** `MemoryStoreError`, `ConversationStoreError`, `DeferralStoreError`,
`NotificationStoreError`, `TraceStoreError`, `GrantError` and `SecretStoreError`
are all the same shape, and a seventh durable store (ADR-0149 §3) arriving without
one would be the exception. `ConnectionStoreError` is that class, and it is
declared by all five operations because all five read or write the store.

**`UnknownConnectionError` follows `UnknownConversationError` and
`UnknownContinuationError`**, which is what the corpus does for "you named
something this store does not hold". It reaches `reprovision_account` only:
`disconnect_account` on an unheld reference is not an error at all (§8), and
`connect_account` names nothing.

**`DisplacedProvisioningError` is the typed refusal ADR-0102 §5's "the store is
the arbiter" requires.** ADR-0148 §6 makes an act's ownership a compare-and-swap
and rules that an act whose compare-and-swap fails "never held it and writes
nothing", and that an activation "lands only if the record still holds that state,
writing nothing otherwise". Both are lost races, both leave the caller's act
unperformed, and both have one recourse: read `connected_accounts` and decide
whether to run the act again. One class covers them for ADR-0097 §10's reason —
"the caller's recourse is identical" — and no operation performs a liveness
pre-check to narrow the window, because a pre-check narrows and does not close it
while inviting a reader to believe it had.

**`UnusableIdentityError` is one class for four refusals, on the same test.**
ADR-0149 §4 refuses an act whose identity equals the credential's plaintext, one
whose identity carries a control character or a line break, and one whose identity
exceeds the bound; §5 below adds nothing to that list and only fixes where the
bound lives. In every case the recourse is to supply a different identity, so one
class is right and three would be surface with no consumer.

**It is an `AssistantError` rather than ADR-0085 §9's `ValueError`, and the
distinction is §9's own.** §9's `ValueError` is "a caller programming error rather
than a condition of the system" — a blank id, a non-positive `limit` — refused
locally in both implementations. An identity is a value the **user typed**, and a
person pasting a token into the wrong field has not made a programming error; a
client needs to render the refusal, and `wire/server.py` converts an
`AssistantError` into an error frame while letting anything else close the
connection. A dropped socket is the worst available outcome on the one call that
carries a credential, because the natural client response to a dropped socket is
to retry it.

> **Normative.** `UnusableIdentityError` is raised **locally, before any I/O**, by
> every implementation of `connect_account` and `reprovision_account` — the client
> included — so both refuse the same values without a round trip and neither is
> silently more permissive (ADR-0085 §9). No such call reaches the hub, and no
> credential is sent for one.

**`ValueError` keeps the cases ADR-0085 §9 gives it**, and one of them is
inherited rather than invented: a blank, unencodable or oversized credential is
`secret_value`'s own refusal (ADR-0125 §3), raised by the annotation's validator
and by the seam's revalidation, with a message that names neither the value nor
its length (ADR-0125 §6). The others are a blank or unwritable `reference` and a
`limit` that is not strictly positive.

> **Normative.** `recent_connection_acts` refuses a `limit` that is not strictly
> positive, locally and before any I/O, in every implementation.

**`SecretStoreError` is declared and is not converted.** ADR-0125 §7 rules that a
keyring which is unreachable, locked or backendless is one visible error state,
and ADR-0149 §6's second clause forbids any lane treating it as an absent
credential. §7 below is where its two occurrences on this surface acquire their
meaning; declaring it here is what stops an implementation wrapping it into a
`ConnectionStoreError` and losing the distinction.

### 3. The reference is minted hub-side, and no caller ever authors one

> **Normative.** A connection reference is **minted by the provisioner** from an
> injected factory, at the moment `connect_account` writes the reference's first
> record, and by nothing else. No client, no `Settings` value, no configuration
> file and no model-authored value supplies, proposes, constrains or predicts one.
> `connect_account` accepts no reference and mints exactly one per call that
> writes a record.

> **Normative.** A reference is minted once per reference and is **never reused,
> re-minted or recycled** — not after a disconnection, not after a purge, and not
> for a second account. A reference the store has ever held is never minted again.

> **Normative.** The reference a caller supplies to `reprovision_account` or
> `disconnect_account` is one the hub previously returned. It is compared exactly
> against the references the store holds; no implementation matches one by prefix,
> by case-insensitive comparison or by any equivalence other than equality.

> **Normative.** A reference is a **non-secret handle** and may be logged
> (ADR-0149 §3). An account identity may not, and no implementation logs one, puts
> one in an error message, or derives a reference from one.

**Minting is what ADR-0149 §3's "chosen by code" means here, and the alternative
contradicts the clause beside it.** §3 licenses logging the reference in the same
breath that it rules the identity Tier 1 and keeps it out of every log, error and
diagnostic. A caller-authored reference is user-authored data, and licensing it to
be logged would put a value the user typed into the operator's log — the exact
disclosure §3's split exists to prevent, arriving through the half that was
supposed to be safe. Minting is the only reading under which both halves of §3
stay true at once.

**It also closes the failure a free-text reference makes unavoidable.** With a
typed reference, a stray space or a mistyped character on `connect_account`
creates a *second* connection where the user meant to replace the first, silently,
and the two are told apart only by an identity string the user may have typed the
same way twice; the same typo on `disconnect_account` writes nothing and leaves
the user believing they disconnected. With a minted reference the first case
cannot arise, because `connect_account` cannot be aimed at an existing record at
all, and the second is a typed `UnknownConnectionError` on `reprovision_account`
and a `None` on `disconnect_account` (§8).

**The precedent is ADR-0102 §5's, taken rather than resembled.** "The hub's grant
operations mint each record's `id` from an injected factory. No client supplies
either" — and its reasoning transfers whole: a client that minted an id into a
write-once store would be authoring durable state whose whole value is that the
hub wrote it. ADR-0148 §6's stability requirement then comes free: "The reference
is therefore stable across a rotation, which is what keeps a parked `CONFIRM`
answerable after one", and a minted handle is stable across re-provisioning by
construction rather than by a rule anyone has to keep.

**What it costs is named rather than discovered.** A user cannot address a
connection declaratively — there is no name they chose to type — so every act
after the first is performed against a reference read out of `connected_accounts`,
and a client that offers connecting must offer listing. That is the same shape
ADR-0102 §6's third clause puts on a grant client, and §18 records the two things
it forecloses for now: an idempotent "ensure this account is connected" call, and
a configuration file that names connections. Both are ADR-0149 §4's position
anyway — nothing may create a connection from configuration.

### 4. Three promoted types, and a pending record is visible

> **Normative.** `core/types.py` gains three types.
>
> `ProvisioningState` is a `StrEnum` with exactly two members, `PENDING` and
> `ACTIVE`, which are ADR-0148 §6's two states and no others. No member is added
> for a removal, for an unknown state or for a failure.
>
> `ConnectedAccount` is a frozen pydantic model (ADR-0068 §1) with
> `extra="forbid"` and exactly four fields: `reference: DurableIdentifier`,
> `identity: NonBlankEncodableText`, `revision: int` and
> `state: ProvisioningState`. It carries no other field, and in particular carries
> no credential slot, no `SecretName`, no endpoint and no timestamp.
>
> `ConnectionAct` is a frozen pydantic model with `extra="forbid"` and exactly
> three fields: `reference: DurableIdentifier`, `revision: int` and
> `account: ConnectedAccount | None`.

> **Normative.** `ConnectionAct.account` is `None` **exactly when** the act was a
> disconnection (ADR-0149 §5's removal entry), and present exactly when the act
> was a provisioning act. Where it is present, its `reference` and `revision`
> equal the act's own. A removal is identified by that absence and is **not** a
> third `ProvisioningState`, which ADR-0149 §5 forbids in terms.

> **Normative.** `ConnectedAccount.revision` is a strictly positive integer and is
> ADR-0148 §6's monotonic revision, reported as the store holds it. No
> implementation renumbers, compacts, offsets or resets it, and no surface
> presents it as a count of anything.

> **Normative.** `connected_accounts` returns a `ConnectedAccount` whose `state`
> is `PENDING` for every reference whose live record is pending. It does not omit
> such a reference, does not substitute the previous act's record for it, and does
> not report it as connected.

> **Normative.** No client presents a `PENDING` record as a working connection. A
> surface rendering one says the reference is **not connectable** and that the
> remedy is to run the act again (ADR-0148 §6), and never that the connection is
> being established, is in progress, or will complete on its own.

**Pending is on the surface because it is reachable without anyone doing anything
wrong, and because nothing repairs it.** ADR-0148 §6 rules an interrupted act's
state "refused rather than reconciled", with the remedy being a fresh act. A
surface that showed only active records would answer "what is connected" correctly
and leave a user whose hub was killed mid-act with a reference that exists, is
refused at every call, and appears nowhere they can see. The last clause is what
stops the field being rendered as a spinner: nothing is running, and the record is
inert until a user acts.

**Three types is the floor and the fourth was considered.** An earlier draft gave
`ConnectionAct` a `kind: ConnectionActKind` discriminator over `PROVISIONING` and
`REMOVAL`. It is refused as a fourth promoted type encoding a distinction one
optional field already carries unambiguously, on a surface whose size is a
contract clause (ADR-0085 §8) — and the optional is the safer of the two shapes
here, because an enum invites a third member where ADR-0149 §5 has ruled there may
not be one. The redundancy the nesting introduces is answered by the equality
clause above and by a conformance test rather than left latent (§16).

**The closure stays closed, and that is the property ADR-0085 §5 fixed.** Walking
the declared field types: `DurableIdentifier` and `NonBlankEncodableText` are
`core` aliases; `int` is a builtin; `ProvisioningState` is a `core` enum;
`ConnectedAccount` is a `core` model whose own fields reach only the four just
named. The walk terminates in `core` on every branch, so nothing new leaves `core`
and `lint-imports` sees no new edge.

**There is no timestamp, and its absence is a consequence rather than an
omission.** ADR-0149 §3 fixes what a connection record carries — identity,
revision, state, slot — and ADR-0149 §12 lists "changing what a connection record
carries" among the things deliberately not done. A surface cannot report a field
the record does not have, so `recent_connection_acts` answers in the store's own
order and not by time (§9), and §18 records that giving a connection record a
recorded instant is a change to ADR-0149 §3 owing its own ADR.

### 5. The identity is the user's, is refused rather than normalised, and its bound is one contract constant

> **Normative.** `core/types.py` gains one constant,
> `ACCOUNT_IDENTITY_MAX_BYTES: Final[int]`, the bound ADR-0149 §4 leaves to the
> implementing lane. Its value is that lane's; its **location** is fixed here, and
> every implementation of `connect_account` and `reprovision_account` — the wire
> client included — refuses against that one constant.

> **Normative.** An `identity` is refused with `UnusableIdentityError`, before any
> I/O and with nothing written, when any of these holds: its UTF-8 encoding
> exceeds `ACCOUNT_IDENTITY_MAX_BYTES`; it contains a Unicode control character or
> any line break; or it is equal, as an exact string comparison, to the plaintext
> of the `credential` supplied in the same call. The refusal's message names
> neither value, no part of either, and no length of either.

> **Normative.** The equality comparison is made **before** the first of ADR-0148
> §6's three writes and before the credential is sent anywhere, in every
> implementation. No implementation performs it after a write, on a hash, on a
> prefix, or by any test other than exact equality of the two strings supplied to
> that call.

> **Normative.** Every operation on this surface that returns an identity returns
> it byte-for-byte as it was supplied, and every client that accepts an identity
> displays it to the user as part of the act. No surface accepts an identity it
> does not display (ADR-0149 §4).

**The bound's location is the one thing ADR-0149 §4 left underdetermined, and
ADR-0085 §9 is what determines it.** §4 says "a length bound the implementing lane
sets and the store enforces". Enforcement in the store alone would put the refusal
on the far side of a round trip, and a bound each implementation chose for itself
would make the wire client and the in-process engine disagree about a value both
are handed — ADR-0085 §9's clause exists for exactly that, "so both implementations
refuse the same values without a round trip and neither is silently more
permissive". Fixing the location and leaving the value with the lane keeps §4's
sentence true as written and adds the property §9 requires; §17 records it as a
stacked addition.

**Why a bound in *bytes* rather than characters.** ADR-0085 §8c bounds the
serialised payload, `EncodableText` is defined by having a UTF-8 encoding, and
`SECRET_VALUE_MAX_BYTES` is already stated in bytes — a character bound would be
the only measurement on this surface that does not compose with the frame
arithmetic §11 has to do.

**The display clause is an obligation the hub cannot enforce, and saying so is
part of stating it.** Nothing on the wire distinguishes a client that rendered the
identity from one that did not; ADR-0102 §6's third clause is the same shape and
ADR-0098 §5's discipline is that a bound this system cannot obtain is an
unenforceable rule rather than a weaker one. What the hub enforces is that the
value is returned unaltered by every operation that returns one, which is testable
here; what the clause obliges is the client, which is testable there. It is worth
the words because ADR-0149 §4's third answer to a credential in the identity field
is precisely that the value is *seen*, and a client that swallowed it would remove
the one ingredient that failure needs.

### 6. The credential is one argument, unwrapped once, and `SecretStr` keeps having no wire form

> **Normative.** The credential is supplied as the `credential` argument of
> `connect_account` and `reprovision_account`, typed `SecretValue` (ADR-0125 §3),
> and reaches this system by no other route. No other operation on any surface
> accepts one, no operation returns one or any value derived from one, and no
> field of `ConnectedAccount` or `ConnectionAct` carries one.

> **Normative.** The argument is named `credential` on both operations, so
> `core/logging.py`'s key-name redaction covers it wherever a payload mapping is
> logged. No implementation renames it, aliases it, or nests it under a key that
> redaction does not reach — ADR-0124 §6's "no implementation may give it a name
> that redaction misses", applied to a parameter name.

> **Normative.** ADR-0087's canonical projection is **not** extended to
> `SecretStr`. A `SecretStr` reaching `project` stays the refusal it is today, and
> no lane gives the codec, a pydantic serialiser or any other general mechanism an
> automatic unwrap.

> **Normative.** The wire client unwraps the credential at **one** site — in
> `connect_account` and `reprovision_account`, immediately before the arguments
> are projected, after revalidating the value through `secret_value` — and nowhere
> else. This is ADR-0124 §7's shape, taken deliberately. The hub reconstitutes it
> by validating the received string against the declared `SecretValue` annotation,
> and hands it to the provisioner without unwrapping it.

> **Normative.** `orchestration` relays the credential to the provisioner and does
> nothing else with it: it does not unwrap it, log it, retain it beyond the call,
> copy it into any other value, retry a call with it, or read it back. It holds no
> keyring face (ADR-0149 §9) and acquires none by carrying the value.

> **Normative.** No provisioning act, and no operation on this surface, is
> recorded in a trace (ADR-0141), an `AuditTrail`, a conversation or a plan
> (§12, §13). The credential therefore reaches none of them, and no lane adds a
> path by which it could.

**The `SecretStr`-has-no-wire-form clause is the one that stops a silent
substitution, and it is a fact about the tree before it is a rule.** `project` is
a total dispatch that ends in `TypeError` for an unformed type, and `SecretStr` is
not a `str` subclass, so a credential that reached it fails loudly in the client
before the socket is opened. The alternative that looks tidier — teaching the
codec to unwrap a `SecretStr` — is refused because it is general where the need is
specific: it would silently encode every secret any promoted value ever came to
carry, which removes exactly the property ADR-0125 §3 bought, that "a disclosure
requires somebody to write the unwrapping call, which makes it deliberate and
reviewable rather than accidental". Leaving the refusal in place and writing the
one unwrap by hand keeps the general default failing closed and puts the
disclosure where a reviewer reads it.

**The hazard that clause forecloses is worth stating because it is invisible.** A
`TypeAdapter` over `SecretValue` serialises to `"**********"`. An implementation
that reached for pydantic's serialiser rather than the project's own projection
would therefore send ten asterisks as the credential; the hub would validate them
as a well-formed `SecretValue`, the provisioner would write them into the keyring,
the record would go active, and every in-process test would pass, because the
in-process engine never serialises anything. The failure would surface only at the
first egress call, as an authentication error against a credential nobody could
find a fault in by inspection. That is ADR-0125 §3's own warning about a helpful
store one layer out.

**Passing a credential across the engine surface is new, and ADR-0124 §6's
opposite rule does not reach it.** That clause — "it is never passed to the engine
surface" — is about the **device enrolment credential**, whose direction is the
reverse of this one: the hub mints it, the owner carries it to a device, and the
device presents it on a transport frame, so the engine surface is nowhere on its
path. An integration credential travels from the person to the hub's keyring, and
ADR-0149 §9's third clause states in terms that it "travels only in the request
that performs the act". §17 records that no sentence of ADR-0124 §6 becomes false.

### 7. Interruption, displacement, and the two failures that mean the act already landed

> **Normative.** `connect_account` and `reprovision_account` return only when
> ADR-0148 §6's **third** write has landed, and the `ConnectedAccount` they return
> carries `state=ACTIVE`, the identity supplied in that call, and the revision
> that act took. An implementation that returns after the first or second write,
> or that returns a `PENDING` record from either operation, does not conform.

> **Normative.** A `SecretStoreError` raised by `connect_account` or
> `reprovision_account` means the record write landed and the credential write did
> not, so the reference is **pending and not connectable**. This is derivable
> rather than declared by fiat: ADR-0148 §6 fixes the record as the first write and
> the credential as the second, and the record write reaches no keyring. A client
> reports the reference as left pending and the remedy as running the act again;
> no client reports it as unchanged.

> **Normative.** A `DisplacedProvisioningError` means the act wrote **nothing** —
> neither the record, nor the credential, nor the activation — because ADR-0148
> §6 rules that an act whose compare-and-swap fails "never held it and writes
> nothing" and that an activation writing nothing leaves the successor's record
> untouched. A client reports the act as not performed and the reference's state
> as unread, and resolves it by calling `connected_accounts` rather than by
> retrying blind.

> **Normative.** No implementation retries a displaced act, reorders ADR-0148 §6's
> three writes, splits them across calls, or rolls back a write that landed
> (ADR-0149 §9). No operation on this surface activates a record whose credential
> write it did not itself perform, infers an identity from a credential, or treats
> an absent credential as a reason to change a record's state (ADR-0149 §6).

> **Normative.** Where an operation's outcome is **not known** to a client — the
> call was cancelled, or its response was lost after the hub may already have
> committed — the client reports it as not known and never as either landed or not
> landed, and states the reference's state as unread until it has re-read
> `connected_accounts`. A cancelled client starts no new call in order to report,
> and the `CancelledError` still propagates (ADR-0139 §4, ADR-0060).

**The two "the act already landed" failures are the reason this section exists.**
A surface that reported every exception as "it did not work" would be wrong in
both directions on the two exceptions that matter most: a `SecretStoreError` on a
provisioning act leaves durable state a user has to act on, and a
`DisplacedProvisioningError` leaves none but leaves the reference in a state
somebody else just changed. Both are derived from ADR-0148 §6's fixed write order
rather than added to it, which is what makes them stateable at all — §17 records
that neither adds an obligation to §6.

**Reporting an unknown outcome as unknown is ADR-0139 §4's rule, transposed one
act over.** Its subject was an amendment composed of two ratified operations;
ADR-0148 §6's act is three writes inside one, and the property is the same: the
client cannot see which of them landed, so the honest report is that it does not
know, and the resolution is a read rather than a second write. This matters more
here than there, because the second write a hopeful client would send carries a
credential.

### 8. Disconnection says what was removed, and never more

> **Normative.** `disconnect_account` returns the `ConnectedAccount` it removed —
> the live record as it stood immediately before the removal entry was appended —
> or `None` when the reference had no live record to remove, which covers both a
> reference the store has never held and one whose latest entry is already a
> removal (ADR-0149 §5).

> **Normative.** A `None` return is **not** a report of a disconnection. No client
> presents it as one, as a confirmation that a credential was deleted, or as a
> statement that the reference does not exist. It says one thing: no live record
> was removed by this call.

> **Normative.** A `SecretStoreError` raised by `disconnect_account` means the
> removal entry **landed** and at least one credential deletion did not, so the
> reference is disconnected, the residual slots stay named by the store, and the
> remedy is to run `disconnect_account` again — which is idempotent and re-runnable
> (ADR-0149 §5). This is derivable rather than declared: §5 fixes the removal entry
> as the first step and the deletions as the second, and the removal entry reaches
> no keyring. A client reports the reference as disconnected **and** the credential
> deletion as incomplete, and never as a failed disconnection.

> **Normative.** No client presents a disconnection as having stopped a
> transmission already in flight, as having cancelled a provisioning act, or as a
> guarantee that the keyring holds nothing for that reference. ADR-0149 §5 states
> the weaker, true guarantee — that no live record names any slot for that
> reference — and no surface may state the stronger one.

> **Normative.** Disconnecting every reference is **not** ADR-0149 §8's purge and
> does not discharge ADR-0004 §6's delete right. No surface presents it as either,
> and no lane composes one out of the other.

**Raising rather than reporting a residue in a field is deliberate, and it is
ADR-0149 §5's own requirement doing the choosing.** §5 says the failure "is
reported and never suppressed". A boolean field saying the deletion did not
complete is exactly what an inattentive client suppresses — it renders the success
and drops the flag — whereas an exception cannot be ignored without being caught,
and a catch is a line a reviewer reads. The cost is that an operation both
succeeds and raises, which is unusual enough to be worth the clause above that
says precisely what a caller may conclude from it.

**The last clause closes an overclaim the two acts make available together.** A
user who disconnects every reference has caused every slot the store names to be
deleted, which looks like the purge and is not: ADR-0149 §8's purge is a
whole-installation act that also removes the store's entries and refuses whole
where any slot is unconfirmed, and it runs with no provisioning act concurrent.
Presenting a sequence of disconnections as discharging the owner's delete right
would be the "purge that skips a scope" ADR-0125 §5 forbids being presented as
complete, arriving by composition instead of by omission.

### 9. What the two listings answer, and why neither derives the other

> **Normative.** `connected_accounts` answers *what is connected now*, from the
> connection store's live records alone. `recent_connection_acts` answers *what
> was done*, from the store's history. No implementation derives either from the
> other, and no surface presents one as the other (ADR-0139 §1).

> **Normative.** `connected_accounts` returns the live record for **every**
> reference that has one, whatever tools the hub has registered, whatever
> integrations exist, and whatever configuration says. It returns the complete set
> or it fails: it is not paged, admits no `limit` and no `offset`, and no
> implementation truncates, samples or elides it. Where the result does not fit the
> configured frame it raises `OversizedValueError` and reports nothing.

> **Normative.** `connected_accounts` is computed from **one** read of the store,
> so it is a snapshot: no reference appears in it twice, none is missing because
> another was being written, and the set is internally consistent. It is not a
> claim that stays true after it is computed, and no client presents it as one.

> **Normative.** `recent_connection_acts` returns one `ConnectionAct` per act on a
> reference — per `(reference, revision)` pair — carrying the furthest
> provisioning state that act reached, in the store's own append order, newest
> first, bounded by `limit`. The store's entry granularity is `tools/`-internal
> (ADR-0149 §3) and is not exposed: no implementation returns two rows for one
> act, and no client reads the store's internal shape off this result.

> **Normative.** `recent_connection_acts` carries **no** instant, and no client
> presents its order as a timing claim, an interval, or a statement about when
> anything happened. Its order is the order the store recorded the acts in, and
> that is the whole of what a position means.

> **Normative.** No client derives a reference's current state from
> `recent_connection_acts`, and no client presents a row from it as live, as
> withdrawn, or as the account currently connected under that reference.
> `connected_accounts` is what states it.

**The non-derivability is structural rather than stylistic, and the unsoundness is
not the one ADR-0102 §3 found.** There, a clock correction could sort a revoking
record below the grant it revoked. Here revisions are monotonic per reference and
there is no clock at all, so that failure is unavailable — but the page boundary
supplies its own: `recent_connection_acts` is bounded by `limit`, so a reference
whose latest act falls outside the page is one a client walking the page reports
by an *earlier* act. A user with several connections and a busy history would see
a disconnected account reported as connected, on the deployment with the most
history and nowhere else, which is the failure that never shows up in a test.
Stating the rule over the shape rather than over the clock is what makes it hold
as the store's contents grow.

**`connected_accounts` is unpaged for ADR-0139 §2's reason, taken whole.** A
truncated answer to "what is connected" is a false answer rather than a partial
one, and there is no honest way for a client to tell the two apart. Failing with a
declared `OversizedValueError` puts the remedy where the operator can reach it
(§11) and leaves no shape in which a missing row reads as an absent connection.

**Answering from the store rather than from what the hub can offer is ADR-0139
§1's rule at its sharpest here.** A connection whose integration is no longer
built, whose tool is no longer registered, or whose configuration has been changed
is still a connection: the record exists, the credential exists in the keyring,
and the user is the only party who can end it. A listing that filtered by what the
hub currently holds would hide from the owner exactly the connections they most
need to see, and would hide them from the disconnection that is their only remedy.
ADR-0102 §4's revocation clause is the same instrument one axis over — a
configuration edit may never make a user's own act unwithdrawable.

### 10. Where the operations live, and the one Protocol this ADR places

> **Normative.** The five operations are implemented in `orchestration`, in one
> object that holds the provisioner seam below and nothing else that reaches the
> keyring or the connection store. `Engine` delegates to it. `orchestration`
> constructs no `SecretStore`, no `Secrets` and no connection store, and names
> neither keyring face (ADR-0125 §8, ADR-0149 §9).

> **Normative.** `core/protocols.py` gains **one** Protocol,
> `ConnectionProvisioner`, the seam by which `orchestration` reaches the
> provisioner in `tools/` (ADR-0149 §10). It carries exactly five members, one per
> operation in §2, with these signatures:

```python
class ConnectionProvisioner(Protocol):
    async def provision(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount: ...

    async def reprovision(
        self,
        reference: Identifier,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount: ...

    async def disconnect(self, reference: Identifier) -> ConnectedAccount | None: ...

    async def connected(self) -> tuple[ConnectedAccount, ...]: ...

    async def recent_acts(self, *, limit: int) -> tuple[ConnectionAct, ...]: ...
```

> **Normative.** `provision` takes **no** reference argument and accepts none
> under any other name: §3 makes the mint the provisioner's, so the engine passes
> nothing and `provision` returns the `ConnectedAccount` carrying the reference it
> minted. The other four members take the reference the engine received from its
> caller, unaltered.

> **Normative.** `recent_acts` takes `limit` with **no default**. The default is
> `AssistantEngine`'s (§2), and a seam repeating it would be a second place for one
> number to drift.

> **Normative.** Each member declares the failures §2a declares for the operation
> it serves, less the two the engine refuses **before** the seam is reached:
> no member declares `UnusableIdentityError` (§5 refuses locally and before any
> I/O, so no such call arrives) and none declares `ValueError` for an argument the
> engine has already validated. `OversizedValueError` is likewise not a seam
> failure: ADR-0085 §8c bounds a serialised payload, and nothing is serialised
> here.

> **Normative.** That Protocol's members return no credential value and no value
> derived from one, carry no `SecretName` in any argument or return type, and
> confer no keyring face on the object that holds them (ADR-0149 §10, ADR-0149
> §8). A `ConnectedAccount` and a `ConnectionAct` are the whole of what crosses it
> in the returning direction.

> **Normative.** The five members named here are what **this ADR** places on that
> Protocol. The enumeration is not a bar on a later ADR adding one: ADR-0149 §8's
> fourth clause leaves the purge's seam — "whether it is a seam of its own or a
> member of the one §9 defers" — to #909, and nothing here may be cited to
> foreclose that choice (§14).

> **Normative.** The provisioner is reached by `orchestration` through that
> Protocol and never by an injected concrete, and `orchestration` imports no
> module of `tools/` (golden rule 1). The composition root wires the one
> implementation.

> **Normative.** A CLI command for any of these is a client of the operation
> (ADR-0084 §5). `interfaces/` stays a thin adapter, holds no keyring face, builds
> no engine, and reads no connection store (golden rule 3, ADR-0084 §6).

**`orchestration` is forced rather than chosen**, for ADR-0102 §7's reason
unchanged: the operations are `AssistantEngine` methods, `AssistantEngine` is
provided by `orchestration` (ADR-0085 §1), `service/` holds no engine method, and
ADR-0149 §9 states the placement normatively anyway. What is new is the one thing
`orchestration` touches that it did not before — a `SecretValue` in transit — and
§6's relay clause is what keeps that from becoming a second path to the keyring.

**Holding a seam is not holding a face, and this ADR relies on a distinction the
corpus has already drawn twice.** ADR-0102 §7 drew it about the composition root
and `SourceGrantStore` — "Structural typing means the concrete store satisfies
`SourceGrants`, so a composition root passes one object to both; what the driver
cannot do is *name* `record`" — and ADR-0149 §8's tenth clause states it directly
for this neighbourhood: "holding such a seam is not holding a keyring face". The
object in `orchestration` names five members that take and return `core` types; it
cannot name `set`, `delete` or `get`, and no annotation on it mentions `Secrets`
or `SecretStore`. ADR-0125 §8's fourth clause therefore stays true of
`orchestration` word for word, which §17 checks.

**The mint is on the provisioner's side of the seam, which is why `provision`
takes nothing the engine could have supplied.** ADR-0149 §1 puts the act, and §3
the store, inside `tools/`, so the only component that can mint a reference into
that store is the provisioner. An engine-side factory would put the mint on the far
side of the boundary from the compare-and-swap it has to be atomic with, which is
the placement ADR-0149 §1 refused for the record's readers and refuses here for the
same reason.

**The members are named shorter than the operations they serve, deliberately.**
`AssistantEngine` needs `connect_account` because its namespace holds twenty-six
unrelated methods and a bare `connect` would sit beside ADR-0084 §2's connect
handshake, which also has a credential member — the near-neighbour collision
ADR-0102 §2 warns about. `ConnectionProvisioner`'s whole subject is connections, so
its members need no disambiguator; and members named identically to the engine's
would invite a reader to assume one forwards to the other unchanged, which the
mint asymmetry and §2a's declared-failure difference both say it does not.

### 11. The frame, the reserve, and the paging convention

ADR-0085 §8c bounds the whole serialised payload at `hub_max_frame_bytes - 512`,
which `Settings` defaults to 16 MiB with a floor of 1024 bytes (ADR-0085 §8d). The
arithmetic is stated because §8f states it for the belief page and because the
answers differ across these five.

- **The method names do not move ADR-0085 §8b's reserve.** The longest added here
  is `recent_connection_acts` at 22 bytes, against the tree's current longest,
  `set_notification_preferences` at 28. §8b's 110-byte worst case was computed at
  21 and the tree already stands at 117; 512 leaves several hundred bytes of
  headroom either way, which is the slack §8b says it chose deliberately. Nothing
  here corrects that figure, and §17 records why no ADR owes a record for it.
- **`connect_account` and `reprovision_account` are the calls a small configured
  frame refuses, and the credential is why.** `SECRET_VALUE_MAX_BYTES` is 1024
  bytes, and the payload budget at `hub_max_frame_bytes`' 1024-byte floor is 512.
  So a maximal credential does not fit the minimum frame, and neither does a
  credential much above half of it once the identity, the reference and the JSON
  punctuation are counted.

  > **Normative.** Where a provisioning call's arguments do not fit the configured
  > frame, the call raises `OversizedValueError` and nothing is written. No
  > implementation truncates a credential or an identity, splits a provisioning act
  > across frames, or falls back to another route. Raising `hub_max_frame_bytes` is
  > the operator's remedy and the only one this ADR offers.

  Fail-closed is the only available direction: a truncated credential is a
  credential that will fail authentication later with no evidence of why, and
  ADR-0084 §4 already forbids silent truncation on this surface. The reachable
  population is an operator who deliberately configured the floor, since the
  default is four orders of magnitude above any credential.
- **`connected_accounts` grows with the number of live connections** and each row
  has one unbounded factor — the identity, bounded by
  `ACCOUNT_IDENTITY_MAX_BYTES` (§5) — plus a minted reference, which
  `DurableIdentifier` does not bound. §9 makes it unpaged, so the whole set must
  fit or the call fails; with the identity bound in place the reachable way past a
  default frame is a very large number of connections or a factory minting very
  long references, and the declared `OversizedValueError` is the answer to both.

  > **Normative.** The lane that mints references chooses a bounded encoded form,
  > and records its width where the constant lives. A minting scheme whose output
  > is unbounded is refused by this clause rather than by a later frame failure.
- **`recent_connection_acts` is bounded by `limit` exactly as the other paging
  methods are**, and busts a 1024-byte frame at the default page for the same
  reason they do; ADR-0085 §8e's answer applies unchanged, a declared
  `OversizedValueError` whose `field` is `None` because the payload is a bare
  array.
- **`recent_connection_acts` takes `limit` and no `offset`**, following ADR-0102
  §10: an offset over a store that has none is either a store change this ADR does
  not own or an engine-side over-fetch-and-slice, which is a paging surface that
  lies about its cost. A keyword-only `offset` is additive the day the store gains
  one (§18).

**Nothing in `wire/` changes but the client's five methods**, and this is recorded
so the lane does not go looking for a table and so a reviewer can check the claim:
`METHODS` is derived from the Protocol by reflection, arguments and results are
validated from the annotations, and an error code is the exception class's own
name resolved over `core.errors` — the four new classes therefore cost the error
registry nothing. The client's five methods are unavoidable, because
`tests/wire/test_client_contract.py` binds `HubEngineClient` to
`AssistantEngineContract` and a missing method is a red gate. §6's unwrap lives in
two of those five and nowhere else.

### 12. Auditing: no ruling, no trail, and the listing is the discharge

> **Normative.** No `ActionPolicy` ruling is sought for any operation on this
> surface, no `PermissionDecision` is synthesised for one, and no `AuditTrail`
> record is written for one (ADR-0149 §7). No client presents any of these
> operations as authorised by a `PermissionDecision`.

> **Normative.** `recent_connection_acts` is the surface that discharges the
> record half of ADR-0004 §7 for a provisioning act, which ADR-0149 §7's second
> clause assigns to the append-only connection store. A store the owner cannot
> read is not a discharge of "transparent and reviewable", and this operation is
> what makes it one.

> **Normative.** A connection is not an authorisation and no surface presents one
> as permission to act (ADR-0149 §4). No ruling rests on the existence of a
> connection, no listing on this surface is presented as a list of what the
> assistant may do, and connecting an account is never offered as an alternative
> to a grant or to a confirmation.

**This is ADR-0102 §11's answer read forward rather than a new exemption.** There,
"`recent_grants` is the surface that discharges ADR-0097 §4's audit property", and
the reason no `AuditTrail` record is written is that a trail record is a permission
decision's and no decision is taken; ADR-0149 §7 states both halves for this act
already. What this section adds is only the identification of *which* operation
carries the discharge, which ADR-0149 §7 could not do because the operations did
not exist yet.

**The alternative — shipping no history listing — was seriously considered and is
refused.** It would have saved one method and one promoted type, and the argument
for it is that ADR-0149 §7 names the *store* rather than a surface. But ADR-0004
§7's sentence is about the assistant's behaviour being "transparent and
reviewable", and a Tier 1 store whose only reader is the code that writes it is
reviewable by nobody the clause was written for. ADR-0102 shipped `recent_grants`
against exactly this argument for exactly this reason, and a connection is the
sibling act one tier down.

### 13. The prohibitions

> **Normative.** No `ToolDefinition` binds any of the five operations, no plan step
> may reach one, no model-authored value may become an argument to any of them, and
> no scheduler job (ADR-0083 §7) may invoke one. A connection is created,
> re-provisioned and disconnected only by an explicit user act through a client
> (ADR-0149 §4).

> **Normative.** This surface adds no `Settings` field, defines no file the user is
> asked to edit, and reads no environment variable. No connection is created,
> re-provisioned, disconnected or inferred from a `Settings` value, existing
> configuration, an upgrade, a migration, a first run or a backup restore
> (ADR-0149 §4).

> **Normative.** **No lane exposes these operations over any transport other than
> ADR-0084 §1's loopback socket** — in particular not over ADR-0124's remote
> listener — before a ratified decision rules the credential's hop from an enrolled
> device to the hub. This is a named precondition on the remote-transport lane, in
> the form ADR-0021 §3 and ADR-0097 §9a use, and it is the question ADR-0149 §13
> assigns to this ADR by name.

**Two of the first clause's prohibitions are held mechanically and it is worth
recording which**, as ADR-0102 §8 did: `tools/` is a subsystem, subsystems never
import `orchestration`, and subsystems never import one another, so nothing a
model or a plan steers can reach an `AssistantEngine` method. The clause is
written anyway because it is the load-bearing one — ADR-0005 §3's "The model
proposes; a deterministic policy disposes" is what would be inverted — and because
ADR-0149 §1 already transposes ADR-0102 §8's prohibitions onto the provisioner,
which would be defeated one layer up if the operation calling it were reachable.

**The transport clause answers a question ADR-0149 handed over and answers it
conservatively.** ADR-0149 §13 says "§9's surface ADR decides which clients may
reach the operations", noting that "a credential crossing to the hub from a remote
spoke raises questions about that hop this ADR has no producer for". Every
disclosure argument this surface leans on is ADR-0084 §1's: ADR-0102 §6 admits
reading the user's own configuration back to them because it crosses a `0600`
socket and "discloses it to nobody", and a Tier 0 credential crossing an overlay
network is a different posture entirely — ADR-0124 §3 accepts a specific,
enumerated disclosure to a coordination service, and a credential is not on that
list. It is stated as a precondition on a lane rather than as a check the engine
performs, because an `AssistantEngine` method cannot see its transport and ADR-0098
§5's discipline forbids stating a bound this system cannot obtain as though it
could.

### 14. #909 is not decided here, and what stays blocked because of it

> **Normative.** This ADR does **not** decide who invokes ADR-0149 §8's purge, does
> not route ADR-0126's act to it, does not decide the seam that reaches it, and
> does not change any clause of ADR-0126. All of that stays with **#909**, where
> ADR-0149 §8's fourth and fifth clauses put it.

> **Normative.** ADR-0149 §8's precondition is carried forward unrelaxed: **no
> lane provisions a connection in an installation before a ratified decision routes
> the owner's delete right to that purge.** Nothing in this ADR is a route around
> it, and no lane cites this surface's existence, its merge, or the readiness of
> its implementation as satisfying it. The five operations may be built and tested;
> a connection may not be provisioned in an installation until #909 lands.

> **Normative.** The Protocol §10 places carries **no** purge member, and its
> five-member enumeration is not a bar on one. #909 stays free to add a member to
> it or to declare a seam of its own, which is the choice ADR-0149 §8's fourth
> clause reserves to it; no lane cites §10 to foreclose either.

**Deciding it here would have been overreach rather than diligence, and the reason
is ADR-0149 §8's own.** #909's three questions are: whether the purge is composed
or performed by a single holder, whether the coordinator is the hub or the offline
tool, and whether either needs a fourth face or a widened scope enum. ADR-0149 §8
answered the first and the third — composed by the consumer that wrote the
entries, and no new face or scope — and left the second because answering it
changes ADR-0126 §6's first marked clause, which is ADR-0126's to change. That
clause is no more this ADR's to change than it was ADR-0149's: a document about the
shape of five engine methods is not the one that reopens where the owner-delete act
lives, and ADR-0126 §6's forward clause is explicit that the question be decided
"by whoever creates it, at the moment they create it — rather than that it be
answered here in a package that may not answer it". The symmetric restraint is
right in this direction too.

**What this ADR does contribute to #909 is a narrowing, stated so the ruling lane
does not have to derive it.** If #909 chooses the **hub** as coordinator, the
coordinator is a component that already reaches the provisioner through §10's
Protocol, and adding a purge member to that Protocol costs one member and no new
boundary. If it chooses the **offline tool** (ADR-0126 §2's placement), the
coordinator is in `service/`, `orchestration`'s Protocol is unavailable to it —
nothing may import `service` and `service` runs no engine in that mode — and the
seam is a new one on `tools/`, which is the case ADR-0149 §10's correction was
about. That is a cost difference, not a decision, and it is offered as one.

**The precondition is why the third clause of §13 and this section are not
redundant.** §13's transport clause blocks a *route*; this one blocks the *act*.
Until #909 lands, an installation that ran ADR-0126's offline delete would keep
credentials the owner asked to destroy, which is the state ADR-0126 §6 forbids and
ADR-0149 §8 refused to authorise by silence. A surface ADR that shipped without
repeating it would be doing exactly that by silence one document later.

### 15. New `core` contract surface, flagged and not landed here

> **Normative.** This decision cannot be implemented without contract surface
> `core` does not have, all of it flagged here under golden rule 5 and **none of it
> added by this ADR**: five methods on `AssistantEngine`; one new Protocol (§10);
> three types and one constant in `core/types.py` (§4, §5); and four classes in
> `core/errors.py` (§2a).

> **Normative.** All of it lands in **one lane and one PR**: the `AssistantEngine`
> change with its conformance-suite additions, its canonical fake's new methods and
> `HubEngineClient`'s; `ConnectionProvisioner`'s full triad — Protocol, shared
> conformance suite, canonical fake in `ai_assistant.testing` with the concrete
> `Test…Contract` subclass; and that Protocol's **primary production
> implementation**, the provisioner in `tools/` with its store and its wiring. No
> lane splits the triad from the provisioner, and none lands the `AssistantEngine`
> change ahead of the seam (ADR-0137 §2 and §3, ADR-0149 §10, `CLAUDE.md` → "One
> subsystem per change" and its stated exception).

> **Normative.** This ADR adds **no** member to `SecretScope`, changes **no**
> signature on `Secrets` or `SecretStore`, adds no field to `ActionRequest`,
> `PermissionDecision`, `ToolDefinition`, `ToolCall` or `ToolResult`, adds no
> Protocol for the connection record or the connection store (ADR-0149 §3), and
> changes no existing `AssistantEngine` method. A lane that finds it needs any of
> those is changing a ratified decision and owes its own ADR.

**One new Protocol is what ADR-0149 §10 flagged and the count is unchanged.** §10
named "a Protocol by which `orchestration` reaches the provisioner in `tools/`",
said it was "not the whole of the contract surface this decision's neighbourhood
will need", and pointed at #909's routing seam for the rest. §10 above places
exactly the one, and §14 leaves the other where §10 left it.

**The single lane is forced rather than preferred, and the cut a lane would reach
for first does not exist.** The tempting split is a contract lane carrying the
`AssistantEngine` change and a later lane carrying the provisioner. It is
unavailable: `orchestration`'s concrete `Engine` structurally satisfies
`AssistantEngine`, so a change adding five methods to that Protocol is a change
that must implement five methods on `Engine`, and `Engine` can implement them only
through `ConnectionProvisioner` (§10). So the seam has to be in that same change —
and ADR-0149 §10 and ADR-0137 §2 then put its triad with the provisioner, which is
the third thing in the same lane. That is `CLAUDE.md`'s stated exception exactly:
the slice is cut at a contract seam because its implementation would otherwise put
new machinery into two subsystems, so the triad rides with its primary production
implementation as one unit of work rather than as three changes.

**What is genuinely separable is separated**, and it is the client: a CLI has no
Protocol obligation, `tests/wire/test_client_contract.py` binds `HubEngineClient`
rather than an adapter, and nothing in `interfaces/` is a second implementation of
anything this ADR adds.

### 16. What the implementing lanes owe

**The contract-and-provisioner lane**, as one change (§15):

1. The five methods on `AssistantEngine` with §2a's declared failures in their
   docstrings; `ConnectionProvisioner` in `core/protocols.py` with §10's five
   signatures; `ProvisioningState`, `ConnectedAccount`, `ConnectionAct` and
   `ACCOUNT_IDENTITY_MAX_BYTES` in `core/types.py`; and the four classes in
   `core/errors.py`.
2. **The `AssistantEngine` conformance suite gains a clause per ruling above that a
   store cannot exhibit**, which is the whole of §2a's local refusals, §5, §7, §8
   and §9's shape clauses:

   > **Normative.** The suite pins, at minimum: an identity equal to the supplied
   > credential's plaintext raises `UnusableIdentityError` with nothing written and
   > without reaching the store; an identity carrying a line break or a control
   > character does the same; an identity is returned byte-for-byte as supplied,
   > including one with leading and trailing whitespace and one differing from
   > another only by case; `connect_account` returns a record whose `state` is
   > `ACTIVE` and whose `revision` is the reference's first; `reprovision_account`
   > on a reference the store does not hold raises `UnknownConnectionError`;
   > `disconnect_account` on such a reference returns `None` and writes nothing;
   > `disconnect_account` on a reference whose latest entry is already a removal
   > returns `None`; `connected_accounts` includes a reference whose live record is
   > `PENDING`, with that state; `connected_accounts` includes a reference no
   > registered tool is bound to; `recent_connection_acts` returns one row per
   > `(reference, revision)` with `account=None` exactly for a removal; and
   > `recent_connection_acts` refuses a non-positive `limit` before any I/O.

   > **Normative.** The suite pins the two cases that distinguish a stated outcome
   > from a guessed one: a `disconnect_account` whose credential deletion fails
   > raises `SecretStoreError` **and** leaves the reference with no live record, so
   > a following `connected_accounts` omits it; and a `reprovision_account`
   > displaced by a concurrent act raises `DisplacedProvisioningError` and leaves
   > the store holding exactly what the displacing act wrote, with no entry from
   > the displaced one.

   Each is written as a required case rather than left to the prose for ADR-0102
   §12's reason: a clause a test cannot reach is worse than no test.
3. **`ConnectionProvisioner`'s triad in full** — the Protocol, a shared
   `ConnectionProvisionerContract` encoding §7's and §8's ownership and ordering
   rulings, and a canonical fake in `ai_assistant.testing` with the concrete
   `Test…Contract` subclass that runs it (`tests/core/test_protocol_triad.py`
   enforces the last part, and no exemption is available to a new Protocol).
4. **The `AssistantEngine` canonical fake gains the five methods**, scriptable to
   hold live records in both states, references with history and no live record, a
   store that raises, and a keyring deletion that raises — so a client's own
   refusal paths are reachable from a test.
5. **Five methods on `HubEngineClient`, in the same change**, each a `_call` plus
   the local refusals ADR-0085 §9 requires — §2a's `ValueError` cases, §2a's
   `UnusableIdentityError` clause and §11's `limit` rule — and, on the two
   provisioning methods, §6's single unwrap.
6. **A test that the wire client sends the credential's plaintext and not its
   redaction**, written against the encoded frame rather than against the client's
   arguments. This is the one failure §6 exists to prevent and the one an
   in-process test cannot see.
7. **A test that no operation's arguments reach a log**, exercised with a
   deliberately failing call, against `core/logging.py`'s redaction as well as
   against the absence of any payload logging in `wire/server.py`.
8. **The provisioner in `tools/` with its store and its wiring** — everything
   ADR-0149 §14 already requires of it, plus the reference mint (§3) with its
   bounded encoded form, and the engine-side object of §10 that delegates to it.
9. **Nothing else in `wire/` changes** — `METHODS`, the argument and result
   adapters and the error code are all derived from the contract (ADR-0102 §12
   item 5).

> **Normative.** That lane builds and tests the provisioner; it does **not**
> provision a connection in an installation, which §14's precondition forbids until
> #909 is ruled. A test fixture's temporary keyring is not an installation, and no
> lane cites this item as satisfying that precondition.

**The client lane**: the CLI commands behind the five operations — illustratively
`assistant connect`, `assistant reconnect`, `assistant disconnect`,
`assistant connections` and `assistant connection-log`, spellings the lane's under
ADR-0073 §1's form — with §5's display clause, §7's unknown-outcome clause, §8's
two report clauses and §4's `PENDING` clause each as a client-side test.

> **Normative.** The count claims in `core/types.py`'s promoted-surface comment and
> `wire/surface.py`'s module docstring are already wrong at `origin/main` —
> "nineteen methods" against a Protocol carrying twenty-six — and this ADR does not
> make them wrong. The lane above corrects them to the figure the tree then
> holds, and files nothing; the pre-existing drift is tracked separately and is not
> this lane's to investigate.

### 17. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**It amends nothing and supersedes nothing.** ADR-0082 §1 requires the judgement in
this ADR's text, clause by clause, against ADR-0070 §1's test: *would a reader
holding only the earlier ADR now act differently, or read one of its clauses more
widely than it now holds?* Applied to the seven places where the opposite reading
is available. Each ADR is read for **what it is relied on for**, which is ADR-0084
§12's semantic method rather than a phrase search.

**ADR-0149 §9 and §13 — no record owed, and this is the clearest of the seven.**
§9's second clause names this ADR by function and states its firing condition;
§13's remote-provisioning bullet says in as many words that "§9's surface ADR
decides which clients may reach the operations". Discharging a deferral by the
route the deferral itself specified is the mechanism working (ADR-0100 §11,
ADR-0102 §13), and every sentence of both stays true. §9's third clause is checked
property by property against this ADR: no response carries a credential value (§4,
§6); the credential travels only in the two requests that perform the act and comes
to rest only in the keyring (§6); no operation is bound by a `ToolDefinition` or
reachable by a plan step (§13); a refusal names the reference and not the identity
(§2a, §5); and the three writes stay the provisioner's, in order, with
`orchestration` neither reordering, splitting nor retrying them (§6, §7).

**The refusal clause is the one property of the five that needs the test shown
rather than ticked**, because §3's mint makes one of its two limbs inapplicable to
one operation. §9's sentence is "a refusal names the reference and not the
identity (§3)", and its "(§3)" is ADR-0149 §3's split: the reference is a
non-secret handle that may be logged, the identity is Tier 1 and may not. So the
clause has a **prohibitive** limb — never the identity — and a **permissive** limb
— the reference is the thing it is safe to name instead. §2a binds the prohibitive
limb across all five operations without exception, and honours the permissive limb
on the four calls that carry a reference. On `connect_account` the permissive limb
has no subject: the call carries no reference, and §3 mints one only as the first
record is written, so a refused act has none to name.

Would a reader holding only ADR-0149 §9 now act differently, or read the clause
more widely than it now holds? **No, in both directions.** Nothing they must do
becomes optional — the identity stays out of every refusal — and nothing they must
not do becomes permitted. What they find is that one operation's refusals have no
reference, which is a fact about the operation §9 deferred the shape of rather
than a sentence of §9 becoming false; §9's second clause hands that shape here in
as many words, and its third clause's own list is written as properties the shape
must have, not as a guarantee that every shape supplies a subject for each of
them. A reviewer who reads it the other way is invited to name the sentence of
ADR-0149 §9 that becomes false or over-wide, which is the showing ADR-0082 §1
requires — and to weigh, against it, that the alternative reading forces a
caller-authored reference, which ADR-0149 §3's loggability clause forecloses (§3
above). The two clauses cannot both be read at maximum strength, and this ADR
reads §3 at its strength because §3 is a marked clause about a durable value while
§9's is a marked clause about a message.

**ADR-0149 §3 and §4 — no record owed, and §3 is the one that needs the
argument.** §3's clause that a reference is a non-secret handle "chosen by code"
is *relied on* by §3 above rather than narrowed: minting is a reading of that
clause, not an addition to it, and a reader holding only ADR-0149 §3 would wire the
same store with the same fields. §4's clauses are consumed: the identity is
supplied by the user in the same act as the credential, recorded verbatim, refused
on equality and on shape, displayed back — this ADR fixes only *where the length
bound lives*, which §4 left to "the implementing lane" and which ADR-0085 §9
requires to be one value both implementations name. A lane holding only ADR-0149 §4
sets a bound and enforces it in the store, which stays exactly what they must do;
this ADR adds that the same constant is also what the client refuses against. That
is a stacked addition under ADR-0082 §1 — an obligation contradicting no sentence
§4 wrote — and it is recorded here and nowhere else.

**ADR-0148 §6 — no record owed.** Its clauses are consumed and not restated. §7
above states what a caller may conclude from two failures, and both conclusions are
*derived from* §6's fixed write order rather than added to it: because the record
write is first and reaches no keyring, a keyring failure implies the record write
landed; because a failed compare-and-swap "never held it and writes nothing", a
displacement implies nothing landed. Neither sentence of §6 becomes false or
over-wide, and no state, field or ordering is added. §4's two-member
`ProvisioningState` is §6's two states and §4's clause forbidding a third member is
§6's own rule expressed in a type.

**ADR-0085 §1's "and nothing else" — not owed, and the corpus has adjudicated it
twice.** ADR-0102 §13 sets out the showing in full — what the exclusion excludes is
*lifecycle*, ADR-0097 §9 had already ratified that a later ADR adds to this
Protocol, and "one closed graph" is a claim about types rather than about the
method count — and ADR-0139 added `standing_grants` on the same reading, recording
its partial supersession against ADR-0102 §1 rather than against ADR-0085 §1. §4
above shows this ADR's own closure walk terminating in `core`. Pointing at that
adjudication is what ADR-0082 §1's reviewer clause invites: a reviewer who reads
the test the other way is asked to name the sentence of ADR-0085 that becomes false
or over-wide.

**ADR-0102 §1 as partially superseded by ADR-0139, and ADR-0139 §§1–4 — no record
owed.** §1's surviving limb is about `SourceGrant`: "No other operation on any
surface creates, revokes, or reports a `SourceGrant`." No operation here creates,
revokes or reports one — ADR-0149 §4's marked clause already rules that a connection
record is not a `SourceGrant`, is not written to the grant store and is not read by
`SourceGrants.live` — and `GrantScope` gains no member. ADR-0139 §1's
non-derivability rule and §4's outcome vocabulary are read as **precedent** and
applied to a different pair of questions and a different compound act; neither is
narrowed, and `standing_grants` is untouched.

**ADR-0085 §8b's reserve and §8c's bound — not owed, and both are checked rather
than asserted.** §8b's worst case is computed from the longest method name; the
longest added here is 22 bytes against a tree whose longest is already 28, so this
ADR does not move the maximum and the 512-byte reserve stands with the headroom
§8b describes. §8c's payload bound is **applied**, not changed (§11): the
provisioning calls are measured against it and declare `OversizedValueError` like
every other method. That the tree's own worst case has drifted past §8b's stated
110 bytes is a fact about a prior lane's addition and is inside §8b's deliberate
slack; a record against ADR-0085 for it would be one this ADR is not the cause of,
which is not where ADR-0070 §1 puts a record.

**ADR-0124 §6 and §7 — not owed, and this is the one most available to a
misreading.** §6's clause "it is never passed to the engine surface" has as its
subject the **device enrolment credential** §6 mints, whose whole path is
hub → owner → device → connect frame; nothing about an integration credential is
in its scope, and a reader holding only ADR-0124 keeps their bootstrap credential
off the engine surface exactly as before. §7's admission rules and its ADR-0084 §2
clause are untouched, and §13 above adds a precondition that keeps this surface
away from the remote listener rather than putting anything new on it. What is
*taken* from §7 is its shape for the one authorised unwrap (§6), which is use as
precedent and not amendment.

**ADR-0125 §3, §8 and §12, and ADR-0126 §6 — not owed.** `SecretValue` is used as
ratified, including its own `ValueError` refusals, and no lane is given a second
way to build one. §8's four marked clauses each stay true: `models/` is untouched;
`tools/` still holds `Secrets` at the tool that needs one and `ToolRegistry` and
`ToolInvoker` still hold neither; the wire client's enrolment paths are untouched;
and the ten enumerated subsystems still hold neither face — `orchestration` among
them, which §10's seam clause is written to keep true. §12's provisioning bullet
was discharged in part by ADR-0149 and its note records the boundary; this ADR
neither widens that discharge nor touches the provider half. ADR-0126 §6 is
answered in part by ADR-0149 §8 and stays binding; §14 carries its prohibition
forward without relaxing it, which is the treatment ADR-0149 §12 records for the
same clause.

**No ADR's decision text, header or `Status` line is edited by this lane**, and
neither `VISION.md`, `CLAUDE.md`, `CONTRIBUTING.md` nor `docs/roadmap.md` is
touched.

**What would have owed a record and is deliberately not done.** Adding a timestamp
to a connection record (ADR-0149 §3); admitting a third `ProvisioningState`
(ADR-0149 §5); routing ADR-0126's act to ADR-0149 §8's purge (ADR-0126 §6, ADR-0149
§8); giving `orchestration` a keyring face (ADR-0125 §8); extending ADR-0087's
canonical projection to `SecretStr` (§6); and adding a `SecretScope` member.

### 18. Explicitly out of scope

Scoping something out is a decision, so each carries its reason and, where one
exists, the condition that fires it (ADR-0029 §7's form). Where ADR-0149 §13
already scoped something out, this list points at its clause rather than
re-deferring it.

- **Who invokes ADR-0149 §8's purge and the seam that reaches it** — **#909**, and
  §14 states what stays blocked. ADR-0149 §13's first bullet is where it lives.
- **What an integration *is*: an endpoint, a service identity, a scope list, an
  account chooser, or any argument beyond a reference, an identity and a
  credential.** ADR-0149 §9 names each as "a guess today and an observation once
  one exists", and the tree still holds no integration. The consequence is stated
  rather than hidden: a listing shows an identity and a minted reference with
  nothing saying *which service* the account is on, and a user with two accounts on
  two services tells them apart by the identity alone. **Fires with the first
  integration**, whose registration seam (ADR-0148 §11's surfaces (a) and (b)) is
  where an endpoint is already bound; adding an argument to `connect_account` is
  additive under ADR-0008 §1's pattern.
- **An interactive authorisation flow — OAuth or any redirect-based exchange.**
  ADR-0149 §13's bullet owns the reason: it is an egress call needing a designated
  seam, a canonicalisation and a ruling that do not exist, plus a loopback listener
  ADR-0084 §1 did not decide. What this ADR adds is the surface-side half: such a
  flow does not fit `connect_account`'s shape at all, because the credential
  arrives from a service rather than from the user, so it is a different operation
  rather than an argument on this one.
- **Rotation, expiry and re-provisioning *policy*** — ADR-0125 §12's third bullet
  and ADR-0149 §13, unchanged. This ADR says what a re-provisioning *is* and gives
  it an operation; it says nothing about when one is due, whether an expiry is
  tracked, or whether anything reminds the user, and nothing automatic may perform
  one (ADR-0149 §4, §13 above).
- **Provisioning from an enrolled device over the remote transport** — decided in
  part rather than deferred: §13's third clause refuses it until the hop is ruled,
  which is the answer ADR-0149 §13 asked this ADR for. **Fires with the lane that
  rules the credential's hop**, which owes it in the same change.
- **A recorded instant on a connection record**, and with it any timing claim on
  `recent_connection_acts` (§4, §9). It is a change to what ADR-0149 §3 rules a
  record carries, so it owes its own ADR. **Fires with the first surface that has
  to answer "when did I connect this?"** — a review or export surface being the
  likeliest.
- **An export or wholesale erasure of the connection store.** ADR-0101 §7 records
  that ADR-0004 §6's export right has no user surface at all and defers the whole
  question; this rides on that deferral rather than inventing a second answer for a
  seventh store, exactly as ADR-0102 §14 did for the grant store. **Fires with the
  lane that gives the export right a surface**, which owes this store's rows in the
  same change.
- **`offset` on `recent_connection_acts`.** Fires when the connection store gains
  one, and lands as a keyword-only argument under ADR-0008 §1's additive pattern
  (§11).
- **An idempotent "ensure this account is connected" operation, and any
  declarative expression of a connection.** Foreclosed by §3's mint — there is no
  user-chosen key to be idempotent over — and by ADR-0149 §4, under which nothing
  may create a connection from configuration. **Fires only with an ADR that gives a
  connection a user-chosen name**, which would have to answer ADR-0149 §3's
  loggability clause first.
- **What a client renders, and under what paging, beyond the clauses above.**
  ADR-0149 §13 assigns rendering to this ADR "bounded by §9's third clause"; §4,
  §5, §7, §8 and §9 fix every property a client may not choose otherwise, and the
  presentation inside those bounds is the client lane's.
- **Two accounts under one reference, and a reference bound to more than one
  tool.** ADR-0148 §6 rules one account per reference and one tool per account;
  nothing here widens either, and an integration serving several accounts gets
  several references and several tools.
- **Transport pinning** (**#83**) and the **payload manifest** (**#57**).
  ADR-0148 §13 owns both; nothing on this surface carries an endpoint or a payload
  description.

### 19. Marking, review and ratification

- **Marked under ADR-0089 §2, and the marks are the whole of what this ADR
  obligates** (§3 there). Unmarked text — the derivations in §1 and §3, the
  arithmetic in §11, the classification in §17 and the reasons in §18 — is read to
  determine what a marked clause means and supplies no obligation of its own,
  except where §18's bullets restate a marked clause elsewhere by citation.
- **Citations are in ADR-0088 §1's forms**, and no code citation carries a line
  number (§5 there): the modules and symbols named above are named by symbol.
- **The tree claims in the Context and in §11 were checked at `origin/main` on the
  branch this ADR was written on**, by running the code rather than by reading it:
  the `AssistantEngine` method count and longest name, `SECRET_VALUE_MAX_BYTES`,
  `project`'s refusal of a `SecretStr`, a `TypeAdapter` over `SecretValue`
  rendering `"**********"`, the inbound validation preserving the plaintext, and
  `core/logging.py`'s redaction of a key containing `credential`.
- **Drafted, reviewed and revised while `Proposed`**, with the required set —
  adversarial *and* architecture — run against it in that state, its status flipped
  only once both returned clean on one tree, and both re-run on the flipped tree for
  the coverage reason `CONTRIBUTING.md` → "Finishing an ADR PR" gives. Nothing
  implements against this ADR until it has merged (ADR-0015 §5), and no connection
  is provisioned in an installation until §14's precondition is met.

## Consequences

- **ADR-0149 §9's deferral is discharged and leg 12's actuator work waits on one
  decision rather than two.** ADR-0149's Consequences named the surface ADR and
  #909's coordinator ruling; the first is this document, and #909 is what remains.
- **A person can connect, replace and disconnect an account, and see what they
  connected.** The record ADR-0149 §3 keeps acquires a reader, which is what makes
  ADR-0004 §7's "transparent and reviewable" true of an act whose subject is a
  secret rather than true only of a store.
- **A credential crosses the engine surface for the first time**, and that is the
  real cost. `orchestration` now relays a Tier 0 value it must not read, and the
  wire client now performs an unwrap. §6's clauses and §16's two tests are what
  keep the blast radius at two methods; ADR-0087's projection continuing to refuse
  a `SecretStr` is what keeps the general default failing closed.
- **The user cannot name a connection**, because the reference is minted. Every act
  after the first goes through a listing, a client that offers connecting must
  offer listing, and there is no declarative or idempotent expression of a
  connection. That is the price of ADR-0149 §3's loggable reference and it is paid
  deliberately.
- **A listing says which account and not which service.** With no integration in
  the tree there is nothing honest to put there, and §18 records the firing
  condition. A deployment with two accounts on two services would find the surface
  thin, and no such deployment can exist before an integration does.
- **Two partial outcomes are now reportable as partial.** A provisioning act whose
  keyring write failed, and a disconnection whose deletion failed, each say which
  half landed instead of reading as a flat success or a flat failure — which is
  what stops a client telling a user their credentials are gone when they are not.
- **Nothing is provisioned yet.** ADR-0149 §8's precondition binds, `tools/egress`
  stays empty, and every one of ADR-0017 §3's conditions stays undischarged.

## Alternatives considered

- **A caller-supplied reference, on the grant surface's shape.** The obvious
  design, and the one every reader reaches for: the user names the connection and
  re-runs the same command to replace its credential. Refused in §3 because
  ADR-0149 §3 licenses a reference to be logged in the same clause that keeps the
  identity out of every log, which a user-typed value cannot satisfy — and because
  it makes a typo create a silent second connection on one operation and a silent
  no-op on another. What it would have bought is idempotence, which §18 records as
  foreclosed and names the ADR that could return it.
- **A `connectable_references` enumeration, as ADR-0102's fourth operation.**
  Unavailable rather than rejected: ADR-0148 §6 makes tool registration follow
  connection, so the set a client would choose from does not exist before the act
  that creates its members. This is the one place the grant precedent genuinely
  does not transfer, and the Context says why rather than leaving the missing
  fourth operation to look like an oversight.
- **One folded `connect_account` with an optional reference.** Four methods instead
  of five. Refused in §1 on ADR-0085 §9's ground that the declared failures differ
  between the two cases and a folded method tells a caller nothing about which
  apply — and because splitting them makes "I meant to replace and created a
  second" unreachable rather than merely visible.
- **A `Disconnection` result type carrying a `credentials_deleted` boolean.** One
  more promoted type, and the shape an author writes first. Refused in §8 because
  ADR-0149 §5 requires the failure to be "reported and never suppressed", and a
  boolean is precisely what a client suppresses by rendering the success and
  dropping the flag. An exception cannot be ignored without a `catch` a reviewer
  reads.
- **A `ConnectionActKind` enum discriminating a provisioning act from a removal.**
  Refused in §4: a fourth promoted type to encode what one optional field already
  says unambiguously, on a surface whose size is a contract clause — and an enum is
  the shape that invites the third member ADR-0149 §5 forbids.
- **Extending ADR-0087's canonical projection to unwrap a `SecretStr`.** The tidier
  implementation, and it would make the client's method a plain `_call` like every
  other. Refused in §6 because it is general where the need is specific: it would
  silently encode every secret any promoted value ever came to carry, removing the
  property ADR-0125 §3 bought, that unwrapping is a line somebody had to write.
- **A plain bounded `str` for the credential argument**, avoiding the wire question
  entirely. Refused for the same reason one level down: `SecretValue`'s redaction is
  what makes an accidental log a deliberate act, and ADR-0125 §3 forbids
  reimplementing the redaction or the accessor under another name. The wire
  question is answered once, in two methods, rather than avoided everywhere.
- **Shipping no history listing**, leaving ADR-0149 §7's record half to the store
  alone. One fewer method and one fewer type. Refused in §12: ADR-0004 §7's
  "reviewable" is about a person, and ADR-0102 shipped `recent_grants` against the
  identical argument for the identical reason.
- **Paging `connected_accounts`.** Refused in §9 on ADR-0139 §2's ground that a
  truncated answer to "what is connected" is a false one rather than a partial one,
  with no shape in which a client can tell the two apart.
- **Deciding #909's coordinator here**, so that one ADR unblocks the implementation
  entirely. Refused in §14: it changes ADR-0126 §6's first marked clause, which
  ADR-0126 §6 itself says belongs to whoever creates the entry rather than to a
  package that may not answer it — and this ADR is a document about five engine
  methods, which is further from that act than ADR-0149 was.
- **Presenting the operations over ADR-0124's remote listener**, so an enrolled
  device could provision. Refused in §13: every disclosure argument this surface
  rests on is ADR-0084 §1's `0600` socket, and ADR-0124 §3's accepted disclosure
  list does not include a Tier 0 credential. Stated as a precondition on that lane
  rather than as a check, because an `AssistantEngine` method cannot see its
  transport.
