# 192. An authorisation is spent by the act it authorises, and the trail gains an invocation row

- Status: Proposed
- Date: 2026-08-24
- Partially supersedes: ADR-0029 — §5's closing paragraph, "An approval is not
  consumed by executing it"; §1 below states the scope and what of §5 stands.
  ADR-0021 — §4's paragraph "It bounds resolutions, not executions, and the
  difference is worth being precise about"; §2 below states the scope and what of
  §4 stands.
- **Decides `core/protocols.py` and `core/types.py` surface, and it is a breaking
  change.** Golden rule 5 asks that it be flagged. `AuditTrail` gains three
  members, `AssistantEngine` gains two, `ToolInvoker.invoke` gains an obligation
  and a collaborator, `ToolResult` gains a field, and `core/types.py` gains one
  model and `core/errors.py` one error class. Every structural implementation of
  the two Protocols must grow the new members, and one that does not stops
  satisfying them. It adds no Protocol, so it is not a triad (`CONTRIBUTING.md` →
  "Adding a Protocol"); it grows two existing ones, their shared conformance
  suites and their canonical fakes. ADR-0015 §5 and golden rule 5 put it in its
  own PR, ratified before anything implements against it.
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

> **Normative.** `ToolInvoker.invoke` appends a **claim** to the `AuditTrail`
> immediately before the callable is entered and after ADR-0029 §2's three checks
> have passed, naming the decision the call carries. The append is the consume: it
> is one atomic store operation, and a call whose claim is refused does not reach
> the callable.

> **Normative.** On a **spendable** authorisation the claim is refused where the
> named decision already carries a claim that is open, or a claim completed with
> `SUCCEEDED` or `INDETERMINATE`. A claim completed `FAILED` does not refuse a
> further claim, and is the only completed state that does not.

> **Normative.** A refused claim raises `AuthorisationSpentError` and returns no
> `ToolResult`. It is a seam fault, never data, and it is never auto-retried. It is
> raised before the callable is entered, so ADR-0034 §1's pre-invocation rule
> classifies the step and this ADR adds no rule to the executor.

> **Normative.** The claim spends the authority to **begin a further act** and
> nothing else. It removes, rewrites, hides, expires or invalidates no recorded
> row; `PermissionDecision.authorises` stays the pure comparison ADR-0021 §1 made
> it, answering identically before and after a claim; and no lane reads a claim as
> a change to what a decision says.

> **Normative.** A retry admitted by ADR-0029 §5's two-part conjunction is not a
> second act. It appends a further claim under the same decision, and it is
> admitted exactly because the preceding claim completed `FAILED`. ADR-0029 §5's
> key derivation, its retry conjunction, its two-sided window obligation and its
> fail-closed elapsed-time reading are untouched and are still what bound
> repetition.

**The discriminator in the first clause is ADR-0029 §5's own.** Its retry rule
permits a repeat when "the tool is not `side_effecting`; or its `idempotency` is
`NATURAL`; or it is `KEYED` **and** the elapsed time since the first attempt of
this call is strictly less than `idempotency_window`" — so the corpus has already
decided which tools a repeat is safe on, and the consume borrows the first two arms
rather than inventing a test. A read gated by ADR-0016 §3 is invoked under one
`ALLOW` as often as the pipeline needs it, and refusing the second read would break
working behaviour to protect nothing. The `KEYED` arm is deliberately **not**
borrowed: a fresh act on a `KEYED` tool would be deduplicated by the tool anyway if
it fell inside the window, and refusing it costs a caller nothing while a window
that has silently lapsed costs a duplicated effect. Refusing is the conservative
direction and it is the one this ADR takes.

**Why this does not falsify either sentence ADR-0029 §5 gave as its reason.** Retry
survives, because the retry path is the `FAILED` arm of the third clause: the
approval still authorises the second attempt, and the transient `UNAVAILABLE` §5
was written about still does not reach the user as a fresh prompt. And the trail is
not consumed, because nothing is consumed: a claim is an **append**, and the sole
thing it spends is a permission to append a second one. What ADR-0029 §5 rejected
was destroying the record of what was authorised; what this ADR adds is a record
of what was performed. The paragraph is superseded because its literal answer —
"no", and "not a deferral" — is now partly yes, which is a change to what was
decided and takes a supersession under ADR-0070 §1 whatever the reasoning behind it
survives.

