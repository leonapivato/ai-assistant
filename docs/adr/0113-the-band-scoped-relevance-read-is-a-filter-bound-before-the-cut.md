# 113. The band-scoped relevance read is a `bands` filter on `search`, bound before the cut

- Status: Proposed
- Date: 2026-08-06
- **Durability clause.** Every reference below to ADR-NNNN is to its text as it
  stood at this ADR's base, `ba48c25`, not to its status on any later day. Every
  ADR this decision composes with reads `Accepted` there (or partially superseded
  in a scope this ADR does not touch), including
  [ADR-0112](0112-currency-never-ranks-and-retrieval-orders-by-relevance.md), whose
  ratification landed while this lane held and is that base's tip;
  `CONTRIBUTING.md` → "Trivial ADR edits" and
  [ADR-0070](0070-amendment-and-supersession-rules.md) §1 both class a status flip
  as recording a ratification rather than deciding one, so not one clause cited
  here moved with ADR-0112's — its ratifying commit edits its `Status` line and
  appends a dated note, and touches no other word — and none moves with a later
  one. Where a later ADR *changes* one of them, this ADR is read against the text
  quoted here and the later ADR's own record says what moved.

  **The `Date` line above is this ADR's authoring date in this clone's `-0400`
  frame**, the convention ADR-0112's own `Date` line follows and its ratification
  note states. The base named here was committed at `2026-08-06T21:24:57-04:00`,
  which is the next calendar day in UTC, so the two frames straddle midnight for
  every ADR in this leg. The frame is written down because the corpus has already
  paid once for its absence, and because a base SHA is the anchor that does not
  move under either.
- **This is a contract change.** §1 adds one keyword-only parameter — `bands` — to
  `MemoryStore.search` in `core/protocols.py`, and §2 rules where it binds relative
  to the ranking cut. Golden rule 5 therefore applies: this ADR ships as **its own
  docs-only PR**, is reviewed while still `Proposed` — under **both** lenses, which
  `CONTRIBUTING.md` → "Report the review, then mark it ready" requires of "the ADR
  deciding that surface" — and is flipped to `Accepted` on merge (ADR-0015 §5).
  **No code changes with it.** The Protocol change, the conformance extension, all
  three implementations and the assembler that consumes it are later lanes (§7).
- **Adds no `core/types.py` type.** The parameter exchanges `BeliefBand`, which
  [ADR-0072](0072-the-profile-and-the-inferred-model-are-bands-of-one-store.md) §2
  landed. The contract owed is one parameter, its placement, and its read
  semantics, and nothing else.
- **Discharges [ADR-0072](0072-the-profile-and-the-inferred-model-are-bands-of-one-store.md)
  §7's second branch.** §7 ruled a band-scoped read owed, named two shapes, and
  deferred the choice "to the slice that holds the consumer, because the two differ
  in exactly the way a consumer settles: enumeration wants an offset and a stable
  order and no query, while a filter wants relevance".
  [ADR-0073](0073-the-band-scoped-read-is-an-enumeration.md) §1 took the
  enumeration branch for the inspection consumer and deferred the filter *with* its
  consumer; ADR-0073 §10's first entry carries it. This ADR takes the filter
  branch, for the consumer ADR-0072 §5 specifies.
- **Answers #790**, which [ADR-0112](0112-currency-never-ranks-and-retrieval-orders-by-relevance.md)
  §5 filed: ADR-0072 §5's per-band composition is unimplemented *because* neither
  read on the contract serves it, and ADR-0112 §10 declined to pre-authorise the
  surface that would. This is that surface's ADR.
- **Reintroduces no ranking quantity.** §4 holds ADR-0112 §1 exactly as ruled and
  keeps the band on the other side of the line it draws: the band is an
  **eligibility** axis deciding which records are ranked, never an **ordering** one
  contributing to how they compare. A filter selects what is ranked; it does not
  rank.
- **Amends and supersedes nothing.** §11 applies ADR-0070 §1's test clause by
  clause to every ADR this decision touches — ADR-0072 §5 and §7, ADR-0073 §1, §2,
  §9 and §10, ADR-0112 §1, §3, §5, §7, §8 and §10, ADR-0045 §6, ADR-0007 §2 and its
  Consequences — and finds nothing owed. No ADR's `Status` line is edited.
- **Refs** #790 (the problem statement), #663, #457, #411, #789, #729, #733 (the
  band-changing fold §5 turns on), #436, #115.
  ADR-0072 (the bands, §5's precedence, §7's deferred signature), ADR-0073 (the
  other branch, and the conventions this parameter inherits), ADR-0112 (the
  ordering axis and the measurement gate), ADR-0045 §6 (the read-time predicate and
  the post-filter concession this ADR does not widen), ADR-0007 §2 (the expiry
  axis), ADR-0065 §3 (the input-observation discharge), ADR-0060 (the standing
  cancellation clause), ADR-0015 §5 (contract-first).

## Context

[ADR-0112](0112-currency-never-ranks-and-retrieval-orders-by-relevance.md) §5 made
a finding its own lane could not act on, and filed it as #790:

> So the two reads on the contract today are complementary and neither serves
> assembly: `search` ranks by relevance and is band-blind; `list_beliefs` is
> band-scoped and ranks nothing. §5's assembler needs both properties at once […]
> the second half of §7's deferral is simply still open, and it has been invisible
> because §7 reads as discharged once one of its shapes landed.

This ADR closes that half.

### What ADR-0072 §5 obliges, and why it cannot be met today

