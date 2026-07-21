# 29. The tool invocation contract

- Status: Proposed
- Date: 2026-07-21
- Decides: what ADR-0016 §7 defers — invocation, its result type and error
  taxonomy, timeouts and cancellation, and idempotency-key plumbing. It honours
  the three constraints ADR-0016 §7 sets on this ADR (§1, §2, §6 below).
- Records for ratification: dated notes on ADR-0016 and ADR-0014, whose exact
  forms are in §9. Neither edit is made by this change, and neither `Status`
  line moves, for the reasons ADR-0026 §6 and §9 give.
- Does **not** designate the `tools/` egress seam. ADR-0017 §3's conditions are
  not discharged here and `tools/` still transmits nothing (§7).

## Context

The request pipeline (`CLAUDE.md`) runs `intent → context assembly → memory
retrieval → planning → tool selection → permission check → execute → learn`.
The left half exists. The right half does not, and the roadmap says why: the
`LearningLoop` shipped in ADR-0022 deliberately omits tool selection, permission
checking and execution, "none of which can be written honestly while
`Tool.invoke` is deferred (ADR-0016 §7)".

Everything that would be *consumed* by an executor has since landed:

- **`ToolDefinition` and `ToolRegistry`** (ADR-0016, corrected by ADR-0018) —
  declared risk, reversibility, tier reach, cost, and an `Idempotency`
  guarantee, queried through a query-only registry that returns detached
  snapshots and spends an id on first use.
- **`ActionRequest`, `PermissionRuling`, `PermissionDecision`, `ActionPolicy`,
  `AuditTrail`** (ADR-0021) — a permission check as a pure ruling on a
  self-contained request, recorded in an append-only Tier 1 trail.
- **`Goal`, `ActionPlan`, `ExecutionState`, `StepTransition`, `PlanStore`**
  (ADR-0014) — a durable claim on a step, committed before the tool runs, that
  carries `bound_tool` and `approval_ref`.

What is missing is the one seam between them. Nothing can be called, so three
ratified mechanisms are inert:

- ADR-0016 §4's `Idempotency` vocabulary "is unexercised" — nothing passes a
  key, nothing threads it through a retry, nothing holds a tool to its window.
  That is ADR-0014 §7's exactly-once debt, carried forward twice.
- ADR-0021 §1's `PermissionDecision.authorises(request)` is "a seam rather than
  a description" — the comparison exists and nobody calls it. ADR-0021 says in
  terms that "#54 stays open until that call exists".
- ADR-0014 §4's `INDETERMINATE` state exists for "a crash between a tool's side
  effect and the commit", and no tool can produce one.

ADR-0016 §7 also names what invocation drags in — "an error taxonomy, timeouts
and cancellation, idempotency-key plumbing, and credential access through a
`SecretStore` that is itself still uncontracted" — and sets three constraints on
this ADR "because getting them wrong later is not recoverable". Each is
discharged below and named where it is discharged: the single registry in §1,
the approval pinned to the definition it ruled on in §2, and ADR-0004 §2's
amendment in §6.

That third constraint is a **precondition, and it has already landed.**
ADR-0017 discharged it ahead of this ADR rather than leaving it here: its §1
replaces ADR-0004 §2's "only component" clause with "`models/` or … a designated
integration seam inside `tools/`", ADR-0004's `Status` line now reads
`Accepted, partially superseded by ADR-0017 (§2's egress clause)`, and a dated
note at the end of ADR-0004 §2 records the same. So this ADR inherits a settled
rule rather than negotiating one — and inherits, unchanged, ADR-0017 §3's
condition list, none of which it discharges (§7).

ADR-0016 §7 warns against one specific mistake, and it is worth quoting because
it constrains the shape of §1: declaring a `Tool` Protocol "with a lone
`definition` property and no method" would be "ratifying a seam with no
implementation contact — the failure CONTRIBUTING explicitly warns about".

This adds a `core` Protocol and `core` types, so it is a substantive contract
ADR (golden rule 5, ADR-0015 §5) and merges as its own PR ahead of any
implementation.

## Decision

We will model invocation as **one method that performs an authorisation it is
handed, against a definition it holds itself** — a `ToolInvoker` Protocol whose
argument cannot be constructed without a matching `ALLOW`, and whose failures
cross the seam as classified data rather than as exceptions.

### 1. One registry, two faces: `ToolInvoker` alongside `ToolRegistry`

```python
class ToolInvoker(Protocol):
    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult: ...
```

One method, taking a value and returning one. It is not the lone-property seam
ADR-0016 §7 refuses, and it is the whole cross-subsystem surface invocation
adds.

**The callable is bound to its definition at registration, inside `tools/`, and
`ToolInvoker` resolves through that same binding.** This is ADR-0016 §7's first
constraint, and the operative form of it is a biconditional:

> An id is invocable **if and only if** it is registered. `all_tools()` and the
> set of ids `invoke` will act on are the same set, always.

Stating it that way is what makes it *checkable* rather than exhorted: the
shared conformance suite requires its subject to present both faces and asserts
the two sets are equal, so an implementation that kept a second table of
callables fails the suite rather than passing review. Two registries keyed by
the same id could be rebound independently, and ADR-0016 §7 names the failure
that produces — "executing an implementation whose risk declaration is not the
one the user approved". The canonical implementation is therefore **one object
implementing both Protocols** over one mapping from id to
`(definition, callable)`.

**What that biconditional does not reach, stated rather than papered over.** It
binds an implementation, not a wiring. A composition root that injected registry
A and invoker B — each internally consistent, each holding an *equal* definition
under the same id — would satisfy both Protocols and both conformance suites
while B ran a callable A never saw. No Protocol can close that, for the reason
ADR-0017 §4 gives about import contracts: this is a net, not a proof. Two things
bound it, and neither is a claim that it is closed:

- **The residue is narrower than it looks.** Any difference in the *declaration*
  fails closed — B refuses, because the definition it holds must equal the one
  the decision approved (below). So the pair must agree on every safety field
  for the mismatch to survive at all, which means ADR-0016 §7's named failure —
  "executing an implementation whose risk declaration is not the one the user
  approved" — does not occur. What remains is a callable that does not do what
  its equal declaration says, and that hazard is **not** created by the split: a
  single registry does not verify a callable against its declaration either.
- **The pairing is an obligation on the composition root** (§8), not a detail it
  may choose. Making it a contract instead would mean one Protocol carrying both
  capabilities, which the next clause rejects; the enforcement
  that would actually close it is ADR-0017 §8's injected capability, deferred
  there and not reopened here.

**Two Protocols rather than one, and the split is a capability distinction, not
tidiness.** Adding `invoke` to `ToolRegistry` would have made "one registry"
maximally literal, and it is wrong for the reason ADR-0016 §5 gave when it kept
mutation off that contract: the surface should not widen to cover a concern its
consumers do not have. `ToolRegistry` answers questions — the selection stage
asks which tools satisfy a capability, and needs no power to run one. Handing
every holder of a lookup the ability to execute is the shape ADR-0017 §8 wants
to move *away* from, and a consumer that only reads is one a test can double
without stubbing execution.

**How the callable is reached is `tools/`-internal, and this ADR does not
contract it.** ADR-0008 set the precedent and ADR-0016 §5 invoked it: a
`ContextProvider` crosses the boundary while the `ContextSource` seam that
populates it stays inside `context/`. Registration is this subsystem's
`ContextSource`. What signature an integration author writes, and whether a tool
is a function, a bound method or a small class, is decided by the implementation
PR — where it will have implementation contact — not blessed here. ADR-0016 §5
predicted exactly this: "When invocation lands it will change how `tools/` is
populated, which is then a `tools/` change and not a breaking one."

