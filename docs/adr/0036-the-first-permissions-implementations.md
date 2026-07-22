# 36. The first `permissions` implementations: a rule table and a durable trail

- Status: Accepted
- Date: 2026-07-22
- **Not a contract change.** `ActionPolicy` and `AuditTrail` are ratified by
  ADR-0021 and unchanged here; no Protocol moves and no `core` type or
  `Settings` field is touched. Golden rule 5's separate-PR requirement therefore
  does not apply, and this ADR merges with the implementation it authorises.
- **No ratified text changes here.** Everything below chooses among options
  ADR-0021 left open to implementations; where it settled something, this
  follows it.

## Context

`permissions/` shipped as a docstring. ADR-0021 ratified both of its contracts
and their conformance suites, and `ai_assistant.testing` holds a canonical fake
for each — but no production object in `src/` outside `core/types.py` had ever
constructed a `PermissionDecision`.

That stopped being theoretical when the tool executor landed (ADR-0029,
ADR-0034): an invocation now requires an authorised `ToolCall` carrying a
`PermissionDecision`, so the pipeline stage immediately upstream of the one that
exists is the one that does not.

Implementing a ratified contract is usually not an ADR's business. Two things
here are, because the contract deliberately declines to settle them:

- **ADR-0021 §5 fixes a shape, not a threshold.** "Confirm at or above `MEDIUM`"
  is *"a setting, not a decision this ADR gets to make"*. Whoever writes the
  first policy is choosing how rules are represented, and — more consequentially
  — choosing whether the conformance obligations hold because the code is
  careful or because the structure cannot express a violation.
- **ADR-0021 §4 says implementations "persist locally only" and never says
  whether they persist at all.** That clause is about *residency* — nothing goes
  to a remote service. It leaves the durability question to the implementation,
  and the two answers produce stores that pass the same suite and mean different
  things.

A third question is smaller and still worth recording: the thresholds are the
user's, and this project reads user configuration through `core.config.Settings`
(CONTRIBUTING). There are no permission settings, and adding some was outside
this change's fence.

## Decision

We will ship two implementations: `ThresholdActionPolicy`, a **rule table** whose
conformance is structural, and `SqliteAuditTrail`, a **durable** trail on the
local-first precedent `memory/` set.

### 1. The policy is a table of monotone clauses combined by maximum

`ThresholdActionPolicy` evaluates an ordered table of independent clauses. Each
clause reads exactly one declared field, fires as a step function of it, and
carries the outcome it argues for and the reason it will show the user. The
ruling is the **most restrictive** outcome any clause reached, with the reasons
of every clause that reached it.

```text
non-empty discloses      -> CONFIRM   (floor, not configurable)
UNKNOWN cost             -> CONFIRM   (floor, not configurable)
risk >= confirm_at_risk           -> CONFIRM
reversibility >= confirm_at_reversibility -> CONFIRM
risk >= deny_at_risk              -> DENY
reversibility >= deny_at_reversibility    -> DENY
nothing fires            -> ALLOW
```

**This shape is chosen because it makes ADR-0021 §5's central obligation
structural rather than careful.** A step function of one field is monotone in
that field and constant in the others; the pointwise maximum of monotone
functions is monotone. So *every* setting of the four thresholds yields a
monotone policy, and the property survives adding a clause as long as the clause
is a threshold or a non-emptiness test. The alternative — an `if`/`elif` chain
computing an outcome directly — is how the `RiskLevel.CRITICAL < RiskLevel.LOW`
inversion ADR-0016 §2 disarmed on the type gets reproduced in a subsystem's own
arithmetic, and it would leave the conformance suite as the only thing standing
between a refactor and an inverted gate.

**The two floors are module-level constants that no constructor argument
reaches.** A threshold is the user's; a floor is the contract's. Implementing
the floors as thresholds with a conservative default would have been smaller and
wrong: `confirm_on_disclosure=False` is then one keyword away, and ADR-0021 §5's
"off-device disclosure is never auto-granted" becomes advice. The test suite
runs the policy through the shared conformance suite at four configurations
including "every threshold disabled", which is the arrangement where a floor
implemented as a knob would visibly disappear.

**Rejected: user-supplied rules.** Letting a caller pass its own clause objects
or predicates is the obvious extension and it hands away the guarantee above —
an injected non-monotone predicate produces a non-conforming policy out of a
conforming class. The configuration surface is four ordered scalars precisely
because every value of them is safe. Something richer needs the standing-grant
policy store ADR-0021 §6 defers, which will have its own ADR.

