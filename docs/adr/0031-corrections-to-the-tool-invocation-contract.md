# 31. Corrections to the tool invocation contract

- Status: Proposed
- Date: 2026-07-21
- Amends on ratification: ADR-0029 §§1, 3–4 and its Consequences. The edits are
  **not** made by this change — §7 records their exact form and why they wait,
  following ADR-0026 §6 and ADR-0030 §6.
- **Not breaking for any consumer.** No Protocol signature moves and no ratified
  type narrows. §1 adds a `core` name, §5's first clause binds `tools/`
  registration only (ADR-0018's Compatibility split), and the rest are
  specifications of rules ADR-0029 already states. It is still a substantive
  contract ADR — it changes the `core` surface — so it merges as its own PR
  ahead of any implementation (golden rule 5, ADR-0015 §5).
- Does **not** implement anything. The eighth `core` name is decided here and
  built by a later PR.

## Context

ADR-0029 was ratified without a spike, and its §10 says so in terms. It cites
ADR-0018's lesson — ADR-0016 "ratified a contract argued from consumers rather
than demonstrated by one, and first use found five things wrong" — names the two
questions a spike would have settled, and records the exposure in its own
Consequences: "every conforming implementation on day one will be a fake … the
mitigation is §10's spike-before-ratification … and it is a mitigation rather
than a cure."

PR #188 (`58aebb9`) landed the triad and was that first use. It found five
things, and the provenance is the point rather than an embarrassment, for the
reason ADR-0018 gives: review caught none of the three defects that mattered;
writing the code caught all three.

**Three were defects in the implementation, found by adversarial review across
four rounds and fixed there.** All three failed in the same direction, which is
the worst one available to this seam:

- a callable that catches its injected `CancelledError` and returns a value was
  reported `SUCCEEDED`, for a cancelled turn;
- a callable that catches the *deadline's* cancellation and returns was reported
  `SUCCEEDED`, for a side-effecting call that outran its budget;
- cancellation provenance was read as `Task.cancelling() > 0`, a lifetime count,
  so a caller that had absorbed an earlier cancellation would fail every later
  invocation on that task as cancelled — and would convert a tool's *invented*
  `CancelledError`, which §4 requires to be `INTERNAL`, into a cancellation.

Those are fixed on `main`. They are Context here because they are evidence about
the contract: each was a plausible reading of §4 as ratified, and the third was
the plausible reading. A rule that the obvious implementation gets wrong in the
direction of "a cancelled side-effecting call reported as success" is a rule the
ADR should state rather than imply.

**Two are defects in the contract**, and they are why this ADR exists:

1. **§4's interrupted-call rule has no `core` home.** The rule — `FAILED` when
   the tool is not `side_effecting` or its `idempotency` is `NATURAL`, otherwise
   `INDETERMINATE` — is applied in two places by ADR-0029's own text: at the seam
   on deadline expiry (§4), and by the executor on cancellation (§4, §8). It
   lives at `ai_assistant.tools.invocation.interrupted_outcome`, and
   `orchestration` cannot import `tools/` (golden rule 1, enforced by
   `lint-imports`). ADR-0029's Consequences enumerate the new `core` surface as
   exactly **seven** names, none of which is a home for a predicate, so the
   implementation honoured the enumeration rather than quietly exceeding it —
   correct, and this ADR is what changes it.

   **The duplication is not hypothetical and it is not one copy away.** It has
   already happened: `ai_assistant.testing.invoker` carries a private
   `_interrupted_outcome` that reimplements the same two-field comparison,
   deliberately, because the canonical fake "re-implements the rules rather than
   importing `ai_assistant.tools`: importing it would defeat the purpose". So
   the rule exists twice today with no executor written, and the executor lane
   would make three. That is exactly the shape ADR-0016 §2 argues against when it
   refused to relocate the severity ordering: "two copies of a safety-critical
   ordering, free to disagree, with nothing that fails when they do."

2. **`CANCELLED` is unreachable at the seam.** §4 scopes the member to "a genuine
   cancellation it observed and unwound from cleanly before the tool started
   work". But §4 also requires every genuine cancellation to propagate as a
   `CancelledError` rather than become a result, and it requires `timeout` to be
   strictly positive so there is no expired-before-starting branch. `invoke`
   therefore cannot construct one. The member exists, is exhaustively covered by
   `retryable` (§10 requires that), and is synthesised by nothing.

**And one is a residue that a reviewer asked to close, where the offered remedy
is worse than the hole** — issue #189, below in §4.

Two rules the implementation added, which §1 and §3 imply but do not state, are
ratified here rather than left as undocumented behaviour of one registry.

This ADR corrects; it does not reopen. Everything ADR-0029 decides that first
use did not touch stands, and §6 lists the parts most likely to be mistaken for
in-scope.

## Decision

### 1. §4's interrupted-call rule is `ToolDefinition.interrupted_outcome`, in `core/types.py`

```python
class ToolDefinition(BaseModel):
    ...

    @property
    def interrupted_outcome(self) -> ToolOutcome:
        """What a call of this tool, cut short by a deadline or a cancellation, means.

        ``FAILED`` when the tool is not ``side_effecting``, **or** its
        ``idempotency`` is ``NATURAL``; otherwise ``INDETERMINATE``
        (ADR-0029 §4).
        """
```

A read-only property on `ToolDefinition`, taking nothing beyond `self` and
returning a `ToolOutcome`. The rule's text is unchanged — this clause moves it,
it does not restate it.

**`core/types.py` is the right module, and ADR-0026 §1's reasoning is what
decides it rather than what forbids it.** That clause put `Clock` in
`core/clock.py` and "specifically not `core/types.py`", applying ADR-0016 §2's
restated convention:

> `core/types.py` holds no **subsystem logic**. It may hold semantics
> **intrinsic** to a type it defines.

— intrinsic meaning computable from the type's own declaration, independent of
policy, configuration, context and clock, and the same answer for every
consumer. `checked_clock` failed that test for a stated reason: "a guard that
calls an injected callable is not a semantic of a type at all." This predicate
passes it on every count. It reads two fields of `ToolDefinition` and nothing
else; it consults no policy, no settings, no context and no clock; and there is
one answer, which is the whole point of moving it. `ExecutionState.is_active`
and `FrozenDict` are the precedents ADR-0016 §2 names as already on the
intrinsic side of that line, and `ToolFailureKind.retryable` is ADR-0029's own:
a fact about a type "declared once in `core`", justified under the same
three-part test, and reachable as a property of the value that determines it.

**A property rather than a module-level function**, for the reason `retryable`
is one. The rule's failure mode is not that someone computes it wrongly; it is
that a second subsystem, holding a `ToolDefinition` and needing an outcome,
writes the two-line comparison itself because nothing in front of it says the
answer already exists. A property is the form that is in front of it: the
executor already holds the registry's definition — §4 requires that, and §8
requires `bound_tool` to name it — so `definition.interrupted_outcome` is
reachable from what the caller has in hand, with no import to discover and no
name to guess.

It also puts §4's most dangerous caveat at the call site rather than in a
docstring. §4 is emphatic that "the tool" means the registry's definition for
the committed `bound_tool`, never `call.request.tool`, because a declaration
mutated mid-flight would classify a possible side effect as
certainly-nothing-happened. Written as a property, the wrong version is
`call.request.tool.interrupted_outcome` — visible in the expression, on the
object, at the point of use.

**It is a plain `@property` and specifically not a `@computed_field`**, and the
distinction is load-bearing rather than stylistic. A computed field is included
in `model_dump()`, and ADR-0018 §4 requires a registry to store a definition
that is valid and detached — which `InMemoryToolRegistry` achieves by
`ToolDefinition.model_validate(tool.model_dump())`. `ToolDefinition` sets
`extra="forbid"`. A computed field would therefore make every registration of
every tool fail on the round-trip, and would additionally put a derived value
into any serialised definition, where a later reader could not tell it from a
declared one. Nothing about the model's data changes here: no field is added,
`model_dump()` is unchanged, construction is unchanged, and `==` — which §1's
seam check depends on being field-wise and total — is unchanged.

**`ToolOutcome` is declared after `ToolDefinition` in `core/types.py` today, and
that is fine**: the module sets `from __future__ import annotations`, so the
return annotation is a string resolved on demand, and the body runs long after
import. No reordering is required, and requiring one would be this ADR
specifying a file layout it has no reason to.

**The alternatives, and why each is worse.**

- **Leave it in `tools/` and let the executor write a second copy**, held
  together by the shared conformance suites. This is the option #187 names
  first, and it is the one ADR-0016 §2 rejected in the same situation for the
  same reason. The suites do not hold two copies together: they hold two
  *implementations of `ToolInvoker`* together, and the executor is not one. The
  copy that would diverge is the one nothing tests against the original.
- **A module-level function in `core/types.py`.** Same home, same import, and it
  loses the two properties above: it is not reachable from the value, and the
  `call.request.tool` misuse becomes an argument rather than a receiver.
  Marginal, and the margin is the whole reason to prefer the property.
- **A new `core/invocation.py`**, by analogy with `core/clock.py`. The analogy
  does not hold: `core/clock.py` exists because a guard that calls an injected
  callable is not a type semantic, and this is one. A module for a single pure
  function of a type declared two thousand lines away is a worse place to look
  for it, not a better one.
- **Widen `ToolOutcome` with a constructor** — `ToolOutcome.for_interrupted(definition)`.
  It inverts the dependency: an outcome enum that knows about tool declarations
  is a larger claim than a declaration that knows what interrupting it means,
  and `retryable`'s precedent points the other way.

**Migration, so the implementation PR has no discretion about it.**
`ai_assistant.tools.invocation.interrupted_outcome` is deleted, not kept as an
alias — a second name for one rule is the duplication in slower motion.
`_expiry_failure` reads `definition.interrupted_outcome`;
`ai_assistant.testing.invoker._interrupted_outcome` is deleted and its caller
retargeted; `tests/tools/test_invocation.py`'s table-driven case moves to
`tests/core/`, beside the type. The `tools/` module's `__all__` loses one entry.
No behaviour changes anywhere, which is what makes the diff reviewable as a move.

### 2. Cancellation provenance is a delta across the call, read on both paths

ADR-0029 §4 says the seam classifies on "whether a cancellation was actually
requested — of its own deadline, or of the invoking task". That reads as a
boolean, and it is not one. First use established three things it has to say
instead.

**(a) It is a delta, not a truth value.** `asyncio.Task.cancelling()` is a
*lifetime* count of cancellation requests delivered to the task, and only
`uncancel()` lowers it. A caller that absorbed an earlier cancellation in order
to finish some work, and then invoked a tool, carries a positive count into an
invocation nothing cancelled. So the seam captures the count **before** creating
or awaiting the callable, and treats only an **increase** across the call as a
cancellation of *this* call. Read as a boolean, the rule fails twice over: every
subsequent invocation on that task is reported as cancelled, and a tool's
invented `CancelledError` — which §4 requires to be `INTERNAL` — is promoted to
an external cancellation on the strength of something that happened before the
seam was entered.

**The delta is well-defined only because `asyncio.timeout` restores the count it
spends**, and that is worth recording because the rule silently depends on it:
`Timeout.__aexit__` calls `task.uncancel()` for the cancellation it injected on
expiry. Without that, every deadline expiry would also read as an external
cancellation, and §4's two branches would be indistinguishable.

**(b) It is evaluated on the normal-return path as well as the raising one.**
Nothing forces a callable to let an interruption through. One that catches its
`CancelledError` and returns a value leaves the seam holding an output and no
exception at all — so a seam that classified only in `except` clauses would
report `SUCCEEDED` for a cancelled turn, and for a side-effecting call that
outran its deadline. Both of those were live defects in the first
implementation. The obligation is therefore stated as a postcondition: **before
a `SUCCEEDED` result is constructed, the seam re-reads the deadline and the
cancellation delta, and an interruption found there wins over the returned
value.**

**(c) A cancellation observed after the callable absorbed it is raised afresh.**
The original was consumed inside the callable and there is nothing to re-raise.
What §4 requires is that a cancellation reaches the executor rather than being
answered with a result, and a newly constructed `CancelledError` satisfies that.

**(d) A pending cancellation takes precedence over an expired deadline.** Both
can be true at once — a shutdown that lands on a call already past its budget.
The cancellation must propagate (§4), and a result cannot be returned from a
task being torn down, so the cancellation branch is checked first and the expiry
result is not constructed.

**The tool-proof signal, named because "establish, don't infer" needs one.** §4
requires `TIMED_OUT` to key on *this* deadline having expired rather than on an
exception's type, and first use found the mechanism that makes that satisfiable:
`asyncio.Timeout.expired()` is the seam's own state, and no callable can reset
it. A tool raising Python's own `TimeoutError` well inside the budget leaves it
`False`, so the misclassification §4 describes — a call that failed fast and
provably did nothing, escalated to `INDETERMINATE` and out of retry — is refused
by reading the seam's state rather than by inspecting what was raised.

**The cancellation half has no equivalent, and §4 should not imply that it
does.** `cancelling()` is task state, and the callable runs on the task, so the
delta is evidence a cooperative callable cannot fake and an adversarial one can
move in **both** directions. Erasing it is §4 below. Manufacturing it is the
mirror case and is stated here so the rule is not read as stronger than it is:

> A callable that calls `cancel()` on its own invoking task, awaits, catches the
> resulting `CancelledError` and returns raises the delta with nothing outside
> having cancelled anything. The seam propagates a cancellation the caller never
> requested, and the executor commits the interrupted-call classification for a
> call that ran to completion.

**No signal distinguishes them, because `cancelling()` carries no provenance** —
it is a count of requests, not a record of who made them, and CPython exposes
nothing else. Three things make this the acceptable side of an unclosable
question rather than a defect to fix:

- **It fails in the safe direction**, unlike the three defects §2 corrects.
  Those reported `SUCCEEDED` for a genuinely cancelled or timed-out
  side-effecting call. This reports `INDETERMINATE` for a call that succeeded —
  pessimistic, never auto-retried, resolved explicitly (ADR-0014 §4), which is
  the ignorance-preserving direction that ADR refuses to guess against.
- **The task really is marked cancelling**, and that is not a fiction the seam
  invented. An unbalanced count is a damaged task: an enclosing `asyncio.timeout`
  or `TaskGroup` compares `uncancel()` against its own baseline, so returning
  normally and leaving the count raised corrupts every outer scope. Propagating
  is the more honest of the two available answers.
- **It is the same family as §4's declared limits** — a first-party callable
  sabotaging the seam that invoked it — and §1's residue analysis already covers
  it: "a callable that does not do what its equal declaration says".

So the delta establishes that *a cancellation of this task was requested during
this call*, which is what the rule may claim. It does not establish who
requested it, and §4's sentence is corrected to the first form rather than the
second.

### 3. `CANCELLED` is re-scoped to the tool's own upstream; the seam never synthesises it

The member stays. What changes is whose vocabulary it is.

> **`ToolFailureKind.CANCELLED` is what an integration reports when its own
> upstream cancelled or aborted the operation** — a remote job the provider
> stopped, a batch the service abandoned. **The seam never synthesises it.** A
> cancellation the seam observes propagates as a `CancelledError` and never
> becomes a result (§4); a deadline the seam owns is `TIMED_OUT`.

`retryable` stays `True`, for §3's reason unchanged: a repeat of the same call
could plausibly succeed. And it remains subject to the conjunction in §5 — a
retryable failure is not a retryable call.

**An integration reporting `CANCELLED` chooses its outcome by the same test §4
applies to the seam.** `FAILED` only if it can establish the effect did not
happen; `INDETERMINATE` otherwise. This is §4's existing sentence about
`TIMED_OUT` — "a tool that *can* establish it did not act may return `FAILED`
… nothing can make it prove the converse" — applied to the kind that has the
same shape.

**Removing the member was the alternative and is rejected.** It would narrow a
`core` enum (breaking, for a vocabulary integrations are meant to map onto),
delete a `retryable` answer §10 requires to be exhaustive, and leave a real
upstream failure with no honest kind: `REFUSED` means the upstream *declined*
the request, and `UNAVAILABLE` means it could not be reached. Neither describes
an operation the upstream accepted and then cancelled.

**Why this is a correction rather than a clarification.** As ratified, §4
describes a case its own contract cannot reach, and an implementer reading it
would look for the branch that produces one. There is none, and there should not
be: constructing a `CANCELLED` result at the seam would mean answering a
cancellation with a value, which is the thing §4 forbids everywhere else.

**No integration can report this kind today, and neither can it report five of
its peers — issue #192.** `ToolImplementation` returns `FrozenJson` and nothing
else, so an integration's only channel is to raise, which the seam turns into
`INTERNAL`. `INVALID_REQUEST`, `NOT_AUTHORISED`, `UNAVAILABLE`, `RATE_LIMITED`
and `REFUSED` are in exactly the same position: ADR-0029 §3 ratified the
vocabulary and ADR-0029 §1 deliberately left the callable's shape to `tools/`
("How the callable is reached is `tools/`-internal, and this ADR does not
contract it"), so the transport is a future integration ADR's — which is what
`ToolImplementation`'s own docstring already says. **This clause therefore moves
`CANCELLED` from unreachable-by-construction to unreachable-pending-a-decision,
and those are different states.** The first is a contract describing something it
forbids; the second is a deferral with an owner. Deferring the re-scoping until
that transport exists was the alternative and is rejected: it would leave §4
describing a seam branch that cannot be written, which is the defect. Nothing
here decides the transport, and #192 records that the retry algebra in §5 is
inert until it lands — an upstream 429 arrives as `INTERNAL`, which is not
retryable, where `RATE_LIMITED` is.

### 4. The `uncancel()` residue is a declared limit, and `SUCCEEDED` is qualified accordingly

**The case** (issue #189, found by adversarial review of #188). A callable
catches the externally delivered `CancelledError`, calls
`asyncio.current_task().uncancel()` on the task it does not own, and returns a
value. The count returns to its baseline, the delta in §2 is zero, and the seam
returns an ordinary `SUCCEEDED` result for an invocation whose task was
cancelled. §4 requires that cancellation to propagate. This is real, is
documented in `ai_assistant.tools.invocation._interruption`, and is not closed
here.

**The offered remedy — isolate the callable in a child task — is worse than the
hole, and it was measured rather than argued.**

```
direct await     -> caller sees KeyboardInterrupt   (propagates unchanged)
via child task   -> caller sees CancelledError      (converted)
```

Three things follow, and any one of them would be disqualifying:

- **It breaks §3's `BaseException` rule outright.** `Task.__step` handles a
  `KeyboardInterrupt` by setting it on the future *and* re-raising into the event
  loop, so the exception no longer propagates unchanged: it is converted at the
  awaiting frame and duplicated into the loop.
- **The conversion feeds a false positive straight into the classifier this
  finding is about.** The awaiting frame sees a `CancelledError` where a
  `BaseException` occurred, so an operator's Ctrl-C would be recorded as an
  external cancellation, and a side-effecting non-`NATURAL` step committed
  `INDETERMINATE` — a state §4 reserves for genuine ignorance and ADR-0014 §4
  makes durable and never auto-retried. Trading a narrow hole for a systematic
  misclassification of every `BaseException` is not a trade.
- **It acquires the watchdog shape §10 exists to prevent.** A child task is
  precisely the structure that makes it possible to abandon a callable at the
  deadline, and §10 pins the cooperative limit with a deterministic test so that
  "an implementation quietly acquiring a watchdog" fails the suite rather than
  passing review.

**So it is declared a limit, in the form §4 already uses for the cooperative
limit** — the third bullet of §4's "one event loop" list, which states plainly
that a tool suppressing its own cancellation can outlive its deadline and "the
honest position is that it is unclosable from this side". This is the same
family: a first-party callable, registered inside `tools/`, actively sabotaging
the seam that invoked it. §1's own residue analysis already names this class of
hazard — "a callable that does not do what its equal declaration says" — and
records that no Protocol closes it.

**What a caller may and may not conclude from `SUCCEEDED`**, stated because a
limit nobody can act on is not a limit:

- **May conclude:** the callable returned a value that validates as
  `FrozenJsonValue`; **this seam's deadline had not expired** when it returned;
  and **the invoking task's cancellation count did not rise across the call**.
  The deadline half is unqualified — `Timeout.expired()` is the seam's own state
  and §2 records why no callable can reset it.

  The third clause is a delta and must be read as one, on pain of restating the
  defect §2 corrects. A caller that absorbed an earlier cancellation without
  calling `uncancel()` carries a positive count into an invocation nothing
  cancelled, and that call returns `SUCCEEDED` — correctly, and the conformance
  suite pins it. So `SUCCEEDED` does not say the task carries no cancellation.
  Nor does it say none was requested during the call: that is precisely what the
  next bullet's erasure defeats. **The clause is the observable fact and nothing
  beyond it** — the seam saw no net increase from its entry baseline — and every
  inference from that to what happened is the caller's, bounded by the two
  bullets below.
- **May not conclude:** that the invoking task was never cancelled during the
  call. A callable that catches its `CancelledError` and uncancels the task
  erases that evidence, and no seam running the callable in its own frame can
  restore it.
- **Consequence for the executor:** a cancellation erased this way is not
  delivered, so the step commits `SUCCEEDED` and the executor's cancellation
  branches (§4, §8) do not run. The mitigation is §4's existing one and is
  unchanged: the loop keeps running, and shutdown still proceeds, because the
  party that requested the cancellation is the one tearing the process down.
- **What is *not* claimed:** that the effect did not happen. A callable that
  reaches this state ran to completion, so `SUCCEEDED` is not a lie about the
  side effect — it is a lie about the interruption.

**And the limit is pinned as a limit**, exactly as §10 pins the cooperative one:
the shared conformance suite gains a catch-and-`uncancel`-and-return callable
and asserts the ordinary result, so a later implementation that closes the hole
by acquiring a child task fails the suite and has to come back through an ADR.
#189's other option — an amendment that moves the callable into a child task and
restates §3 and §4 around it — is **rejected**, on the measurement above.

### 5. Two rules first use added, ratified rather than left as one registry's behaviour

Both are implemented and tested on `main`. Neither changes anything ADR-0029
decides; each states a half of a rule it spells out only in the other half.

**(a) Rebinding a *callable* under a live id is refused** (amends §1). §1 binds
the pair — "one mapping from id to `(definition, callable)`" — and then spells
out the declaration half alone, inheriting ADR-0018 §5's rule that an identical
re-registration under a live id is idempotent and a different definition is
refused. The callable half needs the same answer for the same reason: leaving
the approved declaration in place while other code runs behind it is ADR-0016
§7's named failure — "executing an implementation whose risk declaration is not
the one the user approved" — reached from the other direction. The full rule for
a live id becomes: **identical means both halves identical**; a different
definition is refused; a different callable under an equal definition is
refused.

- **Sameness of the callable is identity, not equality**, because a callable has
  no useful equality: two closures built from the same source are unequal, and
  `==` on a bound method compares `__self__` and `__func__` rather than
  behaviour. Identity is total, cheap, and errs closed.
- **The cost is named rather than hidden.** ADR-0018 §5 kept identical
  re-registration idempotent so "a composition root may run twice without
  special-casing". A root that rebuilds its closures on each run now fails that
  second run. That is the correct direction — a fresh closure is a fresh
  implementation as far as this registry can tell — and the fix is one a root
  can make: bind once, register twice.
- **Scope: a `tools/` registration invariant, not a Protocol obligation**, by
  ADR-0018's Compatibility split. No consumer of `ToolRegistry` or `ToolInvoker`
  can reach `register`, so no consumer can be broken by it. It is tested against
  `InMemoryToolRegistry`; the canonical fakes are held to the query and
  invocation contracts and nothing more, and ADR-0018's narrow fidelity
  carve-out — the fake refuses two bindings under one id, because that is the
  arrangement mistake a consumer could plausibly make — is unchanged.

**(b) A validator does not interpolate the fields a tool fills** (amends §3).
§3 already forbids the *seam* from interpolating `str(exc)` into a message, with
a specific reason: `core/logging.py` redacts by key, its own docstring names
`error=str(exc)` as the Tier 1 leak it cannot see, and `message` lands under
exactly such a key. A `ValidationError` raised by a `core` validator lands in the
same place and is not covered by that sentence. The rule extends to where it was
already needed, and it is stated by enumeration rather than by a category, so
that what it binds cannot drift:

> **No validator on `ToolCall`, `ToolResult` or `ToolFailure` interpolates
> `ToolResult.output` or `ActionRequest.parameters`.** It may name their type.

Those two are the fields a *tool* fills, typed `FrozenJsonValue` and
`FrozenJsonMapping` — unbounded content the system did not author, carrying
Tier 1 data routinely. The concrete case is `ToolResult`'s cross-field check: a
non-`SUCCEEDED` result carrying an output is refused with a message naming
`type(self.output).__name__`, because the natural message — the one that helps
most while debugging — would put a tool's output into a `ValidationError` bound
for a log. `ToolCall`'s authorisation validator is under the same rule, where
the tempting value is `parameters`.

The cost is the same one §3 already accepted for the seam's `INTERNAL` message,
and it is accepted here for the same reason: a thinner diagnostic beats a
disclosure on the failure path of every tool nobody thought about.

**What this deliberately does not decide: whether an identifier may appear in a
log-bound message — issue #197.** `ToolCall._authorised` names `decision.id` in
its rejection today, and `Identifier` refuses only a blank while
`PermissionDecision.from_request` takes the id as an argument, "minted by the
caller that records". So nothing in the type system says that message is
Tier 2-safe.

**It is a real question and it is not this ADR's**, on ADR-0018 §2's own
reasoning. Every available resolution reaches outside `tools/`: bounding the
type is a change to an identifier `planning` shares, which ADR-0018 §2 refused
to make from a tools ADR and deferred to **#62**; obliging every caller that
mints a decision or step id binds `planning` and `permissions` from a document
that decides neither; and stripping ids from messages closes the smallest share
of the exposure, since ADR-0021 §4 writes the same id into the audit trail and
ADR-0014 §3 into `StepExecution.approval_ref` and `error`. A blanket rule here —
*never interpolate a value you are validating* — was an earlier draft of this
clause and quietly picked the third, while also falsifying itself:
`ToolResult._outcome_fields_match` names `self.outcome`, one of three declared
constants, deliberately.

So the enumerated rule above is exactly what first use produced, and #197
carries the identifier question to a cross-lane ADR that can amend the contracts
it touches. Nothing in this ADR ratifies the `decision.id` message, and nothing
forbids it; it predates this decision and outlives it unchanged.

### 6. What this does not change

Named because a corrections ADR reads like an invitation to reopen.

- **Every rule in §1, §2 and §5 not listed above.** The biconditional and its
  wiring residue, two Protocols rather than one, the three seam checks and their
  fixed order, `ToolCall`'s unconstructability, the derived key, the retry
  conjunction, the fail-closed window reading, and an approval not being consumed
  by executing it.
- **§4's ownership of the deadline** — required, keyword-only, strictly
  positive, checked rather than trusted, enforced at the seam and not by the
  caller — and its classification rule's *text*, which §1 moves without altering.
- **§3's failure-as-data decision, `retryable`'s values, and the Tier 2 rule on
  `message`.**
- **§6's credential rule.** No credential crosses this seam in either direction,
  and `SecretStore` stays uncontracted.
- **§7's exclusions and §8's executor obligations.** §8 is the executor lane's to
  discharge (issue #187), and this ADR deliberately discharges none of it: it
  removes the reason the executor would have had to duplicate a rule, and nothing
  else. Findings that restate §8 belong to #187.
- **§10's triad requirement and the suite obligations**, extended in §8 below,
  not replaced.

### 7. What ratification does to ADR-0029

ADR-0017 §7 requires the operation performed on an amended ADR to be recorded
rather than inferred, and ADR-0026 §6 sets the form for an ADR that merges as
`Proposed`: the edit is **not** made by this change, because writing "amended by
ADR-0031" onto a ratified ADR while ADR-0031 is only proposed is the state claim
ADR-0019 forbids. Recorded here in the exact form to apply on ratification.

**It earns a `Status` line change, and ADR-0029 §9's own test is what decides
it.** That clause left ADR-0016's status alone because a later ADR taking up an
*explicit deferral* changes nothing in the earlier decision, and ADR-0030 §6
reached the same question days later and answered it the other way, because
"ADR-0023 §2 and ADR-0026 §2 each ratify a check, and this ADR narrows the set of
values that check accepts". This is the ADR-0030 case. Nothing was deferred:
§4 ratifies a classification rule and a scope for `CANCELLED`, and the
Consequences ratify an enumeration. Three ratified sentences now read as false or
unreachable — the seam "classifies on whether a cancellation was actually
requested" (a boolean where it is a delta on two paths), `CANCELLED` covering
"a genuine cancellation it observed and unwound from cleanly before the tool
started work" (a case `invoke` cannot construct), and "seven". That is a change
to a past decision in ADR-0001's sense.

**§5's two clauses would have earned only a note on their own**, since each adds
an obligation §1 and §3 imply and falsifies no sentence. They are carried by the
same `Status` line rather than given a second mechanism, because a `Status` line
records that the ADR was amended, not how many times.

- **ADR-0029's `Status` line becomes**
  `- Status: Accepted, §§1, 3–4 and Consequences amended by ADR-0031`.
- **A dated note is appended to ADR-0029's header, after the `Date` line:**

  `Amended: <ratification date> by ADR-0031 — the corrections first use found
  (PR #188). §4's interrupted-call rule gains a core home and is
  ToolDefinition.interrupted_outcome, a read-only property in core/types.py, so
  the seam, the canonical fake and the executor read one copy of it; the rule's
  text is unchanged. §4's cancellation provenance is a delta on
  asyncio.Task.cancelling() captured across the call, evaluated on the
  normal-return path as well as the raising one, with the deadline established
  from asyncio.Timeout.expired(), which no callable can reset; a pending
  cancellation takes precedence over an expired deadline. The delta establishes
  that a cancellation of this task was requested during this call, not who
  requested it: cancelling() carries no provenance, so a callable that cancels
  its own invoking task is propagated as a cancellation, which is the safe
  direction. §4's CANCELLED is
  re-scoped — the seam never synthesises it, and it is what an integration
  reports when its own upstream cancelled the operation. §4 gains a fourth
  limit, in the form of the cooperative one: a callable that catches its
  cancellation and calls uncancel() on the invoking task erases the seam's
  evidence and the call returns an ordinary result (#189). §1 gains the callable
  half of the rebinding refusal, a tools/ invariant; §3 gains the rule that a
  validator on these types never interpolates ToolResult.output or
  ActionRequest.parameters — the fields a tool fills — and names their type
  instead; whether an identifier may appear in a log-bound message is #197's and
  is untouched. The new
  core surface is eight names, not seven. Everything else in §§1, 3-4 stands as
  ratified: the biconditional, the three seam checks and their order, failure as
  data, retryable, the seam's ownership of the deadline and its classification
  rule, and the cooperative limit.`

- **The note ends by enumerating the sentences it supersedes**, because a reader
  who consults ADR-0029 alone must not be able to act on one of them. Appended
  to the note above, in the same block:

  `Superseded sentences in ADR-0029, which stand in the document unedited: §3's
  CANCELLED gloss "cancelled before completing" and its retryable rationale
  "CANCELLED is true because the cancellation was ours" — the value stays True,
  for §3's general test, that a repeat of the same call could plausibly succeed;
  §4's paragraph "The CANCELLED failure kind covers the narrower case the seam
  itself can report — a genuine cancellation it observed and unwound from
  cleanly before the tool started work", which describes a branch invoke cannot
  construct and must not grow; §4's "the seam therefore classifies on whether a
  cancellation was actually requested", which is the delta above rather than a
  boolean; and the Consequences' "seven".`

- **No ratified text is rewritten**, which is the form ADR-0018 set for
  ADR-0016, ADR-0026 §6 restated, ADR-0030 §6 followed, and ADR-0016's own
  header carries today: a `Status` line and a dated note, with the superseded
  clauses named in the header rather than edited in the body. An earlier draft
  of this clause rewrote the Consequences' enumeration in place while leaving
  three other sentences standing, which is both a second amendment vocabulary —
  the thing ADR-0017 §7 warns against — and the worse half of one, since it
  makes a reader assume the un-edited sentences were checked. The cost is
  ADR-0018's, accepted there and here: "a reader must consult both."

- **"The strongest case against this decision" is not edited either, and the
  reason is recorded rather than left to be rediscovered.** Its first sentence
  already reads "Eight new `core` names", which contradicted the Consequences'
  enumeration when ADR-0029 was ratified and is correct after this amendment.
  The contradiction was in the ratified document, not introduced here.

- **Nothing in ADR-0029 is edited at all.** The `Status` line and the dated note
  are the whole operation.

- **No other ADR is edited, and ADR-0016 in particular gets nothing** — not even
  a note. §1 adds a *property* to `ToolDefinition`, not a field: ADR-0016 §1's
  field list, `model_dump()`, construction, `frozen=True` and field-wise `==` are
  all unchanged, and ADR-0016 §2 is the clause that permits an intrinsic
  semantic on a `core/types.py` type in the first place. By ADR-0029 §9's own
  test — "whether a sentence in the other ADR would now read as false" — no
  sentence in ADR-0016 does. ADR-0014 and ADR-0021 are untouched for the same
  reason: §4's classification rule moves house without changing what it says, so
  the second trigger ADR-0014 §4's note already records is unaffected.

### 8. What the implementation PR owes

`ToolDefinition.interrupted_outcome` is a `core` addition rather than a new
Protocol, so `CONTRIBUTING.md`'s triad requirement is not re-triggered — there
is no new contract to fake. What is owed is the move, the deletions, and three
suite obligations:

- **The exhaustive table moves to `tests/core/`**, beside the type: all four
  combinations of `side_effecting` and `idempotency`, asserted rather than
  sampled, so the rule has one test as well as one definition.
- **Both seams keep their behavioural tests** — §10's "the timeout rule in §4 in
  both directions" is a statement about `invoke`, and it stays where it can
  observe one.
- **The `catch-and-uncancel-and-return` case is added to the shared conformance
  suite**, asserting the ordinary result, as §4 requires — the limit pinned as a
  limit, in the shape §10 uses for the cooperative one. Both `InMemoryToolRegistry`
  and `FakeToolInvoker` must agree, since the point is that neither quietly
  closes it.
- **`ToolFailureKind.CANCELLED`'s docstring is retargeted** from "Cancelled
  before completing" to §3's meaning — the tool's own upstream cancelled the
  operation, and the seam never synthesises it. A member docstring in `core` is
  where an integration author reads the vocabulary, so leaving it describing a
  seam branch that cannot exist is how the branch gets written anyway.
- **`tools.invocation.interrupted_outcome` and `testing.invoker._interrupted_outcome`
  are deleted**, and `lint-imports` still passes without a new contract: nothing
  in `orchestration` needs to import `tools/`, which is the outcome this ADR
  exists to produce.

§5's two clauses are already implemented and tested on `main`; ratification adds
no work for them, which is the point of ratifying behaviour rather than
inventing it.

## Consequences

- **The executor lane is unblocked without a second copy of a safety-critical
  rule** (#187). `orchestration` reads `definition.interrupted_outcome` from a
  definition it already holds, imports nothing from `tools/`, and cannot drift
  from the seam because there is nothing to drift from. This removes a live
  duplicate as well as a prospective one: the canonical fake carries the second
  copy today.
- **`core` carries an eighth name for this contract**, and the enumeration
  ADR-0029 ratified was the thing that stopped it being added quietly. That is
  the enumeration working: the implementation honoured a number it could not
  change, and the change arrives through an ADR with a recorded amendment rather
  than through a commit nobody reviewed as a contract change.
- **`ToolDefinition` gains behaviour, which is a line worth watching.** ADR-0016
  §2 drew it deliberately — intrinsic semantics yes, subsystem logic no — and
  every future proposal to hang something off this type has to pass the same
  three-part test. A predicate over two of its own fields passes; anything
  needing a registry, a clock or a policy does not, and the next one will be
  argued on those terms.
- **The obvious implementation of §4 no longer fails silently in the worst
  direction.** As ratified, the boolean reading of provenance and the
  exception-only classification were both natural and both reported a cancelled
  side-effecting call as `SUCCEEDED`. Three review rounds found them in one PR;
  §2 states the rules so that the next implementation does not have to.
- **`SUCCEEDED` is a qualified claim, and callers now know which half is hard.**
  The deadline half is tool-proof; the cancellation half is not. That is a
  weaker guarantee than §4 as ratified implies, and stating it is the whole
  value: the alternative was a stronger sentence that a first-party callable can
  falsify. The mirror case is stated too — a callable can *manufacture* a
  cancellation delta as well as erase one — so provenance is bounded on both
  sides rather than on the side that happened to be found first.
- **Five of the eight failure kinds still have no carrier** (#192), and
  re-scoping `CANCELLED` puts it in that group rather than outside it. ADR-0029
  §5's retry algebra stays inert until an integration ADR gives a tool a way to
  classify its own failure: today an upstream 429 arrives as `INTERNAL`, which
  is not retryable. This ADR does not decide that transport, and says so where
  it would otherwise be assumed.
- **A second privacy question is now named and open** (#197): `Identifier`
  bounds nothing, so `ToolCall._authorised` naming `decision.id` in a log-bound
  rejection rests on an assumption no type carries. §5(b) deliberately does not
  answer it — every resolution amends a contract this ADR does not own, which is
  ADR-0018 §2's reason for deferring the shared identifier to #62 in the first
  place. The cost of naming it rather than fixing it is that the assumption
  stays live; the cost of fixing it here would have been a tools ADR narrowing
  `planning`'s type.
- **#189 closes as a declared limit rather than a fix**, and the conformance
  suite pins it, so an implementation that later closes it by isolating the
  callable fails the suite and has to come back through an ADR. That is a real
  cost — the correct-looking remedy is now blocked by a test — and it is
  deliberate, because the remedy converts every `BaseException` into a
  `CancelledError`.
- **A composition root that rebuilds its callables cannot register twice.**
  ADR-0018 §5 bought idempotent re-registration precisely so a root could run
  twice; §5(a) narrows that to roots whose callables are stable objects. The
  fail-closed direction is right and the friction is real.
- **ADR-0029 becomes a two-document contract**, like ADR-0016 and ADR-0018
  before it. A reader must consult both, which is the cost ADR-0018 accepted for
  the benefit that the diff between the two decisions stays visible.
- **The workflow lesson repeats, and repeating it is the finding.** ADR-0018's
  verdict was "spike harder before ratifying"; ADR-0029 §10 quoted it, required
  a spike, named the two questions one would settle — and was ratified without
  one. First use then found the second of those two questions was exactly where
  the defects were: whether the tool's own `CancelledError` and the seam's expiry
  are distinguishable. The lesson is not new; what is new is evidence that
  restating it inside an ADR does not enforce it.
- **Revisit when** the executor lands and §8's obligations are discharged (does
  `interrupted_outcome` want a sibling for the executor's commit rule?), when a
  real integration first reports `CANCELLED` from its upstream, or if a Python
  release gives a seam a way to observe a cancellation the callable cannot erase
  — at which point #189's second option becomes cheap and this ADR's §4 is the
  thing to reopen.

### The strongest case against this decision

The blocking item is one property, and the rest is documentation of behaviour
that already exists — so this could have been an amendment note on ADR-0029 and
a one-line `core` addition in the executor's own PR, at a fraction of the cost.
Against that: golden rule 5 makes a `core` surface change its own PR, ADR-0029's
enumeration is exactly the sentence being changed, and ADR-0018's precedent is
that corrections from first use are a substantive ADR rather than an edit —
"that exemption is about *review cost* … and is not a grant of authority to
change a ratified decision in place."

The sharper objection is to §4. Declaring the residue a limit means shipping a
contract that a first-party callable can defeat, and writing a test that *pins*
the defeat — which will read, to someone who has not followed the argument, as a
test asserting a bug. The defence is that the alternative was measured and is
worse in a way that touches every shutdown rather than one adversarial tool, and
that §10 already established the form: a limit pinned as a limit is how this
contract stops a later reader assuming a guarantee it never had.
