# 226. The planner names one more read beside its plan, and the loop services it into the supply

- Status: Accepted, §11 item 1 amended by ADR-0227
- Date: 2026-09-02
- Amended: 2026-09-03 by ADR-0227 — §11 item 1's assertion *"the answer carries it"*
  stands and is not replaced; what it gains is the **fidelity requirement** under which
  it is discharged. Item 1 was written as an obligation to produce a test, and the test
  written for it passed against a fixture no capture site produces: the episode carried
  the reply's distinctive word in `content`, where every group renders it, rather than
  in `outcome` beside a `disposition`, which is the one combination the render rules
  turn on. The production renderer *was* on the path — the fake was the
  `ModelProvider`, and it read the assembled prompt — so nothing about the wiring was
  wrong; the record shape was. A reader holding only this ADR accepts that test, which
  is [ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md)
  §1's test met on item 1 and on no other clause of this ADR. The added obligations are
  recorded here in full:

  > **Normative.** A required representative-input test that asserts a fact about
  > **what a model was shown** runs the production renderer for that surface, and
  > drives it over records **shaped as the production capture site writes them**. A
  > fixture that carries in one field what production carries in another asserts
  > nothing about production, however faithfully the rest of the path is wired.

  > **Normative.** A test of this shape may substitute a fake `ModelProvider`, a fake
  > store and a fake clock. It may **not** substitute the renderer whose output the
  > assertion is about, and it may not assert over a composed reply produced by a fake
  > that did not read the assembled prompt.

  > **Normative.** §11 item 1 is subject to both of the above. Its sentence *"the
  > answer carries it"* is unchanged and is the right assertion; what is added is that
  > it is asserted through `orchestration/composing.py`'s production renderer, over an
  > episode carrying the reply's distinctive word in `outcome` beside a `disposition`,
  > with that word absent from `content`. The existing test is **rewritten** rather
  > than supplemented.

  §11's other items are untouched and bind unchanged, and so is every other section of
  this ADR. **§7 is not amended**: it states the fourth group's construction, position,
  deduplication, evaluation timing and consumer rules and says nothing about rendering,
  so no sentence of it becomes false or over-wide when ADR-0227 supplies the render
  rule — that is ADR-0082 §1's *stacked addition*, recorded in the ADR that makes it
  and nowhere else. The clause that in fact governed the fourth group's rendering, and
  which is superseded, is ADR-0222 §2.
- **Supersedes three ADRs, partially, in four narrowly stated scopes** — one of
  ADR-0208, two of ADR-0204 and one of ADR-0158 — and §13 shows the working for every
  one. Scopes rather than clauses, because the second ADR-0204 scope names two clauses
  of one section that move together and for one reason. The first:
  [ADR-0208](0208-recall-memory-leaves-the-default-tool-set-and-the-turns-supply-is-retrieved-at-one-site.md)
  **partially**, in one scope — §1's **one-site clause**, *"On the turn path the
  assistant's own store is read **for relevance** … at exactly one site: the retrieval
  stage"*, in the single respect that §2's sighted query is a second such site (§13
  here). §1's four other clauses stand, and the keyed-load clause is not merely
  untouched but load-bearing: it is why §2's citation hop needs no supersession at
  all.
- **And the second:**
  [ADR-0204](0204-a-record-carries-whether-the-supply-it-was-produced-over-held-withheld-content.md)
  **partially**, in one scope — §2's **timing clause**, *"once, between retrieval and
  planning"*, and that clause alone. §7 takes that evaluation once over the turn's
  **final** supply: after servicing on a turn that serviced a request, and exactly
  where §2 puts it on every other turn. Only the timing moves. §2's two terms, its
  *"once"*, the set it ranges over, the field it writes and the stage that carries the
  value to capture are untouched; §3 is untouched **entirely**, and nothing in this ADR
  narrows a bounded channel's supply or discards a record on the strength of its class.
  §13 shows the working and says why the alternative — a servicer admitting nothing the
  evaluation would have found — was refused. **And, of the same ADR,** §4's first and
  second clauses, only as they freeze the supply a bounded turn composes over, the
  `TurnResult` it returns, the reply composed for it and `TurnResult.memories`'
  meaning, and only on a turn whose planner emitted a request. §4's narrowing
  prohibition stands entire, and so do the plan, the step it drives and the plan
  persisted through `PlanStore.save_plan`.
- **And the third:**
  [ADR-0158](0158-an-episode-may-supplement-the-answering-prompt-and-never-shares-the-belief-budget.md)
  **partially**, in one scope — §5's **sameness clause**, *"`TurnResult.memories`
  carries the same three groups in the same order as `Planner.plan`'s `memories`"*.
  The planner is called before the servicer and keeps its three groups; the
  `TurnResult` of a turn that serviced a request carries those three, in that order,
  and a fourth appended after them. §5's three-group clause on `Planner.plan` is
  **untouched**, and so is its caution that an implementation *"may rely on the
  grouping and may not rely on a global relevance order"*, which §7 carries word for
  word to the fourth group. §4's append-never-interleave rule is extended in
  application and unchanged in text.
- **No other ADR is superseded in whole or in part**, and §13 shows the working
  for each one a reader would expect to be — ADR-0203, ADR-0210, ADR-0074 and
  ADR-0039 among them. §5's scoping of this envelope off the channel of unbounded
  audience is what keeps the list this short.
- **Decides a change to `src/ai_assistant/core/types.py`** — three added types, one
  additive defaulted field on `ActionPlan`, and `PlanExport.schema_version` moving to
  **3**, with `TurnResult.memories`' documented meaning widened by one group — and a
  widening of `Planner.plan`'s documented **return** in
  `src/ai_assistant/core/protocols.py`: the `ActionPlan` it hands back may carry a
  read request. `Planner.plan`'s signature and its `memories` **input** are unchanged,
  it adds **no Protocol and no member to one**, and it moves no `PROTOCOL_VERSION`:
  `ActionPlan` crosses neither `wire/` nor `service/` in the tree. **The widened return
  is a Protocol change and is flagged as a breaking change under golden rule 5**,
  exactly as ADR-0158 §5 flagged its own; §10 binds Lane A to extend the shared
  `PlannerContract` conformance suite that already runs against both `Planner`
  implementations, and separates the flag from the compatibility fact that no existing
  implementation stops conforming. The versioned surface it *does* cross is the portable
  export, and §4 moves it. **This ADR changes no code.** §10 states what the
  implementing lanes owe; nothing implements against it until it has merged
  ([ADR-0015](0015-simplify-the-agent-workflow.md) §5, golden rule 5).

## Context

### Where this comes from

`track:planning` (#1908) opened 2026-09-02 on the owner's direction, and this is
its milestone 1. The design note is **#1844**, whose observation is one sentence:
*"Every memory read in the system fires before anything has reasoned about the
request."* The note asked for an offline replay before anything was built; that
replay ran on 2026-09-01 and is the comment on #1844 this ADR prices itself from
throughout. #1732 is the same mechanism's first instance, filed narrowly; #838 is
the trigger question in its ambitious form.

The replay's own recommendation was *"**Do not open the one-envelope sighted-read
ADR yet**"*. The owner ruled otherwise on 2026-09-02, and ruled the ground: the
justification is task capability rather than benchmark points, and **no offline
re-measure precedes this ADR — the live audit is the instrument**. §8 is that
ruling's mechanism, and §13's last paragraph states what it costs.

### The observation, verified against `origin/main` rather than inherited

`ConversationLoop._turn` in `src/ai_assistant/orchestration/loop.py` reads, in
order: the conversation tail, the goal minted from the user's unrewritten words,
context assembly, `_retrieve` on `goal.statement`, `_supplement` on
`goal.statement`, the disclosure narrowing, `ToolRegistry.capabilities()`, and then
`self._planner.plan(...)`. The two relevance reads take the user's sentence
verbatim as their query, and by the time the planner has an opinion, reading is
over. That is #1844's finding, and it holds at `b5dcef2e`.

Two consequences follow directly and neither is speculative. Retrieval matches the
**question's** vocabulary and never the **answer's**, because only `content` is
embedded — so *"which lender did you recommend?"* cannot reach an exchange in which
the user asked about "the house payment". And a compound question gets one vector.

### What the replay priced, and what it did not

The replay drove the harness's own `retrieve_for` over copies of pilot-5's as-run
stores, reproducing pilot-5's `retrieved_ids` *"in order, on every question"* and
recomputing its published 75.7% headline *"to the decimal"*. So the blind read it
measures is the production read. Every headline below is LoCoMo's, n=1531; the
LongMemEval arm is 50 questions with session-shaped gold and the replay itself says
it *"should not be read as a 96% hold"*.

**The blind pass splits three ways**: `held` 810 (**52.9%**), `hop` 349 (**22.8%**),
`miss` 372 (**24.3%**). *"The published 75.7% retrieval reach is `held` + `hop`"* —
22.8 points of it is a citation hop the system does not perform. Answer accuracy
falls 90.1% → 76.2% across that boundary, which makes the hop's *"entire addressable
headroom on this corpus"* about **+3.2pt**: *"not zero and it is not large."*

**Both mechanisms work about as well as #1844 predicted.** The hop's oracle shape is
the note's own: *"311/349 need **exactly one** belief, 29 need two, 9 need three"*,
shallowest covering belief at median rank 3. Driven by a real model it reaches the
gold **166/349 = 47.6%**, and *"the failure is selection, not the mechanism"* — 113
replied NONE and 105 *"named an **episode**, whose hop goes nowhere"*. The
reformulated query recovers *"about one in ten at one read"* where the blind key
genuinely cannot see the gold, which qualifies #1844's own framing and is why §2
does not rest the design on reformulation alone.

**They are complementary.** On the same 150 hop questions at one read: reformulated
query 50.0%, citation hop 44.7%, **either 63.3%**, **both 31.3%** — *"28 questions
only the query got, 20 only the hop"*. The replay draws the conclusion this ADR
takes: *"That is an argument for one envelope carrying both shapes, and against
picking one."*

**One read is enough.** *"Every recovery measured is one planner emission serviced by
one loop read"*; reads two and three add 10.0pt then 4.6pt on the miss set and 11.3pt
then 7.4pt on the hop set — *"real, sharply diminishing, and nothing needing
re-planning"*. So the envelope is *"a **refinement, not a different execution
model**"*, and #1844's "end state" agent loop is milestones 2–3's ground rather than
this ADR's.

**And the trigger is the binding constraint.** Asked only SUFFICIENT /
SEARCH_AGAIN, the planner fired on 4.8% of `held`, 14.0% of `hop` and **32.4%** of
`miss`; re-weighted to the population it fires on **13.6% of turns**, giving
precision **57.9%** and recall **32.4%** against total misses. Worse, *"it fires
**least** where it is needed most — on multi-hop misses it fires 13% of the time,
and multi-hop is the category with a 59.1% miss rate"*, and firing is *"statistically
independent of whether a second read would have helped: 21.0% of fired-on misses
recovered at one read against 21.2% of all misses"*. **Those are the numbers this
design must beat**, and §8 exists so that whether it does is a number rather than an
opinion.

### The charter's caution, and this ADR's honest justification

#1908 writes the caution in on purpose: *"do not justify the loop by memory-benchmark
numbers"*, and *"Exits are task-shaped, not retrieval-shaped."* This ADR obeys it,
and states the uncomfortable figure rather than burying it: with the measured
trigger the envelope projects to **≈ +0.9pt** LoCoMo accuracy — against **≈ +4.3pt**
with an oracle trigger, and against **≈ +3.6pt** for a one-line allocation change
that needs no model call at all.

**That last comparison has since been taken, which changes what it argues rather
than how large it is.** ADR-0224 moved `EPISODIC_SUPPLEMENT_LIMIT` 10 → 30, and
`app/composition.py` carries 30 at `b5dcef2e`. So the replay's cheapest lever is
*spent*: it is no longer an alternative to this envelope, it is part of the
denominator the envelope's next measurement is read against, and the +0.9pt figure —
measured on a store read with a supplement of 10 — is if anything an **over**-estimate
of what the envelope adds on top of it. This ADR does not claim otherwise and does
not re-price it; §8's audit is where the live figure comes from.

The justification is therefore the charter's and not the benchmark's. A question
whose answer shares no wording with the record that holds it is not a ranking
problem, and no allocation of a blind read fixes it: *"it reaches the exchange by
pointer, which is the only mechanism that answers 'which lender did you
recommend?'"* The envelope is the seam through which every later rung of #1908
arrives — a revisable plan, an outward fetch, a structured read — and building it on
a corpus where it is worth a point is how it gets built before it is needed.

### Claims in the framing that do not survive contact with the tree

Stated because each was carried into this lane's brief and each would have produced
a wrong citation or a wrong design.

1. **ADR-0014 §6 carries no plan-once clause.** §6 is the `Planner` Protocol seam.
   The frozen-plan rule is **§2**: *"`frozen=True` is not decoration — it is what
   makes the plan an auditable record of a decision. Re-planning produces a *new*
   `ActionPlan` with a new `id`."* This ADR cites §2 for it. (§6's own input roster
   is already partially superseded by ADR-0211.)
