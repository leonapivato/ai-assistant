# 16. `ToolDefinition`: declared risk metadata and a `ToolRegistry` to reason over

- Status: Proposed
- Date: 2026-07-19

## Context

The request pipeline (`CLAUDE.md`) runs `intent → context assembly → memory
retrieval → planning → tool selection → permission check → execute → learn`.
The `tools` subsystem owns the registry the fifth step selects from, and it has
no contract today: neither a registry Protocol nor a `ToolDefinition` type
exists. `ToolDefinition` is the last of the seven first-vertical artifacts
(`docs/roadmap.md`) still missing.

Two consumers are blocked on it, and neither is `tools` itself:

- **`permissions`** (`ActionPolicy`, ADR-0004 §7) must gate *every*
  side-effecting tool call. Its ratified vocabulary — confirmation thresholds,
  spend limits, reversibility requirements — is meaningless unless the thing it
  rules on declares its risk, its reversibility and its cost. Today a policy
  could only be written as a hard-coded list of integration names.
- **`orchestration`** owns tool selection, which ADR-0014 §2 deliberately left
  as a real stage: an `ActionPlan` step names a **capability**, not a tool,
  precisely so that selection can weigh risk and reversibility rather than
  ratify a choice the planner already made. That weighing has nothing to weigh
  until the metadata exists.

VISION §3, "Trust Must Be Built Into the Architecture", enumerates what the
orchestration layer must state explicitly: which tools are available, what data
each can access, which actions require approval, which are reversible, spending
and communication limits, and audit history. Every one of those is a property of
a tool, and none of them is expressible today. The roadmap states the design
constraint directly: *rich metadata lets the planner and permission layer reason
about tools instead of hard-coding integrations.* This ADR is mostly about
taking that seriously.

ADR-0014 also left this lane two explicit debts to settle:

- **The capability vocabulary.** "`capability: str` is an uncontrolled
  vocabulary. Nothing yet enforces that a planner's capability names match what
  tools advertise; a shared vocabulary (or its rejection in favour of matching
  on `ToolDefinition` metadata) is Lane B's to settle."
- **Idempotency keys.** "Turning at-most-once into exactly-once requires tools
  that dedupe against a caller-supplied key; that is Lane B's contract to
  offer."

This adds new `core` types and a Protocol, so it is ADR-worthy (golden rule 5).

## Decision

We will model a tool as a **declaration** — a frozen `ToolDefinition` whose
safety-relevant properties are stated, not inferred — and a `ToolRegistry`
Protocol that stores and queries those declarations without ranking them.

### 1. Declared, not inferred, and no safety field has a default

```python
class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    capability: Identifier
    description: str
    risk_level: RiskLevel            # required
    reversibility: Reversibility     # required
    side_effecting: bool             # required
    reads: tuple[DataTier, ...]      # required
    writes: tuple[DataTier, ...]     # required
    discloses: tuple[DataTier, ...]  # required — what leaves the device (§3)
    cost: ToolCost                   # required
    idempotency: Idempotency         # required
    idempotency_window: timedelta | None = None   # required iff KEYED
    latency: timedelta | None = None
    parameters_schema: FrozenJsonMapping = {}
```

**Every field that a permission decision depends on is required.** This is the
single most important property of the type and the reason it is worth an ADR.
A default is a claim, and for `reads`/`writes` the natural-looking default —
the empty tuple — is the claim *"this tool touches no data"*, which is exactly
the false statement a forgetful integration author would ship. `risk_level` has
no defensible default either: `LOW` under-protects and `CRITICAL` would be
routinely overridden without thought. `cost` and `idempotency` are required for
the same reason and are discussed in §4, where the shape each needs in order to
be *declarable* — rather than merely omitted — is the substance of the decision.
Making the author write them down is the whole mechanism; a tool that does not
declare its reach does not load.

The alternative — deriving risk from the integration's identity, or from
whether the tool's name starts with `send_` — is the hard-coding this ADR
exists to remove, and it fails silently for every tool nobody thought about.

`frozen=True` for the same reason `ActionPlan` is frozen (ADR-0014 §2): a
permission decision is recorded against the definition that was in force, and a
definition that can be edited after a decision was made against it makes the
audit trail a description of the present rather than a record of the past.
Changing a tool's metadata means registering a changed definition, which §5
governs.

`description` is the only free text, and it has two audiences: the model, which
is told what the tool does, and the user, who is shown what they are approving.

