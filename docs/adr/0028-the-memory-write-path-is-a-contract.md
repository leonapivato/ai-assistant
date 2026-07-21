# 28. The memory write path is a contract: `MemoryWriter`

- Status: Proposed
- Date: 2026-07-21
- Closes the gap ADR-0022 §Consequences item 1 filed as issue #103, and the one
  ADR-0009 §Context named before it. Neither is reopened here: this ADR promotes
  an existing shape to a contract and changes no memory semantics.
- Amends on ratification: ADR-0022 §4. The edit is **not** made by this change —
  see §6 for its exact form and why it waits.

## Context

`memory` already owns a complete write path. `MemoryIngestor`
(`src/ai_assistant/memory/ingest.py`) resolves conflicts from the store, asks the
injected `MemoryPolicy` to rule, and applies the ruling — the propose/dispose/
persist loop VISION §7 requires, in one place.

It is concrete, and it is not reachable. Golden rule 1 forbids `orchestration`
from importing `ai_assistant.memory`, so `LearningLoop` (ADR-0022) had to build
its own write half against `MemoryStore` and `MemoryPolicy` directly. ADR-0009
§Context predicted this exact situation — "`MemoryIngestor` is concrete in
`memory/`, not a `core` contract… the pipeline wires them to the ingestor" — and
left it to the pipeline. The pipeline exists now and cannot do it.

Two costs are in the code today.

1. **Conflict detection exists twice.** `MemoryIngestor._detect_conflicts`
   (`ingest.py:96–112`) and `LearningLoop._conflicts_for` (`loop.py:351–373`) are
   the same heuristic — same-kind `search`, over-fetch by one, drop the
   proposal's own record, keep matches at or above a score threshold, truncate to
   the limit — down to a shared eight-line comment explaining the over-fetch.
   Two copies of one rule that must agree, with nothing making them agree. The
   duplication reaches the constructor too: `conflict_threshold` and
   `conflict_limit` are tuning knobs on both classes, so a deployment can set
   them to different values on the two objects writing to the same store.
