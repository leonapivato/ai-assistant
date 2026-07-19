# TODO — tracked debts and follow-ups

Cross-cutting work that is deliberately deferred, not forgotten. Each item is a
real gap surfaced during review; none blocks current functionality. Prefer
turning a substantial item into an ADR or a scoped slice when picked up.

## 1. Backfill shared Protocol conformance suites

**What:** `CONTRIBUTING.md` ("Protocol conformance suites") requires *each*
Protocol to have a shared test suite that every implementation must pass. Done
for `FeedbackProcessor` and `MemoryStore`; the rest still assert
`isinstance(impl, Protocol)` plus implementation-specific tests, which only
proves an attribute exists.

**Missing suites for:** none — the backfill is complete. The `FastEmbedEmbedder`
hole below is what keeps this item open.
(`ContextProvider` done — `tests/context/context_provider_contract.py`, run
against `AssemblingContextProvider` and the shared `FakeContextProvider`.
`MemoryStore` done — `tests/memory/memory_store_contract.py`, run against
`InMemoryMemoryStore`, `SqliteMemoryStore`, and the shared `FakeMemoryStore`.
`MemoryPolicy` done — `tests/memory/memory_policy_contract.py`, run against
`DefaultMemoryPolicy` and the shared `FakeMemoryPolicy`.
`ModelProvider` done — `tests/models/model_provider_contract.py`, run against
`PydanticAIProvider` and the shared `FakeModelProvider`.
`Embedder` done — `tests/models/embedder_contract.py`, run against
`HashingEmbedder` and the shared `FakeEmbedder`.)

**Pattern to follow:** `tests/memory/memory_store_contract.py` or
`tests/learning/feedback_processor_contract.py` — an abstract `…Contract` base
class (not `Test`-prefixed, so pytest does not collect it directly) with a
subject fixture overridden by a `Test…`-prefixed subclass per implementation.

**Known hole — `FastEmbedEmbedder` does not run its suite.** `EmbedderContract`
runs against `HashingEmbedder` and `FakeEmbedder` only. The real embedder's
`embed` downloads a model on first use, and the gate runs everything —
`integration`-marked tests included — with no network, so it cannot join as
things stand. The two cheap ways in are both worse than the hole: patching
`TextEmbedding` out asserts properties of the patch rather than of fastembed,
and letting it download makes the gate network-dependent. Closing it honestly
means an injectable backend seam in `FastEmbedEmbedder` so the *adapter* layer
(count, order, shape, finiteness — everything that could regress on a dependency
bump) runs through the contract against a deterministic offline stub, while
fastembed itself stays out of the gate. That is a `models` change, hence its own
slice rather than part of the testing one. Raised on every pass of the
adversarial review of PR #16 and waived there deliberately, with the reasoning
recorded in `tests/models/embedder_contract.py`.

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

**What:** canonical shared fakes so a subsystem depends on a *shared* stand-in
for its collaborators, never reaching into their internals or hand-rolling a
private mock that drifts from the contract. The home now exists —
`ai_assistant.testing` (test-only, enforced by `lint-imports`) — with the first
fake in place.

**Done:** `FakeMemoryStore` (`ai_assistant/testing/memory.py`),
`FakeModelProvider` (`ai_assistant/testing/models.py`), `FakeEmbedder`
(`ai_assistant/testing/embeddings.py`), `FakeContextProvider`
(`ai_assistant/testing/context.py`), and `FakeMemoryPolicy`
(`ai_assistant/testing/policy.py`), each passing its Protocol's shared
conformance suite (item 1).

**Still needed:** none for the Protocols that exist today. Every new Protocol
brings its own fake as part of the triad (CONTRIBUTING, "Adding a Protocol").
`orchestration` will need most of these; add them as it is built (or ahead of it).

**Origin:** review of AI-agent scalability — the biggest cross-subsystem gap for
parallel development.

## 4. Single generated project-status view — DONE

**Done:** `just status` (`scripts/project_status.py`) derives packages
(built/stub), Protocols, and ADRs (status + numbering gaps) fresh from the repo
on each run, so it cannot go stale. It replaces stitching together the source
tree, `core/protocols.py`, and every ADR header. Human-declared state (lane
owners, ADR numbers in flight) intentionally stays in `WORKING.md`, which the
view points to rather than re-parsing.

**Origin:** review of AI-agent scalability — onboarding-context cost.

## 5. Formalize the "new Protocol" ritual in CONTRIBUTING — DONE

**What:** adding a Protocol today is documented as "edit `protocols.py` + write an
ADR." The machinery that keeps implementations honest — a conformance suite
(item 1) and a canonical fake (item 3) — is created *later, as debt* rather than
*with* the contract. That is precisely how items 1 and 3 became TODOs.

**Done:** `CONTRIBUTING.md` → "Adding a Protocol: land the triad together"
(under Architecture boundaries) makes the required unit of work for a new
Protocol a *triad* — Protocol definition + shared conformance suite + canonical
fake — landing in one change. Cross-referenced from the Testing section and from
`CLAUDE.md`'s "Contract first" rule.

**Convention, not a gate.** The rule is documented and review-enforced; nothing
mechanical fails a new Protocol that ships without its suite and fake. That is
item 6.

**Origin:** review of AI-agent scalability — process fix that closes the loop on
items 1 and 3.

## 6. Enforce the Protocol triad mechanically

**What:** item 5 made the triad the documented rule, but only review enforces
it. A new Protocol can still land with no conformance suite and no canonical
fake and pass the whole gate — the same way items 1 and 3 accumulated.

**Direction:** a deterministic check that maps each Protocol in
`core/protocols.py` to (a) a `…Contract` suite, (b) a canonical fake in
`ai_assistant.testing`, and (c) a *collected* `Test…Contract` subclass binding
the two — the abstract base alone proves nothing. Needs an explicit exemption
list for Protocols not yet backfilled (item 1), or it fails on day one; that
list then doubles as the backlog, shrinking to empty as the backfill lands.

**Origin:** adversarial review of the item-5 change — the documented rule is a
convention until something fails on its absence.

## 7. Ratify input immutability on the MemoryPolicy contract

**What:** `MemoryPolicy.decide` says nothing about whether it may mutate the
proposal or the conflict records it is handed. Both current implementations
treat them as read-only, and every caller relies on that — but it is an
assumption, not a promise.

**Why it is not just tested:** the `MemoryPolicy` conformance suite originally
asserted it. That was wrong: a conformance suite *is* the contract, so asserting
an obligation the Protocol does not state widens the contract without an ADR
(golden rule 5) and would fail an implementation that genuinely conforms. It now
lives in each implementation's own tests, which is the honest place for an
expectation that has not been ratified.

**Direction:** decide whether immutability is part of the contract. If it is,
state it on `MemoryPolicy.decide`, flag the Protocol change as breaking, and move
the assertion into the shared suite. Cheap, but it is a `core/` change and a
contract widening, so it is not a drive-by.

**Origin:** architecture review of the `MemoryPolicy` triad (item 1/3 backfill).
