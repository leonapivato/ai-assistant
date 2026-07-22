# 39. What a finished step durably records about why

- Status: Proposed
- Date: 2026-07-22

## Context

`StepExecution` (ADR-0014 §3) is the durable half of the planning model: what
actually happened to one `PlanStep`, kept separate from the plan so that
recovery is *loading* state rather than reconstructing intent. It carries one
field about failure:

```python
error: str | None = Field(default=None, description="Failure detail; required when FAILED.")
```

and one rule about that field, enforced by `_outcome_fields_match_status` and
mirrored on `StepTransition`:

> `error is only valid for a FAILED step` — ADR-0014 §3

Two recorded follow-ups say that field is not enough, from opposite directions.
They are the same question — *what does a finished step durably record about
why* — and this ADR answers them together, because answering either one alone
sets the shape of the other.

**#172 — the failure kind does not survive a restart.** ADR-0029 §3 gives a tool
failure a structured `ToolFailureKind` with a `retryable` property, and §5 makes
the retry decision read `result.failure.kind.retryable` as the first of two
conjuncts. `error` is an unstructured `str`, so that kind is lost the moment the
step is persisted: after a restart an executor can read *that* a step failed and
not whether retrying is permitted. ADR-0029 §8 names this, declines to fix it
from a tools ADR, and states the interim behaviour — retry decisions are made
in-process from the `ToolResult` in hand, and a `FAILED` step recovered after a
restart is not auto-retried. That is conservative and safe. What is lost is
resuming a retry across a restart.

The same §8 leans on the gap for a second purpose, which matters here: "never
retried" for a raised `ToolBindingError` is a property of the executor's loop
shape rather than of the record, precisely because "nothing durable
distinguishes this `FAILED` from a retryable one".

**#208 — an `INDETERMINATE` step keeps no durable diagnostic.** The FAILED-only
restriction means an `INDETERMINATE` step carries a status and nothing about
why. `INDETERMINATE` is the state ADR-0014 §4 makes durable *precisely because*
it "must be resolved explicitly", by a human or by reconciliation — and it is
the one non-successful outcome whose diagnostic survives only in a log. It now
has three triggers: recovery finding a durable `RUNNING` after a crash (ADR-0014
§4), a deadline expiry or cancellation on a side-effecting non-`NATURAL` tool
(ADR-0029 §4), and a tool reporting `effect_may_have_committed` (ADR-0032 §2).
ADR-0032 §5 calls the asymmetry "inherited rather than chosen" and files it
rather than fixing it, for the same boundary reason.

`orchestration/executor.py` already carries both gaps as comments — the module
docstring for #172, and `_CANCELLED`'s "``INDETERMINATE`` records nothing …
that a cancelled step carries no durable diagnostic is #208".

