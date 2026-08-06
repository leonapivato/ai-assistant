# 112. Currency never ranks: retrieval orders by relevance, and leg 7's retrieval obligation is a measurement

- Status: Proposed
- Date: 2026-08-06
- **Durability clause.** Every reference below to ADR-NNNN is to its text as
  merged on 2026-08-06, not to its status on any later day. Every ADR this
  decision composes with reads `Accepted` (or partially superseded in a scope
  this ADR does not touch) as of that date, including ADR-0110 and ADR-0111,
  whose ratification landed while this lane held; `CONTRIBUTING.md` → "Trivial
  ADR edits" and ADR-0070 §1 both class a status flip as recording a
  ratification rather than deciding one, so no clause cited here moved with
  theirs and none moves with a later one. Where a later ADR *changes* one of them,
  this ADR is read against the text quoted here and the later ADR's own record
  says what moved.
- **This is leg 7's fork 5** (#729), and the last of that leg's forks to be
  decided. It rules **whether and how currency reaches retrieval** — the question
  [ADR-0103](0103-confidence-is-two-quantities-evidence-and-currency.md) §8 routes
  here by name — and it scopes, without designing, the leg's retrieval
  performance obligation. It decides no parameters and lands no implementation.
- **Decides no `core` surface.** No `core/protocols.py` change and no
  `core/types.py` change: §1 leaves `MemoryStore.search` exactly as ADR-0072 §5
  ruled it, and §10 rules that a lane concluding it needs new surface owes its own
  ADR. Golden rule 5 is therefore not triggered and no triad is owed, so the
  required review set is **adversarial alone** — the reading `CONTRIBUTING.md` →
  "Report the review, then mark it ready" states ("adversarial alone for most
  changes; adversarial *and* architecture for a contract-surface one … or when it
  is the ADR deciding that surface"), and the opposite of the reading
  [ADR-0110](0110-a-covered-readings-absence-closes-a-window-and-a-clock-never-does.md)'s
  header records for itself.
- **Discharges [ADR-0103](0103-confidence-is-two-quantities-evidence-and-currency.md)
  §8's routing** — "Whether and how currency reaches retrieval … is the
  retrieval-ranking lane's decision, and that lane's ADR states which shape it
  takes and what ADR-0072 §5 costs under it" — with the answer: through the
  validity machinery and presentation only (§1), and ADR-0072 §5 costs nothing
  because nothing here touches it.
- **Discharges [ADR-0110](0110-a-covered-readings-absence-closes-a-window-and-a-clock-never-does.md)
  §9's first deferral** — "Whether currency reaches retrieval, and how" — for the
  same question from the other side.
- **Answers #663's fired revisit trigger** (ADR-0072 §5, §10) in both its halves:
  the `ATTESTED`-above-`DERIVED` ordering stands unqualified (§4), and §5's
  per-band precedence is confirmed ruled-and-unimplemented, with the reason it is
  unimplemented named and routed (§5).
- **Amends and supersedes nothing.** §11 applies ADR-0070 §1's test clause by
  clause to every ADR this decision touches — ADR-0072 §5 and §6, ADR-0103 §8 and
  §9, ADR-0110 §8 and §9, ADR-0074 §6 and §11, ADR-0007 §5 and its Consequences,
  ADR-0006 §5 — and finds nothing owed. No ADR's `Status` line is edited.
- **Refs** #663, #457, #411, #729. **Files** #789 (the exit instrument, §7),
  #790 (the band-scoped relevance read, §5), #791 (episodic recall's residue, §9)
  and #792 (ADR-0007's post-filter caveat, §11).

## Context

Leg 7's exit test is that "months of use make retrieval better, not slower"
(`docs/roadmap.md`), and fork 5 is the fork that names retrieval directly. It
arrives last of the leg's forks, and by design: every other fork has already
taken ground it would otherwise have had to guess at.

### The fork's original shape was falsified before it was dispatched

#729 proposed fork 5 as "ranking is similarity × currency × band weight". The
operator's own objection on that issue withdrew it against ADR-0072 §5, which
rules `MemoryStore.search` "band-neutral and confidence-neutral" and gives three
reasons — a product of two axes recovers neither, a store that quietly down-ranks
derived beliefs starves the loop those beliefs improve through, and the weighting
would be invisible at the seam where it matters. The proposed shape breached all
three: it is a product, it applies band weighting inside retrieval, and it moves
precedence out of the consumer.

ADR-0103 §8 then recorded the same finding from the confidence lane's side, and
converted the fork from a settled shape into a three-way choice this ADR must
make explicitly:

> Whether and how currency reaches retrieval — through fork 4's validity
> machinery, through composition above the store seam, or through ranking inside
> `MemoryStore.search` — is the retrieval-ranking lane's decision, and that lane's
> ADR states which shape it takes and what ADR-0072 §5 costs under it.

### One of the three choosables has since been built out, and it is not this ADR's

ADR-0110 decided what "acting through fork 4's validity machinery" *consists of*,
and did it without taking any of the three shapes (its §9 says so). Its §1 rules
that a window closes only on a warranting event and that elapsed time is never
one; its §8 rules that a lapse **seeks a confirming event and never retires**,
band by band — re-confirmation with the user for `ASSERTED`, a re-read of the
source for `ATTESTED`, and for `DERIVED` "neither: nothing is asked and nothing
is closed".

So the content of shape 1 is now known rather than assumed, including its
honest gap: a lapsed `DERIVED` belief keeps its standing, its window, its band
and its place in every result set, and what it gets is ADR-0103 §9's last clause
— a surface that renders it conveys the lapse alongside its evidence-strength.
Choosing shape 1 is choosing that, and this ADR says so rather than letting a
later lane discover it (§6).

### Nothing on `main` ranks by anything but relevance, and nothing composes by band

Both halves matter, and only the first is what a reader expects.

**Ranking.** No code in `src/` multiplies a similarity by anything.
`SqliteMemoryStore` orders by the vector distance the KNN returns and scores
`1.0 - distance`; the fake store scores by term overlap and sorts on it. Both
are relevance and nothing else: no second quantity is mixed in, and outside each
store's own ordering a record's `score` is read only as a *threshold* in conflict
detection (`memory/ingest.py`, `testing/writer.py`), never as a ranking factor. `presented_confidence` in
`orchestration/engine.py` computes a number for display and its docstring pins
the reason it is safe: "`MemoryStore.search` stays confidence-neutral (ADR-0072
§5), so retrieval order is untouched by a value computed at the moment of
display." ADR-0072 §5 is, today, a rule the code obeys exactly.