**Placing the claim immediately before the callable is what keeps two records from
disagreeing, and the placement is load-bearing.** ADR-0034 §1 rules that an attempt
ending "after the claim is committed and before the callable is reached" commits
`RUNNING → FAILED` and is never retried — an exit where nothing could have run. A
claim appended earlier than the callable, at the top of `invoke`, would leave a row
saying an act may have happened for exits that ADR-0034 §1 has already ruled could
not have. Appended where this clause puts it, the two records agree by construction:
before the claim, ADR-0034 §1's window and no invocation row; after it, an act that
may have run and a row that says so.

**The atomicity lives in the trail, and it lives there for ADR-0021 §4's own
reason.** That section put the resolution invariant on `record` "because this is
the only place both records are in hand", and made the append atomic because
"without that the single-use guarantee is a race — two concurrent resolutions of the
same `CONFIRM` each observe no prior resolution, each append, and one user approval
has authorised two executions". The consume is the same guarantee one seam later,
against the same race, and putting it anywhere else would mean a check followed by a
write with an `await` between them. Two concurrent `invoke`s on one decision reach
one atomic append: one claims, the other is refused.

> **Normative.** `AuditTrail.record_invocation` refuses a claim whose named
> decision is not recorded in the trail, or whose named decision's ruling outcome
> is not `ALLOW`. This is the resolution invariant's placement argument applied to
> a second row kind: the check is made where both records are in hand.

**That narrows #259 and does not close it, and the difference is worth stating.**
#259 records that `StepExecutor` "accepts any valid `ToolCall`", so a caller
hand-building an `ALLOW` nobody recorded can have its id committed as a step's
`approval_ref`. Under the clause above such a call cannot **execute**: the claim
names a decision the trail does not hold and is refused before the callable. What
remains reachable is the step claim itself, which is committed before `invoke` is
entered — so a fabricated authority can still open a step, and that step is then
closed `FAILED` by ADR-0034 §1's rule. #259's own analysis says a check placed
after the claim leaves "closing a step that should never have been opened" as the
only available response; that response is ADR-0034 §1's and it is already
specified. The cost this places on implementations is the one #259 priced: a
`ToolInvoker` implementation now holds the `AuditTrail`.

### 2. The invocation row: one row kind, two shapes, and it restates nothing

> **Normative.** `core/types.py` gains `ToolInvocation`, a frozen model with
> `extra="forbid"`, in **exactly two well-formed shapes**, refusing every other
> combination at construction. A **claim** carries `id`, `recorded_at`,
> `decision_id` and `attempt`, and carries none of `completes`, `outcome` or
> `incurred`. A **completion** carries `id`, `recorded_at`, `completes`, `outcome`
> and `incurred`, and carries neither `decision_id` nor `attempt`.

> **Normative.** `attempt` is an integer, strictly positive, and is the ordinal of
> this claim among the claims recorded under its decision, in the order they were
> recorded. `recorded_at` is a timezone-aware instant, rejected at construction
> like every other instant in `core`.

> **Normative.** `outcome` is `ToolOutcome` (ADR-0029 §3). This ADR mints no
> outcome vocabulary of its own, adds no member to that enum, and states no fifth
> outcome. The **pending** state ADR-0148 §9 names is a claim carrying no
> completion, and is not a value of any field.

> **Normative.** The row restates nothing its decision already fixes. It carries no
> `ToolDefinition`, no `parameters_digest`, no `step_id`, no `execution_id`, no
> account, no transport endpoint and no destination. What a call transmitted to is
> the decision's own `EgressBinding.canonical_destination_set`, reached through
> `decision_id`, and no lane copies that set, or any member of it, onto this row.

> **Normative.** The row carries **no content**. Not an argument value, not a
> payload, not a tool's output, not a failure message, and not a digest of any of
> them. ADR-0004 §5 and ADR-0021 §1's payload rule bind here as they bind on a
> decision: what this row is an account of is the *act*.

