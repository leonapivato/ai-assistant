# 21. Permission decisions and the audit trail

- Status: Proposed
- Date: 2026-07-20

## Context

`permissions/` is an empty package with a docstring. ADR-0004 §7 ratified what
it owes the rest of the system:

> Access to Tier 0/1 data and every side-effecting tool call is gated by the
> `permissions/` layer and recorded in an **audit trail**, making the
> assistant's behaviour transparent and reviewable (a Tier 1 store itself).

That is a decision without a contract. Nothing in `core/protocols.py` lets
`orchestration` ask whether an action is permitted, and nothing lets it record
that it asked. ADR-0014 §4 nevertheless *already requires* the answer: a step
may not enter `RUNNING` without an `approval_ref`, so every plan the system
executes points at a permission decision that no type describes and no store
holds.

The subsystem was blocked on tool metadata, and is not any more. ADR-0016 and
ADR-0018 ratified `ToolDefinition` — `risk_level`, `reversibility`,
`discloses`, `side_effecting`, `cost` — precisely so a policy could be written
against declared facts rather than a hard-coded list of integration names.
ADR-0016 §3 states the division of labour this ADR takes up: *"What
`permissions/` does with `risk_level`, `reversibility`, `reads`, `writes` and
`discloses` — which combinations auto-grant, which prompt, which refuse — is its
ADR to write, not this one's to pre-empt."*

Three constraints come with that inheritance, and each shapes a decision below.

**Reach is a ceiling, not a measurement** (ADR-0016 §3). `discloses=(PERSONAL,)`
bounds what a call *may* transmit; it never reports what a call *did*. A policy
reading it therefore over-prompts by construction, and that is the direction the
bound is meant to err in.