**Composition.** ADR-0072 §5's *other* half — "the consumer therefore reads per
band and composes, rather than reading once and sorting" — has no implementation.
`orchestration/loop.py`'s retrieval stage makes a single band-neutral call,
`search(query, limit=self._retrieval_limit, kinds=BELIEF_KINDS)`, and passes the
records on. Nothing partitions them, nothing orders `ASSERTED` before `ATTESTED`
before `DERIVED`, and no budget is filled per band. #663 reported this in
December's terms and it is still exactly true. §5 below finds the reason, and it
is not a lane's oversight.

### The leg's own instrument does not exist

The roadmap states leg 7's exit test as "measured in this leg, as retrieval
latency and k-shortfall against a synthetically aged store", and hands the "not
noisier" half to leg 8 because "a claim this leg has no instrument for is one it
would assert rather than test". There is no such instrument on `main`: no
benchmark tree, no aged-store fixture, no `pytest-benchmark`, and outside this
ADR the only occurrence of "k-shortfall" in the repository is the roadmap line
that asks for it. Every
timing assertion in `tests/` is a liveness bound that explicitly disclaims being
a latency measurement.

That absence is what makes the tuning questions on this fork undecidable today.
#457 records that `SqliteMemoryStore.search` can under-serve conflict detection
because kind, expiry and validity-window filters all run *after* the vector KNN
and a filtered row still consumes over-fetch headroom; #411 records the
constants that bound it (`_RESULT_OVERFETCH = 8`, `_VEC_KNN_MAX_K = 4096`, the
effective multiple shrinking past `limit > 512`). Both issues offer option lists.
Neither can be chosen between without knowing how often the shortfall bites at
volume — which is the measurement this leg owes anyway.

### What makes this one decision rather than four

The ranking question, #663's ordering question, the per-band composition gap and
the performance obligation look like four topics. They are one, because the
answer to the first determines the other three: once currency is refused a place
in the order, the ordering axis is relevance alone, and every remaining
retrieval-quality question at volume becomes a question about *what is read and
composed* and *how short the read runs* — neither of which is a ranking question,
and both of which want the instrument this leg is already committed to building.

## Decision

### 1. Currency acts on standing and on presentation, and never on rank

> **Normative.** Currency does not order retrieval. `MemoryStore.search` remains
> band-neutral and confidence-neutral exactly as ADR-0072 §5 ruled it, and a
> consumer assembling context does not order records by currency either — not
> across bands and not within one. Neither currency nor evidence-strength is a
> term in any ordering, score, weight or cut applied to retrieved records.

> **Normative.** The two places currency acts are ruled elsewhere and are not
> widened here: it acts on **standing**, through ADR-0110 §8's seeking of a
> confirming event, whose outcome may then close a window; and it acts on
> **presentation**, through ADR-0103 §9's last clause and ADR-0072 §6. A lane
> finding a third place for it to act owes its own ADR.

This is shape 1 of ADR-0103 §8's three, and it is taken because it is the only
one under which all three of ADR-0072 §5's stated reasons survive untouched —
but the reason it is *right* rather than merely cheapest is narrower than that,
and it is ADR-0110 §1's.

**A rank penalty on lapse is a clock acting, and the corpus has already refused
that mechanism twice.** ADR-0103 §4 refused letting elapsed time retire an
assertion because doing so "would reach the same outcome through a mechanism with
no signal at all, which is worse, because nothing observed anything". ADR-0110 §1
generalised the ground past `ASSERTED`: "a clock is no more of a signal about a
calendar entry than about a preference", and "what differs across bands is not
whether time is evidence — it never is". A belief pushed below the retrieval cut
because a timer expired has been acted against on exactly that non-signal. It
reaches a *softer* outcome than a window close, which is why it is tempting; it
reaches it by the same mechanism, which is why it is refused. The corpus's answer
to staleness is a warranting event, and this ADR does not add a second answer
that needs none.

**And what the softer outcome costs falls hardest where the system can least
afford it.** ADR-0072 §5's second reason is that a store which quietly down-ranks
derived beliefs "starves the loop that is the only way they ever improve", and
ADR-0103 §8 already records that this reason "reads on currency with more force,
not less". A stale derived belief is precisely the record the user most needs to
be shown, because being shown is the whole of its correction affordance
(ADR-0072 §1, §6). An ordering that hides it is an ordering that makes the model
wrong for longer and quieter.

### 2. In-store ranking is refused, and the price it would have had to pay is stated

> **Normative.** This ADR does not supersede or amend ADR-0072 §5, in whole or in
> part, and grants `MemoryStore.search` no weighting authority over any quantity.

The shape ADR-0103 §8 names as "ranking inside `MemoryStore.search`" is available
at a stated price, and the price is not #663. Citation discipline matters here
because two different permissions are easy to confuse:

- **#663 fires only the *ordering* half.** ADR-0072 §5 scopes its own revisit to
  the `ATTESTED`-above-`DERIVED` ordering — "the least-evidenced part of this
  decision", "revisited when the first real sensor exists (§10)" — and that is the
  trigger #663 records as fired. It licenses revisiting *which band outranks
  which*, and nothing about weighting.