> **Normative.** A completion names exactly one claim, a claim is completed at most
> once, and `record_invocation` refuses a completion whose `completes` names no
> recorded claim or names a claim already completed. It refuses a completion whose
> `recorded_at` is earlier than the claim it completes; equal instants are
> permitted.

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
already answered — so the last clause is that invariant transcribed onto a second
row kind rather than a new mechanism.

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

**`attempt` is carried rather than derived, and it is the one count worth
carrying.** It is not restated from the decision — it is a fact about the claim —
and it is what makes ADR-0021 §4's unanswerable question answerable: a reader
holding one row knows how many acts preceded it under that authorisation, without
counting rows a bounded page may not contain. It is also the natural expression of
the store's uniqueness constraint, `(decision_id, attempt)`.

### 3. `INDETERMINATE` spends the authorisation, and exactly-once is not landed here

> **Normative.** A claim completed `INDETERMINATE` spends a spendable
> authorisation exactly as `SUCCEEDED` does. No further claim is admitted under it.

> **Normative.** A claim carrying no completion states that the act **may have
> executed**, positively and as its own state. No lane, store or surface reads it
> as `SUCCEEDED`, as `FAILED`, as "did not run", as an omission, or as a row still
> being written.

> **Normative.** `ToolInvoker.invoke` appends the completion on **every** exit it
> observes — a returned `ToolResult`, a raised seam fault, an expired deadline, a
> cancellation — carrying the outcome ADR-0029 §§3–4 already compute for that exit.
> A completion that is not written because the process did not survive to write it
> leaves the claim open, which is the state the clause above governs.

> **Normative.** Where ADR-0014 §4's recovery scan records `INDETERMINATE` on a
> step, the same act appends the `INDETERMINATE` completion for the open claim
> under the decision that step's `approval_ref` names, where such a claim exists.
> Where none exists, it appends nothing: no claim means the callable was never
> entered.

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
> `recent_invocations(*, limit: int = DEFAULT_PAGE_SIZE) -> tuple[ToolInvocation, ...]`
> reads `AuditTrail.recent_invocations`; `export_invocations() -> tuple[ToolInvocation, ...]`
> reads `AuditTrail.export_invocations`. Neither composes, filters, projects,
> enriches or summarises what the trail returns, and neither reads any other store.

> **Normative.** Both return rows ordered by `recorded_at` **descending**, ties
> broken by `id` **ascending**, and `recent_invocations(limit=n)` returns the first
> `n` of the sequence `export_invocations()` returns over the same trail state. The
> order is guaranteed by the engine operation, over a list it has materialised.
> `limit` is refused when it is not an integer, when it is a `bool`, and when it is
> outside `[1, 2**63)` — locally and before any I/O, in every implementation.
> `export_invocations` takes no argument and is subject to ADR-0085 §8c's payload
> limit exactly as `export_decisions` is. There is no `offset`.

> **Normative.** The two row kinds are two operations returning two sequences. No
> operation returns a mixed sequence; no lane widens ADR-0186 §1's return type or
> adds a `ToolInvocation` to what `recent_decisions` or `export_decisions` returns;
> and ADR-0186 §8's clauses bind every row those two operations return, unchanged
> and in full.

> **Normative.** ADR-0188's hub-down egress record is not a `ToolInvocation` and is
> not returned by either operation above. ADR-0188 §7's first clause is read
> forward onto this surface: that record is rendered through no operation this ADR
> decides, is listed among no row of these listings, and is counted in no bound
> stated over them.

> **Normative.** A surface rendering a `ToolInvocation` renders, for every row: its
> kind — claim or completion — the instant it was recorded, and the identifier and
> capability of the `ToolDefinition` carried by the decision the row reaches. For a
> claim it renders the attempt ordinal; for a completion it renders the outcome and
> the incurred cost, including that the cost is unknown where the basis is
> `UNKNOWN`. It omits, truncates, summarises, samples and counts in place of none
> of that, and a surface that cannot render a row whole renders **fewer rows**.

