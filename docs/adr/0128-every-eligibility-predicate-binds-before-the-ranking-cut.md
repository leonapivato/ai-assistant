# 128. Every eligibility predicate binds before the ranking cut, and `search` reports when its ceiling bound the read

- Status: Accepted
- Date: 2026-08-10
- **Note (2026-08-10, UTC): ratified.** `Proposed` → `Accepted` after the
  required reviews came back green on the content this ADR merged with — both
  lenses, because this ADR decides `core` surface: adversarial **APPROVE with
  no findings** and architecture **APPROVE with no findings**, round 5, 1027
  lines net across 5 commits, churn `1.1×` (1147 touched), posted to PR #923 by
  `just ship`. The outcome is taken from that comment rather than from a
  report. The comment's `<!-- ship:e40ef140… -->` anchor is the pre-merge
  branch head, not an ancestor of `main` after the rebase-merge; identity was
  established through the tree rather than assumed — `e40ef140^{tree}` and
  `04600e10^{tree}`, the tip the PR merged as (2026-08-10T15:50:03Z), are both
  `8845e4d021b5`, the tree both review artifacts record. This edit takes
  `CONTRIBUTING.md` → "Trivial ADR edits"' exemption for the ratification flip
  and ADR-0015 §5's trivial-ADR exemption; beyond the `Status` token and this
  note, not one word below is edited. Filed as the fix for #925, whose standing
  review finding on PR #924 — correctly triaged there as outside that lane's
  fence — this discharges.
- **Durability clause.** Every reference below to ADR-NNNN is to its text as it
  stood at this ADR's base, `3dc22af`, not to its status on any later day. Every
  ADR this decision composes with reads `Accepted` there (or partially superseded
  in a scope this ADR does not touch), and no ADR stands `Proposed` on that tree
  but this one. Where a later ADR *changes* one of them, this ADR is read against
  the text quoted here and the later ADR's own record says what moved. The `Date`
  line above is this ADR's authoring date in this clone's `-0400` frame, the
  convention [ADR-0112](0112-currency-never-ranks-and-retrieval-orders-by-relevance.md)
  and [ADR-0113](0113-the-band-scoped-relevance-read-is-a-filter-bound-before-the-cut.md)
  both state for their own; the base named here is the anchor that does not move
  under either frame.
- **This is a contract change.** §2 changes `MemoryStore.search`'s return type in
  `core/protocols.py` and adds one model to `core/types.py`. Golden rule 5
  therefore applies: this ADR ships as **its own docs-only PR**, is reviewed while
  still `Proposed` — under **both** lenses, which `CONTRIBUTING.md` → "Report the
  review, then mark it ready" requires of "the ADR deciding that surface" — and is
  flipped to `Accepted` on merge (ADR-0015 §5). **No code changes with it.** The
  Protocol change, the conformance extension, the canonical fake, all three
  implementations, the restructured trace emission and the store-health reader are
  later lanes (§5).
- **Selected by the operator's re-ruling on #824** (2026-08-10), which dissolved
  the leg-8 telemetry trigger that ADR-0112 §7 and leg 7's exit ruling had left in
  front of this work, and chose from #457's menu: the indexed pre-filter, plus
  #457's under-service signal. Headroom is declined there because it moves the
  cliff; paging is declined because it owes a termination argument this shape does
  not (§4). Batch #922.
- **Takes ADR-0112 §7's third clause at its word.** That clause names two shapes
  as correctness remedies outside its measurement gate, "because neither iterates:
  a pre-filter that lets the KNN see only eligible rows, and an explicit
  under-service signal a caller can refuse on". This ADR takes both, and §8 shows
  clause by clause that it uses ADR-0112 as written rather than narrowing it.
- **Answers ADR-0112 §10 and ADR-0113 §8's second clause**, each of which
  declined to pre-authorise this surface and required a lane wanting it to bring
  its own ratified ADR under golden rule 5. This is that ADR.
- **Amends and partially supersedes four earlier ADRs**, each argued in §8 under
  ADR-0070 §1's test and recorded in ADR-0082 §1/§2's form: ADR-0007's
  Consequences post-filter caveat and ADR-0045 §6's `valid_from` placement
  sentence are **amended**; ADR-0113 §2's second normative clause and ADR-0120
  §7's #824 shortfall watch are **partially superseded**. ADR-0112, ADR-0119,
  ADR-0073, ADR-0079 and ADR-0050 owe nothing, and §8 shows why for each.
- **Closes #792** (ADR-0007's caveat is retired rather than corrected) and
  **#824** (its trigger is dissolved, its mitigation selected and recorded).
  **#457 stays open** until the implementing lane lands, because it reports a
  defect in the store and this ADR is the decision it was waiting for, not the
  fix. **Takes up #838's entitlement layer only**; its judged-sufficiency and
  metamemory layers stay parked and untouched (§6).
