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
  classes. Because the promoted surface's method set changes, the group that lands
  §4's two operations also **bumps `PROTOCOL_VERSION` in that same change**
  (ADR-0124 §9; §9 below, which splits the work into a paired lane and three
  consumer groups under ADR-0137 §4).
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
> wrapped by `checked_clock` (ADR-0026), and no caller supplies it. It takes
> **exactly one guarded reading per append**, and that one reading is both the
> instant the admission rules above are decided on and the instant stored on the
> row. Two readings would let a retry be admitted at `t+9s` inside a ten-second
> window and stamped at `t+11s` outside it, so the row would then disagree with the
> rule that admitted it — and a reader auditing the window against the stored
> instants would find a claim this store admitted and cannot justify. Any reading of
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

> **Normative.** **Every `AssistantError` the claim append raises** — either
> refusal above, an argument fault, the guard's rejection of a clock reading, a
> store that will not write — is an exit **before the callable is entered**, always,
> and that is a clause of this contract rather than a property of an
> implementation. Each is therefore an exit in the window ADR-0034 §1 governs,
> qualifying on that section's **second** ground — "The contract says the exit
> precedes the callable" — exactly as a `ToolBindingError` does. The executor
> commits `RUNNING → FAILED` and never retries, on the window and not on a list of
> causes.

> **Normative.** **No `Exception` leaves `invoke` from the claim path as a
> non-`AssistantError`, and none of the named refusals is wrapped.** An
> `AssistantError` escaping the claim append leaves `invoke` **unchanged** —
> `AuthorisationSpentError` and `UnrecordedAuthorisationError` as the clause above
> requires, an `AuditError` the ledger translated likewise — because §2's exhaustive
> refusal orders would mean nothing if a caller could not catch the class they name.
> Only an exception that is **not** an `AssistantError` is translated, and then to an
> `AuditError` carrying it as the cause. That reaches **any** exception outside
> `AssistantError`, whatever its class, because ADR-0026 §2 lets a clock callable
> raise anything and §2 above preserves that: a `ValueError`, a `RuntimeError` and a
> third-party client's own error class are one case here and are translated alike.
> What the rule turns on is the class boundary and nothing narrower. ADR-0026 §2's split binds the **ledger**,
> which propagates such an exception without relabelling it (§2); `invoke` is one
> frame out and a consumer rather than a guard, which ADR-0034 §2 is the precedent
> for. Either way what reaches the caller is an `AssistantError`, so the clause above
> reaches it and ADR-0034 §1's second ground classifies the step `FAILED`. The type is destroyed nowhere: it survives on the
> cause chain and as the diagnostic's fault class (§3). ADR-0034 §2 is the precedent
> for a consumer that acts on a callable's failure, and the alternative is a
> `RuntimeError` from a wired-wrong clock leaving a step `RUNNING` until a recovery
> scan makes it `INDETERMINATE` — a provably pre-callable exit recorded as an act
> that may have run, which is the misclassification ADR-0034 §1 exists to refuse.
> The narrowing is what keeps both properties at once: the named refusals stay
> catchable by the class §2 promises, and no exit from the claim append leaves the
> executor without a rule.

> **Normative.** That clause is stated over the `AssistantError` classes §2 names
> and the exceptions the paragraph above translates into one, and it reaches nothing
> else. It does **not** reach a `BaseException` — a `KeyboardInterrupt`, a
> `SystemExit`. This ADR asks the executor to derive **nothing** from those: it
> states no outcome for them, ADR-0029 §3's "`BaseException` propagates unchanged"
> stands, and ADR-0034's own treatment of them is untouched.

> **Normative.** The exclusion is deliberate and is not a gap left open. Such an
> exception carries no marker saying which side of the callable it came from, so a
> clause obliging the executor to tell a clock's `KeyboardInterrupt` from the
> callable's would oblige it to read a fact nothing exposes; minting that marker is
> a change to what `invoke` says about reachability, which ADR-0034 §1 declines
> ("exposes no 'the callable was reached' fact and this ADR introduces none") and
> which #234 owns. What the **store** records still tells the two apart, which is
> the whole point of this ADR: a `BaseException` before the claim leaves no row, and
> one after it leaves an open claim (§3).

> **Normative.** A `CancelledError` is the one class where that reasoning does not
> apply, and the clauses below treat it separately for that reason. It is resolved by
> **`invoke`**, which knows which callable it awaited and already holds the
> `Task.cancelling()` count, and never by the executor, which does not. So nothing
> is asked of a party that cannot answer, and no marker is minted for one.

> **Normative.** The claim append is performed so that its outcome is **observable
> before any cancellation is propagated**: a cancellation delivered while the append
> is in flight is absorbed, the append's result is observed, and the cancellation is
> then re-raised. This is the treatment ADR-0034 §1 already gives the executor's own
> claim — "a cancellation absorbed while the **claim itself** was in flight, where
> the write is known to have landed" — transcribed to this one, and it is what makes
> the "claim landed or did not" question answerable at all under ADR-0060.

> **Normative.** An external cancellation is **delivered onward whatever the append
> did**. Where the append failed and a cancellation is pending, `invoke` re-raises
> the `CancelledError`; it does not raise the append's failure in its place, and it
> converts the cancellation into nothing. ADR-0060 §1's propagation clause,
> ADR-0034 §1's treatment of an absorbed cancellation and ADR-0029 §4's
> classification are unchanged by this ADR and none of them is superseded.

> **Normative.** The append's failure is not lost by that. It is attached to the
> propagating `CancelledError` as its cause, and it reaches the operator as the
> Tier 2 diagnostic §3 requires of every audit-write failure, under that section's
> enumerated-fields bound. No claim landed, so
> the trail records nothing — which is the true thing to record — and this ADR gives
> the seam no returned reachability fact and the executor no new rule to apply.

> **Normative.** A `CancelledError` the **claim path's own collaborator** raises —
> the ledger's clock, its store — where **no external cancellation is pending** is
> not a cancellation of this call and does not leave `invoke` as one. `invoke` raises
> an `AuditError` carrying it as the cause, on the pre-callable path this section
> already defines, so ADR-0034 §1's second ground classifies the step and no retry
> follows. No callable was entered, no claim landed, the trail records nothing, and
> the diagnostic §3 requires is emitted.

> **Normative.** The discriminator is the one the seam already computes and no new
> fact: ADR-0031 §2's `Task.cancelling()` **delta**, captured before the collaborator
> is awaited and read as an *increase*, never as a truth value — that section spells
> out why the boolean reading fails, and one of its two named failures is exactly
> this one, "a tool's invented `CancelledError` … promoted to an external
> cancellation on the strength of something that happened before the seam was
> entered".

> **Normative.** **The delta carries no provenance, and no clause here may say it
> does.** ADR-0031 §2 states the limit in terms — `cancelling()` "is a count of
> requests, not a record of who made them, and CPython exposes nothing else" — and
> names the manufactured case: a collaborator that cancels its own invoking task,
> catches the result and raises can move the count with nothing outside having
> cancelled anything. This ADR inherits that limit whole and closes no part of it.
> What the two branches actually turn on is therefore stated exactly: an **unmoved**
> count means no cancellation request reached this task during the call, and an
> **increased** count means one did, from a party the count cannot name.