2. **ADR-0037 never says "drive at most one step".** Its words are *"This object
   disposes of one step, once"* and *"`StepRunner` does not drive a whole plan."*
   Its subject is the step runner, not the turn, and §12 defers re-planning against
   ADR-0014 §2 rather than against a sentence ADR-0037 does not contain.
3. **ADR-0223 never says "no auto-allow".** It says egress *"loses its automatic
   `ALLOW` on later turns"*, and §6's product sentence is that a later turn *"is a
   confirmation rather than an allow"*. §12 quotes it as written.
4. **#1732's named measurement is unobtainable and is not inherited.** It proposes
   counting *"how often `recall_memory`'s CONFIRMs were drawn on questions the supply
   did not answer"*; #1844 answers that ADR-0208 §1 unregistered that tool *"and it
   was removed partly because it kept parking, so few confirmations exist"*. §8
   replaces it. #1732's *"phrasing miss"* framing is likewise superseded by #1844's:
   *"a planner-emitted query is the system's first sighted read, not a spelling
   correction"* — and the replay's key-miss/rank-miss split is the evidence that
   reformulation alone would have been the smaller claim.
5. **`ActionPlan`'s fields are as the batch issue grep reported, and one property it
   did not report decides §4**: the model is `ConfigDict(extra="forbid",
   frozen=True)`, so the field §4 adds must be declared and cannot be smuggled.

### What is not in dispute, and is used as given

`assemble_by_band(store, query, *, limit, kinds=None)` in
`orchestration/retrieval.py` is the banded read, and ADR-0208 §1 is explicit that
its per-band calls are one site rather than one call: *"One site is not one call."*
`MemoryStore.get_many` resolves *k* ids against **one** read-time snapshot and omits
what does not resolve — *"An id that does not resolve is **simply missing from the
mapping**; it is never an error"* — which is exactly the failure mode §3 needs for a
label that resolves to nothing. `MAX_EVIDENCE_CITATIONS` is 64. And the replay
confirms the hop is fully measurable rather than truncated: *"`evidence_elided` is
**0** across all 81,440 retrieved records in both corpora."*

### An honest statement of what this ADR is not allowed to settle

It does not settle whether the trigger is learnable from the supply alone — #838's
coverage layer is adjacent, undecided, and named as such in §8 and §12. It does not
settle re-planning, an outward fetch, structured read keys, or decomposition; §12
names each with what fires it. It takes no position on hybrid search beyond
recording that ADR-0006 §5 left it *"a plausible later enhancement"* and that nothing
has moved. And it does not measure itself: the owner ruled the live audit is the
instrument, so this ADR's job is to make the instrument exist, not to report from it.

## Decision

### 1. The envelope: one request beside the plan, over a closed kind enumeration

> **Normative.** The planner may emit, beside its plan, at most one **read
> request**: a statement of what it wants read into this turn's supply. The loop —
> never the planner, and never a tool — services it. What a serviced request
> returns into the supply is `MemoryRecord`s carrying their own `Provenance`, and
> never a payload, a rendering, a summary or free text of any kind.

> **Normative.** A read request is a closed enumeration of **kinds**. This ADR
> admits exactly two, named in §2. No implementation, setting or later lane adds a
> third without the ADR that decides it, and no lane widens an admitted kind's
> meaning to carry a read the ADR that admitted it did not describe.

> **Normative.** A later kind is an **additive entry to this enumeration**, not a
> second seam. An ADR admitting one adds a member and states that kind's namer, its
> servicing, its share of §6's budget and its audit fields; it does not introduce a
> second request object, a second servicing site, a second budget or a second audit.

The pattern is ADR-0221 §5's, applied for its reason rather than by analogy: that
section closes its own three cases with *"no implementation, setting or later lane
adds a fourth without the ADR that decides it"*, because a vocabulary that grows by
implementation grows without anyone deciding what the new member means. An envelope
is the same object at one level up. The whole of #1908's sequencing rests on later
milestones adding *kinds* — *"never a new seam"* — and a closed enumeration is what
makes that promise mechanical rather than aspirational.

**Record-not-payload is the property the direction is bought for**, and #1844 says
why: *"any sequence of them still produces one supply of stamped records and
everything downstream is unchanged: the disclosure subtraction runs over the union,
external marks propagate, the policy gate still defers what rests on attested
material, and citations still resolve."* It is also why a tool cannot be the
mechanism. ADR-0170 §5a renders the step account from four closed vocabularies and
*"passes none of that free text through"*, because *"a tool's result is a JSON
payload with no per-span provenance"*; ADR-0208 §1 rules that *"A component on the
turn path that wants records the supply does not hold does not obtain them by
invoking a tool"*. This ADR does not relax either sentence — it satisfies both by
not being a tool.

### 2. The two kinds admitted now, and why they ship together

> **Normative.** The enumeration's two members are `SIGHTED_QUERY` and
> `CITATION_HOP`.

> **Normative.** A `SIGHTED_QUERY` ask carries a **query** the planner composed. The
> loop services it by calling `assemble_by_band` over that query under §6's budget,
> with the band precedence, per-band composition and kind selection of the retrieval
> stage's own read unchanged (ADR-0072 §5, ADR-0113, ADR-0187 §4). It is a relevance
> selection and §13 records it as one.

> **Normative.** A `CITATION_HOP` ask carries one or more **labels** the planner was
> shown. The loop resolves each label **in code** to the record it labelled, reads
> that record's own `Provenance.evidence`, and resolves those identifiers through
> `MemoryStore.get_many`. It selects nothing by relevance: it is a **keyed load** in
> exactly ADR-0208 §1's sense, *"records the turn already names, fetched by
> identifier"*, and §13 records that it needs no supersession for that reason.

> **Normative.** One emission may carry **at most one ask of each kind**, and is
> serviced **once**. Two asks of one kind is not an emission this ADR admits; nor is
> a second emission on the same turn, which is re-planning and is §12's.

**They ship together because the replay measured them recovering different
questions.** On the hop territory at one read the union is 63.3% against 50.0% and
44.7% separately, and the overlap is 31.3% — *"28 questions only the query got, 20
only the hop"*. Building one and sequencing the other would forgo a documented
half of the recovery for no saving, since the two share every downstream mechanism
this ADR states: one request object, one budget, one subtraction, one audit.

**And the hop is not sequenced first**, which the replay is equally direct about:
*"Do not sequence the citation hop first. Its distinguishing property is real, but
with a real planner it converts 47.6% and its failure mode is that the planner names
an episode (30%) or nothing (32%) — the 'which belief do I open' problem is the same
unsolved trigger problem in a different costume."* A design that shipped the hop
alone would be a design whose measured failure mode is the one thing §8 exists to
instrument, with nothing beside it to compare against.

**The hop's distinguishing property is why it is in the enumeration at all.** #1844:
it is *"**not a search**, so the reply's vocabulary never has to match anything; and
it reaches the exchange by pointer, which is the only mechanism that answers 'which
lender did you recommend?'"* This is ADR-0158's Alternative 6, which that ADR
rejected *for its own consumer* — the LoCoMo misses are by definition questions no
belief cites the gold for — and left *"fully available"*. Sighted, it is a different
proposition from the blind expansion #1844 refuses: 30 beliefs × 64 citations is
*"~1,920 candidates against a `get_many` that is contractually uncapped"*, where the
measured sighted shape is one or two beliefs citing one to three episodes each.

### 3. The namer rule is the invariant, and no identifier crosses the seam

> **Normative.** **The namer may be data, or the user, or the model pointing outward
> — never the model pointing inward.** This is the invariant every kind of this
> envelope is built under, and no kind is admitted that violates it.

> **Normative.** **No record identifier is rendered to a model, and none is accepted
> from one.** A `CITATION_HOP` ask names a **label** from the labelled set the turn
> rendered, and nothing else. The loop maps a label to the identifier of the record
> it actually labelled; it never parses an identifier out of model output, and it
> never treats a model-supplied string as an identifier.

> **Normative.** **A record's label is its position in the sequence the loop
> handed the planner.** The label of the record at 1-based index *n* of
> `Planner.plan`'s `memories` is the ASCII string `M` followed by *n* in decimal with
> no padding. That is the whole of the scheme: it is fixed here, it is the same on
> both sides of the seam, and no later lane substitutes another spelling, adds a
> prefix per group, or makes it configurable.

> **Normative.** **Both sides derive the label from `memories` and neither consults
> the other.** The planner renders each record's label from the sequence it was
> given; the loop resolves a label by parsing *n* and indexing **the very sequence it
> passed on this call**. No mapping, table or identifier crosses between `planning`
> and `orchestration`, and neither package imports a name from the other to agree on
> one. The ordered `memories` sequence is already the contract both hold — ADR-0074
> §5 and ADR-0158 §5 fix its order and its grouping — and this decision adds a rule
> for reading it rather than a channel for sharing it.

> **Normative.** **A label outside the shown set resolves to nothing.** A string
> that does not match the form, an *n* below 1 or beyond the sequence's length, and a
> label whose record is no longer live all resolve to nothing. Each is discarded
> silently — not an error, not a park, not a degradation of the turn — and recorded
> in §9's audit as dropped. `get_many`'s existing behaviour supplies the last case:
> *"An id that does not resolve is **simply missing from the mapping**."*

> **Normative.** A `CITATION_HOP` follows **only** the labelled record's own stored
> `Provenance.evidence`. It does not follow the evidence of a record reached by that
> hop, and no lane adds a second level: that is iteration, and it is §12's.

**The ordinal is what keeps the label from becoming a private protocol between two
subsystems.** A scheme in which `planning` invents labels and `orchestration` resolves
them would need the two to agree on an allocation that appears in no contract — two
implementations could label the same `memories` differently, or coordinate privately
across packages, which is the import golden rule 1 forbids and which no test in either
package would catch. Deriving the label from the position in the sequence the loop
itself passed removes the agreement entirely: there is nothing to share, because both
sides are reading the same ordered value, and the loop resolves against its own copy.
It also makes the failure mode inert — a label the planner invents is an index, and an
index outside the range it was shown resolves to nothing by the clause above.

**It costs one property, and the cost is named.** The label is meaningful only within
the turn that rendered it, so no label survives to a later turn and none is
persistable as a reference. That is the correct behaviour rather than a limitation to
repair: the resolvable set is exactly what this turn showed, which is §3's whole point,
and a label that outlived its turn would be an identifier by another name.

This is the observer's own scheme, applied to the supply. `learning/observer.py`
states the reason in terms — *"**The citations are ours, never the model's.** The
prompt labels each episode and the model cites labels; this module maps every label
back to the id of the episode it actually read. A model that can write an id can
write one for an episode it never saw."* — and ADR-0208 §1 is the same line drawn
against a tool. #1844 gives the general rule and this ADR ratifies it as an
invariant rather than an argument, because #1908 makes every later milestone inherit
it and an invariant that lives only in a design note is not inheritable.

**The rule is what makes the hop safe rather than what makes it awkward.** The
failure a fabricated identifier produces is not a crash — `get_many` would simply
omit it — but a system in which the model can *steer what it is shown* by naming
records it never saw. The label discipline forecloses that by construction: the
resolvable set is exactly what the loop chose to render, so the widest possible
abuse of the mechanism is asking for something already on screen.

### 4. Where the emission lives: an additive, defaulted field on `ActionPlan`

> **Normative.** `core/types.py` gains one `StrEnum`, `ReadKind`, with two members —
> `SIGHTED_QUERY`, valued `sighted_query`, and `CITATION_HOP`, valued `citation_hop`
> — and two frozen models, `ReadAsk` and `ReadRequest`. `ActionPlan` gains one
> field, `read_request: ReadRequest | None`, defaulting to `None`. `Planner.plan`'s
> signature is **unchanged**, and no Protocol gains a member.

> **Normative.** `None` means **the planner asked for no read**, and it is the
> semantically correct answer for a planner that knows nothing of this envelope. No
> implementation reads `None` as an error, a degradation, or an instruction to
> service a default read.

> **Normative.** `ReadKind`'s members and their serialised values are fixed here.
> The vocabulary is **added to and never renamed**: no later ADR removes a member,
> renames one, gives one a second spelling, or replaces this enum with a
> differently-named one for the same question.

> **Normative.** A `ReadAsk` states one kind and the argument that kind takes: a
> non-blank query for `SIGHTED_QUERY` and no labels; at least one label for
> `CITATION_HOP` and no query. A `ReadRequest` carries at least one ask and at most
> one of each kind. Both refuse mutation and refuse unknown fields, and each of these
> conditions is enforced by the model rather than by its callers — an emission that
> fails any of them is not a request this ADR admits.

> **Normative.** **`PlanExport.schema_version` becomes `Literal[3]`.** `PlanExport`
> carries `plans: tuple[ActionPlan, ...]`, so a member of the portable document
> changing shape is what that field exists to announce (ADR-0039 §10, ADR-0014 §5).
> The annotation is edited rather than defaulted, exactly as ADR-0039 §10 made it, so
> a document of the older shape does not validate against this contract at all.