**`discloses` must be read alongside `reversibility`** (ADR-0016 §2, restated in
its Consequences as *"a two-field rule `permissions` has to honour rather than a
property the type enforces for it"*). A `REVERSIBLE` tool can make an
irrevocable disclosure; a policy keyed on the reversibility scale alone
auto-grants it.

**An approval names an id, and an id can be rebound** — issue #54. ADR-0014
records `bound_tool` as a *string* and `approval_ref` as a pointer to a decision
made against whatever that id meant at the time. ADR-0016 §5 and ADR-0018 §5
close the within-a-registry half by spending ids permanently; the residue
crosses a restart, because plan state is durable (ADR-0014 §5) and the registry
is rebuilt each run. ADR-0018 §4 arrived at the same seam from a second
direction — a tampered-but-valid definition under a fresh id is accepted, and
*"no mechanism in this ADR detects it"* — and ADR-0018 §3 from a third: a caller
may tamper the copy a query handed it and pass that downstream. All three name
the same fix and park it here: **the decision must pin the definition it ruled
on.**

This adds Protocols and `core` types, so it is a substantive contract ADR
(golden rule 5, ADR-0015 §5) and ships as its own PR ahead of any
implementation.

## Decision

We will model a permission check as a **pure ruling on a self-contained
request**, and the audit trail as an **append-only Tier 1 store** that holds the
rulings verbatim.

### 1. A decision records the request it ruled on, not a name

```python
class PermissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    ruling: PermissionRuling         # what the policy said (§3)
    tool: ToolDefinition             # the declaration ruled on, verbatim
    parameters_digest: str           # binds the payload without storing it
    decided_at: datetime             # timezone-aware
    step_id: Identifier | None = None
    resolves: Identifier | None = None

    @classmethod
    def from_request(
        cls,
        request: ActionRequest,
        ruling: PermissionRuling,
        *,
        id: Identifier,
        decided_at: datetime,
        resolves: Identifier | None = None,
    ) -> PermissionDecision:
        """Bind a ruling to the request it was made about."""
```

**`tool` is the whole `ToolDefinition`, embedded by value.** This is the single
most important clause here and it is what closes #54: there is no name left to
rebind. A decision does not say "I approved `send_message`"; it says "I approved
*this declaration*, which happens to call itself `send_message`, is `REVERSIBLE`,
discloses `PERSONAL`, and costs nothing". A process that restarts and registers a
different definition under the same id has not altered any decision, and the
mismatch is a value comparison away.

**`from_request` is the only construction path a caller should use, and it exists
so the binding is transcribed rather than asserted.** Every field describing
*what was ruled on* — `tool`, `parameters_digest`, `step_id` — is copied from the
request by `core`, so a decision that names a different tool than the one the
policy saw cannot be produced by following the contract. The complementary half
is §3's: a policy returns a `PermissionRuling` and never a `PermissionDecision`,
so it has no field in which to name a tool at all. Between the two, "the decision
is about the request" stops being a claim the prose makes and becomes a property
of the types.

It is a factory rather than a validator because the request is not a field of the
decision — embedding the request whole would store the parameters this design is
careful not to store (below). What remains open is a caller hand-constructing a
`PermissionDecision` field by field; that is a caller falsifying its own audit
trail, not a policy subverting a gate, and no producer can prevent it (the same
boundary ADR-0018 §3 drew for detachment).

The verification seam is offered on the type rather than left to each caller, and
it takes a **request**, not a bare definition:

```python
def authorises(self, request: ActionRequest) -> bool:
    """Whether this decision authorises performing ``request``."""
    return (
        self.ruling.outcome is PermissionOutcome.ALLOW
        and request.tool == self.tool
        and request.parameters_digest == self.parameters_digest
        and request.step_id == self.step_id
    )
```

Taking the request is what makes this discharge ADR-0017 §3's *"what is
transmitted is bound to what was authorised, immutably, and consumed
unchanged"*. A signature taking only a definition would have checked the tool
and silently ignored the arguments — authorising an email to one recipient and
executing it to another, with every record still reading as consistent. That is
the same failure shape as #54, one level down, and it is worth the wider
parameter.

`ToolDefinition` is a frozen pydantic model, so `==` is field-wise and total.

**Why this may live in `core` at all.** `authorises` compares; it does not
decide. Whether an action *should* be allowed is `ActionPolicy`'s, in
`permissions/`, and none of that reasoning is here — this asks only whether a
record already in hand is a record of *this* request being allowed. It therefore
passes ADR-0016 §2's three-part test for a semantic intrinsic to a type:
computable from the two values alone, independent of policy, configuration,
context and clock, and the same answer for every consumer. That is the amended
rule — *"`core/types.py` holds no subsystem logic; it may hold semantics
intrinsic to a type it defines"* — and it is the rule that already admits
`FrozenDict` and `ExecutionState.is_active`.

The alternative, a comparison living in `permissions/`, fails for the reason
ADR-0016 §2 gave when it declined to put the severity ordering in a subsystem:
both `permissions` and the future invocation path need it, golden rule 1 forbids
either importing the other, so it would become two copies of a safety-critical
comparison free to disagree.

**Why not a digest.** Issue #54 and ADR-0018 §3 both propose "a digest or a
version". A digest is what you reach for when the thing is too large or too
sensitive to keep; a `ToolDefinition` is neither. It is a few hundred bytes of
Tier 2 configuration declared by code (ADR-0016 §6), so storing it costs
approximately nothing, and storing it buys three things a digest does not:

- **The trail is readable without the registry.** ADR-0016 §6 makes the registry
  in-memory and rebuilt each run. An audit record holding only a digest is,
  after a restart, an opaque hex string against which nothing can be resolved —
  an audit trail that cannot say what was approved is not one.
- **No canonicalisation to get wrong.** A digest needs a byte-exact encoding
  every implementation agrees on, and two that disagree produce false mismatches
  on identical definitions — a refusal that looks like an attack. ADR-0016 §3
  already had to legislate tuple ordering for a weaker version of this problem.
- **It composes with detachment rather than fighting it.** ADR-0018 §3 hands
  callers detached copies precisely so registry state cannot be mutated through
  a query; embedding the copy the policy ruled on extends that discipline
  instead of adding a parallel mechanism.

**What this does and does not close, stated plainly.** It closes the *permissions
half* of #54: a decision can no longer be about a name. It does not by itself
prevent a substituted execution, because nothing here invokes anything (ADR-0016
§7). The remaining half is one call — `decision.authorises(request)` against the
request the executor is about to perform — and it belongs to the invocation
contract. #54 stays open until that call exists; what changes is that the
verification seam is now built and typed rather than described.

The same holds for ADR-0018 §4's tampered-but-valid definition. If a caller
tampers a copy and asks the policy to rule on *that*, the policy grants against
the tampered declaration and records it faithfully. Nothing here detects the
tampering at decision time. What it does mean is that the tampering becomes
*detectable at execution*, against the registry's own definition, which is
strictly more than the current position where an id matched and nothing else was
compared.

**`parameters_digest`, and why the payload is bound but not stored.** The
arguments a call proposes carry Tier 1 data routinely — a recipient, a message
body, a calendar entry — and a durable record holding them verbatim would make
the trail a second copy of the user's most sensitive material, growing forever,
for no purpose the trail actually has. The trail needs to answer "were *these*
arguments the ones approved", which a digest answers exactly. So the decision
binds the payload and holds none of it.

**`parameters` may not carry a Tier 0 credential value, and that is a
pre-existing rule rather than one invented here.** ADR-0004 §3 puts secrets in
the OS keyring and has `tools/` read them through `SecretStore`; a tool fetches
its own credential and is not handed one. ADR-0017 §3 asks for exactly that
shape — *"bind a reference, fetch the secret after approval, or the binding and
every audit record derived from it become Tier 0 stores"* — and the ratified
architecture already satisfies it in the strongest available way: the credential
never enters the request, so there is nothing for the digest to be taken over.
This ADR restates the prohibition rather than relying on it being obvious,
because a digest is *not* an adequate remedy if one ever gets in. SHA-256 of a
low-entropy secret is brute-forceable offline, so a hash of a credential is a
weakened copy of it, not an absence of one. The rule is therefore "no Tier 0 in
`parameters`", not "a digest makes Tier 0 safe".

**The residual is a user-typed secret, and it is already a blocking condition
elsewhere.** A user who pastes an API key into a conversation can have it reach a
plan step's parameters, where no rule here would recognise it — issues #94
(classification by provenance, including Tier 0 the user typed) and #75 (no
egress-side detection for secrets in user-authored content). ADR-0017 §3 makes
#94 a *condition* on designating the tool egress seam, so the seam stays
undesignated while it is open. That is the right place for it: the answer is a
classification mechanism neither this contract nor the invocation contract can
substitute for, and it is named here rather than absorbed.

