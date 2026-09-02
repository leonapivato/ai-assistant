# 226. The planner names one more read beside its plan, and the loop services it into the supply

- Status: Proposed
- Date: 2026-09-02
- **Supersedes one clause of one ADR:**
  [ADR-0208](0208-recall-memory-leaves-the-default-tool-set-and-the-turns-supply-is-retrieved-at-one-site.md)
  **partially**, in one scope — §1's **one-site clause**, *"On the turn path the
  assistant's own store is read **for relevance** … at exactly one site: the retrieval
  stage"*, in the single respect that §2's sighted query is a second such site (§13
  here). §1's four other clauses stand, and the keyed-load clause is not merely
  untouched but load-bearing: it is why §2's citation hop needs no supersession at
  all. **No other ADR is superseded in whole or in part**, and §13 shows the working
  for each one a reader would expect to be — ADR-0203, ADR-0210, ADR-0158 and
  ADR-0074 among them. §5's scoping of this envelope off the channel of unbounded
  audience is what keeps that list at one.
- **Decides a change to `src/ai_assistant/core/types.py`** — three added types and one
  additive, defaulted field on `ActionPlan` — and a widening of `Planner.plan`'s and
  `TurnResult`'s documented meaning in `src/ai_assistant/core/protocols.py`. It adds
  **no Protocol and no member to one**, and moves no `PROTOCOL_VERSION`: `ActionPlan`
  crosses neither `wire/` nor `service/` in the tree. **This ADR changes no code.**
  §10 states what the implementing lanes owe; nothing implements against it until it
  has merged ([ADR-0015](0015-simplify-the-agent-workflow.md) §5, golden rule 5).

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
> from it, and the audit records what was asked and that nothing came back. No
> implementation raises out of the turn, parks the turn, or asks the user anything
> on account of a read that did not land.

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
> precedence and is already ratified. The resulting fourth group is therefore a
> function of the request and the store alone, and two conforming implementations
> given one request over one store produce the same group in the same order.

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

**The hop goes first because it is the bounded read and the one the query cannot
substitute for.** Its size is fixed and small by §2's two-label cap and the measured
shape behind it — one or two beliefs citing one to three episodes each — so it can
never crowd the query out by much. A sighted query, by contrast, can return the whole
budget on its own, so putting it first would let a broad reformulation starve the hop
entirely and silently reduce the envelope to its weaker half: on the hop territory
the query alone reaches 50.0% where the union reaches 63.3%. Ordering the small
bounded read ahead of the large unbounded one is what makes the union the *measured*
union rather than whichever kind happened to run first.

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

> **Normative.** The serviced records enter `memories` as a **fourth group, appended
> whole after the episodic supplement**, never interleaved. ADR-0074 §5's first
> group, the retrieved beliefs and ADR-0158 §4's supplement keep their positions,
> their order and their meanings. `Planner.plan`'s and `TurnResult`'s documented
> `memories` widens from three groups to four, and a `Planner` implementation may
> rely on the grouping and may not rely on a global relevance order — ADR-0158 §5's
> clause, extended by one group and otherwise unchanged.

> **Normative.** The `TurnResult` is constructed once, over the deduplicated union,
> and the composing stage runs over that and nothing wider. Nothing is planned,
> composed or rendered over a supply wider than the one this section returns.

> **Normative.** ADR-0204 §2's evaluation — the boolean a bounded-audience turn's
> capture records — is taken over the **whole supply including the fourth group**,
> and is therefore taken **after** servicing. An implementation that evaluates before
> servicing and does not re-evaluate over the union under-fires the boolean on
> exactly the records the planner asked for.

**This section changes no ADR, and the reason is §5's channel scoping.** ADR-0203 §1
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
owed. An earlier draft of this ADR superseded §1 to put them there; that supersession
was **withdrawn** once §5 scoped the envelope off the unbounded channel, and it is
recorded here because a reader comparing drafts should see that the narrower design
removed a clause change rather than hid one.

**The ordering requirement above is the one real obligation this creates, and it is
not book-keeping.** `orchestration/engine.py` reads the boolean *"once, immediately
after the one evaluation that set it, so every capture below stamps the same turn's
own value"*. If servicing lands after that read, a record the planner asked for and
that ADR-0199 §3 would withhold sets nothing — and `BoundedAudienceSupply`'s own
docstring says why that matters: *"#1708's laundering path runs entirely through this
channel's captures"*, so an under-fired boolean here is a typed turn's capture
becoming a clean input to a spoken one. The evaluation must see the fourth group.

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
subtraction dropped.

