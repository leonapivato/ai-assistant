# 33. Bounding the drain after a required source fails

- Status: Accepted
- Date: 2026-07-22
- Decides issue #211, raised by Codex against the ADR-0026 §4 implementation and
  triaged out of that PR. It is a behaviour decision for `context`, not a defect
  in required-source propagation, which is why it gets an ADR rather than a
  patch.
- **Not a contract change.** No Protocol moves, no `core` type or `Settings`
  field is touched, and `ContextProvider.assemble()`'s signature is unchanged.
  `source_timeout` is a constructor argument of `AssemblingContextProvider`,
  internal to `context/`. So golden rule 5's separate-PR requirement does not
  apply and this ADR merges with the implementation it authorises.
- **No ratified text changes here**, so this carries neither of the header
  fields that would record one. ADR-0026 §4 decides the required-source
  *marker*, and that a required source's failure reaches the caller with its
  cause intact. It says nothing about cancelling siblings, joining them, or
  leaving no work outstanding — that was an implementation choice taken in the
  PR that built it, written down only in a docstring. ADR-0001's procedure for
  changing a past decision is therefore not triggered, and ADR-0026's `Status`
  line stays as it is. What this ADR does to §4's actual requirement is
  *strengthen* it: today a cancellation-suppressing sibling stops that failure
  from arriving at all.
- Refs: ADR-0008 §4, ADR-0026 §4.

## Context

ADR-0026 §4 gave `context` its first source whose failure must *not* be
degraded. `AssemblingContextProvider._gather_contributions` therefore had to
grow a failure path it never had before: `asyncio.gather` propagates the first
exception but does not cancel its siblings, so a required source failing fast
beside an optional source blocked in I/O would return to the caller with that
source still running, still able to perform a late side effect for a request
that is over. The implementation cancels the siblings and then **awaits** them
before re-raising, and its docstring claims the method "never returns or raises
with work outstanding".

That claim holds only for sources that honour cancellation. Two shapes break it,
and they are not the same shape:

- **A source that suppresses `CancelledError` and keeps going.** The drain waits
  on it forever, so the required failure never reaches the caller. `assemble()`
  hangs; the request pipeline hangs behind it.
- **A source blocked in `asyncio.to_thread`.** Named alongside the first in
  #211, but it behaves differently and the difference matters below.

Both are misbehaviour by Python's cancellation contract, and neither is
introduced by the ADR-0026 diff: with `source_timeout=None` a hung optional
source already stalls `assemble()` on `main`, because `asyncio.gather` waits for
everything. The question is what the assembler owes a caller when a source
breaks that contract — and whether `source_timeout=None`, which the issue calls
"the one bound that exists", is one at all.

### What the runtime actually does

Four claims this decision rests on, each checked against CPython on this
project's interpreter rather than reasoned from the docs:

1. **`asyncio.timeout` does not bound a body that suppresses `CancelledError`.**
   The deadline fires exactly once, delivering a single cancellation; a body that
   swallows it runs on and the timeout never fires again. A task guarded by
   `asyncio.timeout(0.1)` was still not done after five times its deadline, and
   still not done after a further explicit `cancel()`. So a numeric
   `source_timeout` is **not** a defence against this failure mode.
   `source_timeout=None` disables nothing that would have caught it.
2. **Today's drain hangs, and wrapping it in `asyncio.timeout` does not fix
   it.** `await asyncio.gather(*tasks, return_exceptions=True)` never returns
   over a suppressor — and putting `asyncio.timeout` around that await also
   never returns, because the deadline's cancellation is delivered into the
   `gather`, which re-cancels the same suppressor and goes on awaiting it.
3. **`asyncio.wait(tasks, timeout=…)` does bound it.** `wait` observes the
   futures rather than awaiting them directly and does not cancel what is still
   pending, so it returns at its deadline with the suppressor in `pending`. It
   is the only primitive of the three that produces the behaviour this decision
   needs, which is why §1 names it rather than leaving the mechanism open.
4. **`asyncio.to_thread` is a different problem entirely.** Cancelling a task
   awaiting `to_thread` settles the await in ~0 ms; the *thread* runs to
   completion, detached, outside the event loop. So the second shape in #211
   never hangs the drain — it leaks a thread that no caller-side construct,
   bounded or not, can observe or stop. Nothing here addresses it, and nothing
   here can.

Claim 1 is the one that reframes the issue. The bound that a suppressing source
defeats is not `source_timeout`; it is every caller-side deadline
simultaneously.