> **Normative.** **No migration is owed, and not because no v2 export exists.**
> `PlanStore` offers `export` and no `import`, `restore` or `load`, so nothing in this
> system ever validates a `PlanExport` it did not just construct. ADR-0039 §10's rule
> carries forward unchanged and widens by one value: **an export of an earlier shape
> is not readable by this contract at any version**, and if an import path is ever
> contracted, accepting or refusing one is that ADR's decision and is not settled
> here.

> **Normative.** A `ReadAsk` is **not a `PlanStep`**, and nothing drives it. It is
> not selected against the capability vocabulary, not resolved to a tool, not ruled
> on by the permission gate, and never reaches `StepExecutor` or `ExecutionState`.
> Reading the owner's own store is not an act in the world, and no lane routes it
> through the machinery that decides acts.

**`ActionPlan` is the right home because the request is part of what the planner
decided.** ADR-0014 §2 makes the plan *"an auditable record of a decision"*, and a
turn on which the planner judged its supply insufficient and named a read decided
exactly that. The plan already reaches the durable planning store and the audit
surface, so §9's record has somewhere to be without a second channel.

**The export version moves because the export is the one durable surface `ActionPlan`
crosses, and this ADR nearly missed it.** `PROTOCOL_VERSION` does not move —
`ActionPlan` reaches neither `wire/` nor `service/` — and it would have been easy to
read that as "no version moves". `PlanExport` is the counterexample, and the corpus
has already ruled this exact case twice: ADR-0039 §10 moved the field to 2 because
`StepExecution` *"is inside the export, so its shape changing is exactly what the
version exists to announce"*, and ADR-0212 §8 moved `ConversationExport`'s for a
member gaining one field. A defaulted field on a frozen model is still a shape change
to every document that carries it, and `extra="forbid"` is what makes the mislabelling
concrete: a reader validating an older-shaped document against the new contract, or
the reverse, rejects it. ADR-0039 §10 called the annotation edit *"the intended
friction"*, and this is the friction working.

**The default is what makes this additive rather than breaking, and it is right on
the merits rather than merely convenient.** Every existing `Planner` implementation
and every canonical fake keeps compiling and keeps meaning what it meant: a planner
that does not emit a request is a planner that did not ask for a read, which is the
truth about it. Contrast the alternative of widening `Planner.plan`'s **return** to a
tuple or a wrapper: that changes a Protocol's signature, breaks every implementation,
every fake and every call site at once, and buys nothing this field does not
already buy. The `extra="forbid"` on `ActionPlan` is why the field must be declared
rather than attached, and `frozen=True` is why the emission cannot be edited after
the plan records it.

**ADR-0211 §1 is the precedent for the shape and the counter-precedent for the
default**, and the difference is worth stating. That decision made `capabilities` a
**required** input with no default, because a caller that forgot it *"would be handed
the empty one, under which every goal requiring an act declines: a system that
silently refuses to act at all"* — a silent, invisible regression. The failure mode
here is the opposite: an omitted request means no extra read, which is precisely the
system as it stands today and is visible in §9's audit as a turn that did not fire.
There is nothing to make loud.

### 5. Where the servicer runs, and what it may not be

> **Normative.** The request is serviced in `ai_assistant.orchestration`, inside the
> turn, **after** the planner returns and **before** the `TurnResult` that turn
> produces is constructed. The `TurnResult` is constructed once, over the final
> union; no implementation constructs one and then edits it, and none exists in an
> intermediate state any other stage can observe.

> **Normative.** The servicer is not the composing stage and adds nothing to it.
> ADR-0170 §2's clause — the composing stage *"performs no second context assembly
> and no second retrieval"* and consumes *"no `ContextProvider` and no
> `MemoryStore`"* — binds unchanged, and this ADR gives that stage no new
> collaborator. What the composing stage sees is what it has always seen: the
> `TurnResult` the turn produced.

> **Normative.** The servicer is not a tool, is not registered, advertises no
> capability, and is reachable through no `ToolRegistry`. ADR-0208 §1's second
> clause — that no lane registers a tool whose implementation reads a `MemoryStore`
> into any registry the turn path selects from — binds unchanged and is not
> approached.

> **Normative.** A servicing failure **degrades the turn and never fails it**. A
> failed or partial read leaves the supply as planning saw it, the turn composes
> from it, and the audit records what was asked and that nothing came back — which §9
> fixes as every count zero, a partial read distinguished from a total one by its
> failure fields alone. No implementation raises out of the turn, parks the turn, or
> asks the user anything on account of a read that did not land.

> **Normative.** **A read request is not serviced on an operation whose output
> channel's audience is unbounded** (ADR-0199 §1, declared as ADR-0200 §3 declares
> `converse_spoken`'s). On such an operation the servicer does nothing, the supply is
> the three groups ADR-0203 §1 narrowed, and §9's audit records the emission and that
> it was not serviced. A planner on such a turn is not told that its request will not
> be serviced, and no lane suppresses the emission itself: what is scoped is the
> **servicing**, so the trigger goes on being measured on every channel.

> **Normative.** No lane services a request on such an operation on the ground that
> the subtraction left the planner short, that the reply will otherwise be thin, or
> that the read would be harmless. That is the case §12 defers, and it is the one
> ADR-0203 §2's backfill clause is about.

**The channel scoping is the whole of this ADR's answer to ADR-0203 §2, and it is
taken rather than argued around.** §2 forbids an implementation that *"widens, re-runs
or re-parameterises retrieval to replace what the subtraction removed"*, and its
reasoning names the exact trap: *"A lane that noticed a spoken turn retrieving twelve
records and planning over four would reasonably reach for a second read to fill the
budget. That read is a second retrieval, which the clause above forbids, and it is
worse than that: to be useful it would have to ask for 'more like these, but
speakable', which is a retrieval shaped by what was withheld."*

**A planner-emitted read on such a turn is not distinguishable from that backfill,
and this ADR does not claim it is.** The planner never sees the withheld records —
but on an unbounded-audience operation it judges sufficiency over a supply the
subtraction has already thinned, so the hole is an input to the emission even though
the content is not. A design that serviced the request there would be asking a model
to notice a gap the withholding created and then reading to fill it, which is §2's
sentence with the intent removed. Refusing to service it on that channel is the
fail-closed answer, and it is why §13 records **no** supersession of ADR-0203: §§1
and 2 bind an operation this envelope does not run on.

**What it costs is stated rather than minimised.** A spoken turn gets no sighted read
in milestone 1, so the mechanism's benefit lands first on the channel that is easiest
to measure and hardest to leak through. That is a real limitation and #1908's exit
for this milestone does not require the spoken channel; ADR-0203 §2's own accepted
cost — *"A spoken turn may reach the planner with fewer records than a typed one for
the same utterance; that is the decision working"* — is inherited unchanged rather
than eroded by a mechanism that quietly refills it.

**This placement is the one that satisfies every existing clause at once, and #1732
asked for it to be argued rather than assumed.** Its point 3 names the tension
exactly — ADR-0170 §2's "no second retrieval" clause *"binds the composing stage; a
loop-level second read before composing is a stacked addition to argue in text, not
assume"*. Read against the tree, the clause is stated over the stage and over the
collaborators the stage holds, and this ADR gives the stage neither a
`MemoryStore` nor a second read; the loop, which has held one since leg 1, performs
it. The composing stage's guarantee is untouched in text and in effect.

**And the failure posture follows the archive's**, for the same reason ADR-0225 §2
gives: a turn that answered from the supply it had is a worse turn, not a broken
one, and a mechanism whose whole purpose is a marginal improvement in reach must
never be able to take the reply down with it.

### 6. One read, one budget, one bound

> **Normative.** One emission is serviced **once** per turn. The servicer performs no
> second pass, and no configuration, setting or later lane makes the count
> configurable without the ADR that decides it (§12).

> **Normative.** The whole emission shares **one record budget of ten records**,
> counted **after** the deduplication of §7 — that is, ten records that were not
> already in the turn's supply. Where both kinds are asked they draw on the one
> budget rather than on a share each.

> **Normative.** **The citation hop is serviced first, and the sighted query fills
> what remains.** Where the hop exhausts the budget the query is serviced with
> whatever is left, which may be nothing, and §9's audit records the truncation.
> Within the hop, labels are followed in the order the ask names them and each
> record's evidence in the order that record stores it; within the query, records
> arrive in the order `assemble_by_band` returns them, which is ADR-0072 §5's band
> precedence and is already ratified. What this fixes is the **order and the
> precedence**: given one request, one pre-servicing supply and one set of candidates,
> two conforming implementations append the same records in the same order. Which
> records survive depends on that supply as well as on the request, because §7
> deduplicates against it and this section counts the budget after that deduplication.

> **Normative.** **No cross-call read consistency is promised here, and ADR-0113 §5
> is inherited rather than closed.** A `SIGHTED_QUERY` reaches the store through
> `assemble_by_band`, which is several `MemoryStore.search` calls, and §5 rules that
> *"This ADR adds no multi-band snapshot and no cross-call read consistency of any
> kind"* and that a record changing band between two of a turn's calls *"may instead
> be **missed** by all of them. That is accepted, not closed"*. The same is accepted
> here: no snapshot is added, no consumer-side rule recovers a record no call
> returned, and no lane reads a thin fourth group as evidence the store held nothing
> more. So the ordering clause above is a statement about a fixed candidate set and
> never a promise that two runs over a concurrently-written store see one.

> **Normative.** A `CITATION_HOP` ask names **at most two labels**, and the evidence
> of the records they resolve to is drawn under the same budget of ten. No
> implementation reads `Provenance.evidence` for a record no label named.

> **Normative.** The budget is a **second budget and never a share of the first**.
> It does not reduce, borrow from, or draw against `RETRIEVAL_LIMIT` or
> `EPISODIC_SUPPLEMENT_LIMIT`, and no lane funds it by lowering either.

**The cross-kind precedence is ratified here rather than left to a lane, because it
decides what reaches the prompt.** ADR-0158 treats exactly this kind of ordering as a
decision — *"Position is how this corpus expresses precedence into a prompt"* — and
under one shared budget the fill order is not a detail but a policy: the two kinds
compete for the same ten slots, and either order satisfies every other clause of this
section while producing a different fourth group, a different prompt and a different
audit.

**The hop goes first because it is the capped read and the one the query cannot
substitute for.** Its size is bounded by §2's two-label cap, and the shape the replay
measured behind that cap is small — one or two beliefs citing one to three episodes
each. It is **not** guaranteed small: `MAX_EVIDENCE_CITATIONS` is 64, so two labels
may resolve to ten distinct live evidence records and take the whole budget, leaving
the query none. That is permitted by the truncation clause above and asserted by
§11's seventh test, and it is stated here as an accepted cost rather than glossed.

**The alternative is worse in the case that recurs.** A sighted query can return the
whole budget on *every* firing, so query-first would starve the hop routinely rather
than exceptionally, and would quietly reduce the envelope to its weaker half — on the
hop territory the query alone reaches 50.0% where the union reaches 63.3%. Ordering
the capped read ahead of the uncapped one makes the union the *measured* union in the
ordinary case, and gives the query up only where a hop genuinely reached ten records.

**Ten is a measured figure rather than a judged one, from three directions.** The
replay's oracle shape is *"311/349 need **exactly one** belief, 29 need two, 9 need
three"*, and #1844 predicts *"two to six records"* — ten covers the measured
distribution with room and cuts off the tail that made blind expansion unaffordable,
where two beliefs at `MAX_EVIDENCE_CITATIONS` would be 128 records. Two labels is the
figure the replay's own real arm used (*"asked to name ≤2"*), so the conversion it
measured, 47.6%, is the conversion of the bound this section sets rather than of a
looser one. And ten is a prompt size this system has shipped: it is exactly what
`EPISODIC_SUPPLEMENT_LIMIT` carried for the whole of pilot-5, before ADR-0224 moved
it to 30.

**The second-budget rule is ADR-0158 §3's refusal, inherited for its own reason.**
That decision refuses a share because `RETRIEVAL_LIMIT`'s move *"was bought for
beliefs on #1029's rank-miss measurement, and a share hands part of it back on no
measurement — worst in precisely the deployments where the belief layer is
working"*. Every word of that applies to funding this envelope out of either
existing budget, and ADR-0224 has just bought the episodic one on a measurement of
its own. Two budgets cost prompt size, which is the honest cost, and §9 is where it
is watched.

**One read is what the evidence supports and the bound is not arbitrary
conservatism.** The replay's decisive finding is *"**One read.**"*, with the second
and third adding 10.0pt then 4.6pt on the miss set — real, diminishing, and *"nothing
needing re-planning"*. Servicing one emission once is also what keeps this milestone
inside ADR-0014 §2's plan-once model, which §12 defers rather than disturbs.

### 7. The union: the group, the deduplication, and what the evaluation ranges over

