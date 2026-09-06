# 237. `search` filters on what the records already carry, and a structured read needs no query

- Status: Proposed
- Date: 2026-09-05

## Context

### Where this comes from

Design note #1874 names it "ADR B": `MemoryStore.search` "gains filters over what
the records already carry (`occurred_at` range, `participants`, `topics`,
`about_person`), so an event is found by when/where/what". Milestone 30 of
`track:planning` (#1908) is the consumer — "the planner chooses how to read",
whose envelope kinds "each is inert until `track:memory` has ratified the store
read it maps to". This is that store read, and nothing else: the envelope kind is
#1908's lane, the episode-labelling producer is its own lane, and neither is
decided here.

The owner sharpened the milestone on 2026-09-05 and the sharpening is the brief
this ADR is written against, not the design note's porch cameras:

- **The value is "it remembered the right conversation", not "we added search
  parameters".** The exit must *isolate structure's contribution*: several
  conversations on one topic, only one matching the asked person **and** period.
  Different-wording retrieval does not isolate it, because the store is already
  semantic.
- **Structure complements, never replaces.** A bounded time/person/topic lookup
  must be possible **without a similarity query**; semantic search stays available.
- **An empty structured result is not proof nothing happened.**
- **Grounded in existing conversations.** No cameras, event producers or entity
  system as preconditions.
- **First slice**: a time-window filter over episodes plus the existing text
  query — "what did we discuss about the renovation last week".

### The tree, read rather than assumed, at `origin/main` `b732dc7e`

- `core/protocols.py` — `MemoryStore.search(query: str, *, limit: int = 10,
  kinds: Sequence[MemoryKind] | None = None, bands: Sequence[BeliefBand] | None =
  None) -> MemorySearchResult`. Four arguments, none of them structured.
- `core/types.py` — `MemoryBase` carries `about_person` and `topics`;
  `EpisodicMemory` carries `occurred_at: UtcInstant` and `participants:
  tuple[EncodableText, ...]`. The values the filters would read are already
  stored, on records already written.
- `orchestration/conversations.py` — the one capture producer.
  `_build_episode` stamps `occurred_at=turn.occurred_at` and **nothing else on
  these axes**: its own docstring says "``participants`` stays empty, because the
  two parties to a turn are structural rather than informative and constants there
  would occupy, with noise, the field an observer means to fill with the people an
  episode is *about*". It sets no `topics` and no `about_person`.
- `docs/adr/0213-…` §6 — "Capture (`orchestration/conversations.py`) writes no
  topics on the `EpisodicMemory` it records per turn. **No topic is proposed on any
  episode under this ADR, by any producer.**" The two topic producers are
  `ModelBackedObserver` and `ConsolidationStage`, and both label *beliefs*.
- So **the who/what axes are unpopulated on every captured episode today**, and
  the only axis today's data supports is time. The owner's audit (#1908, M30 (b))
  says exactly this, and it is true at this ADR's base.
- `search` is **not** on the promoted `AssistantEngine` surface and takes and
  returns no type that crosses `wire/` or `service/`; the wire's method set is
  pinned by `tests/core/test_engine_surface_closure.py` beside `PROTOCOL_VERSION`.
- The stores are `InMemoryMemoryStore` (`memory/store.py`), `SqliteMemoryStore`
  (`memory/sqlite_store.py`) and the canonical fake `FakeMemoryStore`
  (`testing/memory.py`); the shared suite is
  `tests/memory/memory_store_contract.py`.

### What the corpus already decides, and is used here as given

- **ADR-0128 §1** — every read-time eligibility predicate `search` applies binds
  **before the ranking cut**, and "a store that cannot bind one of them before its
  cut does not conform".
- **ADR-0128 §2** — `search` returns a `MemorySearchResult` carrying the records
  and `capped`, whose four clauses say what each state certifies. `capped` is
  `False`, never `True`, "where `search` matches nothing by construction: a blank
  query, a non-positive `limit`, or **a filter selecting nothing**".
- **ADR-0113 §3** — the filter conventions: `None` selects everything on that
  axis, an **empty sequence selects nothing**, duplicates are set semantics, and
  filters compose by **conjunction**. Stated rather than inherited, "for the reason
  ADR-0073 §1 gives about `kinds`".
- **ADR-0113 §4, ADR-0112 §1–§2** — an eligibility axis is never an ordering one,
  and `search` is granted no weighting authority over any quantity.
- **ADR-0073 §1–§2** — `list_beliefs` is the query-less read the corpus already
  runs: a **total, stable, specified** order (`provenance.last_updated`
  descending, ties by `id` ascending), every predicate before the cut, and `score`
  **cleared** on every record because nothing was ranked.
- **ADR-0100 §3** — an unset `about_person` "means no subject is stated, and is
  read as the owner's"; **the owner is never named** in that field.
- **ADR-0100 §6** — a subject label is "a label, carried verbatim, resolving to
  nothing", and whether labels may be *matched* was reserved to a later ADR.
- **ADR-0101 §2–§3** — that later ADR. A subject query matches a record "exactly
  when `r` states a subject and the two labels are **canonically caseless-equal**
  in the Unicode Standard's sense (definition D145)", nothing else is compared,
  and "**a record with `about_person` unset is matched by no query**". ADR-0101
  §10 records the scope of the lift: ADR-0100 §6's reservation is one "which §3
  lifts only as far as comparison and matching".
- **ADR-0213 §3** — `TopicLabel`'s only relation is equality of the stored
  characters; a wider matching rule is reserved (§15).
- **ADR-0213 §7** — an empty `topics` states that **no topic was recorded**: "not
  'about nothing' and not 'about everything'", "a topic-scoped act reaches a record
  if and only if the record carries the label the act names", and the surface owes
  the owner the disclosure that unlabelled records were not reached.
- **ADR-0213 §15** — two deferrals this ADR meets. A topic-scoped `forget` "owes
  three things this ADR cannot give it", the first being "a `MemoryStore` read that
  selects records by label, which is a Protocol change and therefore its own
  ratified, separately-merged ADR". And "**The storage a filtered record read
  needs.** §11 requires none, because no read here filters records by label.
  **Fires** with the lane that adds that read".

### Claims in the framing that do not survive contact with the tree

Two, and both are recorded rather than quietly worked around.

**"The planner broadens (28's revision) rather than concluding" is not available
on an empty read.** ADR-0228 §2 fires a revision only where **all seven** of its
conditions hold, and (e) is "The servicing returned **at least one record the
supply did not already hold**, counted after ADR-0226 §7's deduplication." An
empty structured read returns none, so it fires no revision under the mechanism as
ratified. The obligation this ADR states in §7 — that an empty result is a
statement about *records carrying the values named* and never about the world —
is therefore a store-contract obligation on the *consumer's reading*, and the
broadening that would act on it is the planner lane's to build or to defer. This
ADR neither asserts the mechanism exists nor decides what replaces it.

**The generalisation of ADR-0213 §7 to `about_person` is a restatement, not a new
rule.** ADR-0101 §2 already rules that "a record with `about_person` unset is
matched by no query". §6 below states the rule once across all four axes and shows
that on the subject axis it is the ratified sentence and not a widening of it.

### What this ADR is not allowed to settle

- **The producer that fills the who/what axes.** #1908's M30 owes an
  episode-labelling producer; ADR-0213 §6 forbids any producer from labelling an
  episode today and §15 defers "Topics on episodes" with its own firing condition.
  That is a separate ADR and a separate lane. This one decides a *read*.
- **The planner's envelope kind** that names a structured read (#1908's M30, the
  `track:planning` lane). §1 below is a store surface; nothing here says how a plan
  asks for it.
- **Hybrid or lexical search** (ADR-0006 §5) — a different retrieval mechanism, not
  a filter over stored values.
- **A topic-scoped `forget` or guard** (#1720, #1719, ADR-0213 §15). This ADR
  supplies the first of the three things §15 says that lane owes and takes no part
  of the other two.
- **Ranking.** ADR-0112 §1 and ADR-0113 §4 own the ordering axis. §5 below names
  the order for a read that has no relevance to rank by, and supplies no quantity
  and no place to put one.
- **Any wider matching rule** for a person label or a topic label. Both are
  reserved elsewhere (ADR-0101 §10, ADR-0213 §15) and this ADR takes neither.

## Decision

### 1. Four filters over what the records already carry, and each binds before the ranking cut

> **Normative.** `MemoryStore` gains four keyword-only filter axes over values the
> records already carry: `occurred_within`, `participants`, `topics` and
> `about_person`. Each defaults to `None`, and `None` means the axis is not
> applied. **Two** reads carry them: `search`, whose `query` stays required and
> whose order stays relevance; and `select` (§4), the structured read that carries
> no query at all. `MemorySearchResult` gains no field, and no **existing**
> `MemoryStore` member other than `search` changes.

> **Normative.** On both reads each of the four is a **read-time eligibility
> predicate** and binds **before the ranking cut**, joining the predicates
> ADR-0128 §1 already binds there. An implementation may not let a record failing
> any of them consume the candidate budget the cut is taken from, and the records
> it ranks are the records eligible on every one of those axes. A store that
> cannot bind one of them before its cut does not conform — the implementing lane stops and brings back an
> ADR rather than shipping the weaker form.

> **Normative.** No filter is an ordering term on either read. None of the four is
> an addend, factor, weight or threshold in any comparison, and on `search` a call
> spanning two values of an axis compares the records it selects to one another by
> relevance and by nothing else — ADR-0113 §4's clause, which binds on `search`
> unchanged and unnarrowed after this decision. `select` ranks nothing at all and
> §5 states the order it returns instead.

The two signatures this decides, stated once so the shapes are not read out of
prose:

```python
async def search(
    self,
    query: str,
    *,
    limit: int = 10,
    kinds: Sequence[MemoryKind] | None = None,
    bands: Sequence[BeliefBand] | None = None,
    occurred_within: TimeWindow | None = None,
    participants: Sequence[NonBlankEncodableText] | None = None,
    topics: Sequence[TopicLabel] | None = None,
    about_person: Sequence[NonBlankEncodableText] | None = None,
) -> MemorySearchResult: ...


async def select(
    self,
    *,
    limit: int = 10,
    kinds: Sequence[MemoryKind] | None = None,
    bands: Sequence[BeliefBand] | None = None,
    occurred_within: TimeWindow | None = None,
    participants: Sequence[NonBlankEncodableText] | None = None,
    topics: Sequence[TopicLabel] | None = None,
    about_person: Sequence[NonBlankEncodableText] | None = None,
) -> MemorySearchResult: ...
```

**Docstrings are owed and are not reproduced here**, which is ADR-0085 §3's move
and ADR-0101 §1's: `CONTRIBUTING.md`'s Google-style requirement applies to the
real `core/protocols.py`, and reproducing the prose would bury the shapes this
section exists to fix. What each docstring must state is settled by the clauses of
§§1–8 and by nothing outside them (ADR-0089 §3).

**Every existing caller is preserved unchanged**, because every new argument is
keyword-only with a `None` default, `query` keeps its position and its type, and
`select` is a member nobody calls yet. That is not a
convenience: ADR-0128 §5 names five call sites (`orchestration/loop.py`,
`orchestration/retrieval.py`, `memory/ingest.py`, `tools/builtin.py`,
`testing/writer.py`), and a contract change that obliged five consumers to decide
something they have no question about would be spending five lanes' review on a
default.

**The pre-cut clause is the one an implementation can pass in name and fail in
substance**, which is why it is a contract decision and not a parameter. ADR-0128
§1 argues it in full and the argument is not re-derived: a nearer ineligible row
consuming a candidate slot the cut is taken from is the mechanism, and #799
measured it as a threshold — 0% below a filtered-neighbour density of
`fetch_k − limit` and 100% above it. On these axes the skew is worse than on the
band's, and structurally so. A time window over "last week" excludes, by
construction, every record the store has ever written outside it; a store that
retrieves the top `limit` by similarity and *then* drops what falls outside the
window will return nothing at all on any store with more than a few weeks of
history, while the records the user asked for sit eligible and unranked. The
milestone's own exit — several conversations on one topic, only one matching the
asked person and period — is precisely a crowded-neighbour fixture: the
distractors are near in similarity by construction, because they are about the
same topic.

**The filters bind on the record's own stored value and on nothing derived.** No
implementation infers a topic, a participant, a subject or an instant from
`content`, from `outcome`, from a rendered facet or from any other span at read
time. That is ADR-0213 §4's write-time rule ("no consumer, surface, store,
retrieval path, scheduler job, migration or later ADR derives a record's topics at
read time") holding on the read this ADR adds, and ADR-0199 §2's read-time
classifier prohibition holding with it. A filter is a comparison against a stored
field or it is not this decision.

### 2. The shapes, and how the four compose

> **Normative.** `occurred_within` takes a `TimeWindow`: one new frozen
> `core/types.py` model with `start: UtcInstant | None` and `end: UtcInstant |
> None`, bounding the **half-open** interval `[start, end)`. A record is eligible
> on this axis when it carries an `occurred_at` and `start <= occurred_at` (or
> `start` is unset) **and** `occurred_at < end` (or `end` is unset). A window with
> both ends unset is refused with `ValueError`, and so is one whose `end` is not
> strictly after its `start`.

> **Normative.** `participants`, `topics` and `about_person` each take a sequence.
> `None` means the axis is not applied; an **empty sequence selects nothing**;
> duplicates are set semantics and change nothing. This is ADR-0113 §3's
> convention, stated here rather than left to be read off a sibling parameter, for
> the reason ADR-0113 §3 gives: leaving it to be inherited "is how one
> implementation comes to treat `bands=()` as 'no filter' — the opposite outcome".

> **Normative.** **Within** an axis the values compose by **disjunction**: a record
> is eligible on that axis when it matches at least one of the values given.
> **Across** axes — the four new ones, `kinds` and `bands` alike — they compose by
> **conjunction**: a record is eligible when it is eligible on every axis the call
> applies.

> **Normative.** A blank or whitespace-only value in `participants` or
> `about_person` is refused with `ValueError`. It is never read as "unstated" and
> it never matches a record. A `topics` value not already in `TopicLabel`'s
> canonical form is refused by the type.

**The window is a value object because the half-open convention and the inversion
rule are exactly what two stores would implement differently.** `Validity` is the
corpus's own precedent for the shape — half-open `[valid_from, valid_until)`,
`None` at either end meaning unbounded, and a model validator refusing an
inverted window — and reusing the shape rather than two loose keyword arguments
puts the three ambiguities (which end is inclusive, what an inverted window does,
what an unbounded one does) in one validated place. It is the discipline ADR-0092
§2 used to choose a value object, applied to an argument list, and it is the same
reason ADR-0128 §2 gave `search` a result type rather than a bare list.

**A both-ends-unset window is refused where `Validity` permits one**, and the
asymmetry is the difference between a stored value and a query. `Validity()` means
"live forever until something retires it", which is a fact about a record.
`TimeWindow()` would mean "any instant", which is a caller that reached for a
bound and named none — ADR-0100 §1's reasoning about a blank label ("a record
saying `""` is a producer that meant to speak and said nothing") read on a query,
and ADR-0101 §1's blank refusal on the same ground. A caller wanting every record
omits the argument.

**One window and not a sequence of them**, because a disjunction of intervals has
no consumer in sight and one interval is what "last week" is. A caller wanting two
disjoint periods issues two calls and composes, which is what ADR-0113 §6 already
has a band-precedence consumer doing.

**The three sequence axes have one arity between them and it is the sequence**,
even though ADR-0100 §6 rules that "a belief has at most one subject" and
`export`'s own subject argument is singular (ADR-0101 §1). The record's arity and
the *query's* arity are different questions: a record has one subject, and a
caller may legitimately ask about two people. What a mixed surface would cost is
the argument against it — one method with four new axes of three different
arities is the surface a caller gets wrong, and the milestone's own exit ("only
one matching the asked person *and* period") is a conjunction across axes rather
than within one, so nothing is bought by making one of them scalar.
`MemoryStore.export`'s singular argument is untouched by this ADR; the two are
different operations and ADR-0101 §8's symmetry argument is about `export` and
`delete_about`, not about `search`.

**`NonBlankEncodableText` carries the blank refusal rather than a hand-written
check**, which is the annotation ADR-0100 §1 chose for `about_person` itself and
for this reason: "it refuses a blank without stripping the value it accepts". The
value a caller passes reaches the comparison byte for byte.

### 3. Matching: three rules, every one of them borrowed

> **Normative.** `about_person` matches by ADR-0101 §2's rule, unchanged and
> unextended: a value `q` matches a record `r` exactly when `r` states a subject
> and `NFD(toCasefold(NFD(q)))` equals `NFD(toCasefold(NFD(r.about_person)))`.
> Nothing else is compared, and no implementation trims, strips diacritics, removes
> punctuation, tokenises, splits, truncates or otherwise transforms either label
> beyond that fold.

> **Normative.** `participants` matches by the **same** rule, applied across the
> record's tuple: a record is eligible on this axis when at least one entry of its
> `participants` is canonically caseless-equal, in that same sense, to at least one
> of the call's values.

> **Normative.** `topics` matches by **equality of the stored characters** and by
> nothing else, which is the only relation `TopicLabel` has (ADR-0213 §3). No fold
> is applied and none is needed: the type is already canonical, refusing any value
> that does not equal its own `str.casefold()`.

> **Normative.** No filter resolves a label to a person, a topic to a concept, or
> either to an identifier. Matching here is ADR-0101 §3's "pure function of two
> strings" and creates no registry, no alias table and no equivalence beyond the
> one the rule itself defines. ADR-0100 §6's identity prohibition is untouched.

**One matching rule for both person axes, and this ADR invents neither.**
ADR-0100 §6 reserved matching to a later ADR "which is the only thing that may
lift the clause above", ADR-0101 was that ADR, and ADR-0101 §10 records the scope
of what it lifted: ADR-0100 §6's reservation is one "which §3 lifts only as far as
comparison and matching". Comparison and matching is all this ADR does. Applying a
*different* rule to `participants` — byte equality, say — would put two
incompatible answers to "are these the same person label?" in one method, and the
one the caller got would depend on which field the label happened to be stored in.
The corpus is explicit that `participants` is the honest precedent for what
`about_person` is (ADR-0100 §6: "`EpisodicMemory.participants` has been
free-text-resolving-to-nothing since ADR-0005 §1"), so the two axes have the same
kind of value and get the same rule.

**Why caseless rather than exact is ADR-0101 §2's argument and is not re-derived
here**, but it is worth saying that it reads the same way on a read as on an
erasure: under exact equality a user who has written both `"Marta"` and `"marta"`
gets an answer that silently omits half their own history, and the over-reach case
requires two different people whose labels differ only in case. What is different
about a read is that the failure is recoverable — the user asks again — which is
why this ADR takes the rule rather than arguing it afresh.

**D145 is an external standard and that is what keeps the further steps out.**
Every wider rule a lane might reach for — trimming, folding diacritics, stripping
honorifics, matching nicknames — is someone's judgement about people, and none of
them is available without superseding ADR-0101 §2 (ADR-0101 §10). The same holds
one axis over: a wider topic rule is ADR-0213 §15's reservation, and "health"
reaching "healthcare" is named there as the first owner surprise it would fix and
the supersession it would cost.

### 4. The structured read is its own member, and `search` keeps its query

> **Normative.** `MemoryStore` gains `select`: a read carrying the six filter axes
> — `kinds` and `bands` as `search` has them, and §1's four — a `limit`, and **no
> query**. It returns a `MemorySearchResult` under §7's clauses, in §5's order,
> with `score` cleared on every record.

> **Normative.** `search` is otherwise unchanged in shape. Its `query` stays
> **required** and `str`; a blank or whitespace-only query still matches nothing by
> construction; its order stays relevance, best first; and `score` stays populated
> on every record it returns. Nothing in this ADR gives `search` a mode in which it
> ranks by anything other than relevance.

> **Normative.** A `select` call applies **at least one** of its six axes. A call
> applying none is refused with `ValueError`, and no value of any axis means
> "everything".

> **Normative.** `select` carries no `offset` and offers no paging. `limit` cuts,
> and a result holding `limit` records asserts nothing about whether the store holds
> further eligible records below the cut — ADR-0128 §1's second clause, on this
> read.

**A bounded structured lookup without a similarity query is the milestone's third
requirement and it cannot be met by a query.** The owner's sharpening is explicit —
"bounded time/person/topic lookup **without** a similarity query" — and the reason
is the same one that puts the filters before the cut. A structured lookup expressed
as a similarity search is a similarity search: the records it returns are the ones
nearest some text, and "which conversations involved Alex in March" has no text to
be near. Under the milestone's own exit the distractors are *the same topic*, so
any text a caller could invent is nearer to the distractors than to the answer as
often as not.

**It is a second member rather than an optional `query` on `search`, and the corpus
decides that twice over.** ADR-0113 §4's first normative clause is unconditional
over a `search` call — "Within the result of one call the order is relevance alone,
whichever bands are selected" — so a `search` that ordered by anything else, in any
mode, would make that sentence false for a reader holding only ADR-0113. That is
ADR-0082 §1's test failing and an amendment owed on a clause this decision has no
need to touch, on the axis ADR-0112 §2 is most careful about. And ADR-0073 §1 had
already answered the shape question in as many words: a read that "carries **no
query text** and is not a retrieval — nothing is ranked and no relevance is
computed — so it is an enumeration with a stable order and a page rather than a
filter on `search`". Two ratified sections point the same way, and the reading that
put the query-less read inside `search` was this ADR's own convenience rather than
the corpus's position.

**`search` still gains the four filters, because the milestone's first slice needs
them there.** "A time-window filter over episodes **plus** the existing text query"
is a filtered *relevance* read: the caller has text and wants the nearest records
within a period. That is `search` with `occurred_within`, and it is why the axes are
not confined to the new member.

**The name is `select`, and the two rejected names are rejected for reasons.**
`find` is a synonym for `search` and would leave a caller guessing which of two
members answers "find me the records about X". `list_records` borrows
`list_beliefs`' verb, which the corpus uses for a *paged inspection* of live
beliefs (ADR-0073 §1, §3), and this is neither paged nor an inspection. `recall` is
the engine's verb (ADR-0085 §3), and a seam that borrows the layer above's
vocabulary makes two surfaces look like one — ADR-0101 §1's own argument for
`delete_about`. `select` names what the operation does, promises no ordering by
relevance, and claims no completeness.

**One axis set on two members is a real cost and it is the smaller one.** The
alternative was one member with an optional query, and what it bought — a single
statement of the axes — it paid for with an amendment to ADR-0113 §4 and a `search`
carrying two orders and two `score` regimes selected by whether one argument is
`None`. The corpus already carries this cost in the same shape and made the same
choice: `kinds` and `bands` sit on `search` and on `list_beliefs` both, defined once
in ADR-0073 §1 and restated by ADR-0113 §3 rather than merged into one method. The
drift the duplication invites is closed the way ADR-0128 §5 closes its own: §2 and
§3 define the axes once, for both reads, and §9 requires the conformance suite to
run one parametrised body against both members rather than two bodies that can
disagree.

**`MemorySearchResult` is reused rather than twinned.** Its name is `search`'s
history, not a claim about which member produced it; its two fields are exactly what
`select` has to return; and a second type carrying the same pair would oblige
ADR-0128 §2's four `capped` clauses to be stated twice, which is the drift this
section has just refused one paragraph above. §7 binds those clauses on both reads.

**`list_beliefs` is untouched.** It keeps its offset paging, its refusal of an
out-of-range `limit`, its live-beliefs-only reach and its own order, and it stays
the unfiltered enumeration — which is why `select` refuses a call that names no
criterion rather than quietly becoming a second one. A caller inspecting the profile
calls `list_beliefs`; a caller retrieving by structure calls `select`; a caller with
text calls `search`. Nothing here makes any of the three a substitute for another,
and no lane may fold one into another on the strength of it.

### 5. `select`'s order, and its cleared `score`

> **Normative.** `select` orders its records by `provenance.last_updated`
> **descending**, ties broken by `id` **ascending** — the total, stable order
> ADR-0073 §1 already names for `list_beliefs` — and returns the first `limit` of
> that ordered, filtered sequence.

> **Normative.** `select` returns `score` as `None` on every record —
> **cleared**, not merely absent — because nothing was ranked. That is ADR-0073
> §2's rule, on the second read that has the same property, and it is the opposite
> of `search`'s, which stays populated exactly as ADR-0128 requires.

> **Normative.** The order is not a quantity and creates no place to put one. No
> band, confidence, currency, evidence-strength or importance is a term in it, and
> no implementation may make one so. ADR-0112 §1–§2 bind unchanged: neither read
> is granted weighting authority over any quantity by this ADR.

**Some total order has to be named or two stores answer the same call
differently**, which is ADR-0073 §1's argument for `list_beliefs`' order and
`AuditTrail.recent`'s before it, applied to a third read that has no relevance to
fall back on. Naming *that* order rather than a new one means the corpus has one
enumeration order and not two.

**It is `provenance.last_updated` and not `occurred_at`, and the reason is
totality.** Only `EpisodicMemory` carries `occurred_at`; a call whose filters admit
a semantic belief and an episode has no `occurred_at` to compare across the pair,
so an order keyed on it would be undefined on exactly the mixed result a
conjunction of `topics` and `about_person` produces. `provenance.last_updated` is
on `MemoryBase` and total over `MemoryRecord`. The cost is named rather than
hidden: on a window filter over a busy week, `limit=10` returns the ten most
recently *written* of the week's records and not the ten most recent by event
time. §7's clauses are what keep that honest, and §11 defers an event-time order
with the condition that fires it.

**Ordering `select` by a write stamp is not currency acting.**
ADR-0112 §1 forbids currency and evidence-strength as terms in "any ordering,
score, weight or cut applied to retrieved records", and names the two places
currency does act — standing (ADR-0110 §8) and presentation (ADR-0103 §9,
ADR-0072 §6). `provenance.last_updated` is neither: it is the store's own write
stamp, it is the sort key ADR-0073 §1 ratified for `list_beliefs`, and ADR-0112
was decided with that read in the tree and left it standing. What ADR-0112 refuses
is a *rank penalty on lapse* — a record pushed below the cut because a timer
expired — and a total order over a set that has no relevance ordering at all
penalises nothing: every record the filters admit is eligible, and the cut is
`limit`'s.

### 6. Empty means unrecorded, on every axis, and a filter reaches only what carries the value

> **Normative.** A filter reaches a record **if and only if** the record carries a
> value on that axis and the value matches. A record carrying no value on an axis
> is reached by no filter on that axis — whether the value is absent because the
> field is empty, because it is unset, or because the record's kind has no such
> field at all.

> **Normative.** An absent value on any of the four axes states that **nothing was
> recorded** on that axis for that record. It does not state that the record has no
> such property, and it does not state that it has every such property. No
> consumer, surface, store or later ADR reads an absent value as matching a filter
> that names one, and none reads it as excluded from a call that applies no filter
> on that axis.

> **Normative.** A surface performing a structured read says what the read did not
> reach: that records carrying no value on the axes it filtered were not reached,
> and that the reach of the read is the values that were **recorded** rather than
> the subject the owner has in mind.

**This is ADR-0213 §7 stated once over four axes rather than four times.** That
section rules it for `topics` — "an act reaches a record if and only if the record
carries the label the act names" — and the two wrong readings it names are
available on every one of these axes and damaging in the same opposite directions.
Read as "every value", an unlabelled record is admitted to every structured read
and the answer to "which conversations involved Alex" is every conversation. Read
as "no value", nothing changes about what is returned but the owner is told the
axis works. The third reading, stated with the disclosure obligation beside it, is
the only honest one while §6 of ADR-0213 leaves capture writing none.

**On the subject axis it is the ratified sentence and not a widening of it.**
ADR-0101 §2's second half already says "a record with `about_person` unset is
matched by no query", so the clause above restates it for a third operation rather
than deciding anything new. What has to be said beside it, because ADR-0100 §3
says it about *readers* and not only about fields, is the next paragraph.

**There is no way to ask for the owner's own records by this axis, and that is
deliberate.** ADR-0100 §3 rules that an unset subject "is read as the owner's" and
that "the owner is never named here — there is no user identity anywhere in this
system". So a value meaning "the owner" cannot be spelled, and a *sentinel*
meaning "unstated" would spell it: it would make an absence into a queryable
value, which is the one thing the clause above rules absences are not, and it
would do so on the axis where the corpus has been most explicit that the owner has
no label. The consequence is stated rather than left to be discovered: **a caller
wanting the owner's records omits the `about_person` argument**, which admits
stated and unstated records alike and excludes nothing. That is ADR-0100 §3's own
prohibition satisfied exactly — "no reader, store or surface may exclude a `None`
record from an answer about the owner on the ground that it says nothing" — since
the only read that excludes them is one that named somebody else.

**Today's consequence, stated plainly.** Capture writes no `topics`, no
`participants` and no `about_person` (ADR-0213 §6; `orchestration/conversations.py`
verified above), so **a `topics`, `participants` or `about_person` filter reaches
no captured episode at all** on any store as it stands. The axes are not
speculative — beliefs carry `topics` and `about_person` today, and the observer
and the consolidation stage fill them — but on episodes they are inert until the
producer #1908's M30 owes exists. This ADR states that as a fact about the tree,
not as a defect of the contract: the contract is what the producer lane will be
written against, and the milestone's **first slice is the time axis** precisely
because it is the one today's data supports. ADR-0213 §15's "Topics on episodes"
deferral fires "where a consumer's promise is materially wrong without them", and
the milestone's own exit — "which conversation involved Alex" — is such a
consumer. Naming that is not deciding it: the producer, the vocabulary and the
proposal rule are that lane's, and this ADR designs none of them.

### 7. What an empty result asserts, and what `capped` says under a filter

> **Normative.** ADR-0128 §2's four clauses bind unchanged over the new axes on
> `search`, and bind on `select`'s result in the same terms and with the same
> words. `capped` reports the store's own candidate ceiling and never the size of
> the eligible set; a read that matches nothing by construction — a filter
> selecting nothing, a non-positive `limit`, and on `search` a blank query — yields
> `capped` `False`, never `True`; and an empty result is not a capped one.

> **Normative.** `select` inherits `search`'s `limit` behaviour exactly: a
> non-positive `limit` matches nothing and returns an empty, uncapped result, and a
> `limit` larger than the eligible set returns the whole of it and raises nothing.
> Neither read *refuses* a `limit` — that is `list_beliefs`' rule (ADR-0073 §2) and
> it is not borrowed here — and neither propagates an error from a value its
> storage layer cannot represent: an implementation binding `limit` into a query
> language clamps at its own boundary, and the contract's answer is unchanged.

> **Normative.** The certification ADR-0128 §2's first clause gives — where
> `capped` is `False` and the result is shorter than `limit`, the store holds no
> further record matching the call's filters and passing its read-time eligibility
> axes — is a statement about **records carrying the values the call named**, and
> about nothing else. It is not a statement that no record concerns the subject,
> the period, the person or the topic the owner has in mind, and it is never a
> statement about what did or did not happen.

> **Normative.** No consumer composes an assertion of absence from an empty or
> short structured result — not to the owner, not into a record, and not into a
> plan. A surface reporting on such a read reports what it looked for and what it
> could not reach (§6), never that the thing did not occur.

**The two statements are compatible and it matters that they are.** ADR-0128 §2's
first clause is a real certification and this ADR does not weaken it: on a store
that reports `capped=False`, an empty structured result *does* tell a caller that
no record carries those labels in that window. What it cannot tell the caller is
anything about the world, and the gap between the two is exactly the size of the
unlabelled population — which, on the episodes today, is all of it. A consumer
that reads "no record carries the label `alex`" as "you never talked to Alex" has
made the inference §6's disclosure exists to prevent.

**And the store contract is where this belongs, because the store is where the
certification is issued.** ADR-0128 §6 leaves what a consumer does with `capped`
to that consumer; this clause is not a policy about what to do with an empty
result, it is a statement of what the result *means*, which is the store's to say
and nobody else's. The broadening the milestone contemplates is the planner's, and
as the Context records, ADR-0228 §2(e) does not fire a revision on a read that
returned nothing — so no lane may cite this section as evidence that the
broadening exists.

### 8. `occurred_at` is the instant of the exchange, not of the event

> **Normative.** `occurred_within` filters on the instant a record's `occurred_at`
> carries and on nothing else. On an episode this system captured, that instant is
> **the exchange's** — the turn's own `occurred_at`, stamped by capture — and not
> the instant of whatever the exchange was about.

> **Normative.** No consumer reads a window match as evidence about when the
> event discussed in a record happened, and no surface presents it as one. A
> surface answering a time-scoped question over captured episodes says which
> instant it filtered on wherever the distinction could mislead.

> **Normative.** This ADR adds no event-time axis and no second instant to any
> record. A read that filters on when something *happened*, as distinct from when
> it was *said*, needs the producer that records such an instant and its own ADR.

**Verified rather than asserted**: `ConversationRecorder._build_episode` writes
`occurred_at=turn.occurred_at`, and the turn's instant is the reading the recorder
"already carries" so that "the narrowing and the record of it cannot disagree
about when the turn happened" — its own words, about `placement.set_at`. That is
the right stamp for what capture knows and the wrong one for what a user means by
"the renovation last week" if the renovation was discussed a fortnight after it
happened.

**The milestone's first-slice exit survives the caveat, and that is why the caveat
is stated rather than treated as a blocker.** "What did we discuss about the
renovation last week" is a question *about the exchanges* — it asks when the
talking happened — so the exchange instant is the correct axis for it, not an
approximation of a better one. What the clause prevents is the next question
inheriting the assumption silently: "when did the boiler break" filtered on
`occurred_within` returns the conversations in that window, not the events, and a
consumer that renders the first as the second is wrong in a way no store can
detect.

### 9. What the implementing lane owes

This changes an existing Protocol **and** adds a new `core` type, so it is one
unit of work under ADR-0137 §2 — the triad's obligations plus the primary
production implementation whose demands shape the contract — and not a contract
landed alone with its tests to follow.

> **Normative.** The shared conformance suite gains, **for each of the four axes**,
> a case seeding enough **nearer ineligible** records to exhaust any plausible
> candidate budget and asserting that the eligible records come back in full. A
> case asserting only that no ineligible record is returned is satisfied by
> returning nothing and does not test §1 — ADR-0128 §5's clause, restated because
> it is the clause an implementation passes in name and fails in substance.

> **Normative.** Every axis case is written **once** and run against **both**
> reads, parametrised over the member rather than duplicated per member. Two
> bodies asserting one axis set is the drift §4 refuses, and a suite that
> reproduced it would be the instrument that failed to catch it.

> **Normative.** The suite pins, on both reads and on every implementation: the
> `None`/empty/duplicate convention on each sequence axis; conjunction across axes
> and disjunction within one; both ends of the half-open window and both refusals
> `TimeWindow` makes; §3's fold on both person axes; exact-character matching on
> `topics`; and that a record carrying no value on an axis is reached by no filter
> on it. It pins on `select` in addition: §5's order and cleared `score`, the
> refusal of a call applying no axis, and §10's `limit` cases — which are **not**
> inherited from `search`'s existing ones, because every one of those supplies a
> query and none of them executes this read's path.

1. **The contract** — `TimeWindow` in `core/types.py`, and in
   `core/protocols.py` both `MemoryStore.search`'s extended signature and the new
   `MemoryStore.select`, each with a docstring carrying §§1–8's semantics. Each
   `Args` block states the conventions rather than pointing at its sibling, which
   is ADR-0113 §3's own instruction and the reason it gives for it.
2. **The shared conformance suite** — `tests/memory/memory_store_contract.py`,
   with the clauses above beside ADR-0128 §5's existing crowding cases. The
   standing clauses bind unchanged on the new member too: cancellation (ADR-0060)
   and input observation (ADR-0065 §3).
3. **The canonical fake** — `FakeMemoryStore` in `ai_assistant.testing`, passing
   the extended suite. As ADR-0128 §5 records, it has no KNN and therefore no
   ceiling, so the case that bites lives in the SQL store's own tests.
4. **The primary production implementation** — `SqliteMemoryStore`, which is where
   §1 bites and which ADR-0213 §15's "storage a filtered record read needs"
   deferral fires on. Whether that is a column, a child table, an index or a
   migration is the implementing lane's, under the observable obligation §1 states
   and as ADR-0113 §10 and ADR-0128 §6 left the band's and the window's.
   `InMemoryMemoryStore` is implemented in the same change.
5. **No caller changes.** Every existing call site is preserved by the defaults;
   the lane adds none and rewrites none.
6. **No version moves.** Neither `search` nor `select` is on the promoted
   `AssistantEngine` surface — `select` adds a `MemoryStore` member, not an engine
   one — and `TimeWindow` crosses neither `wire/` nor `service/`, so under
   ADR-0124 §9 no frame a conforming peer may send changes and `PROTOCOL_VERSION`
   stays.
   `EXPORT_VERSION` likewise: no stored record gains a field. The lane verifies
   both against the tree of its day rather than against this sentence.

**The consumer that shapes the contract is the milestone's first slice**, and it
is not in this lane: a planner envelope kind carrying a time window, mapped onto
`occurred_within` (#1908's M30, `track:planning`). ADR-0137 §2's widening is about
the implementation whose demands shape the contract, which here is the store; the
planner lane rides behind the merged contract exactly as #1908 says its envelope
kinds do — "each is inert until `track:memory` has ratified the store read it maps
to".

### 10. The representative-input tests this decision owes

From #1874's list and #1908's M30 sharpening, each stated so a lane can build the
fixture rather than interpret a wish:

1. **Structure isolates.** Several conversations on one topic, all near in
   similarity; exactly one carries the asked person **and** falls in the asked
   period. A call conjoining `about_person` and `occurred_within` returns that one
   and no other, and it returns it with the distractors crowding the candidate
   budget — the fixture ADR-0128 §5 requires, built at a density that fails a
   post-cut filter.
2. **The first slice, end to end.** A time window over episodes **plus** the
   existing text query returns the week's renovation conversations and excludes an
   identically-worded conversation from the month before. This is the one arm
   today's captured data supports without any new producer.
3. **A caption is never the reason.** A record whose text is engineered to sit
   near unrelated questions is not returned by a read whose filters it fails, at
   any similarity. Run it on `select`, and again on `search` with a query the
   caption matches: the second is the arm that matters, because it is the one where
   similarity would have won.
4. **Wording shares nothing.** A question whose words appear nowhere in the stored
   record is answered by a filter over values the record carries.
5. **Missing.** A filter naming a value no record carries returns an empty result
   with `capped` `False`, and the suite asserts that the result is empty **and**
   that no unlabelled record leaked into it — the two failures §6 sits between.
6. **Ambiguous.** Two records match the same person and window; both are returned,
   in §5's order on `select`, and neither is preferred by any quantity.
7. **Unpopulated axes.** Over a store of captured episodes as they are written
   today, a `topics` or `participants` filter returns nothing, and the test asserts
   that as the *specified* behaviour rather than as a bug — the arm that will be
   inverted, deliberately, by the producer lane.
8. **The fold is D145's and not a lowercase comparison.** Four pairs on **both**
   person axes, because a `.lower()` implementation passes the obvious two and
   fails the rest. `"Marta"`/`"marta"` match; `"Marta"`/`"Márta"` do **not**;
   `"Straße"`/`"STRASSE"` **do**, which is full case folding and not lowercasing;
   and `"Márta"` against the same name written with a combining acute
   (`"Ma\u0301rta"`) **do**, which is the canonical equivalence the outer and inner
   `NFD` supply. The last two are what pin the rule; the first two alone do not.
9. **Both refusals, and the two calls that name nothing.** `TimeWindow()` and
   `TimeWindow(start=t, end=t)` each raise `ValueError`; `select()` applying no
   axis raises `ValueError`; an empty sequence on any axis returns an empty,
   uncapped result on both reads.
10. **`select`'s own `limit` boundaries**, asserted on this read and never inherited
    from `search`'s, since every existing limit case supplies a query and none of
    them executes this path. `limit=0` and `limit=-1` each return an empty,
    uncapped result; `limit=2**63` returns the whole eligible set and raises
    nothing — the case a store that binds `limit` straight into its query language
    fails while passing every other fixture here.
11. **The two reads are not each other.** One store, one fixture: `search` over a
    query with a window returns the nearest-first records of that window with
    `score` populated; `select` over the same window returns §5's order with
    `score` `None`. Asserted together, because the pair is what §4 decided and a
    reader of §5 will want to see it held.

### 11. Deferred, by name, each with what fires it

- **An event-time axis.** A filter on when something *happened*, distinct from
  when it was said (§8). **Fires** with the first producer that records such an
  instant — #1874's "ADR A" is the named candidate — and it owes the field before
  it owes the filter.
- **An order keyed on event time.** §5 orders `select` by
  `provenance.last_updated` for totality. **Fires** with the axis above, since an
  order over a field one kind carries needs either a kind-scoped read or a total
  fallback, and neither is worth deciding before the field exists.
- **A wider matching rule on either label axis.** Reserved by ADR-0101 §10 for
  person labels and by ADR-0213 §15 for topics, unchanged. **Fires** as those
  sections say, and as a supersession in the person case.
- **Enumerating the values a store holds on an axis** — "which topics do you have
  records about", "which people". Refused on ADR-0101 §10's ground, which applies
  unchanged: it is derivable from `export()` today, so a method would be surface
  over a derivation already in hand. **Fires** with the first surface that must
  offer discovery without handing over the whole export.
- **A structured `forget`, guard or export.** ADR-0213 §15 and #1720/#1719. This
  ADR supplies the read that section says such a lane owes and takes no part of the
  rest; ADR-0101 §1's clause that no lane may add a subject dimension to `delete`,
  `clear` or `purge_expired` binds unchanged. **Fires** as §15 states.
- **Any filter on `disposition` or `capture`.** ADR-0221 §14 rules that "no read
  returning records is filtered on it" for both fields, and this ADR adds no such
  axis. **Fires** with an ADR that reckons with that clause.
- **A negation or exclusion on any axis** — "not about Alex", "outside this
  window". No consumer asks for one, and an exclusion over an axis where absence
  means *unrecorded* has two defensible answers (does it admit the unlabelled?)
  that §6 would have to choose between. **Fires** with a consumer that needs one
  and can say which.
- **Reusing `TimeWindow` anywhere else.** It has one meaning at one site under
  this ADR. **Fires** with a lane that needs an instant window on another read and
  argues that the half-open, both-ends-refused shape is right there too; nothing
  re-expresses `Validity` in it.

### 12. Scope, and what this records against earlier ADRs

> **Normative.** This ADR supersedes nothing and amends nothing. Every ADR it
> cites binds after it exactly as it bound before, and no record is written on any
> earlier ADR's `Status` line or in any earlier ADR's note. No file outside this
> one changes in the lane that merges it.

The judgement ADR-0082 §1 requires is made here, clause by clause, against
ADR-0070 §1's test: *would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?* The four
places where the opposite reading is available are worked, because "absent a
clause that fails §1's test, there is nothing to record" and a reviewer is
entitled to see the showing rather than the conclusion.

**ADR-0128 §1's third clause is the one that has to be met head-on.** It reads:

> This moves **where** `search`'s read-time eligibility axes bind and changes
> nothing about what they mean or which instant they are read against. No axis is
> added, removed or relaxed: `search` gains no `include_retired` axis and no as-of
> axis, and the liveness it applies stays read-time-relative exactly as ADR-0045
> §6 has it and ADR-0079 §1 left it.

Every sentence of it stays true. Its subject is "this" — ADR-0128's own move — and
what it fixes is that *that* decision relocated predicates without touching what
they mean; the two axes it names by way of example are the two that would relax
eligibility (`include_retired`) or move the instant the axes are read against (an
as-of axis), which is what the clause's own second half is about. This ADR adds
neither. It adds **narrowing** filters over values already stored on the records,
it relaxes no existing axis, it removes none, it changes what no existing axis
means, and the liveness `search` applies stays read-time-relative and unamended.
A reader holding only ADR-0128 would refuse `include_retired` and an as-of axis
after this ADR exactly as before it, and would find every predicate it named still
binding before the cut, now joined by four more that also do. That is ADR-0082
§1's **stacked addition** — "adding an obligation that contradicts no sentence the
earlier ADR wrote … is recorded in the ADR that makes it, and nowhere else" — and
it is the same treatment ADR-0077 §9 and ADR-0079 §3 gave their own additions.

**ADR-0128 §2 is untouched in every particular, and the new member is the place to
show that rather than to assume it.** Its first clause fixes what *that* change did
— "No other `MemoryStore` member changes, `list_beliefs` is untouched, no other
`core` type is added, and the result carries no field beyond those two" — with the
same self-scoping subject as §1's third clause, and it stays true of ADR-0128: that
decision changed no other member and added no other type. This one adds `select`
and `TimeWindow`, changes no existing member but `search`, leaves `list_beliefs`
untouched in name, signature and meaning, and adds no field to
`MemorySearchResult`. §2's second clause is the one that has to be read carefully,
because it names a second member: "no second `MemoryStore` member **reports on a
`search` that has already returned**". `select` reports on no `search`. It is a
read of its own, issuing its own result with its own `capped` under §7, and a
caller learns nothing from it about a `search` it made — which is the under-service
back channel that clause forbids, and exactly what this member is not. `search`
still neither raises nor refuses because a read was capped, and no parameter on
either read selects a refusing or completeness-requiring mode. §2's fourth clause
already contemplates "a filter selecting nothing", so an empty sequence on a new
axis lands in a case it decided rather than one it did not foresee. §7 above states
what the certification covers; it narrows nothing about when `capped` is `False`.

**ADR-0113 §3 and §4 are the two clauses a first draft of this ADR did make false,
and the surface was changed rather than the clauses.** §3's convention — the
`None`/empty/duplicate rule and conjunction — is restated for four more axes
exactly as written, and its unmarked prose beside it ("an empty query with a band
selected is still nothing rather than 'the whole band'") stays literally true,
because `search` keeps a required `query` and a blank one still matches nothing.
§4's first normative clause — "Within the result of one call the order is relevance
alone, whichever bands are selected" — is the one that decided §4 of this ADR. An
earlier draft gave `search` an optional `query` ordering a query-less call by
`provenance.last_updated`, which would have made that sentence false for a reader
holding only ADR-0113 and owed an amendment on it. The architecture lens raised it
as a blocker on round 1 and it was right. Putting the query-less read on its own
member is what makes the clause true rather than merely narrow: after this decision
every `search` call still orders by relevance alone, and `select` is a member
ADR-0113 never spoke about. ADR-0112 §1–§2 are untouched for the same reason, and
§5 argues separately why a total order over an unranked set is not currency acting.

**ADR-0100 §6 and ADR-0101 §2–§3 are used at their stated scope.** ADR-0101 §10
records that ADR-0100 §6's reservation is lifted "only as far as comparison and
matching", and §3 above does comparison and matching and nothing else — no
resolution, no aliasing, no registry, no equivalence beyond the fold. ADR-0101 §9's
two clauses bind "neither operation", naming `export` and `delete_about`; `search`
is not one of them, and its existing composition with `kinds` and `bands` is
ADR-0113 §3's, unchanged. ADR-0100 §3's prohibition on excluding an unstated-subject
record from an answer about the owner is satisfied exactly as §6 above works it.

**ADR-0213 §7 is generalised in this ADR's text and not in ADR-0213's.** §6 above
states the rule for four axes; ADR-0213's own sentences are about `topics` and stay
true of `topics`. A reader holding only ADR-0213 reads §7 no more widely after this
decision: what they gain is a second document saying the same thing about three
other fields.

### 13. Marking, review and ratification

> **Normative.** This ADR is marked under ADR-0089: the block quotes above are the
> whole of what it obliges, and unmarked text is read to determine what a marked
> clause means and never supplies an obligation.

It decides `core/protocols.py` and `core/types.py` surface — a changed member, a
new one and a new type — so it owes **both** required lenses, adversarial and
architecture, under ADR-0015 §1, and it merges as its own PR, ratified before
anything implements against it (golden rule 5, ADR-0015 §5). The implementation
lane is briefed from the merged text.

## Consequences

**What becomes easier.** A caller can ask for the records of a period, a person or
a topic and get them, rather than getting the records nearest some text and hoping.
The milestone's exit becomes constructible: "several conversations on one topic,
only one matching the asked person and period" is a conjunction of two axes, and
the answer is decided by what the records carry rather than by what they say. The
retrieval that #1874 wants for an event — "found by when/where/what" — has a
contract to be written against, and the injection hazard that note names is
sidestepped structurally: a caption an adversary wrote is content the read returns,
never the reason it was selected.

**What becomes harder.** The store has more to bind before its cut, and on the SQL
implementation that is a storage question ADR-0213 §15 correctly says fires with
this read: `topics` is a tuple on a row, and a filter over it that binds pre-cut is
a column, a child table or an index, not a post-fetch comprehension. The suite
grows by four axes' worth of crowding fixtures, which are the expensive kind, and
runs each of them twice over. And `MemoryStore` now has three reads whose filter
axes overlap — `search`, `select` and `list_beliefs` — which is a surface a caller
has to choose within; §4 states the three-way test in one sentence so that the
choice is written down rather than inferred.

**What is inert on the day it merges.** Three of the four axes reach no captured
episode, because capture writes none of those values and ADR-0213 §6 forbids any
producer from adding them today. That is the honest state of the tree and it is why
the milestone's first slice is the time axis. A lane that reads this ADR as
delivering "which conversation involved Alex" has read it wrong: it delivers the
read that question needs, and #1908's M30 owes the producer separately.

**What would trigger revisiting this.** An event-time instant on a record (§11's
first deferral) makes §5's order and §8's caveat both look different. A consumer
that needs an exclusion, or a matching rule wider than the two borrowed here, fires
the deferrals that name it. And a measured store in which the pre-cut binding
cannot be made to hold on one of the four axes is ADR-0128 §1's own instruction:
the lane stops and brings back an ADR.

## Alternatives considered

**An optional `query` on `search` instead of a second member**, so that one method
carried the axes once and `query=None` meant "no similarity constraint". This ADR's
first draft took it, and it was wrong twice over. It would have made ADR-0113 §4's
"the order is relevance alone, whichever bands are selected" false of a `search`
call and owed an amendment on it; and it would have set `None` and `""` beside each
other on one argument with opposite meanings, so that a surface composing
`query=user_text or None` would silently ask for everything the filters admit
instead of nothing. §4 records the change and the clause that forced it. What the
optional argument bought — one statement of the axes — is paid for instead by §9's
requirement that the suite parametrise over the member rather than duplicate the
body.

**Refusing a blank `query` outright**, considered while the optional-`query` shape
was still on the table, so that `None` and `""` could not be confused. It is
ADR-0101 §1's shape and it would have been cleaner than the pair. Declined then
because ADR-0128 §2's fourth clause decides the blank-query case explicitly — "It
reports `False`, never `True`, where `search` matches nothing by construction: a
blank query, a non-positive `limit`, or a filter selecting nothing" — so making a
blank query unconstructable would make a reader holding only ADR-0128 act
differently, which is ADR-0082 §1's test failing on a clause this ADR has no need
to touch. Moot under §4's surface, and recorded because the reasoning is what keeps
a later lane from reaching for it.

**A sentinel selecting records with no stated subject**, so that "about the owner"
could be asked for directly — for instance admitting `None` as a member of the
`about_person` sequence. Declined in §6 on two grounds that point the same way: it
makes an absence into a queryable value, which is precisely what §6 rules an
absence is not, and on this axis it would spell the owner, which ADR-0100 §3
forbids in as many words. Omitting the argument is the ask, and it excludes
nothing.

**Two keyword arguments for the window** (`occurred_from`, `occurred_until`)
instead of a `TimeWindow`. Smaller — no new `core` type. Declined in §2 because the
three ambiguities it leaves open (which end is inclusive, what an inverted window
does, what an unbounded one does) are exactly what two stores would answer
differently, and `Validity` already shows the corpus's answer to the same shape.

**A purpose-specific name for the window type** (`OccurredAtWindow`, on
`QuietWindow`'s precedent). Declined: the parameter name `occurred_within` carries
the axis at the call site and the type carries only the shape, and §11's deferral
fences the reuse a generic name would otherwise invite.

**Byte-equality matching on `participants`**, leaving the D145 fold to
`about_person` alone, on the ground that ADR-0101 lifted ADR-0100 §6's reservation
for the subject axis. Declined in §3: it would put two answers to "are these the
same person label?" in one method, selected by which field the label sits in, and
ADR-0100 §6 itself names `participants` as the honest precedent for what
`about_person` is.

**A relevance order for `select`, computed from the filters.** Declined without
much hesitation: there is no query, so any such quantity would be invented by the
store, and ADR-0112 §2 grants no read weighting authority over any quantity. A
named total order is the whole of what §5 needs.

**Giving `select` an `offset` and making it a paged read**, on `list_beliefs`'
shape. Declined in §4: no consumer pages a retrieval into a turn's supply, `limit`
is the bound that matters there, and offset paging over a mutating store may skip
or repeat a record — accepted for an inspection surface (ADR-0073 §2) and not worth
inheriting for a read nobody pages. It is additive if a consumer ever needs it.

**Filtering on `disposition` or `capture`** — plausible-looking axes on the same
records. Declined because ADR-0221 §14 rules for both that "no read returning
records is filtered on it", and this ADR is not the instrument that changes another
ADR's ruling. §11 defers it with the condition.
