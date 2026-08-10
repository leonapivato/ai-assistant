# 125. One seam to the keyring, reading narrower than writing, and an unreachable keyring is not an absent secret

- Status: Proposed
- Date: 2026-08-09
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-09**,
  the durability form ADR-0100 established. Three of the ADRs this decision rests
  on — ADR-0004, ADR-0017 and ADR-0124 — carry supersession records written within
  the last two days, and a citation that silently means "whatever this ADR says
  when you read it" is not checkable. Where a later ADR changes one of them, this
  one is read against the text named here until an ADR says otherwise.
- **This ADR partially supersedes ADR-0004 and ADR-0124, and both records land in
  this change.** One clause each, and they are the same clause twice: §3 of the
  first and §6 of the second each name `SecretStore` as the Protocol a consumer
  reads credentials through, and §1 below gives a read-only consumer the reading
  face of that seam instead. §13 applies ADR-0070 §1's test to both and states what
  survives, which is nearly all of both sections — including §3's keyring rule and
  every one of §6's obligations about where the device credential lives, what may
  read it, and what may never see it. No ratified text of either is rewritten; each
  `Status` line and its appended dated note are the whole of the record (ADR-0070
  §1, ADR-0082 §1 and §2).
- **No implementation lands with it.** No `src/`, no `tests/`, no `pyproject.toml`.
  The Protocol, its shared conformance suite and its canonical fake are the triad
  lane, briefed against this text once it merges (golden rule 5, ADR-0015 §5,
  `CONTRIBUTING.md` → "Adding a Protocol"). The keyring-backed implementation is a
  third lane behind that.
- **It decides `core` surface, and that is the whole point of it.** Two Protocols
  in `core/protocols.py`, three types in `core/types.py` and two errors in
  `core/errors.py`, each specified in §§1–6 closely enough that the triad lane
  builds from this text rather than from a fresh judgement. ADR-0124's header
  records that no `core` surface was decided there and that a lane finding it
  needed some would owe its own contract ADR; this is that ADR.
