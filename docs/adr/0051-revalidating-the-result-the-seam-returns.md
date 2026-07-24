# 51. The executor revalidates the result the seam returns, and records an unusable one as INDETERMINATE

- Status: Accepted
- Date: 2026-07-23

## Context

ADR-0029 §3 contracts `ToolInvoker.invoke` to return a valid `ToolResult`, and
ADR-0039 §6 has the executor record it verbatim. `StepExecutor._record` acts on
that trust directly: `_STATUS_BY_OUTCOME[result.outcome]` maps the outcome to a
`StepStatus`, and `_failure_of` dereferences `result.failure.kind`/`.message` on
the non-`SUCCEEDED` branch.

`ToolResult` is `frozen=True`, but frozen refuses `result.outcome = ...` and does
nothing about `result.__dict__["outcome"] = ...`. That `__dict__`-bypass is
already inside this repository's threat model — ADR-0018 §3 states it, and it is
exactly why the executor revalidates and detaches the *inbound* `ToolCall`
(`_detached`) rather than trusting `frozen=True` to hold across the awaits it
holds the caller's object over. The *returned* result is the mirror-image hole,
left open:

- an `outcome` replaced with a non-member raises `KeyError` out of the total
  `_STATUS_BY_OUTCOME` mapping;
- a `failure` replaced with an object lacking `kind`/`message` raises
  `AttributeError` out of `_failure_of`.

Both raise **after** the claim. The claim precedes the call (ADR-0014 §4), so by
the time `_record` runs the step is durably `RUNNING`; an exception escaping
there strands it, and recovery reads a durable `RUNNING` as `INDETERMINATE` —
"we cannot tell whether it acted". This is #270, surfaced during the ADR-0039
review (PR #269), where it was deferred as "a separate design decision" that
ADR-0039 §9 explicitly declined to make: ADR-0039 does not change the seam
contract and does not add result revalidation.

Two things make it a decision worth recording rather than a one-line guard.

**Where the guard sits is different from the inbound one.** `_detached` runs
*before* the claim, so it can raise: an unusable inbound call touches no durable
state. A returned-result guard runs *after* the claim, so it must **commit**,
not raise — the way `_refuse` commits the seam's own post-claim rejection
instead of letting it propagate.

**What it commits is a genuine choice.** The tool was invoked and may have
acted, and the result whose `outcome` is now unreadable was the only evidence of
whether it did. Which `StepStatus` an executor writes for "the seam answered,
and its answer is unreadable" is not settled by any existing ADR, and the
obvious analogies each get it subtly wrong (§2).

## Decision

**We will revalidate and detach the `ToolResult` the seam returns before the
executor reads it, and record an unusable one as an executor-authored,
never-retried `INDETERMINATE` close.**

### 1. Revalidate and detach the returned result, mirroring `_detached`

A `_detached_result` helper round-trips the return through
`ToolResult.model_validate(result.model_dump(...))`, the mirror of `_detached`
for the seam's output. On success it yields a revalidated copy nothing else
holds a reference to — so it cannot be edited between the check and the commit —
and both `_record` and the retry decision read *that* copy, never the raw value.

Unlike `_detached`, it returns a sentinel rather than raising, because of where
it sits (Context): an unusable return becomes a commit, not an escape.

It is **total over any return, not only a tampered `ToolResult`.** The parameter
is typed `ToolResult`, but the point of a post-claim guard is to survive a value
that violates its type: a non-conforming seam that returns `None` or some other
object raises out of `model_dump` before `model_validate` is reached, and a
subclass could override serialization to raise anything. Any of those escaping
would strand the claim exactly as the `KeyError`/`AttributeError` this exists to
prevent would. So it catches every ordinary `Exception` and reports "unusable";
`BaseException` — a cancellation, a shutdown — is deliberately *not* caught, so
structured concurrency is unaffected.

This does not replace the seam's own contract to return a valid result (ADR-0029
§2, §3) and is not meant to, exactly as `_detached` does not replace the seam's
inbound revalidation. Each guard is total over what it is handed.

### 2. An unusable return is recorded `INDETERMINATE`, unconditionally

