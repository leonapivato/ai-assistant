# 129. Store health is a census at an instant, and closure concentration is a neighbourhood figure the retrieval path can no longer see

- Status: Proposed
- Date: 2026-08-10
- **Durability clause.** Every reference below to ADR-NNNN is to its text as it
  stood at this ADR's base, `4204438`, not to its status on any later day. Every
  ADR this decision composes with reads `Accepted` there (or partially superseded
  in a scope this ADR does not touch), and no ADR stands `Proposed` on that tree
  but this one. Where a later ADR *changes* one of them, this ADR is read against
  the text quoted here and the later ADR's own record says what moved. The `Date`
  line above is this ADR's authoring date in this clone's `-0400` frame, the
  convention [ADR-0112](0112-currency-never-ranks-and-retrieval-orders-by-relevance.md)
  and [ADR-0113](0113-the-band-scoped-relevance-read-is-a-filter-bound-before-the-cut.md)
  both state for their own; the base named here is the anchor that does not move
  under either frame.
- **This decision adds no contract surface, and §5 argues it rather than
  asserting it.** No Protocol in `core/protocols.py` gains a member or changes a
  signature; no type, enum member, constrained string or constant is added to
  `core/types.py`; no `Settings` field appears; no `AssistantEngine` method, wire
  operation or `assistant` CLI command is created. Golden rule 5 and ADR-0015 §5
  therefore do not bind this ADR. §5 also records the one place where a plausible
  design *would* have taken `core` surface, and why that design is declined rather
  than deferred.
- **It still ships as its own `Proposed` PR and carries both review lenses.** The
  reader §5 decides is a follow-on lane, and review while the decision is still
  `Proposed` is what lets a finding change it rather than supersede it
  (`CONTRIBUTING.md` → "Contract ADRs land before their implementation"). The
  architecture lens is run for the reason
  [ADR-0120](0120-a-measure-is-a-rate-over-the-trace-stream-read-offline-while-the-hub-is-stopped.md)
  ran it and in its own words: "the decision that actually needs adjudicating here
  is a *placement* — which package may hold the walk, and by what route an operator
  reaches it — not because the diff touches the contract floor, which it does not".
  That is exactly this ADR's §5, and this ADR reaches the *opposite* placement from
  the sibling tool on a difference of instrument, so the lens that adjudicated the
  first should read the second. ADR-0112's ratification note records the
  single-lens precedent for an ADR that decides no `core` surface — "this ADR
  touches no Protocol and no `core` type and, under §10, decides none, so it is not
  'the ADR deciding that surface'" — and that precedent is followed as far as it
  goes: it makes architecture *optional* here, not forbidden, and `scripts/ship.sh`
  fires its own architecture requirement only on a diff touching
  `core/protocols.py` or `core/types.py`, which this diff does not.
- **This ADR amends nothing and supersedes nothing.** §11 applies ADR-0082 §1's
  test to each place a record looks owed and records why none is.
- **It discharges ADR-0128 §3's third clause** — the direction that hands the
  retired watch's question to "a **direct store-health measure**, read offline over
  the store rather than over the trace stream, in the pattern ADR-0120 §9 sets",
  ratifying nothing beyond that direction because "its figures, its population and
  its surface are its own lane's". This is that lane, and §11 shows the clause is
  discharged by the route it names rather than superseded.
- **It does not re-ratify ADR-0128 §5 item 7.** The removal of `Shortfall` and
  `MeasureReport.shortfall` from `evaluation/_figures.py` and the report is already
  ratified there and rides ADR-0128's implementation lane. This ADR composes with
  that removal and touches no file under `src/ai_assistant/evaluation/`; §9 says so
  as a scope statement rather than as a rule about someone else's lane.