> **Normative.** Where the count increased, the `CancelledError` propagates
> untouched. That is the **fail-safe** branch and it is chosen because it is safe,
> not because provenance was established: ADR-0031 §2 already accepts the same trade
> one collaborator over, on the ground that the misreading "fails in the safe
> direction" — an interrupted-call classification for a call that may have finished,
> rather than a success reported for one that was cancelled. ADR-0060 §1's
> propagation clause is satisfied whenever there is any doubt, which is what this
> branch guarantees.

> **Normative.** The mirror residue is inherited too and is named rather than
> papered over: a collaborator that calls `uncancel()` can zero the delta and hide a
> genuine external cancellation, at which point the clause above absorbs one it
> should have delivered. That is exactly ADR-0031 §4's declared limit (#189), one
> collaborator over — **not closed here, not made worse here**, and reaching an
> injected clock or store only where it reaches an integration's callable already.

> **Normative.** This is ADR-0029 §4's own rule applied one collaborator over, not a
> new one. That section reserves propagation for "a cancellation delivered from
> outside" and makes an invented one an ordinary failure — "anything else escaping
> the callable is an exception like any other" — and ADR-0031 §2 names the invented
> case in terms as `INTERNAL`. **Nothing new crosses the seam:** what changes is the
> *class* `invoke` raises, which its contract already enumerates. The executor is
> untouched, keeps its standing rule that a `CancelledError` leaving `invoke` is an
> interrupted call, and is simply no longer handed one for a call that was never
> cancelled. The reachability fact ADR-0034 §1 declines is still not minted, and
> #234's residue is unchanged.

> **Normative.** Where a `CancelledError` **does** leave `invoke` — an external
> cancellation delivered while the append was in flight, or one the clauses above
> propagate on an increased count — the step's outcome is whatever
> `ToolDefinition.interrupted_outcome` already computes for a cancellation
> (ADR-0029 §4), which may be `INDETERMINATE` for a call that provably did not run.
> This ADR does **not** change that, exactly as it declines to change it for the
> cancellation cases #234 already owns.

> **Normative.** That clause governs **only** the cases where a `CancelledError`
> leaves `invoke`, and is stated that way because an earlier draft left it
> unqualified beside the new one. Where the collaborator's cancellation was absorbed
> and an `AuditError` left instead, `interrupted_outcome` is never consulted: the
> step is `FAILED` on ADR-0034 §1's second ground and can be nothing else. The two
> clauses partition the claim path's exits and no exit falls under both.

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

**An earlier draft let a failed append outrank a pending cancellation, and it was
wrong on three ratified clauses at once.** The reasoning was that an append which
did not land proves nothing ran, so reporting `CancelledError` — classified by
`interrupted_outcome`, possibly `INDETERMINATE` — records an act that may have
occurred for a call that could not have. The observation is right and the remedy
was not. ADR-0060 §1 rules that a cancellation from outside "is delivered onward,
never absorbed" and that a method "never converts such a cancellation into a return
value"; raising a different exception in its place is that conversion by another
route. ADR-0034 §1 gives the absorbed cancellation precedence over a competing
failure in this very window, and ADR-0029 §4 owns the classification. Three
supersessions to buy a distinction the **store already makes**: no claim landed, so
there is no row saying an act may have occurred, which is the durable half #234
asks for and the half this ADR can give. The step's `INDETERMINATE` in that case is
the residue #234 exists for, and this ADR narrows it and leaves it, as it says
everywhere else that it does.

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
> `completes`, `outcome` and `incurred_cost` all set, and `failure_kind` set **only
> where `outcome` is not `SUCCEEDED`** — where it may be set and may be absent.
> `completes` is the discriminator.

> **Normative.** `INDETERMINATE` carries a kind on the same terms as `FAILED`, and
> the row does not drop it. ADR-0029 §3's `ToolResult` validator **requires** a
> `ToolFailure` on every result that is not `SUCCEEDED` — "when it is FAILED or
> INDETERMINATE and `failure` is None" is a rejection in terms — so a keyed
> side-effecting call that timed out arrives at this seam carrying `TIMED_OUT`, and a
> row that refused to hold it would either fail validation and leave the claim open
> or discard a kind the seam was handed. ADR-0039 already settled the same question
> one layer up when it made a tool-reported failure "land durably on an INDETERMINATE
> step too, by value — kind and message unedited"; this row takes the kind and not
> the message, because §2 carries no content.

> **Normative.** A `failure_kind` is **transcribed from the `ToolResult` that
> carried one and is never synthesised**. So a completion derived from a
> `ToolResult` carries that result's kind, whichever of the two non-`SUCCEEDED`
> outcomes it holds; and a completion derived from an **exception** — a cancellation
> ADR-0029 §4 classifies through `ToolDefinition.interrupted_outcome`, which may
> compute either `FAILED` or `INDETERMINATE` — carries **none**, because no
> `ToolResult` was produced to transcribe from. That is why the shape above permits
> a kindless completion rather than requiring a kind, and why it permits one on both
> outcomes rather than on neither.

> **Normative.** No lane fills that absence. ADR-0031 §3 rules that "The seam never
> synthesises" `CANCELLED`, and no other member of `ToolFailureKind` describes an
> externally delivered cancellation: `TIMED_OUT` is a deadline the seam owns,
> `REFUSED` is an upstream declining, `UNAVAILABLE` is one that could not be
> reached. Writing any of them here would be the seam inventing a cause, which is
> the failure ADR-0031 §3 corrected. The absence is the honest value and it is
> readable as one: a completion with no kind is a non-success this system observed
> without a reported cause.

> **Normative.** A kindless `FAILED` therefore **admits no further claim** under
> §1, whose conjunction requires "a recorded `failure_kind` whose `retryable` is
> true". A cancelled act is not auto-retried, which is the direction ADR-0029 §5 and
> ADR-0014 §4 already take, and it falls out of the rule rather than needing a
> clause of its own. An `INDETERMINATE` completion, kind or no kind, is refused by
> §1's completed-outcome arm before the conjunction is reached, so the kind it now
> carries changes nothing about what may follow it — it is recorded because the seam
> was handed it, not because anything reads it to decide a retry.

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
> cause where it has one. A consumer catching `AuditError` catches every failure a
> ledger member **owns** — every refusal above, and every failure it translates at
> this boundary. It does **not** catch an exception the clock callable raises on its
> own account, which §2's split propagates unwrapped and which is by construction
> not the ledger's to classify; a consumer that must survive one catches it by its
> own type, as it would from any other injected callable.

> **Normative.** `claim_invocation` refuses in this order and no other: `AuditError`
> where an argument is not valid; `UnrecordedAuthorisationError` where the store
> holds no decision under that id, where the stored decision is not equal to the one
> passed, or where the stored decision's ruling outcome is not `ALLOW`; then
> `AuthorisationSpentError` where §1's consume refuses. The three grounds of the
> second are one class deliberately: they are all "the authority this call claims is
> not one this store recorded", and separating them would tell a caller which half
> of a forgery was detected.

