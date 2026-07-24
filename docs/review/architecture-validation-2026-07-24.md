# Architecture validation — 2026-07-24

Scope: architectural claims only (contracts, seams, enforcement mechanisms).
No implementation bugs, style, or coverage findings — those belong to per-diff
review. Base: `origin/main` @ 42c4de3.

---

## C1 — The concurrency contract

**Verdict: ASPIRATIONAL**

`CLAUDE.md`'s entire stated contract is one sentence: "I/O-bound methods are
`async`. The system composes on one event loop." That is a scheduling fact, not
a cancellation contract, and in practice cancellation safety has been derived
independently, three times, after three different bugs:

- ADR-0054 (a cancelled store call must not release its connection while a
  worker thread still holds it) — fixes `SqliteMemoryStore`, `SqliteAuditTrail`,
  `SqlitePlanStore` with a hand-written `_run_to_completion` helper, **duplicated
  verbatim in each of the three store modules** because the ADR itself rules out
  a shared home ("a shared home would have to be `core`... this change
  deliberately touches no `core`").
- ADR-0056 (a store write snapshots its record before the first await) — fixes
  `SqliteMemoryStore.add`'s specific tear (#286), and explicitly declines to
  generalize: "We deliberately keep this a `SqliteMemoryStore` behaviour, not a
  universal `MemoryWriter` obligation... noted as **deferred** to that separate
  lane" (issue #314).
- ADR-0057 (resolving the deferred caller-cancellation gap) — fixes
  `AssemblingContextProvider.assemble()`'s swallowed cancellation (#231), again
  scoped to one implementation.

All three ADRs open with the same disclaimer: "Not a contract change... touches
no Protocol." That is true and also the finding: three subsystems (`memory`,
`permissions`, `context`) independently discovered and fixed the same class of
bug — a cancellation absorbed or a connection released mid-flight — and each
time the fix was ruled explicitly out of `core/protocols.py`.

Only one Protocol method states a cancellation contract at all:
`ToolInvoker.invoke` (`protocols.py:606-683`) — three ordered checks, what
`BaseException` does, what happens "on expiry," and an explicit `CancelledError`
raise clause. `MemoryStore`, `PlanStore`, `AuditTrail`, and `ContextProvider`
say nothing about what a caller may assume if cancelled mid-call
(`protocols.py:139-242`, `380-508`, `797-1021`, `308-323`). A new implementer of
any of those four has no textual guarantee to conform to — only three
implementation-specific ADRs to discover by reading store internals.

The canonical fakes confirm the gap rather than closing it: `FakeToolInvoker`
(`testing/invoker.py:227-291`) is the only fake that models cancellation at all
— tracking `Task.cancelling()` deltas to detect an absorbed cancellation,
because its Protocol demands it. `FakeMemoryStore`, `FakePlanStore`,
`FakeAuditTrail`, `FakeContextProvider` model no cancellation behavior, because
nothing requires them to. And the shared conformance suites split the same way:
`tests/tools/tool_invoker_contract.py` and `tests/planning/plan_store_contract.py`
carry cancellation tests that any implementation must pass; the ADR-0054/0056/0057
fixes are tested **only** in implementation-specific files
(`tests/memory/test_sqlite_store.py:1008-1103`,
`tests/permissions/test_audit.py:635-677`, `tests/context/test_context_provider.py`)
— `tests/memory/memory_store_contract.py`, `tests/permissions/audit_trail_contract.py`,
and `tests/context/context_provider_contract.py` assert none of it. A fourth
future `MemoryStore` or `AuditTrail` backend could reintroduce exactly the
ADR-0054 bug and nothing in the shared suite would catch it.

The `models` layer shows a fourth independent derivation:
`models/retry.py:216-274` and `models/routing.py:118-119` reason carefully
about `CancelledError` vs. `TimeoutError` vs. a provider swallowing its own
cancellation — none of it traceable to a stated `ModelProvider.complete`
guarantee (`protocols.py:64-80` says nothing about cancellation).

**Cost of leaving as-is:** every future `MemoryStore`/`PlanStore`/`AuditTrail`/
`ContextProvider`/`ModelProvider` implementation re-derives cancellation safety
from scratch, catches it only by an implementation-specific test someone
remembers to write, and the shared conformance suites give false confidence —
they pass an implementation that reintroduces a connection-release-under-
cancellation bug. This is exactly the shape of risk `core/protocols.py`
otherwise exists to eliminate.

---

## C2 — Interaction rules stated only as prose

**Verdict: HOLDS (as a description of the current state) — and mostly, but not
entirely, defensible**

