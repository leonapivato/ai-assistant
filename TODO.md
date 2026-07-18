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