2. **`LearningLoop` cannot apply a `MERGE`.** Folding two records is `memory`'s
   own semantics (`ingest.py:44–56`: newest content wins, evidence unioned,
   confidence maximised, target's id kept). Re-deriving that fold in
   `orchestration` would fork it, so the loop reports the decision with a `None`
   record id and writes nothing (`loop.py:375–395`, ADR-0022 §4, and
   `tests/orchestration/test_loop.py::test_learn_reports_a_merge_without_applying_it`).

The second is the one that matters beyond tidiness. The product thesis is an
accumulated user model that improves through continuous learning; a
`MERGE` is precisely the ruling that consolidates rather than accretes. Today
the loop can *propose* and, for that ruling, cannot *commit*.

The fix is small because the shape already exists.

- `MemoryUpdateProposal` and `MemoryIngestResult` are already `core` types
  (`core/types.py:186` and `:260`). Nothing has to move into `core`.
- `MemoryIngestor.ingest` already reads
  `async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult`
  (`ingest.py:88`).

So what is missing is a name in `core/protocols.py`, not a design.

## Decision

### 1. `MemoryWriter`, one method, in `core/protocols.py`

`core/protocols.py` gains, immediately after `MemoryPolicy` and before
`ContextProvider` — the position that keeps the memory contracts
(`MemoryStore`, `MemoryPolicy`, `MemoryWriter`) adjacent and reads in the order
the path runs:

```python
@runtime_checkable
class MemoryWriter(Protocol):
    """The memory write path: conflicts, policy, persistence, in one call."""

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Resolve conflicts, ask the policy to rule, and apply its ruling."""
        ...
```

`@runtime_checkable` matches every other Protocol in the file. The parameter
keeps the name `proposal` and stays positional-or-keyword, because a structural
match requires the names to agree and the point is to match the implementation
that exists.

**The method keeps the name `ingest` rather than a tidier `write`.** A rename
would make this a change to `memory` as well as an addition to `core`, and the
whole claim of this ADR is that the write path needs no modification.

### 2. `MemoryIngestor` satisfies it structurally, unmodified — verified

Checked, not assumed, against `HEAD` (`34464b4`), by type-checking an assignment
of a real `MemoryIngestor` to the Protocol above under the repository's own
`mypy --strict` settings, and by an `isinstance` check at runtime:

- `mypy --strict`: `Success: no issues found in 1 source file`.
- `isinstance(MemoryIngestor(store=…, policy=…), MemoryWriter)` → `True`.

So `memory/ingest.py` is not edited by the implementing change. `MemoryIngestor`
gains a contract it already satisfies; its constructor, its conflict tuning, its
merge rule and its error behaviour are untouched.

### 3. One method suffices, because conflict detection is not a separate stage

The question the extraction raises is whether `LearningLoop` needs something
`ingest` does not expose — conflicts, most obviously, since it computes them
today.

It does not, and the code is unambiguous about why. `LearningLoop._conflicts_for`
has exactly one caller, `_ingest` (`loop.py:345`), which passes the conflicts
straight to `self._policy.decide` and then discards them: `_apply` receives only
the decision and the proposed record. Nothing in `respond`, in `TurnResult`, or
in the tuple `learn` returns carries a conflict anywhere. The loop computes
conflicts solely because it has to feed the policy — a step that is *inside*
`ingest` on the other side of the seam.

The same holds for the conflict *tuning*. `conflict_threshold` and
`conflict_limit` reach only `_conflicts_for`; `_check_tuning` validates them and
nothing else reads them.

So the seam needs no `detect_conflicts` member, no conflicts-in parameter, and no
conflicts field added to `MemoryIngestResult`. Widening the contract to expose an
intermediate value one consumer computes only in order to hand it back would make
the duplication a permanent feature of the contract instead of deleting it. If a
consumer ever needs to *show* a user what a proposal contradicted, that is a
change to the result type, decided then, with a use case in hand.

### 4. `orchestration` injects it, and delegates

`LearningLoop` takes `writer: MemoryWriter` alongside its existing collaborators
and `learn` becomes: process the event into proposals, then
`await self._writer.ingest(proposal)` for each, in order. Three things follow,
and they are the decision, not incidental consequences:

- **`_conflicts_for`, `_apply` and `_expiry` are deleted** from `loop.py`, with
  the `conflict_threshold` and `conflict_limit` constructor parameters and their
  half of `_check_tuning`. That is the duplication in cost 1, removed rather than
  synchronised. `retrieval_limit` stays — it belongs to the read half — and so
  does `_now_utc`, which `_goal_from` still uses.
- **`MemoryPolicy` stops being a `LearningLoop` collaborator.** The writer holds
  the policy, as `MemoryIngestor` already does. A loop that kept its own policy
  reference would be able to rule on a proposal it then handed to a writer
  holding a different one.
- **`MERGE` is applied**, by the fold that already exists, and reports the target
  record's id. Cost 2 disappears without `orchestration` learning what a merge is.

This is a breaking constructor change to `LearningLoop`, in the package whose
whole purpose is wiring. It is called out here so the implementing change is
expected to carry it, not discover it.

### 5. Failure semantics: `MemoryStoreError` crosses the seam

`MemoryStoreError` is the only `AssistantError` the write path raises today, from
three places, all inside the implementation: a failing `search` during conflict
resolution, a failing `add`, and `ingest.py:132`'s refusal of a `MERGE` naming a
target that is not among the conflicts. The Protocol documents it in a `Raises:`
clause, the way `Planner.plan` documents `PlanningError` and
`PlanStore.commit_transition` documents its three.

Nothing new is invented for this seam. In particular there is **no**
`MemoryWriteError` and no rule that a policy's failure is repackaged: a policy
that raises propagates as whatever it raised, which is what `LearningLoop` does
today and what `MemoryIngestor` does today. Introducing an error type here would
be a change to the write path's behaviour under the cover of naming it.

`learn`'s existing guarantee is unchanged by delegation, and this is worth being
precise about because it is easy to assume otherwise: proposals are still applied
one at a time, in order, independently, so a failure on the third proposal leaves
the first two written. ADR-0022 §4 states that and it survives verbatim.

### 6. What ratification does to ADR-0022

Recorded in the form ADR-0017 §7 requires and ADR-0026 §6 most recently applied —
a qualified `Status` line plus a dated header note, with no ratified text
rewritten. This ADR merges as `Proposed`, so **the edit is not made by this
change**: writing "amended by ADR-0028" onto ADR-0022 while ADR-0028 is only
proposed is the state claim ADR-0019 forbids. Its exact form, to apply on
ratification:

- ADR-0022's `Status` line becomes
  `- Status: Accepted, §4 amended by ADR-0028`.
- A dated note is appended to ADR-0022's header, after `Date`:
  `Amended: <ratification date> by ADR-0028 — §4's "MERGE is reported but not
  applied" is withdrawn as a standing limitation. It describes the loop until the
  MemoryWriter triad lands and learn delegates to it; from then a MERGE is
  applied by memory's own fold and reported with the target's record id. §4's
  remaining clauses stand unchanged — ACCEPT, STORE_TEMPORARY, REJECT/ASK_USER,
  "no proposals is a normal outcome", in-order independent application with no
  transaction, the non-atomic search → decide → add across calls (issue #104),
  and last-write-wins on a repeated record id.`
- Nothing else in ADR-0022 is edited. Its §§1–3, §4a, §5 and Consequences stand
  as ratified, including Consequences item 1, which named this gap correctly and
  is answered by this ADR rather than falsified by it.

The note is worded around the implementation because that is when the behaviour
changes; the amendment is recorded at ratification because that is when the
decision becomes binding.

### 7. Deliberately out of scope: batch and transaction (#104)

ADR-0022 §Consequences item 2 filed the absence of any batch or transaction on
`MemoryStore` as issue #104: multi-proposal learning cannot be atomic, and
`search → decide → add` is not atomic across concurrent calls either.

This ADR neither solves nor ignores that. `MemoryWriter.ingest` takes **one**
proposal, which is the shape `MemoryIngestor` has, so delegation moves the
non-atomic sequence from `LearningLoop` into `MemoryIngestor` and changes its
guarantees in neither direction. Giving this Protocol a
`ingest_all(proposals) -> Sequence[MemoryIngestResult]` would look like the fix
and not be one: atomicity has to come from the store, and a batch method over a
store with no transaction is a loop with a better name — an atomicity guarantee
that holds only when nothing else writes, which ADR-0022 §4 already rejected as
worse than a documented absence. #104 stays open and stays `MemoryStore`'s.

### 8. The triad is owed by the implementing change, not by this one

This ADR ships **no code**. Golden rule 5 is that a Protocol's ADR is ratified and
merged as its own PR before anything implements against it, so
`core/protocols.py` is not touched here.

When the implementation comes, `CONTRIBUTING.md` → "Adding a Protocol" requires
the triad in **one** change:

1. `MemoryWriter` in `core/protocols.py`. No new `core/types.py` entry — §Context
   verified both exchanged types are already there.
2. A shared conformance suite, `MemoryWriterContract`, under `tests/memory/`
   beside `MemoryStoreContract` and `MemoryPolicyContract`.
3. A canonical `FakeMemoryWriter` in `ai_assistant.testing`, **plus** the
   concrete `TestFakeMemoryWriterContract` subclass that runs the suite against
   it — the abstract base collects nothing on its own.

The obligations the suite encodes are the ones the write path is already held to
by `tests/memory/test_ingest.py`, restated as contract rather than as one
implementation's tests: conflicts are resolved *before* the policy is asked and
the ids are carried on the proposal the policy sees; `ACCEPT` stores the record
and returns its id; `STORE_TEMPORARY` stores it with an expiry stamped from the
writer's clock; `REJECT` and `ASK_USER` write nothing and return a `None` record
id; `MERGE` folds into the named target, keeps the target's id, and returns it;
and a `MERGE` naming a target absent from the conflicts raises `MemoryStoreError`
rather than storing the proposal as new.

The suite deliberately does **not** fix the conflict threshold, the conflict
limit, or the fold's own rule. Those are `MemoryIngestor`'s tuning and
`memory`'s semantics, and a suite that pinned them would stop being a contract
and start being a second copy of one implementation — the mistake this ADR exists
to undo.

`tests/core/test_protocol_triad.py` enforces all three mechanically, and its
`_LEGACY_DEBT` is a closed, empty set: a new Protocol cannot be exempted. Adding
`MemoryWriter` without its triad turns the gate red, which is the intended
outcome and the reason the triad is named here rather than left to be remembered.

## Consequences

**Easier.**

- The learning loop commits what it decides. Every `MemoryDecisionKind` now has
  an effect, so "the policy ruled `MERGE`" and "memory changed" stop being
  different questions.
- One conflict heuristic. Tuning it is one edit in one class, and the two
  constructors that could disagree about a threshold become one.
- `orchestration` shrinks toward what it is for. `learn` becomes process → ingest,
  with no `memory` semantics resident in the wiring package — the property
  ADR-0022 §Context called the thing actually being tested.
- Any writer can be swapped in: a writer that batches, one that audits its
  proposals, one that queues them for later, all behind the same seam.

**Harder.**

- **A third `core` Protocol touching memory**, so the memory contract surface is
  now `MemoryStore`, `MemoryPolicy`, `MemoryWriter` — three seams a future
  refactor must move together. Accepted because the alternative on offer is not
  "fewer contracts", it is the same three responsibilities with one of them
  unreachable and duplicated.
- **`LearningLoop`'s constructor breaks**, and its tests move with it: the
  conflict-tuning validation tests and the `MERGE`-not-applied test become tests
  of the writer seam, not of the loop.
- **A conforming writer can be wrong in a way the loop cannot see.** Today the
  loop's write half is inspectable in `loop.py`; afterwards it is an injected
  object, and a writer that never persists conforms structurally. That is the
  standing cost of every Protocol here and the conformance suite is the answer to
  it — which is why §8 makes the suite non-optional rather than a follow-up.

**Revisit when** a consumer needs the conflicts a ruling was made against (§3),
when #104 gives `MemoryStore` a transaction and batch ingestion becomes
expressible (§7), or when a second `MemoryWriter` implementation exists — the
first real test of whether the suite encodes the contract or one implementation.
