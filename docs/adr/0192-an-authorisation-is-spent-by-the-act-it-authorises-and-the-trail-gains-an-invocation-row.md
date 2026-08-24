# 192. An authorisation is spent by the act it authorises, and the trail gains an invocation row

- Status: Proposed
- Date: 2026-08-24
- Partially supersedes: ADR-0029 — §5's closing paragraph, "An approval is not
  consumed by executing it", and §3's sentence "`ToolResult` carries no cost and no
  disclosure report" as it reaches cost; §1 and §5 below state each scope and what
  of §§3 and 5 stands. ADR-0021 — §4's paragraph "It bounds resolutions, not
  executions, and the difference is worth being precise about"; §2 below states the
  scope and what of §4 stands. ADR-0148 — §9's third clause, as it reaches **where**
  an attempt's outcome is recorded and not **which four** outcomes there are; §7
  below states the scope and what of §9 stands.
- **Decides `core/protocols.py` and `core/types.py` surface, and it is a breaking
  change.** Golden rule 5 asks that it be flagged. It adds one Protocol —
  `InvocationLedger` — so the implementing lane owes a **triad**: contract, shared
  conformance suite and canonical fake in `ai_assistant.testing`, in one change and
  never deferred (`CONTRIBUTING.md` → "Adding a Protocol"). It also grows two
  existing Protocols: `AuditTrail` gains two read members and `AssistantEngine`
  two, so every structural implementation of each must grow them or stop satisfying
  it. `ToolInvoker.invoke` gains an obligation and a collaborator, `ToolResult`
  gains a field, `core/types.py` gains two models and `core/errors.py` three error
  classes. Because the promoted surface's method set changes, the implementing lane
  also **bumps `PROTOCOL_VERSION` in the same change** (ADR-0124 §9; §9 below).
  ADR-0015 §5 and golden rule 5 put it in its own PR, ratified before
  anything implements against it.