- **The *weighting* half's only door is ADR-0072's Consequences**: "A future
  proposal to weight retrieval by confidence has to supersede §5 rather than
  arrive as a tuning change." That is an open invitation with a named price — a
  supersession — and it is what a shape-3 ADR would have to cite.

This ADR declines to pay it, on three grounds, the third of which is decisive
today and the first two of which outlive it.

**A product still recovers neither axis, and renaming the multiplicand changes
nothing.** ADR-0103 §8 settled this in terms: §5 "is a rule about **what the
store's ranking may mix**, not about which field's name is on the multiplicand".
Currency is a different quantity from evidence-strength, and it is not a different
*kind* of quantity from the standpoint of §5's first reason.

**Precedence would leave the consumer, and §5 put it there for a reason that has
not changed.** The consumer is the only component that knows the budget it is
filling and the turn it is filling it for. A store that pre-applies precedence
serves every caller the same compromise and, per §5's third reason, does it
invisibly at the one seam where the behaviour matters.

**There is no currency value to rank on, and the gap is not transient.**
ADR-0103 §9 rules currency's domain to carry an explicit **unknown**, distinct
from every value it can take, and rules that "a belief whose confirmation instant
the store does not hold — which is every record written before this decision —
reads as unknown, and never as current". It also forbids the other invention:
reading such a record as stale "would manufacture a decline from a rate nobody
has measured". An ordering has to place unknowns *somewhere*, and both placements
are refused by name — last treats unknown as stale, first treats unknown as
current. There is no third position that is not one of those two in disguise. And
the gap does not age out: ADR-0103 §9's third constraint forbids a migration that
"fabricates a currency decline that was never measured", so a pre-ADR-0109 record
carries unknown currency until something actually confirms it, which for a
`DERIVED` belief means a new observation and for an `ASSERTED` one means the user.

That third ground is worth stating even though the first two would suffice,
because it is the one that would otherwise be discovered by an implementation
lane at the point of writing the comparator — the point at which the cheapest
available answer is to invent a placement and call it a tuning detail.

### 3. Composition above the seam is refused too, and this is the part §5 did not already decide

> **Normative.** A consumer assembling context does not order or cut records by
> currency within a band. ADR-0072 §5's per-band precedence is composed on the
> band and on relevance alone.

Shape 2 is the one that looks free. It touches no store, breaches no sentence of
ADR-0072 §5 — §5 rules what the *store* may mix and where precedence lives, and
says nothing about within-band ordering — and it puts a legitimately declining
quantity to work in the one component §5 trusts with ordering. It is refused
anyway, and refusing it is the substantive half of §1 rather than a corollary of
it, because §5 genuinely left this open.

**The ground is that ADR-0110 §8 enumerated what a lapse does, and this is not on
the list.** For `DERIVED`, §8 rules that a lapse "closes no window, lowers no
evidence-strength (ADR-0103 §3), and changes no band (ADR-0072 §4)", that nothing
is asked, and that what a lapsed derived belief gets is a surface conveying the
lapse. Ordering it below a fresher sibling would be a fourth consequence — and,
uniquely among the four, the one that removes the belief from the user's view.
ADR-0110 §9 is careful that it "takes none of the three shapes", so §8's list is
not a rule that forecloses shape 2; it is the corpus's fully-worked answer to
what a lapse warrants, arrived at without reference to retrieval, and shape 2
would append to it the one item §8's own reasoning most argues against. ADR-0110
§8's `DERIVED` paragraph gives that reasoning directly: closing a derived belief
"would be worse on two ratified counts", ADR-0072 §1's re-derivability and
ADR-0103 §1's warrant requirement, and a within-band demotion is those two counts
applied at lower amplitude, not avoided.

**The second ground is §2's third one, unchanged.** A within-band order by
currency needs a currency to order by, and ADR-0103 §9's unknown has nowhere to
sit in a total order. Nothing about moving the comparator above the store seam
supplies the value the store did not have.

**And the flood problem shape 2 is offered to solve is not a currency problem.**
The failure ADR-0072 §5 names — "a flood of low-confidence inferences can displace
an assertion *below the cut*" — is real and is getting worse as leg 3's observer
lands, but §5 also states its own fix, which is per-band composition, and that fix
is unbuilt (§5 below). Within-band currency ordering would not implement it: a
flood of *fresh* derived beliefs displaces an assertion below a band-neutral cut
exactly as a flood of stale ones does. Shape 2 addresses the ordering of what
survives the cut; the corpus's stated failure is what does not.

### 4. #663's ordering question, answered: the `ATTESTED`-above-`DERIVED` ordering stands

> **Normative.** ADR-0072 §5's band precedence — `ASSERTED`, then `ATTESTED`, then
> `DERIVED` — is affirmed as ruled, unqualified. No recency, currency or staleness
> qualification attaches to it.

#663 records the trigger ADR-0072 §5 set for itself as fired: `readers/calendar.py`
carries a working `CalendarReader` on `main`, so "the first real sensor exists"
and the `ATTESTED` band has a producer. The trigger having fired obliges an
answer, not a change, and the answer is that the ordering survives — and survives
on stronger ground than it was ruled on.

**#663's stated worry has inverted since it was filed.** Its question 1 asks
whether `ATTESTED`-above-`DERIVED` "survives contact with a band whose staleness
is undetectable by construction", pointing at `CalendarReader` setting
`SourceReading.as_of=None` — which it still does, deliberately and with the
reason in a comment: "a local `.ics` declares no reading-level as-of". That much
is unchanged. What has changed is everything around it. The `ATTESTED` band now
has three ways for a belief to stop being live without the user: ADR-0080 §1's
clamp to the producer's own declared end, ADR-0092 §4's user assertion, and
ADR-0110 §3's absence under a declared coverage. The `DERIVED` band has none —
ADR-0110 §8 rules that for a derived belief "nothing is asked and nothing is
closed". The band #663 worried was undetectably stale is now the only one of the
two whose staleness the system has a mechanism to detect at all.