> **Normative.** A record the servicer returns that the supply already holds is
> **deduplicated out**, and the copy the supply already held keeps its position. This
> is ADR-0158 §4's rule applied to a fourth group, for its reason.

> **Normative.** **The deduplication ranges over the whole union and not only against
> the pre-servicing supply.** A record **both kinds** reach — a belief's cited evidence
> that the sighted query also returns, held by none of the three groups planning saw —
> enters the fourth group **once**, at the position §6's precedence gives its first
> arrival, which is the hop's; the second arrival is deduplicated out and **consumes no
> slot of the budget**. A servicer seeding its seen set from the supply alone would
> satisfy the clause above and still render one record twice and spend two of the ten
> on it, which is exactly what the deduplicated union below forbids — so the rule is
> stated over both directions rather than left to be inferred from the noun.

> **Normative.** The serviced records enter `memories` as a **fourth group, appended
> whole after the episodic supplement**, never interleaved. ADR-0074 §5's first
> group, the retrieved beliefs and ADR-0158 §4's supplement keep their positions,
> their order and their meanings.

> **Normative.** **`Planner.plan`'s `memories` still carries exactly three groups.**
> The planner is called before the servicer runs and receives what it receives
> today; ADR-0158 §5's three-group clause and its caution that an implementation
> *"may rely on the grouping and may not rely on a global relevance order"* bind on
> that parameter word for word. What widens in `Planner.plan` is its **return** —
> the `ActionPlan` may carry a `read_request` (§4) — and nothing about its input.

> **Normative.** **`TurnResult.memories` carries those same three groups in the same
> order and, on a turn that serviced a request, the fourth group appended after
> them.** On every other turn it is exactly the three it is today. This **partially
> supersedes ADR-0158 §5's sameness clause** — *"`TurnResult.memories` carries the
> same three groups in the same order as `Planner.plan`'s `memories`"* — in that one
> respect and no other (§13), and the grouping-not-ranking caution carries over to
> the fourth group unchanged: a consumer of `TurnResult.memories` may rely on the
> grouping and may not rely on a global relevance order.

> **Normative.** That the turn composes over more than the planner saw is the
> mechanism and not a side effect, and no lane closes the gap by re-calling the
> planner: §6 services one emission once and ADR-0014 §2's frozen plan stands (§12).

> **Normative.** The `TurnResult` is constructed once, over the deduplicated union,
> and the composing stage runs over that and nothing wider. Nothing is planned,
> composed or rendered over a supply wider than the one this section returns.

> **Normative.** **The servicer discards no record on the ground of its class.** It
> applies no placement test, no withholding test and no subtraction: every record it
> returns, after §6's budget and this section's deduplication, enters the fourth group
> and reaches the turn.

> **Normative.** **ADR-0204 §2's evaluation is taken once, over the turn's final
> supply.** On a turn that serviced a request, the final supply is the deduplicated
> union of all four groups and the evaluation is taken **after servicing**; on every
> other turn it is the three groups it is today and the evaluation is taken exactly
> where it is today. One evaluation, both of §2's terms, one supply — this clause
> moves **when** it is taken and nothing else about it.

> **Normative.** This **partially supersedes ADR-0204 §2's timing clause** — *"once,
> between retrieval and planning"* — and no other clause of §2 (§13). §2's set is
> untouched and needs no widening: ADR-0210 §1's bounded clause already ranges the
> evaluation over *"the whole supply as assembled and retrieved"*, and the serviced
> records are part of the supply the turn assembled. §2's *"once"* is kept in letter,
> so no implementation evaluates twice and none disjoins two evaluations' results.

> **Normative.** The fourth group also reaches **ADR-0204 §4's** first and second
> clauses, which freeze a bounded turn's `TurnResult` and the reply composed for it,
> and **that is recorded too** (§13). Its scope is what such a turn may *gain* and
> nothing else: §4's narrowing prohibition stands entire, and so do the plan, the step
> it drives and the plan persisted through `PlanStore.save_plan`.

> **Normative.** The value that evaluation produces is carried to capture exactly as
> ADR-0204 §2 requires, and an implementation reads it **once, after the one
> evaluation that set it**. A servicing that lands after that read under-fires the
> value on exactly the records the planner asked for, and is the failure this clause
> exists to forbid.

**Nothing of ADR-0203 moves, and the reason is §5's channel scoping.** ADR-0203 §1
and §2 bind an operation whose output channel's audience is unbounded; §5 refuses to
service a request on one. So the only turns this envelope's fourth group exists on
are bounded-audience turns — and on those, `BoundedAudienceSupply` *"hands the turn
back **everything it was given**"*, subtracting nothing. There is no subtraction for
a servicer to re-apply, no second filter application to justify, and nothing of
ADR-0203 to supersede.

**ADR-0210 §1 is likewise untouched, and this is the clause a reader should check.**
Its narrowed set governs the **unbounded** channel, which this envelope never reaches.
Its **bounded** clause is the one that governs here, and it already covers the fourth
group as written: on such an operation *"the evaluation is exactly ADR-0204 §2's and
§4's, over the whole supply as assembled and retrieved, first group included, with
nothing subtracted from that turn."* The serviced records are part of the supply the
turn assembled, so they are inside that set by its own words and no extension is
owed — which is precisely why the supersession above is scoped to §2's **timing** and
reaches neither §2's set nor ADR-0210 §1. An earlier draft of this ADR superseded §1
to put them there; that supersession
was **withdrawn** once §5 scoped the envelope off the unbounded channel, and it is
recorded here because a reader comparing drafts should see that the narrower design
removed a clause change rather than hid one.

**Why the timing moves rather than the servicer filtering, and why that is the honest
answer rather than the convenient one.** ADR-0204 §2 fixes its evaluation *"once,
between retrieval and planning"*, and a group that arrives after planning is outside
it. Three designs close the gap and two of them are worse. **Filter at the servicer** —
admit no record the evaluation would have found — needs no clause of §2 to move, but it
is a **second placement test at a new site**, and it applies that test on a bounded
channel, where §3 says a supply site *"applies this test to nothing"* and §4 says *"no
implementation narrows a bounded channel's supply on the strength of this ADR."* It
buys §2's timing by breaching §3 and §4, which is a worse trade and not a smaller one.
**Admit the group untested** — arguing §2's first term ranges over the supply *"as
assembled and retrieved"* and a serviced group is neither — is textually available and
is refused below on the laundering ground. **Move the timing**, narrowly and with the
record, leaves every substantive clause of the withholding corpus binding on more
material than before, and it is the one that is true to why §2 said what it said.

**§2's clause said "between retrieval and planning" because, when it was written,
retrieval was the last thing that added to a turn's supply.** That is the fact this
ADR changes. The clause's *purpose* — one evaluation, over everything the turn holds,
before the turn's value is captured — is not weakened by moving it; it is the only way
to keep it true. A supersession that moves a clause because its premise stopped holding
is what ADR-0070 §1 is for, and working around it with a second filter would have been
a way of not saying that out loud.

**What the evaluation protects is worth naming, because it is why this is normative and
not book-keeping.** `orchestration/engine.py` reads the value *"once, immediately after
the one evaluation that set it, so every capture below stamps the same turn's own
value"*, and `BoundedAudienceSupply`'s own docstring says why it must not under-fire:
*"#1708's laundering path runs entirely through this channel's captures"*. A bounded
turn that plans over withheld-class material captures a marked episode, and that mark
is what stops a later spoken turn reading it back. A serviced record that the
evaluation never saw is exactly that leak, reached by a new route — which is also why
admitting the fourth group untested is refused rather than deferred: it would reopen
#1708 by a route no clause of the corpus is watching.

**And nothing is narrowed to buy it.** The fourth group carries whatever the read
returned, withheld-class records included, exactly as the other three groups do on a
bounded channel. A sighted read is as wide as the read that precedes it and a hop
follows its evidence wherever it points; what changes is only that the turn's capture
records what stood in front of it. That is the same bargain §4 already struck for the
other three groups, extended to the fourth rather than a new one.

**A fourth group and not a merge**, because ADR-0158 §4's argument is positional:
*"Position is how this corpus expresses precedence into a prompt"*, and sorting kinds
together *"would restore §2's displacement in the renderer immediately after refusing
it in the reader"*. Appending is also what the renderer was written to expect —
`planning/planner.py` splits on the **leading run** of `EPISODIC` records, so a group
added at the tail cannot extend that run and cannot be misread as the conversation's
own turns. ADR-0158 §4's separator rule is evaluated over what precedes the
supplement, and a group appended after it leaves that condition untouched.

### 8. The trigger is first-class, and what the live audit can and cannot measure

> **Normative.** The trigger is the planner's own judgement that this turn's supply
> did not suffice, and it is **expressed by emitting a request and by nothing else**.
> There is no separate flag, no confidence score and no second seam: a turn on which
> `read_request` is not `None` is a turn the trigger fired on, and a turn on which it
> is `None` is a turn it did not.

> **Normative.** Every turn writes §9's audit record, **whether or not the trigger
> fired**. A record is written for a turn that asked for nothing, and it says so. An
> instrument that only records its positives cannot measure a fire rate.

> **Normative.** **The trigger has a third outcome, and it is neither a firing nor a
> non-firing.** A turn on which planning did not return a plan — the planner raised, or
> the turn ended before it returned — reached no judgement about its supply at all, so
> its record says the trigger was **not reached** rather than that it did not fire.
> Such a turn is in neither the fire rate's numerator nor its denominator; it is
> counted on its own, so that a deployment can see how many turns the instrument took
> no reading from rather than have them silently dilute the rate. A turn whose planner
> **did** return a plan carrying no request is recorded as a non-firing exactly as
> above: what separates it from a not-reached turn is that the planner returned, not
> that the turn went on to succeed.

> **Normative.** **The fire rate is a property of the planner a deployment runs, and
> no lane reports one without saying which planner produced it.** §4's field is
> additive and defaulted, so a `Planner` that knows nothing of this envelope conforms
> and returns no request on every turn; its non-firings are **constant rather than
> judged**, and the 0% such a deployment would read is a true statement about that
> planner rather than a reading of a trigger that is not there. The record carries no
> per-turn distinction between that and a judged non-firing, because one would have to
> be declared at the `Planner` seam — a Protocol addition this decision does not need
> and golden rule 5 puts behind its own ADR — and §12 defers it with what fires it.
> What keeps the live figure honest meanwhile is §10's order and this deployment's
> composition: `app/composition.py` wires exactly one `Planner`, and it is the one
> Lane A makes envelope-aware before Lane B's servicer and its audit exist at all.

> **Normative.** Every figure this audit supports is computed **over a population of
> turns** and is never a per-turn quantity. A turn contributes to a numerator or a
> denominator; it carries no rate of its own, and a turn on which the trigger rightly
> did not fire carries none at all. No lane reports any of these figures as a
> property of a single turn.

> **Normative.** The figures §9's record supports **on its own** are the **fire
> rate** and the **novelty rate**, and no lane calls either of them precision or
> recall. Precision and recall of the trigger additionally require, per turn, a
> **label** of whether that turn's supply in fact sufficed. §9's record does not
> carry one, no clause of this ADR obliges one, and no lane computes either figure
> from this record alone or reports one as though it had.

> **Normative.** No lane makes the trigger's firing conditional on a setting, a
> channel, a surface or a deployment flag. It fires where the planner judges the
> supply short, and its rate is therefore a property of the planner that the audit
> measures rather than a property of the configuration.

**What the live audit yields, and what it does not.** Per turn it records inputs;
over a population of turns those inputs yield the **fire rate** — the share emitting
a request, directly comparable to the replay's 13.6% — and the **yield**: how many
records came back, how many survived deduplication as genuinely new, and how many the
budget and the unresolved labels left behind.

**The novelty rate is a separate yield measure and is not a bound on precision in
either direction.** Novelty says a fired read returned records the supply did not
already hold. It does **not** say the supply was insufficient, that the new records
bore on the question, or that the reply was better for them. It runs above precision
where a planner emits a broad query on a perfectly sufficed turn and gets back one
irrelevant record it had not seen — a false fire scoring as novel. And it runs below
precision where a genuinely insufficient supply triggers a read that correctly fires
and returns only duplicates or nothing — a true fire scoring as zero. So no lane
reports novelty as an upper bound, a lower bound or a proxy for precision: it measures
what the read returned, and precision measures whether the trigger was right, and
those are two questions.

**Recall is further out of reach than precision, and for a structural reason rather
than a missing field.** Its denominator is the turns on which a read **would** have
helped — and on a turn where the trigger did not fire, nothing looked, so the system
never learns whether it should have. No enrichment of §9's record closes that: the
evidence does not exist on the turn. Closing it needs either a labelled corpus, which
the replay had because LoCoMo ships gold records and a live turn has not, or a
sampled shadow read on non-fired turns, which is a real per-turn spend and is
deferred by name in §12.