- **Refs** #457 (the problem statement), #824 (the trigger and its re-ruling),
  #922 (the batch), #799 (the instrument), #792, #411, #838, #829, #460, #805,
  #115.
  ADR-0112 (the remedy split and the measurement gate), ADR-0113 (the precedent
  this generalises), ADR-0007 §2 (the retention axis), ADR-0045 §6 (the validity
  window's read semantics), ADR-0073 §2 (the sibling read that already binds
  everything before its cut), ADR-0079 §1 (the ceiling this signal serves),
  ADR-0119 §3/§8 (the trace's observation rule and its retrieval counts),
  ADR-0120 §7/§9 (the diagnostic retired, and the offline pattern its job passes
  to), ADR-0015 §5 (contract-first), ADR-0070/ADR-0082 (the amendment records),
  ADR-0088 (citation form), ADR-0089 (normative marking).

## Context

### The trigger this waited on was dissolved rather than fired

Leg 7's exit ruling deferred #457's mitigation behind leg-8 telemetry showing a
real store developing topic-concentrated window closure, and ADR-0120 §7 built
the watch that would read it. The operator's re-ruling on #824 removes that
trigger, on three grounds recorded there: #799 answered the lab half already; the
watch's only consumer was this decision, so it "bought nothing but the chance to
never pay a cost that is mostly owed anyway"; and the inhabitation arc starts
daily accumulation, which is what manufactures concentrated closure, against an
exposure that is write-path correctness and therefore "wrong at any frequency".

That last ground is ADR-0112 §7's own, restated by the operator against the
issue's trigger rather than against the ADR's gate. The two are different
instruments and only one is dissolved: ADR-0112 §7's gate binds **headroom**
changes and is untouched here (§8).

### What the tree does today, and what ADR-0113 has already proved

`SqliteMemoryStore._search_sync` runs the vector KNN with `k = min(limit *
_RESULT_OVERFETCH, _VEC_KNN_MAX_K)` and then walks the returned rows applying
four predicates in order — `kind`, `expires_at`, `valid_until`, `valid_from` —
breaking at `limit`. The method's own comment records the consequence: a filtered
row "still counts against over-fetch". That is #457's mechanism verbatim, and
#792 records that ADR-0007's caveat, which describes the pass as carrying two
predicates, has described three since ADR-0045 §6 landed.

**The band is the one predicate that is not in that pass, and it is the
precedent.** ADR-0113 §2 ruled that the band binds before the cut, and the
implementing lane met it with a `v.rowid IN (SELECT rowid FROM records WHERE
json_extract(...) IN (...))` restriction on the KNN — no schema migration, no
indexed column, and `excluded_band` written into the trace as a literal zero
because the post-cut pass has no out-of-band candidate left to drop.

So the question #457 filed as needing "investigation rather than assumption" —
whether sqlite-vec can pre-filter at all — is answered on `main` and not by a
spike: **the pinned sqlite-vec applies `k` after a `rowid` restriction, and a
restriction whose predicate is a `json_extract` of the stored blob is in
production.** The three predicates this ADR moves are strictly easier than the
one already moved: `kind`, `expires_at` and `valid_until` are **columns** on
`records`, not JSON fields, and only `valid_from` shares the band's storage shape
(ADR-0045 §9).

### What #799 measured, and the structural fact behind it

The re-ruling reports #799's latency result as roughly 1.2 µs per record, and a
full eligibility pre-filter as measuring roughly free on an aged store. The
figure is the operator's; what makes it unsurprising is a property of the
backend that `tests/memory/test_aged_store_retrieval.py` states in its own
trip-wire comment and that anyone can check: **`search` is a linear scan of the
vector table, because `vec0` keeps no ANN index, so cost is affine in the
population.** A restriction that removes rows from the scan therefore cannot
make it slower in order, and a pre-filter is not defeating an index because
there is no index to defeat.

That is the whole latency argument, and it is worth stating structurally rather
than numerically: a measured number ages with the store and the machine, and the
claim this decision actually rests on is that pre-filtering does not change the
*shape* of the cost. #799's numbers are the evidence that it does not change the
constant either.

### The under-service signal is not a second decision — it is what the pre-filter makes free

#457 lists the signal as a separate option, and ADR-0112 §8 treats it as "the one
worth naming, because it is available at the lowest cost". Under a post-KNN pass
it is genuinely a second mechanism: the store would have to distinguish "the
eligible set ran out" from "the candidate budget ran out" while both look like a
short result.

Under §1 it is neither. Once every eligibility predicate binds before the cut,
every candidate the store ranks is eligible, so a short result has exactly two
causes and the store already knows which one it is: the eligible set was smaller
than `limit`, or the store's own candidate ceiling was. #838 names this the
**entitlement** layer and prices it exactly right — "exact: `m < k`, mechanical,
free". Leaving it unreported would mean the store computing the answer and
throwing it away, and every consumer that needs it guessing.

**And the consumers that need it exist.** ADR-0079 §1 re-founded `conflict_limit`
as a ceiling on the strength of a distinction retrieval can make — "retrieval
surfaced at most `conflict_limit` conflicts" versus "it surfaced more" — and is
explicit in §1 and §6 that it "cannot make retrieval exhaustive" and that closing
that needs "a new `MemoryStore` obligation — a Protocol change, so its own ADR
under golden rule 5". `MemoryIngestor._detect_conflicts` reads with
`limit=self._conflict_limit + 2` for exactly that probe, and its docstring
records that "what it never surfaced is invisible here". This ADR is what makes
it visible.

### What makes this a decision rather than an implementation detail

1. **It changes a `MemoryStore` return type** (golden rule 5). All three
   implementations and every caller move together, and their read semantics must
   be identical or consumers differ by backend.
2. **The predicates' placement is a ratified concession, not an oversight.**
   ADR-0007's Consequences, ADR-0045 §6 and ADR-0113 §2's second clause each
   record it, the last as a marked normative clause. Moving it is a change to the
   record and not a refactor, and ADR-0113's own Alternatives says so by name:
   ruling these three predicates before the cut was "rejected as outside this
   lane's fence … changing it is that issue's ADR and not a rider on this one".
3. **A signal invites a wrong shape.** The obvious richer answers — a count of
   what was filtered, an estimate of what exists, an escalation hook — are
   #838's *upper* layers wearing the entitlement layer's clothes, and #838's own
   design invariant is that entitlement "stays mechanical forever". What is on
   the contract has to be decided before an implementation picks.
4. **A diagnostic dies with the mechanism it watched**, and a figure that is zero
   by construction is worse than no figure. ADR-0120 §7's shortfall watch has to
   be ruled on here or it survives as a report field nobody can read (§3).

## Decision

### 1. Every read-time eligibility predicate binds before the ranking cut

> **Normative.** Every read-time eligibility predicate `MemoryStore.search`
> applies — the `kinds` filter, ADR-0007 §2's `expires_at` retention deadline,
> and **both** ends of ADR-0045 §6's validity window — binds **before** the
> ranking cut, joining the band predicate ADR-0113 §2 already binds there. An
> implementation may not let a record failing any of them consume the candidate
> budget the cut is taken from, and the records it ranks are the records eligible
> on every one of those axes. Where a store cannot bind one of them before its
> cut, the implementing lane stops and brings back an ADR rather than shipping
> the weaker form.

> **Normative.** This rules **where a predicate binds, not how large a page a
> caller gets.** `limit` still cuts, and a result holding `limit` records asserts
> nothing about whether the store holds further eligible records below the cut.
> The completeness a caller *does* get is stated in §2 and nowhere else.

> **Normative.** This moves **where** `search`'s read-time eligibility axes bind
> and changes nothing about what they mean or which instant they are read
> against. No axis is added, removed or relaxed: `search` gains no
> `include_retired` axis and no as-of axis, and the liveness it applies stays
> read-time-relative exactly as ADR-0045 §6 has it and ADR-0079 §1 left it.

> **Normative.** A candidate over-fetch is no longer required on a read whose
> eligibility predicates all bind before the cut, and reducing or removing one is
> **not** a headroom change: ADR-0112 §7's second clause gates a change that buys
> a *larger* candidate budget, and this buys none. An implementation may keep a
> margin. It may not reintroduce a post-cut eligibility pass, on that ground or
> any other.

**This is ADR-0113 §2's argument with its scope restriction removed, and the
restriction was a fence rather than a reason.** ADR-0113 §2 rests on the band
skew being unbounded and growing by design; its Alternatives records that ruling
the other three predicates the same way was declined "as outside this lane's
fence", not as wrong. The mechanism is identical — a nearer ineligible row
consuming a candidate slot the cut is taken from — and so is the failure: ADR-0113's
spike returned **zero** of four live assertions at a 49× band skew, and #799
established the same effect on the window axis as a threshold, 0% below a
filtered-neighbour density of `fetch_k − limit` and 100% above it.

**What makes the window axis the urgent one is that the system manufactures its
own skew.** Every `SUPERSEDE` leaves a window-closed record behind (ADR-0045
§4/§6), ADR-0110 §3 adds a second producer in a covered reading's absence, and
both are *topically concentrated* by construction: the records that crowd out a
belief are the retired versions of that same belief. A well-corrected topic is
therefore the topic whose retrieval fails first, which is the inversion #457
records — the failure mode grows with use, and grows fastest exactly where the
user has been most engaged.

**The exposure it closes is on the write path, and no frequency makes it safe.**
`MemoryIngestor._detect_conflicts` is built on this call, and
`DefaultMemoryPolicy`'s asserted-conflict gates (ADR-0050 §2) are predicates over
the conflict set they are handed — so an unsurfaced `USER_ASSERTED` conflict can
turn what should be an `ASK_USER` into a `SUPERSEDE`, the profile silently
committing a self-contradiction. That is ADR-0112 §7's own reasoning for placing
this remedy outside its gate, and this ADR does not need a new argument for it.

**It is stated as an observable obligation, not a mechanism**, as ADR-0113 §2 is
and for the same reason: the Context records that at least one mechanism exists
on the pinned dependency and is in production, and naming one here would ratify
a schema decision this ADR has no need to make. Whether `SqliteMemoryStore`
grows an indexed column or a migration is §6's, not this clause's.

**The fourth clause exists because the over-fetch will otherwise be read as
protected.** ADR-0112 §7's gate is worded as a list of moves — "raising
`_RESULT_OVERFETCH`, decoupling or lifting the KNN `k` cap to buy a larger
candidate budget, deepening the candidate scan …" — and a lane that reads the
list rather than the clause could conclude that `_RESULT_OVERFETCH` may not be
touched at all. §7's own sentence is that "what is gated is the bet, never the
mechanism that carries it", and the bet it gates is that a *bigger* multiple is
enough. Dropping a multiple whose whole purpose has been removed makes no bet in
either direction, and the measurement §7 gates on now exists in any case (#799).

**The sibling read already works this way**, which is the corpus's own evidence
that the shape is implementable and expected. ADR-0073 §2 binds `list_beliefs`
more strictly than `search` — "both filters and both read-time axes are applied
to the whole candidate set, the set is ordered, and only then is" the page taken
— on the ground that a row dropped after a paged enumeration's cut "drops a row
no later page returns". After this ADR the two reads differ in what they rank by
and no longer in when they filter.

### 2. `search` returns a result that says whether the store's ceiling bound the read

> **Normative.** `MemoryStore.search` returns a `MemorySearchResult` — one new
> `core/types.py` model carrying the ranked records and one boolean, `capped` —
> in place of a bare `list[MemoryRecord]`. No other `MemoryStore` member changes,
> `list_beliefs` is untouched, no other `core` type is added, and the result
> carries no field beyond those two.

> **Normative.** The under-service signal lives on `search`'s result and nowhere
> else. `search` does not raise or otherwise refuse because a read was capped, no
> parameter selects a refusing or completeness-requiring mode, and no second
> `MemoryStore` member reports on a `search` that has already returned. A lane
> wanting any of those owes its own ratified ADR under golden rule 5.

> **Normative.** Where `capped` is `False` **and the result holds fewer than
> `limit` records**, the store holds **no** further record matching the call's
> filters and passing its read-time eligibility axes: the result is the whole
> eligible set at the read instant, and a caller may act on that. Where `capped`
> is `True`, the store's own candidate ceiling bound the read short of `limit`
> and the store certifies nothing — a caller may not read the result as the whole
> eligible set.

> **Normative.** `capped` is `False` on every result holding `limit` records, and
> on such a result it certifies nothing: a full page never asserts that the store
> holds no more eligible records below the cut, however large or small the
> eligible set is and whether or not a ceiling was reached in filling the page.
> `capped` reports the store's ceiling, never the size of the eligible set.

> **Normative.** `True` is available on a result **shorter than `limit`** and
> nowhere else. On such a result `capped` is a refusal to certify and never a
> claim that more exists: an implementation reports `False` only where the first
> clause lets it certify and reports `True` wherever it cannot, including where
> its eligible set exactly meets its ceiling. It reports `False`, never `True`,
> where `search` matches nothing by construction: a blank query, a non-positive
> `limit`, or a filter selecting nothing. An empty result is not a capped one.

The illustrative model; the semantics above are the contract:

```python
class MemorySearchResult(BaseModel):
    """What one `MemoryStore.search` returned, and whether it was cut short."""

    model_config = ConfigDict(frozen=True)

    records: tuple[MemoryRecord, ...]
    capped: bool = False
```

`tuple` and `frozen=True` are `core/types.py`'s conventions for a value that
crosses the seam, not obligations of this decision; the ranked order is
`search`'s existing one, best first.

**The three clauses are separated because an earlier draft's two were
unsatisfiable together, and the correction is the substance of the field.** That
draft defined `capped` as `False` "exactly where the store considered every
record eligible under the call's filters" and, beside it, `False` "on every
result holding `limit` records". The adversarial lens gave the case: 5,000
eligible records, a 4,096-candidate ceiling and `limit=10`. The store fills the
page without having considered every eligible record, so the first clause
demanded `True` and the second demanded `False`, and no implementation could
satisfy both. What that draft got wrong is the thing the field is *for*: `capped`
is not a statement about how much of the store was examined, it is a statement
about whether a **short** result may be trusted as complete. A full page is
outside the question entirely, because a caller that got what it asked for is not
being under-served — and reading a full page as a completeness claim is the
mistake ADR-0113 §5's third clause already warns consumers off in the
band-scoped case.

**And on a short result `capped` certifies in one direction, which keeps it
mechanically decidable.** `False` is the claim and `True` is the absence of one,
so an implementation that cannot tell reports `True` and is conforming. That is
what makes the boundary case — an eligible set exactly meeting the ceiling, where
the result happens to be complete and the store cannot know it — a permitted
`True` rather than a defect to design around. The alternative, requiring
exactness in both directions, would oblige a store to prove a negative about rows
it never fetched, which is the second vector search ADR-0113's `excluded_band`
reasoning already refuses on the interactive read path.

**That latitude is confined to short results, and the confinement is the second
correction this section took.** The first revision granted the "report `True`
wherever you cannot certify" permission unscoped, which reached the full page —
where the previous clause *requires* `False` — so one call was simultaneously
obliged to report `False` and permitted to report `True`, and two conforming
stores could disagree about it. The adversarial lens caught it on the round after
the one that produced it, which is worth recording: both defects are the same
mistake in different clothes, reading `capped` as a claim about the store's
knowledge rather than as a warning attached to a short answer. On a full page
there is no warning to attach, so there is nothing to be uncertain about and
`False` is the whole of it.

**Wrapping the list is the point, not a cost of it.** #457's harm is that a
caller "silently believes it saw everything", and every shape that leaves the
bare list intact leaves the silence intact — an extra method the caller may not
call, an attribute on a list subclass nobody reads, a keyword that defaults to
the old behaviour. A return type that cannot be consumed without naming the
field is the one shape where forgetting the signal is a type error rather than a
silent wrong answer. That is a real ergonomic cost at four production call sites
and a large number of tests, and it is the cost being bought.

**ADR-0113 §1 refused a new `core/types.py` type, and the test it used is the
test this passes.** It rejected a composed per-band result for expressing "no
information a consumer cannot get from `band_of`". Here the information is not
otherwise obtainable by anyone: distinguishing a sparse answer from a truncated
one is precisely what #457 says nothing above the store can do, and ADR-0079 §6
says the same from the writer's side. A type that carries a fact only the store
holds is the case ADR-0113 §1's refusal implies rather than forbids.

**One boolean, and the reason is #838's own invariant.** The layered design
parks judged sufficiency and metamemory coverage above a mechanical floor and
rules that "entitlement stays mechanical forever — arithmetic failures must
never depend on model judgment to be noticed". A count of what was filtered, a
population estimate, or an escalation hint would each be an upper-layer quantity
on the entitlement layer's surface, and each would be a number this ADR would
have to define a meaning for across three implementations. A boolean has one
meaning and two states, and the clause above enumerates both.

**Why it is not an exception or a refusal.** ADR-0079 §1 refuses rather than
truncating, and the parallel is tempting. It does not carry: the writer refuses
because it holds evidence it would otherwise discard and can act on the whole of
it, while a capped `search` has served a correct prefix that many callers can
legitimately use — `tools/builtin.py`'s lookup wants what there is, and
`LoopEngine._retrieve` already has a degradation channel in
`TurnResult.memory_degraded`. Raising would move the policy into the store and
serve every caller the strictest one, which is ADR-0072 §5's third reason applied
to a different quantity.

**What a consumer does with it is not decided here** (§6). The signal is the
capability; the refusal, the degradation or the second query is the consumer's,
and ADR-0079 §1's ceiling and ADR-0113 §5's cross-call rules are the shapes those
consumers already work under.

### 3. The exclusion counts go structurally zero, the trace keeps its shape, and #824's watch is retired

> **Normative.** The `RETRIEVAL` trace keeps the count-per-predicate shape
> ADR-0119 §8 requires. `excluded_kind`, `excluded_retention` and
> `excluded_window` join `excluded_band` as **structural zeros** wherever the
> read reached a candidate set, written as literals rather than as counters that
> can only stay at zero, and all four stay absent together on the fault and
> short-circuit paths where no candidate set exists. No metric key is added,
> removed or renamed, and ADR-0119 §13e's vocabulary gate is not reached.

> **Normative.** ADR-0120 §7's #824 shortfall watch is **retired**: the offline
> report states no shortfall incidence and no window share, and `MeasureReport`
> carries no shortfall figure. ADR-0120 §7's other two diagnostics — the
> operation-latency summary and the stream-health counts — and §7's second
> normative clause stand unchanged, as does §2's counter-inconsistency rule.

> **Normative.** The question that watch stood in for — whether a real store is
> developing topic-concentrated window closure — passes to a **direct store-health
> measure**, read offline over the store rather than over the trace stream, in the
> pattern ADR-0120 §9 sets. This ADR ratifies no such measure: its figures, its
> population and its surface are its own lane's, and this clause authorises
> nothing beyond the direction.

**Keeping the four counts at zero is what makes the intervention legible**, and
that is a stronger reason than symmetry. #829's window turns on reading the trace
stream before and after a dated change. If the implementing lane dropped the
three keys, every trace before the change and every trace after it would fall in
different populations — ADR-0120 §7's population is defined as the traces
*carrying* those keys — and the before/after comparison the window exists for
would be unreadable at exactly the moment it matters. Held at zero, the same
population spans the intervention and the counters going to zero on a date **is**
the observation.

**And the zero is not the placeholder ADR-0119 §3 forbids.** §3's rule is that
"an absent key means *not observed* and never zero", aimed at a quantity the
event did not reach. `memory/traces.py` already worked this out for
`excluded_band` and the reasoning carries unchanged: the four counts decompose
the candidate set the same trace reports, so they stand or fall together, and a
key present only when non-zero would make "nothing was dropped" and "no candidate
set existed" the same record. A read that reached a candidate set reached all
four answers; three of them simply became zero by construction rather than by
counting.

**The watch is retired rather than redefined, and the choice is on the figures.**
ADR-0120 §7 defines a *saturated shortfall read* as one with `returned < limit`
and `candidates ≥ fetch_k`, and reports two numbers over it: the incidence, and
the window share `excluded_window ÷ (candidates − returned)`. Under §1 both
degenerate, and not by the same amount.

- **The share becomes identically zero**, because its numerator is a structural
  zero. §7 already excludes from the share a shortfall "that excluded nothing",
  which after §1 is every shortfall — so the share is not merely uninformative,
  it is undefined over an empty set.
- **The incidence stops measuring the store.** With every candidate eligible, a
  read can only fall short of `limit` when the candidate ceiling bound it, so the
  incidence becomes the rate at which callers ask for more than the backend's `k`
  ceiling — a fact about `retrieval_limit` and `conflict_limit`, not about
  accumulated closure. It answers a question nobody asked and looks like an
  answer to the one #824 did ask.

**A redefined watch would be strictly worse than the contract signal beside it.**
The only thing left to count is the ceiling case, and §2 reports that exactly,
per call, to the caller who can act on it, at the instant it happens. A rate over
the same event, read offline weeks later, is the same fact with the actionable
part removed — and ADR-0120 §7's own second clause already forbids substituting a
diagnostic for a measure, which is the only use a redefined watch would have.

**What is lost is real and is named.** ADR-0120 §7 recorded that the watch could
report incidence and not headroom, and §12 item 3 filed the emitter change that
would close it. After this decision neither is available from the trace stream at
all: an eligibility pre-filter removes the *evidence* of concentrated closure
along with its consequence, because the rows that would have been counted are
never fetched. That is the trade — the failure stops happening and stops being
observable in the same change — and it is why the third clause routes the
question to a measure that reads the store rather than the stream. A store-health
measure can see closure directly, which the trace never could; what it cannot do
is see it *through retrieval*, and after §1 there is nothing to see there.

### 4. No iterating remedy is taken, so no termination argument is owed

> **Normative.** This ADR takes no iterating remedy. It adds no paging
> continuation to `MemoryStore.search`, no cursor, no second pass, no escalation
> and no re-search, and nothing in it may be read as pre-blessing one. ADR-0112
> §7's fourth clause is therefore neither engaged nor discharged: it stands whole,
> and the termination argument it demands — against ADR-0050 §1's ratified
> rejection of an unbounded re-search and ADR-0079 §1's objection that such a
> sweep has no termination guarantee and depends on the store's read clock —
> remains owed in full by any later ADR that does iterate.

**#411 part 3 is adjudicated and not taken.** The issue calls paging the KNN "the
durable fix", and that framing is overtaken: it was written when the KNN's
candidate window was the thing standing between a caller and the eligible rows.
Under §1 nothing eligible is outside that window, so paging would buy only what
`limit` already buys — more rows past the cut — which is a paging feature and not
a correctness remedy. The part stays open on #411 as the feature it now is, with
its termination argument still owed if anyone wants it.

**#838's two-pass escalation is answered the same way and is worth naming
separately**, because #824's own design note called it "the leading candidate"
and observed that "the tripwire and the mitigation may collapse into one
mechanism". They do collapse — into the pre-filter, not into the two-pass. The
escalation's whole value is optimistic post-filtering with a fallback for the
queries near the threshold; §1 removes the threshold, so pass 1 is always right
and pass 2 never fires. Its known residue — that a genuinely sparse store
"escalates once to learn it" — is what §2's boolean reports for free.

### 5. What the implementing lanes owe

This changes an existing Protocol rather than adding one, so there is no new
triad — but `CONTRIBUTING.md` is explicit that the mechanical check does not
reach a change to an existing Protocol, so the obligation is stated.

> **Normative.** The shared conformance suite gains, for each predicate §1 moves,
> a case seeding enough **nearer ineligible** records to exhaust any plausible
> candidate budget and asserting that the eligible records come back in full. A
> case asserting only that no ineligible record is returned is satisfied by
> returning nothing and does not test §1.

> **Normative.** The suite asserts `capped` on **every** implementation in two
> cases: `False` on a result short of `limit` over an exhausted eligible set, and
> `False` on an ordinary full page. On an implementation that **has** a candidate
> ceiling it asserts two more: `False` on a full page drawn from an eligible set
> larger than that ceiling — the case an earlier draft of §2 made unsatisfiable,
> and the one a store conflating "examined everything" with "served the page"
> fails — and `True` where the ceiling bound the read short of `limit`. On an
> implementation with no ceiling those two are skipped rather than faked, because
> neither input is constructible against it, and it reports `False` throughout.

1. **The contract** — `MemorySearchResult` in `core/types.py`, and
   `MemoryStore.search`'s return type in `core/protocols.py`, with §§1–2's
   semantics in its docstring. The docstring's existing "That binds the band axis
   alone and promises no full page" paragraph is the one that must go, since §1
   moves what it describes.
2. **The shared conformance suite** — `tests/memory/memory_store_contract.py`,
   with the two clauses above and the boundary cases ADR-0045 §6 already requires
   for each window end, now asserted through a fixture that crowds rather than a
   balanced one. The standing clauses bind unchanged: cancellation (ADR-0060) and
   input observation (ADR-0065 §3).
3. **The canonical fake** — `FakeMemoryStore` in `ai_assistant.testing`, passing
   the extended suite. Note that it has no KNN and therefore no ceiling, so it
   reports `capped=False` always and cannot reach §1's failure mode: the case
   that bites lives in `tests/memory/test_sqlite_store.py`, which is what #457
   says and why it names a `SqliteMemoryStore` regression specifically.
4. **Both production stores** — `InMemoryMemoryStore` and `SqliteMemoryStore`.
   The SQL one is where §1 bites, and the regression #457 asks for — enough
   window-closed and other-kind *nearer* neighbours to hide an above-threshold
   same-kind conflict — belongs there, over #799's fixture, which already builds
   an aged store at a chosen closure fraction.
5. **Every caller** — `orchestration/loop.py`, `orchestration/retrieval.py`,
   `memory/ingest.py`, `tools/builtin.py` and `testing/writer.py` — unwrapping
   the result. None of them is obliged to *act* on `capped` by this ADR (§6).
6. **The trace emitter** — `memory/sqlite_store.py` and `memory/traces.py`, for
   §3's first clause.
7. **The store-health reader** — a later lane, under §3's third clause, which also
   removes `Shortfall` and `MeasureReport.shortfall` from `evaluation/_figures.py`
   and the report.

Whether that is one lane or several is the dispatcher's call; the contract half
must not land without its suite, and §1 must not land without the crowding
fixture, which is the clause an implementation can pass in name and fail in
substance.

### 6. What this ADR does not decide

- **What any consumer does with `capped`.** Whether `MemoryIngestor` refuses on
  it under ADR-0079 §1's ceiling, whether the per-band assembler degrades on it,
  and whether `LoopEngine` sets `memory_degraded` from it are those consumers'
  lanes. §2 supplies the fact, not the policy.
- **The store-health measure's design** (§3) — its figures, its population, its
  surface, and whether it reads the store directly or a walk over it.
- **Whether `capped` rides the trace as a metric.** ADR-0119 §3 makes a new
  number cheap and §13e does not gate one, so it is an emitter question and not a
  contract one. §3's first clause is about the four counts and takes no view.
- **#460 — the absolute, clock-coherence-independent hide guarantee.** §1 moves
  *where* the window and expiry predicates bind and changes nothing about *what
  instant* they are read against: liveness stays read-time-relative exactly as
  ADR-0045 §6 has it and ADR-0079 §1 left it. A pre-filtered predicate compares
  the same two instants the post-filtered one did.
- **#805 — band-read degradation policy.** A different failure (one band's read
  raising) with a different remedy, and `capped` is not it: a capped read
  succeeded.
- **#838's judged-sufficiency and metamemory layers**, and its retrieval-context
  escalation policy. Parked, untouched, and explicitly not authorised by §2's
  boolean.
- **#411 parts 1 and 2** — a construction-time bound on the search limit, a
  documented maximum on the contract, and decoupling `_VEC_KNN_MAX_K` from the
  pinned dependency. Part 2 is the one this decision makes *more* interesting,
  since §2's `capped` is defined against a ceiling whose value is version-coupled;
  it remains free-standing and any lane may take it.
- **Whether `SqliteMemoryStore` grows indexed columns or a migration** for the
  pre-filter. An implementation choice under an observable obligation, as
  ADR-0113 §10 left the band's.
- **Anything about eviction, size caps or retention policy.** ADR-0007 §5's
  deferral stands, as ADR-0103 §1, ADR-0112 §9 and ADR-0113 §10 each record.
- **Ranking.** ADR-0112 §1 and ADR-0113 §4 own the ordering axis; eligibility is
  the other axis and this ADR touches only it. No quantity is supplied and no
  place to put one is created.

### 7. Explicitly declined

**This section supplies no obligation of its own, and that is deliberate rather
than an oversight.** This is a marked ADR, so under ADR-0089 §3 the marked
clauses are the whole of what it obligates and unmarked text only says what a
mark *means*. Every refusal below that is meant to constrain a later lane
therefore lives in a clause above, and each entry names it; the rest is the
reasoning for a refusal, which ADR-0089 §1's conduct test leaves unmarked. An
architecture reviewer raised this list as under-marked and was right about four
entries: the refusal of a raising or `require_complete` mode and of a second
reporting member are now §2's second clause, the refusal of an `include_retired`
or as-of axis is now §1's second clause, and a documented maximum `limit` has
been struck from this list entirely because it is #411 part 1 — a question §6
leaves open, not one this ADR refuses, and listing a deferral among the refusals
was itself the error.

- **A headroom change.** §1's fourth clause. Nothing here raises
  `_RESULT_OVERFETCH`, lifts or decouples the KNN `k` cap, deepens a candidate
  scan or adopts hybrid retrieval; ADR-0112 §7's second clause is untouched and
  #799's measurement remains the warrant for any of them.
- **Paging the KNN, and two-pass escalation.** §4.
- **A richer signal than one boolean** — an exclusion count, a coverage estimate,
  an escalation hint, or a "there is more below the cut" flag. §2, on #838's
  entitlement invariant. The last is refused separately: it is not free, since
  answering it means looking past `limit`.
- **Raising on a capped read, or a `require_complete` keyword.** §2's second
  clause. It moves a consumer policy into the store and serves every caller the
  strictest one.
- **A separate status method beside `search`.** §2's second clause. Two reads
  racing each other to describe one read, and a caller may skip the second —
  which is the silence #457 is about.
- **Keeping the bare `list[MemoryRecord]` and reporting under-service only in the
  trace.** §2's first clause. The trace is read offline by a tool no subsystem
  may import (ADR-0120 §9); the caller that must refuse is in-process and in the
  turn.
- **Redefining ADR-0120 §7's watch rather than retiring it.** §3's second clause.
- **Dropping the three exclusion counts from the trace.** §3's first clause, on
  #829's window.
- **An `include_retired` axis, an as-of axis, or any relaxation of the read-time
  axes.** §1's second clause. `search`'s axes are ADR-0007 §2's and ADR-0045 §6's;
  this ADR moves where they bind and does not touch what they mean. ADR-0073 §3
  refused the retired axis on the sibling read, ADR-0113 §9 refused it here, and
  ADR-0045 §1 deferred as-of retrieval.

### 8. What this records against earlier ADRs

The judgement ADR-0082 §1 requires, clause by clause, applying ADR-0070 §1's
test: would a reader holding only that ADR now act differently, or read one of
its clauses more widely than it now holds? Four records are owed and each is
classified below; five ADRs that look like candidates owe nothing, and the
showing is given for each rather than asserted.

**ADR-0113 §2's second normative clause — partially superseded.** The clause
rules that "`kind`, `expires_at` and both window ends keep the post-cut placement
ADR-0045 §6 and ADR-0007 ratified for them, so an in-band record failing one of
those may still consume the candidate budget and a call may return fewer than
`limit` records while eligible ones exist". §1 above makes both halves false, and
an implementer holding only ADR-0113 builds a post-cut pass for three predicates
— acting differently, on a **marked** clause, which under ADR-0089 §3 is the
whole of what a marked ADR obligates. That is a change to what was decided and
not a stale phrase, so it takes the partial-supersession form and not an
amendment. **Everything else in ADR-0113 stands and is used as written**: §2's
*first* clause (the band binds before the cut) is generalised rather than
narrowed; §8's first clause (no headroom change) is untouched, since ADR-0113
still makes none; §8's second clause (no under-service signal, #457 not closed, a
lane wanting one owes its own ratified ADR) is a deferral discharged by exactly
the route it names, which ADR-0110 §13 distinguishes from supersession. §2's
scope sentence remains true of ADR-0113 itself — it still binds the band axis
alone — and §8's unmarked prose about where the residue falls goes stale without
binding anything (ADR-0089 §3). ADR-0113's `Status` takes the leading token with
the scope naming the clause, and a dated note records the move.