This changes a `core` type that crosses subsystem boundaries, so it is a
breaking change under golden rule 5 and ships as its own PR ahead of any
implementation (ADR-0015 §5, `CONTRIBUTING.md` → "Contract ADRs land before
their implementation").

## Decision

We will **replace `error: str | None` with `failure: StepFailure | None`** on
`StepExecution` and on `StepTransition`, and **redraw the required/forbidden
rule over `{FAILED, INDETERMINATE}`** rather than over `FAILED` alone.

### 1. `StepFailure` — one field, one authority

`core/types.py` gains:

```python
class StepFailure(BaseModel):
    """Why a step finished without succeeding (see ADR-0039)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message: str                          # Tier 2 operator text; visible characters required
    kind: ToolFailureKind | None = None   # the tool's own classification, when a tool produced one

    @field_validator("message")
    @classmethod
    def _message_is_present(cls, value: str) -> str:
        """Return ``value`` stripped, or raise if nothing in it renders.

        The ``_has_visible_text`` test ADR-0018 §1 applies to a tool's
        description, ADR-0021 §1 to a ruling's reason and ADR-0029 §3 to a
        ``ToolFailure``'s message.
        """
```

**This is a shape, not an implementation**, in the form every contract ADR in
this repo has used (ADR-0029 §3, ADR-0021 §1). What is normative is each rule
stated in prose; the implementation PR writes the bodies.

`frozen=True` because it is a record of something that already happened, and the
argument ADR-0014 makes for freezing the plan applies to the account of a
failure just as much: what an operator reads while resolving an `INDETERMINATE`
step must not be editable after the fact. (`StepExecution` itself stays mutable —
ADR-0014's Consequences already record why, and freezing that object graph is a
different change.)

**`message` is required and `kind` is optional, and that asymmetry is the whole
design.** Every finished-unsuccessfully step has something to say. Not every
one has a tool's classification to say it with.

### 2. The rule is redrawn over `{FAILED, INDETERMINATE}`, and #208's framing is corrected

> `failure` is **required when the status is `FAILED` or `INDETERMINATE`, and
> forbidden on every other status.** The same rule, over `to_status`, on
> `StepTransition`.

#208 argues the current restriction "is the wrong way round". Tested against
ADR-0014 §3's actual text and validator, that is too strong, and adopting it
would be a mistake. The restriction is not backwards; it is **too coarse**.

The both-directions form of `_outcome_fields_match_status` exists to make
contradictory combinations unrepresentable — "a SKIPPED step carrying an error,
say, or an output on a step that never ran". That reasoning is correct and
survives intact for four of the seven statuses:

- `PENDING` and `AWAITING_APPROVAL` have not run. A diagnostic on them is the
  fabricated history `_unclaimed_step_carries_no_history` already refuses in its
  other fields.
- `SUCCEEDED` has nothing to explain. A succeeded step carrying a failure is the
  half-says-two-things state ADR-0029 §3 refuses on `ToolResult` one layer down.
- `SKIPPED` already has `skip_reason`, a closed enum, which is the *better*
  record. Admitting a free-text failure beside it would create a second,
  disagreeing account of the same decision.
- `RUNNING` has not finished, and `_finished_at_matches_status` already refuses
  the marks of an ending on it.

The restriction is wrong for exactly one status. `INDETERMINATE` is a **finished,
non-successful** outcome: it sits in `_FINISHED_STATUSES` beside `SUCCEEDED` and
`FAILED`, so it is required to carry `finished_at`, and `PlanExecution` gives it
no outgoing transition at all. It is the only finished status required to carry
no account of itself. So the fix is not to lift the rule but to draw it over the
set it was always about: *the step stopped, and it did not succeed.*

Redrawing rather than lifting is what keeps the guarantee. A `failure` permitted
anywhere would re-open every combination the validator exists to close, and
would make "a step that carries a diagnostic is a step that failed" stop being
readable off the type.

**Required, not merely permitted, on `INDETERMINATE`.** Every one of the three
triggers has something true to write: the executor's live paths hold a
`ToolResult` whose `failure` ADR-0029 §3 *requires* to be present when the
outcome is `INDETERMINATE`, and recovery knows the one fact that matters — that
it found the step `RUNNING` with nothing executing it. Permitting the field
instead would make the useful case optional exactly where it is most needed, and
`PlanExecution.abandon_running` — which today writes only `status` and
`finished_at` — is the code that would skip it.

### 3. `kind` is `ToolFailureKind`, and `None` means no tool classified this

`kind` is the tool's own `ToolFailureKind` (ADR-0029 §3), not a planning-owned
mirror of it. Both types live in `core/types.py`, so no boundary is crossed, and
ADR-0031 §1 is explicit about the cost of the alternative: two copies of a
safety-critical classification, "free to disagree, with nothing that fails when
they do". A mirror would also have to copy `retryable`, which is the property
the retry decision actually reads.

This does not make `planning` depend on the `tools` subsystem's shape. ADR-0014
§2 keeps *the plan* tool-agnostic — a step names a capability, not a tool — and
is equally explicit that "execution records what actually ran". `StepExecution`
already records `bound_tool`, an actual registry id, for that reason. Recording
the tool's own account of how its call failed is the same move at the same
layer.

**`kind is None` is the durable form of ADR-0029 §8's rule.** Three of the
executor's write paths close a step that no tool ever classified:

- a seam rejection (`ToolBindingError`, ADR-0029 §8),
- an attempt that ended between the committed claim and the callable (ADR-0034
  §1),
- a cancellation the executor commits before re-raising (ADR-0029 §4).

None of them produces a `ToolResult`. §8's rule — "retry is scheduled only from
a `ToolResult`, never from an exception" — is therefore visible in the record for
the first time: a `FAILED` step with `kind is None` provably had no result to
read a retry decision from.

**And the executor must never fabricate a kind.** `INTERNAL` is the tempting
fill-in and it is wrong: it means "the tool implementation is broken" (ADR-0029
§3), which would make a wiring fault indistinguishable from a broken integration
and would put a *tools* classification on a failure the tools layer never saw.
`None` is the honest value and the field is optional so that it can be given.

**This does not make §8's rule enforced by the type system, and does not claim
to.** `PlanExecution` still does not read `kind`; the tracker validates the move
and not the trigger (ADR-0014 §4, restated in ADR-0034's note). What changes is
that a future recovery-side retry driver can *honour* the rule by reading the
record, instead of only by being shaped correctly. Widening the tracker to
reject a transition on the basis of a failure kind is the alternative ADR-0029
§8 already rejected, and it stays rejected.

### 4. A durable kind on an `INDETERMINATE` step is diagnostic, never permission

An `INDETERMINATE` step can now carry a kind whose `retryable` is `True` — a
`TIMED_OUT` from ADR-0029 §4's expiry rule, or a `RATE_LIMITED` a tool raised
with `effect_may_have_committed=True` under ADR-0032 §2. That must not become a
retry.

It cannot, and the reason is structural rather than conventional: **ADR-0014
§4's transition graph has no `INDETERMINATE → RUNNING` edge at all.**
`_LEGAL_TRANSITIONS` maps `INDETERMINATE` to the empty set, so `PlanExecution`
rejects the move with a `PlanningError` regardless of what any field says.
ADR-0029 §5's "neither is an `INDETERMINATE` outcome" is unchanged and unrelaxed.

Stating it is worth the paragraph because this is the one place where making a
record more informative could plausibly be read as making an action more
permitted, and the answer is that the two are enforced in different places.

### 5. The data tier — verified against ADR-0004, and #172's reasoning corrected

#172 asserts that `ToolFailure.message` is Tier 2 under ADR-0029 §3's
producer-side rule and `kind` is an enum, so "neither widens the record's
sensitivity". Checked against ADR-0004 rather than repeated: **the conclusion
holds, the reasoning does not, and there is a real change of exposure the
framing misses.**

**The tier does not widen — but not for #172's reason.** ADR-0004 §1 tiers
*data*, and ADR-0014 §5 already rules on this record: "Goals, plans, parameters,
outputs and errors are all personal data, so this state is squarely within
ADR-0004's scope." The `PlanStore` is a Tier 1 store. A Tier 2 field inside a
Tier 1 record is handled as Tier 1 — the tier is a floor over the record, not a
per-field property — so adding a Tier 2 string could not have raised it whatever
the string was. The tier argument is therefore true and empty; it is not what
makes this safe.

**What makes the `FAILED` half safe is that it is not new.** ADR-0029 §3 says
the tool's message "is bound for a log and for `StepExecution.error`", and
ADR-0032 §5 confirms it "lands in `StepExecution.error` when the outcome is
`FAILED`". For that half this ADR moves an existing string from one field on
this record to another. Nothing about its exposure changes.

**The `INDETERMINATE` half is a genuine widening, and it widens reach rather
than tier.** A message that today survives only in whatever the executor logged
becomes durable. Concretely, under ADR-0004 that means it:

- **persists for the record's lifetime instead of the log's.** ADR-0014 §5
  refuses to delete a goal while a step is live and reports `INDETERMINATE`
  steps it erased, so this string outlives a rotated log file by design.
- **enters `PlanExport`** (ADR-0004 §6, ADR-0014 §5), so it leaves the machine
  when the user exercises their export right.
- **gains at-rest protection it did not have.** ADR-0004 §3 and §4 put the store
  under owner-only permissions and optional SQLCipher; a log file has neither.

Weighed against the destination it already reaches, this is the **lower**-risk
home of the two. ADR-0004 §5 forbids Tier 0/1 in logs outright, and
`core/logging.py`'s own docstring concedes that its key-based redactor cannot see
this exact case — it names `error=str(exc)`, "where the provider quoted the
user's prompt", as the canonical leak it misses. So if the producer honours
ADR-0029 §3, both homes are fine; if it does not, the log leak already happened
first and is the worse of the two. A durable record is a different exposure from
an in-process value, and it is the right one to have named — but it is not the
one that would carry the leak.

**Three things this does not relax, stated so no one reads a widening as a
licence.**

- The producer-side rule is **unchanged and still the only defence**: an
  integration authors its message, and copying an upstream error body into it is
  the leak (ADR-0029 §3). ADR-0032 §5 already made that load-bearing rather than
  aspirational.
- The **seam still authors nothing**. ADR-0032 §5's enumeration — the message
  crosses by value or is discarded whole, and nothing derived from the exception
  object enters a message or a log — binds `invoke`, and nothing here touches it.
  The executor's job is to write down what it was handed, verbatim (§6).
- `kind` **carries no content from the call**: eight members of a closed enum
  authored by `core`. This is the same reasoning ADR-0032 §5 uses for what the
  seam may log, "an identifier and a member of a closed enum".

No egress or residency rule moves: `StepFailure` is a `core` type, ADR-0014 §5
already binds `PlanStore` implementations to persist locally only, and no
import-linter contract changes.

### 6. What this asks of the executor

In the shape of ADR-0029 §8's own section, so the implementation PR inherits
these rather than rediscovering them. All five write sites are in
`orchestration/executor.py` today.

- **A `FAILED` from a `ToolResult`** writes
  `StepFailure(kind=result.failure.kind, message=result.failure.message)`. The
  message still crosses **by value and unedited** — ADR-0032 §5 governs it up to
  the seam, and the executor adds no rule of its own past that point. It does not
  prefix, wrap or annotate; `_UNEXPLAINED` remains the stand-in for the
  result-with-no-failure that `ToolResult`'s validator makes unconstructable.
- **An `INDETERMINATE` from a `ToolResult`** — ADR-0029 §4's expiry and ADR-0032
  §2's tool-reported commit — writes the same thing, where today it drops it.
  This is #208's live half, and it needs no fabrication: ADR-0029 §3 requires
  `failure` to be present on a non-`SUCCEEDED` result.
- **The three exception paths** keep their existing authored constants and gain
  `kind=None`: `_REFUSED` for a seam rejection, `_UNSTARTED` for the
  claim-to-callable window, `_CANCELLED` for a commit through a cancellation.
  `_CANCELLED`'s `INDETERMINATE` branch stops discarding its text — the change
  that closes the comment in the module naming #208.
- **No fabricated kind** on any of those three (§3).
- **The retry decision is unchanged.** It still reads the `ToolResult` in hand.
  Nothing in this ADR asks the executor to read `failure.kind` back off the
  record, and §7 says why it must not yet.

### 7. What this asks of recovery — and the one thing it does not deliver

- **`PlanExecution.abandon_running` must now supply a failure.** ADR-0014 §4's
  `RUNNING → INDETERMINATE` move writes `status` and `finished_at` today; it
  gains `StepFailure(kind=None, message=...)` with text `planning` authors —
  that the step was found `RUNNING` with nothing executing it, so whether the
  tool acted is unknown. `kind=None` is correct and not a shortfall: recovery
  has no `ToolResult` and never had one. This is the transition that gets
  strictly more expensive, and it is the one #208 is really about.
- **Recovery must not read `kind` as permission** (§4). The graph refuses the
  move.
- **This ADR does not enable cross-restart retry, and claiming it did would be
  false.** ADR-0029 §5's permission is a conjunction, and this closes only the
  first conjunct. The second — "the elapsed time since the **first attempt of
  this call** is strictly less than `idempotency_window`" — is measured in
  `orchestration` from a local `started`, read once after the first claim and
  held across the in-process retry loop. It is not durable, and it cannot be
  recovered from `StepExecution.started_at`, because ADR-0014 §4's
  `FAILED → RUNNING` retry **resets** `started_at` — `PlanExecution` writes
  `"started_at": self._now()` on every claim. So a restarted executor reading a
  durable retryable kind still could not establish that repeating is safe.

  **ADR-0029 §8's interim behaviour therefore stands unchanged: a `FAILED` step
  recovered after a restart is not auto-retried.** This ADR removes one of the
  two blockers, and the remaining one is filed as a follow-up issue rather than
  decided here — a durable first-attempt instant is a second `StepExecution`
  field with its own reset semantics, and stacking it onto this change would
  make the diff answer two questions instead of one.

### 8. What ratification does to ADR-0014, ADR-0029 and ADR-0032

Appended as notes by the PR that implements this, not by this one — ADRs are
append-only (ADR-0001) and this PR's diff is one file (§10).

- **ADR-0014 §3** — `StepExecution.error` and `StepTransition.error` become
  `failure: StepFailure | None`, and "error is only valid for a FAILED step"
  becomes "required when `FAILED` or `INDETERMINATE`, forbidden otherwise".
  §4's transition table gains `failure` in the *Also sets* column for
  `RUNNING → FAILED` and `RUNNING → INDETERMINATE`. The graph itself, the retry
  ceiling, and `INDETERMINATE`'s never-auto-retried, resolved-explicitly
  treatment are all unchanged.
- **ADR-0029 §8** — the bullet "Failure kind does not survive a restart, and
  this ADR does not widen `StepExecution` to fix it" is discharged in its first
  half and **explicitly not in its second**: the interim behaviour it states
  stands, for §7's reason. The bullet's "Result mapping is total" gains
  `INDETERMINATE → failure and finished_at`, where it previously mapped that
  outcome to a transition carrying neither.
- **ADR-0032 §5** — its "it does not reach `StepExecution.error` when the outcome
  is `INDETERMINATE`, an asymmetry inherited rather than chosen" is resolved.
  Everything else in §5 — the seam's enumeration, the by-value rule, the
  no-safety-net candour — is untouched and still the only defence (§5).
- **ADR-0004** — nothing changes. §5 verified rather than amended (§5 above).

### 9. What this does not change

- No Protocol changes. `PlanStore.commit_transition` still takes a
  `StepTransition`; only that command's shape moves.
- The transition graph, the retry ceiling, `TERMINAL_STEP_STATUSES`, and
  `is_active` / `has_live_step`.
- `SkipReason`, which stays the record for a `SKIPPED` step (§2).
- ADR-0029 §5's retry conjunction, ADR-0032's seam rules, and ADR-0004 §5's
  producer-side obligation.
- `ToolResult` and `ToolFailure`, which are not touched. `StepFailure` is a
  separate type deliberately (§10, alternative (a)).

### 10. What the implementation PR owes

**The triad requirement is not re-triggered** — no new Protocol, so no new
canonical fake. But `StepTransition` is `PlanStore`'s only write path, so **both**
conforming implementations change (`planning`'s `InMemoryPlanStore` and the
canonical fake in `ai_assistant/testing/planning.py`, whose `_to_finished`
mirror plumbs `transition.error` today), and the shared conformance suite
(`tests/planning/plan_store_contract.py`) gains cases.

- **`core/types.py`**: `StepFailure`; `StepExecution.error` → `failure`;
  `StepTransition.error` → `failure`; `_outcome_fields_match_status` and
  `_fields_match_target_status` redrawn over `{FAILED, INDETERMINATE}`.
- **A module reordering, which is not cosmetic.** `ToolFailureKind` is defined
  at the bottom of `core/types.py` and `StepExecution` in the middle; the enum
  must move above the planning types. Worth naming because it is the one part of
  this that touches lines nothing else in the diff explains.
- **`PlanExport.schema_version` becomes 2.** ADR-0014 §5 states the reason
  itself — "an export outlives the code that wrote it … a reader must be able to
  tell which shape it is holding" — and `StepExecution` is inside the export.
  The bump is cheap and correct now: the SQLite `PlanStore` is still deferred
  (ADR-0014 §7), so no export written under shape 1 exists, and there is no
  migration to write.
- **`planning/execution.py`**: `_to_finished`, the retry reset (which clears the
  last attempt's outcome and must clear `failure`), and `abandon_running` (§7).
- **`orchestration/executor.py`**: the five write sites in §6, and the two
  module comments naming #172 and #208, which become descriptions rather than
  deferrals.
- **Existing `error` readers** are entirely in-repo and enumerable:
  `planning/execution.py`, `testing/planning.py`, `orchestration/executor.py`,
  and their tests. There is no deprecation window and no compatibility alias —
  a `str` field aliased to a model would be the two-spellings failure this ADR
  rejects (alternative (a)), and ADR-0001's append-only rule binds *decisions*,
  not dead fields.

Suite cases, asserted rather than sampled:

- **The required half on both statuses, and the forbidden half on each of the
  other five**, as rejection tests — the shape ADR-0029 §10 requires. A suite
  that tests `SUCCEEDED` and stops certifies an implementation that merely
  widened the rule to "anything finished".
- **`StepTransition` and `StepExecution` agree**, both directions, on both
  statuses. They are two validators expressing one rule and are exactly the pair
  that can drift.
- **A tool-produced failure round-trips through the store verbatim** — kind and
  message unchanged after `commit_transition`, on `FAILED` *and* on
  `INDETERMINATE`. The `INDETERMINATE` case is the regression test for #208 and
  for ADR-0032 §5's by-value rule surviving one frame further than the seam.
- **An executor-authored failure carries `kind=None`**, for each of `_REFUSED`,
  `_UNSTARTED` and `_CANCELLED`, and specifically not `INTERNAL` (§3).
  Asserting only that a failure is present passes an implementation that
  fabricates a kind.
- **An `INDETERMINATE` step carrying `TIMED_OUT` is still refused a
  `→ RUNNING` transition** by the tracker. Nothing else pins §4, and it is the
  case a reader of the new field is most likely to get wrong.
- **`abandon_running` writes a failure**, with `kind=None` and visible text, for
  every recovered `RUNNING` step (§7).
- **A blank message is refused** at construction, by `_has_visible_text` —
  ADR-0029 §3's case, one layer up.
- **A retry clears the previous attempt's failure**, so a step re-opened to
  `RUNNING` carries none — the `forbidden` half of §2 exercised through the
  transition that most easily leaves it behind.
- **`PlanExport` round-trips at `schema_version` 2** with an execution whose step
  carries a failure.

## Alternatives considered

**(a) `failure: ToolFailure | None` beside a retained `error: str`.** The
literal first option in #172. Rejected twice over. It creates two spellings of
the same thing — `error` and `failure.message` — free to disagree, in a durable
record; this is precisely what ADR-0032 §2 refused when it declined to keep
`effect_may_have_committed` on `ToolFailure` beside the outcome it had already
ruled. And `ToolFailure` requires a `kind`, so the executor's three
non-tool paths (§3) would have to **fabricate** one for a failure no tool ever
saw. Those are exactly the failures that must never be retried, and giving them
a tool's classification is the wrong direction to be wrong in.

**(b) A scalar `failure_kind: ToolFailureKind | None` beside `error: str`.** The
smallest possible change for #172 alone. Rejected: it answers half the brief. It
leaves #208 untouched unless `error`'s FAILED-only restriction is separately
redrawn, at which point the required/forbidden rule is stated twice over two
fields that must stay consistent by hand. It also cannot grow — the next thing a
finished step needs to record about why becomes a third top-level field.

**(c) A planning-owned `StepFailureKind` mirroring `ToolFailureKind`.**
Attractive on subsystem-independence grounds and rejected on ADR-0031 §1's:
two copies of a safety-critical classification, free to disagree, with nothing
failing when they do. The mirror would have to copy `retryable` as well, which
is the property the retry decision reads, and the mapping between the two enums
would become a third place to get it wrong. ADR-0014 §2's independence claim is
about *the plan*, and `bound_tool` already settles that execution records real
tool facts (§3).

**(d) A separate `indeterminate_reason` field for #208's half.** Keeps `error`
untouched and looks minimal. Rejected: it puts the diagnostic for the two most
alike statuses in two different fields, so every reader — an interface rendering
a failed step, an export consumer, a future reconciler — branches on status to
find the same string. The two issues would also stop being one question, which
is the thing this ADR concluded they are.

**(e) Lift the restriction entirely, permitting a failure on any status.** What
#208's "wrong way round" framing literally implies. Rejected on the argument in
§2: the restriction is too coarse, not backwards, and it is correct for four of
the seven statuses. Lifting it re-opens the contradictory combinations
ADR-0014 §3's validator exists to make unrepresentable — a `SKIPPED` step with a
free-text account disagreeing with its `skip_reason`, a `PENDING` step with
fabricated history — for no gain over redrawing.

**(f) A third field: `origin: FailureOrigin` — `TOOL` / `EXECUTOR` /
`RECOVERY`.** Considered seriously, because it would distinguish an
`INDETERMINATE` from a crash from one from a deadline expiry. Rejected as
surface built for a consumer that does not exist. `kind is None` already carries
the only distinction anything reads today (§3), and the residue — recovery and
cancellation both landing at `kind=None` — is separable by the message a human
reads while resolving the step, which is the only reader `INDETERMINATE`
currently has. Automated reconciliation is still deferred (ADR-0014 §7); if it
needs to branch mechanically, an optional field is additive, in the shape
ADR-0029 §3 reserved for `ToolResult`'s own later fields.

**(g) Do nothing, and treat the log as the record.** The status quo, and it has a
real argument: the interim behaviour is safe, nothing is blocked, and #208 says
so itself. Rejected because ADR-0004 §5 makes logs Tier 2, rotatable and outside
the export and deletion rights §6 grants — and the state ADR-0014 §4 made
durable *because* it must be resolved explicitly cannot have its only
explanation living in the one store designed to be discarded. The asymmetry is
also no longer static: ADR-0032 §2 added a third trigger for `INDETERMINATE`,
and a gap that widens on its own is one to close rather than to carry.

## Consequences

- **`INDETERMINATE` becomes resolvable from the record**, which is what
  ADR-0014 §4 asks of the state it made durable. A human or a future reconciler
  reads why, not just that.
- **The retry decision's first conjunct survives a restart.** ADR-0029 §5's
  `result.failure.kind.retryable` has a durable home for the first time.
- **And the second conjunct still does not**, so cross-restart retry is *not*
  enabled by this ADR and ADR-0029 §8's interim behaviour is unchanged (§7).
  Anyone reading this as "restarts can now resume retries" has read it wrong,
  which is why §7 says so twice.
- **A breaking `core` change** to two types that cross subsystem boundaries.
  It lands as its own PR ahead of any implementation (golden rule 5), and the
  implementation PR touches `core`, `planning`, `orchestration`, `testing` and
  three test suites — larger than this repo's usual one-subsystem scope, because
  a field on a shared type has no smaller shape.
- **`PlanExport` gains a schema version**, cheaply, because nothing durable
  exists to migrate yet. Deferring the bump until the SQLite store lands would
  make it expensive at exactly the moment it stops being free.
- **ADR-0029 §8's "retry only from a `ToolResult`" becomes readable off the
  record** rather than only inferable from the executor's shape — without
  becoming enforced by the tracker, which §8 already rejected and §3 keeps
  rejected.
- **One more durable Tier 1 field**, and a tool-authored message with a longer
  life and an export path than the log it already reached. Accepted with the
  reasoning in §5, and with the producer-side rule unchanged as the only
  defence — this ADR does not close ADR-0032 §5's candid hole and does not
  claim to.
- **Recovery gets more expensive**, in that `abandon_running` must now author
  text. That is a small, one-time cost and it is the point.
- **Revisit when** a durable first-attempt instant lands (§7), when automated
  `INDETERMINATE` reconciliation is designed and may want alternative (f)'s
  `origin`, or when a real integration produces the first tool-authored message
  and its own ADR binds the review obligation ADR-0032 §5 names.

### The strongest case against this decision

That it makes a planning type carry a tools enum, and the boundary ADR-0014 §2,
ADR-0018 §2 and ADR-0031 §5(b) each defended is a boundary worth more than the
convenience. The honest reply is that `bound_tool` crossed it first and for the
same reason — execution records what actually ran — and that the alternative
(c) mirror is the shape ADR-0031 §1 says fails. But someone who weighs the
independence higher would take (c), accept the mapping, and be making a
defensible choice rather than an obviously wrong one. This is the part of the
decision most worth a reviewer's disagreement.