**Rejected: clauses keyed on `reads`, `writes`, `side_effecting`, or a
`PER_CALL` price.** All four are readable and none has a rule to be part of yet.
ADR-0021 §5 states monotonicity over risk, reversibility and disclosure, and the
shared suite's cross-product spans exactly those plus cost — a clause keyed
outside that set would be unexercised by the contract, which is where a
monotonicity inversion could hide. Spend accumulation is deferred by ADR-0021
§6 for a reason this cannot pre-empt: `cost` is an estimate nothing reconciles.

**`resolve` re-reads the rules against the recorded declaration.** ADR-0021 §3
permits a policy to refuse a confirmation "whose request would now be `DENY`",
and the recorded `CONFIRM` embeds the whole `ToolDefinition` it was made about
(ADR-0021 §1) — which is all any clause reads. So an approval is checked against
the rules as they now stand, and does not resurrect an action the policy has
since come to refuse outright. A `CONFIRM`-today declaration still resolves to
`ALLOW`: only a `DENY` withdraws consent, because anything weaker would make the
prompt's own outcome a reason to ignore its answer.

**Rejected: a confirmation TTL.** "Answered long after it was asked" is the other
staleness ADR-0021 §3 mentions, and it needs a clock. ADR-0021 §3 removed the
clock from the policy deliberately — it is what leaves `decide` a genuine
function of its argument and the monotonicity obligations checkable at all — and
smuggling one back in through `resolve` would trade that for a rule better
placed where the prompt's lifetime is actually managed. A confirmation that has
gone stale should not be answerable; that is `orchestration`'s to enforce, not
something the policy can observe.

**The thresholds are constructor arguments, not `Settings` fields.** They are the
user's configuration and belong in `Settings` eventually; adding fields to
`core/config.py` was outside this change's fence, and a policy that read global
configuration itself would stop being the injectable, deterministic object the
conformance suite relies on. The composition root passes them in. Wiring
`Settings` to that call is follow-on work, tracked as an issue.

### 2. The audit trail persists

`SqliteAuditTrail` writes to a local SQLite file — `:memory:` by default so a
test or a throwaway composition needs no filesystem, a path in a real
deployment. One table: the decision's JSON dump, plus an id, an ordering key and
the `resolves` pointer as columns SQLite can constrain and sort by.

**Why not an in-process trail, which the Protocol would have accepted.** Two
ratified decisions are about records that outlive the process, and a volatile
store satisfies neither while passing every test in the suite:

- ADR-0004 §7 makes the trail the thing that renders the assistant's behaviour
  "transparent and reviewable". A trail emptied by every restart cannot answer
  "what did the assistant do", which is the only question it has.