ADR-0072 §5 rules band precedence *and* rules how it is applied:

> **Precedence is applied by the consumer assembling context, and it is by band,
> not by detected contradiction.** The assembler fills its budget `ASSERTED` first,
> then `ATTESTED`, then `DERIVED`.

and refuses the cheap version by name:

> A band-neutral top-k followed by a post-hoc partition does not implement
> precedence: a flood of low-confidence inferences can displace an assertion
> *below the cut*, where no amount of downstream ordering recovers it. The consumer
> therefore reads per band and composes, rather than reading once and sorting.

The dated position, at the time of writing. `MemoryStore.search` takes `query`,
`limit` and `kinds` and nothing else; `MemoryStore.list_beliefs` takes `bands`,
`kinds`, `limit` and `offset` and no query, and its own docstring pins that it
"carries **no query text** and is not a retrieval — nothing is ranked and no
relevance is computed". `orchestration/loop.py`'s retrieval stage makes one
band-neutral call, `search(query, limit=self._retrieval_limit, kinds=BELIEF_KINDS)`,
and passes the records on unchanged. Nothing partitions by band and no budget is
filled per band. #663 reported this and ADR-0112 §5 diagnosed it.

### Why the shape is decidable now, when ADR-0072 §7 said it was not

ADR-0072 §7 deferred the signature because "the two differ in exactly the way a
consumer settles", and the consumer that settles *this* branch is the assembler.
It does not exist. That looks like the discipline ADR-0028 §7 and ADR-0045 §1
apply — defer surface until a consumer exists — and it is not, for a reason worth
stating rather than assuming.

**The deferral was about the shape, and the shape is now over-determined.** §7 did
not defer *whether* a relevance-ranked band-scoped read is owed; it ruled it owed
and left the choice between two shapes to whichever consumer arrived first. The
inspection consumer arrived, chose enumeration, and ADR-0073 §1 recorded in terms
that the *other* consumer wants the other shape: "That consumer genuinely wants
relevance within a band, which enumeration cannot serve." What the assembler needs
is not a guess — ADR-0072 §5 specifies it completely: relevance within a band, a
budget filled band by band, and the composition owned by the consumer. There is no
open question a live consumer would settle.

**And golden rule 5 puts the contract ahead of the implementation, not beside
it.** ADR-0015 §5 and `CONTRIBUTING.md` → "Contract ADRs land before their
implementation" require the ratified ADR to *merge* before anything builds against
the shape. So the alternative to deciding now is not "decide with the consumer in
hand"; it is the assembler lane discovering mid-flight that it needs
`core/protocols.py` surface — the outcome ADR-0112 §10 refused to pre-authorise
and #790 exists to prevent.

### The mechanism that makes this more than a parameter

Two facts about the tree decide the substantive half of this ADR, and neither is
visible from the contract.

**The band is not a column.** `SqliteMemoryStore`'s `records` table carries
`rowid`, `id`, `kind`, `data`, `expires_at`, `valid_until` and `about_person`. The
provenance source — and therefore the band — lives only inside each record's JSON
blob. `SqliteMemoryStore.list_beliefs` reads it off the decoded record, which it
can afford because that read has no ranking cut to be short of.

**`search` filters after the vector KNN, and a filtered row still costs.**
`SqliteMemoryStore._search_sync` runs the KNN with `k = min(limit *
_RESULT_OVERFETCH, _VEC_KNN_MAX_K)` and applies kind, expiry and both window ends
in a post-KNN pass; the store's own comment records that "a filtered row still
counts against over-fetch". #457 records the consequence and #411 records the
constants that bound it.

Compose the two naively and the band filter is a fourth post-KNN predicate — and
that is not a mitigation shortfall, it is ADR-0072 §5's flood failure reproduced
one layer down. A throwaway spike against the pinned `sqlite-vec` 0.1.9 (discarded
before this PR, per `CONTRIBUTING.md` → "Spike first if you need to") made the
shape concrete: over 200 records of which 4 are `ASSERTED` and 196 `DERIVED`, with
the derived vectors nearer the query, a KNN at `k=8` followed by a post-filter to
`ASSERTED` returns **zero** rows. Asking for the user's own assertions returns
none of them while every one of them is live. That is §5's "displace an assertion
below the cut" verbatim, and per-band composition built on it would restage the
exact failure it exists to prevent.

The same spike establishes the other half: **`sqlite-vec` 0.1.9 restricts a KNN by
`rowid`**, both against a literal id list and against a subquery over `records`,
including one whose predicate is a `json_extract` of the stored blob — and `k`
applies *after* the restriction (asking for `k=10` over 4 eligible rows returned
all 4, not the 10 nearest overall). So a pre-filtered band read is implementable on
the pinned dependency, with or without a schema migration, and this ADR is not
ratifying a seam nothing can meet.

### Four forces make this a decision rather than an implementation detail

1. **A `MemoryStore` parameter is a breaking change** (golden rule 5). All three
   implementations must grow it and their read semantics must be identical, or
   consumers differ by backend.
2. **Where the filter binds is the whole value of the read.** Post-KNN, the
   parameter type-checks, passes a naive suite, and delivers nothing §5 asked for.
   That is not a tuning question and no measurement answers it, which is why it is
   ruled here rather than routed to #789.
3. **ADR-0112 has just closed the ordering axis**, and a band parameter is the
   most plausible way for band to leak back into ranking. §1 and §4 have to say
   what the parameter is and is not, or the next lane reads a filter as a licence
   to weight.