- **Refs** #922 (the batch), #824 (the incidence question and its re-ruling), #799
  (the instrument that answered the lab half), #457 (the defect), #838 (the layered
  design, whose upper layers stay parked), #829 (the measurement window), #926 (the
  stale comment, which belongs to the implementation lane and not here).
  ADR-0128 §3/§5/§6 (the clause this discharges and the scope it left open),
  ADR-0120 §1/§7/§9/§10/§14 (the offline pattern, the retired watch and the
  no-threshold disposition), ADR-0119 §2/§7 (the content rule and the read-back
  prohibition), ADR-0114 (the walk and its cursor), ADR-0104 §5 (the offline-tool
  placement this reuses), ADR-0083 §8/§10 and ADR-0084 §6 (the entry-point rules),
  ADR-0045 §6 (read-time liveness), ADR-0007 §2/§5 (retention and the eviction
  deferral), ADR-0072 §1/§4 (one store, and the band's single classifier),
  ADR-0100 §6 (the subject axis is not a topic axis), ADR-0004 §1 (the tier),
  ADR-0015 §5 (contract-first), ADR-0088 (citation form), ADR-0089 (normative
  marking).

## Context

### ADR-0128 removed the failure and its evidence in one change, and said so

ADR-0128 §1 binds every read-time eligibility predicate before `MemoryStore.search`'s
ranking cut. Its §3 retires ADR-0120 §7's #824 shortfall watch as a consequence and
states the trade in as many words:

> an eligibility pre-filter removes the *evidence* of concentrated closure along
> with its consequence, because the rows that would have been counted are never
> fetched. That is the trade — the failure stops happening and stops being
> observable in the same change — and it is why the third clause routes the
> question to a measure that reads the store rather than the stream. A store-health
> measure can see closure directly, which the trace never could; what it cannot do
> is see it *through retrieval*, and after §1 there is nothing to see there.

So the question this lane inherits is not the one #824 asked. #824 asked whether a
real store develops concentrated closure *approaching the measured threshold*, and
armed a mitigation on the answer. The mitigation has landed and the threshold is
gone: #799 established the shortfall as "0% until filtered-neighbour density crosses
`fetch_k − limit`, then 100%", and after ADR-0128 §1 `fetch_k` is `min(limit,
_VEC_KNN_MAX_K)` and no ineligible row can consume a candidate slot at all. A figure
reporting density against `fetch_k − limit` today would be reporting a quantity with
no consequence attached to it.

**What survives is the half of #799 that was never about retrieval.** Its finding was
that "the store-wide window-closed proportion is the wrong tuning statistic … an even
50% closure under-returns nothing; the same 50% concentrated in one topic serves 0 of
10 at 20k records while untouched topics serve 10/10. Concentration, not proportion."
The second sentence is a statement about *retrieval* and is now spent. The first is a
statement about *the store*, and it is still true and still unmeasured: nobody knows
what a real store's closure looks like, evenly or unevenly, because the only
instrument ever built for it read the trace stream and the trace stream can no longer
see it.

### What the store carries, checked rather than assumed

Every definition below is only as good as its agreement with what a stored record
actually holds, so this is the inventory it was checked against at `origin/main`.

- **`MemoryRecord`** is the four-kind union over `MemoryBase`, which carries `id`,
  `content`, `provenance`, `score`, `expires_at`, `validity` and `about_person`.
  `Validity` carries `valid_from` and `valid_until` and the `live_at` predicate that
  ADR-0045 §2 puts in `core` so "every `MemoryStore` read path enforces *both* ends
  identically instead of each re-deriving it".
- **`Provenance`** carries `source`, `confidence`, `evidence`, `evidence_elided`,
  `last_updated`, `last_confirmed_at`, an attestation and `derived_from_external`.
  **No field on `MemoryRecord` or on `Provenance` links a retired record to the
  record that replaced it.** ADR-0045 §4 mints a correction at a fresh id and
  window-closes the target; `evidence` holds supporting references, not a successor
  pointer, and `evidence_elided` counts citation displacements. So a per-belief
  correction *count* is not computable from the store, and §3 does not invent one.
- **`band_of`** in `core/types.py` maps a `MemorySource` to a `BeliefBand`, and
  ADR-0072 §4 keeps `source` the single classifier — so a band decomposition is a
  pure function of a field every record carries, and the census and the store cannot
  disagree about it.
- **`MemoryStore` carries the walk, and the walk cannot see this census's
  population** (ADR-0114). `walk_records` returns a chunk in insertion order against
  a **named** cursor, `advance_walk` persists that cursor — and its contract is
  explicit that "**Only records retained *and* live at the instant it reads are
  yielded** … An expired record is never yielded and neither is one whose window is
  closed or not yet open", because "the walk sides with `get`/`search` rather than
  with `export`". So a store holding nothing but retired records produces an empty
  walk. `export` does return the window-closed records — "a superseded belief is data
  the store holds" — and excludes the expired ones, since "retention still wins over
  history"; it returns the whole store in one list. **So no member returns every
  record the store physically holds.** None of them returns an embedding, and
  `MemoryRecord` has no field for one.
- **The vectors are in the store and nowhere else.** `SqliteMemoryStore` creates
  `vec_records` as a `vec0` virtual table joined to `records` by `rowid` with no
  foreign key, and `search` reads `SELECT r.data, v.distance FROM vec_records v …`.
  The embeddings are already computed and already durable; reading them requires no
  model.
- **The eligibility columns are now columns.** ADR-0128's implementation put both
  window ends, the retention deadline, the kind and the subject on `records` so the
  pre-filter can bind them before the KNN's cut.

### The only topical structure a real store has is its geometry

#799's fixture manufactures topics — `AgedStoreSpec` takes a `closed_concentration`
— because a lab needs a ground truth. A real store has no such label. `kind` is a
type, not a topic. `about_person` is a *subject*, and ADR-0100 §6 rules it "whom, not
what": "a belief about a company, a project, a device or a topic states no subject",
and the label "resolves to nothing … nothing normalises, case-folds, aliases or
de-duplicates it". A decomposition by subject would therefore not be a decomposition
by topic even where it were permitted, and §7 refuses it on a second ground anyway.

That leaves the embedding geometry, which is the structure retrieval itself uses and
the structure in which "topic" has an operational meaning at all. **Concentration is
a neighbourhood figure over the stored vectors, or it is not a statement about topics.**
§2 takes the first branch, and §5's placement is what that branch costs.

### `search` is the one instrument that cannot be used, and its parent ADR is why

The natural design is to ask the store: run some queries, see how much retired
material comes back near the live beliefs. It is unavailable, and not for a reason of
taste. After ADR-0128 §1 a record failing the validity window is never a candidate,
so `search` **cannot return a retired row** — the pre-filter that removed the cliff
also made the read path blind to exactly the population this figure counts. A reader
built on `search` would report a neighbourhood closure density of zero on every store
in every state, which is the "figure that is zero by construction" ADR-0128's own
Context calls "worse than no figure". It would additionally need an `Embedder` to
turn a query into a vector, and so would drag an inference dependency and ADR-0104
§4's cloud-refusal question into a tool that needs neither.

So the measure reads the store's *storage*, not the store's read API. That is the
single fact from which §5's placement follows, and it is inherited rather than chosen.

### What makes this a decision rather than a query somebody writes

1. **The obvious figure is the one #799 already ruled useless.** Store-wide closed
   proportion is a line of SQL and it is the statistic #799 named as the wrong one.
   A lane that shipped it would have discharged ADR-0128 §3's clause in form and
   answered nothing. §3 keeps the proportion, for a different and stated job, and
   makes concentration a separate figure with its own definition.
2. **The figure that answers the question dictates the package.** Concentration
   needs the vectors; the vectors are `memory`'s schema; `lint-imports`' "evaluation
   depends on core and nothing else" forbids `evaluation → memory`. A lane that
   started from "beside `MeasureReader`" would have been forced, by the package
   boundary rather than by the question, into the figures a `MemoryStore` Protocol
   consumer can compute — which are exactly the ones that do not answer #824. §5 is
   the adjudication, and it goes the other way.
3. **A census is not a measure, and the corpus has a rule against mixing them.**
   ADR-0120 §1 defines a measure as a rate over a window of the trace stream, and
   ADR-0119 §8 refused to derive corrections "from what the store now holds, which is
   a measure of the present rather than a record of an event". This ADR's figures are
   deliberately that refused shape, because the question is about accumulated state.
   Saying so, and forbidding the substitution in both directions, is the difference
   between a second instrument and a contradiction of the first.
4. **A diagnostic that fires something is a mitigation nobody ratified.** The #824
   re-ruling's own disposition is that the watch's value was as an operator's
   evidence, and its grounds for dissolving the trigger were that the watch "bought
   nothing but the chance to never pay a cost that is mostly owed anyway". A figure
   that armed a mechanism would rebuild the instrument that ruling took apart. §6
   forbids it in a clause rather than leaving it to good sense.

## Decision

### 1. Store health is a census of the store's state at one instant, and it is not a measure

> **Normative.** Every figure this ADR defines is a count, a proportion of counts,
> or a distribution of per-record quantities, taken over the memory store's records
> as they stand at one stated instant `T`. No figure defined here is a rate over a
> window of events, and none is a measure of ADR-0120.

> **Normative.** No figure defined here may be substituted for a measure of
> ADR-0120, and no measure of ADR-0120 may be substituted for one of these. The
> report states its own figures and no measure; ADR-0120's report states its own
> measures and none of these.

> **Normative.** Every proportion and every distribution this ADR defines is
> **undefined** when the population it is taken over is empty, and the report states
> that it is undefined rather than stating a figure or a zero.

> **Normative.** `T` is an input to the run, not a fact the mechanism discovers
> about itself: it is either given by the operator or defaulted to the tool's own
> start instant, and it is fixed for the whole run so every figure in one report is
> taken at the same instant. The report states `T`, and states every parameter §3
> makes a parameter, on its own output. A figure reported without them is not one
> of these figures.

**The category matters because the two reports will be read side by side.** ADR-0120
§1's measures answer "did the user model get more accurate over this window" from a
stream of events, and its §8 goes to some trouble over settling periods because "a
measure taken at the trailing edge of a window is biased and the bias is invisible".
None of that applies here: a census looks at no future, so it needs no settling, and
it has no denominator drawn from a lossy stream, so ADR-0119 §5's denominator rule
has nothing to bind. What it has instead is a hazard ADR-0120 does not have — the
present state of a store is the accumulated residue of every event since it was
created, including events before any retained trace — and that is why a census can
answer a question about accumulation that no window over the stream can.

**`T` being an input is not the as-of retrieval axis ADR-0045 §1 deferred and
ADR-0128 §1's second clause refuses.** Those are about `MemoryStore.search` gaining a
parameter that moves the instant its read-time predicates are evaluated against, and
this ADR adds no parameter to any contract (§5) and does not go through `search` at
all (§2). The census evaluates `Validity.live_at` itself, over the records it read, at
an instant it states — which is what any reader of the whole store has to do to say
anything about liveness, since ADR-0045 §6's read semantics are that `get` and
`search` hide a record on either end of the window while `export` keeps it. A
diagnostic choosing which instant to describe is not a read path acquiring an axis.

**The undefined clause is ADR-0120 §1's second clause restated for this family, and
it is restated rather than cited because ADR-0120 §1 binds "every measure defined by
this ADR" and these are not.** §11 records that this creates no obligation on
ADR-0120 and takes nothing from it. The reasoning is the one §1 gives there and it
transfers whole: a zero asserts a proportion that was measured to be zero, an omitted
line asserts nothing and is read as zero anyway, and an empty population is reachable
in normal operation — a store with no retired record, a store mid-re-embed with no
vector, a store with nothing in it at all.

### 2. Closure concentration is the neighbourhood figure, and the store carries no other topic axis

> **Normative.** The concentration figure is defined over the store's **stored**
> embedding vectors. It embeds nothing, constructs no `Embedder`, consults no model
> and performs no inference; every vector it reads was written by an earlier ingest
> or re-embed.

> **Normative.** The concentration figure is not defined over, and may not be
> computed through, `MemoryStore.search`. After ADR-0128 §1 no record failing the
> validity window is a candidate, so `search` cannot observe the population this
> figure counts.

> **Normative.** No figure defined here is decomposed by `about_person`, and the
> report states no subject label. ADR-0100 §6 rules the field a subject and not a
> topic, and ADR-0101 owns whether labels may be matched at all.

**This is the clause that decides the shape of everything after it.** The question
handed down is topical concentration; the store's only topical structure is the
geometry retrieval ranks in; that geometry is a set of vectors sitting in
`vec_records`. Reading them is cheap in the sense that matters — no model is loaded,
nothing is uploaded, and ADR-0104 §4's cloud refusal has no question to answer,
because that refusal is about *sending the store to an embedder* and this tool sends
nothing anywhere.

**The second clause is where this ADR's parent constrains it most sharply.** ADR-0128
§1 is a correctness fix and this is its cost, stated once: the read path is now
structurally unable to see retired neighbours, so the instrument that measures them
must go under it. A reviewer who reads the second clause as excessive should check
what a `search`-based reader would report on a store that is 90% retired and
concentrated: zero, on every query, forever.

**The third clause refuses a decomposition that would look free.** Grouping closure
by `about_person` needs one `GROUP BY` and would produce a table that reads like a
topical breakdown. It is not one — ADR-0100 §6 is explicit that a belief about a
topic states no subject, so the beliefs a topic-concentrated closure is made of are
mostly `None` on that axis — and printing the labels would put user-supplied strings
about third parties into a report §7 otherwise keeps free of them. Both objections
stand alone; either is sufficient.

### 3. Four figures, and each one says what it is for

> **Normative.** A record is **live at `T`** exactly when `Validity.live_at(T)`
> holds for its `validity`; **retired at `T`** when `valid_until` is set and at or
> before `T`; **not yet live at `T`** when `valid_from` is set and after `T`; and
> **expired at `T`** when `expires_at` is set and at or before `T`. Liveness and
> expiry are separate axes and a record may be both.

> **Normative.** The **census population** is every record **physically present** in
> the memory store at the read, whatever its liveness or retention state: a retired,
> a not-yet-live and an unpurged expired record are each in it. No `MemoryStore`
> member returns this population, and none is required to — `export` excludes
> expired records and `walk_records` yields only the retained and live. The report
> states the population's size.

> **Normative.** The report states the **closure census**: over the census
> population, the total and the counts live, retired, not-yet-live and expired at
> `T`, each as a count and as a proportion of the total, store-wide and decomposed
> by `kind`.

> **Normative.** The report states the **neighbourhood closure density
> distribution**: over a sample of records live at `T` for which the store holds a
> vector, each record's density is the count of its `k` nearest neighbours — by the
> store's own distance metric, among every record for which the store holds a
> vector, excluding the record itself, live or not — that are **not** live at `T`,
> divided by `k`. The report states the distribution of that density over the
> sample, the sample size, `k`, and, beside it, the store-wide proportion of
> vector-bearing records that are not live at `T`.

> **Normative.** The sample and `k` are parameters of the run, stated on the report.
> `k` is a **positive integer** and is the same for every sampled record in a run.
> The sample is a deterministic function of the store's contents and the stated
> parameters, and does not depend on `T`. Two runs over an unchanged store, with
> the same parameters and the same `T`, produce identical figures.

> **Normative.** The density figure is **undefined** where the store holds fewer
> than `k + 1` records with a vector, and the report states that it is undefined
> and names both counts. Where the store holds at least `k + 1` such records, every
> sampled record has `k` neighbours available: no sampled record is dropped for
> want of a full neighbourhood, and no density is taken over fewer than `k`.

> **Normative.** The report states the **closure-age distribution**: over every
> record retired at `T`, the interval from its `valid_until` to `T`.

> **Normative.** The report states the **band fill**: over the census population, the
> count live and the count not live at `T` for each `BeliefBand`, taken as
> `band_of` of the record's `provenance.source`.

> **Normative.** The report states how many records of the census population the
> store holds no vector for, separately from every other count.

**Physical presence is the population, and it is neither of the two the contract
offers.** `export` is a data-rights snapshot and drops the expired rows on purpose —
"Only *expired* records (past `expires_at`) are excluded: retention still wins over
history, so a record the system promised to forget cannot resurface here" — which is
right for an export and wrong for a census, because an unpurged expired row is still a
row in the scan, in the backup and in a re-embed until `purge_expired` runs. That
backlog is one of the things an operator reads this report to see. `walk_records`
drops more still. So the population is stated as physical presence, which is the same
notion `SqliteMemoryStore.get` already works in, and §5 records that no contract
member supplies it — a third and independent reason the mechanism reads the store's
storage rather than its contract.

**The census is kept even though #799 ruled the proportion useless, and the job has
changed.** #799 ruled it the wrong *tuning* statistic — it does not predict the
retrieval cliff, and after ADR-0128 there is no cliff to predict. What it does say is
how much of the store is scanned for nothing. `search` is a linear scan of the vector
table because `vec0` keeps no ANN index, so a retired record costs a scan exactly what
a live one does, at the ~1.2 µs per record #799 measured; and every retired record is
also a row in the backup, a row in a re-embed, and a row a future ANN index would have
to hold. The proportion is a dead-weight figure and it is labelled as one. It is not
offered as an answer to #824.

**The density figure is #824's question made computable, and it is stated against its
own null.** If closure were spread evenly through the geometry, a live record's
neighbourhood would contain non-live records at about the store-wide proportion, so
the proportion printed beside the distribution is the value the distribution should
sit on if nothing is concentrated. Topic-concentrated closure is a heavy right tail —
live beliefs whose nearest neighbours are almost all retired versions of themselves,
which is #457's mechanism in the store rather than in a read. That is the shape the
operator is looking for, and it is why the figure is a *distribution* and not a mean:
a mean over an evenly-aged store and a mean over a store with a few catastrophically
crowded topics can be identical, which is the whole of what #799 found.

**The `k + 1` clause is a domain rule, not a restatement of §1's empty-population
rule, and the two do not overlap.** §1 makes a figure undefined where its
population is empty; the density figure's population is the *sample*, and a store
holding one live vector-bearing record supplies a sample of one — non-empty — whose
single neighbourhood is empty, because the record itself is excluded. Every
available reading of that case is wrong: a density of `0 ÷ k` reports "no closure
nearby" from a store with no neighbourhood at all, a division by a count of
available neighbours reports `0 ÷ 0`, and dropping the record silently shrinks a
sample the report has already stated the size of. The condition is uniform across
records — with `k + 1` vector-bearing records in the store, *every* record has `k`
others — so one store-wide test settles it, and the figure is either taken over full
neighbourhoods or not taken. `k` is required positive for the same reason from the
other end: a `k` of zero makes the denominator zero on every record in every store.

The null is approximate, and the approximation is named: a neighbourhood excludes the
sampled record itself and is drawn from `k` nearest rather than uniformly, so the
expected density under even spread is near the store-wide proportion rather than
exactly it. The figure is read as a comparison, not as a test statistic, which is what
§6's no-threshold clause requires of it in any case.

**The sample exists because the cost is quadratic and the backend has no index.** A
density per record is one KNN over the whole vector table, and `vec0` scans it; at
#799's measured ~1.2 µs per record a sample of `m` records over a store of `n` costs
about `m × n × 1.2 µs`, which is seconds for a thousand samples over a hundred
thousand records and hours for the exhaustive figure. Sampling is the honest way to
buy the figure, and the determinism clause is what keeps it a figure rather than a
draw: two operators running the same tool on the same store at the same `T` must not
get two answers. The mechanism — a stable order over ids, a stride, a hash cut — is
the implementing lane's, and any of them satisfies the clause.

**The clause binds the sample and not the figure's value, and the distinction is the
one an implementation gets wrong.** Determinism here means *which records are looked
at*, which is why the sample is required not to depend on `T`: a sampler that drew
from the live records would change its draw as the day moved, and two censuses of an
unchanged store would then differ for two reasons at once — the records whose windows
lapsed, and the records the sampler happened to pick. What a figure is *worth* is
allowed to move with `T`, and must: a record whose `valid_until` falls between two
runs is live in the first census and retired in the second, and a rule promising
identical figures across that would be promising a census that is not of an instant.
`T` is an input (§1) precisely so the two effects are separable — an operator who
wants the same answer twice passes the same `T`, and one who wants to see what a day
did passes two.

**Closure age is what the store can honestly say about churn, and the limit is
stated.** There is no supersession lineage in the store (Context), so "how many times
has this belief been corrected" is not computable and is not offered. What is
computable is *when* each retirement happened: a store whose retirements are all
recent is being actively corrected, one whose retirements are old has settled, and the
distribution distinguishes them without a single semantic judgement. A reader who
wants a per-belief correction count should read ADR-0120 §5's correction rate, which
is a rate over events and is the right instrument for it — bounded, as §1 says, to the
retained window.

**Band fill is here because #829's experiment turns on it and it is nearly free.**
Arming consolidation writes into the `DERIVED` band (ADR-0106), so the band
decomposition is the store-side view of the intervention ADR-0120 §8 partitions the
stream at. It needs no vector and no sample, and it uses `core`'s own `band_of` so the
census cannot disagree with the store about which band a record is in.

**The no-vector count is a completeness statement and not an error.** `vec_records`
is joined to `records` by `rowid` with no foreign key, and a re-embed rebuilds the
store; a record with no vector enters the census, the closure age and the band fill
and leaves the density figure's population. Counting them separately is what lets a
reader tell "the geometry is healthy" from "the geometry was mostly not read".

### 4. The census is taken of a store nothing is writing, and it writes nothing back

> **Normative.** The tool takes `<data_dir>/hub.lock` before it opens the store and
> holds it until it exits. A contended lock is refused immediately with a diagnostic
> naming the data directory and the lock path; the tool does not retry.

> **Normative.** The tool writes nothing to the memory store: it adds, updates,
> deletes and purges no record, and it **advances no named walk cursor** under
> ADR-0114.

> **Normative.** The tool opens no store but the memory store. It emits no
> `EvaluationTrace`, reads none, and purges none.

> **Normative.** Where the store's file does not exist, the report says so and states
> no figure, and the tool does not create one. Where the store exists and holds no
> record, the report says the store is empty and states no figure.

**The lock is a correctness condition and not hygiene.** §1 defines every figure at
one instant `T`; a census taken while supersessions are landing is a census of no
instant, and the concentration figure is the one that would suffer most, since a
retirement changes both a sampled record's liveness and its neighbours'. ADR-0083 §10
already establishes the shape — "Everything else that needs the data goes through the
API, **or runs while the hub is stopped**. An offline tool … takes the same instance
lock, which serialises it against the hub by construction and needs no new mechanism"
— and ADR-0120 §9 took it for the trace reader. This is the same lock for the same
reason.

**The cursor clause exists because ADR-0114's walk is named and durable, and it binds
even though the census cannot come from a walk.** §3's population is every record the
store holds and `walk_records` yields only the live and retained ones (§5), so the
mechanism has no reason to touch a walk at all — but "no reason to" is not a rule, and
the failure it prevents is severe and silent. A diagnostic that reached for
`walk_records` and then called `advance_walk` would consume a consumer's position and
silently skip records for whatever job owns that
name. Reading through a walk is permitted; *advancing* one is not. This is stated as a
clause rather than left to care, because the failure is invisible and lands on a
different subsystem.

**The absent store is not a failure**, exactly as it is not one for the measures
tool: a deployment that has never run the hub has written no record, and opening a
database to discover that would create the very thing being asked about.
`build_measure_reader`'s own note records the same disposition — "A reader that opened
the database on construction would create an empty one as a side effect of a
deployment that has never run the hub asking whether it has any traces".

### 5. The mechanism lives in `memory/`, and the placement follows the instrument

> **Normative.** The store-health mechanism lives in `ai_assistant/memory/`, it is
> wired in `app/composition.py`, and its console entry point lives in
> `ai_assistant/service/` and imports no subsystem directly.

> **Normative.** The entry point is its **own** console script, beside
> `ai-assistant-hub`, `ai-assistant-reembed` and `ai-assistant-measures`, and never
> an `assistant` subcommand.

> **Normative.** No `AssistantEngine` method, no wire operation and no `assistant`
> CLI command is created for reading store health. No Protocol in
> `core/protocols.py` changes, and no type, enum member or constant is added to
> `core/types.py`.

> **Normative.** No component of the request pipeline — `orchestration`, `memory`,
> `context`, `planning`, `readers`, `learning`, `tools`, `permissions` — and no
> interface adapter computes, holds, caches or consults a figure defined here, and
> no figure defined here is an input to anything the system does. The mechanism's
> module is reached only through `app` by the offline entry point.

> **Normative.** The implementing lane makes the previous clause mechanical: a
> `lint-imports` contract names the store-health module as forbidden to every
> subsystem package and to `orchestration` and `interfaces`.

> **Normative.** The store-health report is its own type, produced in
> `ai_assistant/memory/`. It is not a section, field or variant of ADR-0120's
> `MeasureReport`, and neither report imports the other's package.

**Three placements were available and two of them cannot hold the figure §3 defines.**

*In `evaluation/`, beside `MeasureReader`* — the shape #922's lane sketch assumed — is
unavailable, and the reason is mechanical rather than stylistic. `pyproject.toml`'s
"evaluation depends on core and nothing else" contract forbids `evaluation → memory`,
so a reader placed there reaches the memory store only through the `MemoryStore`
Protocol, and that Protocol cannot supply §3's figures. `search` cannot see a retired
row after ADR-0128 §1 (§2). `walk_records` yields "only records retained *and* live at
the instant it reads", so a walk cannot see one either — and that is not an oversight
to route around but ADR-0114's ruling that "the walk sides with `get`/`search` rather
than with `export`, because everything that *derives* new content reads the live set".
And `export`, which does return the window-closed records, is a data-rights snapshot
that excludes the expired ones — "retention still wins over history" — so it cannot
supply §3's purge backlog either, and it returns the whole store in a single
`list[MemoryRecord]`. **No `MemoryStore` member returns the census population**, and
none of them returns an embedding. So a reader placed in `evaluation/` could take a
census that is short by the expired rows, only by holding every record in memory at
once, and **could not compute the concentration figure at all** — the package boundary
would pick the figures, which is backwards, and the figure it would drop is the one
ADR-0128 §3 routed here.

*Adding the vectors to the `MemoryStore` contract* would restore that placement and is
declined on three grounds, none of which is the cost of writing the ADR. It is a
Protocol change, so under golden rule 5 it merges as its own ratified ADR before
anything implements against it — which is a real price but the smallest of the three.
It would put a diagnostic-only member on a contract three implementations must satisfy,
for a quantity only the vector-backed one has: `FakeMemoryStore` and
`InMemoryMemoryStore` would have to answer a question about a geometry they do not
have. And it would make the embeddings — which are today an implementation detail of
one store, joined by `rowid` with no foreign key and rebuilt wholesale by a re-embed —
part of the public contract, so a later store could no longer choose a different
representation. A tool that runs once a week does not get to constrain the store's
storage forever.

*In `memory/`* is refused by nothing and has an exact precedent. `Reembedder` is an
offline migration living in `memory/`, reading and rewriting the same schema, built by
`build_reembedder` in `app/composition.py`, and driven by `service/reembed.py` — an
entry point that names no subsystem type, takes the instance lock, and is its own
console script. ADR-0104 §5 settles every term of that arrangement and ADR-0120 §9
transferred it once already. The store-health reader is that shape with the embedder
removed, which makes it strictly simpler than the tool it copies: `build_reembedder`
exists partly to hold ADR-0104 §4's cloud refusal, and this reader has nothing to
refuse because it embeds nothing.

**ADR-0120 §9 is honoured rather than contradicted, and the difference is the
instrument.** §9 put the measures in `evaluation/` on two grounds: that it "is the
package that already implements the three trace Protocols", and that "no subsystem may
import it — which is the same contract that makes ADR-0119 §7's prohibition
mechanical". Neither transfers. The memory store is not the trace stream; `evaluation/`
implements no memory Protocol; and ADR-0119 §7's prohibition is on the *pipeline
reading traces back*, a hazard that has no analogue here because every pipeline
component reads the memory store by design. What §9's last clause does forbid — a
measure being consulted by the pipeline — is restated above as this ADR's own
obligation over these figures, and the clause after it makes it mechanical, which is
the property §9 actually valued: "unreachable from the pipeline by the architecture
checker, not by a promise". Placing the module inside a pipeline package would
otherwise weaken that to a convention, and the import contract is what buys it back.

**The entry point's placement is forced, not chosen**, by the argument ADR-0084 §6
makes and ADR-0104 §5 and ADR-0120 §9 each reuse: the tool takes the instance lock, the
lock lives in `service/lock.py`, `lint-imports`' "nothing imports the service" contract
means the entry point has to *be* in `service/`, and a subcommand "would live in
`interfaces`, which would then have to import `service`". This is the ninth entry in
`[project.scripts]` and the offline family's sixth member, by the count ADR-0126's
Consequences keeps.

**Two reports rather than one, and the first reason is that one is unconstructible.**
`memory` may not import `evaluation` (the "nothing imports the evaluation package"
contract) and `evaluation` may not import `memory`, so a single report carrying both
families would have to put its type in `core/types.py` — a type that crosses no
subsystem boundary, which ADR-0120 §9 refused in terms as "the opposite of what `core`
is for". The second reason is the one that would hold even if the first did not: §1
makes these figures a census and ADR-0120's a rate over a window, and a single document
presenting them together invites a reader to divide one by the other. Two commands, two
outputs, two instants.

### 6. No threshold, no target, no trigger

> **Normative.** No figure defined here carries a threshold, a target, a pass/fail
> verdict or a trend claim, and the report states none.

> **Normative.** No figure defined here arms, gates, schedules or selects anything.
> Nothing in the system reads one, and no mitigation, migration or policy change is
> authorised by a value one of them takes.

**This is the #824 re-ruling's disposition written into the instrument that replaces
its watch.** That ruling dissolved a trigger whose "only consumer is the `Shortfall`
figure … whose only consumer is this decision", on the ground that waiting on it
"bought nothing but the chance to never pay a cost that is mostly owed anyway". A
figure that armed something would rebuild exactly that arrangement, one instrument
later. What these figures are for is an operator reading them and ruling; ADR-0120 §1
says the same of its measures — "A measure is a number; whether it is good is the
operator's ruling" — and the disposition is the corpus's, not this ADR's invention.

**It also protects the figure from its own arithmetic.** §3's density is compared to a
null that is approximate by construction, and a threshold written on top of an
approximate null is a false precision that would be read as a fact. There is no data
yet on what a real store's distribution looks like; a number written now would be an
opinion pre-empting the data, which is ADR-0120 §14's own reason for setting none.

### 7. The report is Tier 2, and it prints no identifier and no content

> **Normative.** The report's output carries counts, proportions, distributions of
> counts and of intervals, instants, `kind` labels, `BeliefBand` labels and the run's
> stated parameters. It carries **no** record id, no `about_person` label, no record
> content or any part of it, and no embedding vector or component of one.

> **Normative.** The report is Tier 2 under ADR-0004 §1 and never leaves the device.
> This ADR creates no designated seam under ADR-0017 and no opt-in that would enable
> store-health egress.

**Printing no id closes the bridge for the reason ADR-0120 §10 gives.** An opaque id
in a report identifies nobody; what it does is invite the operator to go and look the
record up, and the lookup is a semantic step over content that this figure family has
no business performing. Every figure here is a count over a population defined by rules
a second implementation can re-run, so nothing is lost by refusing the id.

**The vector clause is not redundant with the content clause.** An embedding is a
lossy projection of the content that produced it, and a report that printed a
neighbourhood's vectors would be exporting the store's semantic material in a form
that reads as numbers. Naming it separately costs a sentence and closes a door that a
"we only print numbers" rule would appear to leave open.

### 8. What the implementing lane owes

> **Normative.** The lane lands, in one change: the mechanism in
> `ai_assistant/memory/`; its builder in `app/composition.py`; the entry point in
> `ai_assistant/service/`; the console script in `pyproject.toml`; the
> `lint-imports` contract §5 requires; and tests under `tests/` mirroring each path.

> **Normative.** The tests assert every disposition §1 and §4 make reachable: an
> absent store, an empty store, a store with no retired record, a store with no
> vector for any record, and a contended lock. Each is a stated output and not an
> exception.

> **Normative.** The tests assert that an **unpurged expired** record — one past
> `expires_at` that `purge_expired` has not yet removed — is in the census
> population, counted as expired, and counted in the total, over a store where
> `export` would not return it.

> **Normative.** The tests assert §3's `k` domain at its boundaries: a store
> holding exactly `k` vector-bearing records reports the figure undefined, a store
> holding exactly `k + 1` reports it over full neighbourhoods, and a `k` that is
> zero or negative is refused rather than run.

> **Normative.** The tests assert §3's determinism clause directly — two runs of the
> concentration figure over an unchanged store, with the same parameters and the
> same `T`, produce identical figures — and assert the density figure over a store
> built with a known concentration, in the shape `tests/memory/aged_store.py`
> already builds.

> **Normative.** The tests assert that `T` moves the figures and the sample: over
> an unchanged store, two runs whose `T` falls either side of a record's
> `valid_until` reclassify that record between live and retired in the census, the
> band fill and the density population, while selecting the same sample.

**The determinism test is named because it is the clause an implementation can pass in
name and fail in substance.** A sampler seeded from the system RNG, or one that walks a
`dict` whose order depends on insertion, satisfies every other clause and produces two
different answers on two runs — and the failure would surface as an operator
disbelieving a figure rather than as a red test. `aged_store.py` is named for the
opposite reason: the fixture that manufactures concentrated closure already exists,
built for #799, and the figure that measures it should be asserted against a store
whose concentration is known by construction.

### 9. What this ADR does not decide

- **ADR-0128 §5 item 7.** The removal of `Shortfall` and `MeasureReport.shortfall` is
  already ratified there and rides that ADR's implementation lane. This ADR neither
  re-ratifies it nor conditions anything on it, and touches no file under
  `src/ai_assistant/evaluation/`. #926's stale `FETCH_K` comment travels with that
  lane for the same reason.
- **#838's judged-sufficiency and metamemory layers.** Parked, untouched and not
  authorised by anything here. §3's band fill and census are store aggregates, which
  is the shape #838's coverage layer would consume — and §6's second clause is what
  keeps that a future ADR's decision rather than a consequence of this one.
- **#838's write-time eligibility tiering.** A live tier and a history tier would
  change what "retired" means for a walk, and #838's own comments record four
  obligations such a design owes (ADR-0114's total insertion order across tiers,
  ADR-0072 §1's partition-not-copy argument, ADR-0115 §3's hold, ADR-0118's vector
  reuse). None of them is engaged here: this ADR adds no tier, no projection and no
  copy, and reads the one store ADR-0072 §1 rules there is.
- **Whether these figures are ever computed over a window, or compared across runs.**
  §1 makes each report a census at one instant. Trending two censuses is an operator
  reading two outputs; a *figure* over successive instants would be a different
  instrument with its own sampling and settling questions, and it is not authorised
  here.
- **The report's output format** beyond §7's content rules — text, JSON or both is the
  implementing lane's, since nothing depends on it.
- **The sample size and `k`.** §3 makes both parameters and requires them stated. What
  values are useful is an operating question the first real store will answer.
- **Anything about eviction, size caps, retention policy or purge cadence.**
  ADR-0007 §5's deferral stands, as ADR-0103 §1, ADR-0112 §9, ADR-0113 §10 and
  ADR-0128 §6 each record. A dead-weight figure is not a licence to delete.
- **Whether `SqliteMemoryStore`'s vector table gains an index.** #799's affine cost is
  the reason §3 samples; changing the backend's index structure is a separate decision
  with its own consequences for `search`, and this ADR neither asks for it nor
  forecloses it.
- **What ADR-0128's revisit condition resolves to.** ADR-0128's Consequences say to
  revisit "if the store-health measure (§3) shows closure concentration that the
  pre-filter does not in fact absorb". This ADR builds the instrument for that reading
  and takes no view on what it will show; §6's second clause means the reading is an
  operator's act, not a mechanism firing.

### 10. Explicitly declined

**This section supplies no obligation of its own.** This is a marked ADR, so under
ADR-0089 §3 the marked clauses are the whole of what it obligates; every refusal below
that constrains a later lane lives in a clause above, and each entry names it.

- **Computing concentration through `MemoryStore.search`.** §2's second clause. It
  would report zero on every store in every state, because ADR-0128 §1 makes a retired
  row uncandidate.
- **Adding vector access to `MemoryStore`.** §5's third clause. A diagnostic-only
  member on a contract three implementations must satisfy, for a geometry two of them
  do not have, freezing a storage detail into the contract.
- **Placing the mechanism in `evaluation/`, beside `MeasureReader`.** §5's first
  clause. It is where #922's lane sketch put it and the import contracts make it a
  placement that can only hold the figures that do not answer the question.
- **A single report carrying both families.** §5's last clause. Unconstructible
  without a `core` type that crosses no boundary, and it invites reading a census as a
  rate.
- **A threshold, a target, or arming anything on a value.** §6. The #824 re-ruling
  took apart the last instrument built that way.
- **A decomposition by `about_person`.** §2's third clause and §7's first. Not a topic
  axis, and it would print labels the report otherwise keeps out.
- **A per-belief supersession count.** Not refused so much as unavailable: no field
  links a retired record to its successor (Context), and §3 offers closure age
  instead rather than inventing a lineage.
- **An exhaustive density over every live record.** §3's sampling clause. Quadratic
  against a backend with no ANN index; the sample buys the same shape at a stated cost.
- **Advancing a walk cursor, or writing anything to the store.** §4's second clause.
- **An `Engine` maintenance operation, a wire operation or an `assistant`
  subcommand.** §5's second and third clauses, on ADR-0084 §6's forced argument and
  ADR-0083 §8's prohibition.

### 11. What this records against earlier ADRs, under ADR-0082 §1

The judgement ADR-0082 §1 requires, applying ADR-0070 §1's test to each place a record
looks owed: would a reader holding only that ADR now act differently, or read one of
its clauses more widely than it now holds? **No record is owed anywhere**, and the
showing is given rather than asserted.

**ADR-0128 §3's third clause — a deferral discharged by the route it names.** The
clause routes the retired watch's question to "a **direct store-health measure**, read
offline over the store rather than over the trace stream, in the pattern ADR-0120 §9
sets", and says "this ADR ratifies no such measure: its figures, its population and its
surface are its own lane's". This ADR supplies exactly those three and nothing the
clause reserved to itself. ADR-0128 §6 lists "the store-health measure's design — its
figures, its population, its surface, and whether it reads the store directly or a walk
over it" among what it does not decide; §2 and §5 take the first branch of that last
question with an argument. A deferral used by the route it names is discharged, not
superseded, which is the distinction ADR-0110 §13 draws and ADR-0128 §8 itself applies
to ADR-0079 §6. **No record owed.**

**ADR-0120 §9 — nothing owed, and this is the finding a reader would most expect to go
the other way.** §9's clauses are about "the reporting tool" that computes "the
measures", and every one of them is scoped to that tool by its own words: "The measures
are computed by a **reporting tool** that runs while the hub is stopped"; "The
**reporting mechanism** lives in `ai_assistant/evaluation/`"; "The **reporting tool**
calls `TraceStore.walk` and no other member". This ADR builds a different tool over a
different store, and §1 rules its figures are not measures of ADR-0120. A reader
holding only ADR-0120 builds ADR-0120's tool in `evaluation/` and is right to; nothing
above tells them otherwise, and §5's placement is a statement about a tool ADR-0120
does not describe. The clause that comes closest is §9's last — "No component of the
request pipeline computes, holds, caches or consults a measure" — and it is not
narrowed here: §5's fourth clause restates the same prohibition over these figures, and
§5's fifth makes it mechanical. **No record owed.** A reviewer who thinks §9 reads as a
general rule about *all* offline evaluation tooling should say so as a finding; the
answer this ADR gives is that §9's subject is named in every clause and the pattern
ADR-0128 §3 invoked is the offline-tool *shape*, not the `evaluation/` address.

**ADR-0120 §1 and §10 — nothing owed.** §1's clauses bind "every measure defined by
this ADR" and §10's bind "the report" it defines; neither reaches a figure family
defined elsewhere. §1's second and third clauses (undefined on an empty denominator, no
threshold) and §10's content rules are **restated** here as §1's and §6's and §7's own,
which takes nothing from ADR-0120 and adds nothing to it: an ADR adopting another's
disposition for its own subject leaves the original binding exactly what it bound.
**No record owed**, and the restatement is deliberate rather than a citation because a
lane reading only this ADR must be bound by them.

**ADR-0119 §2 and §7 — nothing owed.** §2's content rule constrains what a *trace*
carries and this ADR emits none. §7's prohibition — no pipeline component "holds a seam
carrying the **walk**, and none reads a trace back" — is about the trace stream; §4's
third clause keeps this tool out of the trace store entirely, in either direction, so
§7 is not engaged rather than narrowed. **No record owed.**

**ADR-0114 — nothing owed, and its lifecycle predicate is read as written rather than
worked around.** §5 takes ADR-0114's ruling that a walk yields only the retained and
live records at face value, and concludes from it that this census cannot be taken
through a walk — not that the walk should change. §4's second clause *narrows* this
tool's own behaviour by forbidding it to advance a cursor, which adds an obligation on
this lane and none on ADR-0114. Nothing here reopens ADR-0114's total-insertion-order
condition, because nothing here partitions the store (§9). **No record owed.**

**ADR-0104 §5 — nothing owed.** The offline-tool placement is cited as the precedent it
is, and this ADR takes it as written: entry point in `service/`, mechanism in the
package that owns the data, wiring in `app`. ADR-0104 §4's cloud refusal is not
engaged, because §2's first clause means no embedder is constructed. Reusing a shape
neither widens nor narrows the decision that established it. **No record owed.**

**ADR-0045 §6, ADR-0007 §2, ADR-0072 §1 and §4, ADR-0100 §6, ADR-0004 §1 — nothing
owed.** Each is read as a definition this ADR consumes: liveness at a read instant, the
retention deadline, the single store and the band's single classifier, the subject axis,
the tier. None acquires an exception and none loses one. In particular ADR-0072 §1's
"one store" is affirmed rather than touched — §4 forbids this tool to write, so it
creates no projection and no cache with an invalidation contract to drift.

**ADR-0112 §7 — nothing owed, and it is worth stating because a reader may expect a
measurement gate to appear.** §7's second clause gates *headroom changes* to retrieval.
This ADR changes no retrieval parameter, makes no bet on a candidate budget, and does
not touch the read path at all. **No record owed.**

## Consequences

- **#824's question becomes answerable for the first time, over the store instead of
  the stream.** The watch could report incidence and not concentration, and after
  ADR-0128 it could report neither; §3's density distribution reports concentration
  directly and needs no read to have gone wrong first. What it gives up is timing —
  a census says what the store looks like now, never when it got that way — and
  ADR-0120 §5's correction rate remains the instrument for the rate of events.
- **ADR-0128's revisit condition acquires an instrument.** Its Consequences say to
  revisit "if the store-health measure (§3) shows closure concentration that the
  pre-filter does not in fact absorb". That reading is now a command an operator can
  run; §6 keeps the reading an operator's act.
- **A pipeline package gains an offline diagnostic, and the import contract is what
  makes that safe.** `memory/` is the second subsystem to hold an offline tool, after
  its own `Reembedder`, and unlike `evaluation/` it is a package the pipeline may
  import. §5's fifth clause pays for that with a `lint-imports` contract naming the
  module, so the separation is checked rather than promised — and the same clause is
  the reason this placement does not weaken what ADR-0120 §9 bought.
- **Two offline reports where there was one, and they must not be added together.**
  An operator now runs `ai-assistant-measures` for rates over a window and a second
  script for a census at an instant. §1's second clause forbids substituting one for
  the other, and the cost of the split is that a reader wanting both stops the hub
  once and runs two commands.
- **The concentration figure is a sampled estimate and the report says so every
  time.** That is a permanent property, not a first-version compromise: the exhaustive
  figure is quadratic against a backend with no ANN index, and #799's ~1.2 µs per
  record is the constant it would be quadratic in. If an ANN index ever lands, the
  exhaustive figure becomes affordable and §3's sampling clause is the thing to
  revisit.
- **Revisit if** a store appears whose retirement is not window-closure — a tier, an
  archive, a hard delete on supersession — since §3's every definition is written on
  `valid_until`; if a supersession lineage is ever stored, which would make a
  per-belief correction count computable and closure age the weaker figure; if the
  first real store's distribution turns out to be flat, in which case the concentration
  #799 built and #457 recorded is a lab artefact and ADR-0128's pre-filter is a fix for
  a failure that would never have arrived; or if #838's tiering is taken up, which
  would change what a walk sees and therefore what this census is of.

## Alternatives considered

- **The census alone — closed-row proportion, band fill, churn, and no concentration
  figure.** Rejected in §2 and §3. It is the design a `MemoryStore`-Protocol consumer
  can build, it is buildable in `evaluation/` beside `MeasureReader`, and it answers
  everything except the question ADR-0128 §3 routed here. #799 ruled the store-wide
  proportion the wrong statistic in terms; shipping it as the answer would discharge
  the clause in form and leave the incidence question exactly where #824 left it.
- **Concentration through `MemoryStore.search`, with an embedder in the tool.**
  Rejected in §2. ADR-0128 §1 makes a retired record uncandidate, so the figure is
  zero by construction on every store — the shape ADR-0128's own Context calls "worse
  than no figure" — and it would drag an `Embedder`, ADR-0104 §4's cloud-refusal
  question and a per-query model call into a tool that needs none of them.
- **A new `MemoryStore` member exposing stored vectors or neighbourhoods.** Rejected
  in §5. It restores the `evaluation/` placement at the price of a Protocol change, a
  diagnostic-only obligation on two implementations that hold no geometry, and the
  embeddings becoming contract rather than storage. A weekly tool should not fix the
  store's representation.
- **A section on `MeasureReport`.** Rejected in §5. `memory` may not import
  `evaluation` and `evaluation` may not import `memory`, so it needs a `core` type that
  crosses no subsystem boundary — the shape ADR-0120 §9 refused in terms — and it pools
  a census with a rate in one document.
- **A subcommand on `ai-assistant-measures`, sharing its lock acquisition.** Rejected
  in §5. The two tools open different stores and compute different kinds of number, the
  lock is taken per run so nothing is shared by combining them, and the combined tool
  would have to import both `evaluation` and `memory` through `app` to render two
  reports whose only relationship is that an operator reads them on the same afternoon.
- **A `GROUP BY about_person` breakdown.** Rejected in §2 and §7. It looks like a
  topical decomposition and is not one (ADR-0100 §6), and it would put user-supplied
  labels about third parties into a report otherwise free of them.
- **An exhaustive density over every live record.** Rejected in §3. Quadratic against
  a linear-scan backend; the sample gives the same distribution shape at a cost the
  report states.
- **A mean neighbourhood density instead of a distribution.** Rejected in §3. It is
  the figure #799's finding specifically rules out: an evenly-aged store and a store
  with a few catastrophically crowded topics can share a mean, and the difference
  between them is the whole question.
- **A threshold on the density distribution, or arming a mitigation on it.** Rejected
  in §6. There is no data on what a real store's distribution looks like, so any number
  written now is an opinion pre-empting the data (ADR-0120 §14's own ground), and the
  #824 re-ruling took apart the last figure that existed to arm something.
- **Deferring the whole family until an operator asks for a figure.** Rejected. The
  question has been open since leg 7's exit, its previous instrument was retired by
  ADR-0128 on the understanding that this one replaces it, and the accumulation arc
  that manufactures concentrated closure has already started. Deferring would leave
  ADR-0128 §3's third clause discharged by nothing.
