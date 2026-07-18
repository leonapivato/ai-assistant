# TODO — tracked debts and follow-ups

Cross-cutting work that is deliberately deferred, not forgotten. Each item is a
real gap surfaced during review; none blocks current functionality. Prefer
turning a substantial item into an ADR or a scoped slice when picked up.

## 1. Backfill shared Protocol conformance suites

**What:** `CONTRIBUTING.md` ("Protocol conformance suites") requires *each*
Protocol to have a shared test suite that every implementation must pass. Only
`FeedbackProcessor` has one so far; the rest assert `isinstance(impl, Protocol)`
plus implementation-specific tests, which the reviewer noted only proves an
attribute exists.

**Missing suites for:** `ModelProvider`, `Embedder`, `MemoryStore` (two
implementations — `InMemoryMemoryStore` + `SqliteMemoryStore` — so this one has
the most value), `MemoryPolicy`, `ContextProvider`.

**Pattern to follow:** `tests/learning/feedback_processor_contract.py` — an
abstract `…Contract` base class (not `Test`-prefixed, so pytest does not collect
it directly) with a `subject` fixture overridden by a `Test…`-prefixed subclass
per implementation.

**Origin:** adversarial review of the `learning` slice (ADR-0009).

## 2. Assertion-supersedes-conflict policy refinement

**What:** `DefaultMemoryPolicy` returns `ACCEPT` for a `USER_ASSERTED` proposal
*before* its merge rule (ADR-0005 §3). So an explicit correction that conflicts
with an existing **inferred** memory is stored as a *new* record rather than
superseding the stale one — the old (now-wrong) memory lingers.

**Impact:** the first learning loop ("learn a new preference, reuse it") is
unaffected, but "a correction supersedes a wrong belief" leaves a stale memory
behind.

**Direction:** refine the policy so a user assertion supersedes (merges over /
retires) a conflicting inference. This is a **memory-policy** decision — a
follow-up to ADR-0005, likely its own ADR.

**Origin:** recorded in ADR-0009 §5 ("Known interaction with the policy").

## 3. Canonical shared test doubles for every Protocol

**What:** there is no single, shared fake for each Protocol. The golden rule
tells a subsystem to depend on *fakes* of its collaborators and never reach into
their internals, but with no canonical fake to import, each subsystem hand-rolls
its own (`learning` already has one; `orchestration` will need `MemoryStore`,
`ModelProvider`, `ContextProvider`, etc.). Hand-rolled fakes drift — each encodes
slightly different assumptions about the contract — and the drift surfaces as an
integration surprise that no subsystem's unit tests caught.

**Direction:** one canonical in-memory fake per Protocol in a shared location
(e.g. `ai_assistant/testing/` or `tests/fakes/`) — `FakeModelProvider`,
`FakeMemoryStore`, `FakeContextProvider`, … — imported by any subsystem that
needs that collaborator. Each fake must itself pass its Protocol's conformance
suite (see item 1), so the fake cannot drift from the contract either. Highest
leverage for parallel, multi-agent work: it is the shared definition of "how a
compliant dependency behaves."

**Origin:** review of AI-agent scalability — the biggest cross-subsystem gap for
parallel development.

## 4. Single generated project-status view

**What:** onboarding to "what exists, what's claimed, what's next" currently
requires stitching together four files — `docs/roadmap.md`, `WORKING.md`,
`core/protocols.py`, and the ADR statuses. The seams already show (e.g. ADR-0011
is on a contributor branch, so the accepted-ADR sequence has a hole with no index
explaining it). Every agent pays this assembly cost on every pickup.

**Direction:** one status view — capability → Protocol → implementation status →
owning ADR → lane owner — ideally *generated* (e.g. a `just status` recipe that
derives it from the tree and ADR front-matter) so it cannot go stale. Collapses
agent onboarding into a single read.

**Origin:** review of AI-agent scalability — onboarding-context cost.

## 5. Formalize the "new Protocol" ritual in CONTRIBUTING

**What:** adding a Protocol today is documented as "edit `protocols.py` + write an
ADR." The machinery that keeps implementations honest — a conformance suite
(item 1) and a canonical fake (item 3) — is created *later, as debt* rather than
*with* the contract. That is precisely how items 1 and 3 became TODOs.

**Direction:** make the required unit of work for a new Protocol a *triad* —
Protocol definition + canonical fake + shared conformance suite — landing
together, and state this in `CONTRIBUTING.md` (Architecture boundaries / Testing).
Prevents the backfill debt from recurring for the remaining subsystems.

**Origin:** review of AI-agent scalability — process fix that closes the loop on
items 1 and 3.