4. **The interaction with #457 needs adjudicating, not inheriting.** A band filter
   changes the over-fetch exposure, and ADR-0112 §7 draws a sharp line between a
   correctness remedy (ungated) and a headroom change (gated on a measurement that
   does not exist). This ADR has to say which side each half of its own decision
   falls on.

## Decision

### 1. The band-scoped relevance read is a `bands` filter on `search`

> **Normative.** `MemoryStore.search` gains one keyword-only parameter, `bands:
> Sequence[BeliefBand] | None = None`, restricting the records it may return to
> the selected bands. No third read method is added, `list_beliefs` grows no query
> text, and no other `MemoryStore` member changes.

The illustrative signature; the semantics in §§2–6 are the contract:

```python
async def search(
    self,
    query: str,
    *,
    limit: int = 10,
    kinds: Sequence[MemoryKind] | None = None,
    bands: Sequence[BeliefBand] | None = None,
) -> list[MemoryRecord]:
```

We settle ADR-0072 §7's remaining branch in favour of the **filter**, exactly as
§7 predicted the second consumer would: "a filter wants relevance". The assembler
issues one call per band it is filling, each with that band's share of the budget,
and composes the results in ADR-0072 §5's order.

**The default preserves every existing caller.** `bands=None` is "every band",
which is what `search` does today, so no call site changes and
`orchestration/loop.py`'s retrieval stage keeps its present meaning until the
assembler lane replaces it. This is source-compatible for *callers* and breaking
for *implementations*, which is the ordinary shape of a Protocol change and the
reason it is still golden rule 5's.

**A third read is refused, and the reason is not economy.** The shape that suggests
itself — one call taking a per-band budget map and returning a composed result — is
refused because it moves the budget and the precedence into the store, and ADR-0072
§5 put them in the consumer on the ground that "the weighting would be invisible at
the seam where it matters and untestable from outside it". A store that fills a
budget band by band is a store applying precedence. It would also need a new
`core/types.py` return type to express the partition, for no information a consumer
cannot get from `band_of`, and it would serve every caller the same compromise —
§5's third reason, restated.

### 2. The band filter binds before the ranking cut

> **Normative.** The band predicate binds **before** the ranking cut. An
> implementation may not let a record outside the selected bands consume the
> candidate budget the cut is taken from, and the records it ranks are the
> selected bands' records — never the selected-band members of a band-neutral top
> `limit`. Where the store cannot bind the band before the cut, the implementing
> lane stops and brings back an ADR rather than shipping the weaker form.

> **Normative.** This binds the **band axis alone and promises no full page.**
> `kind`, `expires_at` and both window ends keep the post-cut placement ADR-0045
> §6 and ADR-0007 ratified for them, so an in-band record failing one of those may
> still consume the candidate budget and a call may return fewer than `limit`
> records while eligible ones exist. That residue is #457's and is neither closed
> nor widened here (§8).

This is the substantive half of this decision and the half a reader would not
derive from ADR-0072 §7.

**The two clauses are separated because the first one, stated as a completeness
promise, would contradict §8.** An earlier draft of this section promised "the
`limit` most relevant records among the records in the selected bands that pass
both read-time axes", which reads as a full page and is not deliverable: with
`limit=10` and eighty nearer *in-band* expired records, a store that pre-filters
the band exactly as required still exhausts its over-fetch budget on the unchanged
post-KNN expiry pass and returns nothing. The adversarial lens caught the two
clauses contradicting each other, and the correction is worth leaving legible
because the distinction is the whole architecture of this decision: **what is ruled
here is where a predicate binds, not how much of a page a caller gets.** Binding
the band is a correctness obligation because the band skew is unbounded and grows
by design; filling the page is #457's exhaustiveness question, which ADR-0112 §8
adjudicates and §8 below routes.

**The ground is that the weak form reproduces the failure the read exists to
prevent.** ADR-0072 §5 refuses a band-neutral top-k partitioned afterwards because
"a flood of low-confidence inferences can displace an assertion *below the cut*".
A band filter applied after the KNN is that refusal's subject wearing a parameter:
the truncation still happens before the band is consulted, and the Context's spike
shows it returning zero assertions out of four live ones once the derived band is
49× the size. The accumulation arc makes that ratio the expected case rather than a
contrived one — leg 3's observer and leg 7's consolidation (ADR-0106) are both
machines for growing the derived band, which is ADR-0112 §5's own closing argument.

**It is a correctness remedy and therefore not gated on #789's measurement.**
ADR-0112 §7 draws the line and names this shape on the ungated side:

> Two shapes the corpus already names qualify on their face, because neither
> iterates: a pre-filter that lets the KNN see only eligible rows, and an explicit
> under-service signal a caller can refuse on.

§7's test is whether the change is "a bet on a frequency". This is not: the claim
is not that pre-filtering makes the shortfall rarer, it is that without it the read
does not implement ADR-0072 §5 at all. No k-shortfall figure would make a read that
returns none of the user's assertions correct, which is exactly ADR-0112 §7's
reasoning about #457's write-path exposure applied to a read.

**It is stated as an observable obligation, not a mechanism.** How a backend
achieves it is its own business, as with every clause of ADR-0073 §2. The Context
records that at least two mechanisms exist on the pinned dependency; naming one
here would ratify a schema decision this ADR has no need to make.