**This ADR states the limit rather than promising a figure the instrument cannot
produce.** The owner ruled the live audit is the trigger's instrument, and the honest
form of that ruling is an instrument whose readings are labelled with what they are.
A decision that claimed precision and recall here would be discovered to have claimed
them at the first attempt to report, and the number most worth watching — the fire
rate against the replay's 13.6% — is available on day one and needs no label at all.

**What the live figures are read against is the replay, and that is the point of
deploying rather than re-measuring.** The replay's arms *"ran on sonnet-5, a floor"*
against a pilot answered on opus-4-8, and its own Limits name the consequence: the
trigger *"might improve with the production planner — that is the one number most
worth re-measuring before ruling."* The owner ruled on 2026-09-02 that the live audit
is that re-measure. So a live fire rate near 13.6% says the production planner
behaves as the floor did; a materially different one is the finding, and either way
it arrives from real turns rather than from a second offline arm on the same corpus.

**#838's coverage layer is adjacent, undecided, and named.** Its table puts
sufficiency as *"the consumer (model judgment)"* and coverage as a *"mechanical
estimate from store aggregates"* that *"feeds the sufficiency layer so escalation is
an informed bet"* — and its own contract note is that a coverage read *"exists on no
current contract"* and owes its own ADR. This ADR decides the sufficiency layer's
emission and nothing above it. Whether the trigger is learnable from the supply alone
is #1908's standing question and stays open; §9's record is what a later answer will
be fitted against.

**#838's entitlement layer is untouched and must stay mechanical.** Its design
invariant — *"entitlement stays mechanical forever — arithmetic failures must never
depend on model judgment to be noticed"* — is not weakened by a model-judged
sufficiency trigger sitting above it, and no lane implements entitlement escalation
by making the planner ask twice.

### 9. The audit record

> **Normative.** Each turn records: whether a request was emitted, was not emitted, or
> was **not reached** in §8's sense; whether it was serviced or declined under §5's
> channel scoping; for each ask, its **kind**; how many records the servicing returned;
> how many of those were new after deduplication; how many the deduplication removed;
> how many labels resolved to nothing; whether the budget truncated a kind; whether the
> servicing failed; and, where it failed, whether **any read it had already performed
> had returned records** when it did. That second failure field is stated over reads
> and not over asks, because §6's sighted query is *several* `MemoryStore.search`
> calls: a query whose second band raises after its first returned is as partial as a
> hop that returned before a query raised, and a field keyed on asks would call the
> one-ask case a total failure. No count here is of a record the servicer refused on
> the ground of its class, because §7 admits no such refusal.

> **Normative.** **Every count above is taken over a servicing that completed, and
> never over a store call whose result §5 discarded.** §5 makes the servicing
> all-or-nothing — *"a failed **or partial** read leaves the supply as planning saw
> it"* — so a servicing that failed returned nothing to the turn and every count above
> is **zero**, the partial case included: where a hop returned records and the query
> then raised, §5 discards the hop's records with the rest and none of them is counted
> anywhere. *"How many records the servicing returned"* is therefore what a completed
> servicing carried into the union before deduplication, and it is never a per-ask
> tally of what each store call handed back. What represents a partial servicing is the
> **pair of failure fields** — that the servicing failed, and that a read it had
> already performed had returned records when it did — and that pair is deliberately
> the whole of it: a count of discarded records would report a yield on a turn §5
> defines as having received none, and would make §8's novelty rate a figure about
> reads the prompt never saw. §11's fourteenth test asserts both halves, over a
> failure between asks and a failure inside one.

> **Normative.** The record holds **counts and kinds**, and copies no text. It does
> not copy the query the planner composed, the labels it named, any `content` span,
> any excerpt or any rendering. The ask stays durable on the frozen `ActionPlan` (§4)
> and the record neither copies it nor points at it.

> **Normative.** **The only identifier the record carries is the ambient correlation
> identifier**, ADR-0119 §4's, which `core/correlation.py` mints and which *"cannot be
> supplied"*. The emitter **reads it with `current_correlation()` and attaches it under
> a fixed field on the event**; where it is `None` the field says the turn ran outside
> a correlated operation and the record is emitted regardless. It carries **no plan
> identifier, no goal identifier and no record identifier** — no value whose provenance
> is a caller's rather than this system's.

> **Normative.** The record is emitted **once per turn**, at any point in the turn
> after the servicing decision is known — or, on a turn where planning did not return a
> plan, at the point that turn ends — and its emission is conditioned on nothing: not
> on the plan being persisted, not on the turn completing, and not on capacity being
> admitted. A turn that fired and then failed for any reason still contributes its
> numerator; a turn that did not fire still contributes its denominator; and a turn
> that never reached the planner's judgement (§8) contributes to neither and is
> recorded as not reached.

> **Normative.** The event is emitted at **`INFO`**, and the every-turn obligation
> binds the **emitting code** rather than any deployment's log configuration. A
> deployment whose `log_level` is above `INFO` discards the event and loses the
> instrument along with it; that is the honest cost of putting the record in the log
> rather than in a store, it is stated here rather than discovered, and §12's deferred
> durable surface is what a deployment that cannot accept it fires.

> **Normative.** A planner-composed query is a **model completion with no recorded
> origin**, of the same class as `ActionPlan.rationale`. Wherever it is rendered,
> read back or exported it is treated as that class already is, and nothing in this
> ADR makes it speakable, placeable, or admissible to a channel a rationale is
> inadmissible to. No lane infers a placement for it by inspecting it.

> **Normative.** **The record is a structured log event**, emitted from
> `ai_assistant.orchestration` under one fixed event key, through
> the `structlog` seam `core/logging.py` configures. It is **Tier 2** in ADR-0004 §5's
> classification, and what keeps it inside that tier is the clauses below rather than
> the redaction net: the record carries *"identifiers, classes, and counts, never
> content"* — `core/logging.py`'s own statement of the primary defence — and it carries
> no identifier whose provenance is not this system's.

> **Normative.** This ADR adds **no audit Protocol, no audit store and no injected
> sink**, and no lane invents one. `AuditTrail` is the permissions trail and records
> permission decisions; this record is not one and does not go there. A **durable,
> queryable aggregation surface** for these events is deferred by name in §12 — a
> deployment that wants the fire rate over a retention window rather than out of its
> logs is what fires it, and it is a decision about storage rather than about this
> mechanism.

> **Normative.** These are the fields milestone 2 **raises rather than replaces**. An
> ADR admitting a second serviced emission per turn extends this record to account
> per emission and keeps every field's meaning; it does not rename them, drop them,
> or start a second audit beside this one.

The instrument has to exist at the first deploy rather than be added when someone
asks, because the question it answers — did the trigger fire, and did the read return
anything new — is unanswerable retrospectively. Recording the not-fired turns is what
turns a log into a denominator, and recording the declined ones is what keeps §5's
channel scoping visible rather than silent.

**Counts and no copy is ADR-0004 §7's minimisation taken seriously, and it closes a
hole an earlier draft of this section had.** That draft retained the planner's own
query text on the ground that it is the planner's composition rather than a record's
content. But nothing bounds what a planner may put in a query: it reads the rendered
supply, so a query may quote a sensitive span of a record verbatim, and the clause
forbidding record content and the clause retaining the query would then contradict
each other on the same bytes. Not copying it removes the contradiction: the ask is
retained exactly once, on the frozen `ActionPlan` the planning store already keeps,
under whatever retention that record has. A later reader who wants to judge whether a
reformulation was any good reads it there.

**And the record does not point at that plan either, which two review rounds are the
reason for.** A pointer would have to be `ActionPlan.id`, and `Identifier` admits any
non-blank encodable string, so a `Planner` — or `ModelBackedPlanner`'s own injectable
id factory — may supply one carrying content, which in a Tier 2 event is a Tier 1
leak. A draft answered that by logging the identifier only where this system minted
it; that is **not implementable**, because provenance cannot be recovered from the
value: a third-party planner may return a UUID-shaped id and the trusted factory may
be configured to return an address, so any format test either emits an untrusted value
or suppresses a trusted one. Carrying unforgeable provenance would mean putting it on
the contract, which is a Protocol change this decision does not need. So the record
carries no plan identifier at all. Joinability was never the pointer's job — the
correlation id is on this event and on every other line of the same turn — and what is
genuinely lost is the hop from an audit event to the plan's ask text, which §12 defers
along with the durable surface that would make such a join worth building.

**The correlation id is attached explicitly rather than inherited, and that is a fact
about the tree rather than a belt-and-braces choice.** `core/logging.py` configures
`structlog.contextvars.merge_contextvars`, and `core/correlation.py` keeps the id in
its **own** `ContextVar` — nothing binds one into the other. So an emitter that merely
logged and expected the id to arrive would emit an event with no correlation field at
all, and the audit's only identifier would be silently absent. Reading
`current_correlation()` at the emitter is one line and is what the clause requires;
ADR-0119 §4's carrier stays exactly where it is and gains nothing.

**Emitting unconditionally is what keeps the denominator honest.** A record gated on
the plan being persisted, or on the turn completing, would silently drop exactly the
turns most worth counting: `AssistantEngine` admits and reserves capacity **after** the
loop has planned, so a full system rejects a turn whose planner had already fired, and
a `PlanStore.save_plan` failure loses another. Under a gated record the fire rate would
read low by exactly the number of turns that went wrong. The record owes nothing to
those later stages, because it carries no reference into them.

**And naming the query's class is what stops the same laundering ADR-0203 §1
diagnosed.** That decision's reason is that *"a model completion is unplaceable"*, and
that storing a plan rationale inside an episode *"launders an unplaced value into a
placed one"*. A sighted query is the same kind of object produced at the same seam, so
it inherits the same treatment by name here rather than being discovered to need it
later — which is the whole of why this ADR says what the query *is* as well as where
it lives.

### 10. What the implementing lanes owe

> **Normative.** Two lanes, in order, each briefed from this ADR's merged text.

**Lane A — the types and the planner's emission.** `core/types.py` (`ReadKind`,
`ReadAsk`, `ReadRequest`, `ActionPlan`'s field with its validators, and
`PlanExport.schema_version` moving to `Literal[3]`), the widened
docstrings on `Planner.plan` and `TurnResult` in `core/protocols.py` and
`core/types.py`, §3's ordinal labelling of the supply in `planning/planner.py`, the
planner's emission and the prompt that asks for it, and the canonical fakes in
`ai_assistant.testing` that construct a request. **Not** the servicer.

> **Normative.** Lane A **extends the shared `PlannerContract` conformance suite**
> (`tests/planning/planner_contract.py`) for the widened return, so that every
> `Planner` implementation is held to it — the model-backed planner and the canonical
> fake alike, through the `Test…Contract` subclasses that already run it. A canonical
> fake updated without the suite is an unverified fake, which is the failure
> `CONTRIBUTING.md` → "Adding a Protocol: land the triad together" names.

**This is a widened contract and not a triad, and the difference decides what is
owed.** `CONTRIBUTING.md`'s triad is *"the required unit of work for a **new**
Protocol"*, and ADR-0137 §3 forbids splitting one; this ADR adds no Protocol, so no
triad exists to split and §3 has no subject here. What does exist is a `Planner`
Protocol whose documented return widens, and the corpus already carries the guardrail
for that — a shared `PlannerContract` run against both implementations — so the clause
above binds Lane A to it rather than leaving a widened meaning pinned by nothing. The
widening **is flagged as a breaking change under golden rule 5** — *"A Protocol change
is a breaking change. Flag it in your summary"* — and this ADR does not argue itself
out of that classification: the documented meaning of what `Planner.plan` returns
changes, `orchestration` consumes it, and the rule admits no semantic-widening
exception. ADR-0158 §5 flagged its own widening the same way. What the flag does
**not** assert is a compatibility break, and the two are separate facts worth stating
together: `Planner.plan`'s signature and its `memories` input are unchanged, and
`read_request` is additive and defaulted, so an existing `Planner` implementation that
returns an `ActionPlan` without one conforms exactly as it does today (§4). The flag
is why the conformance suite is extended; the compatibility fact is why no
implementation has to be rewritten to keep passing it.

**Lane B — the servicer, the union and the audit.** In `orchestration/`: the
servicing of both kinds, §3's label resolution by index into the sequence the loop
passed, §5's channel scoping and degradation posture, §6's budget and cross-kind
precedence, §7's deduplication, fourth group and post-servicing evaluation, and §9's
audit record — including that it is emitted once per turn and gated on nothing that
happens after the servicing decision.

> **Normative.** Neither lane invents a second label scheme, a shared label table, or
> any value crossing `planning` and `orchestration` other than the `memories`
> sequence and the `ActionPlan` that already cross it (§3).

> **Normative.** Neither lane moves `PROTOCOL_VERSION`. `ActionPlan` crosses neither
> `wire/` nor `service/` in the tree, no type this ADR adds does either, and no
> method is added to the engine surface. A lane that finds otherwise stops and says
> so rather than bumping it.

> **Normative.** Neither lane implements, prepares for, or leaves a hook for any
> mechanism §12 defers — and in particular neither admits an archive entry to a
> prompt, to the supply, or to a citation resolution (ADR-0225 §12).

