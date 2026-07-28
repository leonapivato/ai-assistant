# 73. The band-scoped read is an enumeration; inspection shows live beliefs

- Status: Proposed
- Date: 2026-07-27
- **This is a contract change.** §1 adds one method — `list_beliefs` — to the
  `MemoryStore` Protocol in `core/protocols.py`. Golden rule 5 therefore applies:
  this ADR ships as **its own docs-only PR**, is reviewed while still `Proposed`
  so a finding can still change the decision, and is flipped to `Accepted` on
  merge (`CONTRIBUTING.md`, "Contract ADRs land before their implementation";
  ADR-0015 §5). **No code changes with it.** The Protocol change, the conformance
  extension, both stores, the canonical fake, and the façade/CLI surface are the
  next lane (§8).
- **Adds no `core/types.py` type.** The read exchanges `BeliefBand`,
  `MemoryKind` and `MemoryRecord`, all of which exist (ADR-0072 §2 landed the
  first). The contract owed is one method signature and its read semantics, and
  nothing else.
- **Amends and supersedes nothing.** Applying ADR-0070 §1's test: ADR-0072 §7
  ruled the *obligation* and explicitly deferred the *signature* "to the slice
  that holds the consumer"; §10 deferred live-only-versus-live-plus-retired to
  the same slice. This ADR settles what ADR-0072 left open and changes no clause
  it closed — §7's store-level rule and its refusal of adapter-side filtering of
  `export` are honoured as written (§1), and its both-axes read rule is honoured
  as written (§2, §3). No ADR's Status line is edited.