**And it reaches the band axis only.** The kind, expiry and window predicates keep
the placement ADR-0045 §6 and ADR-0007 ratified for them, and this ADR widens
nothing there — §8 states the residue that leaves and routes it.

### 3. Keyed on `BeliefBand`, and the filter conventions are ADR-0073 §1's

> **Normative.** `bands` takes `BeliefBand` values and never `MemorySource` ones.
> `None` selects every band; an **empty sequence selects nothing**, returning an
> empty result. `bands` and `kinds` compose by **conjunction**: a record is
> eligible when its band is selected *and* its kind is.

ADR-0073 §1's argument carries over without amendment and is not re-derived here:
the band is the vocabulary ADR-0072 §2 ratified and the unit the user reads; a
`sources` parameter would push `band_of` into every caller and would let one ask
for half a band — `OBSERVED` without `INFERRED` — which ADR-0072 §4 keeps
indistinguishable to the supersession law. No inverse `sources_of(band)` mapping is
added to `core/types.py`, for ADR-0073 §1's reason: a second, hand-written mapping
is a mapping that can drift from the one whose totality the gate enforces.

**The `None`/empty convention is stated rather than inherited**, for the reason
ADR-0073 §1 gives about `kinds`: leaving it to be read off a sibling method is how
one implementation comes to treat `bands=()` as "no filter" — the opposite outcome,
every record instead of none — on a parameter whose suite never asked. Duplicates
in the sequence are set semantics and change nothing.

**`search`'s other refusals are unchanged.** A blank query and a non-positive
`limit` still match nothing, as `MemoryStoreContract` pins them; `bands` does not
turn `search` into an enumeration, and in particular an empty query with a band
selected is still nothing rather than "the whole band". That contrast with
`list_beliefs` — whose `limit` and `offset` are *refused* out of range rather than
matching nothing (ADR-0073 §2) — is deliberate and stays.

### 4. The band is an eligibility axis, never an ordering one

> **Normative.** The band decides **which records are ranked** (§2) and contributes
> nothing to **how ranked records compare**. It is not a term in any ordering, not
> an addend or factor in any score, not a weight, and not a threshold a record is
> dropped below. Within the result of one call the order is relevance alone, and
> the store never compares a record of one band against a record of another.

> **Normative.** ADR-0112 §1 binds unchanged and is not narrowed here: neither
> currency nor evidence-strength is a term in any ordering, score, weight or cut
> applied to retrieved records. This ADR supplies neither quantity and creates no
> place to put one. `MemoryStore.search` remains band-neutral and
> confidence-neutral in the sense ADR-0072 §5 ruled and ADR-0112 §1 affirmed.

**The eligibility/ordering distinction is load-bearing and an earlier draft
collapsed it.** That draft mirrored ADR-0112 §1's wording onto the band — "not a
term in any order, score, weight or cut" — which reads cleanly for currency,
because no clause anywhere admits a currency *filter*. For the band it collides
head-on with §2: a filter that binds before the ranking cut necessarily decides
what the cut is taken over. The architecture lens caught the two marked clauses
contradicting each other, and under ADR-0089 §3 that could not be repaired by the
prose beside them — in a marked ADR "unmarked text is read to determine what a
marked clause *means*; it never supplies an obligation", so a clause has to carry
its own scope. Splitting eligibility from ordering is what carries it: the band
answers *which records*, relevance answers *in what order*, and neither answer
reaches the other's question.

A filter and a weight are different things, and this section exists because the
parameter is the most plausible route by which they get confused.

**What ADR-0072 §5 rules is what the store's ranking may *mix*.** ADR-0103 §8 put
it in those terms — §5 "is a rule about **what the store's ranking may mix**, not
about which field's name is on the multiplicand" — and ADR-0112 §2 declined to open
the weighting door at the supersession price ADR-0072's Consequences quotes. A
`bands` argument mixes nothing: it restricts the eligible set on the caller's own
instruction, and every record that comes back is ordered against every other by
similarity and by nothing else. Two calls with different `bands` produce two
independently-ordered results; neither carries a cross-band comparison, because the
store never makes one.

**Precedence still lives in the consumer, and this read hands it nothing.** The
store does not know which band the caller will place first, what budget each gets,
or whether a band is being read at all. ADR-0072 §5's three reasons are untouched:
no product of two axes is formed, no derived belief is quietly down-ranked (a
consumer that asks for `DERIVED` gets it ranked on relevance alone), and nothing is
applied invisibly — the filter is the caller's argument and appears in the caller's
code.

**And nothing here reopens ADR-0112.** §1 of that ADR forbids currency from
ordering retrieval "not across bands and not within one", and §3 forbids the
consumer from ordering or cutting by currency within a band. This read supplies no
currency value and creates no place to put one; the assembler built on it orders on
the band and on relevance, which is ADR-0112 §3's own sentence.

### 5. The bands partition **within a call**; composing across calls is not a transaction

> **Normative.** Within one call, every returned record's band is one the caller
> selected: `band_of` is a total function of `provenance.source`, so a record has
> exactly one band at one instant. An implementation may not return a record whose
> band is not selected, and in particular may not pad a short result with the
> next-nearest neighbour of another band in order to fill a page.

> **Normative.** Across calls, no disjointness is promised and none may be assumed.
> A consumer composing band-scoped reads **deduplicates by record id**, and where
> the same id arrives from two bands it keeps the copy from the
> higher-precedence band in ADR-0072 §5's order and counts it once against that
> band's budget. This ADR adds no multi-band snapshot and no cross-call read
> consistency of any kind.