> **Normative.** `complete_invocation` refuses in this order and no other:
> `AuditError` where an argument is not valid, which includes a `failure_kind`
> supplied with a `SUCCEEDED` outcome — the one combination the shape above forbids,
> an absent kind being well-formed on either other outcome; then `InvalidCompletionError` where `claim_id` names no
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
> `AuditError`, so a `ToolInvoker` never meets a non-`AssistantError` **the ledger
> itself produced**. An exception **the clock callable itself raises** propagates
> **unwrapped** and does reach the invoker as itself — §1 and §3 say what `invoke`
> does with one on each path, and neither leaves it to an implementation:
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
ADR-0191 has since taken §8's deferred shape for **transport** — an injected
capability a subsystem either holds or does not — and partially superseded that
deferral. This is the same discipline one seam over, on a capability that was never
deferred: the invoker is handed what it must write with and nothing else.

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

> **Normative.** The clause above is `invoke`'s and it is decided by **class, not
> by origin**. Every `Exception` raised on the completion path is a completion
> failure it absorbs — the ledger's own refusals, the `AuditError` it translated,
> and an exception the **clock callable** raised on its own account and the ledger
> propagated unwrapped (§2). Each is surfaced through the diagnostic below, which
> names its fault class; none of them changes what `invoke` returns.

> **Normative.** "By class, not by origin" is exact and has exactly one companion
> rule, stated below rather than folded in here: a `CancelledError` is not an
> `Exception`, so this clause does not reach it, and whether it is absorbed turns on
> the `Task.cancelling()` **count** and not on its class or its origin either. That
> is the one place in this section where a fact outside the exception decides the
> arm, and it is the one place where the exception's class is not evidence of
> anything — a cancellation with nothing cancelled says only that a collaborator
> raised the wrong thing.

> **Normative.** A **`BaseException` that is not a `CancelledError`** raised on the
> completion path while no external cancellation is propagating is not absorbed,
> whatever its class and wherever it arose — a `KeyboardInterrupt` and a `SystemExit`
> alike. It propagates unchanged, the `ToolResult` does not reach the caller, and no
> diagnostic stands in for it: a process being torn down is not a refusal, and
> converting a `KeyboardInterrupt` into a returned result is the conversion ADR-0029
> §3 forbids. The claim is left open by that exit as by any other.

> **Normative.** A `CancelledError` **a collaborator raised** on the completion path
> — the ledger's clock, its store — where the `Task.cancelling()` count is
> **unmoved across the call**, so no cancellation request reached this task at all,
> is not a cancellation of this call, is never read as one, and is **absorbed exactly
> as any other completion failure is**. `invoke`
> returns the call's own `ToolResult` unchanged, the claim is left open, the
> diagnostic is emitted carrying no class (the clause above governs that field), and
> `invoke` attempts no second completion: the obligation is to call
> `complete_invocation` once per claim, and a completion path that failed has
> discharged it.

> **Normative.** It is **absorbed rather than propagated**, and an earlier draft of
> this section had it the other way. Propagating it would discard a `ToolResult` the
> tool had already produced and hand the executor a `CancelledError` for a call
> nothing cancelled, which the executor commits as an interrupted call — a
> known-successful side effect recorded as interrupted, the outcome this section
> calls the one worse than an incomplete record. ADR-0060 §1's propagation clause
> does not reach it: that clause binds a cancellation delivered *from outside the
> call*, and this one was raised inside `invoke`'s own frame by something `invoke`
> awaited. ADR-0029 §4 decides the rest, reserving propagation for the outside case
> and making an invented cancellation an ordinary failure. `invoke` mints no outcome
> from it and does not classify it through `ToolDefinition.interrupted_outcome`; the
> outcome was already decided by the call itself.

> **Normative.** Where the count **did** move, a cancellation request reached this
> task during the call and that cancellation is what leaves `invoke`, by the clause
> below and by ADR-0060 §1. The two cases are told apart by the count and by nothing
> else — never by the exception's class, never by its identity, and never by where in
> the body it surfaced. §1's provenance clauses bind here in full: the count names no
> requester, the moved branch is chosen because it is the safe one rather than
> because provenance was established, and ADR-0031 §4's `uncancel()` residue is
> inherited and not closed.

> **Normative.** No exit ever attempts a second completion for one claim. That is
> stated on its own because three of the arms above are reached *from inside* the
> completion attempt, and a rule phrased as "complete on every exit" could be read
> as re-entering itself.

> **Normative.** Where an **external cancellation is already propagating** and the
> completion path then raises — an `Exception` or a `BaseException` alike — the
> cancellation is what leaves `invoke`. ADR-0060 §1's propagation clause and
> ADR-0034 §1's precedence for an absorbed cancellation decide this and are not
> superseded here. The completion-path exception is attached to it as a cause on the
> exception, and it reaches the operator through the diagnostic below — by fault
> class where it is an `Exception`, and by the operation and outcome alone where it
> is a `BaseException` that is not one. It does not stand in the cancellation's
> place, and the claim is left open as in every other completion failure.

> **Normative.** No such failure is **swallowed**: the implementation surfaces it
> to the operator as a Tier 2 diagnostic, and it is a diagnostic and never a row.

> **Normative.** That diagnostic carries **enumerated fields and no free text**:
> the exception's **fault class**, the ledger operation attempted, and — on a
> completion only — the outcome that was being written. It carries no exception
> instance, no exception message, no `str()` of one, and no member of a cause chain —
> not the ledger's own, and not one an injected callable raised. The exception object
> still preserves its cause (§2); what is bounded here is the **log line**.

> **Normative.** The outcome field is **absent on a claim-path diagnostic**, and its
> absence is required rather than tolerated. A claim carries no `ToolOutcome` — §2's
> shape leaves `outcome` unset on that row — so there is nothing to report, and a
> lane that filled the field would be inventing the one value this ADR is most
> careful never to invent. The **operation** field already says which append failed,
> which is what a reader needs to know why the outcome is missing; nothing else
> stands in for it, and no literal, sentinel or "n/a" is minted for the position.

> **Normative.** The fault class is `core.types.fault_class_of(exception)` and never
> a raw `type(exception).__name__`. A class **name** is as attacker-controlled as a
> message: an injected clock or store can raise
> `type("recipient@example.com", (RuntimeError,), {})()`, and nothing stops a
> dynamically built class from carrying Tier 1 content in the one position the
> clauses above leave open. `fault_class_of` is that hazard already solved, and no
> lane writes a second classifier for it — the conversion is **total**, an
> unrepresentable name becoming `UNREPRESENTABLE_FAULT_CLASS`; the rejected name is
> "dropped here and goes nowhere, log included"; and the `__name__` read is itself
> guarded, so a hostile metaclass takes down neither the diagnostic nor the call.
> This is ADR-0119 §2's rule — no string in the record is derived from data — held
> at one more emitter, with §3's reserved literal as the escape it already minted.

> **Normative.** Where the exception being reported is a `BaseException` that is
> **not** an `Exception`, the diagnostic carries **no class at all** — the ledger
> operation and the outcome, and nothing else. That is `fault_class_of`'s own stated
> rule read forward rather than worked around: its parameter is `Exception` because
> "a cancellation is not a fault and must never be classified as one", so this ADR
> neither widens it, nor classifies such an exception by another route, nor
> substitutes a literal in the field. The operation and the outcome name the fault,
> which is what the diagnostic is for; the class was never the load-bearing part.