**The honest bound on that argument, stated because it is the reviewable part.**
ADR-0110's own Consequences record that its mechanism "changes no behaviour until
a reader lane opts in", and no reader on `main` satisfies its four conditions —
`SourceReading` has no coverage field yet and `CalendarReader` declares none. So
the warrant for the ordering is *structural*: `ATTESTED` is the band whose
staleness is answerable by re-reading a source that exists, and `DERIVED` is the
band where re-deriving from the same episodes confirms nothing (ADR-0103 §9,
ADR-0077 §5). That argument does not depend on any reader having opted in, which
is why it is available now. What is not claimed is that any attested belief on
`main` today is in fact being kept fresh.

**And the qualification #663 floats is refused by §1 rather than weighed.** Its
question 1 asks whether "the ordering wants a recency qualification". A recency
qualification is a clock acting on rank, which §1 rules out for every band. The
mechanism `ATTESTED` gets for staleness is ADR-0110 §8's re-read, whose *outcome*
— a fold, or an absence — is what acts. #663's question is answered no, and
answered by the same principle that answers the fork.

### 5. #663's second half: §5's precedence is unimplemented because no read can serve it

> **Normative.** ADR-0072 §5's per-band composition remains owed and unbuilt, and
> closing it is not this ADR's and not this lane's. A lane closing it composes per
> band as §5 rules and does not partition a band-neutral top-k, which §5 refuses
> by name.

> **Normative.** The read such a lane needs does not exist on the `MemoryStore`
> contract, and this ADR authorises none. Adding one is a `core/protocols.py`
> decision under golden rule 5 and owes its own ratified ADR before any
> implementation.

This is the finding this lane was best placed to make, and it is not the one
#663 expected. #663 reports the gap as "the precedence is ruled and
unimplemented", implying a consumer that has not got round to it. The cause is
structural.

ADR-0072 §7 ruled a band-scoped read owed and deferred its *signature*, naming
two shapes and leaving the choice "to the slice that holds the consumer, because
the two differ in exactly the way a consumer settles: enumeration wants an offset
and a stable order and no query, while a filter wants relevance". ADR-0073 §1
then took the **enumeration** branch, for the **inspection** consumer, and
`MemoryStore.list_beliefs` says so on its face: it "carries **no query text** and
is not a retrieval — nothing is ranked and no relevance is computed".

So the two reads on the contract today are complementary and neither serves
assembly: `search` ranks by relevance and is band-blind; `list_beliefs` is
band-scoped and ranks nothing. §5's assembler needs both properties at once, and
ADR-0072 §7's own reasoning predicted exactly this — it separated the two shapes
on the grounds that a consumer settles the choice, and the second consumer has a
different answer from the first. Nothing is wrong in the record; the second half
of §7's deferral is simply still open, and it has been invisible because §7 reads
as discharged once one of its shapes landed.

**Why this ADR names it and does not take it.** Taking it means adding a `bands`
or `sources` filter to `MemoryStore.search`, or a third read — `core/protocols.py`
surface, which golden rule 5 puts behind its own ratified ADR, and which this
lane was neither given nor needs. What this lane owes is to say that the gap is
retrieval's, that it is not a ranking problem, and that the ranking answer it
would otherwise be reached for is refused. That is filed as **#790**, not
deferred silently.

**And it is the one that actually degrades with volume**, which is why it belongs
in leg 7's account of itself even though its fix does not. ADR-0072 §5's
flood-below-the-cut failure is a function of how many `DERIVED` records exist
relative to the retrieval budget, and leg 3's observer plus leg 7's consolidation
are both machines for increasing that ratio. A store that has accumulated for
months is precisely the store in which a single band-neutral top-k stops
returning the user's own assertions.

### 6. What fork 5 delivers, stated so this is not ratified as a no-op

Shape 1 changes no code, and an ADR that changes no code and rules a prohibition
is worth auditing for whether it decided anything. Four things, none of which was
settled before it:

1. **The fork is closed against a shape that was live.** ADR-0103 §8 left three
   shapes open and explicitly declined to lean; ADR-0110 §9 declined to take any
   of them. Two of the three are now refused with their grounds on the record, and
   §2's second normative clause means the third cannot arrive as a tuning change.
   The concrete thing that stops happening is an implementation lane writing a
   comparator, choosing a placement for ADR-0103 §9's unknown, and shipping a
   decision inside a sort key.
2. **#663's fired trigger is discharged in both halves** (§4, §5) rather than
   staying open under an ADR that scheduled its own revisit and got none.
3. **The real retrieval defect at volume is named and routed** (§5): not currency,
   but a per-band composed read the contract cannot express, whose absence is what
   §5's own flood argument predicts will bite as the derived band fills.
4. **The leg's exit obligation gets an owner** (§7), and the tuning questions that
   would otherwise be answered by taste get a gate.

**And the gap shape 1 leaves is stated, not glossed.** A lapsed `DERIVED` belief
is retrieved on the same terms as a fresh one. Nothing closes it (ADR-0110 §8),
nothing asks about it (ADR-0110 §8), nothing demotes it (§1, §3). What it gets is
rendered lapse (ADR-0103 §9, ADR-0072 §6) and the user's correction. Whether that
is enough is a *noisiness* question, and the roadmap already assigns the "not
noisier" half of leg 7's exit test to leg 8 "because it needs the memory-precision
measure leg 8 builds; a claim this leg has no instrument for is one it would
assert rather than test". This ADR does not assert it either. It records that
leg 8's memory-precision measure is what would show the gap biting, and §Consequences
carries the revisit.