> **Normative.** A surface may render an invocation row **as an execution**, which
> is what the row is. On a **completion whose outcome is `SUCCEEDED`**, for a
> decision whose `egress_binding` is present, a surface may say that the call was
> **sent**. It says this on no other row and in no other state.

> **Normative.** No surface says or implies that anything was **read**, **received**,
> **delivered**, **seen** or **acted on** by any recipient, on any row, in any
> state. `SUCCEEDED` is what the tool reported to the seam and nothing observes
> what happened after that. ADR-0186 §8's third clause is narrowed to decision rows
> and to nothing else; every other bar it states stands over every row of every
> operation, this ADR's included.

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

**"Sent" is the whole point of the exercise and it is granted narrowly.** ADR-0186
§8 barred it because the trail held only rulings: "a resolved `ALLOW` says a call
was permitted and says nothing about whether, or how many times, it ran". That
sentence stays true of a decision row and is now false of nothing, because the word
is granted on a different row — one that *is* an execution, joined to a binding that
fixes where the bytes went. The three words that stay barred everywhere are barred
for a reason no record can lift: nothing in this system observes a recipient. A
tool reporting `SUCCEEDED` reports that its own upstream accepted the call, and a
surface that turned that into "delivered" would be asserting the measurement
ADR-0016 §3 declines to offer, one axis over.

**Deciding the engine surface here rather than deferring it, which ADR-0188 §7 did
for its own record.** That deferral rested on the record being "in the data
directory, is legible without this system, and is copied by the same act that
exports it". Nothing of that holds here: these rows are in a Tier 1 store only the
hub opens, so a user reaches them through the engine or not at all. Leaving the
surface out would land the record and leave #1503's user-visible half exactly where
the milestone-24 ruling found it.

### 5. What the budget ceiling reads

> **Normative.** `ToolResult` gains `cost: ToolCost | None`, defaulting to `None`:
> what **this invocation** actually cost, reported by the tool. `None` states that
> the tool reported no figure.

> **Normative.** `ToolInvocation.incurred` on a completion is that reported value
> where the tool reported one, and a `ToolCost` whose basis is `UNKNOWN`
> otherwise. No lane copies `ToolDefinition.cost` into it, or derives it from the
> declaration by any other route.

> **Normative.** A spend accumulator sums `ToolInvocation.incurred` over
> **completion** rows and reads no other field of any row for that purpose. A
> member whose basis is `UNKNOWN` fails closed, which is ADR-0016 §4's rule for
> `UNKNOWN` and not a new one.

> **Normative.** `incurred` is the price of the invocation. It is never money the
> tool moved, and no lane reads it as a transacted amount (ADR-0016 §4).

> **Normative.** This ADR decides no ceiling, no budget period, no currency
> reconciliation and no refusal outcome. Those are the budget ADR's, and it cites
> the field named above rather than reshaping it.

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

### 6. Data rights

> **Normative.** `ToolInvocation` rows are Tier 1 (ADR-0004 §7), persist **locally
> only** under ADR-0004 §2's residency clause, and are held by the same store as
> the decisions they name. They are append-only and write-once: `record_invocation`
> refuses a duplicate `id`, and there is no `update` and no selective delete.

> **Normative.** `AuditTrail.clear()` erases **both** row kinds and returns the
> count of every row it removed, of either kind. No operation erases one kind and
> leaves the other, and no surface offers one.

> **Normative.** `AuditTrail.export_invocations` and the engine operation above
> discharge ADR-0004 §6's portability obligation for this row kind.

> **Normative.** Every read of this row kind returns a **detached snapshot** — the
> tuple and everything mutable it reaches — as every other `AuditTrail` read does
> (ADR-0018 §3, ADR-0021 §4).

> **Normative.** This ADR mints no retention rule and no TTL. #108's question is
> unchanged and now covers both kinds of row; a rule that expires one kind and not
> the other is not available to the ADR that answers it, because a trail holding
> completions whose claims have expired would misstate what it holds.

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
of it fails ADR-0070 §1's test. Two do. The rest are stacked additions and are
listed so a reviewer can check the showing rather than infer it.

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
promotes. §8's clauses are stated over the rows its §1's two operations return; §4
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