- **Its required review set is adversarial *and* architecture.** It fixes a
  contract surface, a placement rule for a concrete that has no package yet, and
  the shape a still-open question (#74) has to be able to land into. Every one of
  those is answerable from prose before an implementation commits to an answer
  (`CONTRIBUTING.md` → "Contract ADRs land before their implementation").

## Context

### What is provisioned, undeclared, and now blocking

ADR-0004 §3 has said since ratification that "the `models/` and `tools/` layers
read credentials through a small `SecretStore` Protocol (added to
`core/protocols.py`) so the keyring backing can be faked in tests and swapped per
platform". `core/protocols.py` does not declare it and never has. That was
tolerable for as long as nothing needed it: ADR-0029 §6 recorded the deferral
precisely rather than leaving it ambiguous, and observed that nothing was blocked
by it, because a tool needing a secret is a tool reaching an external service and
the `tools/` egress seam stays undesignated until every ADR-0017 §3 condition
holds.

ADR-0124 §6 ends that. Its marked clause is unconditional:

> The client reads the credential through the `SecretStore` Protocol ADR-0004 §3
> provisions, and through no other path to the keyring. Because
> `core/protocols.py` does not declare it, that Protocol and its triad are a
> **prerequisite of the client half of the remote transport** — their own contract
> ADR, merged before anything implements against it.

So the queue is: this decision, then the triad, then the client half of the hop
(#892, #883).

### Three consumers, arrived at three different times, and none of them alike

ADR-0004 §3 named two. ADR-0124 §6 added a third and ADR-0124 §12 recorded it as a
stacked addition under ADR-0082 §1, because §3's sentence is scoped to "the
`models/` and `tools/` layers" and a client in `wire` contradicts nothing it says.
The three want different things, and a contract written for any one of them alone
would be wrong for the other two:

- **`models/`** wants to *read* a provider credential on the way to a completion.
  It never provisions one; the owner does, out of band.
- **`tools/`** wants a tool to *read* its own integration credential, inside
  `tools/`, with ADR-0029 §6's rule intact — no credential value crosses the
  invocation seam in either direction, ever, and `invoke` grows neither a
  `credentials=` parameter nor a `SecretStore` argument.
- **the wire client** wants to *write* at enrolment, *read* on the connect path,
  and *delete* at unenrolment (ADR-0124 §6, §8). It is the only consumer that
  writes, and the only one holding something that is not itself a secret: the
  enrolled hub identity travels beside the credential and ADR-0124 §6 states
  plainly that "the hub identity is not a secret".

### What the tree actually holds, checked rather than remembered

- `core/protocols.py` declares twenty-three Protocols and none of them is this one.
- `core/errors.py` has no secret-store error. Its shape is settled and consistent:
  a subsystem base under `AssistantError`, narrowed subclasses only where a
  caller's correct response differs, and `IncompatibleStateError` as the standing
  example of a class carved out so an entry point can map a deployment fault to an
  exit code by a type check rather than a string match.
- `pyproject.toml` does not depend on `keyring`. Nothing in `src/` imports it.
- The only Tier 0 credential this system holds today is the model provider key,
  and `models/provider.py` never reads it: pydantic-ai's own provider construction
  reads it from the process environment, which is why `_check_provider_importable`
  is "deliberately key-free and offline" and why ADR-0062 §2 drew the boundary it
  did. That is the **unmet** state of a ratified rule, not a permission ADR-0004 §3
  granted.
- The suite/fake/binding triad is mechanically enforced by
  `tests/core/test_protocol_triad.py`, whose `EXEMPTIONS` list is now empty — so a
  Protocol declared without its triad fails the gate, and a new Protocol may not
  buy itself an entry.
- Two Protocols may share one conformance-suite module and one canonical fake:
  `tests/permissions/source_grant_contract.py` does it for `SourceGrants` and
  `SourceGrantStore`, and `TraceStore(TraceSink, TraceRetention, Protocol)` is the
  corpus's shape for a composed seam.

### What is genuinely open here, and what only looks open

Two questions arrive attached to this one and neither is settled by ratifying a
storage seam.

**#74 — does ADR-0004 §7's Tier 0 gate reach a credential read?** ADR-0017 §2
names it as one of three pre-existing gaps in `models/`; ADR-0017 §3 makes
"credential access gated, not just transmission" a condition on designating the
`tools/` egress seam; ADR-0021 §3 defers gating direct Tier 0 access pending it;
and ADR-0124 §6 supersedes §7's gate for exactly one read — the client's bootstrap
read — and forbids any lane citing that exemption to widen it. ADR-0029 §6 states
the trap this ADR has to avoid by name: a `SecretStore` shaped without #74's
answer "would either smuggle a gating decision into a `get(name) -> str` signature
or ratify one that has to break when #74 lands, which is the shape ADR-0016 §5
calls 'a contract whose author expects it to break'". §9 below is the answer, and
it is neither of those two.

**ADR-0078 §11's secret-tier `ASK_USER` arm.** It is the one arm of the memory
policy that ADR-0078 does not make answerable, and §11 gates closing it on "the
`SecretStore` seam ADR-0004 §3 names and that `core/protocols.py` does not yet
have — payload in the keyring, a non-secret reference in the queue, and a
read/export/delete path across the two", with the owner named as "a `SecretStore`
lane, gated on a producer existing". A lane called the `SecretStore` lane could
read that as a summons. §10 below reads the second half of the sentence instead,
says what this contract supplies toward it and what it does not, and leaves the
arm where §11 put it — because saying nothing would let silence be read as an
answer, and both available answers are wrong.

## Decision

### 1. One seam to the keyring, in two faces: `Secrets` reads, `SecretStore` writes

> **Normative.** `core/protocols.py` declares two Protocols. `Secrets` has one
> method, `get`. `SecretStore` extends `Secrets` and adds `set` and `delete`. Both
> are `@runtime_checkable`, and one object satisfies both structurally, so a
> composition root builds one implementation and hands each consumer the face its
> job needs.

> **Normative.** Every method on both Protocols is `async`.

> **Normative.** The two Protocols are declared with exactly the signatures below.
> A lane that changes one of them is changing this decision and owes an ADR.

```python
@runtime_checkable
class Secrets(Protocol):
    async def get(self, name: SecretName) -> SecretValue | None: ...


@runtime_checkable
class SecretStore(Secrets, Protocol):
    async def set(self, name: SecretName, value: SecretValue) -> None: ...

    async def delete(self, name: SecretName) -> bool: ...
```

Docstrings are elided there and are not optional: §§2–7 are what they have to
say, and `core/protocols.py`'s existing Protocols are the standard for how much
of it belongs on the method.

**`async` is this corpus's convention and here it is also the stronger answer.**
`CLAUDE.md` puts I/O-bound methods on `async` so the system composes on one event
loop, and `core/protocols.py`'s own guidance repeats it. A keyring call is a round
trip to an operating-system service, which would be reason enough; what makes it
decisive is that a *locked* store prompts the owner, so the call's duration is
bounded by a human rather than by I/O. ADR-0083 puts the hub on one event loop, and
a synchronous read there would stall every other connection for as long as the
owner takes to type a passphrase. Running the synchronous backing library in a
worker thread is the implementation's business, and it is precisely the shape
ADR-0054 ruled on — a cancelled call must not release what a worker thread still
holds — so that rule is inherited rather than restated.

Getting this wrong in either direction is a real failure and not a stylistic one:
a synchronous `get` returns a value to a consumer that wrote `await`, and an
asynchronous one returns an un-awaited coroutine to a consumer that did not.

The shape is `SourceGrants` and `SourceGrantStore`'s, taken deliberately rather
than by resemblance: the same problem produced it, which is that a seam with one
writer and several readers should not hand every reader the ability to write. Here
the concrete case is sharp. A tool holding a three-method store can delete the
device's enrolment credential, and nothing in the type system or the review
process would notice — the two entries sit in one keyring behind one object. With
the split, the tool's dependency cannot express the call.

`Secrets` rather than `SecretReader`, because `Reader` is already a Protocol in
this system with an entirely unrelated meaning (`readers/`, read-only ingestion,
ADR-0095), and a `SecretReader` beside it would be read as one of those. The
corpus's own convention for the reading half of a seam is the bare plural, which
is what `SourceGrants` is.

**The names ADR-0004 §3 and ADR-0124 §6 use both still resolve**, which matters
because ADR-0124 §6's clause is marked. The seam is `SecretStore`; `Secrets` is its
reading face and not a second path to the keyring. §13 records the check.

### 2. An entry is named by a scope and a key, inside one installation

> **Normative.** `core/types.py` gains `SecretName`, a frozen model with exactly
> two fields: `scope`, a `SecretScope`, and `key`, a bounded token. Two
> `SecretName` values name the same entry when and only when both fields are equal.

> **Normative.** `core/types.py` gains `SecretScope`, an enum with exactly three
> members — `PROVIDER` for a model provider credential, `INTEGRATION` for a tool's
> credential for an external service, and `ENROLMENT` for the device credential and
> the enrolled hub identity ADR-0124 §6 places on the device. A fourth consumer
> needs a fourth member, which is `core` surface and therefore its own ADR.

Closing the enum is the point of it. ADR-0004 §3's discipline — one contracted path
to the keyring, not a bespoke one per layer — is today a sentence a lane can
overlook. As an enum it is a compile-time question: a subsystem with a secret to
hold has to name the scope it belongs to, and if none of the three fits, the
mechanical answer is the same as the ratified one, which is that adding it is
contract surface and owes an ADR. ADR-0004 §4's application-level encryption key is
the immediate example — it is held in the OS keyring by a ratified clause, no
member covers it, and wiring `memory/` to this seam is consequently a decision
somebody has to make on the record rather than a wiring detail (§12).

> **Normative.** A `key` is one to sixty-four characters drawn from lowercase ASCII
> letters, digits, `.`, `_` and `-`, beginning and ending with a letter or digit. No
> uppercase, no whitespace, no control character, no non-ASCII character, no `:` and
> no `/`. A value violating this raises `ValueError` at construction, so no store
> method ever receives a malformed name.

**The character rule is a portability rule and each exclusion earns its place.**
The concrete implementation composes the backend's own coordinates out of an
installation namespace, the scope and the key, and that composition must be
injective — two distinct `SecretName` values that collide on the backend are one
secret silently overwriting another. Two things break injectivity. A component
containing the joining character, which is why `:` and `/` are excluded rather
than merely discouraged. And case, which is the subtler one: at least one
mainstream backend treats its target names case-insensitively, so `github` and
`GitHub` would be one entry on that platform and two elsewhere — a system that
stores a credential on Linux and cannot find it on Windows, or worse, finds a
different one. Forbidding uppercase makes the mapping injective on every backend
rather than on most.

> **Normative.** A `SecretName` is not itself a secret. It may be logged, held in a
> Tier 1 store, carried in an error and shown to the owner. A caller may therefore
> never encode a secret value into a `key`.

The permission and the prohibition are one clause because each is unsafe without
the other. Diagnosing "the keyring has no entry for this" requires saying which
entry, and ADR-0055 already set this posture for a comparable question about what
is safe to emit. What makes it safe is that the name is chosen by the code and not
by the secret; a `key` derived from a credential would put a Tier 0 value into
every log line that mentions it. This is also the clause ADR-0078 §11's "non-secret
reference in the queue" would rest on (§10).

> **Normative.** A `Secrets` or `SecretStore` instance is bound to one
> installation, and two installations on one machine share no entry. The
> installation is the one ADR-0084 §9 already uses to locate everything else — the
> resolved `Settings.data_dir` — and the implementation receives its namespace by
> injection rather than reading a setting itself.

> **Normative.** An instance is bound to exactly one `SecretScope` as well. Every
> method raises `ValueError` for a `SecretName` whose `scope` is not the
> instance's, before reaching the keyring, and a consumer therefore reaches only
> the scope it was given.

**Without the scope binding, §8's consumer boundary is a sentence rather than a
mechanism, and the gap is the whole seam.** A `SecretName` carries its scope as
data and §2 makes it safe to log, so a tool holding a `Secrets` bound only to an
installation can construct an `ENROLMENT` name — a value it can read off this ADR
— and read the device credential ADR-0124 §6 spent a section confining. Splitting
read from write (§1) does not touch that: the whole attack is a read. Binding the
scope to the object is what makes "for `INTEGRATION`-scoped reads" a property of
the thing the tool is holding rather than a rule the tool is trusted to follow.

**It is a `ValueError` and not a permission refusal**, because nothing was denied:
a call for another scope is a consumer holding the wrong instance, which is a
wiring fault at the composition root and reproduces identically on every attempt.
`PermissionDeniedError` would say a policy ran, which §9 is explicit that none
did; a `SecretStoreError` would say the store failed. The corpus's spelling for an
argument a seam refuses on its own terms is `ValueError`, and it is what
`SecretName` and `SecretValue` already raise.

**The residual is named rather than hidden: within `INTEGRATION`, one tool can
read another's credential.** Per-tool confinement would need a scope per tool,
which §2's closed enum forbids by design. It is accepted because tools are code in
this repository behind ADR-0016's registry rather than third-party plugins, so the
boundary crossed would be one between two modules the same review approved. A
plugin model would change that answer, and the fix would be additive — a
capability narrower than a scope, handed out at the same wiring point.

**Without this the second hub on a machine silently shares the first's
credentials.** ADR-0083 puts one resident process per data directory, so two data
directories on one machine is a supported deployment and a routine one during QA.
The keyring is per OS user, not per data directory. A test hub enrolling a device
would overwrite the owner's real credential, and a test unenrolment would delete
it — data loss produced by a namespace nobody chose. Binding the instance rather
than putting the namespace in `SecretName` keeps every caller out of it: a
consumer names the entry it wants and cannot name another installation's.

**The accepted cost is that moving a data directory orphans its entries.** The
owner re-enrols the device and re-enters a provider key; nothing is lost that
cannot be re-provisioned, and the alternative failure — two installations quietly
sharing one credential — is the one that cannot be noticed. A `Settings` field
overriding the namespace is additive later, and no lane should add one without a
deployment asking for it.

### 3. A value is bounded text that redacts itself

> **Normative.** `core/types.py` gains `SecretValue`, the type both `get` returns
> and `set` accepts. It validates its plaintext as non-blank and UTF-8 encodable —
> `NonBlankEncodableText`'s obligations, including that type's own refusal to
> normalise what it accepts — and additionally refuses a plaintext whose UTF-8
> encoding exceeds **1024 bytes**. A violation raises `ValueError` at construction.

> **Normative.** `SecretValue` is built on `pydantic.SecretStr`, so its `repr` and
> its `str` disclose no part of the plaintext and the plaintext is reached only
> through that class's own accessor, `get_secret_value`. No implementation may
> define a `SecretValue` whose default rendering is the secret, and no lane may
> reimplement the redaction or the accessor under another name.

> **Normative.** `core/types.py` also exports `secret_value`, the callable that
> applies those refusals and returns the validated `SecretValue`. It is the only
> supported way to build one, and every clause in this ADR saying a violation
> "raises `ValueError` at construction" means through it.

```python
type SecretValue = Annotated[SecretStr, AfterValidator(secret_value)]


def secret_value(value: SecretStr) -> SecretStr: ...
```

**The callable is not decoration, and leaving it out would have made §3's
promise false.** An `Annotated` alias is a *field* annotation: pydantic runs its
`AfterValidator` when a model carrying the field is validated, and calling the
alias directly constructs the bare `SecretStr` origin with no validator in the
path. So a blank or oversized value could reach `set` through a direct
construction while this ADR claimed it could not. `core/types.py` already carries
the answer — `encodable_text` is the callable beside `EncodableText`, and
`core/errors.py` calls it in a constructor for exactly this reason — and this
follows it. Both spellings are then real: a model field annotated `SecretValue`
validates through pydantic, and a hand-built value validates through the callable.

Building on the library's type rather than writing one is the other half of the
decision: the redaction and the accessor are then the ones every reader of this
codebase already knows. It is also what makes the accessor nameable here, which
the client half needs — ADR-0124 §7 requires the connect frame's credential member
to be a JSON string, so the client unwraps with `get_secret_value` immediately
before encoding and nowhere else.

**The redacting type is the mechanism, not a convenience.** `core/logging.py`
redacts by key name — ADR-0124 §6 relies on exactly that, requiring that no
implementation "give it a name that redaction misses". A plain `str` return keeps
that promise only as long as every call site chooses a covered key, and the whole
history of credential leaks is call sites that did not. A type whose default
rendering is `**********` inverts the default: a leak requires somebody to write
the unwrapping call, which makes it deliberate and reviewable rather than
accidental. The claim being made is exactly that and no more — an unwrapped value
can still be logged, and this ADR does not pretend otherwise.

**1024 bytes, and the arithmetic is the reason.** Backend limits differ and the
tightest among the ones a cross-platform keyring selects is a credential blob of a
few kilobytes stored UTF-16, where a character of value costs two bytes of storage.
A UTF-8 byte budget of 1024 converts to at most 2048 UTF-16 bytes — every character
costing k UTF-8 bytes costs at most 2 when k ≤ 3 and exactly 4 when k = 4, so twice
the UTF-8 budget bounds it in every case — which clears every mainstream backend
with margin. Above that, a value stores on one platform and fails on another, and
the failure arrives on the owner's machine rather than in CI. This is the shape
ADR-0124 §6 used for ADR-0085 §8d's 256-byte connect bound: a credential scheme
that does not fit is **refused by this clause** rather than discovered later, and
raising the bound is an amendment somebody argues for.

Every credential this system holds or plans to hold sits far below it: ADR-0124
§6's is 128 bits of `urandom` in an encoded form of a few tens of bytes, a provider
API key is around a hundred, and an OAuth refresh token is a few hundred.

> **Normative.** A value is stored and returned **verbatim**. No implementation
> trims whitespace, normalises Unicode, changes case, re-encodes, or alters the
> plaintext in any way between `set` and a subsequent `get`.

This is stated because the corpus has a normalising habit for good reasons
elsewhere — ADR-0121 §1 casefolds and normalises where two spellings of a name
should be one thing — and a credential is the exact inverse. Two spellings of a
secret are two different secrets, and a store that helpfully stripped a trailing
newline would produce an authentication failure nobody could reproduce by
inspection.

### 4. What `get`, `set` and `delete` mean

> **Normative.** `get(name)` returns the `SecretValue` last written under `name` in
> this installation, or `None` if there is none. It reads nothing else, consults no
> policy, writes no record, and creates no entry.

> **Normative.** `set(name, value)` stores `value` under `name`, creating the entry
> or replacing whatever it held. It never refuses on the ground that an entry
> already exists.

> **Normative.** `set` validates `value` through `secret_value` at its own
> boundary, before touching the keyring, and raises `ValueError` for one that does
> not satisfy §3. An implementation may not rely on the annotation having been
> honoured upstream.

**Without the boundary check §3's promise is false, and the reason is a property
of `Annotated` rather than of this design.** `SecretValue` is
`Annotated[SecretStr, …]`, which has no runtime identity distinct from
`SecretStr`: pydantic runs the validator when a model field carrying the
annotation is validated, and a caller who builds `SecretStr("")` or a
2 KB one and passes it directly satisfies every static check while the validator
never runs. `core/types.py`'s existing aliases have the identical property and
`core/errors.py` already answers it the same way — `AssistantError.__init__` calls
`encodable_text` on every string argument rather than trusting that
`EncodableText` was honoured. So the annotation is the declaration, the callable
is the enforcement, and the seam calls it.

> **Normative.** `delete(name)` removes the entry under `name` and returns whether
> one was there. It raises nothing for an absent entry, and calling it repeatedly is
> safe.

**Replace rather than refuse, because rotation is the case that matters.**
ADR-0124 §6 makes re-enrolling a device that already has a live enrolment a single
act that mints a replacement credential, and forbids an intermediate state. A
store that refused an occupied name would force delete-then-set at the device, with
a window in which the device holds nothing and a crash in that window leaving it
unenrolled. Last-write-wins is what lets the device-side half of that act be one
call.

**`delete` returns a `bool` rather than raising, for the reason the corpus already
uses it.** `DeferralStore` spells absence and refusal with a `None` return or a
`bool` where a spelling exists, and raises only for faults. Here the caller is
ADR-0124 §8's device-side unenrolment, whose whole job is to make sure the entry is
gone; an unenrolment that raised the second time it ran would be a worse surface
for the one operation an owner performs when something has already gone wrong.

> **Normative.** A `get` never observes a partially written value: it returns
> either what a concurrent `set` wrote or what preceded it, never a mixture and
> never a fragment. Concurrent `set`s of one name leave one of the written values
> whole.

> **Normative.** Nothing further is guaranteed under concurrency, and two
> assumptions are named as forbidden because they are the ones a caller would
> reach for. `delete`'s `bool` is **not** a synchronisation primitive: two callers
> deleting one entry may both be told `True`, so it may never be used to elect a
> winner or to make an operation happen exactly once. And there is no atomicity
> **across** names — no transaction, no compare-and-set, no multi-name write.

**The claim is stated in the weaker, true form, which is this corpus's posture
rather than a hedge.** An earlier draft said each method is "atomic with respect
to concurrent callers", which reads as one `delete` winning; no cross-platform
keyring offers a compare-and-delete, so an implementation doing a read followed by
a removal would tell both callers `True` and be conforming on the backing that
exists. Ratifying an obligation the chosen backing cannot meet is the failure
ADR-0016 §5 names, and it is the same reason §5 above refuses enumeration.
`core/protocols.py`'s cancellation clause makes the identical move for the
identical reason — "the rule is cooperative and is stated in the weaker, true
form: no seam can stop work that declines to be cancelled" — and buys the same
thing, which is that what the contract does promise is true everywhere.

**Nothing needs the stronger property.** ADR-0124 §8's unenrolment needs the entry
gone, not a winner elected; two unenrolments racing is an owner running one command
twice. If a consumer ever does need mutual exclusion over a secret, the place for it
is a lock the consumer owns, not a return value from a keyring.

**These are caller-facing rules rather than suite obligations**, because a shared
suite running in one process cannot prove or refute any of them portably. Saying
so here is the point: the contract states what a caller may not assume, which is
the enforceable half, and §11 does not pretend to test it.

**Two entries can therefore be half-written, and ADR-0124 already handles it.** A
device holds a credential and an enrolled hub identity as two entries, and a crash
between the two `set` calls leaves one. That is not a gap this seam must close,
because ADR-0124 §6 already rules that "holding the credential without the hub
identity is an incomplete enrolment the client refuses to connect on" — the client
must detect exactly this state whatever the storage does. A client that prefers to
avoid it entirely may store the pair as one value under one name; both satisfy
ADR-0124 §6 and this ADR rules neither in.

Cross-name atomicity is refused rather than deferred because no backend a
cross-platform keyring selects offers it, and contracting an obligation the chosen
backing cannot meet is the failure ADR-0016 §5 names.

### 5. What this seam refuses to be

> **Normative.** There is no enumeration. No method lists the entries in an
> installation, in a scope, or at all. Every caller reaches an entry by naming it.

Three reasons, and the first alone would be enough. **No consumer needs one**:
each of the three knows the names it wrote. **The blast radius**: an enumeration
turns "this object can read the secret I gave it a name for" into "this object can
discover and read every secret on the machine", which is a different capability
and a strictly worse one to hand a tool. And **portability**: a cross-platform
keyring's common surface is get, set and delete, and enumeration is where backends
diverge most, so contracting it would ratify something the backing may not be able
to answer. It is additive later if a consumer and a portable mechanism both turn
up.

> **Normative.** A complete purge of Tier 0 data is therefore composed from the
> names its holders know, and every consumer that writes an entry owes a path that
> deletes it. No lane may present a purge that skips a scope as complete.

This is the honest consequence of refusing enumeration, and it is the discipline
ADR-0124 §8 already imposes for the case a hub cannot reach: a delete surface must
"report the devices it could not purge" rather than presenting itself as complete.
The same standard applies within one machine.

> **Normative.** This seam is not a Tier 1 store. Nothing but a Tier 0 secret goes
> in it, with exactly one exception: a non-secret value that ADR-0124 §4 and §6
> require to travel with one, which today is the enrolled hub identity. It is not a
> general key-value store, not a settings store, and not a cache.

> **Normative.** This seam is not the hub's enrolment-verifier store. ADR-0124 §6
> puts the enrolment record — a device's overlay identity, its credential verifier,
> and its enrolment and revocation instants — inside `data_dir` under ADR-0083's
> layout, and this ADR moves none of it. The hub holds neither face of this seam for
> enrolment purposes.

The two are easy to conflate and the distinction is the security property.
ADR-0124 §6 retains "only a verifier from which the credential cannot be recovered,
so the hub holds no device's Tier 0 secret at rest". A hub that kept its verifiers
in the keyring behind this seam would still be correct, but a hub that kept
*credentials* there would have destroyed that property; ruling the store out of the
hub's enrolment path removes the ambiguity that would let the second happen while
looking like the first.

### 6. Errors, and absence is not one of them

> **Normative.** `core/errors.py` gains `SecretStoreError(AssistantError)`, raised
> when a keyring operation fails, and `SecretStoreUnavailableError`, a subclass
> raised when the keyring cannot be reached on this machine at all. Every `except
> SecretStoreError` catches both.

> **Normative.** Absence is never an error. An unset name is a `None` from `get`
> and a `False` from `delete`, and neither raises.

> **Normative.** No exception raised by this seam, no message, no exception
> argument, and no log line an implementation emits may contain a secret value or
> any part of one. The `SecretName` may appear in all of them (§2).

`SecretStoreUnavailableError` is narrowed out for the reason the corpus narrows:
**the correct response differs**. A keyring that is absent, locked or not running
is a deployment condition a human clears, and retrying it is futile; a write the
backend rejected may be transient. `IncompatibleStateError`'s docstring records the
same distinction and why it is worth a type check rather than a message match — one
fault means the supervisor stays down and a human acts, the other may clear on its
own. It subclasses the base rather than sitting beside it, which is
`MemoryStoreConflictError`'s and `DeferralIdConflictError`'s shape, so a caller that
only wants "the secret is not available" writes one handler.

A malformed name or value is not a store error at all: `SecretName` and
`SecretValue` validate at construction and raise `ValueError`, which is ADR-0073
§2's spelling inherited unchanged, so the store's methods never see one.

### 7. Platform posture: absent, locked and headless are one visible state

> **Normative.** When no keyring backend is available, or the backend is present
> and locked with no unlock possible in this session, every method raises
> `SecretStoreUnavailableError`. `get` **never** returns `None` for that condition.

**This is the clause that stops the worst failure available here.** If an
unreachable keyring answered `None`, "this device is not enrolled" and "this
device's keyring is locked" would be the same observation. A client would report
the owner as unenrolled while they are enrolled; an enrolment flow reading `None`
as a first run could mint a replacement credential and, under ADR-0124 §6's
uniqueness clause, revoke the working one — a locked keyring turned into a
revocation the owner never asked for. Absence and unreachability must be different
answers, and the error is where the difference lives.

> **Normative.** An implementation may not fall back. When the keyring is
> unavailable it raises; it does not substitute a file, an environment variable, an
> in-memory map, or any backend that stores a value without the operating system's
> own access control on it.

ADR-0004 §3 is unconditional — "never in the memory database, never in a committed
file" — and ADR-0124 §6's exemption from ADR-0004 §7's gate is granted *against*
three replacements, the second of which is that "custody is the operating system's
own access control on the keyring". A plaintext fallback removes the custody the
exemption was traded for, which would make the exemption unearned. The hazard is
concrete rather than theoretical: cross-platform keyring stacks ship alternative
backends that store to a plaintext or weakly-obscured file and can be selected by
configuration or by what happens to be installed, so "it worked on the headless
box" is exactly how this arrives. The remedy for a headless box is a keyring the
operator installs and unlocks, and the fault is legible until they do — which is the
posture ADR-0084 §9 takes for a hub that is down.

> **Normative.** Constructing an implementation touches no keyring. The backend is
> resolved on the first call, so a deployment with no keyring and no consumer
> needing one starts normally.

`HubEngineClient` already takes this shape and states why — "a constructor that
connected would make 'is the hub up' a question asked at a moment no command
chose". The same argument holds harder here, because ADR-0083 §3's startup
sequence must not acquire a dependency the hub may never use, and #879's box is a
deployment where the hub runs headless and the credential lives on somebody else's
laptop.

> **Normative.** `SecretStoreUnavailableError` states the condition in terms the
> operator can act on — which backend was looked for and what was found — and never
> in terms of a value.

### 8. Who holds which face, and no second path to the keyring

> **Normative.** `models/` holds `Secrets`, by injection, for `PROVIDER`-scoped
> reads. It does not hold `SecretStore`; provisioning a provider credential is not
> `models/`'s.

> **Normative.** `tools/` holds `Secrets` at the tool that needs one, by injection,
> for `INTEGRATION`-scoped reads. `ToolRegistry` and `ToolInvoker` hold neither
> face, and ADR-0029 §6's rule is inherited unchanged rather than restated: no
> credential value crosses the invocation seam in either direction, `invoke` grows
> no `credentials=` parameter and no `SecretStore` argument, `ToolCall` gains no
> credential field, `ActionRequest.parameters` may carry no Tier 0 value, and
> `ToolResult` carries none back.

> **Normative.** The wire client's enrolment and unenrolment paths hold
> `SecretStore`; its connect path is given `Secrets` and nothing wider. Both are
> `ENROLMENT`-scoped, and the connect-path read is the one ADR-0124 §6 confines to
> one purpose and one path.

**Every scope word in the four clauses of this section is mechanical, not
advisory.** §2 binds an instance to one scope and makes every method refuse a name
outside it, so "`tools/` holds `Secrets` ... for `INTEGRATION`-scoped reads"
describes what the object the tool holds can do, and a tool naming an `ENROLMENT`
entry gets a `ValueError` rather than the device credential. The composition root
is where the two facts about an instance — its installation and its scope — are
chosen, which is the one place that knows both.

> **Normative.** No other subsystem holds either face. `orchestration`, `memory`,
> `context`, `planning`, `permissions`, `learning`, `readers`, `evaluation`,
> `service` and `interfaces` hold neither, and none of them may acquire one without
> the ADR §2 requires for a fourth scope.

> **Normative.** One concrete keyring-backed implementation exists, in a leaf
> package that no subsystem imports, and it reaches every consumer by injection from
> whoever composes it. No subsystem builds its own.

The leaf-package shape is `readers/` and `evaluation/`'s, and the reason is the
one recorded for both: `core` holds the Protocol, so the edge that would invert the
dependency is one an implementation could plausibly reach for, and a package
outside every subsystem is what makes the inversion impossible rather than
discouraged. The package's **name** is the landing lane's, along with adding it to
`CLAUDE.md`'s architecture map and to the `core`-forbidden import-linter contract,
exactly as ADR-0124 §6 left the enrolment record's store to its lane. One caution
for that lane: `ai_assistant.secrets` shadows a standard-library module name that
ADR-0124 §6's credential minting has direct use for, and while absolute imports make
it safe, it is a name that will confuse every reader of a file that needs both.

> **Normative.** The lane that lands the concrete implementation adds an
> import-linter contract confining the keyring library's import to that one package,
> so ADR-0004 §3's single-path rule is mechanically enforced rather than
> review-checked.

This is golden rule 4's shape applied to a second external dependency, and it is
issue #66's shape applied inside the machine rather than at the egress boundary.
Without it, "read credentials through `SecretStore`" is a convention, and the
history of this particular convention is that it stayed unimplemented from
ADR-0004's ratification until a third consumer made it blocking.

> **Normative.** No lane may add a new path to a Tier 0 credential — an environment
> read, a file read, or a direct keyring import — for any secret this seam can hold.

> **Normative.** The existing environment read of the model provider key is
> **pre-existing and is not authorised by this ADR**. It is the unmet state of
> ADR-0004 §3, it stays #74's and the `models/` lane's, and no lane may cite this
> ADR toward keeping it.

The asymmetry is deliberate and it is ADR-0124 §6's, adopted rather than
reinvented: a known pre-existing gap does not authorise a new one. What is new here
is only that the gap now has a seam to close into.

### 9. This contract does not gate, and is shaped so that #74 can land into it

> **Normative.** No method here performs a permission check, consults
> `permissions/`, or writes an audit record. This is a storage seam, not an
> authorisation seam.

> **Normative.** Nothing in this ADR discharges ADR-0017 §3's "credential access
> gated, not just transmission" condition, and nothing in it narrows ADR-0004 §7.
> The `tools/` egress seam stays undesignated, #74 stays open on its own subject,
> and ADR-0124 §6's exemption stays confined to the one read it names.

**What this ADR contributes to #74 is a shape that does not have to break when it
lands**, which is the specific thing ADR-0029 §6 asked for. `Secrets` is a
single-method Protocol satisfied structurally, so a gating implementation is an
object that implements `Secrets`, consults `permissions/` and delegates to the
concrete store. If #74 rules that a credential read is a permission subject, the
gate arrives as a decorator at the composition root and **no signature in
`core/protocols.py` changes** — not the method, not its arguments, not its return.
If #74 rules it is not, nothing is built and nothing is left dangling. Both answers
are reachable from here, which is why `get` takes a name and returns a value and
carries no decision-shaped parameter for a decision nobody has made.

The subject such a gate would need is already present: a `SecretName` names the
scope and the entry, which is what a policy would rule on, and §2 makes it safe to
put in an audit record.

**One placement is ruled out in advance**, because it would be the obvious mistake:
the client's connect-path reader is not decorated. ADR-0124 §6 supersedes ADR-0004
§7's gate for that read precisely because the gate lives behind the connection the
read opens, and wrapping it would rebuild the circularity that supersession exists
to escape.

### 10. ADR-0078 §11's secret-tier arm stays where §11 put it

> **Normative.** This ADR does not close ADR-0078 §11's secret-tier `ASK_USER`
> arm, does not change `DeferredProposal`'s refusal of a `DataTier.SECRET`
> proposal, and adds nothing to the deferral queue. §11's gate is unchanged: the
> arm is closed by a lane with a producer, and no producer exists.

**§11 names two conditions and only one of them was this ADR's.** It says closing
the arm needs "the `SecretStore` seam ADR-0004 §3 names and that
`core/protocols.py` does not yet have — payload in the keyring, a non-secret
reference in the queue, and a read/export/delete path across the two", and then
names the owner as "a `SecretStore` lane, **gated on a producer existing**; nothing
in the codebase constructs a `DataTier.SECRET` proposal today". The tree still
constructs none. Building the design now would be building a read/export/delete
path across two stores for a value nothing produces, which is the scope ADR-0078
§11 itself called out as the wrong move — for a producer that does not exist.

**What this contract does supply toward it**, so the lane that eventually holds a
producer knows what it inherits: the keyring half exists; §2 rules that a
`SecretName` is not a secret and may be held in a Tier 1 store, which is exactly
what makes "a non-secret reference in the queue" constructible; and §5's refusal of
enumeration tells that lane that its purge path is composed from names it recorded
rather than discovered.

**What it does not supply**, and each is a decision that lane owns: the reference
field on the queue's record type, the coordination between a queue row and a
keyring entry when one of the two writes fails, the export behaviour under ADR-0004
§6, and — the one that makes the discipline concrete — a `SecretScope` member. None
of §2's three members covers a user-typed secret caught by the memory policy, so
that lane's first act is a contract ADR adding one. That is the enum working as
intended rather than an obstacle in its way.

**Silence here would have been read as an answer**, which is why this section
exists at all. A reader finding a ratified `SecretStore` ADR that never mentions
ADR-0078 §11 would reasonably conclude the gate had been forgotten or quietly
discharged, and the arm would sit closed-looking and open.

### 11. What the triad must prove

The conformance suites are the contract's enforcement, and the obligations below
are their floor rather than a wish list. The triad lane adds tests it judges necessary;
it may not omit these. Naming them here is what stops the next lane from inventing
a weaker set (`CONTRIBUTING.md` → "Adding a Protocol").

**There are two suites, because there are two Protocols and they have different
subjects.** `SecretsContract` binds anything satisfying the reading face —
including the gating implementation §9 permits, which has no `set` to call — and
`SecretStoreContract` inherits it and adds the write obligations. A single suite
asserting `set` "against every subject" would be unrunnable against exactly the
implementation §9 exists to make possible. The narrow suite arranges the state it
asserts about through an abstract `given` hook the subject implements, which is
`SourceGrantsContract`'s solution to the identical problem — a query-only seam has
no contract-level way to write, and adding one to the Protocol would destroy the
property being tested.

> **Normative.** `SecretsContract` proves, against every subject: an entry
> arranged through `given` is returned verbatim, including a value with leading
> and trailing whitespace, embedded newlines and non-ASCII characters; `get` of an
> unset name returns `None`; two names differing only in `scope` are distinct
> entries, and two differing only in `key` are distinct; two subjects bound to
> different installations share no entry, so an entry arranged in one is `None` in
> the other; a name outside the subject's bound scope raises `ValueError` and the
> subject's own scope still answers afterwards; the subject satisfies `Secrets` by
> `isinstance`; and no secret value appears in the `repr` of the subject, of a
> `SecretValue`, or of any error the subject raises.

> **Normative.** `SecretStoreContract` inherits every obligation above, binding
> the same subject through the narrow face rather than a second object, and adds:
> a `set` then `get` round trip returns the value verbatim; `set` over an occupied
> name replaces and leaves one entry; `delete` of an unset name returns `False` and
> raises nothing; `delete` returns `True` once and `False` thereafter, and `get`
> then returns `None`; `set` and `delete` each raise `ValueError` for a name
> outside the subject's bound scope, and the entry that name would have addressed
> is neither written nor removed; `set` raises `ValueError` for a blank value and
> for an oversized one built directly as a bare `SecretStr`, storing nothing in
> either case; and the subject satisfies `SecretStore` by `isinstance`.

> **Normative.** The type obligations are proved beside the suites, over the types
> themselves: a `SecretValue` of exactly 1024 UTF-8 bytes constructs and one of
> 1025 raises `ValueError`; a blank one raises; a `SecretValue` is not normalised
> between construction and `get_secret_value`; and `SecretName` refuses uppercase,
> whitespace, `:`, `/`, an empty key and a 65-character key.

**The installation obligation is in the suite rather than left to the adapter,
and that placement is the point of it.** Every other test on this list passes
against a subject that ignores its installation namespace entirely, because one
subject cannot observe another's entries by accident. Two subjects can, and the
failure it catches is the one §2 exists to prevent: a concrete adapter that
composes backend coordinates from the scope and key alone, whose second
installation then overwrites the first's credential and whose unenrolment deletes
it. Requiring two subjects makes that a red test rather than a support ticket.

> **Normative.** The suite proves the unavailable state too — that every method
> raises `SecretStoreUnavailableError` and that `get` does not return `None` — as a
> test marked `@pytest.mark.optional_obligation`, so an implementation that cannot
> be driven into that state skips it and the canonical fake, which can, does not.

The optional marking is the mechanism `CONTRIBUTING.md` provides and
`ContextProviderContract.test_each_assembly_recomputes_from_the_clock` is its
standing example. It is used here rather than dropping the obligation because the
unavailable path is the one §7 argues hardest about, and a suite that could not
test it at all would leave the argument unenforced.

> **Normative.** Two obligations are the landing lane's rather than the triad's,
> because a shared suite running against a fake cannot reach them, and the lane
> that lands the keyring-backed implementation owes both: that a backend selection
> which finds nothing usable **raises rather than falling back** (§7), and that no
> backend storing a value without the operating system's own access control is
> ever selected.

**Naming them here is what stops them from evaporating between two lanes.** Every
obligation the shared suite carries can be satisfied by the canonical fake, which
has no backend to select and cannot fall back — so a triad that goes green proves
nothing about the property §7 spends its longest argument on. The adapter is where
that property lives and the adapter's own tests are where it has to be pinned;
recorded as a debt on a lane that does not exist yet, it would be discovered by
whoever first ran the system on a headless box.

> **Normative.** The canonical fake in `ai_assistant.testing` is an in-memory
> implementation of `SecretStore`, taking its installation namespace and its
> `SecretScope` at construction so the suites can build two that differ in either,
> and carrying an explicit switch that puts it into the unavailable state. It is
> test-only, and no composition root wires it.

> **Normative.** Both Protocols get a concrete `Test…Contract` subclass running
> the fake through its suite — through the narrow suite as a `Secrets`, and through
> the wide one as itself.

The suite module and the fake follow the corpus's placement: two Protocols may
share one suite module and one fake, as `SourceGrants` and `SourceGrantStore` do,
and a contract with no owning subsystem package sits under `tests/core/`, as
`tests/core/reader_contract.py` does. The `Test…Contract` subclasses are not
optional — an abstract suite collects nothing on its own, so without them the fake
is unverified however many files exist, and `tests/core/test_protocol_triad.py`
fails naming what is missing. That check wants evidence the contract *ran*, which
is why it is two subclasses and not one: `Secrets` is a Protocol in
`core/protocols.py` and the check enumerates every one of them.

> **Normative.** The triad lane declares no `EXEMPTIONS` entry. That list may name
> only Protocols predating the check, it is currently empty, and this contract is
> not eligible for it.

### 12. What this ADR does not decide

Each is scoped out with its reason, because scoping out is a decision.

- **Whether the model provider credential moves onto this seam, and when.** That
  needs #74's answer and a `models/` lane, and it needs pydantic-ai's provider
  construction to accept an injected key rather than reading the environment —
  which ADR-0062 §2 records as the boundary that made `_check_provider_importable`
  key-free. §8 rules the direction and forbids new paths; it does not schedule the
  migration. #74 stays open.
- **A provisioning surface.** Nothing here mints a command that sets a provider
  key or an integration credential. `SecretStore` is the seam such a command would
  use, and today no code holds it for a `PROVIDER` scope.
- **Rotation, expiry and re-provisioning policy.** `set` replaces; when and why
  are the consumer's. ADR-0124 §6 already rules re-enrolment for its own scope.
- **The `keyring` dependency's adoption.** ADR-0004 §3 already names the library
  and this ADR neither re-ratifies nor replaces that choice; what the landing lane
  owes is #664's Python 3.14 wheel check before it adds the dependency, and this
  ADR requires only that the backing give the operating system's own access
  control (§7).
- **Whether a backup carries a keyring entry.** ADR-0123 backs up the cold data
  directory; the keyring is not in it, so a restored installation holds no Tier 0
  entry and the owner re-provisions. That is a statement of ADR-0123's scope rather
  than a change to it, and this ADR asks nothing of that lane.
- **#462's endpoint configuration.** Adjacent — it is an egress-surface question
  about where `models/` sends — and untouched here.

### 13. Amendment records under ADR-0082 §1

ADR-0082 §1 requires the judgement in this ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds? Every ADR
this one relies on was read for **what it is relied on for**, which is ADR-0084
§12's semantic method rather than a phrase search.

**Two clauses are partially superseded — ADR-0004 §3's and ADR-0124 §6's — and
both records land in this change**, on each ADR's `Status` line and in its
appended dated note. They are the same clause twice: each names `SecretStore` as
the Protocol a consumer reads through, and §1 above hands a read-only consumer
`Secrets` instead. One further record is owed and is a stacked addition, which
ADR-0082 §1 places in this ADR and nowhere else.

**Both were drafted as stacked additions and neither is one.** The first draft
argued that §3's sentence "stays true" because `models/` still reads through the
`SecretStore` *seam*, of which `Secrets` is a face. Architecture review named the
substitution: §3 says **Protocol**, not seam, and a reader holding only §3 wires
`models/` with a `SecretStore` where after this ADR they wire it with something
else. That is ADR-0070 §1's first limb met, and the reasoning is adopted rather
than argued with — the same outcome ADR-0124 §12 records for its own two clauses,
found the same way. Applying the identical test to ADR-0124 §6 then gives the
identical answer, which is why there are two records and not one; leaving the
second unrecorded because it was not the one review named would be keeping a
misclassification that the finding had already refuted.

**What was *not* conceded is the design.** Narrowing what a read-only consumer
holds is the decision (§1), and ADR-0082 §1 is explicit that a record is a
book-keeping consequence of a decision rather than a reason to choose a different
one. Weakening the seam to avoid two status-line edits would have been exactly
that inversion.

- **ADR-0004 §3's reader clause is partially superseded, and only that clause.**
  The sentence is "The `models/` and `tools/` layers read credentials through a
  small `SecretStore` Protocol (added to `core/protocols.py`) so the keyring
  backing can be faked in tests and swapped per platform." §1 and §8 above give
  those two layers `Secrets` and state that neither holds `SecretStore`, so a
  reader holding only §3 wires them differently from a reader holding this ADR —
  ADR-0070 §1's first limb, met. In its place: the seam is two Protocols, a
  read-only consumer holds the reading one, and the sentence's own purpose is
  carried unchanged, because `Secrets` is in `core/protocols.py`, is fakeable, is
  swappable per platform, and is the only path either layer has to the keyring
  (§8). **Nothing else of §3 moves.** Its keyring rule — Tier 0 in the OS keyring,
  never in the memory database, never in a committed file — is applied rather than
  narrowed, and §7 above turns it into a refusal-to-fall-back. Its third consumer,
  recorded by ADR-0124 §12, is untouched and this ADR adds no fourth. §1's tiers,
  §4's at-rest posture, §5's redaction and §6's rights are used as given; §6's
  Tier 0 purge gains the mechanism §5 above describes and loses nothing. §7 is not
  engaged: §9 above gates nothing and widens nothing, and ADR-0124 §6's exemption
  is left exactly where it was put.
- **ADR-0124 §6's reader clause is partially superseded, and only that clause.**
  The marked sentence is "The client reads the credential through the
  `SecretStore` Protocol ADR-0004 §3 provisions, and through no other path to the
  keyring." Its second limb is untouched and is in fact strengthened — §8 above
  adds an import-linter contract confining the keyring library to one package, so
  "no other path" becomes mechanical. Its first limb fails the same test as
  ADR-0004 §3's: the client half holds a `SecretStore` for enrolment and
  unenrolment, but the **connect-path read** this clause is about goes through
  `Secrets`, so a reader holding only §6 wires that call site with the wider
  Protocol. In its place: the connect path holds `Secrets`, bound to `ENROLMENT`
  and to the device's installation (§2), which is strictly narrower than what §6
  described and serves every purpose §6 gave for naming the Protocol at all.
  **Nothing else of §6 moves**, and the parts that matter most are used exactly as
  ratified: the credential persists, it is held only in the OS keyring, the read is
  confined to one purpose and one path, it reaches no log or audit record or error
  message, the enrolment is unique per identity, and ADR-0004 §7's exemption keeps
  its three replacements. §7's credential wire type is untouched — the client
  unwraps with `get_secret_value` immediately before encoding (§3) — and §8's
  device-side unenrolment gains `delete` as its mechanism with none of its rules
  changed.

  **One header field is added to ADR-0124 rather than lost.** Its `Status` was the
  bare token `Accepted`, and the leading `Partially superseded by` token replaces
  it — the template drops `Accepted` so that a prefix match cannot read the
  replaced part as live. That would have left the file with no record of having
  been ratified, so an `Accepted: 2026-08-09` field is added beside `Date`, which
  is the shape ADR-0017 already carries and where ADR-0124 §12 put the same ADR's
  own acceptance date. Nothing else of that header, and no ratified text of that
  ADR, is edited.

  **Both `Status` lines are one physical line, and ADR-0004's is unwrapped with no
  word changed.** ADR-0070 §4 requires a canonical status to occupy one physical
  line and says the wrapped ones already in the corpus are "the exception the
  consumer rule and issue #404 handle, not a licence to write new ones". Adding a
  pair produces a new line, so it is written canonically rather than by extending a
  continuation; the ADR-0017 and ADR-0124 pairs on that line keep their scope text
  exactly as their own lanes wrote it. Each new scope is the short clause reference
  §4 asks for, and the elaboration lives in the dated note, which §4 does not
  constrain.
- **ADR-0084 — a stacked addition on §11, on ADR-0083 §15's own test.** §11 defers
  authentication's storage, saying "`SecretStore` is the obvious home". That
  sentence **stays true and now has an answer**, which is the stacked-addition test
  verbatim; the deferral is discharged by the seam it named. §2's loopback client is
  untouched — it reads no credential — and §9's `data_dir` remains the one setting
  that locates everything, which is what §2 above binds the installation namespace
  to. **Recorded here and nowhere else.**
- **ADR-0124's other sections — no record owed.** §6's reader clause is recorded
  above; nothing else of that ADR is touched. §1's three egress boundaries are not
  engaged, because a keyring read leaves no device. §4's requirement that the
  enrolled hub identity travel with the credential is satisfied by both storage
  shapes §4 above permits. §7's admission rule and §8's revocation levers are used
  as given, and §12's own records — including the stacked addition on ADR-0004 §3
  that put a third consumer there — stand exactly as written.
- **ADR-0029 — no record owed, and §6 was a constraint on this ADR that this ADR
  meets.** §6 recorded that invocation "must not later grow a `credentials=`
  parameter or a `SecretStore` argument on `invoke`", that "a tool fetching its own
  credential from an injected `SecretStore` is a `tools/` wiring concern", and that
  the rule "the seam neither carries nor sees a credential" is "the one the
  `SecretStore` ADR will need to hold to whatever shape it takes". §8 above holds
  it: nothing here touches `ToolInvoker`, `ToolCall`, `ActionRequest` or
  `ToolResult`, and the store arrives at the tool by wiring. §6's other observation
  — that a `SecretStore` must not smuggle a gating decision into its signature — is
  what §9 above is built around.
- **ADR-0021 — no record owed.** §1's prohibition on a Tier 0 value in
  `ActionRequest.parameters` is used as given and reinforced by §8 above; §3's
  deferral of gating direct Tier 0 access pending #74 is left exactly where it is,
  and §9 above declines to pre-empt it.
- **ADR-0017 — no record owed.** §1's egress rule is not engaged: a keyring read
  leaves no device. §2's three pre-existing gaps in `models/` (#83, #74, #89) are
  untouched, and §8 above is explicit that this ADR authorises none of them. §3's
  fourteen conditions all stand, none is discharged here, and §9 above says so.
- **ADR-0078 — no record owed.** §11's sentence about the seam
  `core/protocols.py` "does not yet have" is a statement about the tree that this
  ADR does not falsify — no Protocol lands here — and its gate on a producer
  existing is untouched. §10 above leaves the arm where §11 put it. §1's and §2's
  refusal of a `DataTier.SECRET` proposal is used as given.
- **ADR-0083 — no record owed.** §6's durable-state discipline governs `data_dir`
  and this ADR puts nothing new there; the keyring is not `data_dir`. §3's startup
  sequence is unchanged, which §7's construction clause above is what protects.
- **ADR-0123 — no record owed.** Its backup is the cold data directory and this
  ADR adds nothing to it; §12 above states the consequence for a restore as a fact
  about ADR-0123's scope.
- **ADR-0016 — no record owed.** §7's three constraints on the invocation ADR are
  ADR-0029's and are not reopened; §5's "a contract whose author expects it to
  break" is used as the standard §9 above is measured against.
- **ADR-0054 — no record owed, and it is inherited rather than restated.** Its
  ruling is that a cancelled store call must not release its connection while a
  worker thread still holds it, and §1 above puts an implementation in exactly that
  shape: a synchronous backing library driven from a worker thread behind an
  `async` method. Nothing here weakens it and nothing here needs to repeat it. Its
  premise amendment by ADR-0083 §4 — that the cancellation path is live rather than
  dormant — makes it apply here from the first line rather than eventually.
- **ADR-0060 and ADR-0065**, the two clauses `core/protocols.py` binds on every
  Protocol. Cancellation **has bite**: a keyring call is I/O and may be in flight,
  so ADR-0060's rule that "a cancelled write may or may not have committed" governs
  `set` and `delete`, and a caller may not assume a cancelled `set` did not land.
  Input observation is **vacuous**: `SecretName` is frozen and `SecretValue` is
  immutable, so there is nothing a caller can mutate mid-flight.
- **ADR-0095, ADR-0119 — no record owed.** Their leaf-package placement is used as
  the precedent §8 above follows, and neither is changed by a third package
  adopting it.

## Consequences

- **The client half of the remote transport is unblocked** once the triad lands.
  ADR-0124 §6's prerequisite is a contract ADR plus a triad, and this is the first
  of the two.
- **`core` grows two Protocols, three types and two errors**, and a package that
  does not exist yet acquires a specification. The triad lane builds all of it from
  this text; the keyring-backed implementation, its package, its `CLAUDE.md` map
  entry and its two import-linter contracts are a third lane behind that.
- **A tool can no longer be handed the ability to delete the device credential**,
  and that is enforced by which face it is given rather than by review attention.
- **A second installation on one machine stops being a data-loss hazard**, at the
  cost that moving a data directory orphans its entries and the owner
  re-provisions.
- **#74 acquires a landing site and stays open.** The gate, if there is one,
  arrives as a decorating implementation and changes no signature in
  `core/protocols.py`. What it does not acquire is an answer.
- **ADR-0017 §3's condition list is one item closer to being answerable and no
  items shorter.** The seam a gated credential read would gate now has a shape; the
  gating itself does not, and the `tools/` egress seam stays undesignated.
- **ADR-0078 §11's arm is left open, deliberately and on the record**, with the
  first act of the lane that closes it named: a `SecretScope` member, which is a
  contract ADR.
- **A headless deployment with no keyring now has a defined behaviour** — a
  legible refusal rather than a silent plaintext fallback — which is a harder
  first-run experience on #879's box and the only one compatible with ADR-0124 §6's
  exemption.
- **Revisit when** #74 lands, when a fourth consumer needs a `SecretScope` member,
  when a credential scheme genuinely exceeds 1024 bytes, or when a portable
  enumeration and a consumer for it both exist.

## Alternatives considered

- **One Protocol with three methods, held by every consumer.** Simpler, and it is
  what ADR-0004 §3's wording most directly suggests. Rejected on the concrete case:
  a tool integration and the device's enrolment credential live in one keyring
  behind one object, so a single face gives every tool the ability to delete the
  owner's enrolment. The corpus had already solved this once, in `SourceGrants` and
  `SourceGrantStore`.
- **A flat opaque string as the entry name.** Fewer types. Rejected because it has
  nowhere to put the installation, and because three consumers composing their own
  namespaces into one string is how two of them eventually collide — which is the
  failure mode that is invisible until it destroys a credential.
- **A free-form scope string rather than a closed enum.** More additive. Rejected
  because the closed enum is what converts ADR-0004 §3's discipline from a sentence
  into a compile-time question, and because the cost it imposes — a contract ADR to
  add a consumer — is exactly the cost golden rule 5 already imposes.
- **An enumeration method.** Rejected in §5, on three grounds, and additive later.
- **`get` raising on an absent entry.** Rejected: a first run has no credential and
  that is not a fault, and §7's argument requires absence and unreachability to be
  distinguishable — which is easiest when one is a value and the other is an error.
- **Returning a plain `str`.** Rejected in §3: `core/logging.py` redacts by key
  name, so a plain value under an uncovered key escapes, and ADR-0124 §6 leans on
  that redaction by name explicitly.
- **A gating parameter, a `subject=` argument, or an audit hook on `get`.**
  Rejected on ADR-0029 §6's own argument, which named this as the way a
  `SecretStore` gets ratified with a decision nobody has made.
- **Falling back to an encrypted file where no keyring exists.** Attractive for
  #879's headless box. Rejected in §7: it removes the OS custody that ADR-0124 §6
  traded for its exemption from ADR-0004 §7, and it converts a legible deployment
  fault into a silently weaker deployment.
- **Bytes rather than text as the value.** More general. Rejected because every
  credential this system holds is text, keyring backends take strings, and a bytes
  value would push an encoding decision onto every call site — where the versions
  would diverge.
- **Reading the device credential from an environment variable instead.** Already
  considered and refused by ADR-0124 §6, on the ground that it would put a
  long-lived device secret in the environment of every command the owner runs. It
  is recorded here so it is not proposed a third time.