**ADR-0113 §5's third clause — nothing owed, and it is the near miss worth
stating.** It rules that "a consumer may not read a short band-scoped result as
evidence that the band holds nothing more", which reads as the opposite of §2's
`capped=False`. The two do not meet: §5's clause is about composing *across* a
turn's calls, and its ground is the id-preserving fold that moves a record
between bands between two reads — a race §2 does not touch, since `capped` is a
statement about one call at one read instant. A consumer reading three bands
still cannot conclude that a band holds nothing more, because the record it
missed may have moved. **No record owed.**

**ADR-0120 §7's #824 shortfall watch — partially superseded.** §7's first
normative clause rules that "the report carries three diagnostics beside the
measures: the #824 shortfall watch, the operation-latency summary, and the
stream-health counts". §3 above retires the first, so a reader holding only
ADR-0120 builds a diagnostic that no longer exists — acting differently, on a
marked clause. Scoped to the watch: §7's second clause, its other two
diagnostics, §2's counter-inconsistency rule and every measure in §§4–6 stand
untouched, and §12's inventory of what the emitters carry stays accurate because
§3's first clause keeps every key it names. §12 item 3 — the filed emitter change
that would let the watch read "approaching" — is spent rather than superseded:
the watch it would have served is gone, and §3 says what took its place.
ADR-0120's `Status` takes the leading token, scoped, with a dated note.