> **Normative.** It carries **no identifier**: not the claim's, not the decision's,
> not the step's. `DurableIdentifier` is a non-blank encodable string a caller
> minted, and ADR-0031 §5's neighbouring finding is that a decision id is not
> contractually log-safe — an id reading `recipient@example.com` is a conforming
> value. So the operator gets the class, the operation and the outcome, which name
> the fault, and no lane adds an id "for correlation". A Tier 2 diagnostic that
> could be made to carry a recipient is the ADR-0004 §5 breach this clause exists to
> refuse.

> **Normative.** The bound is ADR-0004 §5's and this ADR does not relax it. A clock
> or a store this system did not write can raise
> `RuntimeError("recipient@example.com")`, and `core/logging.py` redacts by field
> and cannot reach Tier 1 text embedded in a message under an innocuous one. So the
> operator gets the class and the operation — which is what names the fault — and
> the content stays out of the log rather than being trusted to a redactor that
> cannot see it.

> **Normative.** The result of those clauses is a claim left **open**, which is the
> state the clause above governs and which no reader resolves. That is the honest
> record of an act whose outcome this system failed to write down, and it is
> preferred to every alternative that writes a number down instead.

> **Normative.** One case is exempt, and it is exempt because there is nothing to
> leave open: where `clear()` erased the claim, the completion is refused
> `InvalidCompletionError` (§6) and **no claim remains**. Nothing is recreated, and
> the "claim left open" postcondition is not read as an obligation to put one back —
> that would be the store recreating a row the user destroyed on purpose, which §6
> names as the one answer no store may give. Everything else of the clauses above
> holds unchanged: the call's own result stands, and the failure reaches the
> operator as a diagnostic.

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
> so no **rerun** ever attempts a second completion of one, and that is the whole of
> what the ordering buys. A crash after the last completion and before the transition
> costs one scan that appends nothing.

> **Normative.** `clear()` is the one interleaving that does make §2's
> `InvalidCompletionError` reachable here, and the scan is not defeated by it. Between
> enumerating an open claim and completing it, an erasure can remove that claim; the
> completion then refuses exactly as it does for any completion naming no claim (§2,
> §6). That refusal is neither a fault to repair nor a reason to abandon the
> transition — the claim it named no longer exists, so there is nothing left to
> complete, and §6's `clear()` wins here as everywhere. The scan re-reads the open
> claims under that `approval_ref` and proceeds by the rule above: the transition is
> committed once none is open, which after an erasure is trivially so.

> **Normative.** The **re-read** is a property of the rule and not a special case for
> erasure. "Transition only after no claim under that decision is still open" is read
> against the store at the moment of the transition and never against a list
> enumerated earlier; a scan transitioning from a stale enumeration would also
> transition over a claim opened between the two reads. So erasure costs the scan one
> more read of something it had to read anyway, and no marker, generation or resume
> point is minted for it.

> **Normative.** The scan **completes open claims and writes no other outcome.**
> Where it finds claims under that `approval_ref` already completed, it leaves them
> exactly as they stand: it rewrites none, appends no second completion for one, and
> reads none in order to decide the step's transition. ADR-0014 §4's transition
> graph is untouched by this ADR (§10), and a scan that derived a step's outcome
> from an audit row would be changing it.

> **Normative.** The two records therefore answer two questions and **are not
> required to agree**. They can differ in **both** directions and this ADR states
> both rather than one. *(i)* An invocation row reads `SUCCEEDED` or `FAILED` under
> a step that reads `INDETERMINATE`: the seam observed an outcome and wrote it, and
> the process died before the plan could record one. *(ii)* A step reads `SUCCEEDED`
> or `FAILED` over a claim that is still **open**: the completion write failed,
> `invoke` returned the call's own result, and the executor committed the step on
> it.

> **Normative.** In both directions the same three rules hold and are the whole of
> what is guaranteed. Neither record is inferred from the other's absence; neither
> is rewritten to match the other; and no lane, scan or surface is given a rule for
> resolving one from the other. §4's rendering floor renders the row, §5's
> evaluation reads the claim, and ADR-0014 §4 governs the step. An open claim under
> a terminal step is still the positively-read third state of the clause above — it
> is not resolved by the step beside it, and §5 fails the evaluation closed on it
> exactly as if the step were `RUNNING`.

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

**What the order does not buy is that the two records read the same, and two drafts
of this ADR claimed too much about that in turn.** Review found the counter-example
immediately:
a `SUCCEEDED` completion lands, the process dies before the executor commits
`RUNNING → SUCCEEDED`, and the scan then finds a `RUNNING` step with no open claim.
Under ADR-0014 §4 it records `INDETERMINATE`, so the ledger reads `SUCCEEDED` and
the step reads `INDETERMINATE` for one attempt. Closing that would take either a
transaction across two stores, which there is none, or letting the scan write the
step's outcome from an audit row, which is a change to ADR-0014 §4's transition
graph that §10 puts out of scope and that would make the plan store's own
compare-and-swap answerable to a second store. So the clauses above state the
divergence instead, in **both** directions and with the reading each record
supports — which is what ADR-0148 §9's own rule already demands of a pair of
records, that neither be inferred from the other. The second wrong claim was that
the difference always runs one way, with the step the more ignorant. It does not:
§3's own completion-failure path produces the reverse, a step committed on a result
the seam returned while the claim it belongs to is still open, and review found that
eleven lines below the clause asserting otherwise. What survives is the modest
thing, which is also the true one: neither record is guessed from the other, and
each says only what its own writer established.

**Absorbing the clock callable's own exception at `invoke` rather than exempting
it, and the two are a real fork.** Review proposed the exemption: since ADR-0026 §2
has that exception propagate unwrapped from the guard, let it propagate out of
`invoke` too. It is coherent, and it is the wrong half of this ADR's own trade. §3
exists because "reporting a known-successful side effect as failed is the one
outcome worse than an incomplete record", and a clock wired wrong is exactly the
irrelevant fault that should not be allowed to do that — the side effect happened,
the tool said so, and the only thing that failed is the bookkeeping. ADR-0026 §2's
rule binds the **guard**, which must not relabel a callable's failure and destroy
its type; it says nothing about whether a consumer may act on one, and ADR-0034 §2
is the precedent for a consumer that does. So the type survives — as a **fault
class** in the diagnostic, under §3's bound on that field, and intact on the
exception's own cause chain — and `invoke` returns the result the call produced. The
clause is written by **class** rather than by origin for the same reason the
refusal orders are exhaustive over classes: an implementation cannot reliably tell
which side of the guard an `Exception` came from, and a rule it cannot apply is not
a rule.

**The collaborator's own `CancelledError` is absorbed, and this reverses an earlier
draft rather than refining it.** An earlier round had it propagate unchanged, on the
reading that a `CancelledError` is always delivered onward. That reading takes
ADR-0060 §1's propagation clause without its qualifier: "*from outside* is
load-bearing", and the clause is explicitly scoped to a cancellation *delivered from
outside the call*. A clock this system injected, raising inside `invoke`'s own frame
with nothing cancelled, is not that. Two ratified sections already decide the case
the other way — ADR-0029 §4 reserves propagation for the outside case and makes
anything else "an exception like any other", and ADR-0031 §2 names the invented
cancellation in terms and gives the `Task.cancelling()` delta as the discriminator
precisely so it is not "promoted to an external cancellation on the strength of
something that happened before the seam was entered". The delta is a weak signal and
§1 says so — it "carries no provenance", it can be manufactured, and ADR-0031 §4's
`uncancel()` residue can erase it — but it is the signal the seam already has, the
branch it selects on doubt is the propagating one, and the case it decides here is
the one where **no cancellation was requested of this task at all**. Propagating it
also produced
the concrete harm §3 exists to prevent: a `ToolResult` already in hand discarded, and
a successful side effect committed by the executor as an interrupted call. So the arm
is absorbed on the completion path and translated to an `AuditError` on the claim
path, and neither is a new rule — both are ADR-0029 §4's, applied one collaborator
over.