**ADR-0148 §9 — nothing is owed, and this is the clause most at risk of being read
as changed.** The step execution remains the attempt identifier ADR-0017 §3
requires, the four outcomes remain the step's, and the reconciliation path remains
ADR-0014 §4's recovery scan. This ADR adds an audit-trail row for the same attempt;
it does not move the attempt identifier, does not add a reconciliation path, and
does not permit an egress outside a claimed step. §3's fourth clause has the
recovery scan write the completion precisely so the two records say the same thing
rather than two things.

### 8. This ADR classified under ADR-0070 §1 and ADR-0082 §1

The header edits this ADR makes to ADR-0021 and ADR-0029 are §1-permitted status
edits and appended dated notes. No ratified sentence of either is rewritten; both
documents' Decision text stands unedited and legible as history beside the pointer
here, which is ADR-0070 §2's own treatment of ADR-0001.

Both lines take the leading `Partially superseded by` token, so `Accepted` is
dropped — the property ADR-0070 §4 makes load-bearing, so that a filter
prefix-matching `Accepted` cannot read a partially-superseded ADR as fully current.
Under ADR-0082 §2 the amendment qualifiers those two lines already carry come off
the line in the same change and stay whole in the dated notes below them. ADR-0021's
ADR-0148 record already exists as an in-text dated note at the end of its §1;
ADR-0029's ADR-0031, ADR-0032, ADR-0034 and ADR-0039 records already exist as dated
header notes. Nothing is lost by the move, which is ADR-0082 §2's stated condition
for making it.

The records are written now, while this ADR stands `Proposed`, rather than at
ratification. ADR-0165's exempt flip is one ADR file and one changed line, so a
ratification commit cannot carry them; and the corpus already does it this way —
ADR-0148 recorded on ADR-0021 in its own `Proposed` PR, citing ADR-0044's note
"written the day it merged and ahead of its implementation" as its precedent.

### 9. What the implementing lane owes, and what it is sequenced behind

> **Normative.** The implementing lane lands the `core` surface this ADR names, the
> obligations in the shared conformance suites for `AuditTrail`, `ToolInvoker` and
> `AssistantEngine`, and the canonical fakes in `ai_assistant.testing`. No lane
> implements against this ADR before it is ratified and merged (ADR-0015 §5).

> **Normative.** The completion the third clause of §3 requires is written on the
> cancellation and deadline exits too, which means it is written from a path that
> may itself be cancelled. The implementing lane owes a write that survives that
> path; where it cannot, the claim is left open, which is the honest state and not
> a licence to write a wrong outcome.

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
- **A `ToolInvoker` implementation now holds the `AuditTrail`.** That is a new
  collaborator on a seam whose whole design was that it holds a registry binding and
  nothing else, and it is the cost #259 priced when it described closing the same
  hole one level up.
- **`ToolResult` gains a field, so every tool implementation may report a cost and
  none must.** The default is `None` and `None` becomes `UNKNOWN` on the row, so a
  tool that never grows the field fails a budget closed rather than silently
  contributing zero.
- **An honest history has a state that is neither success nor failure, and surfaces
  must render it.** A claim with no completion will be visible to users, and a
  surface that finds it awkward is not permitted to resolve it.
- **The trail becomes the busiest store in the system.** Two rows per side-effecting
  call on top of one per gated action, with no retention rule, makes #108 sharper
  than ADR-0021 §4 left it — and #108's own trade is unchanged, only larger.
- **New `core` surface:** `ToolInvocation` and `AuthorisationSpentError`, one field
  on `ToolResult`, three members on `AuditTrail`, two on `AssistantEngine`, and one
  obligation on `ToolInvoker.invoke`. No new Protocol, so no new triad; three
  conformance suites and three fakes grow.
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

**Defer the engine surface, as ADR-0188 §7 deferred its own.** Refused because that
deferral rested on the record being a file in the data directory legible without the
system; these rows are in a Tier 1 store only the hub opens, so deferring the
surface would leave the record unreachable by the user it is for.
