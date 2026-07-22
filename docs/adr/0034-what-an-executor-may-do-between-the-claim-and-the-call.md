# 34. What an executor may do between the claim and the call

- Status: Accepted
- Date: 2026-07-22
- Amends on ratification: ADR-0029 §8, with a dated note on ADR-0014. The edits
  to ADR-0029 are **not** made by this change — §4 records their exact form and
  why they wait, following ADR-0026 §6, ADR-0030 §6, ADR-0031 §7 and ADR-0032
  §8. ADR-0014's note **is** applied here, for the reason §4 gives.
- **Not breaking for any consumer.** No Protocol signature moves, no `core` name
  is added or removed, and no legal move is added to ADR-0014 §4's transition
  graph. What changes is which *circumstances* an executor resolves a step from,
  and one sentence of ADR-0029 §8 that was false when it was written. `core/protocols.py`
  is untouched, so golden rule 5's separate-PR requirement is not triggered and
  this merges with its implementation.
- **Decides what first use found underspecified**, in the sense ADR-0018 and
  ADR-0031 both use the phrase: PR #224 built ADR-0029 §8's executor, and the
  question below is the one the ADR does not answer.

## Context

ADR-0029 §8 places the claim before the call — "ADR-0014 §4 already requires the
`→ RUNNING` transition to be committed before the tool is invoked, so the CAS in
§5 is what stops two workers acting" — and then names exactly one thing that can
go wrong afterwards without the tool having run:

> **A raised `ToolBindingError` is committed `RUNNING → FAILED`, and never
> retried.** The claim precedes the call, so a seam rejection arrives *after* the
> step is durably `RUNNING`; letting it propagate uncommitted would strand the
> step until recovery, which would then record `INDETERMINATE` — "we cannot tell
> whether it acted" — about a call that provably never reached the callable. That
> is the one thing `INDETERMINATE` must not be used for, since it is the state
> whose whole meaning is ignorance.

**The window that reasoning describes is wider than the one exception that
occupies it.** Between the committed claim and the callable an executor does
real work — it reads a clock to fix the first attempt's instant (§5), and it
awaits a store write that can itself be interrupted. PR #224's adversarial review
found two ways through that window in which the tool provably never ran and the
step was nevertheless left durably `RUNNING`:

- the claim's own `commit_transition` is an `await`, so a cancellation can land
  while it is in flight, after the write has gone in;
- the clock read that follows it can fail, and ADR-0026 §2 is explicit that an
  exception raised by the clock callable itself propagates unwrapped.

Both end in recovery recording `INDETERMINATE` for a call that never started —
the outcome §8's paragraph above exists to prevent, reached by a route it does
not mention.

**Two review personas then disagreed about the fix, which is why this is an ADR
rather than a commit.** The adversarial persona called both defects blockers. The
architecture persona called the resulting code a new `RUNNING → FAILED` trigger
adopted without an amendment, and called the clock handling a violation of
ADR-0026 §2. Each was partly right, and the parts do not compose into a patch:
one says resolve the step, the other says the resolution needs ratifying. The
tiebreak is the ADR text, and settling it is what this document is for.

**One sentence of §8 is also simply false, and was false on ratification.** §8
says of the `ToolBindingError` case:

> This is the only outcome an executor must derive from an exception rather than
> from a `ToolResult`, which is precisely why it is written down.

§4 of the same ADR mandates a second one, three sections earlier: "an executor
whose invocation is cancelled catches the `CancelledError`, commits the step by
the *same* rule the timeout uses … and then **re-raises**." That is an outcome
derived from an exception and not from a `ToolResult`. The superlative did not
survive its own document. It is the same class of defect as #217 — a claim of
count that the document it appears in contradicts — and it is named here as a
drafting error rather than presented as something this change created.

## Decision

### 1. The pre-invocation rule is about the window, not about one exception

We will state §8's rule over the circumstance it was always reasoning about:

> **Anything that ends an attempt after the claim is committed and before the
> callable is reached commits `RUNNING → FAILED`, and is never retried.**

The reasoning is §8's own, unchanged and merely applied where it already
pointed. Nothing ran. `FAILED` is correct and honest. `INDETERMINATE` is refused
because it is the state whose whole meaning is ignorance, and there is no
ignorance here — the executor knows the callable was not reached, because it
knows it never entered `invoke`, or that `invoke` refused before reaching one.

Three exits occupy the window today and all three take the rule:

- a raised `ToolBindingError` — §8's ratified case, unchanged;
- a cancellation absorbed while the **claim itself** was in flight, where the
  write is known to have landed;