**And it is `invoke` that resolves it, which is why it is not #234's.** The executor
cannot tell a collaborator's cancellation from a caller's, and asking it to would
mint the reachability fact ADR-0034 §1 declines. `invoke` can: it knows which
callable it awaited, and it already captures the `Task.cancelling()` count for
ADR-0031 §2's delta. So the resolution sits where the fact already lives, the
executor's rule is untouched, and nothing new crosses the seam — what changes is the
class of exception `invoke` raises, which its contract already enumerates. #234's
residue is narrowed by exactly one case and otherwise stands (§9).

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
> renders the outcome, the failure kind where the row **carries one**, and the
> incurred cost, **including that the cost is unknown** where
> the basis is `UNKNOWN`. It omits, truncates, summarises, samples and counts in
> place of none of that, and a surface that cannot render one whole renders **fewer
> of them**.

> **Normative.** Where the outcome is not `SUCCEEDED` and the row carries **no**
> `failure_kind` — the cancellation-derived completion §2 permits and forbids any
> lane to fill — the floor is met by rendering **that no kind was reported**. A
> surface renders neither a kind it chose nor a blank, and it does not drop the row
> or the field. This costs no new concept: it is the treatment the clause above
> already gives an unknown cost, the treatment §3 gives an open claim, and
> ADR-0184's positively-read absence — an absence stated as one rather than filled
> or hidden. The floor is therefore satisfiable for every shape §2 admits, which is
> what a floor has to be.

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

> **Normative.** Which adapters render these operations is the surface group's
> (§9), and the rendering floor above binds each that does. This ADR promotes no CLI
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

> **Normative.** **No integration can populate this field yet, and this ADR mints
> no channel by which one could.** `ToolImplementation` returns `FrozenJson` and
> nothing else, and ADR-0029 §1 leaves the callable's shape to `tools/` and "does
> not contract it". So a registered integration reports `None`, the row records
> `UNKNOWN`, and a budget over it fails closed — which is the right interim answer
> and the reason the field is a `ToolCost` rather than a bare number.

> **Normative.** **That gap is not #192's and is not answered by ADR-0032.** #192
> asked for a *failure* transport and is closed; ADR-0032 answers it with
> `ClassifiedToolError`, an exception carrying a `ToolFailure`, and its "What is not
> contracted here" keeps `ToolImplementation`'s `FrozenJson` return type on purpose —
> rejecting both a widened return type and a returned `ToolResult`, the second
> because ADR-0031 §2 will not hand a callable the outcome field. An exception is by
> construction unavailable to a call that **succeeded**, which is the case a cost
> matters for. So nothing carries a successful call's cost today and no ADR owns
> minting one; **#1558** owns it, and it also owes the end-to-end case §9 defers.

> **Normative.** The seam group (§9) therefore proves the **mapping** rather than
> populating it, and the two are not the same claim. `ToolResult.incurred_cost`
> reaches `ToolInvocation.incurred_cost` unaltered where the result carries a figure,
> and a `None` becomes a `ToolCost` whose basis is `UNKNOWN` — both asserted at that
> boundary, which is the seam this ADR decides, and **neither asserted end to end**,
> because the clause above says no integration can supply the figure an end-to-end
> case would need (§9). No lane substitutes `ToolDefinition.cost` at any point on
> that path to make the test pass — §5's third clause forbids exactly that, and a
> test that could be satisfied by the declaration would certify the fiction
> ADR-0016 §4 refused.

> **Normative.** This ADR neither pre-empts the shape #1558 lands nor blocks on it,
> and it forecloses none of the options: a return-side channel narrower than
> `ToolResult`, a figure the seam computes, or a measured per-registration
> declaration. What it fixes is the **destination** — the field on the row and the
> `UNKNOWN` that stands until something reaches it — so that whatever carrier lands
> has somewhere to arrive and the budget ADR has something stable to cite.

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
> `InvalidCompletionError` like any other completion naming no claim, and §3
> governs from there: the call's own result stands and the failure reaches the
> operator. Its open-claim postcondition is the one thing that cannot follow, and §3
> states the exemption in terms — the claim was erased, so **no claim remains** and
> nothing is recreated. No lane mints an erasure marker, a cleared generation, or
> any other value by which the two causes could be told apart.

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
completion failure in the two things that matter — the call's result stands and the
operator is told — so the erasure case needs no marker, no generation counter and no
precedence of its own. What it does need, and what a later round found missing, is
the one sentence saying that a claim the user erased is not put back: §3's
"claim left open" describes a claim that is still there, and reading it as an
obligation would turn a data-rights act into a store that rebuilds what it deleted. Erasure still wins, because it is the data-rights act and the other is a
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

**ADR-0060 §1, ADR-0029 §4 and ADR-0031 §2 — nothing is owed, and the showing
matters because §§1 and 3 look at first like a departure.** They put a collaborator's
own `CancelledError` on a non-cancellation path, which reads as absorbing a
cancellation until the three clauses are read as written. ADR-0060 §1's propagation
clause binds "a cancellation delivered **from outside the call**" and says in terms
that "*from outside* is load-bearing"; a clock this system injected, raising inside
`invoke`'s frame with nothing cancelled, is not one, and every other limb of §1 —
the resource clause, the deferred-delivery clause, the indeterminate-effect clause —
is untouched and relied on. ADR-0029 §4 already rules the same way twice over: it
reserves propagation for the outside case, and it makes anything else escaping "an
exception like any other". ADR-0031 §2 supplies the discriminator and names this very
failure as one of the two the boolean reading produces — an invented `CancelledError`
"promoted to an external cancellation on the strength of something that happened
before the seam was entered". So §§1 and 3 apply those three sections rather than
changing any of them, and no sentence of any becomes false or over-wide.

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
so a crash inside the scan always strands the pair on the side a later scan can
still resolve. It does **not** make the two reads identical and this ADR does not
claim it does: they can differ in either direction — an invocation row reading
`SUCCEEDED` under an `INDETERMINATE` step, where the seam wrote and the process died
before the plan did; or a terminal step over a still-open claim, where the
completion write failed and the call's own result stood. What §9 asked for holds in
full across both — neither record is inferred from the other's absence, which is
§9's own next sentence read forward onto the second record and is also §3's
positive-third-state clause. Closing the gap would take a transaction across two
stores, or a scan writing a step's outcome from an audit row, which is ADR-0014
§4's graph and out of scope (§10).

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