**The novelty rate is not precision, and conflating the two would be the easiest
mistake this section could invite.** Novelty says a fired read returned records the
supply did not already hold. It does **not** say the supply was insufficient, that
the new records bore on the question, or that the reply was better for them: a
planner can emit a broad query on a perfectly sufficed turn and get back one
irrelevant record it had not seen, and that turn scores as novel while being a false
fire. So novelty is an upper bound on precision and is reported as one.

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

> **Normative.** Each turn records: whether a request was emitted; whether it was
> serviced or declined under §5's channel scoping; for each ask, its kind, and **the
> identifier of the plan that carries the ask itself**; how many records the
> servicing returned; how many of those were new after deduplication; how many the
> deduplication removed; how many labels resolved to nothing; whether the budget
> truncated a kind; and whether the servicing failed.

> **Normative.** The record holds **counts, kinds and a reference**, and copies no
> text. It does not copy the query the planner composed, the labels it named, any
> `content` span, any excerpt or any rendering. The ask is already durable on the
> plan (§4), and the record points at it.

> **Normative.** A planner-composed query is a **model completion with no recorded
> origin**, of the same class as `ActionPlan.rationale`. Wherever it is rendered,
> read back or exported it is treated as that class already is, and nothing in this
> ADR makes it speakable, placeable, or admissible to a channel a rationale is
> inadmissible to. No lane infers a placement for it by inspecting it.

> **Normative.** These are the fields milestone 2 **raises rather than replaces**. An
> ADR admitting a second serviced emission per turn extends this record to account
> per emission and keeps every field's meaning; it does not rename them, drop them,
> or start a second audit beside this one.

The instrument has to exist at the first deploy rather than be added when someone
asks, because the question it answers — did the trigger fire, and did the read return
anything new — is unanswerable retrospectively. Recording the not-fired turns is what
turns a log into a denominator, and recording the declined ones is what keeps §5's
channel scoping visible rather than silent.

**The reference rather than a copy is ADR-0004 §7's minimisation taken seriously, and
it closes a hole an earlier draft of this section had.** That draft retained the
planner's own query text on the ground that it is the planner's composition rather
than a record's content. But nothing bounds what a planner may put in a query: it
reads the rendered supply, so a query may quote a sensitive span of a record verbatim,
and the clause forbidding record content and the clause retaining the query would then
contradict each other on the same bytes. Pointing at the plan removes the contradiction
by removing the second copy: the ask is retained exactly once, on the frozen
`ActionPlan` the planning store already keeps, under whatever retention that record
has. A later reader who wants to judge whether a reformulation was any good reads it
there.

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
`ReadAsk`, `ReadRequest`, and `ActionPlan`'s field with its validators), the widened
docstrings on `Planner.plan` and `TurnResult` in `core/protocols.py` and
`core/types.py`, §3's ordinal labelling of the supply in `planning/planner.py`, the
planner's emission and the prompt that asks for it, and the canonical fakes in
`ai_assistant.testing` that construct a request. **Not** the servicer.

**Lane B — the servicer, the union and the audit.** In `orchestration/`: the
servicing of both kinds, §3's label resolution by index into the sequence the loop
passed, §5's channel scoping and degradation posture, §6's budget and cross-kind
precedence, §7's deduplication, fourth group and post-servicing evaluation, and §9's
audit record.

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
6. **A serviced record still fires ADR-0204 §2's boolean.** On a bounded-audience
   turn, a record the servicing adds that ADR-0199 §3 would withhold sets the boolean
   the capture records. This fails on any implementation that evaluates before
   servicing and does not re-evaluate over the union, and it is the assertion standing
   between this ADR and #1708's laundering path.
7. **The hop is serviced before the query, and the budget truncates the query.** A
   request whose hop yields records and whose query would yield more than the
   remaining budget produces a fourth group holding the hop's records and exactly the
   remainder from the query, in that order, with the truncation in the audit. A hop
   that exhausts the budget leaves the query no slots and does not fail.
8. **The audit records a fired, a non-fired and a declined turn**, with the counts §9
   names; it copies no text, so neither a distinctive span of a returned record nor
   the planner's query string appears anywhere in it; and the ask it points at is
   readable on the plan.
9. **The budget and the bounds hold.** A hop naming three labels is not a request the
   types admit; a request whose asks are two of one kind is not either; a servicing
   whose candidates exceed ten returns ten; and a record already in the supply is
   deduplicated out with the original keeping its position, counting against nothing.
