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

### 1. A decision records the definition it ruled on, not its name

```python
class PermissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    outcome: PermissionOutcome
    reason: str                      # must contain visible text
    tool: ToolDefinition             # the declaration ruled on, verbatim
    parameters_digest: str           # binds the payload without storing it
    decided_at: datetime             # timezone-aware
    step_id: Identifier | None = None
    resolves: Identifier | None = None
```

**`tool` is the whole `ToolDefinition`, embedded by value.** This is the single
most important clause here and it is what closes #54: there is no name left to
rebind. A decision does not say "I approved `send_message`"; it says "I approved
*this declaration*, which happens to call itself `send_message`, is `REVERSIBLE`,
discloses `PERSONAL`, and costs nothing". A process that restarts and registers a
different definition under the same id has not altered any decision, and the
mismatch is a value comparison away.

That comparison is offered on the type rather than left to each caller:

```python
def authorises(self, definition: ToolDefinition) -> bool:
    """Whether this decision authorises invoking ``definition``."""
    return self.outcome is PermissionOutcome.ALLOW and definition == self.tool
```

`ToolDefinition` is a frozen pydantic model, so `==` is field-wise and total.
This satisfies ADR-0016 §2's three-part test for a semantic intrinsic to a type
— computable from the type's own declaration, independent of policy,
configuration, context and clock, and the same answer for every consumer — which
is the test that permits it in `core` at all.

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
§7). The remaining half is one call — `decision.authorises(definition)` against
the definition the executor is about to run — and it belongs to the invocation
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
arguments a call proposes may carry Tier 0 or Tier 1 data. ADR-0017 §3 is
explicit about the consequence of putting them in a durable record: bind a
reference, *"or the binding and every audit record derived from it become Tier 0
stores"*. So the decision binds the payload by digest and holds none of it.

The digest is computed by `core`, not by callers, over the canonical JSON form
of the request's `parameters` — `json.dumps(sort_keys=True,
separators=(",", ":"), ensure_ascii=False)` of the mapping's JSON dump, then
SHA-256, hex. It is well-defined because `FrozenJson` is already constrained to
JSON-safe values and already rejects non-finite floats (ADR-0014 §2), which is
the case that would otherwise have no encoding. Specifying it here is what stops
two implementations recording different digests for the same call.

Two limits on what that digest is worth, both inherited rather than introduced.
It binds; it does not *describe*. ADR-0017 §3 requires a payload "described
inspectably after it — which records, how many, at what tiers", and observes
that a digest leaves an auditor unable to tell one memory record from the whole
database. That description is issue #57's and the invocation contract's; this
ADR discharges the binding half of the condition and none of the description
half.

**`resolves` makes the confirmation loop auditable.** A `CONFIRM` outcome is
recorded like any other. If the user then answers, the answer is a *second*
decision whose `resolves` names the first. Without it a confirmation the user
declined is indistinguishable from one nobody ever answered — the same
ambiguity ADR-0017 §3 refuses to accept on the egress side, where a timeout must
not read as a successful disclosure. A decision that `resolves` another may not
itself be `CONFIRM`, so the chain is one link and cannot loop.

`reason` is required to contain visible text, by the same `_has_visible_text`
test ADR-0018 §1 applies to a tool's description and for the same reason: it is
shown to the user at the moment they are deciding, and a reason that renders as
nothing leaves the prompt with nothing to say.

### 2. `PermissionOutcome` is an ordered scale, reusing `_SeverityScale`

```python
class PermissionOutcome(_SeverityScale):   # declared least restrictive first
    ALLOW; CONFIRM; DENY
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

### 3. `ActionPolicy` decides; it does not record

```python
class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: ToolDefinition
    parameters: FrozenJsonMapping = _EMPTY_PARAMS
    step_id: Identifier | None = None

class ActionPolicy(Protocol):
    async def decide(self, request: ActionRequest) -> PermissionDecision: ...
```

The request is **self-contained**: it carries the definition rather than an id,
so a policy never consults a registry and cannot rule on something other than
what it was shown. That is what makes §1's guarantee available at all — a policy
that resolved an id would be reintroducing the rebinding hazard inside the very
subsystem meant to close it — and it keeps `permissions` free of any dependency
on `tools` beyond the shared `core` type (golden rule 1).

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
obligations meet. Issue filed.

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
ratifying a union type around the guess. `ActionRequest` is therefore about
invoking a tool, and widening it is a later, additive decision once #74 settles.

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
does not block anything. Issue filed.

### 5. What every policy must satisfy: monotone, and fail-closed twice

A policy is *the user's*, so the contract cannot fix a threshold — "confirm at
or above `MEDIUM`" is a setting, not a decision this ADR gets to make. What it
can fix is the shape of the function. The shared conformance suite requires:

**Monotonicity in severity.** Raising `risk_level`, raising `reversibility`, or
widening `discloses` — with everything else held equal — must never produce a
*less* restrictive outcome. A policy may be as permissive or as strict as its
user wants; what it may not be is more permissive about the more dangerous of
two otherwise identical actions. This is checkable on any implementation without
knowing its rules, and it is what rules out the whole class of accidents where a
threshold comparison is written the wrong way round — including, concretely, the
`RiskLevel.CRITICAL < RiskLevel.LOW` inversion ADR-0016 §2 disarmed on the type
but which a policy could still reproduce in its own arithmetic.