### 7. Leg 7's retrieval obligation is the measurement, and tuning — not correctness — waits on it

> **Normative.** Leg 7's retrieval exit obligation is the measurement the roadmap
> names — retrieval latency and k-shortfall against a synthetically aged store —
> and it is a lane of its own. This ADR neither builds it nor prescribes its
> fixture, thresholds or harness.

> **Normative.** No lane makes a **headroom** change to retrieval before that
> measurement exists — raising `_RESULT_OVERFETCH`, decoupling or lifting the KNN
> `k` cap to buy a larger candidate budget, deepening the candidate scan by some
> further bounded amount to buy a bigger multiple of `limit`, or adopting hybrid
> lexical+vector retrieval. The measurement is the warrant; a constant changed
> without one is a guess with a commit message.

> **Normative.** That gate does **not** reach a **correctness** remedy for #457 —
> a change that removes or exposes the silent failure rather than making it rarer.
> Such a remedy proceeds on its own merits and without waiting for the
> measurement, subject to §10 where it needs contract surface. Two shapes the
> corpus already names qualify on their face, because neither iterates: a
> pre-filter that lets the KNN see only eligible rows, and an explicit
> under-service signal a caller can refuse on.

> **Normative.** Whether a remedy that **iterates** — continuing past the cap
> until served or exhausted — is a correctness remedy or a headroom change is not
> settled here, and this ADR pre-blesses no iterating shape. It is settled by the
> contract ADR §10 requires, and that ADR owes a termination argument against
> ADR-0050 §1's ratified rejection of an unbounded re-search and ADR-0079 §1's
> objection that such a sweep has no termination guarantee and depends on the
> store's read clock.

**The line between the first two clauses is whether the change is a bet on a
frequency, and it is not a line between mechanisms.** What is gated is the bet,
never the mechanism that carries it: the same deepening of a candidate scan is a
headroom change when its case is that the new depth is enough, and something else
when it runs to a condition rather than to a budget. A headroom change buys a
bigger multiple of `limit` and leaves the failure mode exactly where it was, one
denser store further out; its whole case is that the new multiple is enough,
which is a claim about how often nearer
neighbours are filtered — unanswerable without the measurement, and the reason
#457 and #411 each offer *lists* of options rather than a fix. A remedy that
makes the shortfall impossible or legible makes no such claim, and gating it on a
frequency would be a category error: #457's exposure is that
`MemoryIngestor._detect_conflicts` can be handed an incomplete conflict set and
cannot tell, so `DefaultMemoryPolicy`'s asserted-conflict gates can turn what
should be an `ASK_USER` into a `SUPERSEDE` — the profile silently committing a
self-contradiction. **That is wrong at any frequency**, and no k-shortfall number
would make it safe. This distinction was missed by an earlier draft, which gated
"the mitigation options #457 or #411 enumerate" as one set while §8 classed #457
as a write-path correctness exposure; the two statements could not both stand.

**The third clause exists because the second one over-reached, and the correction
is worth leaving legible.** A draft of this section listed, among the shapes that
qualify as correctness remedies, "a pagination that continues until it has served
`limit` eligible rows **or** exhausted the candidate space". The adversarial lens
answered it on the corpus: ADR-0050 §1 carries a ratified rejection of "an
unbounded re-search", ADR-0079 §1 names "the objection that sinks 're-search
until exhausted'" as its want of a termination argument and its dependence on the
store's read clock, and ADR-0079 §1's own design is explicitly "a single bounded
read with a refusing ceiling, not a sweep" *because* of it. Exhaustion is not
self-defining: against a live store it is a moving target, and against a fixed
snapshot it is a read-clock commitment nothing on the `MemoryStore` contract makes
today. So the shape may well be right — #411 part 3 calls it the durable fix — and
this ADR is not the place it earns that, because earning it means making the
termination argument the corpus twice declined to make. Naming the argument that
is owed is worth more to the next lane than a permission it would have had to
re-derive anyway.

The first clause is the one that costs something, and it is the discipline the
corpus already applies to itself. ADR-0103 §5 defers currency's decay parameters
to leg 8's measurement on exactly this ground — "a number invented here would
arrive with the authority of a ratified decision and the evidence of a guess" —
and ADR-0006 §5 leaves hybrid retrieval out of scope with its revisit conditioned
on local retrieval proving "inadequate for the memory sizes we see", which is a
measured claim and not an elapsed one.

**A correction to #729, which this lane is the one to make.** #729 states that
"ADR-0006 §5's revisit-if has fired". It has not. ADR-0006's revisit clause fires
on measured inadequacy of "local embedding quality or latency … for the memory
sizes we see"; its other limb, "if we adopt hybrid retrieval", is a consequence of
adopting hybrid, not a trigger for adopting it, and reading it as one is circular.
No measurement exists, so nothing has fired. This is a correction to an issue's
prose and not to a ratified text, so nothing is owed under ADR-0082 §1 (§11).

**The instrument has no owner and this ADR gives it one by name.** It is a
`tests/`-side lane — an aged-store fixture and a measurement harness — with no
`src/` change and no contract surface, and it is a prerequisite of the tuning
work rather than a follow-up to it. It is filed as **#789** rather than left
implicit in the roadmap's exit line, because an exit test nobody owns is an exit
test that gets asserted at the leg's close.

### 8. #457 and #411 adjudicated against the record

Both issues ride this fork per #729 and both are **scoped, not decided**. What
this ADR settles is which of their contents survive contact with the record and
which gate they sit behind.