- ADR-0021 §1 embeds the entire `ToolDefinition` in each decision *specifically*
  so the record still says what was approved after a restart has rebuilt the
  registry and possibly rebound the id (issue #54). That argument is written
  about the restart, and it evaluates to nothing in a store the restart empties.
  ADR-0021 §4 says as much from the other side: *"durability is what forces §1's
  records to be serialisable"*.

The volatile slot is also already occupied. `FakeAuditTrail` in
`ai_assistant.testing` is a dict-backed trail held to the same suite, so a second
in-process implementation in `permissions/` would be a duplicate with a worse
import path — the shape `InMemoryPlanStore` has only because `planning` has no
durable backend yet.

**The stored form is the JSON dump, and reads rebuild from it.** ADR-0021 §4 asks
for a detached, validated snapshot on the write path and a detached snapshot on
every read. Serialising gives both at once, with no copy step to get wrong and
no recursion depth to keep abreast of the type: nothing in the store shares an
object with the caller in either direction, and `PermissionDecision.model_validate`
— not `type(decision)` — is what comes back, so a caller's subclass overriding
`model_copy` cannot become the object the trail hands out. The round-trip is not
a risk this takes: ADR-0021 §4 already requires the type to survive it, and the
shared suite asserts it.

A record that no longer validates on the way *out* raises `AuditError` rather
than reading as absent. A tampered or downgraded row returned as `None` would be
indistinguishable from a decision that was never made, which is the ambiguity the
trail exists to remove.

**The ordering key is integer microseconds, not a float epoch second.** ADR-0021
§4 makes ordering by `decided_at` part of the contract, and the natural
implementation — `datetime.timestamp()` into a `REAL` column — carries a
present-day instant with microsecond precision in sixteen significant digits,
which is at the edge of a double. Two decisions a microsecond apart can then
compare equal or invert. The key is computed from a `timedelta`'s integer
components instead, which is exact, and it is a key over *instants* because
`decided_at` is a `UtcInstant` already normalised by `core` — which is what makes
the DST repeated hour in the shared suite sort by when things happened rather
than by what the wall clock said.

**A unique index on `resolves` backs the single-resolution check.** ADR-0021 §4
requires that one `CONFIRM` be answered once, and `record` checks it. The index
is the same rule stated where a bug in the check cannot reach it; SQLite treats
NULLs as distinct, so it constrains resolving rows only.

**Atomicity is the `asyncio.Lock`, and the transaction is `BEGIN IMMEDIATE`.**
The lock serialises `record` within the process, and the duplicate check, the
resolution validation and the insert run in one `to_thread` call, so there is no
interleaving point between them — the same argument the canonical fake makes,
transposed. The transaction is opened immediate rather than deferred because the
checks are *reads*: sqlite3 would otherwise begin only at the `INSERT`, leaving
them outside the write lock and a second process free to observe the same
unresolved `CONFIRM`. Single-user local-first (ADR-0002) makes that unlikely
rather than impossible, and the cost of closing it is one statement.

**`clear()` counts from the delete, not from a count in front of it.** The same
reasoning one level down: a `SELECT COUNT(*)` is read before SQLite opens the
write transaction, so a row another instance on the same file appended in
between would be erased and not reported, and the lock is per instance. One
statement makes "the number removed" exact by construction rather than by
transaction discipline.

The file is created owner-only, the precedent `SqliteMemoryStore` set for a
Tier 1 store on disk (ADR-0004). Its rollback journal holds the same Tier 1
pages, and inherits the mode because SQLite gives a journal the mode of the
database it belongs to and the chmod runs before any write — asserted rather
than assumed, since it is a property of another project's file layer.

### 3. What this does not do

- **It does not force a decision to be recorded** (issue #107). ADR-0021 §3
  accepts that cost and names the executor as where it closes. Nothing here
  changes it; what changes is that both halves now exist to be joined.
- **It adds no retention rule** (issue #108). ADR-0021 §4 defers it, `clear()`
  is the only erasure, and a durable trail is what makes the question start
  accumulating an answer.
- **It records that a human answered, not which human** (issue #113). `resolve`
  takes a boolean, as the ratified Protocol does.
- **It gates tool invocation only.** Direct Tier 0/1 data access waits on issue
  #74 and arrives as a second Protocol, not by widening this one (ADR-0021 §3).

## Consequences

- **`permissions` has an implementation, and the pipeline's permission stage is
  buildable.** `orchestration` can now be wired end to end: rule, record,
  authorise, invoke.
- **Policy conformance survives configuration.** Any setting of the four
  thresholds yields a monotone policy and neither floor can be configured away,
  which is asserted by running four different configurations — including both
  extremes and a `deny` threshold inverted below its `confirm` — through the
  shared suite. That is a stronger claim than "the default configuration
  conforms", and it is the claim a user-facing knob needs.
- **A `deny` threshold below its `confirm` threshold is accepted, not rejected.**
  The combination is still a maximum, so the result denies where it would
  otherwise have asked — strictly safer. Refusing it would be the implementation
  deciding how cautious its user is allowed to be.
- **The trail outlives the process, so issue #108 stops being hypothetical.**
  An unbounded Tier 1 store that records every gated action now actually
  accumulates. Nothing is blocked, and the question should be settled before the
  trail holds a meaningful amount of history — which is what #108 already says.
- **The trail can refuse a read.** A row that no longer validates raises rather
  than reading as absent, so a caller handling a corrupted store needs a handler
  it did not need against a dict.
- **`record` is a threaded, locked write.** Callers get the atomicity ADR-0021 §4
  requires without arranging anything, and pay a thread hop per decision. That
  is the same trade `SqliteMemoryStore` makes and is invisible at the rate a
  permission gate runs.
- **Permission thresholds are not yet in `Settings`,** so a deployment
  configures them where it constructs the policy. Follow-on work, and a
  deliberate scope cut rather than an oversight: `core/config.py` is a shared
  surface and this change's fence excluded it.
- **Revisit when** standing grants land (§1's rejected "user-supplied rules"
  becomes a real store with its own ADR), when retention is settled (#108), or
  when approver identity arrives (#113) and `resolve` grows a parameter.