**Tier 0 disclosure is never auto-granted.** A definition whose `discloses`
contains `SECRET` may not receive `ALLOW`. Transmitting a credential off-device
is the one action for which no configuration should be able to remove the human,
and ADR-0004 §3's whole treatment of Tier 0 — keyring-only, never in the
database, never in a file — makes silent egress of it incoherent.

**An `UNKNOWN` cost is never auto-granted.** ADR-0016 §4 ratified `UNKNOWN` as
*"declared: the author does not know — policy must fail closed"*, and this is
where that clause acquires an enforcer. `FREE` is a fact a spend policy can add
to a total; `UNKNOWN` is an absence of information, and an implementation that
treated the two alike would make the enum pointless.

**What these obligations deliberately do not force, so nobody reads more into
them than is there.** They do *not* force a policy to read `discloses` for the
`PERSONAL` tier. Monotonicity is trivially satisfied by ignoring a field —
a constant function is monotone — so a policy keyed on `reversibility` alone
conforms to every rule above while walking straight into the trap ADR-0016 §2
warns of. That is a real gap and it is stated rather than papered over, because
the alternative was worse: a fixed floor requiring confirmation for any
`PERSONAL` disclosure would prompt on essentially every hosted integration,
since almost all of them transmit something and the tuples are ceilings (ADR-0016
§3). That is the "trains its user to approve everything" failure ADR-0016 §5
rejects a merge rule for, arriving from the other side.

What closes it instead is not a type: it is the default policy the
implementation PR ships, which reads both fields, plus the fact that §1 records
the declaration in the trail — so an auto-granted disclosure is *visible* to
whoever reads it. A gap named with a mitigation is the honest position here;
ADR-0018's durable lesson was that a security property claimed but not held is
worse than one bounded and disclosed.

### 6. Deferred

- **Standing grants and policy state.** "Always allow this tool" is the obvious
  next feature and needs durable, per-user policy state with its own
  data-rights obligations — a store, not a field. Nothing here forecloses it:
  a standing grant is a source of an `ALLOW`, not a new outcome.
- **Spend accumulation.** The declaration-level rule lands (`UNKNOWN` fails
  closed); a running total against a budget needs invocation to report what was
  actually spent, and ADR-0016 §4 already records that `cost` is an estimate
  nothing reconciles.
- **Recipient authorisation** (ADR-0017 §3, issue #68). A tier ceiling says
  nothing about who receives the bytes. It needs resolved destinations, which
  need arguments interpreted per tool, which needs invocation.
- **Gating direct Tier 0/1 data access** (§3), pending issue #74.
- **Payload description** as opposed to binding (ADR-0017 §3, issue #57).
- **Retention for the trail** (§4).
- **Richer audit queries** (§4).

## Consequences

- **New `core` surface:** `PermissionOutcome`, `ActionRequest`,
  `PermissionDecision`, the `ActionPolicy` and `AuditTrail` Protocols, and
  `AuditError`/`DuplicateDecisionError` in `core/errors.py`. Two Protocols mean
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
- **The audit trail is a Tier 1 store with the narrowest write surface that
  satisfies ADR-0004 §6.** Append-only, no update, no selective delete. The cost
  is that a user who wants one embarrassing record gone must clear the trail, and
  that is the intended trade.
- **Policy conformance is a shape, not a threshold.** Monotonicity is checkable
  against any implementation without knowing its rules, which is what makes a
  shared suite possible for a subsystem whose behaviour is meant to be
  user-configurable. Two hard floors sit under it, both discharging clauses
  other ADRs already ratified rather than inventing policy here.
- **A conforming policy can still ignore `PERSONAL` disclosure** (§5). Named,
  with its mitigation, because the fixed floor that would close it produces the
  approve-everything failure ADR-0016 §5 rejects. Revisit if a real integration
  suite makes the prompt volume measurable rather than predicted.
- **`orchestration` gains an obligation the type system does not carry**: it
  must record what it decides. ADR-0014 §4 already forces the `approval_ref` to
  exist; nothing yet forces it to resolve.
- **`permissions` is no longer blocked, and nothing else is unblocked by it
  yet.** The layer rules on actions nothing can perform (ADR-0016 §7 defers
  invocation), which is the same unusual intermediate state ADR-0016 shipped in
  and drew ADR-0018's five corrections. The mitigation is the one ADR-0018
  prescribed, and it was taken: the shape above was spiked against a throwaway
  implementation before ratification and discarded, which is what settled four
  things this ADR would otherwise be asserting — that `PermissionOutcome` can
  subclass `_SeverityScale` and inherits its `TypeError`-on-a-bare-string
  behaviour, that the parameters digest is stable across key order, that
  `authorises` rejects a substituted definition, and that a decision survives a
  JSON round-trip with its embedded definition intact. Implementation contact is
  not proof, and ADR-0018 was written by an implementation finding five things a
  review did not.
- **Two ADR-0017 §3 conditions are partly discharged** — a named approver able
  to refuse (`DENY` exists and a policy must be able to reach it), and the
  payload bound before transmission (§1's digest). Neither is *fully* discharged
  and the seam stays undesignated; §3's list is the invocation ADR's to complete.
- **Revisit when** invocation lands (does the request need the resolved
  destination, and does `authorises` need to widen?), when standing grants
  arrive, or when a real policy makes the `PERSONAL` gap in §5 measurable.
</content>
</invoke>