**The invoker verifies the definition against its own trusted original.**
`invoke` refuses, with `ToolBindingError`, when `call.request.tool.id` is not
bound, **or** when the definition carried by the call is not equal to the one
the registry holds under that id. `ToolDefinition` is a frozen pydantic model,
so `==` is field-wise and total.

That second check is the one worth arguing for. ADR-0018 §4 recorded a gap it
could not close: a definition "tampered into a still-valid state —
`risk_level` moved from `CRITICAL` to `LOW` — rebuilds successfully … **Under a
fresh id it is accepted, and nothing here detects it.**" ADR-0021 §1 recorded
the same about a policy asked to rule on a tampered copy: "Nothing here detects
the tampering at decision time. What it does mean is that the tampering becomes
*detectable at execution*, against the registry's own definition." This is where
that detection is made mandatory rather than merely possible. The registry is
the only holder of an untampered original, and the seam is the only place all
three values meet.

The chain the seam therefore enforces, end to end:

> **the registry's original ≡ the declaration the policy approved ≡ the
> declaration being executed.**

The first equality is the check above; the second and third are §2's.

**`invoke` does not consult `ActionPolicy`.** It verifies an authorisation it is
handed and never obtains one. Gating is a pipeline stage `orchestration` owns,
and a `CONFIRM` is answered by a human through an interface, on a timescale a
call cannot wait on. A seam that ruled and then executed would be judge and
executioner in one object, and the confirmation round-trip would have nowhere to
happen.

### 2. `ToolCall` — an unauthorised call is unconstructable

```python
class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ActionRequest          # what to do (ADR-0021 §3)
    decision: PermissionDecision    # the authority for doing it (ADR-0021 §1)

    @model_validator(mode="after")
    def _authorised(self) -> ToolCall:
        """Refuse a call the decision does not authorise."""
        # decision.authorises(request) — ALLOW, same tool, same digest, same step

    @property
    def idempotency_key(self) -> str | None: ...   # §5
```