Two prose-only, explicitly-labeled-unenforceable rules exist:

1. `protocols.py:282-286` (`MemoryWriter`): "The store it writes to must be the
   one its caller retrieves from — a composition-root obligation, unenforceable
   here precisely because no store is on this seam."
2. `protocols.py:589-596` (`ToolInvoker`/`ToolRegistry`): "the composition root
   must inject one object as both... No Protocol can close that."

Both are, in fact, discharged today: `app/composition.py:114,126,136,147` passes
the same `memory` variable to the loop and the writer, and the same `tools`
variable as both `registry=` and `invoker=` to `StepExecutor`. But enforcement
is partial. `tests/app/test_composition.py:58-61` asserts the `PlanStore`/
`AuditTrail` sharing obligation by identity (`engine._runner._plans is plans`,
`engine._trail is engine._runner._trail`) — that one *is* mechanically checked.
There is no equivalent identity assertion for the memory-store/writer pairing
or the registry/invoker pairing; today they're satisfied because it's one line
of Python each, but nothing would fail if a future composition-root change
split them. A cheap identity assertion, alongside the two that already exist,
would close this without a Protocol change.

A third prose rule is a division of *responsibility* rather than a wiring
obligation: `protocols.py:597` — `ToolInvoker.invoke` "does **not** consult
`ActionPolicy`." This one is closer to unenforceable-by-nature: it's a negative
("this seam must not import that Protocol"), and `lint-imports`' independence
contract (`pyproject.toml:207-218`) already keeps `permissions` and `tools` from
importing each other, which is the only mechanical proxy available for "does
not consult." I did not find these two in tension with each other or with any
other prose rule.