> **Normative.** This ADR is implemented by **one paired lane and three consumer
> groups**, not by a single lane. ADR-0137 §4 binds it: every consumer beyond the
> primary implementation is briefed only after the paired lane has merged, and the
> merged contract text is that brief's authority. An earlier draft of this section
> put all of them in one lane, which would have put substantial new machinery into
> four subsystems at once — the widening ADR-0137 §2 grants is the triad *plus its
> primary implementation* and reaches no further.

> **Normative.** **The paired lane** lands the `core` surface this ADR names —
> `ToolInvocation`, `RecordedInvocation`, the three error classes, and
> `ToolResult.incurred_cost` — with `InvocationLedger` as a triad (Protocol, shared
> conformance suite, canonical fake) and its primary production implementation, the
> `permissions` store that also satisfies `AuditTrail` (ADR-0137 §2's pairing). It
> also lands `AuditTrail`'s two new read members with the store-side join, their
> obligations in that Protocol's existing conformance suite, and its fake, because
> those are the same object and the same store. No lane implements against this ADR
> before it is ratified and merged (ADR-0015 §5).

> **Normative.** **The seam group** (`tools/`) lands `ToolInvoker.invoke`'s new
> obligation and its ledger collaborator, the `ToolResult` → `ToolInvocation`
> mapping, that Protocol's new conformance obligations and its fake, and the
> composition-root wiring §9 requires below — the wiring rides here because this is
> the group that first needs an invoker holding a ledger.

> **Normative.** **The recovery group** (`orchestration/`) lands §3's recovery-scan
> completions and their ordering, and the executor-level test below.

> **Normative.** **The surface group** lands §4's two `AssistantEngine` operations,
> that Protocol's new conformance obligations and its fake, the `PROTOCOL_VERSION`
> bump with its wire tests, and whichever adapters render the rows. These are
> relays and adaptation rather than new machinery, which is why ADR-0137 §4's
> grouping test admits them as one group; that test, and not this list, governs any
> resplit the dispatcher judges necessary.

> **Normative.** The suite asserts **one guarded reading per append**, with a clock
> that advances on every call and a test that fails if the append reads it twice,
> and asserts that the instant the admission was decided on is the instant stored on
> the row.

> **Normative.** The suite proves the diagnostic bound rather than asserting it,
> with a Tier 1 sentinel in **four** hostile positions: an exception message, a
> member of its cause chain, a claim's or decision's **identifier**, and the
> **class name** of a dynamically built exception — the test failing if the sentinel
> reaches the log by any route (§3, ADR-0004 §5, ADR-0031 §5).

> **Normative.** The class-name position is pinned as three cases, because
> `fault_class_of`'s totality is what §3 relies on. A collaborator raising
> `type("<sentinel>", (RuntimeError,), {})()` yields a diagnostic carrying
> `UNREPRESENTABLE_FAULT_CLASS` and not the name; an exception whose `__name__` read
> itself raises yields the same literal and neither takes the diagnostic down nor
> changes what `invoke` returns; and a completion-path `BaseException` that is not an
> `Exception` yields a diagnostic with **no class field at all** (§3). No test
> asserts a raw `type(e).__name__` anywhere on this path.

> **Normative.** It pins the cost **mapping** — the `ToolResult` →
> `ToolInvocation` boundary, which is the part this ADR decides: a `ToolResult`
> carrying a figure maps to `ToolInvocation.incurred_cost` unaltered, a `ToolResult`
> carrying `None` maps to a `ToolCost` whose basis is `UNKNOWN`, and a
> `ToolDefinition.cost` present on the definition appears on **no** row (§5).

> **Normative.** It does **not** pin that path end to end, and no group writes a
> test claiming it does. §5 records that no registered integration can supply a
> figure at all, so a case asserting one traversing the production path would have to
> construct a `ToolResult` past the seam or patch inside it — proving the mapping the
> clause above already pins and proving nothing about the path. The end-to-end case
> is owed by whichever ADR answers **#1558**. This ADR mints no integration-side
> carrier to make it writable here: the callable's shape is `tools/`-internal and
> ADR-0029 §1 declines to contract it, so minting one would be this ADR deciding a
> surface it has no ADR for.

> **Normative.** It pins the **kindless** completion on both outcomes: a completion
> derived from a cancellation ADR-0029 §4 classifies `FAILED` constructs with **no**
> `failure_kind` and admits no further claim under §1, and the `INDETERMINATE`
> branch of the same classification is pinned beside it, kindless too (§§1–2). It
> pins the **kinded** `INDETERMINATE` in the same place: a `ToolResult` whose
> outcome is `INDETERMINATE` and whose `ToolFailure.kind` is `TIMED_OUT` — the shape
> ADR-0029 §3's validator requires and §4's deadline produces — constructs a
> completion carrying that kind, unaltered, and one carrying a kind under a
> `SUCCEEDED` outcome is refused at construction (§2). A **completion clock raising
> `CancelledError` directly**, with no external cancellation pending, is **absorbed**:
> `invoke` returns the call's own `ToolResult` unchanged, the claim is left open, the
> diagnostic carries no class, and no second completion is attempted (§3). The same
> clock raising it while an external cancellation **is** pending propagates instead,
> and the test distinguishes the two by the `Task.cancelling()` count alone (§3).

> **Normative.** Each adapter the surface group writes against §4 is tested on
> **every completion shape §2 admits**, not on `FAILED` alone — a renderer that
> branches on `FAILED` passes a `FAILED`-only test and then crashes or silently drops
> a kind on the others. The cases are `FAILED` with no kind, `INDETERMINATE` with no
> kind, `INDETERMINATE` with a reported kind, and `FAILED` with a reported kind. On
> the kindless two it renders that no kind was reported, renders no kind of its own,
> drops neither the row nor the field, and raises nothing; on the kinded two it
> renders the reported kind exactly and substitutes nothing. The floor is proved on
> the shapes hardest to meet it on, which is the only way a floor is proved at all
> (§4).

> **Normative.** Two tests are owed on the claim path's mirror case, one at the seam
> and one at the **executor**. At the seam: the **claim** clock callable raising
> `CancelledError` with `Task.cancelling()` unchanged leaves `invoke` as an
> `AuditError` carrying it as the cause — **not** as a `CancelledError` — with the
> tool callable never entered and no claim appended (§1). At the executor: the same
> wiring commits the step **`FAILED`** on ADR-0034 §1's second ground and **never**
> `interrupted_outcome`, and the test asserts the step's committed outcome rather
> than the exception type alone, because the exception type is what an earlier draft
> got right while the outcome stayed wrong.

> **Normative.** A third case pins the other side of the discriminator: the same
> claim clock raising `CancelledError` while an external cancellation **is** pending
> leaves `invoke` as the `CancelledError`, the executor commits
> `interrupted_outcome` exactly as it does today, and nothing about ADR-0029 §4's
> classification of a genuinely cancelled call is changed (§1, ADR-0060 §1).

> **Normative.** **#234 is narrowed by this and is not closed.** What §1 removes is
> one way `invoke` could hand the executor a `CancelledError` for a call nothing
> cancelled. What remains is #234's own subject: for a call that *was* cancelled,
> the executor still cannot tell how far it got, so `interrupted_outcome` may compute
> `INDETERMINATE` for a call that provably did not run. That fact is not exposed here
> — ADR-0034 §1 declines it ("exposes no 'the callable was reached' fact and this ADR
> introduces none") and §1 above declines to mint it — and changing that
> classification is a change in `orchestration/` that #234 owns. What the **store**
> records still tells the two apart, which is §1's answer to the same question.

> **Normative.** Four further failure paths are pinned. A **`clear()` landing
> between a claim and its completion** leaves the call's result standing, emits the
> diagnostic, refuses the completion `InvalidCompletionError`, and leaves **no
> claim** — nothing recreated (§§3, 6). A **completion-path clock callable raising
> an `Exception`** is absorbed: `invoke` returns the call's own `ToolResult`, and the
> operator gets the diagnostic and **only** the diagnostic — the fault class, the
> operation and the outcome, asserted field by field, with the test failing if the
> instance, the message or any cause reaches the log. Nothing asserts that the
> exception's own type or cause reaches the operator on this path, because the
> exception is absorbed and no channel carries it: §3's "the exception object still
> preserves its cause" is a statement about the object where one survives, and here
> none does. Cause preservation is pinned on the paths where the object **does**
> propagate — the two below (§3). The **same clock
> raising `KeyboardInterrupt`** is not absorbed: it propagates unchanged and no
> `ToolResult` reaches the caller (§3). **An external cancellation already
> propagating when the completion path raises**, in either class, leaves `invoke` as
> the `CancelledError`, with the completion-path exception as its cause and in the
> diagnostic (§3, ADR-0060 §1).

> **Normative.** The conformance suite for `InvocationLedger` pins the clock at the
> boundary: an exact-window reading, a reading one unit outside it, a reading that
> steps backwards, a repeated reading, and a **non-conforming** reading the guard
> rejects — each producing the admission this ADR states. It pins the ordering rule against a backwards clock by
> asserting over append order and not over instants.

> **Normative.** Two writes here run from paths that may themselves be cancelled:
> the claim append, whose outcome §1 requires to be observable before a cancellation
> is propagated, and the completion, which §3 requires on the cancellation and
> deadline exits. The paired lane owes both a write that survives that path.
> Where the completion cannot be written the claim is left open, which is the honest
> state and not a licence to write a wrong outcome; where the **claim**'s outcome
> cannot be observed, the implementation does not satisfy §1 and the conformance
> suite says so.

> **Normative.** The suite pins the minted `id` at the same boundary: every id
> comes from the injected factory, ids are fresh across two claims under one
> decision and across a claim and its own completion, and the caller completes
> against the row the ledger returned. No test supplies an id and no implementation
> accepts one.

> **Normative.** It pins the translated failures as **classes**: the guard's own
> rejection of a non-conforming reading, a store that cannot be read and a store
> that cannot be written each surface as an `AuditError` carrying its cause, none
> escapes as a non-`AssistantError`, and none arrives as one of the three named
> refusals (§2). A clock **callable** that raises is not among them — it is the
> unwrapped case of the clause below, and the two obligations are named apart here
> because an earlier draft ran them together and asked one exception for two
> incompatible shapes.

> **Normative.** The suite pins the **equality** refusal with the attack §1 names:
> a decision recorded under an id, and a second, structurally different `ALLOW`
> carrying that same id, passed to `claim_invocation` — refused
> `UnrecordedAuthorisationError`, before any append, and indistinguishably from an
> id the store never held.

> **Normative.** It pins ADR-0026 §2's split **at the ledger boundary** in both
> directions: a guard rejection surfaces from a ledger member as `AuditError`, and an
> exception the clock **callable** raises on its own account leaves that member
> **unwrapped**, with its type and cause intact and nothing relabelled. It pins
> `invoke`'s own exit separately, because the two boundaries answer differently and
> an earlier draft ran them together. On the claim path: an `AuthorisationSpentError`
> and an `UnrecordedAuthorisationError` each reach the caller **as their own class**,
> unwrapped and asserted by class rather than by `AuditError` alone; a
> non-`AssistantError` — the clock callable's `RuntimeError` — reaches the caller as
> an `AuditError` whose `__cause__` is that exception, type intact; and the test
> covers all three in one place, because it is their interaction that an earlier
> draft got wrong (§1). On the completion path none leaves at all, because it is
> absorbed (§3).

> **Normative.** Five failure-path tests are owed because five clauses above are
> written against them. **A completion write that fails** leaves the claim open,
> returns the call's own `ToolResult` unchanged, reaches the operator as a
> diagnostic, and makes a spend evaluation over that scope fail closed (§§3, 5) —
> asserting the **terminal step** beside the open claim, which is §3's second
> divergence direction and not an anomaly the test may skip.
> **A recovery scan interrupted between two completions** leaves the step
> `RUNNING`; a second scan completes the claim still open and only then commits the
> transition; a third appends nothing (§3). **A crash after the last completion and
> before the step's transition** leaves a completed claim under a `RUNNING` step,
> and the next scan appends nothing and records the step `INDETERMINATE` — the
> divergence §3 states, asserted rather than repaired. **A cancellation delivered
> while an append that then fails is in flight** reaches the caller as
> `CancelledError` carrying the append's failure as its cause, and the task ends
> cancelled — the append failure never stands in its place (§1, ADR-0060 §1). **A
> non-cancellation `BaseException` raised from the callable** propagates unchanged,
> writes no completion, and leaves the claim open (§3).

> **Normative.** `ToolInvocation` and `RecordedInvocation` join the promoted set
> `tests/core/test_engine_surface_closure.py` walks, together with the transitive
> closure of what their fields reach (ADR-0085 §5), and every string among them is
> `EncodableText` (ADR-0085 §4c). The paired lane adds no figure to a comment for
> either count; those checks own them.

> **Normative.** §4's two operations change the promoted surface's **method set**,
> so the **surface group** — the one that lands them — **bumps `PROTOCOL_VERSION` in
> that same change**. That is
> ADR-0124 §9's rule in terms — it reaches "any change to the promoted surface's
> method set or to a method's arguments or results (ADR-0085 §3)", and the
> obligation is "on whoever makes the change, in the same change". Without the bump
> a client at the new version and a hub at the old pass the exact-version handshake
> and `recent_invocations` then fails as an unknown method rather than as an
> incompatible peer, which is the failure the handshake exists to prevent. That
> group's wire tests cover the mixed-version rejection, and it also applies
> ADR-0124 §9's second limb to `ToolResult.incurred_cost` where that type is
> wire-carried; one bump discharges both grounds. `ToolResult` gains its field in the
> paired lane, so a bump is owed at the surface group whether or not the field
> reached the wire earlier — ADR-0124 §9's obligation is on whoever moves the set.

> **Normative.** The composition root wires one object as both `InvocationLedger`
> and `AuditTrail`, and hands the `ToolInvoker` the ledger alone. A composition that
> hands it the trail is a defect the seam group's own test names, in the shape
> ADR-0029 §8's pairing test already has.

> **Normative.** The conformance suite exercises the consume under **concurrent**
> invocation rather than assuming a single-threaded caller, as ADR-0021 §4's suite
> does for concurrent resolution and for the same reason. It exercises the
> **completion** invariant the same way: two coroutines completing one open claim
> must produce exactly one appended completion and one `InvalidCompletionError`,
> never two rows. §2 makes both members decide every refusal inside the same atomic
> operation as the append, so an implementation that separates the check from the
> write fails the contract — and only a racing test finds that, exactly as ADR-0021
> §4 found it for two resolutions of one `CONFIRM`.

> **Normative.** That race is **parameterised by spendability**, because the
> one-winner assertion alone is satisfied by an implementation that consumes every
> `ALLOW` — which would refuse the second gated read and the second `NATURAL`
> invocation that §1 says are never refused on this ground. Two coroutines claiming
> under a **spendable** decision produce exactly one appended claim and one
> `AuthorisationSpentError`. Two claiming under a decision that is **not**
> side-effecting, and two under one whose `idempotency` is `NATURAL`, each produce
> **two appended claims and no refusal**. The non-spendable arms are the half a
> one-winner test cannot see, and omitting them is how a store silently becomes a
> lock on reads.

> **Normative.** The racing suite also exercises the **join against `clear()`**,
> because that race is the reason §2 puts the join inside one store operation. Under
> a barrier, `recent_invocations` and `export_invocations` each run against a
> concurrent `clear()`, and each must return either the complete pre-clear snapshot
> or the empty post-clear one — never a row without its decision, never a row whose
> `tool` or `capability` was read from a decision the erasure had already removed,
> and never a raised error standing in for either answer. An implementation that
> reads rows and decisions in two operations passes the claim and completion races
> above and fails this one, which is the point of testing it: the two-read
> implementation is the natural one, and only this race distinguishes it.

> **Normative.** `clear()`'s **returned count** is pinned over both kinds, on a
> store holding a decision, a claim and a completion: the call returns **3** and the
> store is then empty by every read this ADR names. Asserting emptiness alone leaves
> a store free to erase all three and report the decision-only count it returned
> before this ADR, which every race above still passes; the count is what the caller
> is shown, so it is what the suite checks (§6).

> **Normative.** The **writes** race `clear()` as well, and this is a different test
> from the one above rather than a restatement of it: an implementation may
> synchronise erasure and appends differently, validate a decision or an open claim,
> let the erasure land, and then append a row into a store emptied after the check
> that admitted it. Under a barrier, `claim_invocation` and `complete_invocation`
> each run against a concurrent `clear()`. The store ends **empty**, and each write
> ends one of exactly two ways: it landed before the erasure and was erased with
> everything else, or it was refused after it — `UnrecordedAuthorisationError` for a
> claim whose decision the store no longer holds, `InvalidCompletionError` for a
> completion whose claim it no longer holds. **No row survives the erasure and no row
> is appended after it.** §6's `clear()` wins over a write in flight as much as over
> one already written, and only this race shows whether an implementation agrees.

> **Normative.** The recovery scan's own interleaving with `clear()` is pinned
> beside them: an erasure landing between the scan's enumeration and its completion
> leaves the completion refused `InvalidCompletionError`, the scan re-reading, and
> the step's transition committed — never the scan abandoning the step in `RUNNING`
> and never a completion recreated over an erased claim (§3, §6).

The paired lane is sequenced behind the transport-capability lane of this milestone —
**ADR-0191**, ratified and merged while this ADR was in review, which also touches
`core/protocols.py` — and ahead of the recipient-policy lane (#68), which writes the
same audit surface. ADR-0191 is cited by number because its file is now on `main`;
the recipient-policy lane is still referred to by the issue it answers, and the
budget lane by what it decides, because a decision citation naming an ADR file that
does not exist is a Tier 1 failure of the citation check (ADR-0088 §6) and neither
has merged.

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
- **One approval no longer backs an unbounded number of acts on a *spendable*
  authorisation** — side-effecting and not `NATURAL` (§1). The property ADR-0021 §4
  named as absent is now a property of the store for those, enforced by an atomic
  append rather than by a convention. A side-effecting `NATURAL` tool and a gated
  read are untouched: their authorisations are not spendable and back as many
  invocations as the pipeline needs, which is ADR-0029 §5's own discriminator and
  deliberate.
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
- **The two records of one attempt can read differently, in both directions, and
  the ADR says so rather than promising otherwise.** A completion can land and the
  process die before the plan records the outcome, leaving `SUCCEEDED` in the trail
  under an `INDETERMINATE` step; and a completion write can fail while the call's
  own result stands, leaving a terminal step over an open claim. Closing either
  would take a transaction across two stores or a scan writing plan state from an
  audit row, neither of which this ADR takes.
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
  none must — and for now none can.** `ToolImplementation` returns `FrozenJson`, so
  until #1558's carrier lands, every registered tool reports `None`, every
  row records `UNKNOWN`, and a budget over them fails closed. That is the honest
  interim state rather than a silent zero, and it is why the field is a `ToolCost`
  and not a number. The contract lands now because the ceiling ADR needs something
  stable to cite (§5). It also reverses one sentence of ADR-0029 §3, which is
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
- **A cancellation nothing requested no longer leaves the seam as a cancellation.**
  A ledger clock or store raising `CancelledError` on its own account, with the
  `Task.cancelling()` count unmoved, becomes an `AuditError` before the callable and
  is absorbed after it — so the executor is never handed a `CancelledError` for a
  call nothing cancelled, and a successful side effect is never committed as an
  interrupted one. Nothing new crosses the seam and the executor's own rule is
  unchanged; what changes is which class `invoke` raises. It narrows #234 by one
  case and closes none of it.
- **An audit write can now fail without failing the call**, and that asymmetry is
  deliberate. A completion that will not write leaves an open claim and an operator
  diagnostic, and the tool's own result is returned unchanged — because reporting a
  known-successful side effect as failed is the one outcome worse than an
  incomplete record. The residue is paid at the budget instead: an open claim fails
  a spend evaluation closed (§5), so the next call under that scope is refused
  rather than admitted against a total that quietly lost a price.
- **An honest history has a state that is neither success nor failure, and surfaces
  must render it.** A claim with no completion will be visible to users, and a
  surface that finds it awkward is not permitted to resolve it. The same holds one
  field down: a cancelled act is a `FAILED` or `INDETERMINATE` row with **no**
  failure kind, because no member of the enum describes one, and §4's floor is met
  by saying that none was reported rather than by choosing one or by hiding the row.
  A kind the tool *did* report is kept on either outcome, because ADR-0029 §3
  requires one on both and ADR-0039 already ruled that it survives the trip.
- **The trail becomes the busiest store in the system.** Two rows per side-effecting
  call on top of one per gated action, with no retention rule, makes #108 sharper
  than ADR-0021 §4 left it — and #108's own trade is unchanged, only larger.
- **This lands as four changes, not one.** ADR-0137 §4 puts every consumer beyond
  the primary implementation in its own follow-on lane, so the contract and the
  `permissions` store merge first and the seam, recovery and surface groups are
  briefed against the merged text (§9). The cost is three extra round trips; what
  it buys is that no single PR carries new machinery in four subsystems.
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

**This is a different case from the collaborator's own `CancelledError`, and the two
are easy to run together.** There, the task was never cancelled at all — the
`Task.cancelling()` count did not move, and §1 raises an `AuditError` rather than
letting a cancellation that never happened leave `invoke`. Here, the task **was**
cancelled from outside; the only question is how far the call got, which is the fact
ADR-0034 §1 declines to expose and #234 owns. The first is decided by a count
`invoke` already holds; the second would need a fact nothing exposes. That is why one
is taken and the other is not.

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