**Two lanes and not one, under ADR-0137 §1.** Its test is where *substantial new
machinery* lands: *"A slice is one lane only if its implementation puts substantial
new machinery into at most one subsystem."* Lane B's servicer is new machinery in
`orchestration` — a servicing site, a label resolver, a budget, an audit. Lane A's
emission is new machinery in `planning`: a labelled rendering and a second thing the
planner's prompt asks for and its parser reads. Those are two subsystems, so §1
decomposes them, and §1's own carve-out does not rescue the pairing: what crosses
between them is not *"a call site updated, an argument threaded through"* but two
substantial pieces either of which could be got wrong alone.

**And §2 does not apply, which is worth saying because it is the clause that would
have made this one lane.** §2 widens the exception to *"the contract triad together
with its primary production implementation"* where a slice fails §1 *"and its
subsystems are separated by a contract"*. There is no triad here: this ADR adds **no
Protocol**, so no conformance suite and no canonical fake for a new contract are
owed, and §2's unit of work does not exist to ride with anything. The types Lane A
adds are `core/types.py` models with validators, which the ordinary rule covers.

**The order is Lane A then Lane B, and Lane A is useful alone.** A merged Lane A is a
planner that emits a request nothing services — which is exactly §4's default read
from the other side, and which lets the emission's shape be reviewed against real
prompts before any read fires. Lane B without Lane A would be a servicer with nothing
to service.

> **Normative.** §9's audit record lands with **Lane B**, and §8's every-turn
> obligation binds from the point a servicer exists. Between the two lanes there is no
> mechanism: a Lane A turn's `read_request` reaches no servicer, adds no record to any
> supply, changes no reply and changes nothing a capture records. Nothing is deployed
> that the audit cannot measure, because nothing is deployed.

**And the fire rate is not dark in that window either, which is the point of §4's
placement.** The ask is a field on the `ActionPlan`, and every turn's plan is
persisted through `PlanStore.save_plan`. So over the Lane-A-only window the numerator
and the denominator are both readable off the persisted plans — the turns whose plan
carries a request, over the turns whose plan does not — which is the same measurement
§9's record makes available live, and is why §9 needs to carry neither the ask nor a
pointer to it. A turn whose planner did not return a plan persists none, so it is
absent from that population exactly as §8's not-reached turns are excluded from the
live one. What only Lane B can add is the **yield**: what the servicing
returned, what deduplication removed, what a label failed to resolve. Those fields
are absent in that window because the events they describe have not happened.

### 11. The representative-input tests this decision owes

> **Normative.** The implementing lanes owe tests for each of the following, and each
> is a test over behaviour rather than over a call count.

1. **The reply-vocabulary question answers through the hop.** A conversation in which
   the user asks about one thing and the assistant's reply introduces a word the user
   never used; a later, different conversation asks about that word. The blind read
   returns a belief and not the exchange; the planner names that belief's label; the
   hop reaches the episode by pointer; and the answer carries it. This is the
   milestone's exit shape and the one test that fails if the hop is merely wired.
2. **A sufficed turn pays no read.** A turn whose supply answers the question emits
   no request, the servicer performs no store call, the supply is byte-for-byte the
   three groups it was, and the audit records a turn on which the trigger did not
   fire. Asserted over the audit and over the supply, not over a mock's call count.
3. **A label outside the shown set resolves to nothing.** A request naming a label
   the turn never rendered, a string that is not of the form, an ordinal past the
   sequence's end, a well-formed record identifier, and a label of a record that has
   since expired each add no record, fail no turn, raise nothing, and are recorded as
   dropped. No model-supplied string reaches `get_many` as an identifier.
4. **The label is an ordinal into the sequence the loop passed.** `M3` resolves to
   the third record of that turn's `memories` and to nothing else; the same planner
   output against a different supply resolves to different records; and the two
   packages agree with no shared table, asserted by resolving a request against a
   `memories` sequence the test constructs directly.
5. **An unbounded-audience operation services nothing.** A turn on `converse_spoken`
   whose planner emits a request reaches the composing stage with the three groups
   ADR-0203 §1 narrowed and no fourth one, performs no store read for the request,
   and records the emission as declined — asserted for a request of each kind, and
   asserted over the supply and the audit rather than over a call count.
6. **A serviced record still fires ADR-0204 §2's evaluation.** On a bounded-audience
   turn whose other three groups carry nothing of the kind, a record the servicing adds
   that ADR-0199 §3 withholds sets the value the capture records — and so, separately,
   does one the servicing adds that already carries the mark ADR-0217 moved into
   `MemoryBase.placement`, which is §2's second term. Both records reach the supply and
   the composing stage; neither is dropped. This fails on any implementation that
   evaluates before servicing, and it is the assertion standing between this ADR and
   #1708's laundering path.
7. **The hop is serviced before the query, and the budget truncates the query.** A
   request whose hop yields records and whose query would yield more than the
   remaining budget produces a fourth group holding the hop's records and exactly the
   remainder from the query, in that order, with the truncation in the audit. A hop
   that exhausts the budget leaves the query no slots and does not fail.
8. **The audit records a fired, a non-fired and a declined turn**, with the counts §9
   names; it copies no text, so neither a distinctive span of a returned record nor
   the planner's query string appears anywhere in it; it carries **no pointer to the
   plan** and no identifier but the correlation id; and that correlation id is present
   on the event and equal to the turn's. Asserted at the emitting seam through a
   capturing processor, so the test is about the code's obligation and not about a
   configured level.
9. **The audit carries no identifier a caller supplied.** A turn whose `Planner`
   returns a plan whose id is an address-shaped string emits a record in which that
   string appears nowhere — no plan id, no goal id, no record id — and the ambient
   correlation id is the only identifier on the event. Asserted over the emitted
   event's own fields, not over the redaction net.