### 2. Risk and reversibility are ordered scales, and the ordering lives in `core`

```python
class RiskLevel(StrEnum):       # declared least severe first
    LOW; MEDIUM; HIGH; CRITICAL

class Reversibility(StrEnum):   # declared least severe first
    REVERSIBLE; RECOVERABLE; IRREVERSIBLE
```

- `REVERSIBLE` — the tool can undo it (delete the calendar event it created).
- `RECOVERABLE` — undoable, but not by this tool (a file in the trash; a
  correction email).
- `IRREVERSIBLE` — it cannot be taken back (money moved, a message delivered to
  a third party).

**Both are comparable, and the comparison is by severity.** The canonical
policy sentence is a threshold — "confirm anything at or above `MEDIUM`",
"refuse anything less reversible than `RECOVERABLE`" — so an unordered scale
would force every consumer to carry its own rank table, and two subsystems that
disagreed about whether `HIGH` outranks `MEDIUM` would disagree about whether an
action needed approval.

This is not merely an addition. `StrEnum` members *are* strings, so they already
compare — **lexicographically**, which makes `RiskLevel.CRITICAL <
RiskLevel.LOW` evaluate to `True`. A policy written the obvious way against the
obvious type would silently invert on precisely the most dangerous value. So
severity ordering is not a convenience here; it is the removal of a live trap,
and it has to live on the type rather than in `permissions/`, because the trap
is reachable from anywhere the enum is.

The comparison operators are therefore overridden to rank by declaration order,
and they return `NotImplemented` against anything that is not the same enum —
so `RiskLevel.LOW < "medium"` raises rather than quietly answering
lexicographically. Rank is derived from declaration order rather than a parallel
table, so a level inserted in the middle cannot be given a rank that contradicts
where it reads.

Putting behaviour in `core/types.py` is a deliberate exception to that module's
"data only" convention, of the same kind `FrozenDict` and
`ExecutionState.is_active` already are: this is what the type *means*, not what
a subsystem does with it.

### 3. Data reach reuses ADR-0004's tiers, and gating stays in `permissions`

`reads` and `writes` are tuples of `DataTier` — the existing Tier 0/1/2
classification, not a new taxonomy. This answers VISION §3's "what data each
tool can access" in the vocabulary the privacy ADR already ratified, so a policy
like *"a tool that reads Tier 0 always requires confirmation"* is expressible
without a translation layer, and a tool's declared reach is checkable against
the tiering the rest of the system is already built on.

They are ordered tuples, sorted and de-duplicated on validation, rather than
`frozenset`s. A `frozenset` serialises in hash order, which varies between
processes; these values are written into permission decisions and audit records,
so a stable serialisation matters more than set syntax at the call site.

`side_effecting` is declared rather than derived. Every derivation considered
was wrong for a real tool: non-empty `writes` misses a tool that sends an email
while storing nothing locally, and non-`REVERSIBLE` misses a tool that
reversibly creates a draft. Two consistency rules make the contradictory
combinations unrepresentable rather than merely discouraged:

- a tool that declares `writes` **is** side-effecting;
- a tool that is not side-effecting is `REVERSIBLE` — there is nothing to
  reverse.

Deliberately *not* a rule: risk is unconstrained by `side_effecting`. A
read-only tool that pulls an entire mailbox into a prompt is high risk, and a
type that refused to let it say so would be worse than one that stayed quiet.

**No field on this type decides whether the permission gate is consulted,
because every invocation is gated.** An earlier draft derived a
`requires_permission` predicate on `ToolDefinition` — `side_effecting` or Tier
0/1 reach, the disjunction ADR-0004 §7 actually states. That was wrong twice
over. It put a gating decision on a shared `core` type when ADR-0004 §7 assigns
gating to `permissions/`, and — worse — a predicate that can return `False` is a
documented route around the gate, so every future bug in it is an
under-protection that looks like a fast path.

The rule is therefore unconditional and needs no predicate: **every tool
invocation goes through `permissions/`, and the definition supplies facts rather
than conclusions.** This is not a new burden invented here. ADR-0014 §4 already
requires *every* transition into `RUNNING` to carry an `approval_ref`, including
the common case where the permission layer cleared the step automatically with
no prompt shown — precisely so that the silent, automatic actions are the ones
that can still be correlated with their authorisation. A tool that reads the
clock is gated too; it receives an automatic grant and a recorded decision,
which costs a dictionary lookup and buys a complete audit trail.