**ADR-0007's Consequences post-filter caveat — amended, and #792 closes.** The
bullet reads: "**Search inherits the existing expiry/kind post-filter caveat.** As
with the `kinds` filter, `search` applies the expiry predicate after the vector
KNN … so an over-fetch is used and remains a tracked limitation, not a
regression." After §1 the pass it describes does not exist. Applying ADR-0070
§1's test to what ADR-0007 **decided**: §1's four data-rights operations, §2's
read-time retention guarantee, §3's export snapshot and §4's tier scope are
untouched, and §2's guarantee is if anything strengthened — an expired record is
still never returned, and now never even ranked. The caveat is a **statement of
fact about the implementation at the time of writing**, not a rule; ADR-0112 §11
and ADR-0113 §11 each read it that way in terms ("the residue it describes … read
no more widely than it holds"), and #792 states the same, which is why #792 filed
a bookkeeping question rather than a defect. A fact that postdates the ADR is
ADR-0070 §1's second bucket, and a reader acting on ADR-0007 acts identically
before and after. **Amendment**, recorded as a qualifier on ADR-0007's plain
`Accepted` line and a dated note. #792 asked whether the caveat's two-versus-three
count owed a record; the answer this ADR gives is that the caveat is retired
rather than corrected, which closes the question in the only way that does not
leave a corrected description of a pass that no longer runs.

**ADR-0045 §6's `valid_from` placement sentence — amended.** §6 rules that
"`valid_from` is therefore filtered like `kinds` already are — in the post-filter
step, not the SQL pre-filter (§9)". §1 moves it. What §6 **decided** is the read
semantics — `get` and `search` hide a record on either end of the window, `export`
keeps it — and the placement clause is stated as the reason the rare end is cheap
to honour, inside a bullet whose ruling is that "the `valid_from` end is enforced,
not assumed away … the store must honour the contract regardless". That ruling is
untouched and its conformance obligation (boundary cases at each end) is
strengthened by §5's crowding fixture. A reader acting on ADR-0045 §6 — enforce
both ends at read time, keep them in `export` — acts identically. **Amendment.**
ADR-0045's `Status` carries the leading `Partially superseded by ADR-0080` token,
so under ADR-0082 §2 no qualifier is written on that line and the dated note is
the whole record. **This is the classification most open to being overturned, and
the way to overturn it is named**: ADR-0113 §11 characterised the same sentence as
"a ratified concession that `valid_from` may be filtered in the post-filter step",
i.e. as a permission rather than a description. A reviewer holding that reading
should move this record to the partial-supersession form; the record's substance
is identical either way and only its form moves.

**ADR-0112 §7, §8 and §10 — nothing owed, and this is the finding a reader would
most expect to go the other way.** §7's first clause (the measurement is leg 7's
obligation) is untouched and satisfied by #799. §7's second clause gates headroom
changes and this ADR makes none — §1's fourth clause shows the reduction is not
one, using §7's own "the bet, never the mechanism" test rather than an exception
to it. §7's third clause names both of this ADR's shapes as correctness remedies
outside the gate, by name; taking a permission as written narrows nothing. §7's
fourth clause is unengaged and stays whole (§4). §8's split of #457's option list
is honoured exactly — the two correctness options are taken and the headroom
option is left waiting — and §8's #411 adjudication is unchanged except that part
3's own framing has been overtaken by this decision, which is a statement about
an issue's prose and not about ADR-0112's. §10 forbids reading ADR-0112 as
pre-authorising new contract surface and requires "its own ratified ADR under
golden rule 5"; this ADR is that ADR, which is §10 working. **No record owed.**
Note that the #824 re-ruling dissolved a *trigger recorded on an issue*, not
ADR-0112 §7's gate; conflating the two would put an amendment on the wrong
document.