This is the load-bearing choice. The tool was reached and may have acted;
`FAILED` asserts a possible effect certainly did not happen, which ADR-0014 §4
and ADR-0034 §1 refuse to guess. So the executor records ADR-0014 §4's durable
ignorance instead — the same widened live-executor use of the `INDETERMINATE`
transition that a deadline expiry already makes (ADR-0029 §8, #208), not only the
recovery-time crash it was first reserved for.

**Not the interrupted-call classification** (`ToolDefinition.interrupted_outcome`,
the executor's rule for a cancelled invocation). That rule maps a `NATURAL`
side-effecting tool to `FAILED` *because a repeat does the same thing* (ADR-0016
§4, ADR-0029 §4) — a premise that holds only when a retry follows. An unusable
return is terminal (§below): no retry follows, so the premise is absent, and
`FAILED` for a `NATURAL` side-effecting tool that may have acted would be exactly
the certainly-nothing-happened it warns against, now without the retry that made
it safe. Reusing `interrupted_outcome` here would apply a ratified rule outside
the case it was ratified for.

**Unconditional — the same `INDETERMINATE` for every tool kind**, including a
read-only one where `FAILED` would be defensible (a read that could not have
acted has nothing for ignorance to be uncertain about). Two reasons:

- One rule is simpler than a tool-kind branch, and the read-only precision it
  would buy is marginal — an unusable return is an exceptional wiring/tamper
  event, and recording it conservatively costs a recoverable diagnosis, not a
  duplicated effect.
- It needs no `trusted` declaration. A classification that reads the registry's
  declaration is a classification that can itself fail post-claim, and the same
  corruption that produced an unreadable return is a plausible reason a
  declaration is unavailable. `INDETERMINATE` for a read-only unusable return is
  conservative, not wrong — "we did not get a usable result" is literally true.

**It schedules nothing.** The failure takes `kind=None` — no tool classified it —
and ADR-0029 §5's retry conjuncts read `result.failure.kind`, so a `None` kind is
never auto-retried (ADR-0039 §3, the same shape as `_refuse` and every other
executor-authored close). `INDETERMINATE` is outside automatic retry regardless
(ADR-0014 §4). Two locks on the same door.

### 3. This adds no transition and no contract surface

Stated because it is what makes the one-implementation-PR shape legitimate, and
it is checkable rather than asserted:

- **The `RUNNING → INDETERMINATE` transition carrying a `StepFailure` is already
  legal and already used by a live executor** — a deadline expiry records it, and
  `_commit_through_cancellation` writes it with `kind=None` (ADR-0039 §2, #208).
  This decision reaches it from one more place; it widens nothing in the graph.
- **`ToolResult`, `ToolInvoker`, `StepTransition` and `PlanStore` are unchanged.**
  `ToolResult` is a `core` type, not a Protocol, and no field, validator or
  method of it moves. `ToolInvoker`'s signature and contract are untouched.

So no Protocol and no `core` type moves, golden rule 5's separate-PR requirement
is not triggered, and this ADR is `Accepted` on merge with its implementation
following in its own PR.

### 4. No other ADR is edited

ADR-0039 §9 named this as a separate decision and declined it; ratifying it is
that section working as designed, not a contradiction of it. ADR-0014, ADR-0018,
ADR-0029, ADR-0031 and ADR-0034 are *read* here, not widened — the `INDETERMINATE`
use is the one ADR-0029 §8 already opened, and the reachability principle is
ADR-0014 §4's and ADR-0034 §1's own. Nothing in any of their text reads as false
once this lands (ADR-0029 §9's test).

### 5. Alternatives considered

- **A flat `FAILED` close** (the wording #270's suggested direction used).
  Rejected on §2: post-invocation, `FAILED` records a possible effect as
  certainly-nothing-happened. The issue text is superseded by the reachability
  argument the review surfaced.
- **The interrupted-call classification** (`INDETERMINATE` for side-effecting
  non-`NATURAL`, `FAILED` for read-only *and* `NATURAL`). Rejected on §2: the
  `NATURAL → FAILED` half rests on a repeat following, which never does here.
- **A corrected tool-kind split** (`INDETERMINATE` for any side-effecting tool,
  `FAILED` only for read-only). Rejected on §2: it still needs a `trusted`
  declaration to classify, and the read-only precision is not worth the branch or
  the post-claim dependency.
- **No revalidation; catch the `KeyError`/`AttributeError` inside `_record`.**
  Rejected. It is piecemeal — it misses the non-`ToolResult`/`None` return and a
  raising serializer entirely — and it re-implements, by enumerating raises, the
  totality `ToolResult`'s own validator already expresses. Detach is the one
  guard that is total and that mirrors the inbound side.
- **Raise instead of commit.** Rejected: post-claim, raising is the stranding
  this exists to prevent.

### 6. What the implementation owes

- **`_detached_result` is total**: a revalidated, detached copy on success;
  the sentinel on a tampered `ToolResult`, a non-`ToolResult`/`None` return, or a
  serializer that raises an ordinary exception; `BaseException` still propagates.
- **An unusable return closes `INDETERMINATE` with `kind=None`**, and is not
  retried.
- **The close is unconditional over tool kind** — pinned on a read-only tool as
  well as a side-effecting one, so the rule is shown not to be tool-derived.
- **The pre-existing surfaces #270 names are covered**: the `outcome` lookup, the
  `FAILED`-branch and the `INDETERMINATE`-branch `failure` dereference, each via a
  `__dict__`-poisoned result; plus the non-result return and the raising
  serializer that motivate the broad catch.

## Consequences

**The returned-result seam is now defended symmetrically with the inbound call.**
`_detached` and `_detached_result` are the two halves of one discipline: the
executor trusts neither the object handed to it nor the object handed back across
a `frozen=True` boundary the threat model says can be bypassed.

**A read-only tool's unusable return records `INDETERMINATE`**, which is
conservative rather than precise (§2). If a consumer is ever found that needs
read-only unusable returns distinguished as `FAILED` — reading raw execution
state without the context to treat ignorance correctly — that is a refinement of
§2, not a reversal, and it would be the corrected tool-kind split weighed against
its post-claim `trusted` dependency.

**The guard is fail-safe but quiet.** A genuinely broken seam that always returns
garbage drives every step to `INDETERMINATE` rather than surfacing the wiring bug
loudly — the same trade `_refuse` already makes for a seam that always rejects.
The operational answer is monitoring an `INDETERMINATE` rate, not a louder
executor: the executor's job at this seam is to never strand and never guess, and
it now does neither.

**Recovery is unaffected.** Nothing changes about when `INDETERMINATE` fires from
the transition graph's perspective or how a recovery scan reads it; one more
live-executor path now reaches the state ADR-0029 §8 already established for it.