**The per-call half is what makes §1's N-calls-and-compose safe**, and its two
failure modes are silent ones. A consumer that deduplicates *within* a call hides
an implementation returning out-of-band records; an implementation that pads
converts the under-service §8 discusses into a *wrong-band* result the consumer
cannot detect, since the composed prompt would then carry an inference in the slot
precedence reserved for an assertion. A short result is the correct answer to a
band with nothing more to give.

**The cross-call half is a correction, and the mechanism is live on `main` rather
than hypothetical.** An earlier draft claimed no record is eligible for two bands'
results "in one turn" and told consumers they owed no deduplication. The
adversarial lens answered that the claim needs a snapshot spanning the calls, and
the write path supplies the counter-example: `MemoryStore.add` is an upsert keyed
on the caller's id, `REINFORCE` folds onto the target's id (ADR-0045 §5b), and
`memory/ingest.py`'s `_merge` builds the survivor's provenance with
`source=incoming.provenance.source` on every arm but ADR-0103 §6's corroboration
case — so **a fold moves a record between bands at a stable id**, which is the
premise #733 is filed on. A record read in the `ASSERTED` call and folded to
`ATTESTED` before the `ATTESTED` call is returned twice.

**Ruling the tie-break rather than only the deduplication is deliberate.** A
consumer that dropped the second copy in arrival order would resolve the race by
whichever band it happened to read first, which is precedence decided by loop
order — the one thing ADR-0072 §5 is about. Keeping the higher-precedence copy is
the answer §5 already implies, and stating it here stops each consumer inventing
it. It is not a budget policy and does not reach §6: it says which copy survives a
duplicate, not how any budget is divided.

**No snapshot is added, and the refusal has a precedent.** A multi-band consistent
read is a concurrency primitive, and ADR-0073 §5 refused exactly this shape for
exactly this reason: it is ADR-0046 §5's deferred compare-and-swap, which that ADR
left "for want of a consumer that runs two writers on one store". An assembler
reading three times in one turn is not that consumer either. The corpus's
standing posture on the same race is ADR-0073 §2's, which names it and accepts it:
offset paging "may skip or repeat a record", because "a listing that a user re-runs
is not a transaction". A prompt assembled from three reads is not one either — the
difference is only that a duplicate here spends the budget twice on one belief and
presents it in two bands, which ADR-0072 §6 makes a presentation fault. So the race
is accepted and its one harmful consequence is closed by a consumer-side rule
rather than by a primitive with no second writer.

### 6. The budget, the order of the bands, and what fills the prompt stay with the consumer

> **Normative.** This ADR decides no budget, no per-band share, no number of calls
> and no assembly order. ADR-0072 §5's precedence — `ASSERTED`, then `ATTESTED`,
> then `DERIVED` — is affirmed as ruled and as ADR-0112 §4 reaffirmed it, and how
> a consumer divides a budget across bands is that consumer's lane's decision.

The read is the capability; the composition is the consumer's. Stating it keeps
this ADR from being read as having designed the assembler, and it keeps the
assembler's lane from reading a parameter list as a budget policy. In particular
this ADR does not rule that the assembler must issue three calls, or that a band
whose page comes back short donates its remainder to the next band — both are real
questions and both belong to the lane that holds the prompt.

### 7. What the implementing lane owes