- **Refs:** ADR-0072 (the bands, §7's obligation, §5's precedence, §6's
  presentation rule, §10's deferrals — the ADR this one completes), ADR-0007
  (the data-rights surface `delete` belongs to, and the "forget this" command it
  anticipated), ADR-0045 §6 (the read-time predicate and what `export` keeps) and
  §1 (transaction time deferred — the history view's missing prerequisite),
  ADR-0042 (§1 the façade and its DTOs, §6 what an adapter may do, §7 the CLI),
  ADR-0038 §1a and §2 (an assertion is its own warrant; the recoverability
  asymmetry the deletion ceremony rests on), ADR-0022 (the explicit correction
  loop `learn` already runs), ADR-0021 §4 (the bounded-read precedent
  `AuditTrail.recent` sets), ADR-0004 §6 (the data rights this surface delivers).

## Context

ADR-0072 closed the keystone question of this arc — the profile is a *band* of
one store, not an artifact — and left two things open on purpose, both addressed
to whichever lane first held a consumer:

- **§7: the band-scoped read is owed; its signature is deferred.** It ruled that
  the read is **store-level** (fetching `export()` and re-filtering in an adapter
  is refused: it would put a live-at-now computation and a clock into
  `interfaces/`, and duplicate the predicate ADR-0045 §6 centralised), that it
  honours both read-time axes exactly as `get`/`search` do, and that the choice
  between an enumerating `list_beliefs(*, bands, kinds, limit, offset)` and a
  `bands`/`sources` filter on `search` belongs to the consumer, "because the two
  differ in exactly the way a consumer settles: enumeration wants an offset and a
  stable order and no query, while a filter wants relevance."
- **§10: whether the inspection surface reads live-only or live-plus-retired.**

The consumer has now arrived. The roadmap's leg 1 slice 3 states its exit test in
product terms: *the user can read the assistant's beliefs about them, see why each
is held, and kill any of them.* That is where ADR-0007's `delete`/`export`
obligations first meet an interface, and it is the first read of the store that is
not a retrieval.

The dated position, at the time of writing:

**The store offers no way to ask what it holds.** `get` takes an id, `search`
takes a query and ranks by relevance, `export` returns every retained record
including window-closed ones and cannot filter. "Show me what you believe about
me" is none of those: it has no query text, it wants a stable order and a page,
and it wants the closed windows left out.

**The derived band is still empty.** Nothing writes `OBSERVED` or `INFERRED`;
ADR-0009's `RuleBasedFeedbackProcessor` stamps `USER_ASSERTED`/1.0 by
construction (ADR-0072 Context). So the surface decided here will, on the day it
ships, list a store of assertions. That is not an argument for deferring it —
ADR-0072 §5 makes the reading rule something to fix *before* the first producer —
but it is a constraint on scope: this ADR must not ratify machinery whose only
justification is a band that does not yet hold a record.

**The adapter cannot reach the store, and must not.** ADR-0042 §6 forbids an
adapter from reading memory directly; §1 makes the seam a concrete
`orchestration` façade returning its own result DTOs. So the surface is two
layers — a façade method the engine implements and CLI commands that render it —
and the only *contract* question is what the store must offer underneath.

**Three forces make this a decision rather than an implementation detail.**

1. **A `MemoryStore` method is a breaking change** (golden rule 5). Every
   implementation — `SqliteMemoryStore`, `InMemoryMemoryStore`, `FakeMemoryStore`
   — must grow it, and its read semantics must be identical across all three or
   consumers will differ by backend. That is a contract, ratified first.
2. **The two candidate shapes are not interchangeable, and only one has a
   consumer today.** Enumeration and relevance-filtering satisfy ADR-0072 §7's
   obligation equally; ratifying both would ratify one on speculation. Which one
   leg 1 exercises, and what the *other* one is waiting for, has to be said out
   loud or the next lane will guess.
3. **"See why each is held" and "kill any of them" are contract-adjacent
   product promises.** VISION §Principle 1 asks that every inference carry
   "evidence, confidence, scope, and a way to be corrected"; ADR-0072 §6 rules
   that provenance must survive presentation. What the surface *must* convey, and
   what deleting a belief means for a band that can re-derive, are decisions that
   would otherwise be made by whoever writes the first Rich table.

## Decision

### 1. The band-scoped read is an enumeration: `list_beliefs`

`core/protocols.py` — `MemoryStore` gains one method (illustrative signature; the
semantics below are the contract):

```python
async def list_beliefs(
    self,
    *,
    bands: Sequence[BeliefBand] | None = None,
    kinds: Sequence[MemoryKind] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[MemoryRecord]:
```

We settle ADR-0072 §7 in favour of **enumeration**, and we do **not** add a
`bands` filter to `search` in this ADR.

The consumer decides it, exactly as §7 said it would. "Show me what you believe
about me" carries **no query text**. A relevance filter on `search` would have to
be handed something to be relevant *to*, and the only honest candidates are a
sentinel empty query — which `MemoryStoreContract.test_empty_query_matches_nothing`
already pins to matching nothing — or a fabricated query the surface invents,
which would silently rank the user's own beliefs by their similarity to a string
they never typed. Enumeration also needs an `offset` and a **stable total order**
(§2), neither of which relevance ranking provides: a similarity score is not a
paging key.

**The other shape loses now and is not refused.** ADR-0072 §5 has a *second*
consumer — the assembler that fills a prompt budget "`ASSERTED` first, then
`ATTESTED`, then `DERIVED`", reading per band and composing rather than reading
once and sorting. That consumer genuinely wants relevance within a band, which
enumeration cannot serve. It does not exist: `orchestration` retrieves with a
band-blind `search` and prompt assembly is a later lane. So the `bands` filter on
`search` is **deferred with its consumer** (§10) — the standing discipline
ADR-0028 §7 applied to batch ingestion and ADR-0045 §1 to as-of retrieval — and
this ADR ratifies only what leg 1 exercises. Deferring it costs nothing later: the
two reads are additive, and neither forecloses the other.

**The filter is by band, not by source.** `bands` takes `BeliefBand` values, not
`MemorySource` ones. The band is the vocabulary ADR-0072 §2 ratified and the unit
the user reads; a `sources` parameter would push `band_of` into every caller and
would let a caller ask for half a band — `OBSERVED` without `INFERRED` — which
ADR-0072 §4 deliberately keeps indistinguishable to the supersession law. A
consumer that one day needs source granularity is asking a different question and
may argue for it then.

**No inverse mapping is added to `core`.** An implementation that must pre-filter
by source (§2) derives the source set for a band by applying the total `band_of`
over `MemorySource`'s members; a `sources_of(band)` helper in `core/types.py` is
declined for want of a second caller, and because a second, hand-written mapping
is a mapping that can drift from the one whose totality the gate enforces.

**`None` means every value; an empty sequence selects nothing — for `bands` and
for `kinds` alike.** This is the `kinds` convention on `search` read literally
("if given, restrict results to these") and it is what all three implementations
already do there (`wanted = {...} if kinds is not None else None`). Both
parameters are stated, not just the new one: leaving `kinds` to be inferred from
`search` is how one implementation comes to read `kinds=()` as "no filter" — the
opposite outcome, every record instead of none — on a method whose suite never
asked. The two filters compose by conjunction: a record is listed when its band
is selected **and** its kind is.

### 2. What the enumeration guarantees: order, paging, and the two read-time axes

These are the obligations the conformance suite must encode. They are observable
properties, not mechanisms; how a backend achieves them is its own business.

- **Both read-time axes are honoured, exactly as `get`/`search` honour them**
  (ADR-0072 §7, ADR-0007 §2, ADR-0045 §6): an expired record is never returned,
  and neither is a record not live at now — both ends of the window enforced. So
  "what do you believe about me" and "what do you retrieve" cannot disagree.
- **The order is total, stable, and specified: `provenance.last_updated`
  descending, ties broken by `id` ascending.** Some total order must be named or
  two stores answer the same page differently while each believes it conforms —
  the argument `AuditTrail.recent` already makes, applied to a second store.
  Newest-revision-first is the right default for inspection ("what has the
  assistant recently come to believe"), `last_updated` is present on every record
  (`Provenance` requires it), and supersession moves it, so a corrected topic
  surfaces where the user will look for it.
- **A page is full whenever enough matching records exist.** A request for
  `limit` records returns exactly `limit` when the filtered set — after **both**
  filters and both read-time axes — has at least `offset + limit` members. This
  forbids the short-page failure a naive post-filter produces (filtering after the
  limit is applied), which is the one way paging silently loses records.
  `search`'s over-fetch-and-post-filter caveat (ADR-0007 §Consequences) is a
  *ranking* concession and is not licence here.
- **`limit` and `offset` are bounded on both ends, and a value outside the range
  raises `ValueError`.** The range is `0 <= value < 2**63` — non-negative, and
  representable as a signed 64-bit integer. `limit=0` returns an empty page:
  asking for nothing is a question with an answer.

  Both ends are named because both are places two backends silently disagree.
  *Negative* is `AuditTrail.recent`'s argument and it applies with more force
  here: this is the first `MemoryStore` read that reaches a backend as a literal
  `LIMIT ?`/`OFFSET ?`, where SQLite reads `LIMIT -1` as *no limit at all*,
  turning the bounded read into the unbounded one it exists to avoid. *Too large*
  is the same failure from the other side: Python's `int` is unbounded and
  SQLite's parameter binding is not, so `offset=2**63` raises an `OverflowError`
  out of the driver — a non-`AssistantError` escaping a seam whose contract says
  nothing about it — while an in-memory store answers the same call with an empty
  page. Refusing the argument is the only outcome both can implement, and it is
  the treatment `recent` already chose over clamping: a caller that asked for
  something meaningless should learn that, not be served something it did not ask
  for.

  This deliberately differs from `search`, whose suite pins a non-positive limit
  to matching nothing: `search`'s limit is a ranking cut applied after a KNN, and
  nothing there can invert into unboundedness or reach a bind parameter.
- **Offset paging over a mutating store may skip or repeat a record.** A record
  revised between two pages moves in the order, and a record deleted between them
  shifts every later one. This is accepted and named rather than closed: a cursor
  or a snapshot read is machinery with no consumer at a personal store's scale,
  and a listing that a user re-runs is not a transaction.
- **The default `limit` is bounded.** An unbounded read of a Tier 1 store by
  default is a shape worth not offering (ADR-0021 §4). 50 is the figure, matching
  `AuditTrail.recent`.
- **`score` stays `None`.** This is not a retrieval, so no relevance was
  computed, and the field says so rather than carrying a stale or invented number.
- **Records are detached snapshots**, like every other `MemoryStore` read
  (`MemoryStoreContract.test_stored_records_cannot_be_mutated_by_the_caller`), and
  the module's standing cancellation (ADR-0060) and input-observation (ADR-0065)
  clauses bind this method as they bind every other.

### 3. Inspection reads live beliefs only; history is a different surface

We settle ADR-0072 §10's second deferral: **the inspection surface reads
live-only**, and `list_beliefs` grows no axis for retired records.

"What do you believe about me" is a question about the present. A retired record
is not a belief the assistant holds; it is a record of one it used to hold, which
ADR-0045 §6 keeps on disk and in `export` precisely because it is *history*
rather than *belief*. Mixing the two in one listing would either present retired
records as current — the failure ADR-0072 §6 exists to prevent, in its most
literal form — or force every row to carry a status the user must read to know
whether it counts.

**How the user sees that their correction landed**, without a history view:

1. **At the moment of correction.** `learn` already reports the ruling and the
   policy's reason; a supersession renders as a replacement (`LearnDecision.SUPERSEDED`),
   and `IngestSummary.record_id` names the record left live. The correction loop's
   receipt is issued where the correction happens.
2. **In the listing afterwards.** A correction does not edit a derived belief; it
   retires one and writes another (ADR-0072 §4). So the topic the user corrected
   appears in the next listing in the `ASSERTED` band where it stood `DERIVED`
   before, carrying their own words. The band flip *is* the visible evidence, and
   it is visible precisely because §4 keeps the two records distinct.
3. **In `export`.** Every retired record is retained and exported (ADR-0045 §6).
   The data-rights route to history exists and is ratified; what does not exist is
   a rendered view of it.

**A rendered history view is deferred, and its prerequisite is named.** "What did
you used to believe" is answerable only in a degraded form today: a retired
record's closed `valid_until` says *when* its window closed, but nothing links it
to the record that replaced it, so the view could show a retirement with no
author — "this was retired on 3 July", never "your correction replaced it". The
missing link is a supersession pointer or the transaction-time axis ADR-0045 §1
deferred for want of a consumer. A history view is the consumer that would force
that decision, and it should be taken up as one decision, not smuggled in as a
flag on this read (§10).

### 4. What the surface must convey per belief

ADR-0072 §6 rules that a belief reaching a prompt is rendered *as a belief*,
carrying its band and its confidence. Inspection is where that rule is least
optional: it is the whole point of the screen. Per belief, the surface conveys:

- **Its band** — asserted, derived, or attested. Never omitted, never implied by
  position alone.
- **Its confidence.**
- **Its kind** — the four typed kinds are what the `kinds` filter selects on, and
  a preference and a fact read differently.
- **Its content** — `MemoryBase.content` is the "canonical text rendering", which
  is the readable form of every kind. The kind-specific fields (a preference's
  `strength`, an episode's `participants`) are **not** carried: `content` is what
  the store itself uses to represent the record, and adding six more fields for a
  band that holds no records yet is surface without a consumer.
- **Why it is held.** For an `ASSERTED` belief the answer is the band itself
  plus when it was last revised: a user's assertion is its own warrant (ADR-0038
  §1a) and there is nothing further to cite. For a `DERIVED` one it is
  `Provenance.evidence`, the citations ADR-0072 §3 obliges it to carry — conveyed
  as the **opaque references they are**, echoed and never interpreted by the
  adapter. *Resolving* a citation into readable evidence is deferred (§10): it is
  a second read per belief, against a band with no producer, and what a citation
  that no longer resolves should render is exactly the open half of #431.
- **When it was last revised** — `provenance.last_updated`, the transaction stamp
  (ADR-0045 §3), which is also the sort key (§2). This is what "since when have
  you believed this" means today.
- **Its window, where an end is set.** Every listed belief is live by
  construction, so an unbounded window carries no information; a `valid_until` in
  the future does ("believed until…") and is conveyed.
- **Its id**, opaque, so the user can name it to §5's deletion.

### 5. Killing a belief: one contract, show-then-confirm, a band-appropriate warning

"Kill any of them" is `MemoryStore.delete` (ADR-0007 §1), reached through the
façade. **The contract does not change**, and in particular the store does not
grow a band-conditional refusal. ADR-0004 §6 gives the user an unconditional
right to delete their data; a store that refused to delete a belief because of the
band it sat in would make a data-right conditional on a classification the system
assigned. The store deletes what it is told to delete.

**The ceremony is the surface's, and it is uniform in mechanism and asymmetric in
message.**

- **Show, then confirm.** The surface renders the belief it is about to destroy —
  the same fields §4 lists — and takes the user's confirmation before deleting. A
  person cannot consent to destroying something they were not shown; this is
  ADR-0042 §4's rule for a parked action ("render a prompt a human can actually
  judge") and ADR-0052 §4's ("a non-interactive approval must not run a recovered
  action the user never saw") applied to the one other irreversible thing this
  system does on a user's word. The existing `--yes` idiom of `ask`/`resume` is
  the bypass, and it renders before acting for the same reason `resume` does.
- **The warning differs by band, because the consequence does.** ADR-0072 §1 is
  explicit that an `ASSERTED` belief is not re-derivable and losing one is
  unrecoverable (ADR-0038 §2), while a `DERIVED` one is re-derivable *while the
  observations behind it are retained* — deleting the belief does not delete its
  evidence. `ATTESTED` is the same shape for a different reason: deleting our copy
  of what a connected source reported does not change the source, and a
  re-ingestion can bring it back. So the obligation is: **the surface must not
  represent a deletion as more final than it is, nor as less final.** Destroying
  an assertion is permanent and is said to be; destroying a derived or attested
  belief removes the belief and not its origin, and is said to be. The wording is
  the implementing lane's, exactly as ADR-0072 §6 leaves the prompt-assembly
  phrasing to its lane.
- **This surface deletes what it can show.** `get` is live-only, so a retired
  record's id is not resolvable here and the surface declines it rather than
  deleting something it cannot display. `MemoryStore.delete` itself still reaches
  any record by id and is unchanged, so no right is lost — what is missing is a
  *surface* for retiring history, which belongs with the history view §3 defers
  and is filed (§10).

**The show and the delete are two calls, and the window between them is named
rather than closed.** The render reads at one instant and the delete acts at
another, so a write landing between them is deleted without having been shown.
This ADR does **not** add a conditional delete keyed on a revision, and the
reasons are three:

- **What the window can actually admit is bounded by id semantics.** `add` is an
  upsert whose "`id` is the caller's idempotency key" — an id names one belief,
  and nothing in this system mints an existing id for an unrelated one. Of the two
  rulings that write over a conflict, `SUPERSEDE` mints a *fresh* id (ADR-0045 §4)
  and so cannot occupy the rendered one, and `REINFORCE` inherits the target's id
  (ADR-0045 §5b) and folds the *same* belief. So the reachable case is that the
  user is shown belief X and deletes a strengthened X — not that they are shown
  one belief and destroy another.
- **The residue is a stale rendering, and the user's intent survives it.** The
  user names a belief and asks for it to be gone; a fold that landed a second
  earlier changes what the belief's text says, not which belief it is.
- **The mechanism would be a concurrency primitive ratified ahead of its
  consumer.** A compare-and-delete needs a revision on the record and a
  compare-and-swap seam — exactly what ADR-0046 §5 deferred "for want of a
  consumer that runs two writers on one store", and what #248 tracks. A deletion
  surface is not that consumer: it is one reader with a confirmation prompt.
  Building the primitive here would bless a seam with no implementation contact
  (`CONTRIBUTING.md`, "Spike first if you need to").

What follows is an obligation on the *adapter*, not a new contract clause: the
render is taken as late as it can be, immediately before the prompt, so the window
is the human's answering time and nothing longer. Revisit when a second concurrent
writer genuinely exists — the hub (leg 5) is where that becomes real — at which
point this is one case of #248's compare-and-swap question and not a private one
(§10).

### 6. Correcting is `learn`; inspection adds no second correction path

The roadmap's leg 1 names "list, show, correct, and forget". **Correction already
exists**: `assistant learn --kind correction` runs the ratified loop — feedback →
proposal → `MemoryPolicy` → `SUPERSEDE` → the window closes and the correction is
written (ADR-0022, ADR-0038, ADR-0040, ADR-0045 §4). This ADR adds no second
route, and no edit-in-place: a belief is never rewritten to look like another
(ADR-0072 §4), which an "edit" affordance would quietly do.

The composition is the point, and the two verbs are **not** interchangeable:

- **Correct** (`learn`) — the belief is *retired*, the user's version is written
  in its place, and the retired record stays on disk and in `export`. The system
  keeps a record of having been wrong.
- **Forget** (`delete`) — the record is *destroyed*. Nothing remains, in `export`
  or anywhere else.

The surface must not present one as the other. A user who wants their belief
fixed should correct it; a user who wants it gone should forget it, and losing the
history is what they asked for.

### 7. Where the surface lives: façade methods and CLI commands

Per ADR-0042 §1 the seam is the concrete `orchestration` façade, which is **not**
a contract surface — so the names below are ratified as *shape*, not as spelling,
and the implementing lane owns the mechanism.

**Façade (concrete, `orchestration`, no `core` change):**

- `beliefs(*, bands, kinds, limit, offset) -> tuple[Belief, ...]` — relays the
  filters to `MemoryStore.list_beliefs` and translates each record.
- `belief(record_id) -> Belief | None` — the single-belief read §5's
  show-then-confirm needs, backed by the ratified `MemoryStore.get` and therefore
  live-only like everything else here.
- `forget(record_id) -> bool` — `MemoryStore.delete`, relayed. `False` is "no such
  belief", which the adapter renders and maps to an exit code.

**The `Belief` DTO** is a frozen `orchestration` dataclass carrying exactly §4's
fields, alongside `TurnOutcome` and `IngestSummary` and for their reason: it
crosses no *subsystem* boundary, only `interfaces` (ADR-0042 §1). It is not a raw
`MemoryRecord`, and the deciding reason is not tidiness: **`band_of` is applied
here, once, in the engine.** Classifying a record into its band is the projection
ADR-0072 §1 ratifies, and an adapter doing it would put the projection in
`interfaces/`. The DTO also flattens a four-member discriminated union that an
adapter would otherwise branch over, and drops `score`, which is meaningless on
this path (§2).

**No count is returned.** Neither the store read nor the façade reports how many
beliefs match. A total is a second query against a Tier 1 store, wanted by nobody
here — "is there more" is answered by asking for the next page — and it is the
kind of field that becomes load-bearing for a UI nobody has designed.

**CLI (`interfaces/cli.py`, beside `ask`/`resume`/`learn`):** a listing command
with `--band`, `--kind`, `--limit` and `--offset`, and a deletion command taking a
belief id and honouring §5's ceremony. `forget` is ADR-0007's own word for it
("a CLI 'export my data' / 'forget this' command"). Both obey the existing adapter
rules unchanged: one error boundary per command mapping an `AssistantError` to a
rendered message and an exit code, engine-supplied text neutralised for the
terminal on render, and the façade closed on exit (ADR-0042 §7).

**A standalone `show` command is declined.** The listing conveys every field a
belief has (§4), so a per-belief view would add a command and no information; the
single-belief *read* exists on the façade because §5's confirmation needs it, not
because the CLI needs a verb. Revisit when the listing has to truncate to stay
readable.

### 8. What the implementing lane owes

This **changes** an existing Protocol rather than adding one, so there is no new
triad — but the triad discipline carries over, and `CONTRIBUTING.md` is explicit
that the mechanical check does not enforce it here: "add a method to an existing
Protocol and leave its suite alone and the gate stays green. Keeping the suite
abreast of the contract is a review concern." So it is stated as an obligation of
the next lane:

1. **The Protocol** — `list_beliefs` on `MemoryStore` in `core/protocols.py`,
   with §1's signature and §2's semantics in its docstring.
2. **The shared conformance suite** — `tests/memory/memory_store_contract.py`
   gains a clause for **each** obligation in §2: both read-time axes on both ends
   of the window, the total order including the `id` tie-break, a full page under
   *both* filters (the short-page failure), the out-of-range refusals at **both**
   ends (negative, and beyond the 64-bit bound), `limit=0`, `None` versus empty
   versus non-empty for `bands` **and** for `kinds`, the two composing by
   conjunction, detachment, and `score is None`. An obligation with no clause is
   an obligation nobody meets — and the two that would otherwise be inferred from
   `search` rather than tested (`kinds=()`, the argument range) are exactly where
   two backends diverge in silence.
3. **The canonical fake** — `FakeMemoryStore` in `ai_assistant.testing`
   implements it and passes the extended suite through `tests/memory/test_fake_store.py`.
4. **Both production stores** — `InMemoryMemoryStore` and `SqliteMemoryStore`.
   The SQL one is where §2's full-page rule bites: a band/kind filter applied
   after `LIMIT` returns short pages, so the filter belongs in the query.
5. **The façade and the CLI** (§7), which need no contract change.

Whether all of that is one lane or two is the dispatcher's call; the contract
half must not land without its suite.

### 9. Explicitly declined

- **A `bands`/`sources` filter on `search`.** §1 — deferred with its consumer, not
  refused.
- **An `include_retired` axis on the band-scoped read.** §3. It would put two
  different questions behind one flag and would contradict ADR-0072 §7's
  both-axes rule as written.
- **A band-conditional `delete`.** §5. It makes a data right conditional on a
  classification the system assigned.
- **An edit-in-place affordance.** §6. Correction retires and writes; editing
  would rewrite a derived belief to look like an asserted one.
- **A `sources_of(band)` inverse in `core/types.py`.** §1. Derivable from the
  total `band_of`, and a second mapping is a second thing to drift.
- **A total match count.** §7.
- **A standalone `show` command.** §7.
- **Cursor-based paging.** §2 — offset paging's known race is named and accepted.
- **A conditional (compare-and-)delete keyed on a record revision.** §5. It is
  ADR-0046 §5's deferred compare-and-swap wearing a different hat, and a
  confirmation prompt is not the second writer that would justify it.

### 10. What this ADR does not decide

- **The `bands` filter on `search`** that ADR-0072 §5's band precedence needs
  (§1). Due with the prompt-assembly consumer that applies the precedence; it is
  additive to this read.
- **A rendered history view — "what did you used to believe"** — and its
  prerequisite: a link from a retired record to what replaced it, or the
  transaction-time axis ADR-0045 §1 deferred (§3). Also the surface for deleting a
  retired record, which §5 leaves unreachable.
- **Resolving an evidence citation into readable evidence**, and what a citation
  that no longer resolves renders (§4). The open half of #431, due with the first
  producer of derived beliefs.
- **Whether a `MemoryStore` write ever becomes conditional on a revision** (§5),
  which would close the show-then-confirm window and several others. That is
  ADR-0046 §5's deferral and #248's question, due when a second concurrent writer
  exists; this ADR neither closes it nor pretends the window is absent.
- **An `export` CLI command.** ADR-0007's other data right needs no contract
  change — `MemoryStore.export` has existed since ADR-0007 — so it is an
  implementation question, not a contract one, and it is deliberately not bundled
  into this decision. Its interesting question is presentational and belongs with
  §3's history view: an export includes retired records, so rendering one has to
  say so.
- **The observer** (leg 3), **consolidation, decay and salience** (leg 7), and
  **prompt assembly** — all carried forward from ADR-0072 §10 unchanged. This ADR
  decides what a user reads, not what the system writes or what reaches a prompt.
- **Everything else ADR-0072 §10 filed** — the `Provenance` sub-1.0 validator, the
  `MemoryPolicy` evidence rule, whether §3's obligations extend to `Goal`, whether
  a correction may retire an `ATTESTED` record — is untouched here.

## Consequences

- **ADR-0072 §7 and §10 are closed.** The band split is readable: one method, one
  order, both read-time axes, three bands. The next lane implements a signature
  rather than choosing one.
- **The contract owed is one method, and no new type.** That is the smallest
  contract change this arc could have needed, and it is small because ADR-0072
  landed `BeliefBand` first.
- **`search` is untouched.** It stays band-neutral and confidence-neutral as
  ADR-0072 §5 ruled, and this ADR adds nothing to it — so a future proposal to
  filter or weight retrieval still has to argue with §5 rather than arriving as a
  parameter.
- **The user gets a read that cannot disagree with retrieval.** Both honour the
  same two axes through the same store-level predicate, which is what ADR-0072 §7
  refused adapter-side filtering to protect.
- **Leg 1's exit test becomes reachable**: list (§1, §7), see why (§4), kill (§5).
  What it will show on the day it ships is a store of assertions, because the
  derived band has no producer — the surface is correct and the band is empty, and
  the observer fills it.
- **Paging is honest and slightly weaker than a transaction.** A record revised
  between two pages can be skipped or repeated (§2). Accepted, named, and cheap to
  strengthen if a listing ever has enough rows for it to matter.
- **A confirmed deletion can destroy a record written after it was rendered**
  (§5). Accepted and bounded rather than closed: an id is an idempotency key, so
  the reachable case is a fold of the belief the user named, and the mechanism
  that would close it is ADR-0046 §5's deferred compare-and-swap. It gets better
  when a second concurrent writer forces that decision, not before.
- **The deletion ceremony constrains a lane not yet written**, like ADR-0072 §6's
  presentation rule: a surface that renders "deleted" for a derived belief that
  can be re-proposed teaches the user a false model of their own control, and it
  is far cheaper to state now than to retrofit onto a table that reads well
  without it.
- **A rendered history view is now a decision with a named prerequisite** rather
  than a feature someone adds as a flag. That is the point of deferring it here:
  the flag would have shipped without the link that makes it truthful.
- **Revisit if** a second consumer needs relevance within a band (the `search`
  filter, §1); if a listing grows large enough that offset paging's race or the
  absence of a count starts costing something real; if the first derived beliefs
  make an unresolved evidence citation a common rendering (#431); or if a user
  needs to reach their retired beliefs through anything but `export`.

## Alternatives considered

- **A `bands` filter on `search`, serving inspection too.** Rejected in §1. It
  needs a query the inspection surface does not have; the only ways to supply one
  are a sentinel empty query that matches nothing by contract, or a fabricated
  string that ranks the user's beliefs against something they never typed. It also
  cannot page: a similarity score is not a stable ordering key.
- **Both shapes, ratified together.** Rejected in §1. It satisfies ADR-0072 §5's
  assembler, which does not exist, and ADR-0028 §7's discipline is exactly that
  surface waits for its consumer. Nothing is foreclosed — the two are additive.
- **Filtering `export()` in the adapter.** Already refused by ADR-0072 §7 and not
  reopened: it would put a clock and a live-at-now computation into `interfaces/`
  and duplicate the predicate ADR-0045 §6 centralised in the store. Named here
  only so a reader does not mistake this ADR's silence for a live option.
- **`list_beliefs(*, sources=...)` keyed on `MemorySource`.** Rejected in §1. It
  pushes classification into every caller and lets a caller split a band the
  supersession law treats as one.
- **An `include_retired: bool` parameter, so one read serves inspection and
  history.** Rejected in §3. It contradicts ADR-0072 §7's both-axes rule, and — the
  reason that matters — a history view cannot be truthful today anyway: nothing
  links a retired record to what replaced it, so the flag would ship a view that
  can say when a belief died but never who killed it.
- **Live-plus-retired in one listing, with a status column.** Rejected in §3.
  Either the retired rows read as current — ADR-0072 §6's failure, verbatim — or
  every row carries a status the user must read before the row means anything.
- **A band-conditional deletion: refuse, or require a second confirmation, for an
  `ASSERTED` belief at the store.** Rejected in §5. The asymmetry it encodes is
  real (ADR-0038 §2), but a store that can refuse a data-rights operation is a
  store where ADR-0004 §6 is conditional. The asymmetry belongs in what the user
  is told, which is where it changes their decision.
- **`delete` returning the deleted record, so the surface can render it
  afterwards.** Rejected implicitly by §5's ordering: the render must happen
  *before* the destruction, or the confirmation is a receipt rather than a
  question. It would also widen a contract that does not need widening.
- **A conditional delete — `delete(record_id, *, expected_revision=…)` — so the
  confirmation cannot destroy a record written after the render.** Rejected in §5.
  It closes a real window, but the window's reachable content is a fold of the
  same belief (id is an idempotency key; `SUPERSEDE` mints a fresh id), and the
  mechanism is the compare-and-swap ADR-0046 §5 deferred for want of a second
  writer. Ratifying it here would put a concurrency primitive on the contract with
  a confirmation prompt as its only justification, then hand every store a
  revision field to maintain.
- **Returning `MemoryRecord`s from the façade and letting the CLI classify them.**
  Rejected in §7. Applying `band_of` in the adapter puts ADR-0072 §1's projection
  in `interfaces/`, and hands every future adapter the same four-member union to
  branch over.
- **A `show` command and a `correct` command, completing the roadmap's four
  verbs.** Rejected in §6 and §7. `correct` already exists as `learn` and a second
  route would be a second way to author a memory write from an adapter; `show`
  would render exactly what the listing renders.
- **Deferring the whole surface until the observer produces derived beliefs.**
  Rejected. The band-scoped read is what makes ADR-0072 §5's precedence
  enforceable and ADR-0072 §7 already ruled it owed; and leg 1's exit test is that
  the user can *read and kill* what the system believes, which is worth having
  before the system starts believing things nobody dictated — not after.
