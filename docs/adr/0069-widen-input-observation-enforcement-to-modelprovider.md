# 69. Widen input-observation enforcement to ModelProvider

- Status: Accepted
- Date: 2026-07-25
- **This is an enforcement-scope decision, not a Protocol-surface change.** It
  adds and rewords no Protocol, method, or exchanged type; the input-observation
  clause it enforces already binds every Protocol, `ModelProvider` included, since
  ADR-0065. What it changes is ADR-0065 §3's *shared conformance enforcement* — it
  widens the set of seams the shared suites must check to a third, `ModelProvider`.
  Golden rule 5 / ADR-0015 §5's Protocol-change trigger therefore does **not**
  apply: ADR-0065 §4 and ADR-0060 §5 both hold that "a contract is what is
  written; a suite samples it," so widening enforcement is not a contract-surface
  change. It is nonetheless handled *like* one — its own docs-only PR, ratified
  ahead of the implementation lane, and reviewed under **both** lenses — because
  it amends a ratified contract ADR's enforcement scope (the architecture
  reviewer's rubric: contract discipline and ADR adherence) and the
  `ModelProviderContract` case depends on this decision being ratified first
  (`CONTRIBUTING.md`, "Contract ADRs land before their implementation"). It
  touches no `core/protocols.py`, no conformance suite, and no implementation. The
  `ModelProviderContract` case and its fixture-supplied suspension hook are a
  separate follow-up lane, dispatched after this ADR merges.
- Refs: ADR-0065 (the clause and its §3/§4, this ADR amends §3), ADR-0060 (the
  sibling clause and the observability asymmetry §2 rests on), ADR-0056 (the
  origin tear), ADR-0011 and ADR-0013 (ModelProvider composes by wrapping),
  ADR-0001 (append-only amendment discipline).
- Source: issue #388; grounded in #380 / PR #384 and issues #367, #378.

## Context

ADR-0065 stated a module-level clause on every Protocol in `core/protocols.py`:
*a call observes its inputs at one instant, before its first await.* It then
made a deliberately narrower decision about **enforcement**: §3 scoped the
shared conformance cases to `MemoryStore` and `MemoryWriter`, "those two because
they are where the rule has been broken." Everything else the clause binds sits
in §4's **bound-and-unenforced** category — bound the day the clause landed,
enforced by a shared suite only where §3 says so.