**ADR-0119 §3, §8 and §13e — nothing owed.** §8's second clause requires a
`RETRIEVAL` trace to carry "the count excluded by each read-time predicate
separately — retention, validity window, kind and band", and §3's first clause
adds that it carries what the read *reached*. §3 above keeps all four keys on
every read that reached a candidate set, so both clauses are satisfied literally;
what changes is the value, and a count becoming zero is not a key going absent.
§13e's vocabulary gate is not reached, since nothing is added or removed. §8's
*unmarked* prose — "ADR-0113 §8 leaves the post-KNN `kind`/expiry/window
predicates keeping their placement inside the read" — goes stale, and under
ADR-0089 §3 it supplies no obligation in a marked ADR. **No record owed.**

**ADR-0079 §1 and §6 — nothing owed.** §1 states that it "does not make retrieval
exhaustive" and that "a conflict retrieval does not return is a conflict nothing
in this path can act on"; both stay true of ADR-0079, which still adds no store
obligation. §6 routes the question here in terms — closing it "needs either a new
`MemoryStore` obligation — a Protocol change, so its own ADR under golden rule 5
— or SQL-side pre-filtering" — and this ADR takes both routes at once. A deferral
used by the route it names is discharged, not superseded. §1's ceiling behaviour
is unchanged and this ADR obliges no consumer to use `capped` (§6). **Deferral
discharged; no record owed.**