## Decision

We will bound the post-cancellation drain and leave `source_timeout=None`
permitted, unchanged.

### 1. The drain is bounded, and the bound is not configurable

`_gather_contributions` keeps cancelling its siblings on a required failure, but
joins them with `asyncio.wait(tasks, timeout=_DRAIN_SECONDS)` instead of an
unbounded `gather`. Whatever is still pending at the deadline is **abandoned**,
and the original exception is re-raised.

`_DRAIN_SECONDS` is a module-level `Final` set to **1.0 second**. It bounds how
long the assembler *awaits*, which on a cooperating loop is the same as
wall-clock time; a source that blocks the loop outright suspends every timer in
the process and is outside what any caller-side construct can bound (see
Consequences). Three things about the number are the decision:

- **It sizes cleanup, not work.** The drain is not waiting for a source to
  finish contributing; it is waiting for a source that has already been told to
  stop to unwind. A cooperative source completes in a single event-loop turn —
  measured at ~0.1 ms — so 1.0 s is four orders of magnitude of headroom for a
  `finally` that closes a session, and still well inside any request budget a
  caller would notice.
- **It is deliberately not derived from `source_timeout`.** That parameter sizes
  *I/O*, and per claim 1 it is not a bound on this path in any case. Deriving one
  from the other would tie a cleanup budget to an unrelated network budget and
  imply a relationship that does not exist.
- **It is a budget, and it is enforced as one.** Anything still running when it
  expires is abandoned — a source that ignored cancellation, *and* a source
  whose cooperative `finally` is simply taking longer than a second. The
  assembler does not distinguish them because it cannot: a task that has not
  finished is indistinguishable from one that never will. So the number is
  falsifiable, by exactly one population — a source whose honest cleanup exceeds
  it — and that population is what the Revisit clause names. At 1.0 s it sits
  four orders of magnitude above a measured cooperative unwind (~0.1 ms), so a
  source that exceeds it is doing fresh I/O in its cleanup for a request that is
  already over.

It is a constant rather than a constructor argument because no source that
exists needs it to be anything else, and a per-construction knob would put a
tuning decision at every call site to serve a population of zero. If that
population ever becomes non-empty the Revisit clause applies — which is the
honest form of this, rather than claiming the value cannot matter.

### 2. A bounded drain does not stop the straggler, and does not claim to

This is the honest cost, stated plainly because it is the strongest thing that
can be said against §1: **the abandoned task is still running.** It keeps its
place on the event loop. It can still complete, still log, still perform the
late side effect for a finished request that ADR-0026's cancel-and-await was
added to prevent.

What makes §1 nonetheless right is that bounding does not *trade* propagation
against leakage. Compare the two branches in the case the bound exists for — a
source that suppresses cancellation:

- **Unbounded (today):** the task runs forever **and** the caller waits forever.
- **Bounded:** the task runs forever **and** the caller gets its failure.

The leak is identical in both, because a task that suppresses `CancelledError`
cannot be stopped by anything the assembler can do — awaiting it does not stop
it, it only adds the caller to the set of things stuck behind it. The second
branch dominates. The case for leaving the drain unbounded would be sound if
awaiting actually prevented the leak; claim 2 shows it does not.

The reverse case — where §1 costs something ADR-0026 bought — is narrow but
real, and it is not the suppressing source. A source that honours cancellation
and takes longer than `_DRAIN_SECONDS` to unwind is abandoned too, and for it
the drain genuinely does weaken ADR-0026 §4's join. That is the price, stated:
the budget is enforced on the clock, not on intent, because the assembler has no
access to intent. For a source that unwinds promptly — a single event-loop turn,
~0.1 ms in claim 5 — the bound never fires and cancel-and-join is ADR-0026 §4's
behaviour unmodified.

### 3. A detached task is the source author's, and it is logged, not silent

Nobody collects an abandoned task's result. Responsibility for what it does
afterwards belongs to **whoever wrote the source that suppressed cancellation** —
the assembler's obligation ends at: cancel it, join it for `_DRAIN_SECONDS`,
name it in a `warning` log, and stop waiting. There is no other party who could
hold it, since by construction the task will not respond to the one signal the
assembler has.

Two mechanical consequences of detaching, which the implementation carries so
that abandonment is deterministic rather than merely untidy:

- **A strong reference to each abandoned task is retained** until it completes.
  `asyncio` holds only weak references to running tasks, so an abandoned task
  can be garbage-collected mid-flight and vanish — turning a leak we described
  into non-deterministic behaviour we did not.