That scope has been overtaken by facts §4 itself did not have, and this is the
third time the general question — *which bound seams earn a shared conformance
case, and why* — has been answered locally without being written down. ADR-0060
§2/§5 answered it for the cancellation clause and left `Embedder`/`ModelProvider`
as filed follow-ups (#347, #378). ADR-0065 §3/§4 answered it for the
input-observation clause and left `Planner`/`PlanStore`/`ModelProvider` behind.
Each new lane rediscovers the same gap. The lasting value of this ADR is the
**general trigger**; widening `ModelProvider` is the instance that forces it.

### `ModelProvider` now meets ADR-0065 §3's own stated criterion

§4 originally listed `ModelProvider` as "bound and already satisfied," resting on
one implementation: `PydanticAIProvider.complete` renders the conversation before
its first await and never re-reads it. ADR-0065's **2026-07-25 amendment**
corrected that on the record: the survey behind the row took one implementation
of the seam for the seam. `models/` holds three `ModelProvider`s, and #380 found
the clause **broken in two of the three**:

- `RetryingProvider.complete` loops and re-passes the caller's `messages` to
  every attempt, i.e. after the previous attempt's `await` returned.
- `RoutingProvider.complete` re-passes the caller's `messages` to each route's
  provider in turn, after the previous route's `await` has failed.

PR #384 fixed both by snapshotting the conversation on `complete`'s first
executed line (`[m.model_copy(deep=True) for m in messages]`). At the time, two
mutation vectors could tear a wrapper: the caller could **append/replace turns in
the `Sequence`** (the container is the caller's and mutable), and — because
`Message` was then non-frozen — the caller could **rewrite a turn's `role`/
`content` in place**. ADR-0068 has since deep-frozen the shared record graph,
`Message` included (`core/types.py`, `ConfigDict(frozen=True)`), which **closes
the element-rewrite vector**: a turn's fields can no longer change under an
observation. The **container vector survives** ADR-0068 — a wrapper that re-reads
`messages` after an await still sees an appended or replaced turn — and it is
what still justifies enforcement. The current `models`-local regression cases
under `tests/models/` reflect exactly this: `test_routing.py` now parametrises
over an **appended turn only** (`_append_a_turn`), its own comment noting the
element-rewrite tear is gone. The shared `ModelProviderContract` still gained
nothing — it asserts nothing about input observation — so a fourth provider that
re-reads the caller's `Sequence` after an await passes the shared suite while
tearing.

So `ModelProvider` is exactly where `MemoryStore` was before ADR-0056/§3:
demonstrably broken, and the shared suite silent about it. The §3 amendment
closed that for the record but explicitly declined to widen enforcement,
correctly, because widening is a change to what every implementation owes and
needs its own ADR. This is that ADR.

### The seam that multiplies

`ModelProvider` is not one more seam among thirteen; it is the **one contract
this codebase deliberately re-implements by wrapping** (ADR-0011: cross-cutting
model behaviour composes by wrapping a `ModelProvider` rather than widening the
Protocol; ADR-0013 adds routing as a second wrapper and settles composition
*order*, contemplating more). Retry and routing already exist; more wrappers are
a designed-for outcome, not a hypothetical. Every wrapper hands the caller's
`Sequence[Message]` to an inner provider *after* a previous await has returned,
so every wrapper is a fresh chance to re-read across a suspension — and #380's
fix is `models`-local, so **a fourth wrapper inherits nothing** from it. This is
the property that distinguishes `ModelProvider` from a seam with a single settled
implementation, and it is why the fix belongs in the *shared* suite rather than
in one more `models`-local test.

### The observability asymmetry (why "enforce every bound seam" is wrong)

The tempting over-correction — enforce the clause on every seam it binds — is
wrong, and ADR-0060 already shows why with its own sibling clause. The
cancellation clause needs a **resource the event loop releases** to be
observable through a suite: with no such resource there is nothing for a second
caller to collide on, so a proactive case asserts nothing. Issue #378 records
exactly this for `Embedder` — no `Embedder` owns a resource the event loop
releases (`FastEmbedEmbedder`'s only lock is a `threading.Lock` taken and dropped
inside the worker), so an `EmbedderContract` non-overlap case would be a declared
flag and a branch **no implementation exercises**. `CONTRIBUTING.md` forbids
precisely that ("a contract obligation nothing runs is not enforcement, it is the
appearance of it"), and `tests/core/test_protocol_triad.py` exists because
unexercised guardrails accumulate.

The input-observation clause has **no such gate**: a call is *always* observable
at its input. You can suspend any awaiting call and mutate the argument it was
handed — there is always a window and always something to mutate. So the two
clauses are asymmetric in what they can enforce, and a uniform "enforce every
bound seam" rule would be right for neither: too weak for input-observation
(it stops at the seams someone enumerated) and too strong for cancellation (it
mandates cases nothing exercises). The trigger has to be **observable *and*
broken**, not **bound**.

## Decision

### 1. The general trigger

State it once, as the principle the two prior ADRs kept deriving locally:

> A module-level Protocol clause earns **enforcement** at a seam when a
> violation is **observable through that seam's shared suite and has been reached
> there** (or is imminently reachable) — not merely because the clause binds the
> seam. And that enforcement takes the form of a **shared conformance case**
> — rather than an implementation-local regression test — exactly when the seam
> **admits further implementations a point-fix cannot reach**.

Read as three questions, in order:

1. **Observable?** Can the shared suite make a violation manifest? For the
   input-observation clause the answer is always yes — you can always suspend a
   call and mutate its argument. For the cancellation clause it is yes only where
   the seam owns a resource the event loop releases (ADR-0060 §5; #378). A seam
   the suite cannot make fail earns no case: the case would be unexercised
   machinery, the thing `CONTRIBUTING.md` and `test_protocol_triad.py` refuse.
2. **Reached?** Has the clause actually torn at this seam, or is a tear
   imminently reachable? Evidence, not speculation. A purely hypothetical
   violation is decoration; §3's own criterion is "where the rule has been
   broken."
3. **Does the seam multiply?** If a violation is observable and has been reached,
   the clause must be enforced *somewhere*. Whether that is a **shared conformance
   case** or an **implementation-local regression test** turns on whether the
   seam accrues implementations a point-fix will not protect. A shared case earns
   its cost by catching the *next* implementation ("the gate catches it on a
   fourth store rather than the fourth store's author rediscovering it",
   ADR-0060). Where a seam has a single settled implementation, an
   implementation-local test discharges the break at lower cost and the seam
   stays out of the shared suite.

A seam that fails (1) or (2) stays in §4's legitimate bound-and-unenforced
category. A seam that clears (1) and (2) but fails (3) is enforced by a local
test and *also* stays out of the shared suite. Both are principled outcomes of
the trigger, not gaps in it.

**This is why the two clauses' enforcement scopes differ, and neither can be read
off the other's list** — the point ADR-0065 §2 and ADR-0060 §5 both make. The
vacuity sets differ because the *observability* differs, seam by seam.

### 2. Applying the trigger to `ModelProvider`: widen

`ModelProvider` clears all three questions:

1. **Observable** — always, like every input-observation seam.
2. **Reached** — broken in two of three implementations (`RetryingProvider`,
   `RoutingProvider`), per #380/#384. Not hypothetical; fixed in `models/` and
   pinned only by `models`-local tests.
3. **Multiplies** — it is *the* wrapped seam (ADR-0011/0013). New wrappers are a
   designed-for outcome, and each inherits nothing from the `models`-local fix.

So `ModelProvider` earns a **shared conformance case**, and §3 gains it as a
third enforced seam. It is overdetermined: even a seam that did *not* multiply
would, once observably broken, need enforcing somewhere (as `Planner`/`PlanStore`
were, by their `models`-local... i.e. `planning`-local fixes in #367); the
multiplication is what makes the shared suite, not an implementation-local test,
the right home.

### 3. What the `ModelProviderContract` case must be

Enough that the follow-up lane has no open design question of *principle* (the
mechanics — how suspension is coordinated, what the fake stands in for — are
that lane's, exactly as ADR-0065 §3 leaves them for `MemoryStore`):

- **It establishes mid-flight observation, not post-call isolation.** This is the
  whole content of the enforcement, for the reason ADR-0065 §"The suite already
  appears to cover this, and does not" documents at length: a post-call
  assertion passed the torn `MemoryStore` code for the entire time the tear was
  live, because it mutates after the method has already committed. The case
  suspends `complete` at its first await, mutates the caller-held conversation
  from inside that suspension, then asserts that the single `Message` returned —
  and, for a wrapper, the conversation each inner attempt was given — describes
  **one** version of the input. The mutation vector is **container mutation of the
  caller's `Sequence`** — appending or replacing a turn — because ADR-0068's
  deep-freeze of `Message` closes the element-rewrite vector: a turn's own fields
  can no longer change under an observation, so the case need not (and cannot)
  parametrise over a rewritten turn. `test_routing.py`'s current `_append_a_turn`
  case is the working template — it mutates the caller's list from inside the
  inner provider's suspension and asserts on what the next attempt observes.

- **It needs a fixture-supplied suspension hook**, because the collaborator a
  provider suspends on is not owned by the suite. This is the `MemoryStore`
  problem of ADR-0065 §3, in a milder form: a **wrapper** suspends inside its
  **inner provider**, and a **direct provider** suspends on its **transport** —
  neither is the suite's. `ModelProviderContract` today builds its subject
  through a single fixed `provider` fixture (no factory), so it cannot express a
  mid-call suspension at all. The suite therefore requires a mid-call suspension
  hook supplied through its fixture, exactly the shape §3 requires for
  `MemoryStore`'s `store_factory`, and positioned at the method's **own first
  suspension point** (§3's position clause: a hook at method *entry* lets the
  mutation land before any read and defeats its own case).

- **With the same "no `await`" escape.** An implementation's test module either
  supplies a handle the case can synchronise on, or **declares that this
  implementation performs no `await` between reading its input and answering** —
  in which case the case reduces to the post-call assertion, correctly, because a
  provider with no suspension window has no window to tear in. `FakeModelProvider`
  takes the escape (its `complete` has no such await), exactly as
  `InMemoryMemoryStore` and `FakeMemoryStore` do in §3.

The follow-up lane also decides whether the hook is best expressed as a wrapper
around an injected inner provider (the `MemoryWriter` shape, where the suite owns
the collaborator — ADR-0065 §3 notes this is *general* precisely when the
collaborator is on the suite's side) or as a transport-level hook. #384's
`RetryingProvider`/`RoutingProvider` cases, which suspend inside a fake inner
provider the test controls, are the closest working precedent and strongly
suggest the injected-inner-provider form. That is a design call, not a matter of
principle, so it stays with the lane.

### 4. This ADR amends ADR-0065 §3 (append-only)

Widening §3 is an **amendment** to ADR-0065, not a supersession and not a
rewrite. ADR-0065 §3's original two-seam scope stands as ratified (ADR-0001,
append-only); the amendment **adds** `ModelProvider` as a third enforced seam.

Per ADR-0001 and `CONTRIBUTING.md` ("Trivial ADRs … amendments … skip both the
separate PR and the review"), the mechanical amendment is trivial and rides in
this PR: it is an `## Amendment` section appended to `docs/adr/0065-*.md` plus an
`Amended:` header line, in the shape ADR-0004/ADR-0007 use, leaving every
existing section body untouched. **ADR-0069 is not itself the amendment** — the
cleaner form (dispatch's steer, and the one this ADR takes) is that ADR-0069
records the *decision and its trigger*, and the append-only §3 amendment text
lives on ADR-0065 where a reader of §3 will find it. This ADR's Consequences note
that amendment; the amendment points back here for the reasoning.

### 5. Consequences and what stays principled

**Consequences.**

- **Once the follow-up lane lands the case, a fourth wrapper cannot tear while
  passing the shared suite.** That is the point of the decision — to close, for
  the seam most likely to grow new implementations, the one thing §3 exists to
  prevent (a new implementation passing the conformance suite while violating the
  clause). **This ADR does not itself close it:** until the `ModelProviderContract`
  case lands, `ModelProvider` stays enforced only by the `models`-local #384 cases
  (which pin `RetryingProvider` and `RoutingProvider` specifically), and a fourth
  provider still passes the shared suite. The shared case the follow-up builds is
  what binds the *next* provider; this ADR decides that it must exist.
- **The cost is one shared conformance case plus a fixture, and one escape.**
  `ModelProviderContract` gains a mid-flight case and a suspension-hook fixture;
  `FakeModelProvider` takes the "no `await`" escape. That machinery *is* the
  enforcement — the cheap post-call version is the one that certified the
  `MemoryStore` bug.
- **#378's deferral and `Planner`/`PlanStore`'s status become principled, not ad
  hoc.** Under the trigger, `Embedder` cancellation is deferred because it fails
  question 1 (not observable — no resource the loop releases), and the now-fixed
  `Planner`/`PlanStore` input reads (#367, COMPLETED) stay out of the shared suite
  because they fail question 3 (single settled implementation; discharged by
  `planning`-local fixes). Neither is a gap; both fall out of the same rule that
  widens `ModelProvider`.
- **ADR-0065 §3 grows by one row and no ratified text is rewritten.** The
  amendment is append-only; §3's original scope and reasoning stand as the record
  of what was decided when.
- **The clause's bite at this seam is already narrowed.** ADR-0068 deep-froze
  `Message`, so — exactly as ADR-0065's own revisit note anticipated — the clause
  survives for the `Sequence` container but no longer for a turn's fields. The
  case is therefore container-mutation only (§3). **Revisit** if a wrapper seam's
  inner collaborator stops being injectable (the fixture shape would have to
  change), or if `core` ever exchanges an un-frozen conversation element again.

**Rejected.**

- **Leave `ModelProvider` bound-and-unenforced, like `Planner`/`PlanStore`.**
  This is the status quo the §3 amendment left in place, and it is the closest
  real alternative. It fails on question 3 of the trigger: `Planner`/`PlanStore`
  each have a single settled production implementation, so a `planning`-local fix
  (#367) protects everything the clause can reach there. `ModelProvider` is the
  opposite — it was broken (question 2) *and* it multiplies (question 3), so a
  `models`-local fix protects only the two wrappers that exist and the next one
  inherits nothing. The two seams differ on exactly the property the trigger
  turns on, so treating them alike would be the ad-hoc choice, not the principled
  one.
- **Enforce the clause on every bound seam proactively.** Rejected on the
  observability asymmetry (§Context, and question 1). The input-observation clause
  is always observable but the cancellation clause is not, so a uniform
  "enforce every bound seam" rule mandates `Embedder` cancellation machinery that
  no implementation exercises (#378) — the unexercised-guardrail failure
  `CONTRIBUTING.md` and `test_protocol_triad.py` exist to refuse — while still
  under-serving input-observation by stopping at whatever seams an enumerator
  happened to list. "Observable and broken" is the rule that fits both clauses;
  "bound" fits neither.
- **A narrower "wrapper" obligation the contract names explicitly** — state the
  input-observation case only for implementations that take a collaborator. This
  invents a `wrapper` category `core/protocols.py` does not have and should not:
  the clause binds every `ModelProvider`, direct or wrapping, and a direct
  provider re-reading its transport across an await tears identically. The
  fixture-supplied hook already covers both shapes (a wrapper suspends on its
  inner provider, a direct provider on its transport) without the contract
  learning a new noun. Issue #388 leans the same way.