**The digest is a derived property of `ActionRequest`, and no caller supplies
it.** `ActionRequest.parameters_digest` computes it over the canonical JSON form
of `parameters` — `json.dumps(sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` of the mapping's JSON dump, then SHA-256, hex — and
`PermissionDecision.from_request` copies it across. Naming *where* it is computed
matters as much as naming the encoding: a `str` field that each caller filled in
would be a canonicalisation per caller, and two that disagreed would produce a
false mismatch at execution, which reads as an attack rather than as a bug.
Putting it on the request also makes it intrinsic under ADR-0016 §2's three-part
test, so it belongs in `core` for the same reason the severity scales do.

It is well-defined because `FrozenJson` is already constrained to JSON-safe
values and already rejects non-finite floats (ADR-0014 §2), which is the case
that would otherwise have no encoding.

Two limits on what that digest is worth, both inherited rather than introduced.
It binds; it does not *describe*. ADR-0017 §3 requires a payload "described
inspectably after it — which records, how many, at what tiers", and observes
that a digest leaves an auditor unable to tell one memory record from the whole
database. That description is issue #57's and the invocation contract's; this
ADR discharges the binding half of the condition and none of the description
half.

**`resolves` makes the confirmation loop auditable, and the trail enforces it.**
A `CONFIRM` outcome is recorded like any other. If the user then answers, the
answer is a *second* decision whose `resolves` names the first. Without it a
confirmation the user declined is indistinguishable from one nobody ever
answered — the same ambiguity ADR-0017 §3 refuses to accept on the egress side,
where a timeout must not read as a successful disclosure.

A bare pointer would be worse than none, because it would let an `ALLOW` for
tool B claim to be the user's answer to a `CONFIRM` shown for tool A — the
substitution §1 closes, reintroduced through the one path where a human has
actually been consulted. So the pointer carries an invariant, and it is enforced
where it is *checkable*: `AuditTrail.record` holds the referenced record and
refuses a resolution that does not match it (§4). Nothing else can perform that
check — a `PermissionDecision` in isolation cannot see the decision it names,
which is exactly why leaving this to a model validator would have been leaving
it undone.

The invariant, in full: a decision whose `resolves` is set must name a recorded
decision, whose ruling was `CONFIRM`, which nothing else has already resolved,
and whose `tool`, `parameters_digest` and `step_id` are identical to the
resolving decision's. Its own ruling may not be `CONFIRM`, so the chain is one
link and cannot loop. A confirmation is therefore an answer to *the question that
was asked*, and the audit trail is what says so.

`reason` is required to contain visible text, by the same `_has_visible_text`
test ADR-0018 §1 applies to a tool's description and for the same reason: it is
shown to the user at the moment they are deciding, and a reason that renders as
nothing leaves the prompt with nothing to say.

### 2. `PermissionOutcome` is an ordered scale, reusing `_SeverityScale`

```python
class PermissionOutcome(_SeverityScale):   # declared least restrictive first
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"
```

Three outcomes, ordered by restrictiveness. `ALLOW` proceeds; `CONFIRM` requires
a user decision before proceeding; `DENY` refuses.

It reuses ADR-0016 §2's `_SeverityScale` rather than being a plain `StrEnum`,
and the reason is the trap that ADR already documented. `StrEnum` members *are*
strings, so an un-overridden scale compares lexicographically. Today
`"allow" < "confirm" < "deny"` happens to be correct alphabetically, which is
worse than being wrong: it means the ordering appears to work, nothing fails,
and the first member inserted out of alphabetical order — an `ESCALATE`, a
`DEFER` — silently inverts every threshold comparison written against it. A
coincidence that will not survive the next member is not a foundation. Reusing
the scale also keeps `core` to one convention for ordered enums rather than two,
and gets the `TypeError`-on-a-bare-string behaviour that ADR-0016 §2 argued for
at length.