**ADR-0050 §1 and ADR-0073 §2 — nothing owed.** ADR-0050 §1's rejection of an
unbounded re-search is cited as a live constraint and is not reached, since §4
takes no iterating shape. ADR-0073 §2's stricter placement for `list_beliefs` is
cited as a precedent and is neither narrowed nor extended; `list_beliefs` is
untouched, keeps its enumeration semantics and its cleared `score`, and §2's
result type is `search`'s alone. **No record owed.**

**ADR-0072 §5, ADR-0112 §1, ADR-0110 §3, ADR-0045 §4, ADR-0007 §5, ADR-0103 §1,
ADR-0060, ADR-0065 §3 — nothing owed.** Each is cited as a reason, a mechanism or
a standing clause and read no more widely than it holds; none acquires an
exception and none loses one. In particular ADR-0072 §5's band- and
confidence-neutrality is affirmed rather than touched: this ADR supplies no
quantity and creates no place to put one, and eligibility is not ordering.

## Consequences

- **#457's mechanism stops existing rather than getting rarer.** A nearer
  ineligible row can no longer consume a candidate slot, so the failure that grows
  with use — and grows fastest on the topics the user has corrected most — is
  removed rather than pushed one denser store further out. That is the difference
  ADR-0112 §7 draws between a correctness remedy and a headroom change, and it is
  why this lands without a frequency behind it.