10. **A turn that fired and then failed still counts, and a turn that never judged
    counts as neither.** Four cases, each emitting exactly one record. Two carry the
    fired fact and the servicing counts — a turn rejected for capacity, which
    `AssistantEngine` decides **after** the loop has planned and serviced, and a turn
    whose `PlanStore.save_plan` raises — and neither suppresses the record, so neither
    depresses the fire rate. The other two never reach a plan at all: one where
    `Planner.plan` **raises**, and one where the turn fails **before the planner is
    called** — `ToolRegistry.capabilities()` raising is the injectable case, and the
    loop reads it at `orchestration/loop.py`'s `capabilities = await
    self._registry.capabilities()` immediately above the `plan` call, with `_retrieve`
    and `_supplement` above that. Each emits exactly one record saying the trigger was
    **not reached** (§8) while the original failure still propagates, and the assertion
    places both turns in neither the numerator nor the denominator. Two arms and not
    one, because §8's not-reached case is stated over turns that ended without a plan
    rather than over the planner raising: an implementation that emitted the record
    only from a handler around `Planner.plan` would pass the first and silently drop
    the second, undercounting exactly the population the outcome exists to make
    visible. Together they are what stops a planner or a pre-planning outage from
    reading as a collapse in the fire rate.
11. **Every condition §4 puts on the models is refused by the models**, arm for arm,
    and none of them is left to a caller: a `ReadRequest` whose `asks` is empty; one
    carrying two asks of one kind; a `SIGHTED_QUERY` ask with a blank or
    whitespace-only query; one carrying a query **and** labels; a `CITATION_HOP` ask
    with no labels; one carrying labels **and** a query; a hop naming three labels; an
    unknown field on either model; and a mutation of either after construction. Each
    is asserted as a validation failure at construction, and the empty-request arm is
    the one worth naming: a `ReadRequest` that admitted no ask would be a non-`None`
    `read_request`, which §8 defines as a turn the trigger fired on, servicing nothing
    — a fire-rate numerator with no read under it.
12. **The budget and the bounds hold.** A servicing whose candidates exceed ten
    returns ten; a record already in the supply is deduplicated out with the original
    keeping its position, counting against nothing; and a record **both kinds** return
    — the hop's cited evidence that the query also finds, held by no group of the
    pre-servicing supply — appears in the fourth group exactly once, at the hop's
    position, with the query's copy consuming no slot of the ten. That third case is
    the one a servicer deduplicating only against the pre-servicing supply gets
    wrong. The ordering guarantee is
    asserted over a **fixed** candidate set: one request and one supply over a store
    that returns the same candidates twice produce the same group in the same order,
    and no test asserts that a concurrently-written store does — ADR-0113 §5's accepted
    miss is inherited, and §6 says so rather than pinning a guarantee the store does
    not offer.
13. **The fourth group is appended, not interleaved, and the planner never saw it.**
    The `memories` the planner was called with carries exactly the three groups
    ADR-0158 §5 fixes; the `TurnResult` the same turn returns carries those three, in
    that order and in those positions, followed by the serviced records whole; and
    `planning/planner.py`'s leading-`EPISODIC`-run split is unaffected by a group of
    episodes appended at the tail. On a turn that serviced nothing the two sequences
    are identical, which is ADR-0158 §5's clause where it still binds.
14. **A failed servicing degrades and does not fail, and a partial one leaves nothing
    behind.** A store that raises during servicing leaves the turn composing from the
    supply planning saw, reports the degradation, records what was asked and that
    nothing returned, and parks nothing. Asserted three times: once where the **first**
    store call raises; once where a request carrying **both** kinds has its hop return
    records and its query then raise; and once where a request carrying **only** a
    `SIGHTED_QUERY` has a later band of `assemble_by_band` raise after an earlier band
    returned records. The last two are the arms that distinguish §5's *"failed **or
    partial** read leaves the supply as planning saw it"* from a best-effort servicer,
    and the third is the one a failure field keyed on asks would get wrong: in each,
    the records that did come back do **not** reach the fourth group, the supply is
    byte-for-byte the three groups planning saw, and the audit records the degradation
    with no returned or new count rather than the successful read's — while recording
    that a read had already returned when the failure landed, which is §9's pair of
    failure fields and the only thing distinguishing these two records from the
    first's.
15. **The plan is still frozen and still auditable.** A plan carrying a request
    refuses mutation; a plan carrying none is the default; and a `ReadAsk` is never
    selected, ruled on or driven — asserted by a turn whose request names a query that
    reads like a tool call and which reaches no registry, no gate and no executor.
16. **The export carries the request and announces its shape.** A `PlanExport` whose
    plans carry a request round-trips through serialisation with the request intact
    and `schema_version` 3; a document labelled 2 does not validate as a `PlanExport`
    at all; and both conforming `PlanStore` implementations export the new version.

### 12. Deferred, by name, each with what fires it

- **Re-planning and iteration** (#1908 milestone 2, #242). A read that changes what
  is known may change the plan; ADR-0014 §2's frozen plan and one-plan-per-turn model
  stands untouched here, and §6 services one emission once. Fired by that milestone's
  own ADR, which #1908 calls *"the largest single decision on the track"*. The replay
  is why it is not this one: *"nothing needing re-planning."*
- **The outward fetch** (#1908 milestone 3, #1843). A kind naming a source outside
  the store. It is deferred for a reason that is not resource-shaped: #1844's *"one
  genuinely new risk"* is **a loop steered by what it fetched** — *"iteration one
  reads attacker-controlled content; iteration two decides what to fetch based on
  it… That is an exfiltration channel needing no write capability at all"*. The
  honest first rung is local files, because *"A steered loop that can only read the
  owner's own disk has no channel out"*. Web reach after that is ADR-0154's seam,
  which is designated *"on that basis and on no other"* and grants nothing standing:
  *"There is no first-use exemption, no configuration that grants a standing
  authorisation for a recipient."* ADR-0223 is the control that makes a tainted
  conversation ask — egress *"loses its automatic `ALLOW` on later turns"*, and in a
  deployment with a reader enabled this *"approaches 'every outward call in a
  conversation asks'"*. Fired by milestone 3.
- **Structured read keys and hybrid search** (#1908 milestone 4, #1874, ADR-0006 §5).
  A kind carrying a time window, participants, topics or the person a record is
  about, mapped onto `MemoryStore.search` filters; and lexical or hybrid ranking,
  which ADR-0006 §5 left as *"a plausible later enhancement"* and which nothing has
  moved. Fired by `track:memory` ratifying the store read each maps to; a kind here
  is inert until then.
- **The archive-fetch kind** (ADR-0225 §12). ADR-0225's own §12 anticipates this
  envelope as the likely shape and states the gate: *"Admitting an archive entry to a
  model prompt, to a turn's supply, or to a citation resolution takes an ADR that
  supersedes the relevant clause of §4."* **This ADR does not supersede that clause
  and admits no archive entry anywhere**, and §10's last clause binds the lanes to
  the same. Fired by the owner ruling the feed-back mechanism open.
- **Decomposition of a compound question** into several asks of one kind. §2 admits
  at most one ask per kind for this reason: decomposition is a different decision
  about how a question is split, not a larger budget. #1908 places it at milestone 2.
- **Servicing a request on a channel of unbounded audience** (§5). Deferred because
  ADR-0203 §2 forbids a read that replaces what the subtraction removed, and on such
  a turn the planner judges sufficiency over an already-narrowed supply. Fired by an
  ADR that answers §2's backfill question for a planner-emitted read — plausibly by
  showing the emission is independent of the withholding, which is a measurement the
  audit this ADR builds could supply. Not fired by a lane finding spoken replies thin.
- **A durable, queryable surface for §9's audit, and with it a join from an audit
  event to the plan whose ask it describes** — a store, a Protocol, an aggregation, a
  retention window. §9 puts the record in the Tier 2 log, which is what makes the fire
  rate available on day one with no contract added; what it does not give is a query,
  and it deliberately carries no plan identifier, because provenance for one cannot be
  established from an `Identifier` value and putting it on the contract is a Protocol
  change this decision does not need. A design that wants the join adds trustworthy
  provenance at the seam and decides where the record lives, together. Fired by a
  deployment that needs the figure over a retention window rather than out of its logs,
  or by milestone 2 needing to account per emission. Not fired by a lane finding logs
  inconvenient.
- **#838's coverage layer**, and whether the trigger is learnable from the supply
  alone. Fired by what §9's audit shows, or by #838's own ADR.
- **A sampled shadow read on turns the trigger did not fire on** — the only live
  mechanism §8 identifies for a recall denominator, and a real per-turn spend on
  turns the system has no reason to think need one. Fired by a decision that the
  recall figure is worth that cost, which this ADR does not take.
- **A per-turn distinction between a judged non-firing and a `Planner` that does not
  implement the emission at all** (§8). It would have to be declared at the `Planner`
  seam, which is a Protocol addition golden rule 5 puts behind its own ADR, and this
  system wires exactly one planner — `app/composition.py` constructs
  `ModelBackedPlanner` and nothing else — so the attribution is a fact about the
  configuration rather than about a turn. Fired by a deployment running more than one
  `Planner`, or a third-party one, where a fire rate has to be attributed across them.
  Not fired by a lane wanting a tidier field.
- **A second serviced emission, a configurable read count, or a per-surface
  deadline.** #1908 names the deadline as milestone 2's — *"a voice turn cannot
  afford three round trips"* — and §6 fixes the count at one until an ADR moves it.

### 13. Scope, and what this records against earlier ADRs

**This ADR partially supersedes three ratified ADRs, in four scopes, and no others**
— one scope of ADR-0208, two of ADR-0204, one of ADR-0158 — and every other clause it
cites binds as written. That is a classification
of this change and is therefore stated as prose rather than marked (ADR-0089 §1);
what follows is the working under ADR-0070 §1's test, for both, and for the clauses
a reader would most expect to have moved with them and which did not.

**ADR-0208 §1's one-site clause is partially superseded, and the scope is exactly
one of its five clauses.** It rules that the store is read for relevance *"at
exactly one site: the retrieval stage"*. §2's `SIGHTED_QUERY` selects records by
their bearing on a planner-composed query rather than by an identifier the turn
holds, which is that clause's own definition of a relevance selection, at a second
site. A reader holding only ADR-0208 would refuse to build it, so ADR-0070 §1's test
is met and §3's partial form is the sanctioned tool. ADR-0208's title carries the
same claim; ADR-0070 §1 permits no rewrite of ratified text, so the Status line and
a dated header note are where a reader learns, which is the mechanism ADR-0224 used
on ADR-0162.

**Its four other clauses stand, and two of them are why this decision is shaped as
it is.** The tool clauses — that `recall_memory` is not in the default registry, and
that no lane registers a store-reading tool into any registry the turn path selects
from — are honoured by §5 rather than merely avoided: this envelope is not a tool,
and *"A component on the turn path that wants records the supply does not hold does
not obtain them by invoking a tool"* is satisfied by a loop that reads the store it
already holds.

**ADR-0208 §8 deferred this decision, and §8 is discharged here rather than
overridden — the two are separate facts and #1913 asks for both to be stated.** §8
defers *"A planner-requested second retrieval into the supply — the useful half"* to
#1732 by name, and ADR-0208's own honest statement adds that it *"is not that
decision and may not be read as prejudging it in either direction."* So the sighted
query is the decision ADR-0208 reserved, not a breach of it. **That does not make
§1's clause inapplicable**, and this ADR declines the easier reading: §1 is stated
unconditionally, a reader holding only ADR-0208 would still refuse to open a second
relevance site, and ADR-0070 §1's test is about what a reader would do rather than
about what an author foresaw. A deferral of the *decision* and a normative clause
that forecloses it in the meantime are both real, so the deferral is discharged
**and** the clause is superseded — in that order, and neither instead of the other.

**§8's prohibition binds this ADR, and is obeyed.** Its deferral ends *"Nothing in
this ADR is cited toward that decision in either direction"*, so ADR-0208 is not an
argument here for building the envelope and this ADR does not offer it as one. The
justification is #1844's replay and #1908's charter, stated in Context and resting
on neither. ADR-0208 is cited only for what its clauses **rule**: the one-site clause
it loses, the keyed-load clause it keeps, the tool clauses §5 honours, and its
scoping sentence that *"One site is not one call"*.

**And §8 names five questions #1732 carries, each of which this ADR answers**, which
is what discharging the deferral means concretely: *"the envelope question"* (§§1–2),
*"the one-per-turn bound"* (§6), *"the ADR-0170 §2 reading a loop-level second read
needs"* (§5), *"where the disclosure filter runs over the union"* (§§5 and 7), and
*"the measurement that should decide whether it is worth building at all"* (§8 here,
read with Context's pricing and the owner's ruling that the live audit is the
instrument). The fourth of those gets the answer #1732 did not anticipate: the filter
does not run over the union, because §5 declines to service a request on the only
operations that have a filter at all, and on the operations that remain what runs over
the union is ADR-0204 §2's evaluation rather than a subtraction. #1913 closes against
this section.

**ADR-0208 §1's keyed-load clause is untouched and load-bearing.** It rules that *"A
**keyed load** — records the turn already names, fetched by identifier — is not a
second retrieval and is untouched in both directions"*. §2's `CITATION_HOP` is
precisely that: a label resolved in code to a record the loop already selected,
whose stored `Provenance.evidence` is read through `get_many` — the same member the
clause names `ConversationLifecycle.history` using. **So the hop needs no
supersession at all**, and the scope above is narrowed to the query alone for that
reason rather than by drafting convenience.

**ADR-0203 §§1 and 2 are untouched, and §5's channel scoping is the whole reason.**
Both bind an operation whose output channel's audience is unbounded, and §5 refuses to
service a request on one. So this envelope adds no supply member to a turn that has a
subtraction, applies no second filter, and cannot backfill what a subtraction removed.
§2's backfill clause is the one that decided the design rather than the one the design
had to work around: a planner judging sufficiency over an already-narrowed supply is
reading a hole the withholding made, and servicing that read is *"a retrieval shaped
by what was withheld"* however honestly it was meant.

**An earlier draft did it the other way, and recording that is the point of this
paragraph.** It serviced the request on every channel and re-applied the same
narrowing over the union, arguing that ADR-0203 §1 was extended in application rather
than superseded. That argument was available and this ADR does not rest on it: it
still owed a second filter application against a section titled *"One assembly, one
retrieval, one filter"*, and it still let the withholding shape what the planner asked
for. Scoping the envelope off the channel removes both objections and removes two
clause changes with them, which is why the narrower design is the better one rather
than merely the safer one.

**ADR-0210 §1 is untouched, including the clause an earlier draft superseded.** Its
narrowed set governs the unbounded channel this envelope never reaches. Its bounded
clause governs here and already covers the fourth group in its own words — *"over the
whole supply as assembled and retrieved, first group included, with nothing subtracted
from that turn"* — so §7's evaluation requirement is that clause applied, not extended.
That earlier draft's partial supersession of §1 was **withdrawn**, and §7 says so where
a reader will meet it. §1's third clause as ADR-0217 amended it is read with the field
where ADR-0217 moved it; this ADR neither restores the old name nor moves it again.

**ADR-0039 §10 is applied rather than superseded, and the working is shown because a
review round reached for the other answer.** §10 pinned `PlanExport.schema_version` to
`Literal[2]` and, in the same section, said what happens next: *"The cost is that every
future shape change edits the annotation, which is the intended friction — a version
that moves without anyone noticing is the failure this replaces."* A reader holding
ADR-0039 alone, making a shape change to a record the export carries, is instructed by
that sentence to edit the annotation, and writes `Literal[3]` — which is what §4
requires. Acting on §10 alone produces identical conduct before and after this ADR,
which is ADR-0070 §1's test and the reason no record is owed against ADR-0039.

**The corpus has already ruled this on the sibling export.** ADR-0212 §8 moved
`ConversationExport.schema_version` under §10's rule and recorded no supersession,
stating the test in terms: *"A reader holding ADR-0014 alone therefore acts identically
before and after, which is ADR-0070 §1's test and the reason nothing is recorded on
ADR-0014 here."* ADR-0039's `Status` is `Accepted` and carries no pair from that
change. The contrary reading takes `Literal[2]` as a permanent fact about the field
and leaves §10's friction clause out of the section it sits in.

**What would owe a record, and is not what §4 does**, is changing the *mechanism*:
returning the field to a default, admitting a range, or deciding a shape change need
not move it. §4 edits one integer exactly as §10 prescribes and carries §10's
"not readable at any version" rule forward with one more value inside it.

**ADR-0204 §2's timing clause is partially superseded, and the scope is that clause
and nothing else in §2.** §2's first clause rules that the turn's supply *"is evaluated
against ADR-0199 §3's withholding **once, between retrieval and planning**"*. §7 takes
that evaluation once over the turn's **final** supply, which on a turn that serviced a
request is after servicing. A reader holding only ADR-0204 evaluates before the fourth
group exists and records a value that is false of what the turn actually planned and
composed over; after this ADR, on such a turn, they do not. That is ADR-0070 §1's test,
and §3's partial form is the sanctioned tool.

**The scope is the timing and not the set, and the difference matters.** §2's set —
*"the one supply the turn already holds"*, read for the first term *"as assembled and
retrieved"* — already contains the serviced records, because they are part of the
supply the turn assembled; ADR-0210 §1's bounded clause says so in as many words,
*"over the whole supply as assembled and retrieved, first group included"*. So no
clause about **what** is evaluated moves, no term is added or dropped, the disjunction
is unchanged, §2's *"once"* is kept in letter, and the field and the stage that carries
the value to capture are exactly what ADR-0204 and ADR-0217 make them. What moves is one
adverbial phrase about **when**.

**Why that clause said what it said, and why moving it is the honest repair.** When
ADR-0204 was ratified, retrieval was the last thing that added to a turn's supply, so
*"between retrieval and planning"* and *"over everything the turn holds"* named the same
moment. This ADR makes them different moments. The clause's purpose is the second of
those, and honouring the letter of the first would defeat it — a value evaluated before
servicing is a value about a supply the turn did not run over. ADR-0070 §1's test is
what a reader holding the old text would do, and the reader who follows the letter here
under-fires exactly on the records the planner asked for.

**Not replaced — everything else of ADR-0204, and this list is the point of the narrow
scope.** §2's two terms, its disjunction, its *"once"*, its set, its exclusion of
content-reading and store queries, its rules for a parked turn and a routed pass, and
its carrying of the value to capture all bind whole. §1's field, as ADR-0217 moved it
into `MemoryBase.placement`, is untouched. **§3 is untouched entirely** — including its
third clause, that *"A supply site for a channel whose audience is bounded applies this
test to nothing"*, which the servicer obeys by applying no such test. **§4's narrowing
prohibition is untouched**, and its clause that *"no implementation narrows a bounded
channel's supply on the strength of this ADR"* is honoured in letter: §7 discards no
record on the ground of its class, and the fourth group carries withheld-class records
exactly as the other three do. (§4 is reached in a different respect — what a bounded
turn's `TurnResult` may *gain* — and that is recorded immediately below rather than
here, because it has nothing to do with §2's timing.) §5's ratchet, §6's residue,
§7's version footing and §8's tests bind
unchanged. ADR-0210 §1 and ADR-0217's amendments to ADR-0204 are untouched in both
directions.

**ADR-0204 §4 is reached as well, in one narrow respect, and recording it is the
conservative reading rather than the comfortable one.** §4's first clause rules that
on a bounded-audience operation *"the supply the turn runs over, the plan it produces,
the step that plan drives, the `TurnResult` it returns, the reply composed for it and
the plan persisted through `PlanStore.save_plan` are all exactly what they are
today"*, and its second that *"no `TurnOutcome`, `TurnResult` or `SpokenTurn` member
gains, loses or changes meaning"*. On a turn that serviced a request this ADR does
change three of those: the supply the turn composes over, the `TurnResult` it returns
and the reply composed from it, and `TurnResult.memories`' meaning with them. A
reader holding only ADR-0204 would refuse to append the fourth group, which is
ADR-0070 §1's test, so the record is owed even though §4's evident subject is
ADR-0204's own reach.

**The scope is those two clauses and only as this envelope reaches them.** The plan
the turn produces, the step that plan drives and the plan persisted through
`PlanStore.save_plan` are untouched — the planner runs before the servicer and its
output is frozen (ADR-0014 §2). **§4's narrowing prohibition is untouched entirely**,
and so is ADR-0203 §1's last clause standing whole beside it: nothing here removes a
record from a bounded channel's supply. No surface renders differently, no existing
field changes value, and no `TurnOutcome` or `SpokenTurn` member moves at all. And
on a turn whose planner emitted no request — every turn in the system until a lane
ships the emission — §4 binds exactly as written, which is why the scope names the
serviced turn rather than the channel.

**Two other designs were available and both were refused, which is why this record
exists rather than a workaround.** A **servicer-side filter** — admit no record §2's
evaluation would have found — moves no clause of §2, and an earlier draft of this ADR
took it. It is refused because it buys §2's timing with §3 and §4: discarding a record
at the servicer *is* a placement test at a supply site for a bounded channel, and *is* a
narrowing of a bounded channel's supply on the strength of this ADR, which those two
clauses forbid in terms. Trading one clause of ADR-0204 for two is not a smaller change.
**Admitting the group untested** — arguing §2's first term ranges over the supply *"as
assembled and retrieved"* and a serviced group is neither assembled nor retrieved — is
textually available and is refused on the ground `BoundedAudienceSupply`'s docstring
states: *"#1708's laundering path runs entirely through this channel's captures"*. A
bounded turn composing over a serviced withheld-class record would capture an unmarked
episode, and a later spoken turn may read it back. That is #1708 reopened by a new
route, and calling it "not in scope" would be the laundering, not the fix.

**And this is not the move ADR-0225 §16 records.** That section reached a guarantee
through an existing clause's own text rather than adding a conjunct to it, and an
earlier draft of this ADR cited it here. The citation is withdrawn: this ADR is not
reaching a guarantee through §2's existing text, it is moving §2's text, and saying so
is the whole of what ADR-0070 §1 asks. Recording the near-miss the other way round —
"we nearly worked around a clause instead of moving it" — is what a later reader should
see.

**ADR-0158 §5's sameness clause is partially superseded, and it is the third and
last scope this ADR moves.** §5 rules that *"`TurnResult.memories` carries the same
three groups in the same order as `Planner.plan`'s `memories`"*. §7 makes them differ
on exactly one kind of turn: the planner is called first and sees three groups, the
servicer runs after it, and the `TurnResult` the turn returns carries a fourth. A
reader holding only ADR-0158 builds a `TurnResult` from the planner's own sequence
and has nowhere to put the serviced records — they would refuse to build this — so
ADR-0070 §1's test is met and the partial form is the tool. The scope is that one
clause: **on a turn that serviced no request the two sequences are identical**, as
§5 requires, and on one that did they agree on the first three groups in the same
order and differ only by the appended fourth.

**Everything else of ADR-0158 §5 stands, and one clause of it is untouched precisely
because §7 was redrafted to leave it so.** §5's three-group clause governs
`Planner.plan`'s `memories`, and that parameter still carries three groups: the
planner is called before the servicer and receives what it receives today. An earlier
draft of this ADR widened it to four, which was both a needless contract change and
incoherent — the planner cannot receive a group produced from its own output. §5's
operative caution, that an implementation *"may rely on the grouping and may not rely
on a global relevance order"*, is carried word for word and extended to the fourth
group for `TurnResult`'s consumers. §5's degraded-read clause, its episodic-bound
clauses and its `Settings` prohibition are untouched.

**ADR-0158 §4 is extended in application and unchanged in text.** §4's rule is that
the order is tail, then beliefs, then supplement, *"appended whole, never
interleaved"*; §7 appends a fourth group after the third and disturbs neither the
rule nor any existing group's position, and §4's separator rule is evaluated over
what precedes the supplement. ADR-0074 §5's own clause is untouched: the tail is
still first, still in order, still bounded.

**ADR-0170 §2 and §5a are untouched, and §5a is relied on.** The composing stage
still holds no `MemoryStore`, performs no second retrieval, and renders step accounts
from closed vocabularies alone; §1's record-not-payload rule exists precisely so that
what this envelope returns is not the kind of thing §5a excludes.

**ADR-0225 §12 is untouched and its gate is not approached** (§10, §12).
**ADR-0014 §2's frozen plan is untouched** and §4 relies on it. **ADR-0211 §1 is
untouched**; §4 distinguishes its required-input reasoning rather than extending it.
**ADR-0154 and ADR-0223 are cited only in §12's deferral** and neither is moved.

**Everything else this ADR cites is used as ratified**: ADR-0004 §7; ADR-0006 §5;
ADR-0014 §§2 and 5; ADR-0015 §5; ADR-0016 §5; ADR-0027 and ADR-0070 §§1, 3 and 4 for
the supersession form; ADR-0039 §10; ADR-0072 §5; ADR-0086 §6; ADR-0088 and ADR-0089
for the citation forms and the marks; ADR-0098 §2; ADR-0113; ADR-0137 §§1 and 2;
ADR-0158 §§1, 3 and 4; ADR-0187 §4; ADR-0199 §§1, 3 and 5; ADR-0203 §§1 and 2;
ADR-0210 §1; ADR-0212 §8; ADR-0217 §2; ADR-0221 §5;
ADR-0224 §1; ADR-0225 §12.

**And one honest note on what this ADR is ratified without.** ADR-0015 §5 admits
that *"a contract ratified with no implementation contact is how a seam that does not
survive first use gets blessed"*, and this seam has had none: the replay drove a
model over rendered supplies, not this envelope over this loop. The mitigation is
§10's ordering — Lane A's emission lands before anything services it — and §11's
first test, which is written to fail if the mechanism is wired but not working.

## Consequences

- **The system gets its first sighted read of its own memory**, which is the finding
  #1844 called *"a larger constraint than any single retrieval defect filed to
  date"*. Every read before this one fires on the user's raw sentence.
- **The trigger becomes a number.** From the first deploy the fire rate and the yield
  are per-turn measurables, read against the replay's 13.6% floor. Precision and
  recall stay unavailable live, and §8 says so rather than implying otherwise.
- **The prompt grows by up to ten records on the bounded-audience turns that fire**,
  which the replay puts at about one turn in seven. That is the honest cost, and §9's
  audit is where a deployment watches it.
- **The audit reports a fire rate and a novelty rate, and calls them that.** Precision
  and recall need a per-turn label of whether the supply sufficed, which no live turn
  carries; §8 says so and §12 defers the two ways of obtaining one.
- **Three ADRs move, in four narrow scopes.** ADR-0208 §1's one site becomes
  two for relevance reads; ADR-0204 §2's evaluation moves from *"between retrieval and
  planning"* to the turn's final supply, and §4's freeze on a bounded turn's
  `TurnResult` and reply admits the fourth group; ADR-0158 §5's sameness clause admits
  a `TurnResult` carrying one group more than the planner saw. Nothing else in the
  withholding corpus moves — §5 keeps the envelope off the channel that corpus is
  mostly about, which is also why the spoken channel gains nothing from this milestone,
  stated as a cost in §5 rather than as a footnote; and on the bounded channel the
  corpus binds on **more** material after this ADR than before, because the evaluation
  now sees a group it did not.
- **A closed enumeration is now the growth path.** Milestones 2 through 4 add kinds
  and inherit §3's namer rule, §6's budget discipline, §7's union and §9's audit. A
  milestone that wanted a second *seam* would have to supersede §1 to get it, which
  is the point.
- **The envelope is worth about a point on the benchmark and is not justified by it.**
  #1908's caution is written into §Context, and this ADR would be the wrong decision
  if the benchmark were the argument.

## Alternatives considered

**Widen `Planner.plan`'s return type instead of `ActionPlan`.** Returning a tuple or
a wrapper makes the emission unmistakably distinct from the plan. Refused in §4: it
breaks every implementation, every canonical fake and every call site for a
distinction §4's own clause already draws in terms (a `ReadAsk` is not a `PlanStep`
and nothing drives it), and the additive field's default is not a compatibility
shim but the semantically correct answer for a planner that asked for nothing.

**Filter the fourth group at the servicer instead of moving ADR-0204 §2's timing.**
Discard, before the group is appended, any record ADR-0199 §3 withholds or that already
carries `MemoryBase.placement`'s `OWNER` reach; §2's evaluation then stays word for word
where it is, because a group provably holding no such record contributes nothing it
could have found. A draft of this ADR did exactly that. Refused in §7 and §13: the
discard is a placement test applied at a supply site for a **bounded** channel, which
ADR-0204 §3's third clause says *"applies this test to nothing"*, and it narrows that
channel's supply, which §4 forbids on the strength of that ADR in terms. It also makes
the sighted read narrower than the blind read that precedes it, for no gain the turn's
own audience can see. Buying one clause's timing with two clauses' substance is the
worse trade, and the record ADR-0070 §1 asks for is cheaper than the design that avoids
writing one.

**Admit the fourth group with no evaluation over it at all**, reading §2's first term's
*"as assembled and retrieved"* as excluding a group that is neither. Refused in §13: a
bounded turn composing over a serviced withheld-class record would capture an unmarked
episode, and `BoundedAudienceSupply`'s own docstring says where that goes — *"#1708's
laundering path runs entirely through this channel's captures"*. The reading is
textually available, which is exactly why it is named and rejected here rather than
left for someone to find.

**Ship the citation hop first and the sighted query later.** Refused in §2 on the
replay's explicit recommendation and its measurement: the two recover different
questions (either 63.3%, both 31.3%), and the hop alone converts 47.6% with a failure
mode — naming an episode, or naming nothing — that is the trigger problem this ADR
would then have shipped without an instrument for.

**Make the trigger a separate flag or a confidence score beside the request.**
Refused in §8. Two expressions of one judgement can disagree, and the audit would
then have to decide which of them the fire rate is about. Emitting a request *is* the
trigger, so the two cannot part company.

**Service the request on every channel, re-applying the same narrowing over the
union.** This is what an earlier draft of this ADR did, and it is the alternative a
reader is most likely to reach for, so §13 records it in full rather than leaving it
implicit. Refused twice over: it owes a second filter application against a section
titled *"One assembly, one retrieval, one filter"*, and — the deeper objection — on
an unbounded-audience turn the planner's sufficiency judgement is taken over a supply
the subtraction thinned, so the read it emits is shaped by what was withheld even
though the planner never saw it. §5's channel scoping refuses the case instead, which
costs the spoken channel this milestone and buys back two clause changes.

**Let the servicer apply its own disclosure decision over the records it fetched.**
Refused for a reason that survives the scoping above: it is a second decision
procedure over content, which ADR-0203 §1's second clause forbids in terms, and a
lane tempted by it on some later channel should find the refusal recorded here.

**Retain the planner's query text in the audit.** Refused in §9. Nothing bounds what
a planner may put in a query — it reads the rendered supply — so the clause retaining
the query and the clause forbidding record content would contradict each other on the
same bytes, and ADR-0004 §7 would be breached by a second retained copy. The ask stays
on the frozen plan, which the planning store already keeps, and the audit neither
copies it nor points at it — a pointer would have to be `ActionPlan.id`, whose
provenance §9 shows cannot be established.

**Let the implementing lane choose the cross-kind fill order.** Refused in §6. Under
one shared budget the order decides which records reach the prompt, and ADR-0158
treats prompt precedence as a decision rather than a detail. Left open, a lane that
serviced the query first could silently starve the hop and reduce the envelope to the
weaker of its two halves.

**Fund the envelope from the existing budgets** — take ten of `RETRIEVAL_LIMIT`'s
thirty, or of the supplement's. Refused in §6 for ADR-0158 §3's reason, sharpened by
ADR-0224 having just bought the episodic budget on a measurement: a share hands part
of a measured allocation back on no measurement, and it does so worst where the
existing layer is working.

**Re-measure the trigger offline against the production planner before ratifying.**
The replay's own Limits call it *"the one number most worth re-measuring before
ruling"*, and it is a real option. The owner ruled against it on 2026-09-02: a second
offline arm on the same corpus prices the same questions the same way, where a live
audit prices the turns the system actually gets. §8 is that ruling's mechanism, and
§13's last paragraph states what ratifying without implementation contact costs.

**Do not build the envelope at all, and take the trigger as the lane instead** — the
replay's own ordered recommendation. It remains the strongest argument against this
ADR and is not dismissed: with the measured trigger the envelope is worth about a
quarter of what a one-line allocation change was worth on the same corpus. Two things
answer it. The allocation has since been taken (ADR-0224), so it is no longer the
comparison — it is the baseline. And #838's trigger lane cannot be built without
somewhere for a fired trigger to go: a sufficiency judgement that services nothing is
unmeasurable for the same reason #1732's proposed measurement was. This ADR builds
the instrument the trigger lane will be evaluated with, which is why it comes first
even though the trigger is the larger problem.