**#457 — the retrieval-exhaustiveness residual. Stands, entirely.** Its
description of the mechanism is still accurate on `main`: `SqliteMemoryStore`
runs the vector KNN first and applies kind, expiry and validity-window predicates
in a post-KNN pass, and the store's own comment records that "a filtered row still
counts against over-fetch". Its consequence is unchanged and is a *write-path
correctness* exposure rather than a ranking one — `MemoryIngestor`'s conflict
detection is built on `search`, and `core/protocols.py` and `memory/ingest.py`
both cite #457 at the point where the obligation lands. Two clauses of it have
strengthened since filing: every `SUPERSEDE` leaves a window-closed record that
eats over-fetch headroom, and ADR-0110 §3 adds a *second* producer of
window-closed records, so the headroom pressure grows with reconciliation as well
as with correction. Its option list is untouched by this ADR and is **split** by
§7: its headroom option (raising `_RESULT_OVERFETCH` / decoupling the `k` cap,
which #457 itself calls "a mitigation, not a fix") waits for the measurement,
while its pre-filter and under-service-signal options are correctness remedies
and do not. The under-service signal is the one worth naming, because it is
available at the lowest cost and needs no frequency to justify: #457 states it as
`search` reporting that "it returned fewer than `limit` rows *and* exhausted its
candidate budget, so a caller can refuse rather than silently believe it saw
everything". Whether it lands on the `MemoryStore` contract is §10's question and
not pre-authorised here.

**#457's own ADR judgement is right and is restated here.** It observes that a
threshold-complete read would be "a `MemoryStore` Protocol obligation, so an ADR
under golden rule 5". That is correct and §10 does not pre-authorise it.

**#411 — three parts, and they no longer travel together.**

- **Part 1 (a construction-time bound on the search limit)** is ergonomics, as
  the issue itself says once #410's clamp landed. It spans two `_check_tuning`
  sites and asks whether the bound belongs on the `MemoryStore.search` contract.
  The contract half is golden rule 5's and is not authorised here; the two-site
  half is a `CONTRIBUTING.md`-grade tidy that needs no ADR and no measurement.
- **Part 2 (decoupling `_VEC_KNN_MAX_K` from the pinned `sqlite-vec` version)** is
  a dependency-coupling defect, not a retrieval-quality question. It is behind no
  gate this ADR sets: it is neither a mitigation option nor a tuning change, and a
  lane may take it whenever it likes.
- **Part 3 (filtered cap-boundary behaviour)** is #457's mechanism seen from the
  constant's side, and it is the part that names the durable fix — "retrieval that
  can continue past the cap (paginate the KNN)". It **iterates**, so §7's third
  clause governs it: this ADR classifies it neither way and pre-blesses nothing.
  What it owes, in the contract ADR §10 requires, is the termination argument
  ADR-0050 §1's rejection of an unbounded re-search and ADR-0079 §1's read-clock
  objection between them demand — against what "exhausted" is measured, and what
  the store commits to about concurrent writes while it is measured. The issue is
  right that this is the durable fix; what it does not carry is that argument.

**One staleness in #411 worth recording**: its note that "#115's premise that
`_check_tuning` lives only in `orchestration` … is now stale" is itself now the
load-bearing part, since both of the two sites it names remain — `orchestration/loop.py`'s
`retrieval_limit` and `memory/ingest.py`'s `conflict_limit`, the two that feed
`MemoryStore.search`. Nothing in the issue
misdescribes the tree; it is simply three issues wearing one number, and §7's gate
lands on only one of them.

### 9. What this ADR does not decide

- **Decay parameters, the decay function, and the staleness threshold.**
  ADR-0103 §5 defers them to leg 8's measurement and this ADR does not reach them.
  Nothing here needs a threshold, which is a property of shape 1 worth noticing:
  shapes 2 and 3 would both have needed one before leg 8 could supply it.
- **Demotion semantics.** ADR-0110 owns what a lapse does to standing, in full.
  This ADR consumes §8's answer and adds nothing to it.
- **Consolidation**, which ADR-0106 owns, and whose output lands in the `DERIVED`
  band — increasing the ratio §5's flood argument turns on without changing what
  this ADR rules.
- **Presentation.** How a lapse, a band or an evidence-strength is rendered is
  ADR-0072 §6's and ADR-0103 §9's, with the wording the prompt-assembly lane's.
  §1 puts currency there; it does not say what "there" looks like.
- **The band-scoped relevance read** (§5) and any `MemoryStore` member #457's fix
  might want (§8). Both are golden rule 5 decisions owed their own ADRs.
- **Cross-conversation episodic recall's ranking question.** ADR-0074 §6 defers
  the capability "with its ranking question" and §11 lists it as "due with leg 7's
  retrieval-under-load work" — that is this lane, so it is answered rather than
  passed on silently. **Its ordering half closes here**: the axis is relevance,
  kinds are the caller's argument as ADR-0074 §6 already rules, and no quantity
  joins the order, so "mixing raw turns with distilled beliefs in one relevance
  cut" is not an ordering question but a *budget* question — how much of a turn's
  retrieval budget episodes may take, and from which consumer's decision. That
  half has no consumer, and the repository's standing discipline is to defer
  surface until one exists (ADR-0072 §7, ADR-0045 §1, ADR-0028 §7). It carries
  forward on **#791** rather than on ADR-0074's list.
- **Hybrid lexical+vector retrieval** (ADR-0006 §5), gated by §7's headroom
  clause and unfired (§7).
- **Anything about eviction, size caps or retention.** ADR-0103 §1's framing rules
  them out for this leg and ADR-0007 §5's deferral stands untouched.

### 10. The contract surface: none

> **Normative.** This ADR authorises no change to `core/protocols.py` and no
> change to `core/types.py`. Every mechanism it rules is a prohibition or an
> affirmation over surface that already exists, and a lane concluding it needs new
> contract surface — a `bands` filter on `search`, a third read, a
> threshold-complete conflict read, a documented maximum limit — owes its own
> ratified ADR under golden rule 5 and may not read this one as pre-authorising
> it.

Stating this positively is worth a clause because three of the questions this ADR
touches (§5, §8, §9) each have an obvious fix that is a Protocol member, and an
ADR that names them without ruling on the authorisation invites a lane to read the
naming as a licence. It is also what makes the review set adversarial alone
(`CONTRIBUTING.md`), which is the header's claim and this section's ground for it.

No conformance obligation is created either. Nothing here is a `MemoryStore` or
`MemoryWriter` behaviour a suite could drive: §1's prohibitions bind lanes and
ADRs, not implementations, and the implementation-side statement of §1 is already
`MemoryStore.search`'s ratified band- and confidence-neutrality.

### 11. What this records against earlier ADRs: nothing

The judgement ADR-0082 §1 requires is made here clause by clause, by applying
ADR-0070 §1's test to each earlier ADR's text: would a reader holding only that
ADR now act differently, or read one of its clauses more widely than it now holds?

**ADR-0072 §5, §6 and its Consequences — nothing owed.** §5 is affirmed rather
than touched: §1 leaves `search` band-neutral and confidence-neutral, §4 leaves
the band ordering as ruled, and §5 above leaves the per-band composition owed and
unbuilt. §3 constrains the consumer in a respect §5 left open — within-band
ordering — which is a stacked addition and makes no sentence of §5 false; a reader
holding only ADR-0072 builds the same assembler and owes the same work. §6's
presentation rule is relied on and read no more widely than it holds. The
Consequences line naming the supersession price for confidence-weighted retrieval
is cited as the door this ADR declines to open, which is using it as written.
**Stacked addition; no record owed.**

**ADR-0103 §8 and §9 — nothing owed.** §8 is a routing clause with three
obligations: that ADR-0103 grants no retrieval-side role, that this lane's ADR
"states which shape it takes and what ADR-0072 §5 costs under it", and that
nothing there permits weighting `search`. All three are satisfied rather than
disturbed — §1 states the shape, §2 states the price and declines to pay it, and
nothing here weights anything. §8's closing sentence, "This ADR neither claims
currency ranks nor claims it never will", is a statement about ADR-0103's own
scope and stays true after this ADR makes the claim ADR-0103 declined to.
Discharging a deferral the earlier ADR itself scheduled, without narrowing any of
its sentences, is the shape ADR-0110 §13 distinguishes from supersession by
reference to ADR-0045's 2026-08-02 note. §9's unknown-currency domain is cited as
a reason and applied exactly as ruled. **Deferral discharged; no record owed.**

**ADR-0110 §8 and §9 — nothing owed.** §9's first deferral routes "whether currency
reaches retrieval, and how" here and states that ADR-0110 "takes none of the three
shapes and prices none of them"; this ADR takes one and prices another, which is
that deferral used as written. §8's band-by-band ruling is consumed unchanged and
is cited in §3 as evidence of the corpus's posture rather than as a rule
foreclosing shape 2 — a distinction §9 itself draws, and one this ADR is careful
not to blur, since reading §8 as already deciding retrieval would make ADR-0110's
own §9 false. **Deferral discharged; no record owed.**

**ADR-0074 §6 and §11 — nothing owed.** §6's `kinds` filter and its statement that
`search` "stays exactly as ADR-0072 §5 ruled" are both affirmed. §11's entry —
"Cross-conversation episodic recall and its ranking (§6). Due with leg 7's
retrieval-under-load work" — names this lane, and §9 above answers its ordering
half and carries its consumer half forward on #791. §11's entry stops
describing a wholly open question, which is what a discharge does; no sentence of
ADR-0074 becomes false, because §6 and §11 both frame the deferral as *the
capability plus its ranking* and the capability is untouched. **Partial discharge;
no record owed.**

**ADR-0007 §5 and its Consequences — nothing owed.** §5's size-caps deferral is
untouched, as ADR-0103 §1 already recorded. The Consequences bullet "Search
inherits the existing expiry/kind post-filter caveat" describes the pass as
carrying two predicates; it now carries three, the validity window having been
added by ADR-0045 §6 and extended by ADR-0110 §3. That widening is ADR-0045's and
is not this ADR's to record: the bullet was true when written, nothing here
changes it, and a reader acting on it acts on a caveat that is if anything
understated. It is filed as **#792** rather than ruled on, which is the
park-what-isn't-this-change discipline. **No record owed.**

**ADR-0006 §5 — nothing owed.** §5 leaves hybrid out of scope and its revisit
clause is cited and applied as written; §7's correction is to #729's prose about
ADR-0006, not to ADR-0006. A misreading of a ratified text corrected in a later
ADR leaves the ratified text unchanged and owes it nothing. **No record owed.**

**ADR-0073 §1 — nothing owed.** `list_beliefs` is described exactly as its
docstring and ADR-0073 rule it, and §5's finding is that ADR-0072 §7's *other*
branch is still open, not that ADR-0073 took the wrong one. It took the right one
for its consumer, which is what ADR-0072 §7 asked of it. **No record owed.**

**ADR-0038 §3, ADR-0045, ADR-0077 §5, ADR-0080, ADR-0092, ADR-0106, ADR-0109 —
nothing owed.** Each is cited as a reason or a mechanism and read no more widely
than it holds; none acquires an exception and none loses one.

## Consequences

- **Leg 7's last fork closes, and it closes by subtraction.** The leg ships
  consolidation, demotion, chunking and the re-embedding migration, and ships
  retrieval unchanged — with the reason on the record rather than as an absence
  someone later reads as an oversight.
- **`MemoryStore.search` becomes harder to change, deliberately.** ADR-0072 §5's
  neutrality now has a second ADR affirming it against the specific pressure that
  was most likely to erode it, and §2's clause means the supersession price is
  quoted in two places rather than one.
- **An implementation lane is spared a decision it would have had to invent.**
  The comparator that would have placed ADR-0103 §9's unknown currency somewhere
  in a total order does not get written, and the placement does not get ratified
  by shipping.
- **The `DERIVED` band's lapse gap is now a named, unmitigated cost** rather than
  a property nobody stated (§6). It is carried to leg 8, where the
  memory-precision measure that could show it biting is built.
- **Two things move from implicit to owned**: the exit instrument (§7) and the
  band-scoped relevance read (§5, **#790**), each on its own issue. The first is a
  prerequisite of any tuning this leg does; the second is a golden-rule-5 ADR
  whenever a lane wants §5's precedence real.
- **Headroom tuning gets a gate; correctness does not.** #457's and #411's
  *headroom* options wait for a measurement that does not exist yet — the trade
  being that the alternative is picking among them on the strength of a plausible
  story about a store nobody has aged. What does **not** wait is a remedy that
  removes the silent failure, which matters because #457's exposure is a write-path
  correctness one and no frequency makes it safe (§7). So the gate costs a denser
  store's worth of headroom, not an open correctness hole.
- **Nothing in this leg now needs leg 8's numbers to ship.** Shapes 2 and 3 each
  required a currency threshold or a placement rule before leg 8's measurement
  could supply one; shape 1 requires neither, which is why it is the shape that
  can be ratified today without a provisional parameter under ADR-0103 §5.
- **Revisit if** leg 8's memory-precision measure shows lapsed `DERIVED` beliefs
  measurably degrading retrieval quality — the revisit ADR-0110 §8 already carries
  for its own response, arriving here as a question about rank rather than about
  standing; if the exit measurement (§7) shows k-shortfall biting at ordinary
  volumes, which reopens #457's and #411's headroom options with the warrant §7
  requires; if a consumer for cross-conversation episodic recall appears and its
  budget question turns out to need an ordering answer after all (§9); or if
  ADR-0072 §5's per-band composition is built and the flood failure survives it,
  which would mean the failure was never the composition's.

## Alternatives considered

- **In-store ranking — similarity × currency × band weight, superseding ADR-0072
  §5.** Rejected in §2. It is #729's original shape, withdrawn by its own author's
  objection, and the price for it is a supersession ADR-0072's Consequences quotes
  in advance. Beyond §5's own three reasons, it has no value to rank on: ADR-0103
  §9's unknown currency has no position in a total order that is not one of the two
  inventions ADR-0103 §9 forbids by name.
- **In-store ranking limited to `ATTESTED`, citing #663.** Rejected in §2 on
  citation grounds and worth naming separately because it is the plausible-looking
  version. #663 fires ADR-0072 §5's *ordering* revisit only; the weighting half's
  only door is the Consequences line. A proposal that weights the store while
  citing #663 is citing a trigger that does not reach it.
- **Composition above the seam — the assembler orders by currency within each
  band.** Rejected in §3. It breaches no sentence of ADR-0072 §5, which is exactly
  why it needed deciding rather than deriving: §5 rules the store and the
  precedence and leaves within-band ordering open. It is refused because it appends
  to ADR-0110 §8's enumerated consequences of a lapse the one item that removes a
  belief from the user's view, and because it inherits §2's unknown-currency
  problem unchanged by moving the comparator.
- **Composition above the seam, restricted to records with a known currency.**
  Rejected as the same decision wearing a guard. It partitions the band into
  known-currency and unknown-currency sets and must still order across them; every
  ordering of those two sets asserts something about unknown that ADR-0103 §9
  refuses, and a stable partition that always places unknowns last is "unknown is
  stale" with extra steps.
- **A currency cut rather than a currency order** — dropping records past a
  staleness threshold from the assembled context. Rejected as strictly worse than
  the order: it is the same clock acting on the same non-signal (§1), it needs the
  threshold ADR-0103 §5 defers, and it hides the belief completely rather than
  merely late, which is ADR-0072 §5's second reason at full strength.
- **Deciding the band-scoped relevance read here**, since §5 identifies the gap.
  Rejected in §5 and §10. It is `core/protocols.py` surface, golden rule 5 puts it
  behind its own ratified ADR, and this lane holds neither the consumer nor the
  brief for it. Naming the gap costs a section and leaves the decision where it
  belongs — the discipline ADR-0110 §10 applied to its own writer-surface question
  after an earlier draft did the opposite.
- **Fixing the post-KNN over-fetch in this lane**, as #729's fork-5 text proposes
  ("fixed or instrumented in this lane"). Rejected in §7, but only for the
  *headroom* half: the instrument is what can be built without a number, and a
  headroom change is a choice among options whose merits are all claims about
  frequencies nobody has measured. Taking the instrument and gating those is the
  same sentence read in the order that can actually be executed. A **correctness**
  remedy is not rejected and not gated — it is simply not this docs-only lane's
  to write, and §7's second clause says so rather than letting the gate swallow
  it.
- **Deferring the whole fork until leg 8's measurement.** Rejected. The shape
  question is decidable from the corpus — ADR-0110 §8 supplies what shape 1
  consists of, ADR-0103 §9 supplies the reason shapes 2 and 3 have nothing to
  order — and leaving it open past leg 7 leaves the leg's most load-bearing
  retrieval rule as an invitation for whichever lane next touches a sort key.
  Deferring the *parameters* is right and is what ADR-0103 §5 already does.
- **Ruling that a lapsed `DERIVED` belief is demoted after all**, on the grounds
  that leg 7's exit test is about retrieval quality. Rejected in §1 and §6: the
  roadmap assigns the "not noisier" half of that test to leg 8 precisely because
  this leg has no instrument for it, so a demotion ruled here would be a quality
  claim made in the leg that admitted it cannot measure quality.