An `ESCALATE`/`ASK_LATER` outcome and a `REQUIRES_ELEVATION` were both
considered and rejected as premature: neither has a consumer until there is an
interface to escalate *to*, and a member of an ordered scale is expensive to
insert later precisely because the rank is positional.

### 3. `ActionPolicy` rules; it does not name, mint, or record

```python
class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: ToolDefinition
    parameters: FrozenJsonMapping = _EMPTY_PARAMS
    step_id: Identifier | None = None

    @property
    def parameters_digest(self) -> str: ...   # §1

class PermissionRuling(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    outcome: PermissionOutcome
    reason: str                      # must contain visible text
    authorised_by: Identifier | None = None   # the user decision this ALLOW rests on

class ActionPolicy(Protocol):
    async def decide(self, request: ActionRequest) -> PermissionRuling: ...

    async def resolve(
        self, confirmed: PermissionDecision, *, approved: bool
    ) -> PermissionRuling: ...

```

The request is **self-contained**: it carries the definition rather than an id,
so a policy never consults a registry. That is what makes §1's guarantee
available at all — a policy that resolved an id would be reintroducing the
rebinding hazard inside the very subsystem meant to close it — and it keeps
`permissions` free of any dependency on `tools` beyond the shared `core` type
(golden rule 1).

**A policy returns a `PermissionRuling`, not a `PermissionDecision`, and the
distinction is the security property.** The first draft had `decide` return the
decision, and described the result as being "about the request" — but a
`PermissionDecision` has a `tool` field, so a conforming implementation could
have returned `ALLOW` for a *different* tool than the one it was handed, and
`authorises` would then have approved it. The prose said the policy could not
rule on anything other than what it was shown; nothing in the contract said so.

Splitting the types removes the capability rather than forbidding it. A ruling is
`outcome` and `reason` — the only two things a policy is entitled to author —
and it has no field in which to name a tool, a payload, or a step. Everything
describing *what was ruled on* is transcribed from the request by
`from_request` (§1). A policy therefore cannot substitute a subject, and this is
true of every implementation, including one written by someone who never read
this ADR.

**`resolve` keeps every permission outcome authored inside `permissions`.**
When a `CONFIRM` is answered, something has to turn "the user said yes" into an
`ALLOW`. An earlier draft left that to the caller, which put the authoring of a
permission outcome in `orchestration` or, worse, in an interface adapter — the
business logic golden rule 3 keeps out of `interfaces/`, and the deterministic
ownership of permissions VISION §7 asks for.

So the policy performs the conversion. It takes the recorded `CONFIRM` and the
user's answer and returns the resolving ruling, which lets it refuse a
confirmation it no longer accepts — one answered long after it was asked, or
answered for a request whose ruling would now be `DENY` — rather than being
obliged to rubber-stamp any `approved=True` it is handed. The caller still
records; it no longer decides. `resolve` raising or returning `DENY` on a
`confirmed` whose ruling was not `CONFIRM` is a conformance obligation, so the
method cannot be used to mint an `ALLOW` out of nothing.

**`authorised_by` records where an `ALLOW` came from.** An `ALLOW` reached
because the declaration cleared the policy's own thresholds is a different act
from one reached because the user said so, and §5's disclosure floor turns that
difference into a rule rather than a nicety: an `ALLOW` for a disclosing tool is
permitted only when it names the user decision it rests on. The field is
`None` for every ruling a policy reaches by itself, and may be set only on an
`ALLOW` — a `DENY` that cites an authorisation is incoherent.

**It is a pointer this contract does not verify, and that is bounded by two
rules rather than left open.** A `str` field naming an authorisation is one a
policy could fabricate, which would make §5's floor satisfiable by writing
something in a box. There is no authorisation store to check it against, because
standing grants are deferred — so instead:

- **The conformance suite requires `authorised_by is None`** from a policy
  constructed with no authorisation source. Today that is *every* policy, so a
  conforming implementation cannot produce a non-`None` value at all, and the
  floor is absolute in fact and not merely in intent. This is checkable now,
  against any implementation.
- **The ADR that introduces standing grants must make the pointer resolvable** —
  to a recorded user decision that actually covers this tool — and must say
  where those records live. That is a named precondition on it, in the way
  ADR-0016 §7 set three constraints on the invocation ADR rather than trusting
  it to notice them.

Until both hold, an `ALLOW` for a disclosing tool is unreachable rather than
weakly guarded.

It is present anyway for the reason ADR-0016 §4 carried `parameters_schema`
unenforced: the alternative is that the first standing grant has to *relax a
ratified floor*, which is a breaking change to a safety rule at the moment the
system is being taught to stop asking. ADR-0016 §5 is blunt about that shape —
*"a contract whose author expects it to break is not a contract"*. One optional
field now makes the feature additive later, and lets the floor be written
without an exception clause.