**Cost of leaving as-is:** low for the two composition-root obligations (cheap
to test, not yet done); acceptable for the "does not consult" rule (already has
a mechanical proxy via `lint-imports`' independence contract).

---

## C3 — Is `orchestration`'s four-way split principled?

**Verdict: HOLDS**

The four objects map cleanly onto the documented pipeline and the code path
matches the docs:

- `LearningLoop` (`loop.py`) owns *context → memory retrieval → planning* via
  `respond()` (`loop.py:211`) and *learn* via `learn()` (`loop.py:251`) — both
  ends of the pipeline, grouped in one object because both need the same
  injected collaborators (`context`, `memory`, `writer`, `planner`, `feedback`).
  The docstring is explicit that this is intentionally partial: "Tool
  selection, permission checking and execution are still **not** part of this
  object" (`loop.py:19`).
- `StepRunner` (`runner.py`) owns *tool selection → permission gate → hand-off*
  (`runner.py:267-298`), consuming `ToolRegistry`/`ActionPolicy`/`AuditTrail`.
- `StepExecutor` (`executor.py`) owns *execute*: claim → invoke → commit, on
  `ToolRegistry`/`ToolInvoker` only (`executor.py:1-23`).
- `Engine` (`engine.py`) is the façade that sequences the other three for one
  turn and is explicitly **not** a Protocol, by design (`engine.py:3-11`), since
  there is exactly one orchestration engine and one class of consumer.

`Engine.converse`/`resume` (`engine.py:709,731,792`) call `self._loop.respond`
then `self._runner.run`/`resume` in that order, which is exactly what the
class-level docs claim. The seam is real, not accreted: each object owns a
disjoint set of injected Protocols, and the engine's own docstring names the
scope boundary precisely ("a turn drives at most one step... the rest await
that stage," `engine.py:22-29`) — matching what the code does today.

**Cost of leaving as-is:** none identified; this is a clean seam.

---

## C4 — `core/types.py` as a shared dependency

**Verdict: HOLDS, with a churn-concentration caveat**

The file's ~45 classes cluster by domain (messages; memory records/proposals/
decisions; context; goals/plans/execution; risk/cost/permission/tool
definitions; tool calls/results) and each cluster is exactly the cross-boundary
vocabulary CLAUDE.md's convention requires ("Public data that crosses subsystem
boundaries is a pydantic model in `core/types.py`"). I did not find a type used
by only one subsystem that has no boundary-crossing reason to be there — the
severity/cost/definition types, e.g., are shared by `tools` and `permissions`
at the `ToolDefinition`/`ActionRequest` seam, not internal to either.

The caveat is real, though: the file has **zero internal section markers** —
no comment banners separating the memory cluster from the planning cluster
from the permission cluster — despite being 2,745 lines. And it is the single
highest-churn file in `core`: 49 commits touch it, spanning `memory`,
`planning`, `permissions`, and `tools`-scoped changes alike
(`git log --oneline -- src/ai_assistant/core/types.py`). `lint-imports` cannot
see any of this, because nothing about within-file cohesion is an import
violation — the brief's premise is correct that this risk is invisible to the
gate. Today the changes are domain-scoped even though the file isn't, so this
is a latent, not active, cost.

**Cost of leaving as-is:** every subsystem's schema change lands in the same
file, so merge conflicts across concurrently-worked lanes concentrate here, and
nothing currently marks or bounds the file's growth. Worth a housekeeping ADR
(section banners, or a per-domain submodule under `core/types/`) before more
subsystems stack contract changes here — not urgent today.

---

## C5 — Three stores, three durability postures

**Verdict: ASPIRATIONAL — partially intentional, partially accidental**

The three postures are real and distinct:

- `memory/sqlite_store.py:192-255` (`_migrate_records`): detects column
  *affinity* (`REAL` vs `INTEGER`) via `PRAGMA table_info`, and on mismatch
  rebuilds the table transactionally (`CREATE records_migrated` → copy rows,
  backfilling from JSON → `DROP`/`RENAME`). No version marker; the schema
  itself is the migration trigger.
- `planning/sqlite_store.py:227-245`: a `schema_version` meta row, checked on
  open; **any** mismatch — newer or older — is a hard `PlanningError` ("there
  is no migration yet"). No data-level migration path exists at all.
- `permissions/audit.py:273-322` (`_migrate`): additive-only, `PRAGMA
  table_info` column-presence detection, `ALTER TABLE ... ADD COLUMN` per
  missing column, backfilled from the JSON blob where derivable. No version
  marker either.

ADR-0049 §1 (`docs/adr/0049-a-durable-plan-store.md:139-146`) explicitly reasons
about the divergence from `SqliteMemoryStore`: PlanStore is new with no legacy
data, so it starts with a `schema_version` marker from day one, rather than
backfilling one after the fact the way `SqliteMemoryStore` had to. That much is
a deliberate, recorded trade-off, not an oversight. What is **not** reasoned
anywhere is why `permissions/audit.py` — which post-dates `SqliteMemoryStore`
and could equally have started with a version marker — has none, or why its
posture (additive-only, no version) differs from both siblings without
comment. No ADR states an overall schema-evolution posture across all three
stores, in contrast to the concurrency question (C1), which *did* eventually
get a shared-shape fix (ADR-0054) applied identically across all three —
schema evolution never received the same unifying treatment.

**Cost of leaving as-is:** the three postures fail differently on the same
class of future change. A `PlanStore` schema change makes existing user data
**entirely inaccessible** until a migration is written from scratch — highest
blast radius, but the failure is loud and immediate. `SqliteMemoryStore`'s
column-affinity detection generalizes to type changes but has no demonstrated
path for structural changes (new required fields, column splits). `audit.py`'s
column-existence detection has no version concept at all, so every future
change accretes as another `if column not in columns` branch with no marker of
what's been applied — and, unlike `planning`, no version check to refuse an
unrecognized future schema outright, so a downgrade (opening a newer database
with older code) is not detected the way it is in `planning`.

---

## C6 — Is the system actually model-agnostic?

**Verdict: ASPIRATIONAL — structurally real, empirically unexercised**

The seam is genuinely provider-shaped, not disguised Anthropic-shaped code:

- `models/provider.py:93-156` (`_classify`/`_classify_status`) dispatches on
  **HTTP status code** and on pydantic-ai's own generic exception hierarchy
  (`ModelHTTPError`, `ContentFilterError`, `UnexpectedModelBehavior`,
  `ModelAPIError`) — none of it Anthropic-specific. The one Anthropic mention
  (`provider.py:142`) is an explanatory comment about how a *timeout happens to
  surface* through pydantic-ai, not a branch keyed on the vendor.
- `RoutingProvider` (`models/routing.py`) is a real, generic multi-provider
  fallback wrapper — ordered candidates, a `routable` vs `retryable`
  distinction, composition-order guidance (ADR-0013). It structurally proves
  the seam supports more than one provider.
- `Settings.default_model` is a bare `"provider:model"` string
  (`core/config.py:94-97`), not a closed enum.

But nothing exercises any of this against a second vendor:

- `pyproject.toml:38` pins only `pydantic-ai-slim[anthropic]`.
- `app/composition.py:106-109` wires exactly `RetryingProvider(PydanticAIProvider(...))`
  — `RoutingProvider` is never constructed in production. The multi-provider
  capability exists in `models/` and is used nowhere.
- Every test in `tests/models/test_provider.py` drives `PydanticAIProvider`
  with pydantic-ai's own `TestModel`/`FunctionModel` doubles, never a second
  real SDK's error shapes.

**What would break first on a second provider:** the `_classify` dispatch
itself is probably fine (HTTP-status-based), but nothing has ever verified that
a second SDK's exceptions actually land in pydantic-ai's `ModelHTTPError`/
`ModelAPIError` hierarchy the way Anthropic's do — that assumption is
untested. `Role.TOOL` messages are unconditionally rejected
(`provider.py:85-87`) regardless of provider, a real capability gap orthogonal
to which vendor is behind the seam.

**Cost of leaving as-is:** the moat claim ("model-agnostic") is currently a
proof by construction, not by demonstration. If a second provider is added
without first wiring `RoutingProvider` into the composition root and testing
against it, the first failure will likely be in `_classify`'s exception-pattern
matching silently misclassifying an error as a bare `ModelError` (safe but
unhelpful) rather than a hard crash — the code is written defensively enough
that the risk is under-classification, not a wrong retry.

---

## C7 — Do the canonical fakes tell the truth?

**Verdict: HOLDS — with C1's gap as the one substantive exception**

The fakes I read (`testing/memory.py`, `testing/policy.py`, `testing/invoker.py`)
are unusually honest about their own limits rather than pretending to be real
implementations: `FakeMemoryStore`'s docstring states up front it is "neither
persistent nor semantic... for those, use `SqliteMemoryStore`"
(`testing/memory.py:10-14`), and `FakeMemoryPolicy` is explicit that it exists
precisely to *avoid* coupling tests to `DefaultMemoryPolicy`'s particular rules
(`testing/policy.py:1-11`). Permission-policy conformance is exercised
symmetrically: `tests/permissions/test_action_policy.py` and
`tests/permissions/test_fake_action_policy.py` both run the same
`ActionPolicyContract` against `ThresholdActionPolicy` and `FakeActionPolicy` —
real and fake are held to the identical bar, which is the intended shape of
this whole mechanism working as designed.

The one place a fake's behavior diverges from what every real implementation
must actually do is the C1 finding, restated in this frame: `FakeToolInvoker`
alone models cancellation-absorption detection
(`testing/invoker.py:227-291`), because its Protocol demands it, while
`FakeMemoryStore`, `FakePlanStore`, `FakeAuditTrail`, and `FakeContextProvider`
model none — not because the real `SqliteMemoryStore`/`SqliteAuditTrail`/
`AssemblingContextProvider` don't need it (ADR-0054/0056/0057 prove they do),
but because nothing in the shared Protocol or conformance suite asks the fakes
to. A test written today against `FakeMemoryStore` cannot exercise "what
happens if a memory write is cancelled mid-flight," even though that is a
question the real store had to answer twice (ADR-0054, ADR-0056).

**Cost of leaving as-is:** low outside of the C1 gap — the fakes are
well-scoped and self-aware. The C1 gap means a consumer subsystem
(`orchestration`, `learning`) that only ever tests against fakes has no way to
discover a cancellation-safety regression before it ships against a real
store.

---

## Ranked list — what to address before more subsystems stack on this surface

1. **C1 — state the cancellation contract once, in `core/protocols.py`, and
   push it into the shared conformance suites and fakes.** This is the
   highest-leverage fix: it would have caught ADR-0054/0056/0057's bugs earlier
   and prevents a fourth. Concretely: a documented cancellation guarantee on
   `MemoryStore`/`PlanStore`/`AuditTrail`/`ContextProvider` (what survives a
   `CancelledError` mid-call), a conformance-suite test for it, and a fake that
   models it — the same shape `ToolInvoker`/`FakeToolInvoker` already have.
2. **C5 — decide, and record in one place, the schema-evolution posture all
   three durable stores should share** (or explicitly ratify that they may
   differ, and why `audit.py` gets no version marker while `planning` does).
   Schema is the least reversible surface in the system; right now the
   divergence is half-reasoned (ADR-0049) and half-silent (`audit.py`).
3. **C6 — either wire `RoutingProvider` into the composition root against a
   second provider and test it, or narrow the claim.** The seam looks sound by
   inspection but "model-agnostic" is currently unverified past one vendor,
   and the built fallback mechanism sits unused.
4. **C2 — add the two missing identity assertions** (memory store/writer
   sharing, registry/invoker sharing) to `tests/app/test_composition.py`,
   matching the two that already exist for `PlanStore`/`AuditTrail`. Cheap,
   closes a real (if currently unexploited) gap.
5. **C4 — housekeeping, not urgent.** Section banners or a `core/types/`
   submodule split before the file's churn concentration gets worse.

C3 and C7 hold cleanly and need no action.