This **changes** an existing Protocol rather than adding one, so there is no new
triad — but `CONTRIBUTING.md` is explicit that the mechanical check does not reach
it ("add a method to an existing Protocol and leave its suite alone and the gate
stays green"), so the obligation is stated:

1. **The Protocol** — the `bands` parameter on `MemoryStore.search` in
   `core/protocols.py`, with §§1–5's semantics in its docstring.
2. **The shared conformance suite** — `tests/memory/memory_store_contract.py` gains
   a clause for each obligation, and three of them decide whether the suite tests
   anything:

   - **§2's pre-filter clause needs a skewed fixture, not a balanced one.** A
     fixture with a handful of records per band passes under a post-KNN
     implementation, because nothing floods. The case that bites seeds enough
     nearer records of an unselected band to exhaust any plausible candidate budget
     and then asserts that the selected band's records come back — the shape the
     Context's spike exhibits. A clause that asserts only "every returned record is
     in the selected band" is satisfied by returning nothing, and is the clause a
     suite naturally writes.
   - **`bands=()` must be asserted to return nothing**, distinctly from
     `bands=None`, or an implementation reading an empty filter as "no filter"
     passes.
   - **The conjunction with `kinds` needs a record that passes one filter and fails
     the other**, in each direction; a fixture where the two filters select the
     same records tests neither.

   Alongside those: `score` is **populated** on every returned record, because this
   *is* a retrieval — the opposite of ADR-0073 §2's clearing rule for
   `list_beliefs`, and worth a case precisely because the two reads now differ on
   one field; detachment, as every `MemoryStore` read; and the standing clauses
   bind unchanged — cancellation (ADR-0060) and input observation (ADR-0065 §3),
   the latter discharged by materialising `bands` on the coroutine's **first
   executed line** alongside `kinds`, which is what `SqliteMemoryStore.search`
   already does since #436 and which `MemoryStoreContract` already proves for
   `kinds`.
3. **The canonical fake** — `FakeMemoryStore` in `ai_assistant.testing`, passing the
   extended suite through `tests/memory/test_fake_store.py`.
4. **Both production stores** — `InMemoryMemoryStore` and `SqliteMemoryStore`. The
   SQL one is where §2 bites, and the Context records that the pinned `sqlite-vec`
   admits at least two mechanisms; which one it takes, and whether it wants an
   indexed column and a migration, is the lane's call and needs no further ADR
   **provided the observable obligation is met**.
5. **The assembler** (ADR-0072 §5), which needs no contract change once this lands
   — and which owes a test of its own, because §5's second clause is the one
   obligation here that **no store conformance case can reach**. `MemoryStoreContract`
   drives one store through one call; §5's cross-call rule is a property of the
   composition, so a suite that passes says nothing about it. The case is
   constructible without concurrency and therefore deterministically: a store double
   that returns id `x` in the `ASSERTED` call and, before the `ATTESTED` call,
   applies the id-preserving band change `_merge` performs, then asserting that the
   composed result retains `x` **once**, that the copy retained is the
   higher-precedence band's, and that it is charged once to that band's budget.
   Without it an assembler that concatenates, or that keeps whichever copy arrived
   first, is wrong in a way every mechanical check on this list passes.

Whether that is one lane or two is the dispatcher's call; the contract half must not
land without its suite, and the assembler must not land without §2 being real
underneath it or without the cross-call case above.

### 8. The residue this leaves, named and routed

> **Normative.** This ADR makes no headroom change and authorises none: it does not
> raise `_RESULT_OVERFETCH`, lift or decouple the KNN `k` cap, deepen a candidate
> scan to buy a larger multiple of `limit`, or adopt hybrid retrieval. ADR-0112 §7's
> gate on those is untouched and #789's measurement remains their warrant.

> **Normative.** This ADR neither adds nor pre-authorises an under-service signal on
> the `MemoryStore` contract, and does not close #457. A lane wanting one owes its
> own ratified ADR under golden rule 5, as ADR-0112 §10 rules.

**What §2 fixes and what it leaves.** Pre-filtering the band removes the skew whose
growth is a design consequence of the accumulation arc. It does not remove the
post-KNN placement of `kind`, `expires_at` and the two window ends, so a band-scoped
call can still come back short because *eligible-band* rows that fail those
predicates consumed the budget. That is #457's mechanism exactly, unchanged in kind
and now scoped to one band at a time.

**Where that residue lands is asymmetric, and the asymmetry is the point.** The
`ASSERTED` and `ATTESTED` bands are small by construction — the user typed the
first and a connected source reported the second — so a call pre-filtered to either
sees a candidate set that is mostly, often entirely, the answer. The `DERIVED` band
is the one that holds the volume, and it is the band whose calls will still run
short, chiefly because `orchestration/loop.py` filters to `BELIEF_KINDS` while
episodic records share the derived band. So the residue falls on the *lowest*-
precedence band — the one ADR-0072 §5's ordering is content to have less of — and
not on the assertions §5 exists to protect. That is why §2 is worth ratifying
without waiting for #457's fix, and it is not a claim that #457 is thereby smaller.

**Two calls, two candidate budgets.** #790 observes that "N band-scoped searches
multiply the post-KNN over-fetch exposure by N". Under §2 that is the wrong shape:
each call's budget is spent inside its own band, so N calls buy N *independent*
budgets rather than N draws on one contested one. What N multiplies is the work —
N embeddings of the same query text unless the implementation reuses one, and N
KNNs — which is a latency question and therefore #789's, not a correctness one.
This ADR sets no expectation about it and prescribes no caching.

### 9. Explicitly declined

- **A third `MemoryStore` read taking a per-band budget.** §1. It moves precedence
  and the budget into the store, against ADR-0072 §5.
- **A `sources` filter keyed on `MemorySource`.** §3, on ADR-0073 §1's argument.
- **Query text on `list_beliefs`.** §1. It would collapse two questions into one
  method and break the stable total order and paging ADR-0073 §2 ratified — a
  similarity score is not a paging key, which is ADR-0073 §1's own reason.
- **Band weighting, band-conditional scoring, or a band term in the order.** §4,
  ADR-0072 §5, ADR-0112 §1 and §2. The door remains the supersession ADR-0072's
  Consequences names.
- **A post-KNN band filter.** §2. It type-checks, passes a naive suite, and
  delivers none of ADR-0072 §5.
- **Padding a short band-scoped result from another band.** §5.
- **A multi-band consistent-snapshot read**, so that N calls in one turn see one
  state. §5. It is ADR-0046 §5's deferred compare-and-swap wearing a third hat,
  and an assembler is not the second concurrent writer that would justify it;
  the race is accepted as ADR-0073 §2 accepts its own, and its harmful consequence
  is closed by §5's consumer-side rule.
- **Any headroom change, and the under-service signal.** §8.
- **An `include_retired` axis, or any relaxation of the two read-time axes.**
  `search`'s axes are ADR-0007 §2's and ADR-0045 §6's and this ADR does not touch
  them; ADR-0073 §3 refused the retired axis on the sibling read for reasons that
  apply here with more force, since this one feeds a prompt.

### 10. What this ADR does not decide

- **The assembler's budget policy** — the per-band share, the number of calls, and
  whether an under-filled band donates its remainder (§6). The prompt-assembly
  lane's, and ADR-0072 §6 already owns what it must convey.
- **#457's fix and #411's three parts**, adjudicated by ADR-0112 §8 and untouched
  here (§8).
- **Leg 7's exit measurement** (#789, ADR-0112 §7), including whether N band-scoped
  calls cost enough latency to matter.
- **Currency's role anywhere** — ADR-0112 owns it, and §4 consumes its answer.
- **Cross-conversation episodic recall's budget question** (#791, ADR-0112 §9). It
  is a *budget* question, and this ADR supplies a read rather than a budget.
- **Whether `SqliteMemoryStore` grows an indexed band or source column** (§7). An
  implementation choice under an observable obligation, not a contract question.
- **Anything about eviction, size caps or retention** — ADR-0007 §5's deferral
  stands, as ADR-0103 §1 and ADR-0112 §9 each record.

### 11. What this records against earlier ADRs: nothing

The judgement ADR-0082 §1 requires, clause by clause, by applying ADR-0070 §1's
test: would a reader holding only that ADR now act differently, or read one of its
clauses more widely than it now holds?

**ADR-0072 §5 and §7 — nothing owed.** §7 ruled the obligation and deferred the
signature between two named shapes; this ADR takes the shape §7 named, for the
consumer §7 said would settle it. That is a deferral used as written, which
ADR-0110 §13 distinguishes from supersession by reference to ADR-0045's 2026-08-02
note. §5 is affirmed rather than touched: the store still mixes nothing into its
rank (§4), precedence still lives in the consumer (§6), and §5's refusal of a
partitioned band-neutral top-k is the ground §2 rests on rather than something §2
qualifies. §2 constrains an implementation in a respect §5 left to §7 — where the
filter binds — which is a stacked addition and makes no sentence of §5 false.
**Deferral discharged; no record owed.**

**ADR-0073 §1, §2, §9 and §10 — nothing owed.** §1's "The other shape loses now and
is not refused" is the sentence this ADR acts on, and §9's declined list records
the filter as "deferred with its consumer, not refused". §10's first entry — "The
`bands` filter on `search` that ADR-0072 §5's band precedence needs" — names this
decision and stops describing a wholly open question, which is what a discharge
does. §1's promise that "the two reads are additive, and neither forecloses the
other" is honoured exactly: `list_beliefs` is untouched, keeps its enumeration
semantics, and §3 above adopts its conventions rather than diverging from them. §2's
clearing of `score` is contrasted in §7 and not changed, and §2's named-and-accepted
paging race is the posture §5 above adopts for the analogous cross-call one rather
than a clause §5 narrows. §5's refusal of a concurrency primitive for want of a
second writer is applied, not extended. **Partial discharge; no
record owed.**

**ADR-0112 §1, §3, §5, §7, §8 and §10 — nothing owed.** §5's two normative clauses
say the per-band composition "remains owed and unbuilt" and that "the read such a
lane needs does not exist on the `MemoryStore` contract, and this ADR authorises
none. Adding one is a `core/protocols.py` decision under golden rule 5 and owes its
own ratified ADR before any implementation." This ADR *is* that ADR, arriving by the
route §5 and §10 both prescribe; neither clause is narrowed and a reader holding
only ADR-0112 owes exactly the ADR this one is. §1 and §3 are consumed unchanged
(§4). §7's headroom gate is left standing and §2 lands on the side §7's own third
clause names as ungated, using §7's stated test rather than an exception to it.
§8's adjudication of #457 and #411 is untouched, and §8 above adds a scoping
observation about where the residue falls without disturbing any of it. §10's list
of surfaces that owe their own ADR is honoured by this ADR existing.

ADR-0112's ratification note records that "the four issues the header records as
filed are open on GitHub: #789, #790, #791, #792", and this ADR answers #790, which
closes on its merge. That does not make the note false and owes it nothing: the
note is dated and records the state at the instant it was written, which is the
form ADR-0070 §1 requires of an appended note and the reason ADR-0019's no-state-
claims rule exempts `docs/adr/`. **Deferral discharged; no record owed.**

**ADR-0045 §6 and ADR-0007 §2 and its Consequences — nothing owed.** §6's ratified
concession that `valid_from` may be filtered "in the post-filter step, not the SQL
pre-filter" is a permission about *that* predicate and is neither revoked nor
extended: §2 above binds the band and says so explicitly. ADR-0007's post-filter
caveat is cited as the residue it describes and is read no more widely than it
holds — it is if anything understated, which is #792's subject and not this ADR's.
**No record owed.**

**ADR-0045 §5b, ADR-0103 §6 and ADR-0046 §5 — nothing owed.** §5 above cites the
fold's id-preserving, source-taking shape as the *fact* that makes a cross-call
duplicate reachable, and rules nothing about the fold: whether a `REINFORCE` should
move a record between bands at all is #733's question and not this ADR's, and this
decision is correct either way — a read cannot rely on the write path never doing
it. ADR-0046 §5's deferral is cited as the reason a snapshot is not added and is
left exactly where ADR-0073 §5 left it. **No record owed.**

**ADR-0103 §8, ADR-0110 §8, ADR-0074 §6, ADR-0028 §7, ADR-0021 §4, ADR-0060,
ADR-0065 §3, ADR-0106 — nothing owed.** Each is cited as a reason, a mechanism or a
standing clause and read no more widely than it holds; none acquires an exception
and none loses one. ADR-0074 §6's `kinds` filter is composed with rather than
changed (§3).

## Consequences

- **ADR-0072 §7 is fully closed, three ADRs after it was written.** Both of its
  shapes now exist on the contract, each ratified by the consumer §7 said would
  settle it, and neither forecloses the other — which is the outcome §7's deferral
  was betting on.
- **ADR-0072 §5's per-band composition becomes buildable**, and #790 stops being an
  open finding that every retrieval lane rediscovers. What it does not become is
  built: the assembler is a later lane and the precedence is unimplemented until it
  lands.
- **The read is harder to implement than the parameter suggests, deliberately.** §2
  is the clause an implementation can pass in name and fail in substance, so the
  suite clause §7 specifies is where this decision is actually enforced. A lane that
  ships the parameter without the skewed-fixture case has shipped nothing.
- **`search` acquires a second axis and no second quantity.** Two ADRs now affirm
  its band- and confidence-neutrality against the pressures most likely to erode it
  — ADR-0112 against currency, this one against reading a filter as a weight.
- **The `DERIVED` band keeps #457's shortfall and the other two largely shed it**
  (§8). That is an accepted, named asymmetry rather than a fix, and it is the reason
  §2 is worth having before #457 is answered.
- **The assembler inherits one obligation it would not have guessed** (§5): it
  deduplicates across its band-scoped calls by record id and keeps the
  higher-precedence copy, because a fold can move a record between bands at a
  stable id between two reads of one turn. That constrains a lane not yet written,
  which is the point — it is far cheaper to state now than to diagnose later as a
  belief that appeared twice in a prompt under two different bands.
- **A latency cost is introduced and not measured.** N band-scoped calls per turn
  replace one, and this ADR sets no expectation about what that costs, because #789
  is the instrument and it does not exist yet (ADR-0112 §7). The trade is deliberate:
  a correctness obligation that does not wait, and a performance claim that is not
  made.
- **Revisit if** #789's measurement shows the per-band call pattern dominating
  retrieval latency at ordinary volumes; if #457's remedy lands and makes §8's
  residue asymmetry no longer the reason to accept the `DERIVED` band's shortfall;
  if a consumer needs relevance *within* a band by something other than similarity,
  which would be a new ordering question and ADR-0112 §1's to answer first; or if a
  third consumer wants a band-scoped read that is neither this filter nor
  `list_beliefs`, at which point the two-shape settlement ADR-0072 §7 set up has
  found its limit.

## Alternatives considered

- **A post-KNN band filter — the parameter without §2.** Rejected in §2. It is the
  cheapest thing that type-checks and it returns none of the user's assertions once
  the derived band is an order of magnitude larger, which the Context's spike
  exhibits at 49×. It would ratify a read that restages ADR-0072 §5's flood failure
  inside the mechanism built to prevent it.
- **A third read taking a per-band budget map and returning a composed result.**
  Rejected in §1. It puts the budget and the precedence in the store, against
  ADR-0072 §5's placement of both in the consumer and its third reason; it needs a
  `core/types.py` type to express a partition `band_of` already yields; and it
  serves every caller one compromise.
- **A `sources` filter keyed on `MemorySource`.** Rejected in §3 on ADR-0073 §1's
  argument, which is unchanged: it pushes `band_of` into every caller and lets one
  ask for half a band the supersession law treats as whole.
- **Adding query text to `list_beliefs` instead.** Rejected in §1 and §9. ADR-0073
  §1 chose enumeration precisely because a similarity score is not a paging key and
  the inspection consumer has no query; grafting relevance on would either break the
  stable total order §2 of that ADR ratified or produce a method whose guarantees
  depend on which argument was passed.
- **Composing above the seam from what exists — a large band-neutral `search`
  partitioned by the consumer.** Rejected: ADR-0072 §5 refuses it by name, ADR-0112
  §5 restates the refusal, and the "large" is a headroom change ADR-0112 §7 gates on
  a measurement that does not exist.
- **Composing from `list_beliefs` per band and re-ranking in the consumer.**
  Rejected. It puts a relevance computation — and therefore an embedder — above the
  store seam, duplicating the ranking the store owns, and it would either enumerate
  the whole band into memory or page it, at which point the consumer has
  re-implemented `search` with worse guarantees. It is the same shape ADR-0072 §7
  refused when it refused filtering `export()` in an adapter, one layer up.
- **Ruling the kind, expiry and window predicates before the cut too.** Rejected as
  outside this lane's fence. Their post-KNN placement is ADR-0045 §6's and
  ADR-0007's ratified concession, the exposure it leaves is #457's subject, and
  ADR-0112 §8 has just adjudicated that issue; changing it is that issue's ADR and
  not a rider on this one. §8 states the residue rather than annexing it.
- **Adding the under-service signal here, since §2 is about being served.**
  Rejected in §8. It is a different obligation with a different first consumer —
  `MemoryIngestor`'s conflict detection on the *write* path, per ADR-0112 §8 — and
  ADR-0112 §10 declines to pre-authorise it by name. Bundling it would put two
  contract decisions behind one ratification and give the second one no lane of its
  own.
- **Deferring the whole shape until the assembler lane holds a consumer.** Rejected
  in the Context. Golden rule 5 requires the contract to merge *before* the
  implementation, so the deferral's real effect is not a better-informed decision
  but an assembler lane that stops mid-flight — which is what #790 exists to
  prevent. ADR-0072 §7's deferral was between two shapes, and ADR-0072 §5 specifies
  this consumer's needs completely, so there is no open question a live consumer
  would settle.
- **Deferring until #789's measurement exists.** Rejected. §2 is a correctness
  obligation and ADR-0112 §7's third clause explicitly does not reach one; gating it
  on a frequency would be the category error §7 names, since no k-shortfall figure
  makes a read that hides the user's own assertions acceptable. What genuinely waits
  for the measurement is the headroom question, and §8 leaves it waiting.