**This is where ADR-0016 §7's second constraint is discharged, and it is
discharged by construction.** That constraint reads: *"The approval record must
pin the definition it ruled on (§5, issue #54), or the same substitution is
possible across a restart."* Issue #54 is closed, and this ADR builds on the
resolution rather than re-deciding it. ADR-0021 §1 resolved the pinning half by
embedding the whole `ToolDefinition` in `PermissionDecision` **by value** — "a
decision does not say 'I approved `send_message`'; it says 'I approved *this
declaration*'" — and commit `95ce080` later made that by-value embedding real
rather than nominal, copying the tool and ruling inside `from_request` after a
review found the decision and the request sharing one object. ADR-0021 §1 then
named what it had left undone: *"The remaining half is one call —
`decision.authorises(request)` against the request the executor is about to
perform — and it belongs to the invocation contract."*

This clause is that call, and it is placed where it cannot be skipped. The
alternative — the executor calls `authorises` before invoking — is a rule an
executor can forget, in a codebase whose ADR-0026 Context documents the same
convention being remembered at one site and missed one file over. Putting it in
a model validator means **no conforming caller can hand a seam a call it was not
authorised to make, because the value does not exist.** A `DENY` or an
unanswered `CONFIRM` cannot construct a `ToolCall`; nor can altered arguments,
a substituted definition, or a different step, since `authorises` compares all
three (ADR-0021 §1).

**Construction is the first line, not the only one: `invoke` re-runs the same
check.** `frozen=True` refuses `call.request = ...` and does nothing about
`call.__dict__["request"] = ...` or `object.__setattr__`, and that bypass is
inside this repository's threat model rather than outside it — ADR-0018 §3 and
§4 closed both the read and write paths of the registry against it, and
ADR-0021 §4 required the audit trail to store a detached snapshot for the same
reason. A validator alone would therefore be the "closes the door and leaves the
window open" position ADR-0018 §3 names: construct a call approving one
recipient, replace `parameters` with a valid frozen mapping naming another, and
a seam checking only the definition would execute the second under the first's
approval.

So the obligation on `invoke` is three checks in one place, before the callable
is reached, **and the order is part of the rule**:

1. the call is **revalidated and detached** — first, as ADR-0018 §4 requires of
   anything a registry stores and ADR-0021 §4 of anything the trail records, so
   a mutation landed after construction cannot survive into execution;
2. the definition on that detached copy matches the registry's original (§1);
3. `decision.authorises(request)` on that same copy — re-evaluated, not trusted
   from construction.

Every subsequent check reads the revalidated copy, never the argument. Ordering
it the other way is not a stylistic preference: a `__dict__` write can leave
`parameters` holding a value `FrozenJson` would never have accepted, and
`authorises` compares `parameters_digest`, which canonicalises that mapping to
JSON. Run before revalidation, it raises a raw serialisation error out of a
method whose contract is that it answers a question — after the executor has
already committed its `→ RUNNING` claim, so the step is left durably `RUNNING`
until recovery, which is the exact outcome §4 spends its length avoiding.
Revalidating first turns that input into a rejection instead.

A failure at any of the three raises `ToolBindingError`, with a revalidation
failure carrying the underlying `ValidationError` as its cause — the shape
ADR-0026 §2 uses when `core` translates an arbitrary fault into its own error.
All three are the same fault: the thing about to run is not the thing that was
authorised. None is a tool failing, so none may be an ordinary `FAILED` result
an executor might retry. The `ToolCall` validator stays because it catches the
honest mistake at the point it is made, with a better message and no I/O; the
seam checks are what hold against a deliberate one.

**Why this may live in `core`.** The validator compares two values it is given.
It does not decide whether an action *should* be allowed — that is
`ActionPolicy`'s, in `permissions/` — and it introduces no new comparison: it
calls a method ADR-0021 §1 already justified under ADR-0016 §2's three-part
test for a semantic intrinsic to a type. Computable from the two values alone;
independent of policy, configuration, context and clock; the same answer for
every consumer. Nothing here changes that.

**`ToolCall` carries no third field, and the absences are the design.** It has
no credential (§6), no timeout (§4 — it is not part of what was authorised), no
idempotency key as data (§5 — it is derived), and no tool id (the definition is
carried by value, so there is no name left to rebind). Anything a caller could
fill in is a field a caller could fill in wrongly.

**What this does not check: that the decision was ever recorded.** `authorises`
compares a decision the caller is holding; a caller that never wrote it to the
`AuditTrail` still gets a `True`. Injecting a trail into the invoker was
considered and rejected for ADR-0021 §3's reason — it would put an audit write
inside `tools/` and make the seam a second recorder, splitting the trail across
two subsystems. The obligation stays where ADR-0021 put it, on the caller that
records, and the gap is **issue #107**, which this ADR narrows but does not
close: ADR-0014 §4 already refuses a `→ RUNNING` transition without an
`approval_ref`, and §8 below adds that the committed `approval_ref` must equal
`call.decision.id`, so a step that ran carries the id of the decision that was
actually verified. What is still unenforced is that the id resolves to a stored
record.

### 3. The result crosses the seam as data; only seam faults are raised

```python
class ToolOutcome(StrEnum):
    SUCCEEDED; FAILED; INDETERMINATE

class ToolFailureKind(StrEnum):
    #                          why                                  retryable
    INVALID_REQUEST   # the arguments were unacceptable to the tool     no
    NOT_AUTHORISED    # the tool's own upstream refused its credential  no
    UNAVAILABLE       # the upstream is unreachable or failing          YES
    RATE_LIMITED      # the upstream throttled us                       YES
    TIMED_OUT         # the deadline passed (§4)                        YES
    CANCELLED         # cancelled before completing (§4)                YES
    REFUSED           # attempted, and the upstream declined it         no
    INTERNAL          # the tool implementation is broken               no

    @property
    def retryable(self) -> bool:
        """Whether a repeat of this same call could plausibly succeed.

        Not whether repeating is *safe* — that is
        ``ToolDefinition.idempotency``'s answer, and §5 requires both.
        Exhaustive over the members above; a member added without a value here
        is a mistake the suite catches.
        """

class ToolFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: ToolFailureKind
    message: str                    # Tier 2 only

    @field_validator("message")
    @classmethod
    def _message_is_present(cls, value: str) -> str:
        """Return ``value`` stripped, or raise if nothing in it renders.

        The ``_has_visible_text`` test ADR-0018 §1 applies to a tool's
        description and ADR-0021 §1 to a ruling's reason.
        """

class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    outcome: ToolOutcome
    output: FrozenJsonValue = None
    failure: ToolFailure | None = None

    @model_validator(mode="after")
    def _outcome_fields_match(self) -> ToolResult:
        """Return ``self``, or raise on a result that half-says two things.

        Raise when ``outcome`` is SUCCEEDED and ``failure`` is set; when it is
        FAILED or INDETERMINATE and ``failure`` is None; and when it is not
        SUCCEEDED and ``output`` is not None.
        """
```

**These blocks are shapes, not implementations**, as every contract ADR in this
repo has written them — ADR-0021 §1 shows `from_request` as a signature and a
docstring — and the implementation PR writes the bodies. What is *normative* is
each rule stated here and in the prose below, and §10 requires a rejection test
for each. Annotations cannot express a cross-field rule and a comment beside a
field does not enforce one, which is why these are drawn as validators at all:
the shape `StepExecution._outcome_fields_match_status` already has for the same
question one layer up.

**The cross-field invariants are validated, not conventional**, because every
one of them has a wrong state that reads as plausible:

- `failure` is **required unless `SUCCEEDED` and forbidden when `SUCCEEDED`**.
  A `FAILED` result with no failure would leave the executor writing
  `StepExecution.error` — required when `FAILED` (ADR-0014 §3) — with nothing to
  write, and a `SUCCEEDED` result carrying one is a contradiction a caller reads
  whichever half it looks at first.
- `output` must be `None` unless `SUCCEEDED`. "Only meaningful when
  `SUCCEEDED`" is not enough: a `FAILED` result carrying a partial output is one
  an executor could record as a step's result, and a partial result stored as a
  whole one is worse than an absent one.
- `ToolFailure.message` must contain visible text, per the `_has_visible_text`
  test below.

This is the shape ADR-0016 §1 used for `idempotency_window` and ADR-0014 §3 for
the outcome fields on `StepExecution`: make the self-contradictory combinations
unrepresentable rather than merely discouraged. §10 requires each rejection in
the suite.

**Failure is returned, not raised, because `INDETERMINATE` cannot be an
exception.** ADR-0014 §4 makes "we do not know whether the effect happened" a
first-class durable state, and an executor that learned about it by catching
something would be one `except Exception:` away from recording a completed
action as failed. Three outcomes, mapping one-to-one onto the three `StepStatus`
members a finished invocation can produce, so the executor's mapping is total
and needs no default branch. A separate enum rather than reusing `StepStatus`
because that type also spells `RUNNING` and `AWAITING_APPROVAL`, which a result
must not be able to say.

**What is raised instead**: `ToolBindingError` (§1) — an id with nothing bound,
or a definition that does not match the registry's. That is a wiring or
substitution fault, not a tool failing, and it must not be representable as an
ordinary `FAILED` step the executor might retry. It is the only error this ADR
adds, under the existing `ToolError`.

**An exception escaping the tool implementation becomes
`INTERNAL`.** Integration authors raise; a seam that let that propagate would
leave the step durably `RUNNING` with nothing recording why. `BaseException`
propagates unchanged — a `CancelledError` or a `KeyboardInterrupt` must not be
swallowed into a result — which is the boundary ADR-0026 §2 drew for
`checked_clock` and is drawn here for the same reason: a guard whose own failure
modes bypass the failure path it specifies is enforcing nothing.

**`retryable` is a property of the kind, declared once in `core`.** Whether *a
repeat of this same call could plausibly succeed* is a fact about the failure:
`UNAVAILABLE`, `RATE_LIMITED` and `TIMED_OUT` are true; `INVALID_REQUEST`,
`NOT_AUTHORISED`, `REFUSED` and `INTERNAL` are false; `CANCELLED` is true
because the cancellation was ours. This copies the shape `core/errors.py`
already ratified for `ModelError.retryable`, and it is intrinsic under
ADR-0016 §2's test — computable from the enum's own declaration, and the same
answer for every consumer.

**`retryable` is not permission to retry, and conflating the two is the
mistake this clause exists to prevent.** It answers *could this succeed*;
`ToolDefinition.idempotency` answers *is repeating it safe*. An executor must
satisfy both, and §5 states the conjunction. A `TIMED_OUT` send on an
`Idempotency.NONE` tool is retryable and unsafe, which is precisely the case
that doubles a charge.

**`message` is operator-facing Tier 2 text and must not carry Tier 0 or Tier 1
data.** ADR-0004 §5 already forbids it in logs, and this string is bound for a
log and for `StepExecution.error`. The rule is stated because an upstream error
body routinely echoes a recipient or a subject line back, and the tool is the
only thing positioned to strip it.

**There is no safety net under this field, and saying there was would be
false.** `core/logging.py` names this exact case as the one its redactor cannot
catch — it redacts by *key*, and its own docstring gives `error=str(exc)`, "where
the provider quoted the user's prompt", as the canonical Tier 1 leak it does not
see. `message` lands under precisely such a key, in a log and in
`StepExecution.error`. So the rule has to hold at the producer, in two halves:

- **An integration authors its message**, mapping the upstream failure to text
  it chose. Copying an upstream error body into it is the leak, not a shortcut
  to one.
- **A message the *seam* generates carries no content it did not author.** The
  `INTERNAL` failure it synthesises from an escaping exception names the
  exception's type and the tool's id; it does not interpolate `str(exc)`, which
  is where a `RuntimeError` quoting a recipient would arrive. The cost is a
  thinner diagnostic for a broken integration, accepted because the alternative
  is a Tier 1 disclosure into a Tier 2 store on the failure path of every tool
  nobody thought about — the same fail-closed direction ADR-0016 §1 took for a
  forgetful author.

`message` must contain visible
text, by the `_has_visible_text` test ADR-0018 §1 applies to a description and
ADR-0021 §1 to a reason, and for the same reason: a failure that renders as
nothing leaves the executor and the user with nothing to say about it.

**`output` is `FrozenJsonValue`**, matching `StepExecution.output` exactly, so a
result is recordable without translation and a tool cannot return a live object
that mutates after the step recorded it. A tool whose return value will not
validate produces a `ValidationError` inside its own frame, which the seam
classifies as `INTERNAL` — the tool is broken, and saying so is more useful than
storing something unserialisable.

**`ToolResult` carries no cost and no disclosure report**, and both omissions
are decisions. Cost: ADR-0021 §6 defers spend accumulation because it "needs
invocation to report what was actually spent", and invocation cannot — billing
is asynchronous, so a `spent` field would hold a number the tool made up, which
is the fiction ADR-0016 §4 refused when it declined to model transacted amounts.
Disclosure: a per-call reach report is issue #57 and is scoped out in §7. Both
are additive fields on this type when their own decisions land, which is why the
type is a model rather than a bare tuple.

### 4. Timeouts and cancellation: the seam owns the deadline

**Every invocation carries a deadline, and enforcing it is cooperative.**
`timeout` is a required keyword-only argument with no default, so the contract
has no spelling for "forever" — but what it buys is that the seam stops waiting,
not that the tool stops working. Python has no way to interrupt a coroutine that
declines to be cancelled, so any stronger claim would be false, and the guarantee
is stated in the weaker form deliberately (the third bullet at the end of this
section is the case it excludes).

A default
would be `core` choosing a policy; `None` would be a documented route to an
unbounded call, which is the shape ADR-0016 §3 refused when it declined a
`requires_permission` predicate that could return `False`.

**The annotation is not the enforcement, so `invoke` checks the value.** Python
does not check a parameter annotation at runtime, and this argument crosses a
Protocol boundary from an untyped or dynamically-wired caller, so `invoke`
raises `ValueError` — before the callable is created or awaited — when `timeout`
is not a `timedelta`, or is not strictly positive. That is ADR-0026 §2's rule
for the clock reading ("the guard is total over the reading, because the
annotation is not") and ADR-0021 §4's for `recent`'s `limit`, which raises on a
non-positive value rather than clamping it, for the concrete reason that the
natural implementation leaks — there, `LIMIT -1` in SQLite becomes no limit at
all; here, `asyncio.timeout(None)` becomes no deadline at all, in the one method
whose contract is that there is always one.

**Strictly positive, and not "expired means do not call".** A zero or negative
duration is refused rather than treated as an instantly-expired deadline,
because expiry is delivered by the event loop at an await point: a callable that
performs a synchronous side effect before its first `await` would already have
acted. Refusing the value never creates the coroutine, which is the only
placement that holds for every tool. Nothing legitimate asks to invoke with no
time to do it in — a caller with no budget left should not call.

**It is the caller's budget, not the tool's property, and `ToolDefinition` does
not gain a timeout field.** This answers one of ADR-0016's own "revisit when
invocation lands" questions directly. `latency` is already declared advisory —
ADR-0016 §4: "it is not a timeout and nothing enforces it" — and a timeout on
the definition would let a tool raise its own ceiling, which is the
self-certifying fast path ADR-0016 §3 and ADR-0021 §5 both refuse. How long a
turn may wait is a property of the turn: an interactive request and a background
one are entitled to different answers about the same tool. `latency` remains
what the selection stage sorts on when choosing whether an action fits a turn.

**The seam enforces it, not the caller.** A caller wrapping `invoke` in
`asyncio.wait_for` cancels the invoker mid-await, so the invoker never reaches
the code that classifies the outcome and the caller sees a bare `CancelledError`
it cannot tell apart from a shutdown. Enforcing inside means the expiry comes
back as a classified `ToolResult`, which is the only form in which
`INDETERMINATE` can be reported at all.

**A deadline expiry on a call that may have acted is `INDETERMINATE`, not
`FAILED`.** The rule, stated so it is checkable:

> On timeout or cancellation, the outcome is `FAILED` when the tool is not
> `side_effecting`, **or** its `idempotency` is `NATURAL`. Otherwise it is
> `INDETERMINATE`.

A read that timed out changed nothing and there is nothing to be ambiguous
about. A `NATURAL` tool is idempotent by nature (ADR-0016 §4), so whether it
acted does not change what a repeat does. Everything else is exactly ADR-0014
§4's case — "a crash between a tool's side effect and the commit … cannot be
distinguished from a crash *before* the effect" — reached through a deadline
rather than through a crash, and it gets the same answer, because guessing in
either direction is the thing that ADR refused. A tool that *can* establish it
did not act may return `FAILED` with `TIMED_OUT`; nothing can make it prove the
converse.

**`TIMED_OUT` means the seam's own deadline expired, and the seam must
establish that rather than infer it from an exception type.** An upstream SDK
raises Python's `TimeoutError` for its own reasons — a connect timeout, a read
timeout it configures itself — often long inside our budget, and an
implementation that classified by catching `TimeoutError` would label it
`TIMED_OUT` and, for a side-effecting tool, escalate it to `INDETERMINATE`: a
call that failed fast and provably did nothing, recorded as one whose effect is
unknown, and therefore excluded from retry. So classification keys on *this*
deadline having expired, which the seam alone knows. Anything else escaping the
callable is an exception like any other and becomes `INTERNAL` (§3).

**A cancellation delivered from outside propagates as `CancelledError` and the
seam does not convert it to a result.** Swallowing it would break structured
concurrency and shutdown, and there is no return path from a task being torn
down. The obligation therefore falls on the executor, and it covers **every**
cancelled invocation rather than only the ambiguous ones — an earlier draft
stated only the `INDETERMINATE` half, which left a cancelled read with no rule
at all and therefore stuck in `RUNNING` until recovery, where it would have been
committed as `INDETERMINATE` in flat contradiction of the classification above.
So: an executor whose invocation is cancelled catches the `CancelledError`,
commits the step by the *same* rule the timeout uses — `FAILED` when the tool is
not `side_effecting` or its `idempotency` is `NATURAL`, `INDETERMINATE`
otherwise — and then **re-raises**. Committing is not swallowing: the write is
the executor's own durable bookkeeping, and the cancellation still propagates,
which is what keeps shutdown working. An executor that returns normally from a
cancellation is the bug this clause is not licensing.

**A `CancelledError` the callable invents is not a cancellation, and the seam
must tell them apart.** Nothing about the exception's type says where it came
from, so a tool raising one before it issues its request would otherwise be read
as an external teardown: the executor would record `INDETERMINATE` for a call
that did nothing, and re-raise — cancelling a request nobody cancelled, on a
tool's say-so. The seam therefore classifies on **whether a cancellation was
actually requested** — of its own deadline, or of the invoking task — rather
than on catching the type. If one was, the rule above applies and the exception
propagates. If none was, the tool raised it spuriously and it is a tool that
raised: `INTERNAL`, like any other escaping exception (§3). This is the same
move §4 makes for `TIMED_OUT` one clause up, and for the same reason — the seam
is the only party that knows the difference, and an exception type is not
evidence of provenance.

The `CANCELLED` failure kind covers the narrower case the seam itself *can*
report — a genuine cancellation it observed and unwound from cleanly before the
tool started work.

**What one event loop means for a hung tool.** `CLAUDE.md` composes the system
on a single loop, so three things follow and are worth stating plainly, because
two of them are limits rather than guarantees.

- **An awaiting tool blocks nothing but its own turn.** The rest of the loop
  continues; the cost of a hang is one stalled request and one step held in
  `RUNNING`, which recovery moves to `INDETERMINATE` at the next startup scan
  (ADR-0014 §4).
- **A blocking call is a contract violation, because it makes the timeout
  unenforceable.** `asyncio.timeout` can only fire at an await point, so an
  integration wrapping a synchronous client must offload it to a worker thread.
  Two consequences follow and both are accepted: a thread cannot be cancelled,
  so a deadline expiry on an offloaded call is `INDETERMINATE` by construction
  under the rule above, and the seam returns while the thread may still be
  running.
- **A tool that suppresses its own cancellation can outlive its deadline, and
  no seam can prevent that.** `asyncio.timeout` does not return until the inner
  frame finishes unwinding, so a `finally` that awaits forever hangs `invoke`
  past the timeout it was given. This is a genuine hole and the honest position
  is that it is unclosable from this side: the mitigation is the first bullet —
  the loop keeps running, and the step is recoverable — not a claim that the
  deadline is a hard bound.

### 5. Idempotency: the key is the authorisation, not a caller's invention

This settles the debt ADR-0014 §7 opened and ADR-0016 §4 carried forward
("requiring a key on the call, threading it through a retry, and holding a tool
to its declared window are all invocation's to do").

**The key is derived, not minted:**

> `ToolCall.idempotency_key` is `decision.id` when the tool's `idempotency` is
> `KEYED`, and `None` otherwise. It is a property, not a field.

The three properties a key needs fall out of that, rather than being obligations
on a caller who might get them wrong:

- **Stable across retries.** Every retry of an authorised call reuses the same
  `ToolCall`, hence the same decision, hence the same key. There is no attempt
  counter in it, deliberately — a key that varied per attempt would defeat the
  guarantee at exactly the moment it is needed.
- **Distinct for a distinct intent.** Asking the system to send the same message
  again produces a new `ActionRequest` and a new decision, so a new key. That is
  correct: a fresh authorisation is a fresh action, not a duplicate of the old
  one.
- **Recoverable across a restart**, which is the property that makes it worth
  anything. ADR-0014 §5 makes plan state durable and ADR-0021 §4 makes the audit
  trail durable, so a restarted executor reads `StepExecution.approval_ref`,
  loads the decision from the trail, and derives the identical key. A key held
  only in memory would be lost by precisely the crash it exists to survive.

A field would have had none of these. It would be a value some caller computed,
two callers could compute differently, and a retry path could forget to carry —
the same argument ADR-0021 §1 made for computing `parameters_digest` on the
request rather than accepting it as a `str`.

The key is passed to the tool as an opaque string. A tool whose upstream
constrains the format maps it, inside the integration, and that mapping must be
deterministic for the same reason: a mapping that is not a function of the key
reintroduces the variance the derivation removed.

**When an executor may retry.** Both halves must hold — this is the conjunction
§3 promised:

1. `result.failure.kind.retryable` is true, **and**
2. repeating is safe, which means: the tool is not `side_effecting`; or its
   `idempotency` is `NATURAL`; or it is `KEYED` **and** the elapsed time since
   the first attempt of this call is strictly less than
   `idempotency_window`.

An `Idempotency.NONE` side-effecting tool is therefore **never** auto-retried,
whatever the failure kind. Neither is an `INDETERMINATE` outcome, which
ADR-0014 §4 already places outside automatic retry and which this does not
relax. Both remain resolvable by asking the user or by reconciling with the
tool, which is the explicit resolution ADR-0014 §4 requires.

**Holding a tool to its window is a two-sided obligation**, and both sides are
in the conformance suites:

- *On the tool*: a `KEYED` tool receiving the same key twice within its declared
  window performs the effect once and returns the first result. A tool whose
  upstream dedupes more narrowly than per-tool — per connection, per session —
  may not declare `KEYED` at all (ADR-0016 §4).
- *On the executor*: it stops retrying once the window has elapsed, because past
  it "the tool is free to act again" (ADR-0016 §4) and the retry stops being a
  retry.

**Measuring that elapsed time needs a clock the system does not have, and this
ADR does not invent one.** ADR-0026 §7 is explicit that `Clock` produces
wall-clock instants and that "measuring an elapsed duration across a DST
transition or an NTP step is a different contract this one does not provide and
should not be stretched to". A window is exactly such a measurement. Rather than
contract a monotonic clock in a tools ADR, the rule is made **fail-closed**:
the executor measures with the injected wall clock, and any reading that is not
a positive elapsed duration — a step backwards, a jump past the window — is
treated as *the window has lapsed*, so the failure mode is a retry not taken.
Declining to retry costs a recoverable error surfaced to the user; retrying
outside a lapsed window costs a duplicated side effect. A monotonic clock seam
is the proper fix and is a follow-up issue, not a blocker: the conservative
reading is correct, only occasionally pessimistic.

**An approval is not consumed by executing it**, and ADR-0021 §4 left this open
in terms — "Making an approval single-*use* needs an atomic consume-on-execution
step, which belongs to the invocation contract". The answer is **no**, and it
is not a deferral. `authorises` is a pure comparison that answers `True` every
time, and that is required for retry to work at all: an approval spent on the
first attempt could not authorise the second, so a transient `UNAVAILABLE` would
force a fresh confirmation prompt for an action the user already approved.
Repetition is bounded by the idempotency key and the retry rule above — by what
the tool will deduplicate and what the executor will re-attempt — not by
destroying the record of what was authorised. An audit trail whose entries are
consumed is not an audit trail.

### 6. Credentials: `SecretStore` is deferred, and invocation may assume nothing

**This ADR does not contract `SecretStore`, and the deferral is stated
precisely, because ADR-0016 §7 is right that ambiguity here is how a credential
seam gets built twice.** What invocation may assume, in full:

> **No credential value crosses this seam, in either direction, ever.** A tool
> that needs one obtains it itself, inside `tools/`. `invoke` takes no
> credential parameter, `ToolCall` has no credential field, `ActionRequest.
> parameters` may not carry a Tier 0 value (ADR-0021 §1), and `ToolResult`
> carries none back.

That is not a gap left open; it is the strongest form of ADR-0017 §3's
requirement, which asks implementations to "bind a reference, fetch the secret
after approval, or the binding and every audit record derived from it become
Tier 0 stores". Here there is no reference to bind, because the credential never
enters the call — the same argument ADR-0021 §1 made for why a digest over
`parameters` is safe.

**Why it is not contracted here.** ADR-0004 §3 already decides that `models/`
and `tools/` read credentials "through a small `SecretStore` Protocol"; the
Protocol does not exist in `core/protocols.py` today. Contracting it in this ADR
would mean guessing the answer to a question that is open and named: ADR-0017 §3
requires **credential access** to be gated, not merely transmission — "reading
the token is what needs gating; otherwise an implementation reads it, then
checks, then stops" — and ADR-0021 §3 defers gating direct Tier 0/1 access
pending issue #74, recording that whether such access is a permission subject at
all is unsettled. A `SecretStore` shaped without that answer would either
smuggle a gating decision into a `get(name) -> str` signature or ratify one that
has to break when #74 lands, which is the shape ADR-0016 §5 calls "a contract
whose author expects it to break".

**Nothing is blocked by the deferral**, and that is checkable rather than
asserted. A tool needing a credential is a tool reaching an external service,
and `tools/` transmits nothing: ADR-0017 §2 leaves the egress seam approved and
**undesignated** until every §3 condition holds in code and a later ADR ratifies
that it does. So the first tool that needs a secret cannot be designated before
`SecretStore` exists in any case, and this ADR's rule — *the seam neither
carries nor sees a credential* — is the one the `SecretStore` ADR will need to
hold to whatever shape it takes.

**And there is no second seam to build.** Credential access is contracted in one
place, by that ADR, in `core/protocols.py`. Invocation must not later grow a
`credentials=` parameter or a `SecretStore` argument on `invoke`; a tool
fetching its own credential from an injected `SecretStore` is a `tools/` wiring
concern, exactly as the callable's shape is (§1). This is recorded as a
constraint on the `SecretStore` ADR in the same way ADR-0016 §7 recorded three
on this one.

### 7. Explicitly out of scope

Scoping something out is a decision, so each carries its reason.

- **Designating the `tools/` egress seam.** Ratifying this ADR authorises no
  byte. ADR-0017 §2 requires a *later* ADR to name the seam module, attest each
  §3 condition and record the transition, and §3's list is inherited here
  unabridged and undischarged — recipient authorisation, transport pinning,
  canonicalisation, multi-recipient sets, attempt identifiers, outbound payload
  classification (#94), and the rest. This contract is a precondition for that
  ADR, not a substitute for it. Saying so loudly is the point: an invocation
  contract reads like permission to call things, and it is not.
- **Per-call data reach and ADR-0004 §7's minimisation rule** — **issue #57**.
  ADR-0016 §3 makes the tier tuples a *ceiling*: the definition never sees the
  arguments, so it cannot report what a call touched. Deriving that needs
  argument-level analysis, and #57's own comments have since sharpened the
  requirement from a digest to an inspectable manifest — "which records, how
  many, at what tiers" — which is a real artifact to design with open questions
  about granularity, its own Tier 1 status, and its interaction with ADR-0004
  §6's deletion rules. That design depends on this contract's shape, which is
  why #57 says it is "blocked on the tool invocation contract" and why it
  follows rather than precedes. The ordering is safe because a ceiling only ever
  narrows: the eventual report is an additive field on `ToolResult` (§3).
- **Parameter validation against `parameters_schema`.** ADR-0016 §4 carries the
  schema and §7 defers enforcement because it "needs a JSON Schema
  implementation, which is a runtime dependency decision". That is still true
  and it is not this ADR's decision to make — adding a dependency is ADR-0003's
  process, and choosing between implementations is a trade-off about vendoring,
  draft support and error reporting that has nothing to do with invocation. Its
  absence is bounded rather than silent: an unacceptable argument reaches the
  tool and comes back as `INVALID_REQUEST` (§3), which is not retryable, so the
  failure is loud and terminal instead of being caught early.
- **Ranking and selection** among candidate tools. ADR-0016 §5 assigns it to the
  selection stage in `orchestration`, "informed by `permissions`", and ADR-0016
  §7 defers it. Nothing here changes that: `invoke` acts on a definition already
  chosen, and a seam that chose would collapse the `planning → tool selection`
  boundary ADR-0014 §2 and ADR-0016 §5 both spend argument defending.
- **Standing grants and spend accumulation** (ADR-0021 §6). Both need durable
  policy state; the second additionally needs a cost report invocation cannot
  honestly produce (§3).
- **Concurrent execution, leases, and parallel steps** (ADR-0014 §7). One
  executor runs at a time. `invoke` makes no concurrency promise beyond being
  `async`, and an implementation is not required to be thread-safe — the same
  position `InMemoryToolRegistry` takes today and for the same reason.
- **A monotonic clock** for window measurement (§5), and **a structured failure
  kind on `StepExecution`** (§8). Both are follow-ups with issues, and both have
  a conservative interim behaviour stated where they are raised.

### 8. What this asks of `planning` and `orchestration`

No rule in ADR-0014 or ADR-0021 changes; ADR-0014 §4's transition table gains a
second trigger, recorded as a note in §9. The rest are obligations on the
executor `orchestration` will write, set down here so that PR inherits them
rather than rediscovering them.

- **The claim precedes the call.** ADR-0014 §4 already requires the
  `→ RUNNING` transition to be committed before the tool is invoked, so the CAS
  in §5 is what stops two workers acting. Unchanged, and now load-bearing for
  the first time.
- **`bound_tool` must equal `call.request.tool.id`**, and the committed
  `approval_ref` must equal `call.decision.id`. Both are ids in a durable
  record whose full values live elsewhere; requiring the equality is what makes
  the durable record a description of the call that actually ran.
- **Result mapping is total**: `SUCCEEDED` → `output` and `finished_at`;
  `FAILED` → `error` and `finished_at`; `INDETERMINATE` → the `RUNNING →
  INDETERMINATE` transition ADR-0014 §4 reserves for recovery, now also reachable
  from a live deadline expiry. That is a widening of *when* that transition
  fires, not of the graph.
- **A raised `ToolBindingError` is committed `RUNNING → FAILED`, and never
  retried.** The claim precedes the call, so a seam rejection arrives *after*
  the step is durably `RUNNING`; letting it propagate uncommitted would strand
  the step until recovery, which would then record `INDETERMINATE` — "we cannot
  tell whether it acted" — about a call that provably never reached the
  callable. That is the one thing `INDETERMINATE` must not be used for, since it
  is the state whose whole meaning is ignorance. `FAILED` is correct and
  honest: nothing happened, and the reason is that the call was not the one
  authorised. It is not retryable under §5, because a retry submits the same
  rejected call and a re-authorisation is a *different* call with a new
  decision. This is the only outcome an executor must derive from an exception
  rather than from a `ToolResult`, which is precisely why it is written down.

  **"Never retried" needs a mechanism, and the mechanism is that the executor
  does not schedule one.** ADR-0014 §4 permits `FAILED → RUNNING` while attempts
  remain, and `StepExecution.error` is an unstructured string, so nothing
  durable distinguishes this `FAILED` from a retryable one — a generic loop that
  re-drove failed steps would resubmit the same rejected call forever. So the
  rule is: **retry is scheduled only from a `ToolResult`, never from an
  exception.** §5's two conjuncts read `result.failure.kind`, and a raised
  `ToolBindingError` produces no result to read, so there is nothing for a retry
  decision to be made from — which is the property to preserve rather than an
  accident to work around. Widening the tracker to reject the transition was the
  alternative and is rejected: it would put a tools-specific failure category
  into ADR-0014's graph, a breaking change to a contract this ADR does not own,
  to encode a rule the executor can simply not violate.
- **Failure kind does not survive a restart, and this ADR does not widen
  `StepExecution` to fix it.** `error` is an unstructured `str`, so after a
  restart an executor can read *that* a step failed but not whether it was
  retryable. Widening it is an ADR-0014 change, breaking under golden rule 5,
  belonging to the planning lane and not worth stacking onto a tools contract.
  The interim behaviour is conservative and correct: retry decisions are made
  in-process from the `ToolResult` in hand, and a `FAILED` step recovered after
  a restart is not auto-retried. Follow-up issue.
- **The invoker is injected**, like every other implementation the engine
  receives (golden rule 1). `orchestration` holds a `ToolRegistry` and a
  `ToolInvoker` and sees only those two contracts.
- **The composition root must inject one object as both**, and this is an
  obligation rather than a convenience. §1 is explicit that no Protocol can
  enforce it and that the residue if it is violated is narrow; it is still the
  one place ADR-0016 §7's first constraint has to be honoured by hand, so it is
  written down where the wiring is done rather than left implicit. A root that
  cannot satisfy it — two registries with genuinely different callables — is
  wiring the shape that ADR says is not recoverable.

### 9. What ratification does to ADR-0016

ADR-0017 §7 requires the operation performed on another ADR to be recorded
rather than inferred, and ADR-0026 §6 sets the form for an ADR that merges as
`Proposed`: the edit is **not** made by this change, because writing "discharged
by ADR-0029" onto ADR-0016 while ADR-0029 is only proposed is the state claim
ADR-0019 forbids. Recorded here in the exact form to apply on ratification:

- **ADR-0016's `Status` line is not touched.** This is the substantive
  difference from ADR-0026 §6 and it is deliberate. ADR-0001 reserves a status
  update to an ADR that *changes a past decision*, and nothing in ADR-0016's
  decision text is withdrawn, reversed or narrowed here. Its §7 is a list of
  things deliberately not decided; a later ADR taking one up is that deferral
  working as designed, not a supersession. ADR-0018 changed ADR-0016's rules and
  earned a status line; this does not.
- **A dated note is appended to ADR-0016's header, after the
  `Partially superseded` block:**

  `Note (<ratification date>): §7's **invocation** deferral is discharged by
  ADR-0029, which honours the three constraints §7 sets on it — one registry
  (ADR-0029 §1), the approval pinned to the definition it ruled on (ADR-0029 §2,
  building on ADR-0021 §1's resolution of #54), and ADR-0004 §2's amendment,
  which ADR-0017 discharged ahead of it. §7's **exactly-once** debt is
  discharged with it (ADR-0029 §5). §7's remaining deferrals — per-call data
  reach (#57), parameter-schema validation, ranking and selection, persistence,
  enablement, namespacing, transacted cost — are unaffected and remain deferred.
  ADR-0016's decision text is unchanged: the registry stays query-only, ids stay
  spent on first use, `latency` stays advisory and `ToolDefinition` gains no
  timeout field (ADR-0029 §4).`

- **Nothing else in ADR-0016 is edited.**

**ADR-0014 §4 gains a note too, and the reason is worth being exact about.**
§8's result mapping makes `RUNNING → INDETERMINATE` reachable from a live
deadline expiry, where ADR-0014 §4's table names one trigger: "recovery found it
running after a crash". No legal move is added or removed — `PlanExecution`
validates the move and not the trigger, so an implementation built from that
table needs no change — but the table's trigger column is prose a reader relies
on, and leaving it naming only crash recovery would make the document wrong
about when the state occurs. Recording it is cheap and ADR-0019's lesson is that
an unrecorded widening is the kind that goes unnoticed. So:

- **ADR-0014's `Status` line is not touched**, for §9's reason above: ADR-0001
  reserves a status update to an ADR that *changes* a past decision, and
  ADR-0014's decision — that a step which may or may not have acted becomes a
  durable `INDETERMINATE`, never auto-retried, resolved explicitly — is not
  changed, narrowed or reversed. It is applied to a second circumstance that
  meets its own stated test.
- **A dated note is appended to ADR-0014's header, after `Date`:**

  `Note (<ratification date>): §4's RUNNING → INDETERMINATE transition has a
  second trigger from ADR-0029 §4 — a tool that exceeds its invocation deadline,
  or is cancelled, while side_effecting and not NATURAL. §4's rule is unchanged
  and is what selects it: such a call cannot be distinguished from one that did
  not act. The transition graph, the retry ceiling, and INDETERMINATE's
  never-auto-retried, resolved-explicitly treatment all stand as ratified. §7's
  idempotency-key debt is discharged by ADR-0029 §5; its INDETERMINATE
  reconciliation deferral is not.`

- **No other ADR is edited.** ADR-0021 §1 and §4 name questions this ADR answers
  — where `authorises` is called, and whether an approval is single-use — but
  answering a question an ADR explicitly left to a successor changes none of its
  text and widens none of its statements, so it gets no note; the same holds for
  ADR-0017 §3's condition list, which is inherited undischarged (§7). The line
  between the two cases is whether a sentence in the other ADR would now read as
  false: ADR-0014 §4's trigger column would, and nothing in ADR-0021 or ADR-0017
  does. Noting every ADR that was merely *read* would make the header of each
  one a changelog of everything downstream.

### 10. The implementation PR owes a triad, and what it must prove

`ToolInvoker` is a new `core` Protocol, so `CONTRIBUTING.md` → "Adding a
Protocol" applies without exemption: **Protocol + shared conformance suite +
canonical fake in `ai_assistant.testing`, plus the `Test…Contract` subclass that
runs the suite against the fake**, all in the implementation PR, enforced by
`tests/core/test_protocol_triad.py`. None of it is built here (ADR-0015 §5).

ADR-0018 is the reason this section exists. ADR-0016 ratified a contract argued
from consumers rather than demonstrated by one, and first use found five things
wrong. Its lesson was "spike harder before ratifying", and ADR-0021 took it —
its shape "was spiked against a throwaway implementation before ratification and
discarded". The same is expected here, and the spike is what would settle,
before ratification rather than after, whether a model validator can call
`authorises` at `ToolCall` construction without an import cycle, and whether the
timeout classification in §4 can be written such that the tool's own
`CancelledError` and the seam's expiry are distinguishable.

Beyond the ordinary field-level obligations, the suite must pin the claims this
ADR makes that are not visible in a signature:

- **The biconditional in §1** — the invocable set and `all_tools()` agree — and
  both refusals: an unbound id, and a definition tampered into a still-valid
  state that does not equal the registry's original. The second is ADR-0018 §4's
  named gap and this is where it closes.
- **An unauthorised `ToolCall` is unconstructable** — a `DENY`, an unanswered
  `CONFIRM`, altered parameters, a substituted definition, and a mismatched
  `step_id` each refused at construction.
- **And unauthorised again at the seam** (§2): a call mutated through
  `__dict__` *after* passing construction — parameters swapped for a different
  valid payload, the decision replaced, the definition substituted — refused by
  `invoke` with the tool never reached. This is the check that survives the
  bypass `frozen=True` does not cover, so testing only the construction case
  would certify the door and not the window.
- **And the durable state after that rejection** (§8): a claimed step whose
  `invoke` raised `ToolBindingError` ends `FAILED`, not left `RUNNING` and not
  `INDETERMINATE`. Asserting only that the tool was never reached would leave
  the stranding this rule exists to prevent untested — and the step must also be
  shown *not* to be re-driven, since `FAILED` alone is a status ADR-0014 §4 lets
  a retry leave.
- **And the order of those checks**, which only a malformed mutation
  distinguishes: `parameters` replaced with a mapping `FrozenJson` would have
  rejected must come back as `ToolBindingError` carrying the `ValidationError`
  as its cause — not as a raw serialisation error from the digest. A suite that
  mutates only into *valid* states passes under either order and proves nothing
  about it.
- **The timeout rule in §4 in both directions**: a `side_effecting`,
  non-`NATURAL` tool that exceeds its deadline yields `INDETERMINATE`; a
  read-only or `NATURAL` one yields `FAILED`. And that a `timeout` which is
  zero, negative, or not a `timedelta` at all raises before the tool's coroutine
  is created.
- **The cooperative limit, deterministically** (§4): a fake whose `finally`
  suppresses the injected cancellation and awaits an event the test controls
  must be shown to keep `invoke` waiting past its deadline, and the test then
  releases it. Pinning the *limit* is what stops an implementation quietly
  acquiring a watchdog, or a later reader assuming the deadline is hard; a suite
  that only exercises a cooperative tool would leave both open.
- **A tool that raises becomes `INTERNAL`**, while a `BaseException` propagates.
  Two variants, because an implementation can pass the plain case and leak both:
  a tool returning a value `FrozenJsonValue` rejects — a `set`, a `NaN` — must
  come back as `INTERNAL` rather than as an escaping `ValidationError`; and a
  tool raising Python's own `TimeoutError` well inside its deadline must come
  back as `INTERNAL`, not `TIMED_OUT`. And in the first case the exception's own
  text — a fake raising `RuntimeError("recipient alice@example.com rejected")` —
  must appear neither in `failure.message` nor in anything the seam logs (§3).
  Nothing downstream redacts it, so an untested rule here is an unenforced one.
- **`retryable` for every member of `ToolFailureKind`**, asserted exhaustively
  rather than sampled, so a member added later cannot default silently.
- **External cancellation classified on both branches** (§4): a cancelled
  read-only or `NATURAL` call committed `FAILED`, a cancelled side-effecting
  non-`NATURAL` one committed `INDETERMINATE`, and the `CancelledError`
  re-raised in both. Paired with its opposite: a fake that raises
  `CancelledError` with nothing cancelled must come back as an `INTERNAL`
  result, with no cancellation propagated and no `INDETERMINATE` recorded. The
  two tests together are what pin the classification to provenance rather than
  to the exception type.
- **The key derivation in §5**: identical across retries of one call, different
  across two decisions about identical parameters, and reproducible from
  `approval_ref` alone after a simulated restart.
- **Both sides of the window**: a `KEYED` fake deduplicating a repeat inside its
  window and acting again outside it; and an executor declining to retry when
  the clock reading is not a positive elapsed duration.
- **`ToolResult`'s invariants, as rejections** (§3): a non-`SUCCEEDED` result
  with no `failure`, a `SUCCEEDED` result carrying one, a non-`SUCCEEDED` result
  carrying an `output`, and a `ToolFailure` whose `message` renders as nothing.
  Each is a state the annotations alone permit.
- **`ToolResult` round-trips** `model_dump(mode="json")` unchanged, since
  `output` lands in a durable `StepExecution`.

## Consequences

- **The right half of the pipeline becomes writable.** Tool selection,
  permission checking and execution were omitted from ADR-0022's `LearningLoop`
  because they could not be written honestly without this. They can now, and
  that is the point of the ADR.
- **New `core` surface:** the `ToolInvoker` Protocol, `ToolCall`, `ToolResult`,
  `ToolFailure`, `ToolOutcome`, `ToolFailureKind`, and `ToolBindingError` in
  `core/errors.py` — seven, and **one triad** in the implementation PR (§10).
- **An unauthorised invocation is refused twice, and neither refusal is the
  executor remembering to check.** ADR-0021 built `authorises` and named the one
  call missing; this puts it in a `ToolCall` validator *and* at the seam, since
  `frozen=True` does not survive a `__dict__` write and a construction-time
  check alone would be ADR-0018 §3's door-closed-window-open. The cost is a type
  with a failure mode at construction and a second comparison per call — the
  same costs ADR-0021 §4 accepted for a trail that validates, and ADR-0026 §2
  for a clock that is checked per reading.
- **#54 closes in full.** ADR-0021 §1 closed the permissions half by embedding
  the declaration by value and said the remaining half was "one call … it
  belongs to the invocation contract". §2 is that call, and §1's registry check
  adds the third comparison neither ADR could make alone — against the untampered
  original — which also closes ADR-0018 §4's tampered-but-valid definition at
  execution, exactly where ADR-0021 §1 predicted it would become detectable.
- **ADR-0014's exactly-once debt is discharged as far as it honestly can be.**
  A key is required, derived rather than minted, threaded through retries, and
  recoverable across a restart from durable state alone. What is *not* claimed:
  exactly-once for an `Idempotency.NONE` side-effecting tool, which remains
  at-most-once with an `INDETERMINATE` state and explicit resolution — ADR-0014
  §4's position, unchanged, because no contract can give a tool a guarantee its
  upstream does not offer.
- **The single-binding rule binds an implementation, not a wiring** (§1). A
  composition root that injects two objects holding *equal* declarations under
  one id satisfies both Protocols and both suites, and no Protocol can prevent
  it — the same "a net, not a proof" limit ADR-0017 §4 accepts for import
  contracts, and closable only by ADR-0017 §8's deferred injected capability.
  The residue is a callable that does not match its own declaration, which one
  registry does not verify either; every *declaration* mismatch still fails
  closed. §8 makes the pairing an obligation on the root rather than an
  assumption.
- **Every call has a deadline and no call has a hard bound.** §4 removes the
  unbounded call from the contract and is candid that a tool suppressing
  cancellation can outlive its timeout. The system survives it — one stalled
  turn, one step recoverable to `INDETERMINATE` — but "timeout" here means the
  seam stops waiting, not that the tool stops working.
- **Deadline expiry becomes a live source of `INDETERMINATE`.** ADR-0014 §4
  reserved that state for crash recovery; it is now reachable in a running
  process, on a path a user is present for. Since `INDETERMINATE` is never
  auto-retried and "must be resolved explicitly", a timed-out send will need a
  human answer more often than a crash ever did — the safe direction, and real
  friction. Automated reconciliation is ADR-0014 §7's deferral and stays there.
- **A retryable failure is not a retryable call.** The conjunction in §5 is the
  clause most likely to be misread by an implementation reading only §3, which
  is why `retryable` is documented on the kind as "could this succeed" and never
  as "may I repeat it".
- **`tools/` registration changes shape, and existing callers break.**
  `InMemoryToolRegistry(tools=...)` and `register(tool)` take a definition alone
  today; §1's biconditional requires a callable alongside it. ADR-0016 §5
  predicted this precisely — "a `tools/` change and not a breaking one", since
  the ratified query surface does not move — but it is still a diff across every
  construction site in `tests/` and every future composition root, and the
  implementation PR should expect it.
- **`SecretStore` stays uncontracted and invocation is closed against it.** No
  credential crosses the seam in either direction, which is stronger than
  ADR-0017 §3 asks for and is what makes the deferral safe rather than
  ambiguous. The cost is that no credentialed tool can be built until the
  `SecretStore` ADR lands — which was already true, because the egress seam is
  undesignated.
- **Ratifying this authorises no egress.** ADR-0017 §3's conditions are
  inherited whole and none is discharged here, so `tools/` transmits nothing and
  the first integration needs its own ADR. The risk this ADR carries is that its
  name suggests otherwise, which is why §7 leads with it.
- **A second unusual intermediate state.** ADR-0016 shipped a registry nothing
  could call and drew ADR-0018's five corrections; ADR-0021 shipped a policy
  ruling on actions nothing could perform. This ships a seam with no tool behind
  it — every conforming implementation on day one will be a fake. The mitigation
  is §10's spike-before-ratification, taken from ADR-0018's stated lesson, and it
  is a mitigation rather than a cure.
- **Revisit when** the first real integration lands (does `ToolResult` need the
  disclosure report #57 designs, and does `invoke` need a resolved destination
  for ADR-0017 §3's recipient authorisation?), when standing grants make
  `authorised_by` live, or when concurrent execution makes the single-executor
  assumption in §7 false.

### The strongest case against this decision

It decides a great deal with nothing behind it. Eight new `core` names, a
validator that runs on every call, a retry algebra with two conjuncts and a
clock caveat, and a timeout classification rule — all of it argued from three
ratified ADRs and no line of executing code. ADR-0018 exists because that
happened once already in this exact lane, and its verdict was that ADR-0016 "was
argued from two named consumers rather than demonstrated by one". By that
standard this ADR is more exposed, not less: ADR-0016 at least had `permissions`
and `orchestration` waiting with concrete questions, whereas the only consumer
of `invoke` today is an executor nobody has written.

The answer is partial, and it is the ordering rule rather than a claim of
confidence. Golden rule 5 requires the contract to be ratified and merged before
anything implements against it, so "write the executor first" is not an option
on the table; the choice is between deciding these questions now and deciding
them inside an implementation PR where they would not get architecture review.
And leaving them undecided has a measured cost: ADR-0017, ADR-0018, ADR-0021 and
ADR-0022 have each had to write a paragraph about what they could not do until
invocation existed — ADR-0022 going as far as omitting three pipeline stages
from the engine it shipped. What this
ADR can do about the exposure is name it (§10), require the spike ADR-0021 ran
and ADR-0018 asked for, and expect its own ADR-0018 to follow. Being the second
contract in this lane to be corrected by first use would be a better outcome
than being the second to defer.