10. **The fourth group is appended, not interleaved.** The three existing groups keep
    their order and their positions, the serviced records follow the supplement whole,
    and `planning/planner.py`'s leading-`EPISODIC`-run split is unaffected by a group
    of episodes appended at the tail.
11. **A failed servicing degrades and does not fail.** A store that raises during
    servicing leaves the turn composing from the supply planning saw, reports the
    degradation, records what was asked and that nothing returned, and parks nothing.
12. **The plan is still frozen and still auditable.** A plan carrying a request
    refuses mutation; a plan carrying none is the default; and a `ReadAsk` is never
    selected, ruled on or driven — asserted by a turn whose request names a query that
    reads like a tool call and which reaches no registry, no gate and no executor.

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
- **#838's coverage layer**, and whether the trigger is learnable from the supply
  alone. Fired by what §9's audit shows, or by #838's own ADR.
- **A sampled shadow read on turns the trigger did not fire on** — the only live
  mechanism §8 identifies for a recall denominator, and a real per-turn spend on
  turns the system has no reason to think need one. Fired by a decision that the
  recall figure is worth that cost, which this ADR does not take.
- **A second serviced emission, a configurable read count, or a per-surface
  deadline.** #1908 names the deadline as milestone 2's — *"a voice turn cannot
  afford three round trips"* — and §6 fixes the count at one until an ADR moves it.

### 13. Scope, and what this records against earlier ADRs

**This ADR partially supersedes exactly one clause of one ratified ADR and no
others**, and every other clause it cites binds as written. That is a classification
of this change and is therefore stated as prose rather than marked (ADR-0089 §1);
what follows is the working under ADR-0070 §1's test, including for the three clauses
a reader would most expect to have moved and which did not.

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

**ADR-0204 §2 is untouched and its evaluation is relied on.** §7 requires only that it
be taken after servicing, so the boolean it sets reflects the supply the turn actually
ran over. That is the existing rule applied to a supply that gained a group, and
`BoundedAudienceSupply`'s own statement of why it must not under-fire — *"#1708's
laundering path runs entirely through this channel's captures"* — is the reason the
ordering is normative here rather than left to a lane.

**ADR-0158 §4 and §5 are extended in application and unchanged in text.** §4's rule
is that the order is tail, then beliefs, then supplement, *"appended whole, never
interleaved"*; §7 appends a fourth group after the third and disturbs neither the
rule nor any existing group's position. §5's three-group clause on `Planner.plan`
becomes four groups, which is the same widening §5 itself performed on ADR-0074 §5's
two — and §5's operative sentence, that an implementation *"may rely on the grouping
and may not rely on a global relevance order"*, is carried word for word. ADR-0074
§5's own clause is untouched: the tail is still first, still in order, still bounded.

**ADR-0170 §2 and §5a are untouched, and §5a is relied on.** The composing stage
still holds no `MemoryStore`, performs no second retrieval, and renders step accounts
from closed vocabularies alone; §1's record-not-payload rule exists precisely so that
what this envelope returns is not the kind of thing §5a excludes.

**ADR-0225 §12 is untouched and its gate is not approached** (§10, §12).
**ADR-0014 §2's frozen plan is untouched** and §4 relies on it. **ADR-0211 §1 is
untouched**; §4 distinguishes its required-input reasoning rather than extending it.
**ADR-0154 and ADR-0223 are cited only in §12's deferral** and neither is moved.

**Everything else this ADR cites is used as ratified**: ADR-0004 §7; ADR-0006 §5;
ADR-0015 §5; ADR-0016 §5; ADR-0027 and ADR-0070 §§1, 3 and 4 for the supersession
form; ADR-0072 §5; ADR-0086 §6; ADR-0088 and ADR-0089 for the citation forms and the
marks; ADR-0098 §2; ADR-0113; ADR-0137 §§1 and 2; ADR-0158 §§1, 3, 4 and 5; ADR-0187
§4; ADR-0199 §§1, 3 and 5; ADR-0203 §1; ADR-0208 §1; ADR-0210 §1; ADR-0217 §2;
ADR-0221 §5; ADR-0224 §1; ADR-0225 §12.

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
- **One clause of one ADR moves**: ADR-0208 §1's one site becomes two for relevance
  reads. Nothing in the withholding corpus moves, because §5 keeps the envelope off
  the channel that corpus is about — which is also why the spoken channel gains
  nothing from this milestone, stated as a cost in §5 rather than as a footnote.
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
same bytes, and ADR-0004 §7 would be breached by a second retained copy. The audit
points at the plan that already holds the ask.

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