- **A done-callback consumes the eventual outcome**, drops the reference, and
  records the failure's class at `debug`. `asyncio.wait` does not consume a
  pending task's exception, so a straggler that fails after the request is over
  would otherwise leave one unread. Be precise about how much this buys: on
  *this* path the abandoned `gather` still holds a done-callback on each child,
  and CPython's marks a late exception retrieved itself once the outer future is
  done — so the "exception was never retrieved" report would not actually
  appear. The callback is therefore not the only thing standing between us and
  that report; it is what makes the outcome *observable* — a straggler's late
  failure is logged, with its class rather than its message (ADR-0004 §5), where
  otherwise it would be swallowed silently by an implementation detail of
  `gather` that nothing here controls.

The `warning` names the sources, not the exception: the log is `context`'s and
ADR-0004 §5 keeps Tier 1 content out of it, exactly as the existing degradation
log already records `type(exc).__name__` rather than `str(exc)`.

It also says *why* it gave up, in the only two terms the assembler can tell
apart: the drain **outlasted its budget**, or it was **interrupted** — the
caller cancelled `assemble()` before the budget was spent, so tasks were
abandoned early through the same `finally`. The wording is separated because a
drain cut short after ten milliseconds of a one-second budget has learned
nothing about the source, and reporting it as one that "outlasted the drain"
would point the diagnostic at the wrong party. Within each, whether a source
ignored cancellation or was merely slow to unwind stays undistinguished — that
one the assembler genuinely cannot answer (§1).

### 4. `source_timeout=None` stays permitted

We will not forbid it, narrow its type, or validate against it.

- **It does not disable the bound that matters.** Per claim 1, a numeric
  `source_timeout` does not bound a suppressing source either — so forbidding
  `None` buys exactly nothing against #211's failure mode, while presenting
  itself as a fix for it. §1's drain bound is the bound that protects failure
  propagation, and it is unconditional: no caller can turn it off.
- **It has a legitimate use.** A source whose own client already carries a
  deadline does not need a second, coarser one layered on top, and tests
  configure `None` to make cancellation behaviour observable rather than racing
  a timer — `test_a_required_failure_cancels_its_still_running_siblings` does
  precisely that.
- **What it genuinely costs is stated instead of removed.** With
  `source_timeout=None` and a cooperative but slow optional source,
  `assemble()`'s *success* path has no deadline at all: `gather` waits for
  everything. §1 does not change that, because the drain only runs after a
  failure. That is what the caller asked for by passing `None`, and the
  docstring now says so: `None` transfers the assembly deadline to the caller,
  who is then expected to impose one.

A parameter that hands an obligation to the caller is a legitimate design as
long as the obligation is written down. Removing the parameter to avoid writing
it down would be a narrowing of a documented seam with no failure mode retired.

### 5. The docstring must end up true

`_gather_contributions`' "never returns or raises with work outstanding" becomes
false the moment §1 lands, and was already conditional before it. It is replaced
with the qualified claim: a source that unwinds within `_DRAIN_SECONDS` is
finished when this method returns or raises; anything still running past that
budget is abandoned, still running, and logged. It is stated as a *budget* and
not as "a source that honours cancellation", because those are not the same set
and the assembler can only observe the first. The abandonment log says the same
— it reports that a source outlasted the drain, not that it ignored
cancellation.

### 6. Rejected

- **Ratify the status quo — leave the drain unbounded.** The serious option, and
  the one #211 makes the honest case for: the failure requires a source that is
  already misbehaving, no such source exists, and detaching is a real regression
  against ADR-0026 §4's intent. Rejected on §2's asymmetry. `context` is
  *advisory* (ADR-0008 §4, VISION §7) — the subsystem whose entire failure
  doctrine is "a source fault must not take down the request pipeline". An
  unbounded drain lets one optional source take down the pipeline permanently and
  without a diagnostic, which is the exact outcome §4 exists to forbid, and it
  does not buy containment in exchange.
- **Make `_DRAIN_SECONDS` a constructor argument.** §1: a knob no conforming
  source can observe.
- **`asyncio.timeout` around the existing `gather`.** The obvious spelling, and
  it does not work — claim 2.
