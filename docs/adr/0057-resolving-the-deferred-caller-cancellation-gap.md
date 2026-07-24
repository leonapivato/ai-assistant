# 57. Resolving the deferred caller-cancellation gap: `assemble()` observes its sources

- Status: Accepted
- Date: 2026-07-24
- Resolves issue #231, which ADR-0033 filed rather than folded into its own PR.
  It is a behaviour decision for `context`, the completion of a follow-up
  ADR-0033 named and deferred — which is why it gets its own ADR under ADR-0001
  rather than riding in silently on the fix.
- **Supersedes one consequence of ADR-0033.** ADR-0033's Consequences bullet
  "The bound covers the required-failure path only, and one adjacent path stays
  unbounded … it is filed rather than folded in (issue #231)" no longer holds:
  that path now honours the caller's deadline. ADR-0033's `Status` is updated to
  link here (ADR-0001's procedure for changing a past decision). Nothing else in
  ADR-0033 changes — §§1–3's drain, its `_DRAIN_SECONDS` bound, and §4's
  permission of `source_timeout=None` all stand and are reused unchanged.
- **Not a contract change.** No Protocol moves, no `core` type or `Settings`
  field is touched, and `ContextProvider.assemble()`'s signature is unchanged;
  the change is internal to `AssemblingContextProvider`. So golden rule 5's
  separate-PR requirement does not apply and this ADR merges with the
  implementation it authorises, exactly as ADR-0033 did for #211.
- Refs: ADR-0033 §4 and Consequences, ADR-0026 §4, ADR-0008 §4.

## Context

ADR-0033 bounded the drain that runs *after* a required source fails, but
explicitly left the success path on a bare `await asyncio.gather(*tasks)` and
recorded the gap as a deferred consequence:

> **The bound covers the required-failure path only, and one adjacent path stays
> unbounded.** If the *caller* cancels `assemble()` while a suppressing source is
> running, `asyncio.gather` does not yield that cancellation until every child
> has finished — so the drain never runs, and an `asyncio.timeout` the caller
> wraps around `assemble()` is swallowed exactly as the per-source one is. …
> Fixing it means not using bare `gather` on the success path at all, which is a
> larger change than #211 asks for; it is filed rather than folded in (issue
> #231).

The gap, stated precisely: `asyncio.gather` does not yield a cancellation until
every child finishes, so a source that suppresses `CancelledError` swallows the
caller's own deadline whole — the caller's `asyncio.timeout`, a shutdown, or a
cancelled request never surfaces, and the request pipeline hangs behind the
source. ADR-0033 §4 offered the caller that deadline ("with `source_timeout=None`
the caller owns the deadline") but flagged, in the same breath, that the offer
was "a weaker offer than it sounds against this one class of source."

ADR-0033 deferred the fix with a specific open question: whether "the success
path should be bounded at all." This ADR answers it.

## Decision

**We will observe the sources with `asyncio.wait` rather than await a bare
`asyncio.gather`, so a caller's cancellation of `assemble()` is honoured — routed
through ADR-0033's bounded drain and re-raised — even against a source that
suppresses cancellation.** This resolves #231 and makes ADR-0033 §4's offer real.

The answer to ADR-0033's deferred question is that the success path is *not*
being bounded. No numeric deadline is imposed on a well-behaved source, and
`source_timeout=None` still means the caller owns the deadline (§4 is unchanged).
What changes is only that the caller's *existing* deadline is now **observed**
instead of swallowed. That is §4's promise made honest, not a new bound — which
is why it resolves the deferral rather than reopening §4.

Concretely, in `_gather_contributions`:

1. **Observe, don't await.** The sources run as tasks driven by a loop on
   `asyncio.wait(pending, return_when=FIRST_COMPLETED)` instead of
   `await asyncio.gather(*tasks)`. `asyncio.wait` observes its tasks rather than
   awaiting them, so a caller's `CancelledError` surfaces at the `wait` promptly
   instead of being deferred until every child has finished.
2. **Drain on the caller's way out.** A cancellation caught at the `wait` cancels
   the siblings and joins them under ADR-0033 §1's `_DRAIN_SECONDS` bound, then
   re-raises. A suppressing source is abandoned exactly as on the
   required-failure path — the same asymmetry ADR-0033 §2 accepted: the task
   keeps running, the caller is freed.
3. **A cancelled child is terminal too.** The first task that failed *or was
   cancelled*, in source order, ends the assembly. `FIRST_COMPLETED` rather than
   `FIRST_EXCEPTION` because the latter does not treat a *cancelled* task as a
   raised exception (verified against CPython) — a required source that raises
   `CancelledError` beside a suppressing sibling would otherwise leave `wait`
   pending forever. This reconstructs, by hand, `gather`'s first-exception *and*
   first-cancellation propagation, a cancelled child's own `CancelledError`
   (args and cause intact) included.

### What does not change

- **`source_timeout=None` stays permitted** (ADR-0033 §4). No numeric bound is
  added to the success path.
- **The drain is reused, not modified.** Its `_DRAIN_SECONDS` bound, the
  abandonment, the strong-reference set, and the done-callback (ADR-0033 §§1–3)
  are untouched; the caller-cancellation path simply routes through the same
  `_drain`.
- **`assemble()`'s signature and `CurrentContext` are untouched.**

### Rejected

- **Keep the bare `gather`.** That is exactly the swallowing #231 is about;
  ADR-0033 recorded it as a real gap, not a preference.
- **Wrap `assemble()` in an internal `asyncio.timeout`.** A suppressing source
  swallows an inner timeout the same way it swallows the caller's (ADR-0033
  claims 1–2). It would present a fix while delivering none.

## Consequences

- **A required source's — and now a caller's — cancellation both reach the
  caller within `_DRAIN_SECONDS` of awaiting.** The property ADR-0033 gave the
  required-failure path is extended to the caller-cancellation path. Issue #231
  is closed by this change.
- **`assemble()` can leave an abandoned task on the caller-cancellation path
  too.** One per suppressing source per cancelled assembly — bounded in count
  per assembly, unbounded in duration, logged — the same accounting ADR-0033's
  Consequences already give for the required-failure path, now reached from a
  second entry point. The leak ADR-0033 accepted is unchanged, only extended;
  nothing the assembler can do stops a task that suppresses `CancelledError`, so
  awaiting it would only add the caller to what it blocks (ADR-0033 §2).
- **The success path costs a few extra event-loop wakeups** — a
  `FIRST_COMPLETED` loop rather than a single `gather` await — negligible for the
  small number of sources context assembles.
- **ADR-0033's deferred consequence is retired, and the ratified text it lived in
  is left in place** (ADR-0001 is append-only). A reader of ADR-0033's
  "one adjacent path stays unbounded" bullet is pointed here by ADR-0033's
  updated `Status`.
- **Revisit** alongside ADR-0033's Revisit clause; nothing here changes when to
  reconsider `_DRAIN_SECONDS` or `source_timeout`.
