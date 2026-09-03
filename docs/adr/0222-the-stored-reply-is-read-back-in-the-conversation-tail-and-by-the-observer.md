# 222. The stored reply is read back, in the conversation tail and by the observer

- Status: Partially superseded by ADR-0227 (§2's first normative clause, in the single respect that a record a turn's citation hop reached renders its `outcome` at `orchestration/composing.py`'s request assembler; and §5's eligibility enumeration, in the single respect that such a rendered reply is counted on the pair §5 already requires. §2's second normative clause — `benchmarks/` untouched and every prompt `render_context` builds byte-identical — binds entire; the retrieved group, the episodic supplement and the records a sighted query serviced all stay phrase-only; §1, §3, §4, §6, §7, §8 and §9 and the rest of §5 stand)
- Date: 2026-09-01
- Partially superseded: 2026-09-03 by ADR-0227 — **§2's phrase-only rule no longer
  reaches a record a turn's citation hop reached, and §5's eligible set now counts the
  reply that record renders.** §2's clause — *"No record of the **retrieved** group at
  either request assembler renders its `outcome` where it carries a `disposition`"* —
  was written the day before the read envelope existed, and it governs the assembler's
  whole non-tail population in effect: the episodic supplement is nowhere named in it
  and is plainly covered, and `_split_conversation_tail` puts every non-tail record in
  one bucket. The fourth group ADR-0226 §7 appends therefore fell under it, so a hop
  that reached an exchange **by pointer, for its reply** delivered the disposition
  phrase and withheld the reply — the failure #1944 records against the live hub.

  **Replaced**, in one scope: §2's first clause as it reaches a record the turn's
  citation hop resolved through a named label's `Provenance.evidence`, at
  `orchestration/composing.py`'s assembler alone. Such a record renders its `outcome`
  beside the phrase, in §1's shape and order, under §4's ceiling and §5's elision, and
  under a cap of ten such lines per assembly that the superseding ADR states for
  itself — `Provenance.evidence` carries no read-time length bound, so the count of
  hop-reached records is not bounded by anything in this ADR or in `core`. **A record
  of the conversation-tail group is not reached by the exception at all**: §1 governs
  it alone, so a hop that reaches a tail episode adds no second line under its bullet
  and the tail's rendering stays byte-identical. A
  reader holding only this ADR would refuse to render it, which is
  [ADR-0070](0070-amendment-and-supersession-rules.md) §1's test for a change to what
  was decided.

  **And, in a second scope**, §5's *"eligible to render a reply under §1 or §3"*: a
  reply rendered under the clause above is eligible in that sense and is counted on the
  one statement §5 already requires, over both populations. Every other clause of §5 —
  the prefix rule, the held-data marker outside the quoted span, one statement, no
  reply text, counts of one assembly, the structured-log carrier — binds unchanged.

  **What is not replaced, and is load-bearing.** §2's second normative clause binds
  entire and [ADR-0227](0227-a-record-the-citation-hop-reached-renders-its-reply-and-the-test-that-says-so-runs-the-real-renderer.md)
  §6 restates it as its own obligation: `benchmarks/` is untouched, every prompt
  `render_context` builds is byte-identical, and no benchmark result moves — which the
  harness gets for free four times over, since it runs no planner emission, no
  servicer and no hop, and §1's third clause keeps the line out of `_render_record`.
  §2's three reasons are each answered against the hop and each still reaches the
  retrieved group, the episodic supplement and the records a **sighted query**
  serviced, which stay phrase-only. §1, §3, §4, §6, §7, §8 and §9 stand as ratified,
  and §8's tests 10 and 11 are re-owed rather than narrowed.
- **Partially supersedes:**
  [ADR-0221](0221-an-episode-carries-the-reply-a-typed-disposition-and-how-the-turn-was-captured.md)
  — **§3's second arm and its no-budget clause, at two of the three render sites;
  §11's tests 4 and 5.** §3's first normative clause says every site that renders an
  episode's `outcome` "renders **the phrase for `disposition` where the episode
  carries one**", and closes *"A record carrying a `disposition` has its `outcome`
  rendered into no model prompt by any of them"*. That closing sentence is replaced,
  for the conversation-tail group at `planning/planner.py` and
  `orchestration/composing.py` and for `learning/observer.py`'s batch: those three
  populations render the reply **beside** the phrase, never instead of it. §3's third
  normative clause — *"No render site gains a byte budget, an elision rule or a
  truncation for this change, and none is owed one by it"* — is replaced by §4 and §5
  below, which are the budget ADR-0221 §13 names as this decision's obligation.
  §11's test 4 is deleted, as §11 itself provides, and test 5 is narrowed; §8 says
  which assertions replace them. §3's phrase table rule, its enum-absent fallback,
  its three-populations argument for every *other* rendering, §1, §2, §4, §5, §6,
  §7, §8, §9, §10, §12, §13 and §14 are untouched and bind unchanged.

## Context

### Where this comes from

`track:memory` (#1231), design note #1845, and ADR-0221 §13's second deferral —
*"Every reader of the stored reply: the production observer seeing it, retrieval by
its text, #1314's second-turn reference-back, and the render budgets and elision
rules none of the three prompts has today. Fired by the first lane that wants one"*.
This ADR is that lane, for two of those four and not the other two. #1842 is the
surrounding argument for why an assistant that keeps no record of its own conduct
cannot learn from it; #1844 is the design note whose replay bounds what this decision
may claim.

### What batch #1866 left, read from the tree rather than recalled

ADR-0221 put the composed reply in `EpisodicMemory.outcome` and then rendered it
nowhere, deliberately. The state at `origin/main`, verified:

- **The reply is stored.** `orchestration/engine.py`'s `_capture` writes it, and
  `EpisodicMemory` carries it beside an `ExchangeDisposition`.
- **The three render sites read the enum and not the field.**
  `learning/observer.py`'s `_outcome_lines` returns
  `[f"       Assistant: {_quoted_span(_disposition_phrase(record.disposition))}"]`
  where a `disposition` is present, and reaches `record.outcome` only where it is
  absent. `planning/planner.py`'s and `orchestration/composing.py`'s `_render_record`
  each hold the same two arms, emitting `    how it turned out: …`.
- **Nothing else reads it.** `Belief` and `BeliefSummary` project `content` and not
  `outcome`, and nothing under `interfaces/` reads `TurnResult.memories`.

So the reply has been in the store and outside every prompt since batch #1866, which
is the condition ADR-0221 §3 describes as *"stored, rendered nowhere, and available to
the lane that decides to read it"*.

### The precondition ADR-0221 §13 named is discharged, and by which commit

§13 conditions every reader on *"#672's escaping fix **and** newline normalisation
before it renders a reply into the observer's line-oriented batch"*. Both landed at
`66e3ba9a` (PR #1877, closing #672), which is `origin/main`'s tip as this ADR is
written. `learning/observer.py`'s `_quoted_span` puts every interpolated span through
`json.dumps` at its default `ensure_ascii=True` — the function's own docstring records
the consequence: *"the result is single-line printable ASCII, delimited by quotes the
value can no longer close. Single-line is not a bonus but the second thing ADR-0221
§13 asks of a reader of this batch"*. The planner's and composer's render sites were
already quoted, and `_outcome_lines` records what remains: *"The render budget none of
the three prompts has today is what remains, and it is the half a transform cannot
supply: a quoted reply is one line but is as long as the reply."*

That sentence is this ADR's subject. The two halves §13 made a precondition are paid;
the third is a decision, and §4 and §5 are it.

### The populations, counted, because the budget is arithmetic before it is a rule

- The **conversation tail** is up to 20 turns: `memory/conversation_store.py`'s
  `_DEFAULT_TAIL_LIMIT` is `20`, and both request assemblers split the leading
  episodic run off with `_split_conversation_tail` and head it separately (ADR-0074
  §5).
- The **retrieved group** carries the relevance-retrieved beliefs and the episodic
  supplement, `app/composition.py`'s `EPISODIC_SUPPLEMENT_LIMIT` being `10`.
- The **observation batch** is 20 turns: `observation_batch_size` defaults to `20`.

A composed reply is model prose and `EncodableText` bounds no length, so twenty whole
replies is the quantity §13's "render budgets" is about. It is not a hypothetical: the
tail is exactly where a real conversation puts twenty of them.

### What the #1844 replay rules out, and what it leaves alone

The replay recorded on #1844 on 2026-09-01 measured the sighted-read envelope that
note proposed. Its headline: of the published 75.7% retrieval reach on LoCoMo,
*"22.8pt of it is a citation hop the system does not perform — the measure counts a
belief's evidence as reached"*, worth ≈+3.2pt of answer accuracy at its ceiling; and
the trigger that would have to fire is the binding constraint (32.4% recall on total
misses, firing independently of whether a second read would have helped). Its
recommendation: *"**Do not open the one-envelope sighted-read ADR yet.**"*

That verdict is about **sighted** reads — the planner naming a query, a belief or an
outward source and the loop servicing it. Every door this ADR opens is **unsighted**:
the records are the ones the loop already selected and already renders, and what
changes is how much of a record already in the prompt is shown. §10 states the
relation in terms, because the two are easy to conflate and the replay's verdict must
not be read as forbidding a change it did not measure.

### Why this is one decision and not two

The tail door and the observer door share the thing that is actually hard — the budget
and the elision rule — and they share the boundary that makes reading the reply
lawful at all (ADR-0162 §8). Deciding them apart would state one budget twice and
invite the two statements to drift, which is the failure ADR-0221 §3 guards against
for the phrase table by naming the tables rather than sharing them. Here the rule is
shared, the *number* is one number, and this ADR is where both are written.

## Decision

### 1. The tail door: the reply beside the phrase, in the conversation tail alone

> **Normative.** At `planning/planner.py`'s and `orchestration/composing.py`'s request
> assemblers, a record of the **conversation-tail** group — the leading episodic run
> `_split_conversation_tail` returns — that carries both a `disposition` and an
> `outcome` renders one further continuation line under its own bullet, stating the
> episode's `outcome`, subject to §4's ceiling and §5's elision rule. The
> `    how it turned out: …` line is unchanged, is rendered first, and the reply line
> never replaces it.

> **Normative.** A tail record carrying a `disposition` and no `outcome` renders the
> phrase line alone and grows no reply line. A tail record carrying no `disposition`
> renders exactly as it does today.

> **Normative.** The reply line is emitted by the tail assembler and not by
> `_render_record`. `_render_record` renders, for every record and every caller, the
> bytes it renders today.

**The phrase and the reply are two facts and neither implies the other.** The phrase
is a typed statement of what became of the pass — that a step was parked, that the
permission policy refused it, that a route ran — and it is text this system authored
about its own pipeline. The reply is what the user was actually shown. A reply that
says "I've set that up for you" beside a phrase that says the action was parked for
confirmation is the pair a model needs; either alone is a half-truth. So the reply is
added and the phrase is kept, in that order, and no site is permitted to trade one for
the other.

**The reply line is the caller's, and that is what keeps the harness still.**
`benchmarks/memory/answer.py` imports `planner._render_record` by name and calls it
directly — *"Imported rather than copied (#1181) … the equivalence test caught drift
only after somebody wrote it"* — so anything put **inside** that function reaches the
benchmark's prompt whether or not the harness meant to build a tail. Putting the line
in the tail assembler makes §2 true by construction rather than by a gate the harness
would have to keep passing. `orchestration/composing.py` already holds exactly this
shape one function up: `_render_delivery` is called from the tail loop, appends lines
under the record's bullet, and is not reachable from `_render_record` — ADR-0205 §5's
delivery fact, which *"is written under the turn it is about, and only in the tail"*.

### 2. The retrieved group stays phrase-only, and the harness is untouched twice over

> **Normative.** No record of the **retrieved** group at either request assembler
> renders its `outcome` where it carries a `disposition`. That group's rendering is
> unchanged by this ADR.

> **Normative.** `benchmarks/` is not touched by the lane implementing this decision,
> and every prompt `benchmarks/memory/answer.py`'s `render_context` builds is
> byte-identical to what it builds today. No benchmark result moves.

**Three independent reasons put the line here, and any one of them would do.**

- **A retrieved episode was not retrieved for its reply.** Retrieval is
  content-addressed and the reply is not embedded — ADR-0221's own alternatives record
  that this is why `outcome` was chosen as the slot, so *"an actor who influences what
  the assistant says"* cannot choose which questions retrieve their text. The #1844
  replay measures the consequence directly: the vocabulary of the reply is exactly
  what the search key never sees. Rendering a retrieved record's reply spends budget
  on prose that no part of the selection ever read.
- **ADR-0205 §5 already drew this line at these two sites**, for a fact of the same
  shape and with the reason stated: *"The retrieved group carries none, because §5
  supplies the facts off the replay tail and a record retrieved by relevance is not
  one of those rows."*
- **The harness only ever renders the retrieved group.** `answer.py` records that
  `RETRIEVED_HEADING` *"is always the retrieved group's heading and never the tail's,
  because the harness cannot produce a tail … `planner._split_conversation_tail` over
  these records always returns an empty leading episodic run"*. So a tail-only rule
  cannot reach a benchmark prompt at all — and the second guard is that a harness row
  carries no `disposition` (ADR-0221 §3's third population), so §1's condition is
  false for it twice.

**This is also the narrowest cut that serves #1314.** The second-turn reference-back —
*"which lender did you recommend?"* asked of the turn that just happened — is a
property of the conversation, and the conversation is the tail. Reaching the same
question about an exchange from three months ago is the citation hop, which is
sighted, which is #1844's territory, and which §10 leaves exactly where the replay
left it.

### 3. The observer door: the reply beside the phrase, over the whole batch

> **Normative.** `learning/observer.py`'s `_outcome_lines` renders, for an episode
> carrying both a `disposition` and an `outcome`, **two** continuation lines under the
> episode's own `[E<n>]` label: the `Assistant:` phrase line it renders today,
> unchanged, and one further line stating the reply, subject to §4 and §5. An episode
> carrying a `disposition` and no `outcome` renders the phrase line alone; one
> carrying no `disposition` renders its `outcome` exactly as it does today; one
> carrying neither renders nothing.

> **Normative.** Both lines sit under the same label as continuation lines and neither
> is a second entry, so ADR-0162 §8's whole-episode citation and ADR-0077 §5's
> distinct-id counting are unchanged: one episode remains one label and one support.
> Every span on either line goes through `_quoted_span`, the phrase included.

> **Normative.** The observation system prompt's assistant-half paragraph — which
> today keys ADR-0162 §8's partition on *"an \"Assistant:\" line"* — names **both**
> lines, and applies the same partition to each. The lane implementing this decision
> makes that edit; a reply line the prompt does not account for is a line the model
> reads under no rule.

> **Normative.** The observer applies no recency restriction: every episode of the
> batch that satisfies the condition above renders its reply. §4's ceiling is the only
> bound.

**Why the whole batch and not a recent slice.** The observer's business is the batch
it was handed, and ADR-0220's walk tiles contiguously, so every episode is the subject
of some pass. A slice would make whether an episode's reply was ever seen depend on
where the tile boundary happened to fall — a fact about scheduling deciding a fact
about evidence. The observation pass is also background work at a per-conversation
cadence rather than per-turn latency, so the prompt it can afford is not the composing
prompt's.

**The line-count invariant changes and stays computable, which is the property that
matters.** `_render_batch`'s docstring argues that *"the line count of this batch is
the header plus one line per episode plus one per assistant half, whatever any
episode's `content` says, and the label a model is shown maps to the episode this
module read under it"*. That argument does not rest on the number two; it rests on no
span being able to write a line. `_quoted_span` is what supplies that, and it supplies
it for the reply exactly as for the phrase and the content. The invariant becomes the
header plus one line per episode plus one per assistant half plus one per rendered
reply, and it is as mechanical as it was.

### 4. The budget: one ceiling, one number, three sites

> **Normative.** A reply rendered under §1 or §3 is rendered as the **longest prefix
> of the reply whose quoted rendering is at most 640 characters**. The ceiling is
> counted on the *output* of `_quoted_span`, delimiters included; the cut is taken on
> the reply's own text, so no escape sequence is ever split. Where the whole reply's
> quoted rendering fits, it is rendered whole; otherwise §5's elision applies.

> **Normative.** The ceiling is written out as a module constant at each of the three
> sites and is not shared between them, for the reason ADR-0221 §3 gives for the
> phrase tables: three subsystems rendering their own prompts do not import across a
> boundary golden rule 1 forbids them to cross, and what they share is this ADR's
> number rather than a module. No `Settings` field is added for it.

> **Normative.** No other budget, ceiling or elision is introduced by this ADR. The
> tail depth, the retrieved group's size, `EPISODIC_SUPPLEMENT_LIMIT`,
> `observation_batch_size` and `observation_max_proposals` are all unmoved.

> **Normative.** The **framing** of a reply line — its indent, its label, and §5's
> elision marker with the two numbers in it — is at most **96 characters**, so one
> rendered reply line is at most 736 characters whole. The lane's wording is its own
> choice within that bound.

**The arithmetic, stated because a budget that is not is not a budget.** One reply line
is at most 640 characters of quoted span plus at most 96 of framing: 736. Twenty tail
turns is therefore at most **14,720 characters** of added prompt, and the observation
batch is the same twenty. The quoted spans alone account for 12,800 of it; the rest is
the label and the marker, which are counted here rather than left out because a bound
that excludes the mandatory parts of the line it bounds is not a bound. That total is a
true worst case for *any* reply text, which is the whole reason the ceiling is counted
on the quoted rendering rather than on the source: `json.dumps` expansion is not
uniform, and a source-character ceiling bounds the wrong quantity.

**The expansion is uneven, and getting it wrong is how a budget stops being one.**
Measured on this tree's Python: with `ensure_ascii=True`, a newline becomes two
characters, a Latin-1 or BMP code point such as `é` or `中` becomes six, and an
**astral** code point such as an emoji becomes *twelve* — two `\uXXXX` surrogate
escapes, not one. So `json.dumps("😀" * 600)` is 7,202 characters, where a naive
six-per-code-point reading predicts 3,602. A ceiling on source characters would
therefore admit twenty replies of about 144,000 characters while claiming to admit
72,000. Counting the ceiling on the output removes the whole class of error: whatever
the text is made of, the rendered span is at most 640 characters.

**What 640 buys, in the units a reader cares about.** Ordinary prose escapes to about
its own length, so 640 admits roughly 630 characters of English — about a hundred
words, a substantial paragraph — and the common reply renders whole. Text that is
entirely CJK admits about 105 code points and text that is entirely emoji about 53.
That degradation is correct rather than unfortunate: those replies cost the prompt the
same 640 characters, and a budget that let them cost six or twelve times more would be
measuring the wrong thing.

**The cut is taken on the source text even though the ceiling is measured on the
output.** Slicing the quoted form could split a `\uXXXX` escape or a surrogate pair and
produce something that is not valid JSON, so the prefix is chosen over the reply's own
characters and measured by rendering it. §5's marker then reports source characters,
which is the unit a human can check against the stored reply.

**No measurement stands behind 640, and this ADR says so rather than implying one.**
The corpus's own precedent for an unmeasured bound is `DEFAULT_OBSERVATION_MAX_PROPOSALS`,
where the number is defended by a probe and the instrument that would revise it is
named. There is no probe of reply lengths in this system, and inventing a figure to
justify one would be worse than admitting the gap. What makes the number revisable is
§5's counter pair: a high **share** of elided renders says the ceiling is wrong, and it
is a share rather than a count precisely because a bare numerator cannot say it.

### 5. The elision is legible, it is held data, and it is counted

> **Normative.** Where §4's ceiling binds, the line naming the reply states in
> **held data outside the quoted span** that what follows is a prefix, and states the
> reply's full length. The elided text is never presented as the whole reply, and the
> marker is never placed inside the quoted span.

> **Normative.** An unelided reply carries no marker. The absence of a marker means
> the line carries the reply whole.

> **Normative.** Elision is a **prefix**: the first N characters of the reply's own
> text, in order, with nothing removed from the middle and nothing joined. No site
> renders a head-and-tail composite.

> **Normative.** Each site emits, once per assembly, **two** counts: the number of
> records that were eligible to render a reply under §1 or §3, and how many of those
> §4's ceiling bound on. The pair is the denominator and the numerator of the elision
> share, and neither is owed without the other.

> **Normative.** The pair rides **one statement**, so the two are observed together and
> lost together (ADR-0141 §6's rule for the duplicate share). The statement carries the
> two integers and **no reply text**, elided or whole, so §8's twelfth assertion is
> unaffected and ADR-0119's rule that a trace never contains Tier 0/1 content is not
> approached.

> **Normative.** The counts are of one assembly and are not durable totals; a rate is a
> sum over a window, as ADR-0120 §1 computes every measure.

> **Normative.** The carrier is a **structured log event at the rendering site**, and
> this ADR places the pair on no other surface. No count required by this section
> reaches an `OPERATION` trace, and no implementation adds a field to a `core` type, a
> member to a Protocol, or a side channel between a render site and the engine in
> order to make one.

**The trace is not available to these counts, and saying so is cheaper than a
mechanism.** ADR-0119 §8's mapper is the engine boundary and it can project only the
operation's own result value: `_tracked` takes a `Callable[[_T], Observation]`, and
for an observation pass `_T` is `ObservationReport`, which lives in `core/types.py`
and carries no render counts. §13 forbids adding one. Two passes over one episode can
return identical reports while one elided a long reply and the other did not, so a
mapper of that result cannot distinguish them however it is written — and the ways
round it are worse than the gap: a second operation trace emitted from `learning`
would put a second crossing where ADR-0119 §5 has one, re-reading the store could
select a different batch, and a shared "last counts" slot races concurrent passes. So
the pair stays in the log, where the site that computed it can state it directly.

**A log is the right weight for what this is.** The pair exists to tell a later lane
whether §4's unmeasured number was set right, which is a question asked during a QA
pass and not by a resident query — the same reading #1081 performed for the
notification instrument. §9's figures are read the same way and for the same reason,
so neither instrument in this ADR is a member of ADR-0120's measure set.

> **Normative.** §9's counting hook is a *different* obligation and is unaffected by
> this section: it puts on the `"observe"` seam's trace only counts
> `ObservationReport` already carries, which is why it is lawful where these counts
> are not.

**Outside the span, because inside it is forgeable.** ADR-0098 §2 rules that a span's
attribution must not be forgeable from inside the span, and `_outcome_lines` states the
discipline that follows: *"Every part of a line that is not a span goes on held data
the batch was handed."* A marker inside the quoted reply is a string the reply itself
could contain, so a reply ending in this system's own elision wording would render as
though it had been cut when it had not — or, worse, an unelided reply could claim to be
one. The lengths come from `len()` on held data and the wording is a constant, so
neither is reachable from the text.

**Legibility is the whole answer to ADR-0221's own objection to a prefix.** That ADR
rejected storing one on the ground that *"an assertion whose meaning depends on its
ending is not half-storable"*, and the objection has real force here too: a reply that
ends "…though I may have that wrong" means something else without its ending. Two
things separate this from what §3 refused. Storage is permanent and a stored prefix
destroys the rest; a render budget spends one prompt and the whole reply stays in the
store for the next pass, which is exactly ADR-0086 §4's distinction — *"An elision says
it stood here and we stopped carrying the reference … a surface must not render the
two alike."* And a **legible** prefix does not assert what a silent one does: a model
told it is seeing the first 612 of 1,283 characters knows it has not been given the
ending, which is the difference between an incomplete answer and a wrong one.

**A prefix rather than a middle-out cut, and the observer's own caution is why the
distinction has to be argued.** `observer.py` records that its proposal cap *"truncates
by position in a model's reply, and position is not a ranking"*, and reads a binding cap
as a defect for that reason. That argument is about a **set** whose members are
unordered by value — dropping the tail of a proposal list drops arbitrary beliefs. A
single reply is not such a set: it is one ordered text whose beginning is where its
thrust is, and the alternatives to a prefix are worse. A head-and-tail composite needs a
join marker, which is a second forgeable surface for no measured gain; dropping the
reply entirely past the ceiling would blind the reader to precisely the long replies a
reference-back is most likely to be about. The elision counter is this ADR's answer to
the same worry the cap's counter answers.

### 6. What this partially supersedes in ADR-0221, precisely

> **Normative.** ADR-0221 §3's closing sentence — *"A record carrying a `disposition`
> has its `outcome` rendered into no model prompt by any of them"* — is **partially
> superseded**. In its place: a record carrying a `disposition` has its `outcome`
> rendered by `learning/observer.py`'s `_outcome_lines`, and by the tail assemblers of
> `planning/planner.py` and `orchestration/composing.py` for a record of the
> conversation-tail group, in each case beside the phrase and under §4 and §5. It is
> rendered into no other prompt and by no other site.

> **Normative.** ADR-0221 §3's third normative clause — *"No render site gains a byte
> budget, an elision rule or a truncation for this change, and none is owed one by
> it"* — is **partially superseded**: the three sites named above gain §4's ceiling and
> §5's elision, and no other site gains either.

> **Normative.** Everything else of ADR-0221 §3 binds unchanged: the phrase for
> `disposition` is rendered wherever the enum is present, at all three sites and in
> both groups; `outcome` is rendered as text where the enum is absent; the phrase
> table lives at each site and is not extracted into a shared module, a `core`
> mapping, a method on the enum or a helper any two of the three import.

**The enum-absent fallback is byte-identical, and so are two of §3's three
populations.** A **pre-change** episode carries a phrase in `outcome` and no
`disposition`; every site renders that phrase exactly as it does today, in either
group, and grows no line — §1's and §3's conditions require a `disposition`. A
**benchmark-harness** episode likewise carries no `disposition`, and additionally
never reaches a tail; its rendering is unchanged for both reasons. Only the
**post-change** population — an episode captured after ADR-0221, carrying both fields
— renders differently, and only in the tail and in the observation batch. That is the
whole of the change to the rendered bytes, and it is the population this decision
exists to read.

**ADR-0221 §12's closing prohibition is not breached, because it does not reach here.**
That clause reads *"A lane implementing **the above** … or reading the reply into any
prompt, or adding a render budget … has exceeded this decision"*, and "the above" is
§12's own Lanes C, D and E. It is a fence on those three lanes, which have merged; it
is not a standing prohibition on the corpus, and §13 names this very work as deferred
rather than forbidden. Read otherwise, §13's second bullet could never be discharged
by anyone.

### 7. ADR-0162 §8's boundary clauses are the governing law, restated and not reopened

> **Normative.** ADR-0162 §8's four clauses other than its first bind this decision as
> ratified and are not amended, narrowed or widened by it. In terms: an episode is
> cited whole, and ADR-0077 §5's floor counts distinct episode ids exactly as before;
> what the assistant said **independently supports** a record of its own act — that it
> was asked something, that it answered or did a particular thing, and when; what the
> assistant said **never supports** a record that adopts the proposition it asserted as
> a fact about the world or about the user, such a record being proposed only where the
> user said it; and what the assistant said is **never a licence** to propose an
> `EpisodicMemory`, ADR-0077 §2's refusal standing.

> **Normative.** No implementation of this ADR relaxes, reinterprets or adds an
> exception to any of those four. A change to them is a supersession of ADR-0162 §8
> and takes its own ADR.

**These clauses were ratified against a reader that did not yet exist, and this is the
decision that makes them live.** ADR-0221 §4 says so in as many words: *"The day a
reader lane lets the production observer see the reply, §8's third and fourth clauses
are what govern what it may then propose, and they govern it as ratified."* That day
is this ADR. Nothing here is a fresh judgement about the boundary — the boundary was
decided in ADR-0162 and this section is the citation, not a re-argument.

**One thing that genuinely changes, and it is a strengthening rather than a widening.**
Until now the observer's `Assistant:` line carried a phrase this system authored, so
the third clause's prohibition — do not adopt the assistant's proposition as fact — had
nothing to bite on: a sixteen-member phrase table asserts nothing about the world. With
the reply on the batch, the clause has real work for the first time, and the model can
now actually commit the failure §8 describes: *"the assistant answers 'Paris is the
capital of France', or worse a guess about the user, and a pass later that assertion is
a belief with the user's model behind it and an episode as its citation."* The prompt
already carries the partition (§3's third clause extends it to the new line), the
observer's citation scheme is unchanged, and §9's measurement is how the system finds
out whether the boundary holds in practice rather than only on paper.

### 8. ADR-0221 §11: test 4 is deleted, test 5 is narrowed, and what replaces them

> **Normative.** ADR-0221 §11's test 4 — *"A distinctive span in a captured reply
> appears in no subsequent prompt … This is the test a reader lane must consciously
> delete"* — is **deleted**. This is that conscious deletion, and it is performed here
> rather than left to the implementing lane's discretion.

> **Normative.** ADR-0221 §11's test 5 — byte-identity of the rendered prompt across
> the change, for each of the sixteen members at each of the three render sites — is
> **narrowed** rather than deleted. It binds unchanged for `_render_record` at both
> request assemblers, for every caller and both groups, and it no longer binds for
> `learning/observer.py`'s `_outcome_lines` on a record carrying both fields, nor for
> the tail assemblers' output on such a record. §11's tests 1, 2, 3, 6, 7, 8, 9, 10,
> 11, 12, 13, 14 and 15 are untouched and bind unchanged.

> **Normative.** The following replace them, and the implementing lane owes each.

**The positive assertions — the reply appears where this ADR rules, and nowhere else.**

1. **The tail renders the reply beside the phrase.** A conversation-tail episode
   carrying a `disposition` and a reply renders, at each request assembler, its
   existing bullet, then the `    how it turned out:` line carrying the phrase, then
   the reply line — in that order, the phrase line byte-identical to what the same
   record renders today.
2. **The observer renders two continuation lines**, under one `[E<n>]` label, for the
   same record: the `Assistant:` phrase line byte-identical to today's, and the reply
   line.
3. **Every rendered reply is escaped.** A reply carrying this system's own syntax — a
   newline followed by a well-formed `[E2]` for the observer, a newline and a
   `    how it turned out:` for the assemblers — renders as one line and writes no
   second entry and no second continuation line, at all three sites. This is ADR-0098
   §9's regression shape applied to the new span.
4. **The ceiling binds where it should and not before.** A reply whose quoted
   rendering is exactly the ceiling renders whole and unmarked; one whose quoted
   rendering is a single character over renders a prefix with §5's marker; and the
   marker's length figure is the reply's full length in its own characters.
5. **The ceiling holds against expansion, and this is the case the arithmetic got
   wrong once.** A reply of astral code points — emoji — renders a quoted span of at
   most the ceiling, as does one of CJK characters and one of newlines. The test
   asserts the rendered length, not the source length, at all three sites, and it is
   what would have caught the twelve-characters-per-emoji error §4 records.
6. **The prefix is valid.** The rendered span is decodable as JSON for every input
   above: no cut splits an escape sequence or a surrogate pair.
7. **The whole line is bounded, framing included.** For every input above, the
   complete rendered reply line — indent, label, quoted span and, where it elides,
   §5's marker — is at most 736 characters, which is §4's per-line bound. The
   longest marker the lane's wording can produce is exercised, with the largest
   length figures a reply can carry.
8. **The elision marker is unforgeable.** A reply whose own text contains this
   system's elision wording, and which is under the ceiling, renders unmarked — the
   marker appearing only outside the quoted span, in held data.
9. **Both counters count, and they are emitted together.** An assembly mixing elided
   and unelided replies reports the eligible count and the elided count on one
   statement, with the second no greater than the first; an assembly with eligible
   replies and no elision reports a non-zero denominator and a zero numerator; and an
   assembly with no eligible record at all reports zero and zero rather than omitting
   the statement, so a missing pair is distinguishable from an empty one. No such
   statement carries reply text.

**The negative assertions that remain — where the reply still must not appear.**

10. **The retrieved group carries no reply**, at either request assembler, for a record
   carrying a `disposition`. A distinctive span in such a record's reply occurs
   nowhere in either assembled prompt. This is test 4's shape, retained over the
   population §2 keeps phrase-only, and it is why test 4's deletion is a narrowing
   rather than an abandonment.
11. **The benchmark harness renders no reply.** `render_context` over records built as
   `benchmarks/memory/ingest.py`'s `exchanges_of` builds them is byte-identical to
   today's, and `_render_record` called directly on a record carrying both fields
   emits no reply line.
12. **No log carries the reply.** ADR-0221 §11's test 14 is untouched and is restated
   here because this is the change that would most easily break it: the capture path,
   the observation path and the three render sites emit no log event whose payload
   contains the reply's text, elided or whole. ADR-0004 §5 names *"message bodies"* a
   redaction target and rendering a reply into a prompt is not a licence to log it.

### 9. The act-belief measurement

> **Normative.** This ADR defines two figures over one bounded set of observation
> passes. The **act-record share** is the count of returned proposals whose content
> states an act of the assistant's own under ADR-0162 §8's third clause — that it was
> asked something, that it answered or did a particular thing, and when — divided by
> the count of returned proposals in that set. The **laundering count** is the count
> of proposals in the same set whose content adopts, as a fact about the world or
> about the user, a proposition the assistant asserted. Both are reported as a
> numerator over its denominator, never as a bare ratio.

> **Normative.** The laundering count is expected to be **zero**, and a non-zero one
> is a defect in this decision rather than a datum about it: it is ADR-0162 §8's third
> clause failing in production. It is reported whether or not it is zero.

> **Normative.** Both figures are obtained by **reading the proposals' content**, in a
> QA pass, off a surface that already carries it — `ObservationReport.proposals`, whose
> `ObservedProposal.content` `assistant learn` already prints per proposal. They are
> not computed from the trace stream, are not added to `ai-assistant-measures`, and are
> not read from the store directly.

> **Normative.** This ADR adds no field, no enum member and no flag to
> `ObservedProposal`, `MemoryUpdateProposal`, `ObservationReport`, `ObservationOutcome`
> or any other `core` type to carry the classification, and makes no
> `core/protocols.py` change.

> **Normative.** The implementing lane owes one counting hook: `orchestration/engine.py`
> gives the `"observe"` seam a metrics mapper, so that a single interactive observation
> pass records its own counts on its `OPERATION` trace as a scheduled run already does.
> Nothing else in the instrument is owed, and no production decision is conditioned on
> either figure.

**What the numbers are for.** ADR-0162 §8's third clause has licensed act-records since
it was ratified, and until this decision nothing could exercise it: the observer saw a
phrase from a sixteen-member table, and a phrase drawn from sixteen constants supports
no particular act. Whether a sighted observer *actually* proposes records of the
assistant's own conduct — and at what rate — is therefore unmeasured, and it is the
datum #1842's track-or-note ruling wants before anything larger is built on the
premise. A share near zero says the door was opened and nothing walked through it,
which would make #1842's fifth requirement (a `FeedbackEvent` naming a typed act,
deferred by ADR-0221 §13) a different and larger question than it looks. The laundering
count is the other half, and it is the one that can fail: §7 records that this is the
change which first gives §8's third clause something to bite on, so an instrument that
counted only the upside would measure the benefit of a decision and not its risk.

**Why a reading and not a rate over the trace stream, which is where this project's
measures normally live.** ADR-0120 rules that a measure is a rate over the trace stream
read offline, and ADR-0141 §6 adds the discipline that a figure's numerator and
denominator must ride one emitted statement. Neither shape is available here, for a
reason ADR-0162 §8 states about itself: *"This is a producer-side obligation and it is
not mechanically checkable, which is said rather than glossed. Which proposition
supports a record is a fact about meaning, so no field carries it and no conformance
test sees it."* The trace stream cannot carry the fact even in principle — ADR-0119
rules that a trace *"references Tier 0/1 content and never contains it"*, and a
`MEMORY_WRITE` trace accordingly carries counts and opaque ids and no proposal text. So
a trace-stream rate would have to be fed by a producer-emitted boolean, and the only
producer that can classify meaning is the model. Asking it to declare the class is
building #1842's typed-act surface under cover of an instrument, which is exactly what
the clause below declines.

**Why not a field, and why the slower form is the honest one.** No field distinguishes
a record about the assistant's act from a record about the user. `about_person` is
`None` on every observer proposal — `learning/observer.py`'s `_record` never sets it,
and `core/types.py` reads `None` as the owner's anyway; `kind` gives an act record the
same `SEMANTIC` a world-fact gets; `MemorySource` partitions by entailment, not by
subject; and `derived_from_external` is about external content. The distinction lives
in the observation prompt and nowhere else. Adding a field to make the measure cheap
would prejudge a decision two documents already defer, so this ADR pays the cost of
reading sentences instead.

**Why not `ai-assistant-measures`, and why not the audit trail.** ADR-0120 §10 rules
the offline report reads the trace store and nothing else, so a figure needing Tier 1
text cannot be one of its measures without breaking that rule — the figures here are a
QA-pass reading in ADR-0141's *reporting form* rather than a member of its instrument.
The audit trail is not a candidate at all: `permissions/` records permission rulings
and tool invocations, an observation pass takes no ruling and calls no tool so it
writes nothing there, and it is a Tier 1 store that ADR-0119 §11 forbids merging with
the trace store in either direction.

**The hook that is genuinely missing, named because it is small and real.**
`orchestration/engine.py` traces a scheduled run with a twelve-metric mapper —
`self._tracked(self._observation.run(), "observe_due", _observed_due)`, writing
`passes`, `proposed`, `committed` and the rest — while a single interactive pass is
traced as `self._tracked(self._observation.observe(selected), "observe", checked=True)`,
with no mapper and therefore empty metrics. So the denominator of any per-pass figure
is readable for scheduled runs and not for interactive ones. That asymmetry is not
this decision's to justify and is cheap to close, so the lane closes it; the
classification stays a reading either way.

**How it is reported.** As #1081 reported the notification instrument: the figures
printed with their numerator and denominator, recorded in the QA issue for the run,
read for their structure rather than for their absolute value. The comparison a later
run makes is to the structure — that the act-record share's denominator equals the
proposals the same passes returned, and that the laundering count is still zero.

### 10. What this neither opens nor forecloses

> **Normative.** This ADR opens **unsighted** reads only: it changes how much of a
> record the pipeline has already selected and already renders is shown, and it adds
> no read, no query, no fetch and no model-directed selection. It neither opens nor
> forecloses the sighted-read envelope of #1844 — a planner-emitted query, a sighted
> citation hop, or a sighted outward fetch — and it is not to be cited for or against
> any of them.

> **Normative.** Retrieval by the reply's text is not opened. `outcome` is not
> embedded, no read gains an argument for it, and ADR-0221 §14's clause that no read
> returning records is filtered on `disposition` or `capture` is untouched. Embedding
> the reply is a separate decision with a separate ADR, and this one is not a step
> toward it.

**The replay's verdict is respected by not being this ADR's subject.** #1844's replay
recommended against opening the one-envelope sighted-read ADR *now*, and ordered the
allocation change (`EPISODIC_SUPPLEMENT_LIMIT`) and then the trigger (#838) ahead of it.
None of those three is touched here: this decision adds no read to the loop, no model
call, and no budget to the retrieval path. Its cost is a longer prompt on paths that
already run, which is the one lever the replay did not measure because it is not a
retrieval question.

**And it is deliberately not evidence about the envelope in either direction.** If the
tail door turns out to answer a class of second-turn questions cheaply, that says
nothing about whether a sighted citation hop reaches a three-month-old exchange — the
replay's 22.8pt `hop` share is measured over *retrieved* records, which §2 keeps
phrase-only precisely so this change cannot be mistaken for a partial answer to it. A
later lane weighing the envelope reads #1844's numbers, not this ADR's consequences.

### 11. What the implementing lane owes

One lane, after this ADR merges (ADR-0015 §5, golden rule 5). It is adaptation across
three subsystems and adds no new machinery, so it is one change under ADR-0137 §1 —
the same cut ADR-0221 §12 made for its own Lane D over the same three sites.

1. `learning/observer.py`: `_outcome_lines` renders §3's second line; the ceiling
   constant and the elision helper are written out at this site; the observation
   system prompt's assistant-half paragraph names both lines.
2. `planning/planner.py`: the tail assembler in `_render_request` emits §1's line after
   `_render_record`'s bullet; the ceiling constant and elision helper are written out
   here; `_render_record` itself is not modified.
3. `orchestration/composing.py`: the same, in the tail loop that already calls
   `_render_delivery`.
4. The elision counter §5's fourth clause requires, at each site.
5. §9's counting hook: a metrics mapper for the `"observe"` seam in
   `orchestration/engine.py`, mirroring `_observed_due`'s for the scheduled run.
6. §8's twelve assertions, and the deletion of ADR-0221 §11's test 4 with the narrowing
   of its test 5.

> **Normative.** A lane implementing the above and also embedding the reply, adding a
> retrieval argument for it, rendering it in the retrieved group, touching
> `benchmarks/`, stamping an origin mark, or changing `core/types.py` or
> `core/protocols.py`, has exceeded this decision.

### 12. Deferred, by name

- **Retrieval by the reply's text, and embedding it.** §10. Its own ADR; nothing here
  is a step toward it.
- **The sighted-read envelope** — a planner-emitted query, a sighted citation hop, a
  sighted outward fetch. #1844, whose replay recommends the allocation change and the
  trigger (#838) ahead of it. Fired by whoever takes that ruling.
- **The origin mark on the captured episode.** ADR-0221 §6 and §13, and #1868. Still
  its own ADR and its own lane; §5's escaping is what stands in for it meanwhile, and
  this decision makes that reliance live rather than theoretical.
- **A `FeedbackEvent` naming a typed act** (#1842's fifth requirement). ADR-0221 §13
  defers it and §9 deliberately does not build it as an instrument.
- **The source archive and its retention** — #1843 and milestone 21 of #1318.
  Untouched.
- **Promoting §4's ceiling to a `Settings` field.** Declined here as machinery ahead of
  evidence; fired by §5's counter pair showing the ceiling binds at a share a
  deployment would want to tune.

### 13. Scope

> **Normative.** This ADR changes no file under `src/ai_assistant/core/`. It adds no
> `core` type, no field, no enum member, no Protocol and no member of one; it adds no
> `Settings` field, no wire operation, no tool, no `RoutableOperation` member and no
> member of the promoted `AssistantEngine` surface. `PROTOCOL_VERSION` does not move.

> **Normative.** This decision changes no storage, no capture and no retention.
> `EpisodicMemory` is written exactly as ADR-0221 §1, §2 and §5 fix it,
> `episode_retention` is unmoved, and ADR-0074 §7's horizon still bounds the reply's
> life.

> **Normative.** Nothing here authorises egress, relaxes a permission floor, widens a
> grant, or is cited toward a designation, a registration or a destination. Nothing
> here places a class as speakable on any channel or unplaces one, and no placement is
> stamped differently.

**ADR-0004 §7's minimisation, revisited because this decision is the limb ADR-0221
answered by refusal.** That ADR discharged §7 partly by observing that *"the one
genuinely new limb is egress rather than storage … §3 answers it by never putting the
reply there, which is a stronger answer than a budget."* This ADR gives up the stronger
answer, so it owes the weaker one properly, and §4 and §5 are it: the reply goes to a
model on paths that already send that model the user's own words for the same
exchange, bounded by a stated ceiling, elided legibly, counted, and to no third party
this system was not already talking to for that turn. Retention is unchanged and the
user-facing rights are unchanged — `assistant beliefs --kind episodic`,
`assistant forget`, `assistant forget-conversation`, each mirrored on the gateway.

## Consequences

- **The assistant can refer back to what it said.** #1314's motivating experience —
  a second turn that answers *"which one did you recommend?"* about the turn before —
  works for the conversation tail, which is where that question is asked.
- **The observer can propose records of the assistant's own conduct**, which ADR-0162
  §8 has licensed since it was ratified and nothing could exercise. §9 is how the
  system finds out whether it does.
- **ADR-0162 §8's third clause acquires real work**, and with it a real failure mode:
  a model that launders the assistant's assertions into the user's model. The prompt's
  partition, the whole-episode citation and §9's laundering count are the three things
  standing against it, and the first two were built for exactly this day.
- **The interactive `observe` seam becomes as legible as the scheduled one**, which is
  a gap §9's hook closes in passing rather than a benefit this decision claims.
- **Two of the three render populations are still byte-identical**, and the benchmark
  harness is untouched for two independent reasons rather than one, so no published
  number moves.
- **Every prompt on the turn path gets longer**, bounded by §4 and typically by much
  less. That is the cost, it is paid on every turn, and §5's counter pair is what
  tells a later lane whether the bound was set right.
- **A reply is now model prose reaching a model prompt**, so `_quoted_span` and the
  deferred origin mark stop being a theoretical control and become the live one. ADR-0221
  §6's gap is unchanged in size and larger in consequence.
- **What would trigger revisiting this.** §5's counter pair showing the ceiling binds
  on a large share of renders; §9's measure coming back near zero, which would say the
  observer door was not worth its prompt; a measured need for the retrieved group to
  carry replies, which would be a different decision on different evidence; or #1844's
  envelope being opened, which would supply a better mechanism for the far-past case §2
  declines.

## Alternatives considered

- **Render the reply instead of the phrase.** Rejected in §1. The two are different
  facts and the phrase is the only typed, unforgeable statement of what the pipeline
  did; a reply saying "I've set that up" beside a parked step would be the model's only
  account of the turn.
- **Render the reply in the retrieved group too.** Rejected in §2 on three independent
  grounds — the record was not retrieved for its reply, ADR-0205 §5 drew this line at
  these sites already, and it is what keeps the benchmark harness untouched by
  construction. The far-past reference-back it would partly serve is the citation hop,
  which is #1844's and is deferred.
- **Restrict the tail render to the most recent few turns.** Weighed and rejected. It
  bounds the block more tightly than §4 does, but the tail is a transcript — the
  composing prompt says *"The block below … is this conversation so far"* — and a
  transcript whose assistant half vanishes partway up is more confusing than one with
  no assistant half at all. It also introduces a second unmeasured number to defend.
- **Drop the reply entirely past the ceiling, rather than eliding.** Weighed in §5 and
  rejected: it blinds the reader to precisely the long replies a reference-back is most
  likely to be about, and it trades a legible partial for an invisible absence.
- **A head-and-tail composite instead of a prefix.** Rejected in §5. It answers the
  meaning-depends-on-the-ending worry, but needs a join marker, which is a second
  forgeable surface inside the rendered line, for a gain nothing has measured.
- **Make the ceiling a `Settings` field.** Deferred in §12 rather than rejected. Three
  render sites would each need the value plumbed to them, which is machinery ahead of
  the evidence that any deployment wants a different number; the module constant
  follows the phrase tables' precedent and §5's counter pair is what would justify
  promoting it.
- **Add a field marking a proposal as an act-record, and count that.** Rejected in §9.
  It would make the measurement cheap by building, as an instrument, the typed-act
  surface #1842's fifth requirement and ADR-0221 §13 both defer to their own decision —
  and the only producer that could set it is the model, since ADR-0162 §8 says in terms
  that the distinction is *"not mechanically checkable"*.
- **Make the act-record share a measure of `ai-assistant-measures`.** Rejected in §9.
  ADR-0120 §10 rules that report reads the trace store and nothing else, and ADR-0119
  rules a trace never contains the Tier 0/1 content this figure has to read. The figure
  borrows ADR-0141's reporting *form* without joining its instrument.
- **Open the sighted-read envelope in the same ADR.** Rejected in §10 on the #1844
  replay's own recommendation, and on the ground that the two changes share nothing:
  one shows more of a record already selected, the other adds a read.

## What this records against earlier ADRs, under ADR-0082 §1

- **ADR-0221 §3** — partially superseded as §6 states: the closing "rendered into no
  model prompt" sentence and the no-budget clause, at the three sites named, and
  nothing else of §3.
- **ADR-0221 §11** — test 4 deleted, test 5 narrowed, both under §8. The deletion is
  the one §11 itself provides for: *"This is the test a reader lane must consciously
  delete."*
- **ADR-0162 §8** — **not** superseded by this ADR, and restated in §7 as the governing
  law. Its first clause was already partially superseded by ADR-0221 §4; the four
  boundary clauses bind here as ratified.
- **ADR-0205 §5** — read rather than changed. Its tail-only rule for the delivery fact
  is the precedent §1 and §2 follow, and no delivery rendering moves.
- **ADR-0098 §2 and §9** — read rather than changed. §5's held-data rule for the
  elision marker is §2's requirement applied to a new part of the line, and §8's third
  assertion is §9's regression shape applied to the new span.
- **ADR-0086 §4** — read rather than changed. Its elision/tombstone distinction is the
  argument §5 uses for why a render budget is not a stored prefix.
- **ADR-0119, ADR-0120 and ADR-0141** — read rather than changed. §9 borrows ADR-0141's
  reporting form, declines membership of ADR-0120's instrument on ADR-0120 §10's own
  rule, and gives ADR-0119's no-content rule as the reason the figure cannot be a
  trace-stream rate. No measure moves, no seam set changes, and `ai-assistant-measures`
  gains nothing.
- **ADR-0004 §7** — discharged again in §13, on a weaker footing than ADR-0221's,
  which is stated rather than glossed.