- **Forbid `source_timeout=None`.** §4. Beyond buying nothing, it is a narrowing
  of an existing seam, and this ADR takes no position on when narrowing needs its
  own decision (issue #198 is open on exactly that); it declines to settle that
  question sideways by acting on it.
- **`asyncio.TaskGroup` in place of `gather`.** Its `__aexit__` awaits its
  children unconditionally and offers no deadline, so it is today's drain with
  less control over it, not a fix.

## Consequences

- **A required source's failure now always reaches the caller**, after at most
  `_DRAIN_SECONDS` spent *awaiting* the others. That is the property #211 is
  about. Read it as a bound on what the assembler waits for, not as a wall-clock
  guarantee: a source that **blocks the event loop** during cleanup — a
  synchronous `time.sleep`, a tight CPU loop — defers every timer in the
  process, this drain's included, and nothing available to a single-threaded
  loop can pre-empt it. That is a property of the loop rather than of this
  decision, which neither creates it nor can fix it; `CONTRIBUTING.md`'s "No
  blocking calls on async code paths" is what rules it out. For a source that
  keeps yielding, the bound is the wall-clock one.
- **`assemble()` can now leave a task running.** Any source still running when
  the drain expires produces one, whether it ignored cancellation or was merely
  slow to unwind. It is unbounded in *duration*,
  and bounded in *count* at one per source **per assembly** — which is not a
  bound per process: a permanently-suppressing source leaks one task, and one
  `_abandoned` entry, for every `assemble()` that ends in a required failure, so
  repeated requests grow both without limit. **No cap is imposed, deliberately.**
  The leak is the *task*, which exists whether or not this module holds a
  reference to it; capping the set would drop references without stopping
  anything, restoring the mid-flight garbage collection §3 rules out and making
  the leak invisible rather than smaller. What contains it instead is that the
  `warning` fires per abandonment, so a recurring leak is a recurring log line.
  Before this change the count was one only because the first such failure
  deadlocked the caller and there was never a second request — an accounting the
  bound is worth losing.
- **Nothing changes for a source that unwinds promptly.** The bound never
  fires, the join costs a fraction of a millisecond, and cancel-and-join is
  ADR-0026 §4's behaviour unmodified. A source whose cooperative cleanup exceeds
  the budget *is* affected — it is abandoned like any other straggler — which is
  §1's deliberate choice to enforce on the clock rather than on intent.
- **The bound covers the required-failure path only, and one adjacent path stays
  unbounded.** If the *caller* cancels `assemble()` while a suppressing source is
  running, `asyncio.gather` does not yield that cancellation until every child
  has finished — so the drain never runs, and an `asyncio.timeout` the caller
  wraps around `assemble()` is swallowed exactly as the per-source one is. That
  is unchanged from before this decision and is not made worse by it, but it
  means §4's "the caller owns the deadline" is a weaker offer than it sounds
  against this one class of source. Fixing it means not using bare `gather` on
  the success path at all, which is a larger change than #211 asks for; it is
  filed rather than folded in (issue #231).
- **`context` gains its first deliberately-detached work.** No other subsystem
  abandons a task today; if a second one needs to, this is the precedent to
  argue from or against, not a pattern to copy without one.
- **The `to_thread` half of #211 is not addressed and is not addressable here**
  (claim 4). A source that blocks a worker thread leaks that thread whatever the
  assembler does. If that becomes real, the fix belongs in the source — the only
  place that holds the thread — not in the assembler.
- **Revisit when** a source genuinely needs a long cleanup, which would make
  `_DRAIN_SECONDS` a number someone conforming can observe and therefore a real
  parameter; or if `assemble()` ever acquires an overall deadline of its own, at
  which point §4's transfer of that obligation to the caller stops being the only
  option.

### The strongest case against this decision

It adds a constant, a log, a reference set and a done-callback to defend against
a source nobody has written, in a subsystem with one source in it — and it does
so by *weakening* a guarantee a change one day old deliberately strengthened. ADR-0026 §4 established cancel-and-join specifically so that no
source outlives its request; this ADR carves the first exception into it before
that guarantee has met a single real source. The cheaper answer was available:
write down that a source must honour cancellation, and let a source that does
not be a bug in that source.

The answer, and it is not a complete one: the convention argument is the one
ADR-0026's own "strongest case against" section already lost. A documented
obligation that only misbehaviour violates is still an obligation something has
to hold when it is violated, and here the thing holding it is the request
pipeline, indefinitely, with no diagnostic. The guarantee being weakened was
also never as strong as its docstring said — claim 2 shows the join does not
hold a suppressing source, it only hides that it has not. What this change
actually does is make the existing guarantee's real boundary visible and put the
caller on the safe side of it.