What `permissions/` does with `risk_level`, `reversibility`, `reads`, `writes`
and `discloses` — which combinations auto-grant, which prompt, which refuse — is
its ADR to write, not this one's to pre-empt.

**`discloses` — what leaves the device.** `reads` and `writes` describe a tool's
reach into *stored* data; neither says whether calling it sends that data off
the machine, and for a subsystem whose whole job is talking to external services
that is the question ADR-0004 cares most about. `discloses` is the tiers a call
transmits off-device, required and fail-closed like the other two, so that
"communication limits" (VISION §3) and ADR-0004 §5's minimisation rule have a
declared fact to police instead of an inference from the integration's name.

It states the *tier* that leaves, not the *destination*. Which recipient a call
reaches is parameter-level — the address is an argument, not a property of the
tool — and belongs with the approved-recipients policy §7 defers.

**This does not, by itself, authorise any egress.** ADR-0004 §2 says the
`models/` layer is the only component permitted to send user data off-device and
"every other egress is a bug", while the same ADR's §3 has `tools/` reading
credentials for external services, its §7 gates "every side-effecting tool
call", and its Consequences provision for "the designated `tools/` integration
boundary" importing network clients. §2's wording predates and contradicts the
tool layer the rest of the ADR plans for — the same kind of stale absolute its
2026-07-19 amendment already fixed once, when "the model provider" had to become
the configured *set*.

Reconciling that is **not** this ADR's to do quietly. Nothing here is callable
(§7), so nothing here transmits anything, and ratifying it changes no egress
behaviour. `discloses` exists so that when the invocation ADR arrives it has
something to write its rule against; that ADR must amend ADR-0004 §2 explicitly
before the first tool sends a byte. That obligation is recorded as issue #52
rather than assumed.

### 4. Cost, latency, and idempotency

`cost` is the price of *one invocation of the tool itself*, and it is
**required**, with "free" and "nobody knows" as distinct declarations:

```python
class CostBasis(StrEnum):
    FREE       # declared: an invocation costs nothing
    PER_CALL   # declared: `amount` of `currency` per invocation
    UNKNOWN    # declared: the author does not know — policy must fail closed

class ToolCost(BaseModel):
    basis: CostBasis
    amount: Decimal | None = None      # required iff PER_CALL, ge 0
    currency: str | None = None        # required iff PER_CALL, ISO-4217
```

An optional `cost` defaulting to `None` was the first draft and it reproduced,
in the one field where money is at stake, precisely the failure §1 exists to
prevent: a paid integration whose author simply forgot the field would load, and
a spend policy reading `None` as "no meaningful cost" would approve it. The
distinction that matters to a policy is not present/absent but *free* versus
*unknown* — the first is a fact it can add to a running total, the second is an
absence of information it must refuse or escalate on. A two-state field cannot
carry that, so the enum is what makes the declaration possible rather than
merely mandatory.

`Decimal`, never a float, because this feeds spend limits and binary floating
point is not a thing to accumulate money in.

It deliberately does **not** model money the tool *moves*. The price of a flight
lives in the call's parameters, not in the definition of the tool that books
it; a definition-level field could only ever hold a fiction. Spend limits over
transacted amounts need parameter-level policy, which needs the schema
introspection §7 defers.

`latency` is the expected duration of a typical call, for the selection stage
and for deciding whether an action fits an interactive turn. Advisory: it is not
a timeout, and nothing enforces it.

**`idempotency` declares a retry guarantee, not the presence of a parameter.**

```python
class Idempotency(StrEnum):
    NONE       # a repeat acts again; retrying may double the effect
    NATURAL    # the operation is idempotent by nature (a read; set-to-a-value)
    KEYED      # repeats carrying the same key are deduplicated, per below
```

`accepts_idempotency_key: bool` was the first draft, and a boolean of that name
answers the wrong question. *Accepting* a key is syntax; a tool may accept one
and ignore it, scope it per-connection, or forget it in a second — and an
executor told only that the parameter exists would conclude it "may safely
retry" on the strength of a signature. What ADR-0014 §7 actually asks for is a
*guarantee*, so the field names one, and `KEYED` carries the two properties that
make the guarantee usable:

- **Scope** is the tool, identified by `ToolDefinition.id`. Two calls to the
  same tool with the same key are the same call; nothing is promised across
  tools, and a tool whose upstream dedupes more narrowly than that (per
  connection, per session) may not declare `KEYED`.
- **Lifetime** is `idempotency_window`, required when and only when `KEYED`. A
  repeat inside the window is deduplicated; outside it, the tool is free to act
  again. A window is mandatory because every real implementation has one, and an
  unstated one is the failure mode that looks safe in testing and doubles a
  charge under a slow retry.

`NATURAL` is not a weaker `KEYED`: it is the common case of a read, or a write
that sets a value rather than appending one, which is safe to retry with no key
at all. Collapsing it into `NONE` would make the executor treat re-reading a
calendar as dangerous; collapsing it into `KEYED` would demand a window that
means nothing.

**This does not settle ADR-0014's idempotency debt, and this ADR does not claim
it does.** Nothing here requires or exercises the guarantee, because nothing
invokes tools yet (§7); a declaration no caller checks is a promise, and
exactly-once execution needs the invocation contract to pass a key, the
executor to reuse it across a retry, and a conformance test to hold a tool to
it. What lands here is the vocabulary those need, on the contract before the
executor exists, so that the guarantee does not have to be retrofitted as a
breaking change at the moment it most matters. The debt is carried forward
explicitly in §7.