- a failure of the clock read that fixes the first attempt's instant (§2).

**"Never retried" needs no new mechanism**, and that is the point of putting
these together. §8's mechanism already covers them: "retry is scheduled only
from a `ToolResult`, never from an exception", and §5's two conjuncts read
`result.failure.kind`. No exit through this window produces a result, so there
is nothing for a retry decision to be made from.

**The claim's write is shielded, and that is what makes the cancellation case
decidable at all.** ADR-0029 §4 already requires the idiom for the executor's
bookkeeping write — "keep the commit as a task, wait on it through the shield,
absorb any further cancellations while it is still running, and re-raise only
once it has completed" — and applying it to the claim is what tells the executor
whether the claim landed. A cancellation that arrives before it lands leaves no
`RUNNING` to resolve and needs no rule; one that arrives after it lands is
resolved by the rule above. **The cancellation still propagates afterwards**, on
§4's unchanged terms: committing is not swallowing.

**The close runs while another exception is on its way out, so its precedence is
part of the rule rather than an implementation detail.** Two orderings, and both
are chosen against the same test — which fact, if lost, costs more:

- **An absorbed cancellation wins over everything.** ADR-0029 §4's shield idiom
  absorbs repeat cancellations to let a write land, and absorbing one is a
  promise to re-raise it. A teardown the caller cannot observe is worse than a
  diagnosis it loses: the first leaves a task running after shutdown asked it to
  stop, the second leaves a well-recorded step and a worse log line.
- **A rejected close beats the reason for closing**, chained to it. If the store
  refuses the closing write there is nothing further the executor can do about
  the durable record, so the one thing it must not do is report the original
  fault and let the wrong state pass unmentioned — the step is now `RUNNING` in
  exactly the way this section exists to prevent, and a recovery scan will read
  it as `INDETERMINATE` for a callable never reached. Where the reason for
  closing is *itself* a cancellation the first rule already governs, and the
  store failure is logged.

**Why this is not §4's "correct pessimism", which is the reading it is most
likely to be confused with.** §4 says:

> the process can still be killed between the classification and the write, and
> there the answer is ADR-0014 §4's unchanged — recovery finds a durable
> `RUNNING` and records `INDETERMINATE`. For a read that is more pessimistic than
> the `FAILED` this section prescribes, and it is the correct pessimism, because
> **a write nobody can confirm landed** is exactly the ignorance `INDETERMINATE`
> means.

Its premise is stated in that last clause and it does not hold here. The process
was not killed; the executor is alive, holding a claim it *watched land* through
the shield, and it has the information the recovery scan lacks. §4's passage
governs the case where nobody can confirm anything — which remains true and
remains unchanged for a process that dies mid-write. Applying its conclusion
where its premise is false would discard knowledge the executor demonstrably has,
and record ignorance instead of the fact.

**What we decided against.** Leaving the window to recovery — the architecture
finding's fallback — was the alternative, and it is rejected on §8's own words:
it produces exactly the `INDETERMINATE`-about-a-call-that-never-ran that §8
calls "the one thing `INDETERMINATE` must not be used for". Choosing it would
make ADR-0029 prohibit an outcome in one paragraph and prescribe the path to it
in the next.

### 2. §5's fail-closed rule is scoped to a reading; a raising clock is a wiring bug

We will keep the two apart, because ADR-0026 already does.

**A conforming reading that yields a non-positive elapsed duration lapses the
window.** ADR-0029 §5, verbatim and unchanged: "any reading that is not a
positive elapsed duration — a step backwards, a jump past the window — is
treated as *the window has lapsed*, so the failure mode is a retry not taken."

**A clock that raises produced no reading, and is translated at the boundary.**
ADR-0026 §2 draws this line itself: "The guard covers the reading, not the
invocation. An exception raised by the clock callable itself propagates
unwrapped." ADR-0026 §4 then assigns the translation to the owning subsystem,
which `LearningLoop` and `PlanExecution` both perform, raising `PlanningError`
for the guard's own `ClockReadingError` and leaving anything the callable raises
on its own account untouched. The executor does the same.

**`ClockReadingError` belongs with the second group, and the case against that is
real enough to state.** It could be argued into the first: the value that arrives
is a *rejection of a reading*, §5 is about readings, and treating it as one
lapsed window costs a retry rather than a turn. The argument fails on what the
rejection means. `checked_clock` raises it for a naive, indeterminate or
unlocalizable value — a clock that is *wired wrong*, not a clock that is telling
an awkward truth. §5's pessimism is calibrated for the latter: a wall clock that
stepped is still a clock, and lapsing one window loses one retry. A clock that
cannot produce a conforming instant at all makes **every** window measurement
this executor will ever perform wrong, and the failure mode compounds — the next
one is a duplicated side effect rather than an aborted turn.