It also removes two things a policy had no business doing: minting an `id`, and
reading a clock. `decided_at` and `id` are supplied by the caller that records,
which leaves `decide` a genuine function of its argument — which is in turn what
makes §5's monotonicity obligations checkable at all.

**The policy does not write to the audit trail, and the caller does.** The
tempting alternative injects an `AuditTrail` into the policy so a decision
cannot escape unrecorded. It is rejected for two reasons:

- **Recording would be split anyway.** A `CONFIRM` is answered by the user,
  through an interface, long after `decide` has returned. That second decision
  (§1's `resolves`) can only be recorded by the caller. A policy that recorded
  its own rulings would put half the trail in `permissions` and half in
  `orchestration`, which is worse than putting all of it in one place.
- **A pure policy is a testable policy.** `decide` as a function of its argument
  is what lets §5's monotonicity obligations be checked at all; a policy that
  performs I/O on every call is one whose conformance suite has to mock a store
  to ask a question about ranking.

The accepted cost is real and is named rather than waved at: **nothing
mechanically forces a decision to be recorded.** The mitigation is partial and
pre-existing — ADR-0014 §4 refuses to move a step into `RUNNING` without an
`approval_ref`, so a step that executed without a decision *id* is already
unrepresentable; what is not enforced is that the id resolves to a stored
record. Closing that needs the invocation contract, which is where the two
obligations meet. Issue #107.

`parameters` is carried on the request although **no rule in this ADR reads
it**, and that is deliberate rather than an oversight. Every decision here keys
on the declared ceiling. But ADR-0017 §3 makes per-call gating a condition on
designating the tool egress seam — *"per-call gating that runs before
transmission, not merely a declared ceiling"* — so the invocation ADR must give
the policy the arguments. Carrying an unread field costs a line; adding one to a
ratified cross-subsystem contract later is a breaking change under golden rule 5,
at exactly the moment the system is being wired to transmit. ADR-0016 §4 made
the identical trade for `parameters_schema`, in this lane, for this reason.

**Gating direct Tier 0/1 data access is deferred, not forgotten.** ADR-0004 §7
gates two things: side-effecting tool calls, and access to Tier 0/1 data. Only
the first is modelled here. The second has no settled shape — issue #74 asks
whether §7's Tier 0 gating even applies to a model provider credential, and
ADR-0017 §3 makes gated credential access a condition on the egress seam. Adding
a second request shape now would mean guessing the answer to an open question and
ratifying a union type around the guess.

`ActionRequest` is therefore about invoking a tool, and **extending this contract
to cover direct data access will be a breaking change, not an additive one** — a
union parameter on `decide`, or a second Protocol beside it. An earlier draft of
this section called it additive, which was simply wrong: `decide` names a
concrete parameter type, so widening it breaks every structural implementation
under golden rule 5. Saying so is the point of deferring it honestly. Which of
the two shapes is right depends on what #74 decides the rule is, and that is a
reason to wait rather than to guess now.

### 4. The audit trail is append-only, and erasure is wholesale

```python
class AuditTrail(Protocol):
    async def record(self, decision: PermissionDecision) -> str: ...
    async def get(self, decision_id: str) -> PermissionDecision | None: ...
    async def recent(self, *, limit: int = 50) -> list[PermissionDecision]: ...
    async def export(self) -> list[PermissionDecision]: ...
    async def clear(self) -> int: ...
```

**`record` is write-once.** Re-recording an id already present raises
`DuplicateDecisionError` rather than overwriting. This is a deliberate departure
from the house pattern: `MemoryStore.add` upserts on `id`, and that is right for
memory, where the id is the caller's idempotency key. An audit trail that
upserts is one where history can be rewritten by replaying a write, which is the
one property the trail exists to deny. There is no `update`.

**`record` is also where §1's resolution invariant is enforced**, because it is
the only place both records are in hand. A decision whose `resolves` is set is
refused with `InvalidResolutionError` unless the referenced id is present, its
ruling was `CONFIRM`, no other recorded decision already resolves it, and its
`tool`, `parameters_digest` and `step_id` match the incoming decision's exactly.

This makes the trail an active participant rather than a filing cabinet, which is
a real cost worth stating: a store that validates is a store that can refuse a
write, and a caller must handle that. It is accepted because the alternative is a
`resolves` pointer that means nothing — a `CONFIRM` shown to the user for one
action and an `ALLOW` recorded for another, with the trail attesting that the
user agreed. The single-resolution rule matters for the same reason: without it,
one confirmation could be spent authorising an unbounded number of executions,
which is how "approve once" quietly becomes "approve always".

**There is no `delete(id)`; there is `clear()`.** ADR-0004 §6 gives the user the
right to delete their data and ADR-0004 §7 makes this store Tier 1, so it must
be erasable — but *selective* erasure of an audit trail is indistinguishable
from tampering with it, and an affordance that removes one inconvenient record
undoes the guarantee for all of them. Wholesale erasure is a different act: it
destroys the trail visibly and completely, which is what a data-rights operation
should look like. So the user may burn the book; nobody may tear out a page.

`recent` is newest-first with a bounded default because the realistic query is
"what has the assistant just done", and an unbounded read of a Tier 1 store by
default is a shape worth not offering. Richer querying — by tool, by outcome, by
window — is deferred until something asks for it; adding a query method is
additive, and guessing at filters now is how a contract acquires methods nobody
calls.

`export` matches `MemoryStore.export` and `PlanStore.export` and discharges
ADR-0004 §6's portability obligation for this store.

**Implementations persist locally only**, as `PlanStore` does (ADR-0014 §5): the
trail is Tier 1 by ADR-0004 §7's own words, so ADR-0004 §2's residency clause —
untouched by ADR-0017 — governs it, and none of this may be written to a remote
service. Durability is what forces §1's records to be serialisable, and
`PermissionDecision` is: every field, including the embedded `ToolDefinition`
and its `FrozenJsonMapping`, survives a `model_dump(mode="json")` round-trip
unchanged. That is a property of the design rather than a hope — a decision that
could not be reloaded would make the pin worthless across exactly the restart
#54 is about.

**Every query returns a detached snapshot** — the list, the decisions in it, and
everything mutable those reach. This is ADR-0018 §3's rule applied to a second
store, and the argument transfers without modification: `list` is mutable, a
`PermissionDecision` embeds a `ToolDefinition` which embeds a `ToolCost`, and
`frozen=True` refuses `x.outcome = ...` but not `x.__dict__["outcome"] = ...`.
A store that handed back its own objects would let a reader rewrite the record
of what was approved. As in ADR-0018 §3, this isolates *store state* and does
not make a decision the caller now holds tamper-proof; the guarantee is about
what the trail **produces**.

**Retention is deferred.** ADR-0004 §6 requires retention rules "per memory
type"; this store is not a memory type, and a trail that expires records is one
that forgets what it was built to remember. Whether an audit trail should have a
TTL at all is a genuine question with a privacy argument on each side, and it
does not block anything. Issue #108.

### 5. What every policy must satisfy: monotone, and fail-closed twice over

A policy is *the user's*, so the contract cannot fix a threshold — "confirm at
or above `MEDIUM`" is a setting, not a decision this ADR gets to make. What it
can fix is the shape of the function. The shared `ActionPolicy` conformance suite
requires the following of `ruling.outcome`; the corresponding `AuditTrail` suite
covers write-once, the resolution invariant, ordering, and detachment (§4).

**Monotonicity in severity.** Raising `risk_level`, raising `reversibility`, or
widening `discloses` — with everything else held equal — must never produce a
*less* restrictive outcome. A policy may be as permissive or as strict as its
user wants; what it may not be is more permissive about the more dangerous of
two otherwise identical actions. This is checkable on any implementation without
knowing its rules, and it is what rules out the whole class of accidents where a
threshold comparison is written the wrong way round — including, concretely, the
`RiskLevel.CRITICAL < RiskLevel.LOW` inversion ADR-0016 §2 disarmed on the type
but which a policy could still reproduce in its own arithmetic.

**Off-device disclosure is never auto-granted.** A definition whose `discloses`
contains `SECRET` or `PERSONAL` may not receive `ALLOW` with `authorised_by`
unset. *Auto*-granted is the operative word: the floor is on the policy deciding
by itself, not on the outcome, so an `ALLOW` naming the user decision it rests on
is permitted and is how a standing grant will work (§3, §6). Today nothing
populates that field, so in practice the floor is absolute — but it is written
against the distinction that matters rather than against a proxy for it, which is
what keeps §6's relief valve reachable without amending this clause.

This is the enforceable form of the two-field rule ADR-0016 §2 states as an
obligation on this subsystem — *"`reversibility` alone is not sufficient to
auto-grant … Reading both fields is not an implementation detail left to
`permissions`"* — and it has to be a floor rather than something weaker, because
nothing weaker is checkable. An earlier draft of this ADR tried monotonicity
alone and then conceded, in writing, that a policy keyed on `reversibility`
could ignore `discloses` entirely and still conform. That is not a gap to
disclose; it is a ratified obligation left unmet, and disclosing it does not
discharge it. Monotonicity cannot carry this weight in principle: a function
that ignores an input is monotone in that input, so no monotonicity requirement
can ever force a field to be read.

The floor and monotonicity are also not independent — given monotonicity, the
floor is the *only* form the obligation can take. If some request with
`discloses=(PERSONAL,)` drew an unauthorised `ALLOW`, the otherwise-identical
request with `discloses=()` is less severe and so draws one too, and disclosure
has been shown to make no difference at the auto-grant boundary. Forbidding it
outright is therefore not a strong reading of ADR-0016 §2; it is the reading.

Monotonicity is stated over the outcome and is unaffected by `authorised_by`: a
user authorisation is an input the policy was given, not a severity axis, and the
comparison holds requests equal in every other respect including that one.

**The cost is over-prompting, and ADR-0016 already accepted it.** Almost every
hosted integration transmits something, and the tuples are ceilings (ADR-0016
§3), so this floor means most real tools reach `CONFIRM` rather than `ALLOW`.
ADR-0016's own Consequences call that *"the safe direction"* for a bound to err
in. The relief valve is deliberately **not** a policy quietly deciding on the
user's behalf: it is the standing grant (§6), which ADR-0017 §3 already
anticipates when it accepts an authorisation tracing to *"a user decision or a
standing user policy"*. A user who wants their calendar tool to stop asking says
so once, on the record; the difference between that and an auto-grant is the
whole point.

An earlier draft argued the floor would reproduce the "trains its user to
approve everything" failure ADR-0016 §5 warns of. That was a misreading: §5's
argument is about *tool granularity* — why an integration registers one
definition per operation rather than merging read and send into one
conservative declaration — and it says nothing about prompt volume arising from
disclosure.

**An `UNKNOWN` cost is never auto-granted.** ADR-0016 §4 ratified `UNKNOWN` as
*"declared: the author does not know — policy must fail closed"*, and this is
where that clause acquires an enforcer. `FREE` is a fact a spend policy can add
to a total; `UNKNOWN` is an absence of information, and an implementation that
treated the two alike would make the enum pointless.

**What these obligations do not force, so nobody reads more into them than is
there.** They fix a *shape*, not a policy. Within the floors, a conforming
implementation may be arbitrarily permissive — a policy that returns `CONFIRM`
for everything and one that returns `ALLOW` for every non-disclosing, known-cost
tool are both conforming, and neither is what a user would want. Choosing the
thresholds between them is the default policy's job, not the contract's, and the
conformance suite deliberately cannot tell a good policy from a mediocre one.

What the contract does guarantee is that the failures which are *not* matters of
taste cannot occur: an inverted comparison, a disclosure auto-granted, a cost
nobody declared treated as free.

### 6. Deferred

- **Standing grants and policy state.** "Always allow this tool" needs durable,
  per-user policy state with its own data-rights obligations — a store, not a
  field. It is deferred but **load-bearing**: §5's disclosure floor sends most
  real tools to `CONFIRM`, and the standing grant is the only sanctioned way to
  stop asking. Until it lands, a disclosing tool prompts every time, which is
  the correct default and a poor steady state. The seam it will need is already
  here and unpopulated: `PermissionRuling.authorised_by` (§3), so the feature is
  additive rather than a relaxation of §5's floor — a standing grant is a
  recorded user decision that sources an `ALLOW`, not a new outcome and not a
  policy deciding silently.
- **Spend accumulation.** The declaration-level rule lands (`UNKNOWN` fails
  closed); a running total against a budget needs invocation to report what was
  actually spent, and ADR-0016 §4 already records that `cost` is an estimate
  nothing reconciles.
- **Recipient authorisation** (ADR-0017 §3, issue #68). A tier ceiling says
  nothing about who receives the bytes. It needs resolved destinations, which
  need arguments interpreted per tool, which needs invocation.
- **Gating direct Tier 0/1 data access** (§3), pending issue #74.
- **Payload description** as opposed to binding (ADR-0017 §3, issue #57).
- **Retention for the trail** (§4, issue #108).
- **Richer audit queries** (§4).

## Consequences

- **Every permission outcome is authored inside `permissions`.** `resolve` turns
  a user's answer into the ruling that resolves a `CONFIRM`, so no adapter or
  wiring layer ever constructs one. The caller records; it does not decide.
- **`authorised_by` is unverified by this contract, and unreachable because of
  it.** A conforming policy given no authorisation source must leave it `None`,
  which today is every policy, and the standing-grant ADR inherits the named
  obligation to make the pointer resolve. A floor guarded by a fabricable string
  would be worse than no floor, so the guard is that nothing may set it yet.
- **Extending the contract to direct Tier 0/1 data access will be breaking**
  (§3), not additive as an earlier draft claimed. `decide` names a concrete
  parameter type. Whether it becomes a union or a second Protocol waits on #74.
- **The floor is written against auto-granting, not against the outcome.** A
  disclosing tool may be `ALLOW`ed only by a ruling that names the user decision
  it rests on, and `PermissionRuling.authorised_by` carries that today while
  nothing yet sets it. The first draft forbade the outcome outright and then
  offered standing grants as the relief valve, which the floor made
  unreachable — an inconsistency architecture review caught, and one that would
  have cost a breaking change to a safety rule to fix later.
- **New `core` surface:** `PermissionOutcome`, `PermissionRuling`,
  `ActionRequest`, `PermissionDecision`, the `ActionPolicy` and `AuditTrail`
  Protocols, and `AuditError`/`DuplicateDecisionError`/`InvalidResolutionError`
  in `core/errors.py`. Two Protocols mean
  **two triads** in the implementation PR — contract, shared conformance suite,
  and canonical fake for each — which
  `tests/core/test_protocol_triad.py` enforces mechanically and for which no
  exemption is available.
- **A permission decision is no longer about a name.** #54's permissions half is
  closed by construction: the decision embeds the declaration, so a rebound id,
  a definition substituted across a restart, and a definition tampered through
  `__dict__` are all a value comparison away from detection. The issue stays
  open for its invocation half — one `authorises()` call the executor must make
  — and that is now a seam rather than a description.
- **The subject of a decision is transcribed, never authored.** A policy returns
  a ruling with no field naming a tool; `from_request` copies the subject across;
  `authorises` compares the whole request, arguments included. Three separate
  substitutions — a policy ruling on A and answering about B, a caller binding a
  decision to the wrong request, an executor running different arguments than
  were approved — are closed by the shape of the types rather than by a sentence
  asking implementers not to. The first draft closed none of them and asserted
  all three; architecture review is what caught it.
- **The audit trail validates, so it can refuse a write.** The resolution
  invariant (§1, §4) is enforced where both records are visible, which is the
  only place it can be. The cost is that `record` has a failure mode callers must
  handle; the alternative was a `resolves` pointer attesting that a user agreed
  to something they were never shown.
- **The audit trail is a Tier 1 store with the narrowest write surface that
  satisfies ADR-0004 §6.** Append-only, no update, no selective delete. The cost
  is that a user who wants one embarrassing record gone must clear the trail, and
  that is the intended trade.
- **Policy conformance is a shape, not a threshold.** Monotonicity is checkable
  against any implementation without knowing its rules, which is what makes a
  shared suite possible for a subsystem whose behaviour is meant to be
  user-configurable. Two hard floors sit under it, both discharging clauses
  other ADRs already ratified rather than inventing policy here.
- **ADR-0016 §2's two-field rule is now enforceable rather than exhorted.** A
  disclosing tool cannot be auto-granted by any conforming policy, which is what
  that ADR asked of this subsystem and what an earlier draft of this one waived
  in writing. The cost is over-prompting until standing grants land, and
  ADR-0016 already accepted over-prompting as the safe direction.
- **Monotonicity cannot force a field to be read**, and this ADR now says so
  rather than relying on it. A function that ignores an input is monotone in
  that input, so any obligation of the form "consider field X" has to be written
  as a floor. That generalises beyond `discloses` and is worth remembering the
  next time a shape-based obligation looks sufficient.
- **`orchestration` gains an obligation the type system does not carry**: it
  must record what it decides. ADR-0014 §4 already forces the `approval_ref` to
  exist; nothing yet forces it to resolve.
- **`permissions` is no longer blocked, and nothing else is unblocked by it
  yet.** The layer rules on actions nothing can perform (ADR-0016 §7 defers
  invocation), which is the same unusual intermediate state ADR-0016 shipped in
  and drew ADR-0018's five corrections. The mitigation is the one ADR-0018
  prescribed, and it was taken: the shape above was spiked against a throwaway
  implementation before ratification and discarded, which is what settled six
  things this ADR would otherwise be asserting — that `PermissionOutcome` can
  subclass `_SeverityScale` and inherits its `TypeError`-on-a-bare-string
  behaviour, that the parameters digest is stable across key order, that
  `PermissionRuling` has no field in which a subject could be named, that
  `authorises` rejects a substituted tool, altered arguments and a different
  step alike, that `from_request` transcribes the subject without the request
  becoming a stored field, and that a decision survives a
  JSON round-trip with its embedded definition intact. Implementation contact is
  not proof, and ADR-0018 was written by an implementation finding five things a
  review did not.
- **A Tier 0 credential may not appear in a request's `parameters`** (§1). The
  ratified architecture already implies it — credentials live in the keyring
  behind `SecretStore` — but this contract is the first that would *durably
  record something derived from* a parameter, so it says so explicitly. A hash
  of a low-entropy secret is a weakened copy of it, not an absence of one.
- **Two ADR-0017 §3 conditions are partly discharged** — a named approver able
  to refuse (`DENY` exists and a policy must be able to reach it), and the
  payload bound before transmission (§1's digest). Neither is *fully* discharged
  and the seam stays undesignated; §3's list is the invocation ADR's to complete.
- **Revisit when** invocation lands (does the request need the resolved
  destination, and does `authorises` need to widen?), when standing grants
  arrive, or when a real policy makes the `PERSONAL` gap in §5 measurable.
</content>
</invoke>