`parameters_schema` is a JSON Schema object carried as a `FrozenJsonMapping`,
which is what ADR-0014 §2 promised this lane would provide ("argument *schemas*
belong to `ToolDefinition`"). JSON Schema rather than a pydantic model class
because a definition must be portable and describable by a tool the code did not
author — a remotely-described integration cannot hand over a Python class — and
because it is the shape model tool-calling already speaks. Enforcement is
deferred (§7); carrying it is what lets enforcement land without a contract
change.

### 5. `ToolRegistry` — it answers questions, it does not rank

```python
class ToolRegistry(Protocol):
    async def register(self, tool: ToolDefinition) -> None: ...
    async def deregister(self, tool_id: str) -> bool: ...
    async def get(self, tool_id: str) -> ToolDefinition | None: ...
    async def find(self, capability: str) -> list[ToolDefinition]: ...
    async def capabilities(self) -> tuple[str, ...]: ...
    async def all_tools(self) -> list[ToolDefinition]: ...
```

**The registry does not choose.** `find` returns every candidate for a
capability; which one runs is the selection stage's decision, and it needs the
user's policy and the current context — neither of which the registry has. A
registry that returned "the best tool" would be a policy engine wearing a
lookup's name, and the `planning → tool selection` boundary ADR-0014 §2 worked
to preserve would collapse into it from the other side.

Results are ordered by `id`, ascending. Some total order must be specified or
implementations differ observably and the conformance suite cannot assert
anything; `id` order is the one that carries no accidental meaning. Ordering by
risk would be the beginning of ranking, and a caller would come to depend on it.

**Re-registering a different definition under a live id is refused**
(`ToolRegistrationError`); re-registering an identical one is idempotent. Tool
metadata is a security control, so silently overwriting `risk_level=CRITICAL`
with `LOW` under an id a policy already trusts is a privilege escalation with a
lookup's ergonomics — the same audit hazard `PlanStore.save_plan` refuses
(ADR-0014). Rebinding an id is still possible; it just has to be said out loud,
as `deregister` then `register`. `deregister` exists for that and for revoking a
tool, and it is what keeps the refusal from making an id permanently unusable.

`capabilities()` settles ADR-0014's open vocabulary question, and settles it
**against** a closed enum. Capability names stay an open string vocabulary of
which the registry is the authority: it reports what is actually advertised,
sorted and de-duplicated, and that is what a planner should be given to plan
against. A `Capability` enum in `core/types.py` was the tempting alternative and
is the wrong shape — every new integration would become a `core` change and
therefore a breaking change under golden rule 5, which contradicts a subsystem
whose whole design is self-contained plugins, and forecloses a tool this
repository does not ship. A planner naming a capability nothing implements
remains a legitimate, *detectable* outcome, and ADR-0014 already reserved
`SkipReason.NO_CAPABLE_TOOL` for exactly it.

`capabilities()` is derivable from `all_tools()`, and is on the contract anyway
because it is the question the planning stage actually asks; making every caller
re-derive the vocabulary invites each to derive it slightly differently.

**One definition advertises one capability.** An integration that both sends and
reads email registers two definitions, because a single one would have to carry
one `risk_level` for two operations whose risk is nothing alike — and the
conservative merge (the maximum of the two) would make reading email as
gated as sending it, which is how a permission system trains its user to approve
everything.

Methods are `async` to match every other Protocol in `core`: the in-memory
registry this slice ships needs no I/O, but a registry that discovers tools from
a local daemon or a plugin manifest does, and a synchronous contract would have
to break to accommodate one.

### 6. The registry holds configuration, not personal data

Unlike `MemoryStore` (ADR-0007) and `PlanStore` (ADR-0014 §5), this contract
carries **no export/delete obligation**, and that is a deliberate judgement
rather than an omission. A `ToolDefinition` is a declaration made by code — Tier
2 operational configuration under ADR-0004 §1 — not data derived from or about
the user. The registry in this slice is not persistent at all: it is populated at
startup from whatever is registered and rebuilt each run, so there is nothing to
export and nothing that outlives a process to delete.

The Tier 0/1 data in the neighbourhood is real but is not the registry's:
credentials belong to integrations and are reached through ADR-0004 §3's
`SecretStore`, and what a tool *did* belongs to the `permissions` audit trail
(ADR-0004 §7). Should tool enablement later become per-user durable state, that
is a new decision with the data-rights obligations that follow, not a quiet
widening of this one.

`core/errors.py` gains `ToolRegistrationError(ToolError)`, under the existing
`ToolError`.

### 7. Deferred

- **Invocation.** There is no `Tool.invoke` and no result type in this slice.
  Both blocked consumers need the *metadata* and neither needs the call:
  selection ranks declarations, and a permission check rules before anything
  runs. Invocation drags in an error taxonomy, timeouts and cancellation,
  idempotency-key plumbing, and credential access through a `SecretStore` that
  is itself still uncontracted — a larger decision that deserves its own ADR
  rather than a corner of this one.

  Two constraints on that ADR are set **here**, because getting them wrong later
  is not recoverable:

  - **This registry is the only one.** A callable is registered *with* its
    definition, through this contract; invocation must not arrive as a second
    registry sitting beside this one. Two registries keyed by the same id could
    be rebound independently, and the failure that produces is the worst
    available: executing an implementation whose risk declaration is not the one
    the user approved. The binding of a definition to the thing that runs it is
    made once, at registration.
  - **`register`'s parameter type will change**, from `ToolDefinition` to
    whatever pairs it with a call site. That is a breaking Protocol change under
    golden rule 5, and it needs its own ADR — as the invocation decision does
    anyway. An earlier draft of this ADR called invocation "strictly additive",
    which was an overclaim; the query methods are what stay stable, since they
    return `ToolDefinition` either way.

  Declaring the `Tool` Protocol *now*, with a lone `definition` property and no
  method, would make the signature stable at the cost of ratifying a seam with
  no implementation contact — the failure CONTRIBUTING explicitly warns about,
  and one whose shape depends entirely on invocation questions this slice has
  not answered. The naming of the hazard is what matters; paying for it with a
  speculative Protocol is not.
- **Exactly-once execution** (ADR-0014 §7's debt, carried forward). The
  `idempotency` vocabulary lands here; requiring a key on the call, threading it
  through a retry, and holding a tool to its declared window are all invocation's
  to do, and until then the declaration is unexercised.
- **Parameter validation against `parameters_schema`.** The schema is carried
  (§4); validating a `PlanStep`'s parameters against it at selection time needs
  a JSON Schema implementation, which is a runtime dependency decision, and has
  no consumer until invocation exists.
- **Ranking and selection.** Which candidate to prefer among several — and how
  risk, cost and latency trade off — belongs to the selection stage in
  `orchestration`, informed by `permissions`. This ADR supplies the inputs.
- **Tool enablement and per-user configuration.** Whether a user has switched a
  tool off is policy state, not a property of the tool (§6).
- **A persistent registry.** In-memory only, for the reason in §6.
- **Capability namespacing or a published vocabulary.** Names are flat strings
  (§5). If collisions between integrations become real, a namespacing convention
  is additive.
- **Cost of transacted amounts** and the parameter-level spend policy that would
  consume them (§4).

## Consequences

- **The seventh first-vertical artifact exists**, and `permissions` and
  `orchestration` are unblocked — both on metadata, which is what both were
  actually waiting for.
- **Trust becomes a property of a declaration rather than of a list.** A policy
  can be written as "confirm anything at or above `HIGH`, refuse anything
  `IRREVERSIBLE` outside working hours" and it will govern an integration
  written after the policy was, which is the substance of VISION §3.
- **An under-declared tool does not load.** Making every safety field required
  converts the most likely integration bug — forgetting to say what a tool
  touches — from a silent under-protection into a construction error. The cost
  is real boilerplate on every definition, accepted deliberately.
- **A live trap in the obvious code is closed.** `RiskLevel.CRITICAL <
  RiskLevel.LOW` would be `True` under `StrEnum`'s inherited comparison; it is
  now `False`, and comparing a level against a bare string raises instead of
  answering wrongly.
- **`core/types.py` grows behaviour again** — comparison operators on two enums,
  after `FrozenDict` and `ExecutionState`'s properties. The convention is now
  more accurately "no *subsystem* logic" than "no behaviour"; a future ADR may
  want to say so plainly.
- **ADR-0014's capability debt is settled**: the vocabulary is open,
  registry-authoritative, and deliberately not an enum. Its **idempotency debt is
  not** — the guarantee is declarable here and unexercised until invocation, and
  §7 says so rather than letting a field name imply otherwise.
- **Gating is unconditional, so there is no predicate to get wrong.** No field
  or property on `ToolDefinition` exempts an invocation from `permissions/`;
  the type states facts and the policy draws conclusions. The cost is a
  permission round-trip for trivial reads, which ADR-0014 §4 already imposes by
  requiring an `approval_ref` on every claimed step.
- **A tool's off-device disclosure is a declared fact.** `discloses` gives
  ADR-0004 §2 something to police, and its required-ness means a tool that
  quietly transmits Tier 1 data has to say so in order to load.
- **ADR-0004 §2 still reads as forbidding all tool egress**, and this ADR does
  not amend it — it cannot, without inventing the invocation contract. Ratifying
  this changes no egress behaviour because nothing is callable, but the
  contradiction is now recorded rather than latent, and closing it is a
  precondition on the invocation ADR.
- **Every integration ships at least as many definitions as it has operations**
  (§5). Gmail is not one tool. This is more registration code and it is the
  point — per-operation risk is the granularity a permission decision is made at.
- **The registry cannot be the place a bad definition is fixed quickly.**
  Refusing a conflicting re-registration means a wrong `risk_level` in a shipped
  plugin needs an explicit deregister, not a re-import that happens to win. That
  friction is the intended direction for a security control.
- **Nothing can be called yet.** A registry of definitions no executor can
  invoke is an unusual intermediate state, and the risk is that the contract is
  ratified without implementation contact — the failure CONTRIBUTING warns
  about. It is mitigated but not eliminated: the registry contract itself ships
  with a real in-memory implementation and a conformance suite, so the *lookup*
  seam is exercised; the *metadata's* fitness is argued from its two named
  consumers rather than demonstrated by one.
- **`cost` is an estimate nothing reconciles.** A tool whose declared
  `PER_CALL` amount is wrong will mislead a spend policy, and no mechanism
  detects the drift. `UNKNOWN` at least makes *absence* of the information
  visible; a wrong number stays invisible.
- **Declaring a tool is now wordy.** Nine required fields, two of them
  structured, before an integration author writes a line of behaviour. That is
  the deliberate trade of §1, and it will be felt most by the simplest tools —
  a clock reader must still state its cost basis, its idempotency, and three
  empty data-reach tuples.
- **`register` will break when invocation lands** (§7), and it is named here so
  that the change is a planned, ADR-backed one rather than a surprise. What must
  not happen — a second registry binding behaviour to an id independently of the
  declaration that was approved — is foreclosed by decision, not by a type.
- **New `core` surface:** `RiskLevel`, `Reversibility`, `CostBasis`,
  `ToolCost`, `Idempotency`, `ToolDefinition`, the `ToolRegistry` Protocol, and
  `ToolRegistrationError` — eight, against ADR-0014's fifteen, because execution
  state is not being modelled here.
- **Revisit when** invocation lands (does `ToolDefinition` need a timeout, or a
  rate limit? — and ADR-0004 §2 must be amended first), when `permissions`
  writes its first real `ActionPolicy` against
  these fields (the honest test of whether the metadata is the right metadata),
  or if capability-name collisions between integrations become real.