So loudness wins, and the trade is stated rather than implied: **propagating
aborts the execution where lapsing would have let it continue.** A user loses a
turn they would otherwise have completed. That is the cost, it is accepted, and
it buys the property ADR-0026 §4 chose in the same words when it refused to let
`context` degrade silently — it converts a silent fabrication into a loud
failure. A broken clock discovered at the first step is a wiring bug someone
fixes; a broken clock absorbed into a log line is one that surfaces later as a
duplicate charge.

**The claimed step is still closed first**, by §1: the raise lands inside the
window, so the step is committed `FAILED` before the error leaves. Loud and
stranded is not the trade being taken; loud is.

**Interaction with #207 and #212, noted rather than fixed.** #207 records that a
clock *impersonating* `ClockReadingError` — raising it on its own account — is
reported as a non-conforming reading, since no producer-side guard can tell a
forged rejection from its own. That residue is unchanged in kind here and
changes in consequence: under this decision an impersonated rejection now yields
a `PlanningError` rather than a lapsed window, which is a louder outcome for the
same forgery, so the disposition ADR-0030 §3 gives it ("a guard is not
answerable for the truth of a claim its source did make") is undisturbed but
#207's worked example needs re-stating against this seam. #212 asks whether
`ClockReadingError` needs an ADR-0026 amendment to name it; this decision reads
that type at a new boundary and so adds a consumer to whatever #212 settles.
Neither is decided here.

### 3. §8's "only outcome derived from an exception" is corrected

§8's sentence — "This is the only outcome an executor must derive from an
exception rather than from a `ToolResult`" — is replaced by an accurate one:

> Outcomes derived from an exception rather than from a `ToolResult` are the
> exception rather than the rule, and they are enumerated: a `ToolBindingError`
> and anything else that ends an attempt inside the pre-invocation window (§1,
> ADR-0034), and a cancelled invocation (§4). Every other outcome comes from a
> `ToolResult`. That enumeration is what keeps "never retried" mechanical: §5's
> conjuncts read `result.failure.kind`, and none of these produces a result to
> read.

The clause it replaces was false on ratification, not falsified by this change:
§4's cancellation rule, in the same document, already required a second such
outcome. Recording it as a drafting defect is deliberate. ADR-0031's Context
makes the case that first use finding a contract wrong is evidence rather than
embarrassment, and a superlative that its own document contradicts is the kind of
claim that survives review precisely because it reads like a summary.

### 4. What ratification does to ADR-0029 and ADR-0014

**ADR-0029's `Status` line is not touched**, and its §8 edits are recorded here
rather than applied, following ADR-0026 §6 and ADR-0031 §7: writing an amendment
onto a document while the amending ADR is only proposed is the state claim
ADR-0019 forbids. On ratification:

- **A dated note is appended to ADR-0029's header**, in the form the other
  amending ADRs use, recording §1's widening of §8's pre-invocation rule, §2's
  scoping of §5's fail-closed clause to readings, and §3's correction of the
  "only outcome" sentence — with that sentence named as superseded text standing
  in the document unedited, exactly as ADR-0031 and ADR-0032 list theirs.
- **Nothing else in ADR-0029 is edited.** §4's cancellation rule, its shield
  idiom, its "correct pessimism" passage and §5's derivation and retry algebra
  all stand as ratified.

**ADR-0014 §4 gains a note, and it is applied by this change** rather than
deferred, because ADR-0014 is not the document being amended — it is being kept
accurate about a table this decision widens the trigger column of. The operation
and its justification are ADR-0029 §9's, copied because that section is the
ratified template for it:

> No legal move is added or removed — `PlanExecution` validates the move and not
> the trigger, so an implementation built from that table needs no change — but
> the table's trigger column is prose a reader relies on, and leaving it naming
> only [the ratified trigger] would make the document wrong about when the state
> occurs. Recording it is cheap and ADR-0019's lesson is that an unrecorded
> widening is the kind that goes unnoticed.

- **ADR-0014's `Status` line is not touched**, for ADR-0029 §9's reason:
  ADR-0001 reserves a status update to an ADR that *changes* a past decision, and
  ADR-0014's decision — that `RUNNING → FAILED` records a step that ended without
  succeeding, carrying an `error`, retryable while attempts remain — is not
  changed, narrowed or reversed. It is applied to a second circumstance that
  meets its own stated test.
- **A dated note is appended to ADR-0014's header**, after the existing ones.

**No other ADR is edited.** ADR-0026 is *read* by §2 and not changed: §2 and §4
already say what §2 relies on, and applying a rule an ADR states is not a
widening of it. ADR-0016 §4's window semantics are untouched. ADR-0029 §9's own
line between the two cases is the one used here — whether a sentence in the other
ADR would now read as false. ADR-0014 §4's trigger column would; nothing in
ADR-0026 does.

### 5. What the implementation owes

- **The window's three exits are each pinned by a test** that asserts the step
  is committed `FAILED` — not left `RUNNING`, not `INDETERMINATE` — and that the
  callable was never reached. Asserting only that an exception propagated would
  leave the stranding this decision exists to prevent untested, which is §10's
  standing objection to that shape of test.
- **The claim's shield is pinned as an idiom, not as a `shield` call.** A test
  holds the claim's commit, injects a cancellation, and asserts the executor is
  still waiting — it must fail against a bare `await asyncio.shield(...)`, for
  ADR-0029 §4's reason: shielding the task without absorbing the repeat
  cancellation looks correct and is not.
- **Both clock cases are pinned separately**: a *reading* the guard refuses
  raises `PlanningError` from the executor's boundary, and an exception the
  callable raises on its own account propagates with its own type — ADR-0026
  §2's line, asserted rather than assumed. Both also assert the claimed step was
  closed.
- **Both precedence rules are pinned, since each is a case where the close runs
  under an exception already in flight**: a cancellation absorbed by the closing
  write leaves as a `CancelledError` rather than as the reason for closing, and a
  store that rejects the close raises rather than logging, carrying the reason as
  its cause. Neither is observable without a store a test can hold mid-write.
- **The lapsed-window cases stay as they are.** §5's rule is unchanged, so the
  table of non-positive elapsed durations — no elapsed time, a clock that went
  backwards — keeps testing exactly what it tested.

## Consequences

- **The pre-invocation window has one rule instead of one example.** An executor
  reading ADR-0029 §8 previously had to generalise from `ToolBindingError` to its
  own case, and PR #224's review shows what that costs: two reviewers reached
  opposite conclusions about the same window, each citing the same ADR. The rule
  is now stated over the circumstance, so a fourth exit added later inherits it
  rather than reopening the argument.
- **`INDETERMINATE` keeps its meaning, which is the whole point.** Every
  additional route by which a never-started call could acquire it is closed.
  What still produces it is unchanged: a deadline expiry or a cancellation on a
  side-effecting non-`NATURAL` tool, a tool reporting its effect may have
  committed (ADR-0032 §2), and recovery finding a durable `RUNNING` after a
  crash. The last of those is untouched and remains the honest answer for a
  process that died.
- **A broken clock now costs a turn.** This is the sharpest edge of §2 and it is
  a real regression in availability for a real gain in diagnosis. A deployment
  with a misconfigured clock fails visibly at the first step rather than
  executing with every window measurement silently wrong. The mitigation is that
  the failure is a `PlanningError` naming the owner, which is what ADR-0026 §4
  built the label for.
- **`_reading`'s two branches will look asymmetric to a reader who has not read
  ADR-0026 §2**, and that is a documentation cost this decision accepts rather
  than removes. Both branches are hostile-input handling of the same injected
  callable, and only one of them raises. The docstring carries the citation
  because the code cannot carry the argument.
- **ADR-0029 §8's enumeration is now a maintained list**, with the failure mode
  that any list has: a later ADR adding an exception-derived outcome must extend
  it. That is worse than the superlative it replaces in exactly one way — it can
  go stale — and better in the way that matters, which is that it is true. §3
  names the defect class so the next count claim is written more carefully.
- **This is the fourth ADR amending ADR-0029** (0031, 0032, 0034, with 0033 in
  another lane), and that is worth watching rather than dismissing. ADR-0029's
  own §10 predicted it: it was ratified without a spike, said so, and recorded
  that "every conforming implementation on day one will be a fake". Three of the
  four amendments come from first use, which is the mitigation working as
  described. It is still evidence for ADR-0018's lesson — spike before
  ratifying — and against ratifying a seam this large in one document again.
- **Revisit when** a second executor exists (a background or batch one may want
  the pessimistic path deliberately, to avoid closing a step a peer could still
  resolve), when #171's monotonic clock lands and changes what a window
  measurement can fail with, or when #208 gives an `INDETERMINATE` step a durable
  diagnostic and makes the distinction between the states cheaper to audit.