- **Required review set: adversarial *and* architecture.** Compelled rather than
  declared: `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a
  change contract-surface when it is the ADR deciding that surface, and the bullet
  above says which surface.
- **Answers #1503**, which the milestone-24 exit ruling left standing as "a future
  contract ADR on its own trigger". Milestone 25 is that trigger (#1544): a spend
  ceiling has nothing truthful to decrement without a record of what executed.

## Context

`AuditTrail` records `PermissionDecision`s and nothing else. ADR-0021 §4 says in
terms what that leaves out:

```text
It bounds resolutions, not executions, and the difference is worth being
precise about. `authorises()` is a pure comparison, so the same resolved
`ALLOW` answers `True` every time it is asked — one approval can therefore back
repeated invocations of the identical request.
```

#1503 read that against milestone 24's exit wording — "every read of a source and
every egress is reconstructible from the audit trail alone" — and the owner ruled
the wording as "every egress **decision**", recording that the consume-on-execution
step and an invocation record remain a standing debt for a later contract ADR.
ADR-0186 §8 makes the gap legible at the surface rather than closing it: no surface
may present a decision as a transmission, so a user reading their own history can
see what was permitted and can never see what happened.

**Three things about the tree are worth reading rather than remembering, because
two of them are not what a summary of #1503 would predict.**

**An execution record already exists, and it is the plan step.** ADR-0148 §9 rules
that "Every transmission through the seam happens under a committed `→ RUNNING`
claim on a plan step whose `approval_ref` is the authorising decision's id", that
"The **attempt identifier** ADR-0017 §3 requires is that step execution", and that
the four outcomes are the step's. The trail and the plan store already point at each
other in both directions. So the missing thing is not "a record of execution"
generically. It is three narrower things: that record is in a store no user-facing
history surface reads; it holds no cost; and it does not bound how many acts one
authorisation backs, because nothing does.

**Consume-on-execution was already ruled on, and the answer was no.** ADR-0029 §5
closes with a paragraph that names ADR-0021 §4 and answers it:

```text
**An approval is not consumed by executing it**, and ADR-0021 §4 left this open
in terms — "Making an approval single-*use* needs an atomic consume-on-execution
step, which belongs to the invocation contract". The answer is **no**, and it is
not a deferral.
```

Its reasons are good ones and this ADR keeps both. Spending an approval on the
first attempt would break retry — "a transient `UNAVAILABLE` would force a fresh
confirmation prompt for an action the user already approved" — and "An audit trail
whose entries are consumed is not an audit trail." What follows is written so that
neither sentence becomes false: nothing here erases, rewrites or hides a recorded
row, and a retry is still authorised by the same decision.

**The exactly-once debt is smaller than its citation suggests.** ADR-0016 §7's
exactly-once bullet is already discharged — ADR-0016's own dated note of 2026-07-21
records it, discharged by ADR-0029 §5, which derives `ToolCall.idempotency_key`
from `decision.id` rather than accepting one from a caller. ADR-0014 §7's bullet is
half discharged by the same note: the keys landed, and "Automated reconciliation of
an `INDETERMINATE` step" did not. This ADR does not land it either (§3), and says
so rather than citing a debt it leaves where it found it.

**What is genuinely absent, stated as a list.** Nothing records that a call was
entered, so a resolved `ALLOW` that ran once, ran twice or never ran leaves the
same rows. Nothing bounds the number of acts one resolution backs. Nothing records
what a call actually cost, and ADR-0016 §4 says the declaration's `cost` is a
declaration and not a measurement, which is why ADR-0021 §6 defers spend
accumulation to "invocation reporting what was actually spent". And no user-facing
surface can state an execution at all, because ADR-0186's two operations return
`PermissionDecision`s and §8 bars every transmission word over them.

## Decision

### 1. One authorisation, one act — and the consume is a claim, not an erasure

> **Normative.** An authorisation is **spendable** when the `ToolDefinition` its
> decision carries is `side_effecting` and its `idempotency` is not `NATURAL`.
> Otherwise it is not spendable, and no invocation under it is ever refused on the
> ground that the authorisation is spent.

> **Normative.** `ToolInvoker.invoke` appends a **claim** through the
> `InvocationLedger` it holds (§2), immediately before the callable is entered and
> after ADR-0029 §2's three checks have passed, **passing the `PermissionDecision`
> the call carries** and not its id alone. The append is the consume: it is one
> atomic store operation, and a call whose claim is refused does not reach the
> callable.

> **Normative.** Inside that operation the ledger requires the decision it was
> passed to be **equal to the decision the store holds under that id** — the whole
> value, by the frozen model's own equality — and refuses
> `UnrecordedAuthorisationError` where the store holds none under that id, where
> the stored one's ruling outcome is not `ALLOW`, or where the two are not equal.
> The row records the id; the equality is what makes the id mean the decision.

> **Normative.** A first claim under a decision that carries none is admitted. On
> a **spendable** authorisation a **further** claim is refused unless every one of
> these holds: no claim under that decision is open; **no** claim under it carries
> the outcome `SUCCEEDED` or `INDETERMINATE`; the last claim in the ledger's own
> append order for that decision is completed `FAILED` with a recorded
> `failure_kind` whose `retryable` is true; the decision's
> `ToolDefinition.idempotency` is `KEYED`; and the elapsed time from the **first**
> claim in that append order to this one is strictly less than that definition's
> `idempotency_window`.

> **Normative.** "First" and "last" above are the ledger's own **durable append
> order** for that decision, never an ordering over `recorded_at`. A stored instant
> is what a reader is shown; the order is what the rule is decided on, and the two
> are kept apart deliberately — a wall clock that steps backwards must not be able
> to make a completed act stop being the most recent one.

> **Normative.** The ledger stamps `recorded_at` itself, from an injected `Clock`
> wrapped by `checked_clock` (ADR-0026), and no caller supplies it. Any reading of
> the elapsed time that is not a positive duration is treated as the window having
> lapsed, and the claim is refused; a clock that raises refuses the claim too. Both
> are ADR-0029 §5's fail-closed rule for the same measurement, unchanged and
> enforced where the rule is.

> **Normative.** A claim refused because the authorisation is spent raises
> `AuthorisationSpentError`. A claim refused because the trail holds no decision
> under that id, holds one that is not equal to the decision passed, or holds one
> whose ruling outcome is not `ALLOW`, raises `UnrecordedAuthorisationError`. Both are seam faults, returned as no
> `ToolResult` and never as data, and neither is ever auto-retried. A
> `ToolInvoker` propagates each unchanged rather than translating it.

> **Normative.** **Every** failure of the claim append — either refusal above, a
> malformed argument, a clock that will not read, a store that will not write, any
> class whatever — is an exit **before the callable is entered**, always, and that
> is a clause of this contract rather than a property of an implementation. Each is
> therefore an exit in the window ADR-0034 §1 governs, qualifying on that section's
> **second** ground — "The contract says the exit precedes the callable" — exactly
> as a `ToolBindingError` does. The executor commits `RUNNING → FAILED` and never
> retries, on the window and not on a list of classes.

> **Normative.** The claim append is performed so that its outcome is **observable
> before any cancellation is propagated**: a cancellation delivered while the append
> is in flight is absorbed, the append's result is observed, and the cancellation is
> then re-raised. This is the treatment ADR-0034 §1 already gives the executor's own
> claim — "a cancellation absorbed while the **claim itself** was in flight, where
> the write is known to have landed" — transcribed to this one, and it is what makes
> the "claim landed or did not" question answerable at all under ADR-0060.

> **Normative.** Where a cancellation is pending and the append **failed**, the
> append's failure is what leaves the seam: `invoke` raises the `AuditError` — or
> propagates the clock callable's own exception (§2) — rather than the
> `CancelledError`. The clause above absorbs the cancellation in order to *observe*
> the append, and a failed append is an observation with a consequence the
> cancellation does not carry: nothing could have run. Where the append **landed**,
> the cancellation is re-raised as the clause above says and the clause below
> governs.

> **Normative.** That precedence loses no cancellation. The task remains cancelled
> and the cancellation is delivered again at the next suspension point in the
> cancelled scope; what the precedence decides is only **which fact the executor is
> told first**, and the append failure is the one that is true of the act. The
> alternative was worse in the direction this ADR cares about: a `CancelledError`
> from a side-effecting non-`NATURAL` call is classified by
> `ToolDefinition.interrupted_outcome`, so an append that never landed would be
> recorded `INDETERMINATE` — an act that may have run — for a call the contract
> guarantees could not have. ADR-0034 §1 refuses exactly that in this window.

> **Normative.** Where the claim landed and the call is then cancelled before the
> callable is entered, `invoke` appends the completion carrying the outcome ADR-0029
> §4 computes for that cancellation, and re-raises. This ADR does not change that
> classification, does not reserve it to cancellations after the callable, and gives
> the seam no returned reachability fact. #234 owns all three.

> **Normative.** The claim spends the authority to **begin a further act** and
> nothing else. It removes, rewrites, hides, expires or invalidates no recorded
> row; `PermissionDecision.authorises` stays the pure comparison ADR-0021 §1 made
> it, answering identically before and after a claim; and no lane reads a claim as
> a change to what a decision says.

> **Normative.** A retry admitted by the third clause is not a second act. It
> appends a further claim under the same decision, and it is admitted exactly
> because ADR-0029 §5's conjunction is satisfied. That section's key derivation,
> its retry conjunction, its two-sided window obligation and its fail-closed
> elapsed-time reading are untouched and are still what bound repetition.

**The further-claim rule is ADR-0029 §5's two-part retry conjunction transcribed
onto the store, not a looser one beside it.** §5 permits a repeat only where
`result.failure.kind.retryable` is true **and** repeating is safe, and on a
spendable authorisation — side-effecting, not `NATURAL` — the second conjunct
reduces to the one arm that remains: `KEYED`, inside its window. So an
`Idempotency.NONE` side-effecting tool gets **exactly one claim, ever, whatever the
failure kind**, which is §5's "An `Idempotency.NONE` side-effecting tool is
therefore **never** auto-retried, whatever the failure kind" made a property of the
store. An earlier draft admitted a further claim after *any* `FAILED`, which was
looser than the executor's own rule and would have left the consume unable to bound
the tool class most at risk; that is why `failure_kind` is on the row at all (§2),
and why the window is measured from the first claim rather than the last.

**The order and the clock are the two things a caller must not own, and an earlier
draft gave it both.** It had the caller mint `recorded_at` and the store decide
admission over those instants, which is two failures in one sentence. A caller
could submit a retry stamped one second after the first claim, hours later, and
satisfy every refusal rule — the window would be enforced against a number the
party being bounded supplied. And "most recent" read over caller instants is not a
history: with a wall clock that steps back, a claim written after a success can
carry an earlier instant, and a completed act stops being the most recent one. So
the ledger stamps, from a clock `checked_clock` guards, and admission reads its own
append order. `CONTRIBUTING.md`'s determinism rule is satisfied the way the rest of
the tree satisfies it — the clock is injected, so a test pins the boundary rather
than racing it.

**This does not make ADR-0021 §4's `record` inconsistent with the ledger, and the
difference is the point.** A `PermissionDecision.decided_at` is *when a policy
ruled* — a fact the caller holds and the store cannot recover — so the caller mints
it. A claim's `recorded_at` is *when the append happened*, and it is an input to a
rule the store enforces against that same caller. A store that enforces a rule over
a number the caller chose enforces nothing.

**The row's `id` divides on the same line, and review had to point that out.** A
`PermissionDecision.id` is minted by the caller that records the decision, because
that id is the name the *rest of the system* already knows the ruling by — a step's
`approval_ref`, a `ToolCall`'s `decision`, this ADR's own `decision_id` — so it has
to exist before the write. An invocation row's id names nothing outside the store:
it is minted at the append, learned from the returned row, and used once, to point
a completion at its claim. An earlier draft took it as an argument and had no
answer to the obvious question — where does `ToolInvoker` get one. Neither
`ToolCall` nor the seam has an id source; deriving one from `decision_id` collides
across the two rows of a single attempt and again across a retry; and inventing one
inline would put unseeded randomness on the write path, which `CONTRIBUTING.md`
forbids. Minting it in the ledger, from an injected factory, answers all three at
once and takes a refusal class off the contract rather than adding one: nothing
outside the store can name a row that does not exist yet, so there is no duplicate
`id` for the store to refuse.

**The discriminator in the spendability clause is ADR-0029 §5's own.** Its retry
rule permits a repeat when "the tool is not `side_effecting`; or its `idempotency`
is `NATURAL`; or it is `KEYED` **and** the elapsed time since the first attempt of
this call is strictly less than `idempotency_window`" — so the corpus has already
decided which tools a repeat is safe on, and the consume borrows that test rather
than inventing one. The first two arms decide **spendability**: a read gated by
ADR-0016 §3 is invoked under one `ALLOW` as often as the pipeline needs it, and
refusing the second read would break working behaviour to protect nothing. The
`KEYED` arm decides **the further claim**, above, where it belongs — a repeat under
a lapsed window is not a retry, and §5 says so in terms.

**Why this does not falsify either sentence ADR-0029 §5 gave as its reason.** Retry
survives, because the retry path is the `FAILED` arm: the approval still authorises
the second attempt, and the transient `UNAVAILABLE` §5 was written about still does
not reach the user as a fresh prompt. And the trail is not consumed, because
nothing is consumed: a claim is an **append**, and the sole thing it spends is a
permission to append a second one. What ADR-0029 §5 rejected was destroying the
record of what was authorised; what this ADR adds is a record of what was
performed. The paragraph is superseded because its literal answer — "no", and "not
a deferral" — is now partly yes, which is a change to what was decided and takes a
supersession under ADR-0070 §1 whatever the reasoning behind it survives.

**Placing the claim immediately before the callable is what keeps two records from
disagreeing, and the placement is load-bearing.** ADR-0034 §1 rules that an attempt
ending "after the claim is committed and before the callable is reached" commits
`RUNNING → FAILED` and is never retried — an exit where nothing could have run. A
claim appended earlier than the callable, at the top of `invoke`, would leave a row
saying an act may have happened for exits that ADR-0034 §1 has already ruled could
not have. Appended where this clause puts it, the two records agree by construction:
before the claim, ADR-0034 §1's window and no invocation row; after it, an act that
may have run and a row that says so.

**The atomicity lives in the store, and it lives there for ADR-0021 §4's own
reason.** That section put the resolution invariant on `record` "because this is
the only place both records are in hand", and made the append atomic because
"without that the single-use guarantee is a race — two concurrent resolutions of the
same `CONFIRM` each observe no prior resolution, each append, and one user approval
has authorised two executions". The consume is the same guarantee one seam later,
against the same race, and putting it anywhere else would mean a check followed by a
write with an `await` between them. Two concurrent `invoke`s on one decision reach
one atomic append: one claims, the other is refused.

**Equality rather than an id lookup, and review found the gap by constructing the
attack.** An earlier draft passed `decision_id` alone, which admits a caller who
takes the id of a **recorded, harmless** `ALLOW` and builds a second `ALLOW`
carrying that same id and a dangerous `ToolDefinition`. ADR-0029 §2's three checks
inspect the decision the call carries and pass; the ledger, holding only the id,
finds the harmless stored row and admits the claim; the dangerous callable runs and
`RecordedInvocation` then reports the harmless tool and capability, because §2's
join reads the stored decision. That is worse than an unrecorded execution: it is a
*misrecorded* one, and it defeats ADR-0021 §1's pinned-definition record and
ADR-0029's equality chain at the one seam this ADR adds. Requiring the whole value
to match closes it for the price of an argument `ToolInvoker` already holds —
`ToolCall.decision` — so nothing new reaches `tools/`. It also makes §2's join
sound: the decision a `RecordedInvocation` is joined to is the decision the act ran
under, not merely one filed under the same name.

**That narrows #259 and does not close it, and the difference is worth stating.**
#259 records that `StepExecutor` "accepts any valid `ToolCall`", so a caller
hand-building an `ALLOW` nobody recorded can have its id committed as a step's
`approval_ref`. Under the refusals above such a call cannot **execute**: the claim
carries a decision the trail does not hold — or does not hold *that* value under
that id — and is refused before the callable.
What remains reachable is the step claim itself, which is committed before `invoke`
is entered — so a fabricated authority can still open a step, and that step is then
closed `FAILED` by ADR-0034 §1's rule. #259's own analysis says a check placed after
the claim leaves "closing a step that should never have been opened" as the only
available response; that response is ADR-0034 §1's and it is already specified.

### 2. Two seams, not one, and the row they write

> **Normative.** `core/protocols.py` gains `InvocationLedger`, with exactly two
> members. `claim_invocation(*, decision: PermissionDecision) -> ToolInvocation`
> appends a claim and returns the stored row; it stores the decision's `id` and
> stores no other part of the value it was passed (§1's equality refusal is what it
> is passed for).
> `complete_invocation(*, claim_id: DurableIdentifier, outcome: ToolOutcome, incurred_cost: ToolCost, failure_kind: ToolFailureKind | None = None) -> ToolInvocation`
> appends its completion and returns the stored row. Both are `async`, both stamp
> `recorded_at` themselves, both mint the row's `id` themselves, and both decide
> every refusal below inside the same atomic operation as the append.

> **Normative.** The ledger mints each row's `id` from an **injected identifier
> factory**, and no caller supplies one. The factory is a collaborator of the
> implementation exactly as the `Clock` is, injected so that a test pins the value
> rather than races it — `CONTRIBUTING.md`'s determinism rule, satisfied the way
> `planning`'s own `id_factory` satisfies it. A minted id is fresh on every append
> and is derived from no other field of the row, and in particular not from
> the decision's `id`: the two rows of one attempt share that value, and a retry
> shares it again, so any derivation from it collides. Returning the stored row is
> how a caller learns the id it will need — `invoke` passes the claim's own `id` as
> the completion's `claim_id`, and holds it nowhere else.

> **Normative.** A `ToolInvoker` implementation holds an `InvocationLedger` and
> **never** an `AuditTrail`. The ledger can neither record a `PermissionDecision`,
> nor read one, nor export, nor `clear`, so no decision write, no history read and
> no erasure reaches `tools/` through this seam.

> **Normative.** `AuditTrail` gains exactly two members, both reads:
> `recent_invocations(*, limit: int = 50) -> list[RecordedInvocation]` and
> `export_invocations() -> list[RecordedInvocation]`. `recent_invocations` carries
> `recent`'s total order, its bounded default and its `ValueError` on a `limit`
> that is not strictly positive. Each returns a detached snapshot, as every other
> `AuditTrail` read does (ADR-0018 §3).

> **Normative.** Each read **joins the row to its decision inside one atomic store
> operation**, so every `RecordedInvocation` it returns is complete. No consumer
> assembles one from two reads, and no implementation returns a row it could not
> pair.

> **Normative.** The composition root injects **one object implementing both
> Protocols**, over one store. This is ADR-0029 §8's rule for `ToolRegistry` and
> `ToolInvoker`, applied for the same reason: two tables keyed by the same
> decision could diverge, and the consume would then bound one of them.

> **Normative.** `core/types.py` gains `ToolInvocation`, frozen with
> `extra="forbid"`, whose fields are exactly: `id: DurableIdentifier`;
> `decision_id: DurableIdentifier`; `recorded_at: UtcInstant`;
> `completes: DurableIdentifier | None = None`; `outcome: ToolOutcome | None = None`;
> `incurred_cost: ToolCost | None = None`; and
> `failure_kind: ToolFailureKind | None = None`.

> **Normative.** It has **exactly two well-formed shapes** and a validator refuses
> every other combination at construction. A **claim** carries `completes`,
> `outcome`, `incurred_cost` and `failure_kind` all unset. A **completion** carries
> `completes`, `outcome` and `incurred_cost` all set, and `failure_kind` set when
> and only when `outcome` is `FAILED`. `completes` is the discriminator.

> **Normative.** `core/types.py` gains `RecordedInvocation`, frozen with
> `extra="forbid"`, whose fields are exactly: `invocation: ToolInvocation`;
> `tool: VisibleIdentifier` and `capability: VisibleIdentifier`, read from the
> `ToolDefinition` the named decision carries; and `egress_call: bool`, true when
> and only when that decision's `egress_binding` is not `None`. It carries nothing
> else — no ruling, no reason, no binding, no destination, no digest and no whole
> `ToolDefinition`.

> **Normative.** `core/errors.py` gains exactly three classes, **all three deriving
> from `AuditError`** and none from `ToolError`: `AuthorisationSpentError`,
> `UnrecordedAuthorisationError` and `InvalidCompletionError`. Each preserves its
> cause where it has one. A consumer catching `AuditError` catches every failure
> either ledger member raises, the translated ones below included.

> **Normative.** `claim_invocation` refuses in this order and no other: `AuditError`
> where an argument is not valid; `UnrecordedAuthorisationError` where the store
> holds no decision under that id, where the stored decision is not equal to the one
> passed, or where the stored decision's ruling outcome is not `ALLOW`; then
> `AuthorisationSpentError` where §1's consume refuses. The three grounds of the
> second are one class deliberately: they are all "the authority this call claims is
> not one this store recorded", and separating them would tell a caller which half
> of a forgery was detected.

> **Normative.** `complete_invocation` refuses in this order and no other:
> `AuditError` where an argument is not valid, which includes a `failure_kind` that
> disagrees with `outcome`; then `InvalidCompletionError` where `claim_id` names no
> recorded claim or names one already completed. It never raises
> `UnrecordedAuthorisationError`: a completion names a claim, and the claim already
> names the decision.

> **Normative.** The two orders above are exhaustive over the **classes a refusal
> arrives in**, not over the causes a failure can have. A failure that is neither a
> named refusal nor an argument fault — the guard rejects the reading, the store
> cannot be read, the store cannot be written — is translated at this boundary and
> raised as a plain `AuditError` carrying its cause. That is ADR-0026 §4's rule for
> a subsystem boundary and not a new one, and it is why the three named classes
> derive from `AuditError` rather than standing beside it.

> **Normative.** The clock is split exactly where ADR-0026 §2 splits it, and this
> ADR draws no new line. The guard's **own** rejection of a non-conforming reading —
> `checked_clock`'s owner-labelled `ValueError`, `ClockReadingError` — is a
> `ValueError` and not an `AssistantError`, so the ledger translates it to
> `AuditError` and a `ToolInvoker` never meets a non-`AssistantError` from this
> seam. An exception **the clock callable itself raises** propagates **unwrapped**:
> ADR-0026 §2 rules that "The guard covers the reading, not the invocation. An
> exception raised by the clock callable itself propagates unwrapped", and ADR-0034
> §2 already applies that split at the neighbouring seam, "raising `PlanningError`
> for the guard's own `ClockReadingError` and leaving anything the callable raises
> on its own account untouched". The ledger does the same, so **nothing of ADR-0026
> is superseded** — relabelling a callable's own failure would destroy its type and
> its cause, which is the reason §2 gives. §1's "a clock that raises refuses the
> claim" means both halves and is not a claim that both arrive as one class.

> **Normative.** Where such a failure prevents a refusal above from being **decided
> at all** — the store will not answer whether the decision is recorded, or whether
> a claim is open — the plain `AuditError` is the whole answer, and no refusal above
> is guessed at, reported as though it had been evaluated, or skipped over. This
> costs nothing in safety: §1 makes **every** failure of the claim append an exit
> before the callable is entered, whatever its class and including the unwrapped
> exception above, so an undecidable refusal and a decided one fail in the same
> direction.

> **Normative.** The row restates nothing its decision already fixes. It carries no
> `ToolDefinition`, no `parameters_digest`, no `step_id`, no `execution_id`, no
> account, no transport endpoint and no destination. What a call transmitted to is
> the decision's own `EgressBinding.canonical_destination_set`, reached through
> `decision_id`, and no lane copies that set, or any member of it, onto this row or
> onto a `RecordedInvocation`.

> **Normative.** The row carries **no content**. Not an argument value, not a
> payload, not a tool's output, not a failure message, and not a digest of any of
> them. `failure_kind` is an enum member and is the whole of what a failure
> contributes. ADR-0004 §5 and ADR-0021 §1's payload rule bind here as they bind on
> a decision: what this row is an account of is the *act*.

> **Normative.** The row carries **no ordinal**. How many acts a decision has backed
> is read from the claims themselves under `recent_invocations`' order; no field
> states it, and no store allocates one.

> **Normative.** A completion's `decision_id` is set by the ledger from the claim it
> completes, never accepted from a caller, so the two cannot disagree.

**Two Protocols rather than one, because the invoker needs two methods and
`AuditTrail` has nine.** Handing a `ToolInvoker` the whole trail would put decision
writes, history reads, the whole-trail export and `clear()` into `tools/` — a
subsystem the architecture map gives integrations, not the permission record. That
is the shape ADR-0017 §8 wants to move away from and the split ADR-0029 §1 already
made once, in its own words: "handing every holder of a lookup the ability to
execute is the shape ADR-0017 §8 wants to move away from, and a consumer that only
reads is one a test can double without stubbing execution." A ledger that can append
two kinds of row and read nothing is the narrowest capability that does the job.

**And one object implements both, which is why the split costs no coherence.** The
consume is only a bound if every writer goes through it, so two independent stores
keyed by the same decision would be exactly ADR-0016 §7's named failure one level
over. ADR-0029 §8 already had this problem between the registry and the invoker and
answered it the same way; the residue is the same too, and it is the composition
root's.

**`InvocationLedger` is a new Protocol, so it is a triad.** Contract, shared
conformance suite and canonical fake in `ai_assistant.testing`, in one change and
never deferred (`CONTRIBUTING.md` → "Adding a Protocol"), and under ADR-0137 §2 it
may ride with its primary production implementation — the `permissions` store that
also satisfies `AuditTrail`, which is the consumer whose demands shape it. §9 is
where that lands.

**The reads return a joined value because the join cannot be done safely anywhere
else.** An engine reading rows and then reading their decisions has an `await`
between the two, and `clear()` landing in that gap leaves it holding rows whose
decisions are gone — with nothing to do but drop them, fabricate the identifiers, or
fail, all three of which contradict a total projection. One store operation has no
gap. It also restores ADR-0186 §1's relay rule for the engine (§4), which an earlier
draft of this ADR had to depart from precisely because the join was in the wrong
place.

**One row kind rather than two types, because the surface has to show both
together.** A claim with no completion is precisely the state a user most needs to
see, so a listing that returned claims and completions as two sequences would have
to be merged by whoever rendered it — the merge ADR-0188 §7 warns about, arriving
one level down: "the tempting shortcut for a future surface is to merge the two
lists". One kind, one order, one listing. Two shapes inside one model is the shape
`CanonicalDestination` already uses and for the same reason: the variants are
exactly two and a validator makes every other combination unconstructable.

**Two appends per attempt rather than one row that moves, because the trail does
not move.** ADR-0021 §4 makes the trail append-only and write-once with exactly no
`update`, and ADR-0148 §9 draws the same conclusion for its own case: "an outcome
that moves from pending to succeeded **cannot** live there, and an implementation
that tried would be rewriting an audit record". A claim and its completion joined
by a pointer is the shape the trail already writes — a `CONFIRM` and the resolution
whose `resolves` names it, refused unless the referenced row exists and is not
already answered — so the completion rule is that invariant transcribed onto a
second row kind rather than a new mechanism.

**Write-ahead rather than one row after the call, and this is the clause the whole
section is for.** A single row written on return would record nothing at all for a
call that died mid-effect, which is the one case where the record is worth having;
it would also make the consume impossible, since the refusal has to be decided
before the effect. ADR-0188 §5 reached the same answer for an act performed with
the hub down, and its reasoning transfers unchanged.

**Restating nothing is not economy, it is the failure ADR-0184 §2 named.** That
section declared an egress binding's members once, on a private base, because a
second declaration is "the 'second shape that must agree' ADR-0150 is named after,
arriving one level down", and because "a history row whose recipients were computed
by a second copy of the derivation could disagree with the set the user was shown
when the ruling was made". A destination set copied onto an invocation row is that
copy exactly. It is also unnecessary: ADR-0148 §1's title is that nothing in an
egress call moves after the ruling, so the set the call transmitted to **is** the
set the decision fixed, and a pointer to the decision is a pointer to it.

**`egress_call` is a boolean and not the binding, and that is the line between what
a surface may say and what it may show.** §4 grants one word — *sent* — on a
completed egress call, and a boolean is exactly what deciding that word needs. Who
received the bytes is `recent_decisions`' to render, under ADR-0186 §7's floor,
from the binding itself; putting a second copy of it here would be the drift the
paragraph above refuses, in service of a rendering another operation already owes.

**An earlier draft carried an `attempt` ordinal on the claim, and dropping it is a
correction rather than a simplification.** A caller-minted ordinal cannot be
allocated safely under concurrency — two racing claims both compute 1 — and a
store-allocated one buys nothing now that the ledger returns the stored row and
§1's rule bounds a spendable authorisation to one claim plus retryable `KEYED`
retries inside one window. The claims themselves, in the ledger's own order, are
the count.

### 3. `INDETERMINATE` spends the authorisation, and exactly-once is not landed here

> **Normative.** A claim completed `INDETERMINATE` spends a spendable
> authorisation exactly as `SUCCEEDED` does. No further claim is admitted under it.

> **Normative.** A claim carrying no completion states that the act **may have
> executed**, positively and as its own state. No lane, store or surface reads it
> as `SUCCEEDED`, as `FAILED`, as "did not run", as an omission, or as a row still
> being written.

> **Normative.** Once a claim is appended, `ToolInvoker.invoke` calls
> `complete_invocation` on **every** exit it observes — a returned `ToolResult`, a
> raised seam fault, an expired deadline, a cancellation — carrying the outcome
> ADR-0029 §§3–4 already compute for that exit. An exit that occurs **before** the
> claim completes nothing, because there is no claim: §1's refusals and the rest of
> ADR-0034 §1's window are that case.

> **Normative.** A **`BaseException` that is not a cancellation** — a
> `KeyboardInterrupt`, a `SystemExit` — is not an exit that clause reaches, and no
> outcome is invented for one. ADR-0029 §3 requires it to propagate unchanged, and
> ADR-0029 §§3–4 compute no `ToolOutcome` for it, so there is nothing to pass
> `complete_invocation` and this ADR mints nothing to fill the argument. `invoke`
> writes no completion, lets it propagate, and leaves the claim **open** — which is
> the exact state the clause below governs, and the honest one: the process is being
> torn down and the outcome was never established. Where a recovery scan later finds
> that step `RUNNING`, the clause on ADR-0014 §4 below completes the claim
> `INDETERMINATE` like any other. Nothing of ADR-0029 §3 is changed by saying so.

> **Normative.** The obligation above is **to make the call**, and a completion
> that is refused or fails to write changes nothing about the call itself.
> `invoke` returns the `ToolResult` the call produced, or re-raises the exception
> it was already raising, exactly as it would have; it does not convert the
> completion's failure into a `ToolResult`, does not substitute an outcome, does
> not retry the act, and does not re-claim. A `SUCCEEDED` side effect is not
> reported as failed because a disk was full.

> **Normative.** No such failure is **swallowed**: the implementation surfaces it
> to the operator as a Tier 2 diagnostic carrying the cause, and it is a diagnostic
> and never a row. `core/logging.py`'s redaction rules and ADR-0004 §5 bind it as
> they bind every operator-facing message.

> **Normative.** The result of all three clauses is a claim left **open**, which is
> the state the clause above governs and which no reader resolves. That is the
> honest record of an act whose outcome this system failed to write down, and it is
> preferred to every alternative that writes a number down instead.

> **Normative.** Where ADR-0014 §4's recovery scan records `INDETERMINATE` on a
> step, the same act appends an `INDETERMINATE` completion for **every** open claim
> under the decision that step's `approval_ref` names, not for one selected among
> them. Where none is open, it appends nothing: no open claim means no call was in
> flight.

> **Normative.** The order is **completions first, transition second**. The
> recovery act appends the `INDETERMINATE` completion for every claim it finds open
> under that `approval_ref`, and commits the step's transition out of `RUNNING`
> only after no claim under that decision is still open. It never commits the
> transition first.

> **Normative.** That ordering is the whole of the crash protocol, and it makes the
> act **idempotent** without a marker, a generation or a resume point. A crash
> partway through leaves the step `RUNNING`, so the next scan finds the same step
> and completes whatever is still open; a claim already completed is no longer open,
> so no rerun ever attempts a second completion of one and §2's
> `InvalidCompletionError` is not reachable by this path. A crash after the last
> completion and before the transition costs one scan that appends nothing.

> **Normative.** The scan **completes open claims and writes no other outcome.**
> Where it finds claims under that `approval_ref` already completed, it leaves them
> exactly as they stand: it rewrites none, appends no second completion for one, and
> reads none in order to decide the step's transition. ADR-0014 §4's transition
> graph is untouched by this ADR (§10), and a scan that derived a step's outcome
> from an audit row would be changing it.

> **Normative.** The two records therefore answer two questions and **are not
> required to agree**, in one direction and one only: an invocation row may read
> `SUCCEEDED` or `FAILED` under a step that reads `INDETERMINATE`. That is the crash
> window between two stores — the seam observed an outcome, wrote it, and the
> process died before the plan could record it — and the pair is the honest reading
> of it: the invocation row says what the seam observed, and the step says the plan
> could not be resolved. Neither is inferred from the other's absence, neither is
> rewritten to match the other, and this ADR gives no lane, scan or surface a rule
> for resolving one from the other. §4's rendering floor renders the row, §5's
> evaluation reads the claim, and ADR-0014 §4 governs the step.

> **Normative.** A claim can also be left **open under a step that is not
> `RUNNING`**: the completion write failed, `invoke` returned, and the executor
> committed the step's transition on the result it was handed. No recovery scan
> returns for that step, so that claim stays open for good. This ADR does not repair
> it and does not license a scan over steps in other states to close it: the outcome
> was never durably recorded, so there is nothing to recover and any value written
> there would be invented. Its cost is §5's — the evaluation fails closed while that
> claim is in scope — and any operator remedy is the budget ADR's, not a rewrite of
> a row.

> **Normative.** No lane reverses those two, and no lane treats the completions as
> follow-up work to be done after the transition. Committing the transition first
> loses every claim still open at that moment, permanently: the step stops being
> `RUNNING`, no later scan returns for it, and nothing else knows to look, because a
> `ToolInvocation` names no step (§2) and is reachable from that step's
> `approval_ref` and from nowhere else.

> **Normative.** Completing every open claim is required rather than convenient,
> because no row names a step. A decision may carry more than one open claim — a
> non-spendable authorisation admits concurrent invocations (§1) — and a scan
> holding only `approval_ref` cannot tell one from another. Completing all of them
> is the only unambiguous act, and it is the true one: the process died with each of
> them in flight.

> **Normative.** This ADR lands no automated reconciliation of an `INDETERMINATE`
> act and mints no idempotency mechanism. ADR-0014 §4's requirement that an
> `INDETERMINATE` step is never auto-retried and is resolved explicitly is
> unchanged, and ADR-0029 §5's derived key is unchanged. The ADR that lands
> automated reconciliation is fired by a tool contract that offers a **lookup by
> idempotency key** — until a tool can be asked whether a key was already acted
> on, reconciliation has nothing to read.

**Spending on `INDETERMINATE` is the conservative reading and it is chosen
deliberately.** `INDETERMINATE` is ADR-0014 §4's durable ignorance: the effect may
have committed. An authorisation left unspent on it would let a second act run
under an approval that may already have sent, which is the double-effect this
section exists to prevent, arriving through the one state where nobody can tell. A
spent authorisation that might have sent costs a user one fresh confirmation for an
action that may not have happened; the other direction costs a message sent twice.
ADR-0029 §5 already refuses to auto-retry an `INDETERMINATE` outcome, so this
extends a treatment the corpus has rather than inventing one.

**Two stores, one order, and that order buys a re-runnable window rather than an
identical pair.** The plan store and the audit store are two stores, so no single
commit covers both and some crash window is unavoidable; what an order can buy is
that the window always falls on the side a later act can still fix. Written as
above, a crash partway through the scan leaves the step still `RUNNING` with some of
its claims completed — a state the next scan resolves by doing exactly what it would
have done anyway. Written the other way it leaves an open claim with nothing
pointing at it, which no later act can find at all. Review found that reversal by
construction — two open claims under one decision, one completed, then a crash — and
it is the same class of defect as §6's race clause.

**What the order does not buy is that the two records read the same, and an earlier
draft of this ADR claimed it did.** Review found the counter-example immediately:
a `SUCCEEDED` completion lands, the process dies before the executor commits
`RUNNING → SUCCEEDED`, and the scan then finds a `RUNNING` step with no open claim.
Under ADR-0014 §4 it records `INDETERMINATE`, so the ledger reads `SUCCEEDED` and
the step reads `INDETERMINATE` for one attempt. Closing that would take either a
transaction across two stores, which there is none, or letting the scan write the
step's outcome from an audit row, which is a change to ADR-0014 §4's transition
graph that §10 puts out of scope and that would make the plan store's own
compare-and-swap answerable to a second store. So the clauses above state the
divergence instead, in the one direction it can occur and with the reading each
record supports — which is what ADR-0148 §9's own rule already demands of a pair of
records, that neither be inferred from the other. The claim that was wrong was
"converge by construction"; what is true is that neither record is guessed from the
other, and that the difference is always in the conservative direction: the step is
the more ignorant of the two, never the more confident.

**A claim with no completion is ADR-0184's third state, one store over.** That ADR
minted a value rather than a marker precisely so "the absence is its own value", and
ADR-0188 §4 states the same rule positively for a record whose process died. The
failure being avoided is identical in all three: a reader, or a surface, quietly
resolving a state nobody recorded into whichever of the two known states is
convenient.

**This ADR gives the seam the durable reachability fact #234 asks for, and does not
close #234.** That issue records that "the executor holds no fact about how far the
call got", so a cancellation during the seam's own pre-call work is classified
`INDETERMINATE` by `ToolDefinition.interrupted_outcome` even where nothing could
have run. Under §1's placement the claim **is** that fact, durably: a cancellation
before the claim leaves no row, one after it leaves an open claim. What #234 asks to
change is the executor's *classification*, which reads a declaration and not this
store, and changing it is a Protocol decision of #234's own. So this ADR narrows the
cost — the record distinguishes the two cases even where the step's status does
not — and leaves the classification exactly as ADR-0029 §4 ratified it.

**#305 does not bear on this and is cited to say so.** Its subject is the
`execution_id` nonce `planning` mints under a fork. The claim key here is
`decision_id`, minted by the caller that records the decision under ADR-0021 §1, so
nothing in this section inherits that nonce or its hazard.

### 4. The surface: two operations, two sequences, and one word that becomes sayable

> **Normative.** `AssistantEngine` gains exactly two methods.
> `recent_invocations(*, limit: int = DEFAULT_PAGE_SIZE) -> tuple[RecordedInvocation, ...]`
> reads `AuditTrail.recent_invocations`;
> `export_invocations() -> tuple[RecordedInvocation, ...]` reads
> `AuditTrail.export_invocations`. Neither composes, filters, projects, enriches or
> summarises what the trail returns, and neither reads any other store. The join is
> the store's (§2) and the engine relays it, which is ADR-0186 §1's rule unchanged.

> **Normative.** Both return values ordered by the row's `recorded_at`
> **descending**, ties broken by the row's `id` **ascending**, and
> `recent_invocations(limit=n)` returns the first `n` of the sequence
> `export_invocations()` returns over the same trail state. The order is guaranteed
> by the engine operation, over a list it has materialised. `limit` is refused when
> it is not an integer, when it is a `bool`, and when it is outside `[1, 2**63)` —
> locally and before any I/O, in every implementation. `export_invocations` takes no
> argument and is subject to ADR-0085 §8c's payload limit exactly as
> `export_decisions` is. There is no `offset`.

> **Normative.** The two row kinds are two operations returning two sequences. No
> operation returns a mixed sequence; no lane widens ADR-0186 §1's return type or
> adds a `ToolInvocation` or a `RecordedInvocation` to what `recent_decisions` or
> `export_decisions` returns; and ADR-0186 §8's clauses bind every row those two
> operations return, unchanged and in full.

> **Normative.** ADR-0188's hub-down egress record is not a `ToolInvocation`, is not
> a `RecordedInvocation`, and is not returned by either operation above. ADR-0188
> §7's first clause is read forward onto this surface: that record is rendered
> through no operation this ADR decides, is listed among no row of these listings,
> and is counted in no bound stated over them.

> **Normative.** A surface rendering a `RecordedInvocation` renders, for every one:
> the row's kind — claim or completion — the instant it was recorded, and the tool
> identifier and capability the value itself carries. For a completion it also
> renders the outcome, the failure kind where the outcome is `FAILED`, and the
> incurred cost, **including that the cost is unknown** where the basis is
> `UNKNOWN`. It omits, truncates, summarises, samples and counts in place of none of
> that, and a surface that cannot render one whole renders **fewer of them**.

> **Normative.** Every value a surface renders here comes from the
> `RecordedInvocation` in hand. No surface joins two operations' answers, reads a
> store, calls a second operation to complete a row, or infers a missing half —
> which is what the store-side join exists to make unnecessary.

> **Normative.** A surface may render an invocation row **as an execution**, which
> is what the row is. On a **completion whose outcome is `SUCCEEDED`** and whose
> `RecordedInvocation` carries `egress_call` true, a surface may say that the call
> was **sent**. It says this on no other row and in no other state.

> **Normative.** No surface says or implies that anything was **read**, **received**,
> **delivered**, **seen** or **acted on** by any recipient, on any row, in any
> state. `SUCCEEDED` is what the tool reported to the seam and nothing observes
> what happened after that. ADR-0186 §8's third clause is narrowed to decision rows
> and to nothing else; every other bar it states stands over every row of every
> operation, this ADR's included.

> **Normative.** No surface names a recipient, an account, an endpoint or a
> destination on an invocation row. `egress_call` states that the call was an egress
> call and states nothing about whose bytes went where; the recipients are
> `recent_decisions`' to render, under ADR-0186 §7's floor, from the binding itself.

> **Normative.** A surface that renders both kinds together states each row's kind
> and renders neither in the other's vocabulary. It presents no decision row as a
> transmission, no invocation row as a ruling, and no joined pair as a single
> record.

> **Normative.** No surface derives a count of executions from anything but the
> rows it holds. The absence of a completion, or of a claim, from a bounded page is
> a fact about the page.

> **Normative.** Every value rendered is inserted into the surface's output as
> **data**, neutralised for that target on render (ADR-0042 §4).

> **Normative.** Which adapters render these operations is the implementing lane's,
> and the rendering floor above binds each that does. This ADR promotes no CLI
> command and reserves no command name.

**Separate operations rather than one interleaved listing, and ADR-0186 §1 is why
the question does not even reach taste.** Its first clause fixes
`recent_decisions`' return as `tuple[PermissionDecision, ...]` and its second says
nothing else is promoted *by that ADR* — which leaves a later ADR free to promote a
third and fourth method, and leaves nobody free to change what the first two
return. A mixed sequence would require exactly that change. It would also put the
merge ADR-0188 §7 names inside the contract, "at which point either this record is
rendered as a ruling, which is false, or the rulings are rendered as transmissions",
which is the failure both ADRs are defending against from opposite sides.

**The engine relays and does not compose, and getting there took moving the join.**
A bare `ToolInvocation` cannot be rendered under its own floor — the tool's identity
lives on the decision, and a bounded page may hold a completion whose claim and whose
decision are not on it. An earlier draft had the engine pair the two, which meant an
`await` between reading rows and reading decisions and a `clear()` able to land in
it. The join is the store's now (§2), atomically, so the engine is a relay again and
ADR-0186 §1's rule is untouched rather than departed from. The alternatives were both
forbidden anyway: golden rule 3 keeps the join out of `interfaces/`, and ADR-0042 §4
keeps an adapter from reaching past the engine for a second store.

**The projection is bounded by construction, so ADR-0085 §8c's ceiling is not made
worse by it.** A `RecordedInvocation` is one small row, two identifiers and a
boolean, where a `PermissionDecision` measured 858 bytes in this tree carrying a
whole `ToolDefinition` and an egress binding (ADR-0186 §3). The export of
invocations is subject to the same limit and fails the same honest way.

**"Sent" is the whole point of the exercise and it is granted narrowly.** ADR-0186
§8 barred it because the trail held only rulings: "a resolved `ALLOW` says a call
was permitted and says nothing about whether, or how many times, it ran". That
sentence stays true of a decision row and is now false of nothing, because the word
is granted on a different row — one that *is* an execution, over a decision the
store has already confirmed carried a binding. The three words that stay barred
everywhere are barred for a reason no record can lift: nothing in this system
observes a recipient. A tool reporting `SUCCEEDED` reports that its own upstream
accepted the call, and a surface that turned that into "delivered" would be
asserting the measurement ADR-0016 §3 declines to offer, one axis over.

**Deciding the engine surface here rather than deferring it, which ADR-0188 §7 did
for its own record.** That deferral rested on the record being "in the data
directory, is legible without this system, and is copied by the same act that
exports it". Nothing of that holds here: these rows are in a Tier 1 store only the
hub opens, so a user reaches them through the engine or not at all. Leaving the
surface out would land the record and leave #1503's user-visible half exactly where
the milestone-24 ruling found it.

### 5. What the budget ceiling reads

> **Normative.** `ToolResult` gains `incurred_cost: ToolCost | None`, defaulting to
> `None`: what **this invocation** cost, as the tool reports it. `None` states that
> the tool reported no figure. It is named apart from `ToolDefinition.cost` so that
> a declaration and a measurement are never one word.

> **Normative.** A tool reports a figure only where it **knows** one. A tool whose
> price is settled asynchronously, or later, or elsewhere, reports `UNKNOWN` — the
> `CostBasis` member that exists for exactly that state — and never a number it
> constructed to fill the field.

> **Normative.** `ToolInvocation.incurred_cost` on a completion is the reported
> value where the tool reported one, and a `ToolCost` whose basis is `UNKNOWN`
> otherwise. No lane copies `ToolDefinition.cost` into it, or derives it from the
> declaration by any other route.

> **Normative.** A spend accumulator **sums** `ToolInvocation.incurred_cost` over
> **completion** rows and sums no other field of any row. A member whose basis is
> `UNKNOWN` fails closed, which is ADR-0016 §4's rule for `UNKNOWN` and not a new
> one.

> **Normative.** That clause governs the **sum**. It does not govern the
> **evaluation**, and the two are named apart here deliberately. A spend evaluation
> reads one further fact and exactly one: whether any claim is **open** in the scope
> it totals over. An open claim is an act that may have run at a price nothing
> recorded, so it **fails the evaluation closed**, in the same way and for the same
> reason a completion whose basis is `UNKNOWN` does. No lane reads an open claim as
> zero, as free, as pending, or as a row still being written; §3's clause forbidding
> a reader to resolve it binds here in full.

> **Normative.** Those are one rule over two absences, and the budget ADR states its
> refusal once over both. A completion carrying `UNKNOWN` says the act ran at a
> price the tool could not report; an open claim says the act may have run at a
> price this system failed to write down. Neither is a number, and a total that
> treats either as zero is exactly the failure this section exists to prevent.

> **Normative.** `incurred_cost` is the price of the invocation. It is never money
> the tool moved, and no lane reads it as a transacted amount (ADR-0016 §4).

> **Normative.** This ADR decides no ceiling, no budget period, no currency
> reconciliation and no refusal outcome. Those are the budget ADR's, and it cites
> the field named above rather than reshaping it.

> **Normative.** The accumulator counts **every** completion row, including one
> whose `incurred_cost` carried the total past a ceiling. No row is excluded from the
> total because a refusal followed it, and no lane treats a crossing call as free.

> **Normative.** This row carries no model-token accounting and no model spend.
> `incurred_cost` is the price of one tool invocation; a ledger over model calls
> is a different ledger, and no lane folds one into the other on this row.

**ADR-0029 §3 refused this field and its reason is answered rather than
overridden.** That section says "**`ToolResult` carries no cost and no disclosure
report**, and both omissions are decisions", and gives the reason: "invocation
cannot — billing is asynchronous, so a `spent` field would hold a number the tool
made up, which is the fiction ADR-0016 §4 refused when it declined to model
transacted amounts." The objection is exact and it selects an *arm* rather than
refuting the field. A tool whose billing is asynchronous does not know what the
call cost, and `CostBasis.UNKNOWN` is the value for not knowing — declared by
ADR-0016 §4 precisely because "the distinction that matters to a policy is not
present/absent but *free* versus *unknown*". So the second clause above forbids the
number §3 was written against, in terms, and the field carries a `ToolCost` rather
than the bare `Decimal` a `spent` field implies: a tool that cannot know reports
`UNKNOWN` and the accumulator fails closed. §3 also anticipated this exact landing
— "Both are additive fields on this type when their own decisions land, which is
why the type is a model rather than a bare tuple" — but its sentence "`ToolResult`
carries no cost" is nonetheless false after this ADR, and §3 calls that omission a
decision, so it is recorded as a supersession and not left to the anticipation
(§7).

**The accumulator had to be told about the open claim, and review found that hole
in the one section written to close it — both lenses, independently.** §3 requires
a completion attempt on every exit and also rules that a completion which will not
write leaves the claim open while the call's own result stands. So a call that
reported a real price, whose completion write then failed, leaves a claim, no
completion, and — under the summing clause read alone — a total of zero. That is
the precise direction this section was written against, arriving through §3's own
failure path rather than through a tool that lied. The answer is not a new field:
the open claim is already the durable record that an act may have run, and the
accumulator only had to be forbidden from ignoring it. What the clauses above add
is the separation the earlier wording ran together — what is *summed*, which is
still completion rows and nothing else, and what is *evaluated*, which now includes
an absence.

**The distinction between a declaration and a measurement is the one thing this
section exists to keep.** ADR-0016 §4 makes `cost` "the price of *one invocation of
the tool itself*" as **declared**, and ADR-0021 §6 defers spend accumulation
precisely because "a running total against a budget needs invocation to report what
was actually spent, and ADR-0016 §4 already records that `cost` is an estimate
nothing reconciles". Copying the declaration onto a row labelled `incurred` would
discharge that deferral in appearance and reproduce the estimate underneath, which
is the fiction ADR-0016 §4 refused when it declined a definition-level field for
money the tool moves. The second clause forbids it in terms so that no
implementation reaches for the convenient value.

**`UNKNOWN` rather than a `None` on the row, because the row must state the fact
rather than omit it.** `CostBasis` already spells the difference ADR-0016 §4 was
written for — "the distinction that matters to a policy is not present/absent but
*free* versus *unknown*" — and an optional field would reintroduce the two-state
value that section rejected, at the one place where the total is at stake.

**One currency question is left open on purpose.** ADR-0016 §4 says "A policy
comparing amounts across currencies needs conversion rates and is out of scope
entirely", and a ceiling summing rows in two currencies meets that problem head on.
It is the budget ADR's to answer; naming it here would be deciding the ceiling.

**The two clauses above are written against a surveyed failure rather than an
imagined one.** #1548 surveys five agent runtimes and finds exactly one spend
ceiling among them — and that one is over model tokens, is a client-side estimate
its own documentation says not to bill from, and counts a tool execution as zero.
The survey's two recorded accounting corners are the ones the clauses close: the
call that crosses the ceiling is still spent and must be counted rather than
treated as free, and a budget that is a token budget in disguise misses the axis a
world budget is about. The same survey records a runtime whose resume "re-executes
all logic" from the start of a node, so a side effect before an interrupt runs
twice — which is §1's failure reached by a caller re-check instead of an atomic
single-use claim, observed in a shipped system. None of those figures is measured
here; they are what the surveyed projects' own code and documentation say, and
#1548 carries that caveat in its own terms.

### 6. Data rights

> **Normative.** `ToolInvocation` rows are Tier 1 (ADR-0004 §7), persist **locally
> only** under ADR-0004 §2's residency clause, and are held by the same store as
> the decisions they name. They are append-only and write-once: `claim_invocation`
> and `complete_invocation` each append exactly one row under an `id` the ledger
> mints fresh at the append (§2), so no caller can name a row in order to overwrite
> it, and there is no `update` and no selective delete.

> **Normative.** `AuditTrail.clear()` erases **both** row kinds and returns the
> count of every row it removed, of either kind. No operation erases one kind and
> leaves the other, and no surface offers one.

> **Normative.** `clear()` wins any race with an in-flight invocation. A
> completion whose claim was erased under it is refused as
> `InvalidCompletionError` like any other completion naming no claim, and §3's
> three clauses govern from there without a special case: the call's own result
> stands, the failure reaches the operator, and nothing is recreated. No lane
> mints an erasure marker, a cleared generation, or any other value by which the
> two causes could be told apart.

> **Normative.** `AuditTrail.export_invocations` and the engine operation above
> discharge ADR-0004 §6's portability obligation for this row kind.

> **Normative.** Every read of this row kind returns a **detached snapshot** — the
> sequence returned and everything mutable it reaches — as every other `AuditTrail`
> read does (ADR-0018 §3, ADR-0021 §4). The trail's own two reads return a `list`
> and the engine's two operations return a `tuple` (§§2, 4); both are detached, and
> neither is a view onto stored state.

> **Normative.** This ADR mints no retention rule and no TTL. #108's question is
> unchanged and now covers both kinds of row; a rule that expires one kind and not
> the other is not available to the ADR that answers it, because a trail holding
> completions whose claims have expired would misstate what it holds.

**The race clause resolves a real contradiction, and it resolves it without asking
the store to tell two causes apart.** §3 requires a completion attempt on every exit
after a claim, and §2 refuses a completion whose claim is not there — so an erasure
landing between them would, under an earlier draft that suppressed the error, have
required the store to distinguish "the user burned the trail" from "this pointer is
corrupt". It cannot: after `clear()` the two are the same absence. Review found that
squarely, and the fix is that nothing is suppressed. §3's rule is uniform over every
completion failure — the call's result stands, the operator is told, the claim stays
open — so the erasure case needs no marker, no generation counter and no precedence
of its own. Erasure still wins, because it is the data-rights act and the other is a
record of it; the residue is one call whose record the user destroyed on purpose, and
recreating the row is the one answer no store may give.

**Extending `clear` rather than adding a second erasure act is what keeps ADR-0021
§4's rule true.** "The user may burn the book; nobody may tear out a page" is a rule
about one book, and two erasure operations over one store would let a user destroy
the executions and keep the rulings, or the reverse — selective erasure with an
extra step. The return value widens as a consequence of the store holding a second
kind; the act does not change.

**One store rather than two is what makes that possible.** A separate invocation
store would have its own `clear`, its own residency clause and its own export, and
the obligation that a data-rights act reach both would be a sentence in a
composition root rather than a property of the contract. It would also put the §1
refusal's referential check across a store boundary, where ADR-0021 §4's "the only
place both records are in hand" stops being true.

### 7. What this changes in other ADRs, clause by clause

Under ADR-0082 §1 a record is owed on an earlier ADR exactly where a named clause
of it fails ADR-0070 §1's test. **Three ADRs do, across four clauses** — ADR-0029
§3 and §5, ADR-0021 §4, ADR-0148 §9. The rest are stacked additions and are listed
so a reviewer can check the showing rather than infer it.

**ADR-0029 §3 — partially superseded, as it reaches cost only.** Its sentence
"**`ToolResult` carries no cost and no disclosure report**, and both omissions are
decisions" is false as to cost after §5 above, and §3 itself calls the omission a
decision rather than an absence, so ADR-0082 §1's test comes out on the record side.
The scope is cost and nothing else: **the disclosure-report half stands**, issue #57
is untouched, and no lane reads this as landing a per-call reach report. §3's
reason — billing is asynchronous, so a `spent` field would hold a number the tool
made up — is answered in §5 rather than waived, and the clause forbidding an invented
number is what answers it. Everything else of §3 stands and this ADR relies on it:
failure returned as data, the three-member `ToolOutcome`, `retryable` on
`ToolFailureKind`, the message rule, and `output` as `FrozenJsonValue`.

**ADR-0029 §5 — partially superseded.** Its closing paragraph rules "An approval is
not consumed by executing it" and that "The answer is **no**, and it is not a
deferral." §1 above makes the answer partly yes on a spendable authorisation. A
reader holding only ADR-0029 would act differently, so it is a supersession and not
an amendment. Everything else of §5 stands verbatim and is relied on by §1: the
derived key and its three properties, the two-part retry conjunction, the two-sided
window obligation, the fail-closed elapsed-time reading, and the refusal to
auto-retry an `INDETERMINATE` outcome or an `Idempotency.NONE` side-effecting tool.

**ADR-0021 §4 — partially superseded.** Its paragraph beginning "It bounds
resolutions, not executions" states what the trail does not hold and defers the
consume to the invocation contract. The trail now holds executions, so the
paragraph's first sentence is false and its deferral is discharged. Its scope
carries `clear`'s widening with it, because that is the same fact — the store holds
a second kind — reaching a second sentence. Everything else of §4 stands and is
relied on throughout: write-once, atomicity, the detached validated snapshot, the
resolution invariant, the no-`delete(id)` rule, the total order, the strictly
positive `limit`, local-only residency and the timezone-aware instant.

**ADR-0016 §7 and ADR-0014 §7 — nothing is owed, and the reason is a fact already
on those documents.** ADR-0016 §7's exactly-once bullet was discharged by ADR-0029
§5, recorded in ADR-0016's own dated note; ADR-0014 §7's bullet is discharged in
its key half by the same note and its `INDETERMINATE`-reconciliation half is left
where it stands by §3 above. No sentence of either section becomes false or
over-wide, so under ADR-0082 §1 there is nothing to record against them.

**ADR-0186 — nothing is owed.** §1's second clause reads "Nothing else is promoted
by **this ADR**", which stays true of ADR-0186 however many methods a later ADR
promotes. Its relay rule — "Neither composes, filters, projects, enriches or
summarises" — is not departed from either: §4's two operations relay a value the
store assembled, which is why §2 puts the join there. §8's clauses are stated over the rows its §1's two operations return; §4
above binds every one of them over those rows unchanged, and grants the transmission
word on a different row kind that ADR-0186 did not decide and does not describe. No
sentence of ADR-0186 becomes false, and its third §8 clause is narrowed only in the
sense that it was always about decisions — §4's clause says so rather than leaving
a reader to work it out.

**ADR-0188 — nothing is owed.** §6's normative clause reserves the question to
#1503 and bars a lane from citing ADR-0188 for it; this ADR answers #1503 and cites
ADR-0188 for nothing of the kind. §7's first clause stays true and is extended by
§4's fourth clause onto a surface that did not exist when §7 was written. §8's gate
is untouched.

**ADR-0034 §1 — nothing is owed, and the showing is worth writing out because the
section enumerates.** Its rule is stated over a *window* rather than over one
exception, and it admits an exit on either of two grounds; §1 above supplies a new
exit on the second ground, by a contract clause of the same kind ADR-0029 §2
supplies for `ToolBindingError`. ADR-0034 §1's sentence "Three exits occupy the
window today" is a count at its own date and is not a closed set — "today" is in
it — and its rule, its two grounds, its refusal of `INDETERMINATE` in that window
and its statement that `ToolInvoker` "exposes no 'the callable was reached' fact
and this ADR introduces none" all stay true. This ADR introduces no such fact on
the seam either: §3's claim is a durable row in a store, not a value returned from
`invoke`, and no executor reads it.

**ADR-0148 §9 — partially superseded, on *where* an attempt's outcome is recorded
and not on *which four* outcomes there are.** Its third clause rules that "The four
outcomes ADR-0017 §3 requires are the step's and no others", and its reasoning gives
the ground: the trail is append-only, so "an outcome that moves from pending to
succeeded **cannot** live there", and the condition is discharged "by joining two
ratified records rather than by adding a third". §2 above puts an outcome on an
audit row. A reader holding only ADR-0148 would look for an attempt's outcome in one
store and find that this system writes it in two, so under ADR-0070 §1 that is a
change to what was decided and it takes a record.

**The scope is one sentence's reach, and three things it could be read to cover are
outside it.** *(a) No fifth outcome.* `ToolInvocation.outcome` is `ToolOutcome` —
ADR-0029 §3's three members, alongside the open claim ADR-0148 §9 itself calls
*pending*. This ADR mints no outcome vocabulary, adds no member to that enum and
states no fifth state. *(b) No outcome moves.* ADR-0148's stated reason bars a row
that transitions; §2 writes two rows and no `update`, so a claim is never rewritten
into a completion and the sentence that supplied the reason stays literally true of
this store. *(c) The attempt identifier does not move.* It is still the step
execution; `PermissionDecision.step_id` is still set on every egress decision; there
is still no egress outside a claimed step; and the reconciliation path is still
ADR-0014 §4's recovery scan. §9's other three clauses are untouched and this ADR
rests on all three.

**What the record says positively is that the outcome is now written twice, and it
says what holds between the two.** §3 supplies that and is where the scope points.
The recovery scan appends the `INDETERMINATE` completion for every claim left open
under the step's `approval_ref`, completions first and the step's transition second,
so the window where a crash strands a record always falls on the re-runnable side.
It does **not** make the two reads identical, and this ADR does not claim it does:
an invocation row may read `SUCCEEDED` or `FAILED` under a step that reads
`INDETERMINATE`, because the seam can write its outcome and die before the plan
records one. What §9 asked for holds in full across that difference — neither
record is inferred from the other's absence, which is §9's own next sentence read
forward onto the second record and is also §3's positive-third-state clause — and
the difference runs in the conservative direction only: the step is the more
ignorant of the pair, never the more confident. Closing it would take a transaction
across two stores, or a scan writing a step's outcome from an audit row, which is
ADR-0014 §4's graph and out of scope (§10).

**Recording it rather than arguing the narrow reading, and the reason is worth
stating.** The narrow reading is available and was held by an earlier draft: under
ADR-0089 §3 unmarked text in a marked ADR determines what a marked clause means and
never supplies an obligation, so "and no others" bars a fifth vocabulary — which
this ADR honours in terms — while "cannot live there" is unmarked prose whose stated
reason is a row that *moves*, which two appends are not. That draft concluded
nothing was owed while calling §9, in the same paragraph, "the clause most at risk
of being read as changed". Holding both is the weak position, and ADR-0070 §1's test
is the decision and not the label. The record costs a status line and a note; being
wrong about it costs a reader who acts on §9 alone, which is the failure ADR-0082 §1
exists to prevent.

### 8. This ADR classified under ADR-0070 §1 and ADR-0082 §1

The header edits this ADR makes to ADR-0021, ADR-0029 and ADR-0148 are
§1-permitted status edits and appended dated notes. No ratified sentence of any of
the three is rewritten; all three documents' Decision text stands unedited and
legible as history beside the pointer here, which is ADR-0070 §2's own treatment of
ADR-0001.

All three lines take the leading `Partially superseded by` token, so `Accepted` is
dropped — the property ADR-0070 §4 makes load-bearing, so that a filter
prefix-matching `Accepted` cannot read a partially-superseded ADR as fully current.
Under ADR-0082 §2 the amendment qualifiers a line already carries come off it in the
same change and stay whole in the dated notes below, which is that section's stated
condition for making the move. ADR-0021's line carried one and ADR-0029's carried
three; ADR-0021's ADR-0148 record already exists as an in-text dated note at the end
of its §1, and ADR-0029's ADR-0031, ADR-0032, ADR-0034 and ADR-0039 records already
exist as dated header notes, so nothing is lost. **ADR-0148's line carries no
qualifier to move** — its own 2026-08-22 amendment is already a separate dated
bullet, which the edit leaves untouched — so on that document the change is the
token and the appended note and nothing else.

The records are written now, while this ADR stands `Proposed`, rather than at
ratification. ADR-0165's exempt flip is one ADR file and one changed line, so a
ratification commit cannot carry them; and the corpus already does it this way —
ADR-0148 recorded on ADR-0021 in its own `Proposed` PR, citing ADR-0044's note
"written the day it merged and ahead of its implementation" as its precedent.

### 9. What the implementing lane owes, and what it is sequenced behind

> **Normative.** The implementing lane lands the `core` surface this ADR names:
> `InvocationLedger` as a triad — Protocol, shared conformance suite and canonical
> fake — together with its primary production implementation, the `permissions`
> store that also satisfies `AuditTrail` (ADR-0137 §2's pairing); the new
> obligations in the existing conformance suites for `AuditTrail`, `ToolInvoker`
> and `AssistantEngine`; and the fakes for each. No lane implements against this
> ADR before it is ratified and merged (ADR-0015 §5).

> **Normative.** The conformance suite for `InvocationLedger` pins the clock at the
> boundary: an exact-window reading, a reading one unit outside it, a reading that
> steps backwards, a repeated reading, and a clock that raises — each producing the
> admission this ADR states. It pins the ordering rule against a backwards clock by
> asserting over append order and not over instants.

> **Normative.** Two writes here run from paths that may themselves be cancelled:
> the claim append, whose outcome §1 requires to be observable before a cancellation
> is propagated, and the completion, which §3 requires on the cancellation and
> deadline exits. The implementing lane owes both a write that survives that path.
> Where the completion cannot be written the claim is left open, which is the honest
> state and not a licence to write a wrong outcome; where the **claim**'s outcome
> cannot be observed, the implementation does not satisfy §1 and the conformance
> suite says so.

> **Normative.** The suite pins the minted `id` at the same boundary: every id
> comes from the injected factory, ids are fresh across two claims under one
> decision and across a claim and its own completion, and the caller completes
> against the row the ledger returned. No test supplies an id and no implementation
> accepts one.

> **Normative.** It pins the translated failures as **classes**: a clock that
> raises, a store that cannot be read and a store that cannot be written each
> surface as an `AuditError` carrying its cause, none escapes as a
> non-`AssistantError`, and none arrives as one of the three named refusals (§2).

> **Normative.** The suite pins the **equality** refusal with the attack §1 names:
> a decision recorded under an id, and a second, structurally different `ALLOW`
> carrying that same id, passed to `claim_invocation` — refused
> `UnrecordedAuthorisationError`, before any append, and indistinguishably from an
> id the store never held.

> **Normative.** It pins ADR-0026 §2's split at this seam in both directions: a
> guard rejection surfaces as `AuditError`, and an exception the clock **callable**
> raises on its own account arrives at the caller **unwrapped**, with its type and
> cause intact.

> **Normative.** Five failure-path tests are owed because five clauses above are
> written against them. **A completion write that fails** leaves the claim open,
> returns the call's own `ToolResult` unchanged, reaches the operator as a
> diagnostic, and makes a spend evaluation over that scope fail closed (§§3, 5).
> **A recovery scan interrupted between two completions** leaves the step
> `RUNNING`; a second scan completes the claim still open and only then commits the
> transition; a third appends nothing (§3). **A crash after the last completion and
> before the step's transition** leaves a completed claim under a `RUNNING` step,
> and the next scan appends nothing and records the step `INDETERMINATE` — the
> divergence §3 states, asserted rather than repaired. **A cancellation delivered
> while an append that then fails is in flight** surfaces the append's failure and
> not the `CancelledError` (§1). **A non-cancellation `BaseException` raised from
> the callable** propagates unchanged, writes no completion, and leaves the claim
> open (§3).

> **Normative.** `ToolInvocation` and `RecordedInvocation` join the promoted set
> `tests/core/test_engine_surface_closure.py` walks, together with the transitive
> closure of what their fields reach (ADR-0085 §5), and every string among them is
> `EncodableText` (ADR-0085 §4c). The lane adds no figure to a comment for either
> count; those checks own them.

> **Normative.** §4's two operations change the promoted surface's **method set**,
> so the implementing lane **bumps `PROTOCOL_VERSION` in the same change**. That is
> ADR-0124 §9's rule in terms — it reaches "any change to the promoted surface's
> method set or to a method's arguments or results (ADR-0085 §3)", and the
> obligation is "on whoever makes the change, in the same change". Without the bump
> a client at the new version and a hub at the old pass the exact-version handshake
> and `recent_invocations` then fails as an unknown method rather than as an
> incompatible peer, which is the failure the handshake exists to prevent. The
> lane's wire tests cover the mixed-version rejection. The lane also applies
> ADR-0124 §9's second limb to `ToolResult.incurred_cost` where that type is
> wire-carried; one bump discharges both grounds.

> **Normative.** The composition root wires one object as both `InvocationLedger`
> and `AuditTrail`, and hands the `ToolInvoker` the ledger alone. A composition that
> hands it the trail is a defect the lane's own test names, in the shape ADR-0029
> §8's pairing test already has.

> **Normative.** The conformance suite exercises the consume under **concurrent**
> invocation rather than assuming a single-threaded caller, as ADR-0021 §4's suite
> does for concurrent resolution and for the same reason.

The lane is sequenced behind the transport-capability lane of this milestone (#85),
which also touches `core/protocols.py`, and ahead of the recipient-policy lane
(#68), which writes the same audit surface. Those two are separate ADRs of this
batch and are referred to here by the issues they answer rather than by number,
because a decision citation naming an ADR file that does not exist is a Tier 1
failure of the citation check (ADR-0088 §6).

**The recipient-policy lane's row is a decision annotation, not an execution row,
and the two do not collide.** That lane populates `PermissionRuling.authorised_by`
and records which of ADR-0148 §3's two bases authorised a recipient — facts about a
**ruling**, carried on a `PermissionDecision`. This ADR's row is the record of an
**act** and carries no basis, no policy, no recipient and no ruling. One store, two
row kinds, and the annotation belongs to the kind that was already there.

### 10. Explicitly out of scope

- **The ceiling itself** — the budget, its period, its currency handling and its
  refusal outcome (§5).
- **Automated reconciliation of an `INDETERMINATE` act**, and any idempotency
  mechanism beyond ADR-0029 §5's derived key (§3).
- **#234's classification change.** The reachability fact becomes durable; what the
  executor does with it is that issue's Protocol decision (§3).
- **Retention** (#108), for either row kind (§6).
- **A richer query surface** over either kind — by tool, by outcome, by window, by
  decision. ADR-0021 §4 defers those "until something asks for it" and nothing here
  asks.
- **Closing #259.** §1 narrows it and says by how much.
- **Any change to `PlanStore`, `StepExecution` or ADR-0014 §4's transition graph.**

## Consequences

- **A user can be told what happened, for the first time.** The listing states that
  a call was entered, what it cost, how it finished, and — on an egress call that
  succeeded — that it was sent. That is #1503's user-visible half, and it is what
  milestone 24's exit could not be ruled on.
- **One approval no longer backs an unbounded number of side-effecting acts.** The
  property ADR-0021 §4 named as absent is now a property of the store, enforced by
  an atomic append rather than by a convention.
- **Every side-effecting call now pays two durable writes**, one before the callable
  and one after, on the same store the decision was already written to. That is a
  real cost on the hot path of every tool call and it is accepted: the write before
  the callable is the consume, and a consume that is not durable before the effect
  is not a consume.
- **The wire protocol version moves.** Two methods join the promoted surface, so
  ADR-0124 §9's rule fires and the implementing lane bumps `PROTOCOL_VERSION` in the
  same change. Every deployed spoke and the hub are upgraded together, which for the
  hop this system is on is two machines upgraded by hand.
- **An id is no longer enough to claim under a decision.** The ledger is passed the
  whole `PermissionDecision` and refuses unless the store holds that same value, so
  a caller that reuses a recorded id for a different `ALLOW` is refused before the
  callable. The cost is one argument and one equality comparison inside the append;
  what it buys is that a `RecordedInvocation` reports the decision the act actually
  ran under.
- **The two records of one attempt can read differently, and the ADR says so rather
  than promising otherwise.** A completion can land and the process die before the
  plan records the outcome, leaving `SUCCEEDED` in the trail under an
  `INDETERMINATE` step. The divergence runs one way — the step is the more ignorant
  — and closing it would take a transaction across two stores or a scan writing plan
  state from an audit row, neither of which this ADR takes.
- **A `ToolInvoker` implementation now holds an `InvocationLedger`.** That is a new
  collaborator on a seam whose whole design was that it holds a registry binding and
  nothing else — the cost #259 priced when it described closing the same hole one
  level up — but it is two append methods and not the audit trail, so no decision
  write, history read or erasure reaches `tools/`.
- **The audit store now needs a clock and an identifier factory.** `recorded_at` is
  stamped, and each row's `id` is minted, where the rule is enforced rather than by
  the party the rule bounds — two new injected collaborators on an implementation
  that had none, and a new failure mode: a clock that will not read refuses the
  claim, so nothing side-effecting executes. That is the fail-closed direction and
  it is chosen deliberately.
- **`ToolResult` gains a field, so every tool implementation may report a cost and
  none must.** The default is `None` and `None` becomes `UNKNOWN` on the row, so a
  tool that never grows the field fails a budget closed rather than silently
  contributing zero. It also reverses one sentence of ADR-0029 §3, which is
  recorded rather than glossed (§7).
- **An `Idempotency.NONE` side-effecting tool now gets exactly one invocation per
  authorisation, enforced by the store.** That is stricter than the trail was and
  exactly as strict as ADR-0029 §5's retry rule already was on the executor; a
  caller that was quietly re-invoking such a tool under one `ALLOW` will now be
  refused, and that refusal is the point.
- **A surface can no longer be written against a bare invocation row.** The store
  pairs each with its tool identity and one egress fact, atomically, because the
  rendering floor cannot be met otherwise and because the pairing has no safe home
  above the store; the engine stays the relay ADR-0186 §1 made it.
- **An audit write can now fail without failing the call**, and that asymmetry is
  deliberate. A completion that will not write leaves an open claim and an operator
  diagnostic, and the tool's own result is returned unchanged — because reporting a
  known-successful side effect as failed is the one outcome worse than an
  incomplete record. The residue is paid at the budget instead: an open claim fails
  a spend evaluation closed (§5), so the next call under that scope is refused
  rather than admitted against a total that quietly lost a price.
- **An honest history has a state that is neither success nor failure, and surfaces
  must render it.** A claim with no completion will be visible to users, and a
  surface that finds it awkward is not permitted to resolve it.
- **The trail becomes the busiest store in the system.** Two rows per side-effecting
  call on top of one per gated action, with no retention rule, makes #108 sharper
  than ADR-0021 §4 left it — and #108's own trade is unchanged, only larger.
- **New `core` surface:** the `InvocationLedger` Protocol with two members;
  `ToolInvocation` and `RecordedInvocation`; `AuthorisationSpentError`,
  `UnrecordedAuthorisationError` and `InvalidCompletionError`, all three under
  `AuditError`; one field on `ToolResult`;
  two read members on `AuditTrail`; two on `AssistantEngine`; and one obligation on
  `ToolInvoker.invoke`. One triad lands, and three existing conformance suites and
  their fakes grow.
- **Revisit when** the budget ADR lands and finds the field named in §5 does not
  answer it; when #234 changes the executor's classification; when a tool contract
  offers a lookup by idempotency key and reconciliation becomes possible; or when a
  second row kind is proposed for this store and §6's one-erasure rule is tested.

## Alternatives considered

**Consume the decision literally — mark it spent, or delete it.** Refused for
ADR-0029 §5's own sentence, "An audit trail whose entries are consumed is not an
audit trail", and because it would break retry exactly as §5 predicted. The design
above spends a permission to append, not a record.

**Put the invocation rows in their own store behind their own Protocol.** Cleaner
typing and no ratified signature widened, and refused on §6's argument: two stores
mean two erasure acts a composition root must remember to pair, and the §1
referential check moves across a store boundary where ADR-0021 §4's "the only place
both records are in hand" stops holding.

**One row written after the call, carrying claim and outcome together.** Cheaper by
one write and refused twice over: it records nothing for the call that died
mid-effect, which is the case worth recording, and it makes the consume impossible
because the refusal must be decided before the effect.

**Two types — a claim type and a completion type — with two listings.** Refused
because the surface has to show them together, so the merge would happen in whoever
rendered them; ADR-0188 §7 names that merge as the tempting shortcut and this design
does it once, in the store, where one order describes both.

**Interleave both row kinds in one listing with an explicit kind discriminator.**
Refused because it requires widening ADR-0186 §1's ratified return type, and because
it puts a decision row and an execution row in one sequence where a renderer will
eventually treat them alike — the failure ADR-0186 §8 and ADR-0188 §7 defend against
from opposite sides.

**Carry the canonical destination set on the invocation row.** Refused as ADR-0184
§2's "second shape that must agree": the set is fixed before the ruling and nothing
in the call moves after it (ADR-0148 §1), so a copy could only ever disagree with
the set the user was shown.

**Spend the authorisation on every tool, not only a side-effecting non-`NATURAL`
one.** Refused because it breaks gated reads, which are invoked repeatedly under one
`ALLOW` today, and because ADR-0029 §5 has already decided which repeats are safe.

**Leave `INDETERMINATE` unspent so the act can be retried.** Refused: it admits a
second act under an approval that may already have sent, which is the double-effect
this ADR exists to prevent, arriving through the one state where nobody can tell.
ADR-0014 §4 already places `INDETERMINATE` outside automatic retry.

**Classify a landed pre-callable cancellation as `FAILED` rather than by
`interrupted_outcome`.** Raised in review, and declined on scope rather than on
merit. The seam does hold the fact that nothing ran, and #234 exists because the
contract does not let it say so — but changing that is a change to ADR-0029 §4's
classification, which #234 names as "a Protocol change … route[d] through a contract
ADR of its own", and doing it here would put this ADR's row (`FAILED`) and the step's
status (`INDETERMINATE`) in disagreement about one attempt unless ADR-0029 §4 moved
with it. §1's shielded append — the half of the finding that is this ADR's — is
adopted in full; the classification is left where #234 put it.

**Hand the `ToolInvoker` the whole `AuditTrail`.** The first draft's shape, and
refused once review named what it hands over: decision writes, history reads, the
whole-trail export and `clear()`, into `tools/`. The architecture map gives that
subsystem integrations, not the permission record, and ADR-0029 §1 already split a
capability by consumer for the same reason. `InvocationLedger` is the two methods
the invoker needs and nothing else.

**Let the caller mint `recorded_at` and have the store enforce the window over it.**
The second draft's shape, and wrong twice: the window would be measured against a
number the bounded party supplied, and "most recent" read over caller instants stops
being a history the moment a wall clock steps back. The ledger stamps, and admission
reads its own append order.

**Have the engine pair each row with its decision.** The second draft's shape for
§4, and refused because it puts an `await` between the two reads with `clear()` able
to land in it — leaving the engine holding rows whose decisions are gone and nothing
to do but drop them, fabricate the identifiers, or fail. The store's own operation
has no gap, and moving the join there restores ADR-0186 §1's relay rule as a bonus.

**Mint an erasure marker so a completion refused after `clear()` can be told from a
corrupt pointer and suppressed.** Refused: after `clear()` the two are the same
absence, so the distinction would be a value invented to be trusted. Nothing is
suppressed instead — one uniform rule over every completion failure (§3), which
needs no marker.

**Carry an `attempt` ordinal on the claim.** Refused after review found no safe
allocator, and it is not the same question as the row `id` §2 settled on. A
caller-minted ordinal races — two concurrent claims both compute 1. A store-minted
one differs from a store-minted id in the way that matters: an id is a fresh value
that depends on nothing, where an ordinal has to be **counted from the other rows
under that decision**, which puts a read of the store's own history inside the one
atomic append the consume depends on. It also buys nothing now that the ledger
returns the stored row and §1 bounds a spendable authorisation to one claim plus
retryable `KEYED` retries inside a single window. §2 says what replaces it: the
claims themselves, in the ledger's own order.

**Let any `FAILED` completion admit a further claim.** The first draft's rule, and
looser than ADR-0029 §5's retry conjunction, which forbids repeating a side-effecting
`Idempotency.NONE` call "whatever the failure kind" and a `KEYED` one past its
window. A consume looser than the rule it is meant to enforce is not a consume; §1
transcribes the conjunction instead, which is why the row carries `failure_kind`.

**Defer the engine surface, as ADR-0188 §7 deferred its own.** Refused because that
deferral rested on the record being a file in the data directory legible without the
system; these rows are in a Tier 1 store only the hub opens, so deferring the
surface would leave the record unreachable by the user it is for.