- **The write path can finally tell the two short answers apart.** ADR-0079 §1's
  ceiling has always been a ceiling on what retrieval *showed*; `capped` is the
  first thing on the contract that says whether what it showed was everything.
  Nothing is obliged to use it yet, which is deliberate — the fact lands before
  the policy that reads it.
- **Every `search` call site changes, and that is the cost being bought.** Four
  production callers and a large body of tests unwrap a result instead of
  indexing a list. A cheaper shape existed at every point and each of them left
  the signal skippable.
- **Retrieval telemetry gets quieter and the store gets louder.** Three of the
  four exclusion counts go to zero on a dated change — legible in #829's window
  precisely because the population does not move — and the diagnostic built on
  them is retired. What replaces it reads the store, not the stream, which is a
  better instrument for the question and a worse one for the read path, and §3
  says so rather than claiming the swap is free.
- **`MemoryStore.search`'s contract gets longer and its implementations get
  simpler.** The over-fetch, its clamp, the four-predicate walk and the
  break-at-`limit` prefix all stop being load-bearing; what replaces them is one
  restriction and a comparison. The arithmetic #411 and #115 both record — the
  effective multiple shrinking past `limit > 512` — stops having a consequence,
  though the constant it is made of stays version-coupled (#411 part 2).
- **Two issues close on this merge and one does not.** #824 closes, its trigger
  dissolved and its selection recorded; #792 closes, its caveat retired rather
  than corrected. #457 stays open until the store actually pre-filters, because a
  decision is not a fix.
- **A future paging remedy is more expensive than it was**, and correctly so.
  ADR-0112 §7's fourth clause stands unengaged, so the termination argument is
  still owed in full — and after §1 the case for paging has to be made as a
  feature rather than as a correctness fix, which is a harder case and the honest
  one.
- **Revisit if** a `MemoryStore` implementation appears that cannot bind an
  eligibility predicate before its cut — §1's clause says it stops and brings back
  an ADR, and that ADR is the revisit; if a consumer needs to distinguish
  *why* a read was capped, which would be the first real pressure on §2's single
  boolean and #838's upper layers arriving; if the store-health measure (§3) shows
  closure concentration that the pre-filter does not in fact absorb, which would
  mean the failure was never only retrieval's; or if #411 part 2 lands and the
  ceiling `capped` is defined against stops being a constant.

## Alternatives considered

- **The pre-filter without the signal.** Rejected in §2 and in the Context. It is
  the cheaper half and it leaves the residual ceiling case silent — the same
  silence #457 is about, on a smaller population. It would also throw away a fact
  the store computes for free, and would leave ADR-0079 §6's routing open with no
  owner.
- **The signal without the pre-filter.** Rejected. It is what ADR-0112 §8 called
  "available at the lowest cost", and under a post-KNN pass it is honest but
  useless: a caller told "you were under-served" on a well-corrected topic can do
  nothing but raise `limit`, which is the headroom bet ADR-0112 §7 gates. The
  signal is worth having because the pre-filter makes the answer *rare* as well
  as exact.
- **A two-pass escalation — post-filter optimistically, escalate on `m < k`.**
  Rejected in §4. It was #824's leading candidate and #838's design centre, and
  §1 removes the regime it optimises for: with no post-filter there is no
  threshold to be near, so the second pass is dead code with a latency profile.
- **Paging the KNN (#411 part 3).** Rejected in §4. It owes the termination
  argument ADR-0050 §1 and ADR-0079 §1 between them demand, buys only rows past
  the cut once §1 lands, and would be the first iterating shape on this contract.
- **Raising `_RESULT_OVERFETCH` or lifting the `k` cap.** Rejected in §7 and by
  ADR-0112 §7's second clause, which #799's existence does not repeal — the
  measurement is the warrant for a headroom change, not a licence for one. It also
  moves the cliff rather than removing it, which is the operator's own ground on
  #824 for declining headroom.
- **A `SearchStatus` method beside `search`, or a keyword defaulting to the old
  return.** Rejected in §7. Both leave a caller able to not ask, and one of them
  races itself.
- **Raising `MemoryStoreError` on a capped read.** Rejected in §2. It reads well
  against ADR-0079 §1's refusing ceiling and does not carry: the writer refuses
  because it holds evidence it would discard, while a capped `search` has served
  a usable prefix, and callers like `tools/builtin.py` legitimately want it.
- **A richer result — counts, a coverage estimate, an escalation hint.** Rejected
  in §2 and §7 on #838's own invariant that the entitlement layer stays mechanical.
  Every extra field is a quantity three implementations would have to agree on and
  a door into the layers #838 parks.
- **Redefining ADR-0120 §7's watch over the ceiling case instead of retiring it.**
  Rejected in §3. The only surviving population is one §2 reports exactly, per
  call, to a caller who can act on it; a rate over it read weeks later is the same
  fact minus the action, and ADR-0120 §7's second clause forbids the one use it
  would have.
- **Dropping the three exclusion counts from the `RETRIEVAL` trace, since they can
  only be zero.** Rejected in §3. It would split ADR-0120 §7's population across
  the very change #829's window exists to read, and it would make "nothing was
  dropped" and "no candidate set existed" the same record — the reasoning
  `memory/traces.py` already applies to `excluded_band`.
- **Deferring until a consumer needs `capped`.** Rejected. The consumer exists —
  `MemoryIngestor`'s conflict detection, which ADR-0112 §8 names as the signal's
  first — and golden rule 5 requires the contract to merge before anything
  implements against it, so deferring produces an implementation lane that stops
  mid-flight rather than a better-informed decision. This is ADR-0113's own
  argument against deferring its parameter, and it applies with more force here
  because the store must be changed anyway.
- **Bundling the store-health measure into this ADR.** Rejected in §3 and §6. It
  reads the store rather than the trace stream, adds no contract surface, and is
  a different lane's decision under ADR-0120 §9's pattern; putting two decisions
  behind one ratification would give the second no review of its own — ADR-0113's
  reason for not bundling the under-service signal with its band filter.
