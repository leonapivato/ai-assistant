# 227. A record the citation hop reached renders its reply, and the test that says so runs the real renderer

- Status: Proposed
- Date: 2026-09-03
- **Partially supersedes:**
  [ADR-0222](0222-the-stored-reply-is-read-back-in-the-conversation-tail-and-by-the-observer.md)
  — **§2's first normative clause, in the single respect that a record this turn's
  citation hop reached renders its `outcome` at `orchestration/composing.py`'s request
  assembler; and §5's eligibility enumeration, in the single respect that such a
  rendered reply is counted on the pair that section already requires.** §2's clause
  reads *"No record of the **retrieved** group at either request assembler renders its
  `outcome` where it carries a `disposition`"*, and §6 below shows the working: a
  reader holding only ADR-0222 refuses to render the reply of a record ADR-0226's hop
  fetched by pointer, which is ADR-0070 §1's test met. **§2's second normative clause
  — that `benchmarks/` is untouched and every prompt `render_context` builds is
  byte-identical — binds entire and untouched**, and §3 below is written so that it
  stays true by construction rather than by a gate. The **retrieved** group proper,
  the **episodic supplement**, and the records the **sighted query** serviced all stay
  phrase-only; §2's three reasons are answered one by one in §6, and each of them
  still reaches those three populations. §1, §3, §4, §6, §7, §8 and §9 of ADR-0222 are
  untouched: §1's tail rule and its `_render_record` prohibition, §4's ceiling and its
  arithmetic, §5's prefix rule, its held-data marker, its one-statement rule and its
  no-reply-text rule, and §8's tests 3 to 9, 10 and 11 all bind as ratified and are
  extended in **application** rather than in text.
- **Amends** [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
  — **§11's item 1, and that item alone: it gains the fidelity requirement its
  assertion needs.** Item 1's sentence *"the answer carries it"* is exactly the right
  assertion and is not replaced; §7 below adds that it is asserted through the
  production renderer, over an episode shaped as the capture site writes one. A reader
  holding only ADR-0226 would accept a test this ADR refuses — that is ADR-0082 §1's
  test met, so the record is owed — and it is written as a `Status` qualifier and an
  appended dated note carrying the added clauses verbatim, the mechanism ADR-0224 used
  on ADR-0162.
- **ADR-0226 §7's missing render rule is a *stacked addition*, recorded here and
  nowhere else** (ADR-0082 §1). §7 states the fourth group's construction, position,
  deduplication, evaluation timing and consumer rules and says **nothing** about
  rendering, so no sentence of it becomes false or over-wide when §1 below supplies
  the rule: *"Adding an obligation that contradicts no sentence the earlier ADR wrote
  is a stacked addition: it is recorded in the ADR that makes it, and nowhere else."*
  The clause that in fact governed the fourth group's rendering — and that a reader
  would have acted on — is ADR-0222 §2, which is why the supersession is there and not
  here. §10 shows the working.
- **No other ADR is superseded or amended.** ADR-0226 §3's namer rule, §6's budget and
  §7's grouping, deduplication and evaluation clauses are untouched and two of them are
  load-bearing here; ADR-0221 §3's phrase table and its enum-absent fallback, ADR-0205
  §5's tail-only delivery fact, ADR-0098 §2's non-forgeability, ADR-0162 §8's boundary
  clauses and ADR-0158 §4's positional argument all bind as ratified. §10 shows the
  working for each one a reader would expect to have moved.
- **This ADR changes no code, adds no `core` type, adds no field to one, adds no
  Protocol and no member to one, and moves no `PROTOCOL_VERSION`.** §9 states what the
  implementing lane owes; nothing implements against it until it has merged
  ([ADR-0015](0015-simplify-the-agent-workflow.md) §5, golden rule 5).

## Context

### Where this comes from

`track:planning` (#1908) milestone 1 shipped [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
and its two implementing lanes, and its exit was held by the owner on 2026-09-03 after
two live probes against the hub at `b02d9cb6`. Both probes ran the milestone's own
headline exit clause — a cross-conversation question whose answer exists only in a
past reply — and both failed, for two independent reasons.

**#1929, probe 1, is the trigger.** The planner was shown an act-record belief saying
*"the assistant declined"* over a reply that had in fact named a bank, judged the
supply sufficient, and emitted nothing: `trigger=not_fired servicing=not_asked
kinds=() returned=0`. That is `track:planning`'s Lane C and is not this decision's.

**#1944, probe 2, is this one.** The trigger fired, both kinds were serviced, and ten
records arrived — `trigger=fired kinds=('sighted_query', 'citation_hop')
servicing=serviced returned=10` — and the reply was still *"I don't have a record of
the specific game I named — the earlier exchange shows you asked me to recommend one
two-player board game, but the game itself isn't in what I can see here."* The hop
reached the episode. The composer was shown the episode. The composer was not shown
its reply.

### What the tree actually does, verified against `origin/main`

The three facts that compose the gap are each checkable, and one of them is not what
#1944 says it is.

**A captured episode carries the reply in `outcome` and nowhere else.**
`Engine._capture` writes `outcome=None if composed is None else composed.text` and
`content=_exchange_of(turn, step, resumed=resumed)`, and `_exchange_of` renders
*"The user asked: …"* plus the plan rationale and the tool id. So the vocabulary of
what the assistant *said* is in `outcome`; `content` carries what the user said and
what this system planned.

**`_render_record` renders `content` always and `outcome` only where the record
carries no `disposition`.** At `orchestration/composing.py` and at
`planning/planner.py` alike, an `EpisodicMemory` renders its bullet, and then
`how it turned out:` carrying `_disposition_phrase(record.disposition)` where a
`disposition` is present and `record.outcome` only where it is not. ADR-0221 §3's
enum-absent fallback is that second arm; a post-ADR-0221 episode always takes the
first. ADR-0222 §1 put the reply line in the **caller** — `_reply_lines`, called from
`_render_memories`'s tail loop and from nowhere else — precisely so that
`benchmarks/memory/answer.py`, which imports `planner._render_record` by name, could
not grow a line.

**The fourth group is appended to `memories` and is indistinguishable downstream.**
`LearningLoop._turn` does `memories += audit.read.records` after
`service_read_request` returns, and constructs the `TurnResult` over that.
`_render_memories` then calls `_split_conversation_tail`, which splits on the leading
run of `EpisodicMemory`, and renders everything that is not that leading run through
the retrieved loop — `[_render_record(record) for record in retrieved]`, with no
`_reply_lines` call. So the serviced records render exactly as retrieved ones do, and
nothing in the composing stage knows they are not.

### The claim in #1944 that does not survive contact with the tree

#1944 says of `tests/orchestration/test_engine_read_envelope.py::test_the_reply_vocabulary_question_answers_through_the_hop`
that it *"drives the engine with `_echoing_composer()`, a fake that echoes the fetched
episode's text as the reply. The real composing stage was never on the path."* **That
is false, and the true explanation is worse.** `_echoing_composer()` returns a real
`ComposingStage`; what is fake is the `ModelProvider` under it, and that fake reads
the actual assembled prompt — `prompt = "\n".join(str(message.content) for message in
messages)`, then `return _LENDER if _LENDER in prompt else "I have no record of
that."` The production renderer *was* on the path, and it is exactly the renderer that
would have caught this.

What was not on the path is a record **shaped as production shapes one**. The test's
fixture is `_episode("episode-1", f"{_LENDER} is the best fit for your budget.")` —
the reply's distinctive word in `content`, where every group renders it, and no
`disposition` and no `outcome` at all. Production puts that word in `outcome` on a
record that also carries a `disposition`, which is the one combination no group but
the tail renders. The test therefore asserted a true fact about a record no capture
site writes, and the mechanism it was standing behind was never exercised.

That distinction matters for more than accuracy of the record. A finding that says
"the fake bypassed the renderer" is fixed by driving the renderer; a finding that says
"the fixture was not shaped like the thing" is fixed by shaping fixtures like the
thing, which is a rule and not a repair. §7 states the rule.

### Why ADR-0222 §2 covers the fourth group, and why that is a gap rather than a slip

ADR-0222 was ratified on 2026-09-01 and ADR-0226 on 2026-09-02. §2's clause names
*"the **retrieved** group"*, and when it was written there was no fourth group to
exclude — but there were already three, and §2 plainly means the assembler's non-tail
population: the episodic supplement carries `disposition` and `outcome` on every
post-ADR-0221 episode, §2 says nothing about it, and the implementation keeps it
phrase-only along with the retrieved beliefs because `_split_conversation_tail` puts
both in one bucket. A reader holding ADR-0222 and ADR-0226 and asked whether the hop's
records render their replies reads §2 as the governing clause, finds no rule in
ADR-0226 §7 to displace it, and refuses. So this is ADR-0070 §1's test met on a clause
whose text is ambiguous, and the ambiguity itself is what binds: §6 takes the
conservative route and supersedes rather than reinterpreting.

**ADR-0226 §7 is where the rule should have been and is not.** §7 states the fourth
group's construction, its position, its deduplication, what the evaluation ranges
over and what a consumer may rely on. It states nothing about how it renders. That is
the same shape ADR-0226 §13 records against ADR-0204 §2 — a clause whose premise
stopped holding when a new group arrived — and it is recorded here the same way rather
than papered over as a drafting slip.

### The charter's caution, and this ADR's justification

#1908 writes the caution in on purpose: *"do not justify the loop by memory-benchmark
numbers … the loop's value is *task capability* … **Exits are task-shaped, not
retrieval-shaped.**"* This ADR is justified by the exit clause and by nothing else.
Milestone 1's first exit clause is a cross-conversation reply-vocabulary question
answering through the hop; #1944 shows the mechanism cannot answer it in **any** case,
because the hop's yield is invisible to composing whatever the hop returns. No
benchmark figure is offered here, none moves, and §6 keeps `benchmarks/` byte-identical
as ADR-0222 §2's second clause requires. The claim is that a mechanism whose whole
purpose is to reach a reply cannot reach it, which is a defect and not a datum.

### What this ADR is not allowed to settle

The trigger (#1929) is Lane C's and ADR-0226 §8's judged sufficiency is not touched
here. The observer's act-record accuracy (#1930) is `track:memory`'s. The retrieved
group's rendering, the benchmark harness, #838's coverage layer, milestone 2's
revisable plan and any further kind of read are all outside this decision, and §10
says so against the clauses that would otherwise be read as moved.

## Decision

### 1. A record this turn's citation hop reached renders its reply

> **Normative.** At `orchestration/composing.py`'s request assembler, a
> `MemoryRecord` that **this turn's citation hop reached** and that carries both a
> `disposition` and an `outcome` renders one further continuation line under its own
> bullet, stating the episode's `outcome`, subject to ADR-0222 §4's ceiling and §5's
> elision rule. The `    how it turned out: …` line ADR-0221 §3 renders is unchanged,
> is rendered first, and the reply line never replaces it. This is ADR-0222 §1's line,
> in ADR-0222 §1's shape and order, over a further population.

> **Normative.** A record the hop reached that carries a `disposition` and no
> `outcome` renders the phrase line alone and grows no reply line. One carrying no
> `disposition` renders exactly as it does today. These are ADR-0222 §1's second
> clause, applied unchanged.

> **Normative.** **"Reached by the citation hop" is the whole of the test, and the
> record's group is not part of it.** A record the hop resolved through a named
> label's `Provenance.evidence` renders its reply whether it entered the fourth group
> or was deduplicated out against the pre-servicing supply (ADR-0226 §7). A record
> the hop did not reach does not render its reply, whatever group it sits in.

> **Normative.** **The reply line is emitted by the caller and not by
> `_render_record`.** ADR-0222 §1's third clause binds this line word for word:
> `_render_record` renders, for every record and every caller, the bytes it renders
> today. No implementation of this ADR puts a line inside a record renderer, at either
> request assembler.

> **Normative.** `planning/planner.py`'s request assembler renders no reply line under
> this section, and gains nothing from it. The planner is called before the servicer
> runs (ADR-0226 §7) and no hop has reached anything when its prompt is built.

> **Normative.** `learning/observer.py` is untouched by this ADR. ADR-0222 §3's rule
> over the observation batch binds unchanged, and no hop reaches an observation pass.

**The reason ADR-0222 §1 gives is the reason here, and it is stronger.** §1 argues
that the phrase and the reply *"are two facts and neither implies the other"* — the
phrase is *"a typed statement of what became of the pass … text this system authored
about its own pipeline"*, and the reply is *"what the user was actually shown"*. On a
hop-reached record the second fact is the entire reason the record is in front of the
model: ADR-0226 §2 admits the hop because *"it is **not a search**, so the reply's
vocabulary never has to match anything; and it reaches the exchange by pointer, which
is the only mechanism that answers 'which lender did you recommend?'"* A hop that
delivers the phrase and withholds the reply delivers the half of the record that was
never in question.

**The test is the *reason* the record is there, not the position it occupies, and that
is deliberate.** ADR-0226 §7 rules that a record the servicing returns which the supply
already held is deduplicated out and *"the copy the supply already held keeps its
position"*. Under a group-shaped test, the exact record a belief cites — the one the
planner asked for by label — would render phrase-only whenever the episodic supplement
happened to have picked it up already, and the turn would fail for the same reason
#1944 records, by a narrower route that no probe would distinguish from success. A
reason-shaped test has no such hole: the hop either reached the record or it did not,
and the answer does not depend on what else the retrieval happened to return. It also
keeps §6's exception argued over one population instead of two, since the ground for
the exception is a property of how the record was fetched.

**Both kinds reaching one record is the hop reaching it.** ADR-0226 §7's union case —
*"a belief's cited evidence that the sighted query also returns"* — enters the fourth
group at the hop's position and consumes one slot. It is a record the hop reached, so
it renders. A record the query alone returned is §2's below.

**Position is unchanged and the group encoding is untouched.** No record moves, no
group is reordered, nothing is interleaved and nothing is promoted into the tail.
ADR-0158 §4's positional argument and ADR-0226 §7's append-whole rule are untouched:
this ADR changes what is written under a bullet and never which bullet is written
where. In particular a hop-reached record is **never** rendered as one of the
conversation's own turns, which `_split_conversation_tail`'s leading-run rule already
makes impossible for anything appended after the supplement.

### 2. The sighted query is a relevance selection, and its records stay phrase-only

> **Normative.** A record the **sighted query** serviced into this turn, and which
> this turn's citation hop did not also reach, renders no reply line. ADR-0222 §2's
> rule reaches it unchanged, and this ADR states no exception for it.

> **Normative.** The **retrieved** group and the **episodic supplement** likewise
> render no reply line at either request assembler. Nothing in this ADR reaches them,
> and ADR-0222 §2 binds over them exactly as ratified.

**ADR-0222 §2's first reason reaches a query-serviced record squarely, in its own
words.** §2 rules the line out because *"A retrieved episode was not retrieved for its
reply … the vocabulary of the reply is exactly what the search key never sees"*, and
*"Rendering a retrieved record's reply spends budget on prose that no part of the
selection ever read."* ADR-0226 §2 says of `SIGHTED_QUERY` that the loop *"services
it by calling `assemble_by_band` over that query under §6's budget, with the band
precedence, per-band composition and kind selection of the retrieval stage's own read
unchanged"* and that *"It is a relevance selection and §13 records it as one"* — the
same mechanism, over the same embeddings, against a key the reply is not in. It is the
retrieval stage's read performed a second time with a planner-composed statement, and
§2's first reason is a fact about that mechanism rather than about which stage invoked
it.

**And a second, structural reason.** The query's records are the ones ADR-0226 §6 lets
the hop starve — *"the query is serviced with whatever is left, which may be nothing"*
— so their number varies from nought to ten with the hop's yield. Spending render
budget on a population whose size is decided by how many pointers a different kind
followed is the shape §2's third reason objects to in the harness case: prompt cost
that no part of the selection asked for.

**Stated rather than left to the lane, because the audit already distinguishes them.**
ADR-0226 §9's record carries `kinds`, and probe 2's line reads
`kinds=('sighted_query', 'citation_hop')`: the two kinds are already separately
recorded, so a decision that treated them alike would be discarding a distinction the
system holds. §3 says how the render site comes to hold it too.

### 3. How the renderer knows: supplied, never inferred, and no second label scheme

> **Normative.** Which records this turn's citation hop reached is **supplied to the
> composing stage** by the component that knows it, and is never inferred at the
> render site. No implementation derives it from a record's position in `memories`,
> from a prefix length, from `Provenance.evidence` read back at the renderer, from
> `ActionPlan.read_request`, or from any other reconstruction.

> **Normative.** The set is **recorded where the kind is known** — at the servicer,
> which is the one place `CITATION_HOP` and `SIGHTED_QUERY` are distinguishable — and
> is carried from there to the render site as data. It carries every record the hop
> resolved that the turn's supply holds after servicing, the deduplicated-out ones
> included (§1), and nothing else.

> **Normative.** The set is **empty** on every turn that did not fire, on a turn whose
> servicing ADR-0226 §5 declined, on a turn whose servicing failed or was partial —
> ADR-0226 §5's all-or-nothing posture leaves the supply as planning saw it — and on a
> turn whose hop resolved no live record. An empty set renders no reply line anywhere,
> and the assembled prompt is then byte-identical to what it is today.

> **Normative.** **No record identifier reaches a model and none is accepted from
> one.** ADR-0226 §3's namer rule binds this carrier entire: the identifiers in it are
> held data, used to decide which line the assembler writes, and they are rendered
> into no prompt, no log, no trace and no audit record. This ADR introduces **no
> second label scheme**, adds no member to `ReadKind`, and adds no marking to a
> `MemoryRecord`.

> **Normative.** The carrier adds **no field to a `core` type, no member to a
> Protocol, and no `PROTOCOL_VERSION` move**. It lives inside `orchestration`, which
> holds the servicer, the loop, the engine and the composing stage alike.

> **Normative.** No implementation copies, mutates or reconstructs a `MemoryRecord` to
> carry this fact, and no `TurnResult` is constructed twice or edited after
> construction. ADR-0226 §7's *"constructed **once**, over the deduplicated union"*
> binds unchanged.

**This is exactly the shape ADR-0205 §5 already has at this site, and citing it is
the whole argument.** The delivery fact *"is written under the turn it is about, and
only in the tail"*, and it reaches the composing stage as a `Mapping[str,
SpokenDelivery]` keyed by the episode it qualifies — **supplied, not looked up**:
`ComposingStage.compose`'s own contract says the stage *"gains no store, no second
context assembly and no second retrieval for it"*. A set of record ids the hop reached
is the same kind of fact travelling the same way, and `_render_delivery` is the same
kind of caller-emitted continuation line that `_reply_lines` already is.

**Why inference is refused, concretely.** Three reconstructions are available at the
render site and each is wrong in a way a test would not obviously catch. A **prefix
of the fourth group** requires the renderer to know where the fourth group starts,
which `TurnResult.memories` does not say, and to re-derive ADR-0226 §6's
hop-before-query order, which is a second implementation of that clause free to
disagree with the first. **Reading `Provenance.evidence` back at the renderer** marks
every record any supplied belief happens to cite, whether or not the planner named it
and whether or not the hop ran — a superset that renders replies on turns that fired
nothing. **Reading `ActionPlan.read_request`** says what was asked and never what came
back, so it marks records on turns whose servicing failed, which ADR-0226 §5 rules
must leave the supply as planning saw it. ADR-0170 §5's rule that a stage is *"handed
over rather than inferred here"* is the general form, and this is a case where the
inference is not merely inelegant but unsound.

**What the carrier costs, stated because "no core change" is a claim and not a
wish.** `LearningLoop` is a concrete class in `orchestration/loop.py`, not a Protocol;
`LearningLoop.respond` has exactly one caller in the tree, `Engine._run_turn`; and
`ComposingStage` is a concrete class in `orchestration/composing.py`, not a Protocol.
So widening what the loop returns and what the composing stage is given is an
`orchestration`-internal change at one seam and one call site. Golden rule 5 is not
approached and no versioned surface is crossed. §9 leaves the exact shape to the lane
within the clauses above.

**And the audit is not the carrier.** ADR-0226 §9's record is a structured log event
that *"copies no text"* and carries *"no identifier but the correlation id"*. Threading
a render decision through it would put record identifiers on a surface whose whole
discipline is that they are not there. The audit stays what it is.

### 4. The budget: ADR-0222 §4's ceiling, unchanged, unshared and not a second constant

> **Normative.** A reply rendered under §1 is bound by **ADR-0222 §4's ceiling** and
> by nothing else: the longest prefix of the reply whose quoted rendering is at most
> 640 characters, counted on the output of `_quoted_span` with delimiters included,
> the cut taken on the reply's own text. §4's 96-character framing bound and its
> 736-character whole-line bound bind this line too.

> **Normative.** This ADR introduces **no new ceiling, no new constant and no new
> elision rule**. `orchestration/composing.py` is one of ADR-0222 §4's three sites and
> already holds that site's constant; the line this ADR adds is written at that same
> site and reads that same constant. No fourth site is created and no constant is
> shared across a boundary golden rule 1 forbids crossing.

> **Normative.** The reply line **does not count against ADR-0226 §6's record
> budget**, does not reduce it, and does not draw against `RETRIEVAL_LIMIT` or
> `EPISODIC_SUPPLEMENT_LIMIT`. §6's budget is ten **records**, counted after
> deduplication and spent at the servicer before anything is rendered; this is a
> **render** ceiling in characters at a later stage. The two bound different
> quantities and neither is funded out of the other.

> **Normative.** Where ADR-0226 §6's budget truncated the hop, the records it cut
> render **nothing at all** — no bullet, no phrase line and no reply line — and no
> site writes a marker, a count or an "and *N* more" line about them. §6's truncation
> is already recorded in ADR-0226 §9's audit, and this ADR adds no second disclosure
> of it to the prompt.

> **Normative.** Where ADR-0222 §4's ceiling binds on a reply rendered under §1, §5's
> elision applies **verbatim**: a prefix, the marker in held data outside the quoted
> span, the reply's full length in its own characters, and no head-and-tail composite.
> This ADR states no second marker wording and permits no site to render one.

**The arithmetic, stated because ADR-0222 §4 rules that a budget that is not stated is
not a budget.** ADR-0226 §6 admits at most ten serviced records, and at most ten of
them can be hop-reached. Ten reply lines at §4's per-line bound of 736 characters is
**7,360 characters** of added prompt on a turn that fired and whose hop filled the
budget with episodes carrying both fields — the true worst case for any reply text,
because §4's ceiling is counted on the quoted rendering rather than on the source and
is therefore immune to the twelve-characters-per-emoji expansion §4 records. The
composing prompt's total reply-line worst case becomes §4's 14,720 for a twenty-turn
tail plus this 7,360, or **22,080 characters**, and it is reached only on a turn that
both has a full tail of post-ADR-0221 episodes and fired a hop that returned ten
distinct evidence records with replies at or over the ceiling. The ordinary shape the
replay measured is *"one or two beliefs citing one to three episodes each"*, which is
one to three lines.

**Deduplicated-out records do not raise the bound.** A record the hop reached that the
supply already held renders one reply line and consumed no slot of §6's budget, so the
count of reply lines this section adds is bounded by the number of records the hop
resolved rather than by the budget alone — and ADR-0226 §6's two-label cap and
`MAX_EVIDENCE_CITATIONS` bound *that* at 128 in the pathological case. The honest
statement is therefore that this section's worst case is **not** bounded by ten in
full generality. It is bounded in practice by what a belief cites, and the sound bound
is stated rather than the convenient one. A lane that finds this uncomfortable should
file the question rather than invent a ceiling here: capping the number of *lines*
would be a second budget of exactly the kind ADR-0222 §4's third clause forbids this
ADR to introduce. It is named as a follow-up under Consequences and in Alternatives
considered rather than decided here.

**Why not §6's record budget.** Counting a rendered line against a budget of records
would mean a long reply cost a record, which is two units in one number, and it would
make what the servicer admits depend on what the renderer will later do with it — a
coupling ADR-0226 §5 and §7 are written to avoid, since the servicer *"discards no
record on the ground of its class"* and takes no view of any downstream stage.

### 5. The counts: one statement, one pair, both populations

> **Normative.** A reply rendered under §1 is **eligible** in ADR-0222 §5's sense and
> is counted there: it contributes to the eligible count of the assembly it is
> rendered in, and to the elided count where ADR-0222 §4's ceiling bound on it.

> **Normative.** `orchestration/composing.py` emits **one** statement per assembly
> carrying **one** pair, over both populations — the conversation-tail records
> ADR-0222 §1 admits and the hop-reached records §1 above admits. No implementation
> splits the pair into two statements, emits a second pair, or omits the statement on
> an assembly with no eligible record: ADR-0222 §5's *"a missing pair is
> distinguishable from an empty one"* binds unchanged.

> **Normative.** The statement carries **no reply text**, elided or whole, and no
> record identifier. ADR-0222 §5's carrier rule, ADR-0221 §11's test 14 and ADR-0004
> §5 bind unchanged, and this ADR puts the pair on no other surface: no
> `OPERATION` trace, no `core` type, no Protocol member and no side channel.

> **Normative.** `planning/planner.py`'s pair is over ADR-0222 §1's population alone
> and is unchanged by this ADR, and so is `learning/observer.py`'s over §3's. The two
> assemblers' pairs may therefore differ on one turn, which is correct: they render
> different populations.

**One pair rather than two, because of what the pair is for.** ADR-0222 §5 rules that
*"a high **share** of elided renders says the ceiling is wrong, and it is a share
rather than a count precisely because a bare numerator cannot say it"*, and ADR-0222
§4 records that no measurement stands behind 640. Both populations are stored
`outcome`s written by the same capture site, so they are drawn from one distribution
and one share over both answers the ceiling question on a larger sample. Splitting the
pair would buy the ability to compare the two populations' lengths, which no decision
in this corpus turns on, at the cost of ADR-0141 §6's discipline that a figure's
numerator and denominator ride one emitted statement — which is exactly the property
ADR-0222 §5 cites it for.

**And the pair stays honest about zero.** A turn that fired and whose hop reached three
records with no `outcome` reports those three nowhere: they are not eligible, because
eligibility is §1's condition and not "the hop reached it". That is the same rule
ADR-0222 §1 already applies to a tail record with no reply.

### 6. The scoped exception to ADR-0222 §2, argued from §2's own three reasons

ADR-0222 §2 states that *"Three independent reasons put the line here, and any one of
them would do."* An exception to it is owed all three, one by one, and owes as well
the demonstration that each still reaches the populations §2 keeps. Here they are.

**The first reason does not reach a hop-fetched record, and ADR-0226 admitted the hop
for the converse of it.** §2's reason is *"A retrieved episode was not retrieved for
its reply. Retrieval is content-addressed and the reply is not embedded … the
vocabulary of the reply is exactly what the search key never sees. Rendering a
retrieved record's reply spends budget on prose that no part of the selection ever
read."* Every clause of that is a statement about a **content-addressed selection**.
The citation hop is not one: ADR-0226 §2 rules it *"selects nothing by relevance: it
is a **keyed load** in exactly ADR-0208 §1's sense"*, and ADR-0226 §13 adds that *"the
hop needs no supersession at all"* against ADR-0208's one-site clause for precisely
that reason. There is no search key, so there is nothing for the reply's vocabulary to
fail to match; and the record was fetched *for* the reply, so the prose the line spends
budget on is the prose the whole read was performed to obtain. The reason is not
weakened here — it is inapplicable, and it goes on reaching the retrieved group, the
episodic supplement and the sighted query's records exactly as before.

**The second reason is about a different fact, and conflating them is the error this
paragraph exists to prevent.** §2 cites *"ADR-0205 §5 already drew this line at these
two sites … 'The retrieved group carries none, because §5 supplies the facts off the
replay tail and a record retrieved by relevance is not one of those rows.'"* ADR-0205
§5's fact is the **delivery** — what a device reported playing of a turn's spoken
answer — and its tail-only rule follows from where the fact comes from: the facts ride
on `ConversationLifecycle.history`, so a record that is not one of that history's rows
has no delivery to render, and `Engine._paired_deliveries` intersects them before the
stage is called. That is an argument about **availability**, not about desirability: a
retrieved record's delivery fact is not withheld, it does not exist. A hop-reached
record's reply, by contrast, is in the record's own `outcome`, in hand, already read
from the store by the very call the planner asked for. ADR-0205 §5 is untouched by
this ADR and its tail-only rule for the delivery line binds entire (§10).

**The third reason is the harness, and it is the one this ADR must keep true rather
than argue past.** §2 records that *"The harness only ever renders the retrieved
group"*, that `planner._split_conversation_tail` over its records *"always returns an
empty leading episodic run"*, and that *"a harness row carries no `disposition`"* — so
§1's condition is false for it twice. **A third guard applies to this ADR and is
stronger than either**: the harness runs no planner emission, no servicer and no
citation hop, so §1's condition — that this turn's hop reached the record — is false
for every harness row by construction, and §3's carrier is empty in every harness
assembly. **A fourth guard is structural**: §1's fourth clause keeps the line out of
`_render_record`, which is the function `benchmarks/memory/answer.py` imports by name,
so the harness's prompt cannot grow a line even if every other guard were removed.
ADR-0222 §2's second normative clause — *"`benchmarks/` is not touched … every prompt
`benchmarks/memory/answer.py`'s `render_context` builds is byte-identical to what it
builds today. No benchmark result moves"* — is therefore untouched by this ADR and is
carried forward unchanged, and §8's test 11 binds as ratified.

> **Normative.** ADR-0222 §2's second normative clause binds this ADR and its
> implementing lane entire: `benchmarks/` is not touched, every prompt
> `render_context` builds is byte-identical, and no benchmark result moves.

**The narrowest cut, and #1314's line held.** ADR-0222 §2 closes by saying the tail-only
rule *"is also the narrowest cut that serves #1314"* and that reaching the same
question about an exchange from three months ago *"is the citation hop, which is
sighted, which is #1844's territory, and which §10 leaves exactly where the replay left
it."* That sentence names this decision's territory and leaves it open rather than
closing it; this ADR is the decision it was left open for. The cut here is likewise the
narrowest available: one condition, one site, one population defined by how the record
was fetched, and no change to any group's position, order or meaning.

### 7. The test-fidelity rule, and ADR-0226 §11 item 1 re-specified

> **Normative.** A required representative-input test that asserts a fact about **what
> a model was shown** runs the production renderer for that surface, and drives it
> over records **shaped as the production capture site writes them**. A fixture that
> carries in one field what production carries in another asserts nothing about
> production, however faithfully the rest of the path is wired.

> **Normative.** For an episode this means, concretely and as the field assignments
> stand at ADR-0221 §5 and ADR-0222 §1: the user's material and the plan's rationale
> in `content`, the composed reply in `outcome`, and an `ExchangeDisposition` in
> `disposition`. A test asserting that a reply reached a prompt puts the distinctive
> span in `outcome` on a record that also carries a `disposition`, because that is the
> combination the render rules turn on.

> **Normative.** A test of this shape may substitute a fake `ModelProvider`, a fake
> store and a fake clock. It may **not** substitute the renderer whose output the
> assertion is about, and it may not assert over a composed reply produced by a fake
> that did not read the assembled prompt.

> **Normative.** ADR-0226 §11's item 1 is subject to all of the above. Its sentence
> *"the answer carries it"* is unchanged and is the right assertion; what this section
> adds is that it is asserted through `orchestration/composing.py`'s production
> renderer, over an episode carrying the reply's distinctive word in `outcome` beside
> a `disposition`, with that word absent from `content`.

> **Normative.** The re-specified item 1 is owed by the lane implementing this ADR,
> and the existing test is **rewritten rather than supplemented**: a second test
> beside a fixture that cannot fail is a test suite that reports two greens for one
> guarantee.

**This is a rule and not a repair, which is the whole reason it is stated.** The
failure #1944 records is not that somebody wired a fake in the wrong place — the real
`ComposingStage` was on the path, and the fake model read the real prompt. The failure
is that the fixture put the answer's vocabulary where every group renders it, so the
assertion was true of a record shape no capture site produces and the mechanism under
test was never exercised. That failure mode is invisible to review of the test, because
the test reads correctly; it is visible only by comparing the fixture with the capture
site. A rule that names the comparison is the cheapest instrument available, and it
generalises: ADR-0222 §8's tests 1 and 2 have the same shape and the same exposure, and
so will every future test of a render rule keyed on a field.

**And the corpus already states half of it.** ADR-0226 §11's preamble rules that each
test is *"a test over behaviour rather than over a call count"*, and item 2 insists on
assertions *"over the audit and over the supply, not over a mock's call count"*. The
missing half is that behaviour asserted over a fixture unlike production is not the
behaviour. This section states it once so that it is cited rather than rediscovered.

### 8. The tests this decision owes

> **Normative.** The implementing lane owes a test for each of the following, and each
> is a test over behaviour rather than over a call count.

1. **The hopped episode's reply reaches the composed prompt** — ADR-0226 §11 item 1 as
   §7 re-specifies it. A store holding an episode whose `content` carries the user's
   question and whose `outcome` carries a word the user never used, beside a
   `disposition`; a belief citing that episode and carrying the question's vocabulary;
   a blind read that returns the belief and not the episode; a planner naming the
   belief's label. Driven through the engine with the production `ComposingStage`, the
   composed answer carries the word from `outcome`. This is the milestone's exit shape
   and the test that fails if the hop is merely wired.
2. **The control, unchanged in force.** The same store, question and composer with a
   planner that asks for nothing: the word is unreachable and the answer says so.
3. **A query-reached episode's reply does not reach the prompt.** The same record shape,
   serviced by a `SIGHTED_QUERY` and reached by no hop: the assembled prompt carries its
   bullet and its phrase line and no reply line, and a distinctive span of its `outcome`
   occurs nowhere in the prompt. This is §2 asserted positively rather than assumed.
4. **A record both kinds reached renders once and renders its reply.** ADR-0226 §7's
   union case: one bullet, one reply line, and the record at the hop's position.
5. **A deduplicated-out hop record renders its reply where it already sits.** A record
   the episodic supplement already held and the hop also reached keeps its position and
   grows the reply line. This is §1's third clause, and it is the case a group-shaped
   test would miss.
6. **The tail is unchanged, byte for byte.** A turn with a conversation tail and no
   emission assembles a prompt identical to today's; a turn with a tail *and* a
   serviced hop renders the tail's lines identically and adds only the hop's.
7. **The empty cases render nothing.** A turn that did not fire, one ADR-0226 §5
   declined, one whose servicing failed, and one whose hop resolved no live record each
   assemble a prompt byte-identical to today's, with no reply line anywhere outside the
   tail.
8. **The retrieved group and the supplement still carry no reply**, at both request
   assemblers, on a turn that serviced a hop. ADR-0222 §8's test 10 retained over the
   population §2 keeps, and asserted on the turn shape that could break it.
9. **The benchmark harness renders no reply and no bytes move.** ADR-0222 §8's test 11
   binds unchanged; `render_context` over records built as `benchmarks/memory/ingest.py`'s
   `exchanges_of` builds them is byte-identical to today's, and `_render_record` called
   directly on a record carrying both fields emits no reply line.
10. **The ceiling, the elision and the escaping bind on this line too.** ADR-0222 §8's
    tests 3 to 8, asserted at this site over a hop-reached record: a reply whose quoted
    rendering is exactly the ceiling renders whole and unmarked, one character over
    renders a prefix with the marker and the source-length figure, astral and CJK and
    newline replies render a span of at most the ceiling, the prefix is decodable as
    JSON, the whole line is at most 736 characters, and a reply containing this
    system's own elision wording renders unmarked where it is under the ceiling.
11. **A reply carrying this system's syntax writes no second line.** A hop-reached
    record whose `outcome` contains a newline followed by `    how it turned out:` and
    a well-formed bullet renders as one line and produces no second continuation line
    and no second bullet. ADR-0098 §9's regression shape applied to the new span.
12. **The counts are one pair over both populations.** An assembly with tail replies
    and hop replies reports one statement whose eligible count is the sum and whose
    elided count is no greater; an assembly with eligible replies and no elision reports
    a non-zero denominator and a zero numerator; an assembly with neither reports zero
    and zero rather than staying silent; and no such statement carries reply text or a
    record identifier.
13. **No identifier reaches a prompt, a log or the audit.** On a turn that serviced a
    hop, no record identifier from §3's carrier appears in the assembled prompt, in any
    emitted log event, or in ADR-0226 §9's record — which carries the correlation id and
    no other identifier, as its own test asserts.
14. **The planner's assembler is unchanged.** `planning/planner.py`'s prompt for a turn
    is byte-identical to today's in every case above, tail included; the planner runs
    before the servicer and renders no reply line under this ADR.

### 9. What the implementing lane owes

> **Normative.** This ADR is implemented by **one lane**, after this ADR has merged
> (ADR-0015 §5, golden rule 5). Its diff is confined to `src/ai_assistant/orchestration/`
> and `tests/orchestration/`. It touches no `core` file, no Protocol, no
> `PROTOCOL_VERSION`, no `benchmarks/` file, no other subsystem, and no ADR.

> **Normative.** The lane owes: the servicer recording which records the hop reached
> (§3); the carrier from there to `orchestration/composing.py`'s assembler through the
> loop and the engine (§3); the render rule at that assembler (§1), emitted by the
> caller and not by `_render_record`; the counts folded onto the one existing statement
> (§5); §8's fourteen tests, with ADR-0226 §11 item 1's existing test **rewritten**
> under §7 rather than supplemented; and the docstrings this corpus expects, citing
> this ADR by number at each site it changes.

> **Normative.** The lane's required review set is **adversarial and architecture**.
> The render sites are ADR-0222's contract surface and the carrier crosses three
> modules of one subsystem, which is the shape ADR-0015 §1's second lens exists for.

> **Normative.** The lane changes no ADR-0226 §9 audit field, adds no `ReadKind`
> member, adds no `Settings` field, and adds no configuration for anything this ADR
> decides.

**One lane and not two, because the change is one mechanism.** The carrier without the
render rule renders nothing and the render rule without the carrier cannot be written;
splitting them would produce a first PR whose only test is that a value travels, which
is a test over a call count in a different costume.

**And the audit is the measurement, unchanged.** ADR-0226 §9's record already carries
`trigger`, `kinds`, `servicing`, `returned`, `new` and `deduplicated`, which is what a
re-probe reads to say whether the mechanism fired and yielded. This ADR adds no
instrument, because the fact it fixes is checkable from the reply itself: the probe
question's answer either carries the word or it does not.

### 10. Scope, and what this records against earlier ADRs

**This ADR partially supersedes one ratified ADR, in two scopes, and amends one
other, in one place.** That is a classification of this change and is therefore
stated as prose rather than marked (ADR-0089 §1); what follows is the working under
ADR-0070 §1's test and ADR-0082 §1's, and for the clauses a reader would most expect
to have moved with them and which did not.

**ADR-0222 §2's first normative clause is partially superseded, in one respect.** It
rules that *"No record of the **retrieved** group at either request assembler renders
its `outcome` where it carries a `disposition`."* §1 above admits exactly one further
population — a record this turn's citation hop reached — at exactly one of those two
assemblers. A reader holding only ADR-0222 would refuse to render it: §2's clause is
stated over the assembler's whole non-tail population in effect if not in letter, the
implementation renders it that way, and #1944 read it that way. ADR-0070 §1's test is
met and §3's partial form is the sanctioned tool. ADR-0222's title carries no claim
this narrows; ADR-0070 §1 permits no rewrite of ratified text, so the `Status` line is
where a reader learns.

**ADR-0222 §2's second normative clause is untouched and is restated as this ADR's own
obligation** (§6), because it is the clause a careless implementation would breach
first.

**ADR-0222 §5's eligibility enumeration is partially superseded, in one respect.** It
counts *"the number of records that were eligible to render a reply under §1 or §3"*.
§5 above adds this ADR's own population to that count, on the same one statement, at
one of the three sites. Every other clause of ADR-0222 §5 binds unchanged: the prefix
rule, the held-data marker, the one-statement rule, the no-reply-text rule, the
not-durable-totals rule and the structured-log carrier. The scope is the enumeration
and nothing else.

**ADR-0222 §1 is *not* superseded, and the distinction is worth stating.** §1 rules
what a **conversation-tail** record renders; it does not rule that no other record
renders anything, which is §2's job. So §1's clauses stay true word for word and this
ADR states its own rule in §1's shape rather than widening §1's text. §1's third
clause — the line is the caller's and `_render_record` renders what it renders today —
is not merely untouched but is the load-bearing guard that keeps ADR-0222 §2's
harness clause true (§6).

**ADR-0222 §4 is untouched and this ADR adds nothing to it.** §4's ceiling, its
three-sites-one-number rule, its no-`Settings`-field rule and its third clause — *"No
other budget, ceiling or elision is introduced by this ADR"* — all bind, and §4 above
introduces none. `orchestration/composing.py` is one of §4's three sites, not a fourth.

**ADR-0222 §8's tests 10 and 11 are untouched and are re-owed here.** Test 10 keeps the
retrieved group reply-free and test 11 keeps the harness byte-identical; §8's items 8
and 9 above re-assert both on the turn shape this ADR creates, which is the shape that
could break them.

**ADR-0226 §7 gets no record at all, and the reason is ADR-0082 §1's own test rather
than economy.** §7 states the fourth group's construction, position, deduplication,
evaluation timing and consumer rules; it states **no** rendering rule. Apply the test
to §7's text: would a reader holding only ADR-0226 now act differently on one of its
sentences, or read one more widely than it now holds? Take them in turn. Its
deduplication clauses, its *"appended whole after the episodic supplement, never
interleaved"* clause and its *"keep their positions, their order and their meanings"*
clause are untouched, because §1 above moves no record. Its *"constructed **once**,
over the deduplicated union"* clause is untouched and is restated as an obligation in
§3 above. Its *"Nothing is planned, composed or rendered over a supply wider than the
one this section returns"* clause stays true word for word: §1 renders over exactly
that supply and never wider. Its class clause and its evaluation clauses are untouched.
Not one sentence of §7 becomes false or over-wide, so this is ADR-0082 §1's **stacked
addition** — *"an obligation that contradicts no sentence the earlier ADR wrote … is
recorded in the ADR that makes it, and nowhere else"* — and a record on ADR-0226 §7
would be the book-keeping record that section forbids a reviewer to demand.

**That §7 carried no render rule is still a gap, and saying where it was closed is not
the same as recording it against §7.** The clause a reader *would* have acted on is
ADR-0222 §2, written the day before ADR-0226 and reaching the assembler's whole
non-tail population; it is that clause which is over-wide once the fourth group exists,
and the supersession is written there. The shape is the one ADR-0226 §13 itself records
against ADR-0204 §2 — a clause whose premise stopped holding when a new group
arrived — and it is stated plainly here rather than glossed as a drafting slip.

**ADR-0226 §11 item 1 is amended and not superseded, and here the test comes out the
other way.** Its sentence *"the answer carries it"* is the right assertion and stands;
no item of §11 is deleted and none is replaced. But item 1 is an **obligation to write
a test**, and §7 above shrinks the set of tests that discharge it: a reader holding
only ADR-0226 accepts a fixture this ADR refuses, which is reading the clause more
widely than it now holds. ADR-0082 §1's test is met on that ground and on no other, so
the record is owed — a `Status` qualifier on a line carrying no leading token (ADR-0082
§2) and an appended dated note carrying §7's clauses verbatim.

**ADR-0226 §§2, 3, 5, 6, 8, 9 and 13 are untouched, and three of them are
load-bearing.** §2's keyed-load characterisation of the hop is the ground for §6's
first reason above; §3's namer rule binds §3's carrier entire; §6's budget is neither
spent nor reduced by §4 above. §5's channel scoping stands, so this ADR reaches no
unbounded-audience turn: a declined servicing reaches no record here, and the composed
prompt on such a turn is byte-identical to today's. §8's judged sufficiency is #1929's
and is untouched. §9's audit gains no field.

**ADR-0221 §3 is untouched.** Its phrase table, its enum-absent fallback and its
three-populations argument bind unchanged. The `how it turned out:` line is rendered
first and unchanged on every record this ADR reaches, and no site trades the phrase for
the reply — ADR-0222 §6's restatement of what survives §3 governs here word for word.

**ADR-0205 §5 is untouched, and §6 shows why it does not reach.** Its delivery fact
stays tail-only, its facts stay supplied off the history the engine already read, and
this ADR adds no delivery to any group. What this ADR borrows from it is a *shape* —
a caller-emitted continuation line fed by supplied data — and borrowing a shape is not
amending a clause.

**ADR-0098 §2 is untouched and binds this line entire.** Every span on a reply line
this ADR adds goes through `_quoted_span`; the elision marker is held data outside the
span; and the framing is a constant. The non-forgeability property ADR-0222 §5 argues
for is not weakened by rendering the same line over a further population.

**ADR-0162 §8's four boundary clauses are untouched and are not reopened.** ADR-0222 §7
restates them as governing law for the observer, and this ADR reaches no observation
pass at all: nothing here changes what the observer is shown or what it may propose.

**ADR-0158 §4 and §5 are untouched.** §4's positional argument stands and this ADR
moves no record; §5's three-group clause on `Planner.plan` stands and this ADR reaches
nothing before the planner; §5's sameness clause was already partially superseded by
ADR-0226 §7 and is not touched further here.

**ADR-0208, ADR-0203, ADR-0204, ADR-0210 and ADR-0199 are untouched.** This ADR reads
no store, opens no selection site, admits no record, drops none, and takes no
evaluation. It decides what is written under a bullet for records the turn already
holds, which no clause of any of those five reaches.

**ADR-0014 §2's frozen plan is untouched.** Nothing here re-plans, re-calls the planner,
or re-composes.

## Consequences

**Milestone 1's first exit clause becomes reachable.** Before this decision the hop's
yield was invisible to composing in every case, so the exit's headline question could
not be answered however well the trigger performed; #1929's fix alone would have moved
the audit line and not the reply. After it, a fired hop that reaches the exchange puts
the exchange's reply in front of the model, which is what ADR-0226 §2 admitted the kind
for.

**One more population of the prompt now carries text the user was shown.** ADR-0222 §7
records that the day the observer sees the reply is the day ADR-0162 §8's third and
fourth clauses have real work; the same is true one rung further out. The model
composing an answer is now shown, on a hop-reached record, both what this system did
and what it said — and it can misattribute the second as a fact about the world exactly
as the observer can. The mitigation is the same one already in place: the span is
quoted, the attribution is held data, and the phrase line is rendered beside it and
never instead of it.

**The prompt grows on turns that fire, by a stated and bounded amount in the ordinary
case and by a larger one in the pathological case.** §4 states both, including the case
it does not bound by ten. That the sound bound was written rather than the convenient
one is deliberate; #1908's next milestone should read it before deciding whether a
line cap is owed.

**A test-fidelity rule now exists and is citable.** §7 is stated generally because the
failure it names is not specific to this render rule: a fixture unlike production
passes every check this project runs. It costs future lanes one comparison — is the
fixture shaped like what the capture site writes — and it is the comparison that would
have caught this before the hub was deployed.

**What would trigger revisiting this.** A measured elision share (ADR-0222 §5's pair,
now over both populations) that says 640 is wrong; a re-probe on #1908 that fires,
services, renders and still fails, which would put the remaining loss at the trigger or
at the observer's act-record accuracy rather than here; a decision to admit a third
`ReadKind`, which would owe its own answer to the question §2 above answers for the
sighted query; and a hop whose evidence fan-out turns out in practice to be nothing like
the *"one or two beliefs citing one to three episodes each"* the replay measured, which
would make §4's unbounded case real rather than theoretical.

## Alternatives considered

**Render the whole fourth group, both kinds alike.** Simpler to state and simpler to
carry — a count would do where §3 asks for a set. Refused because ADR-0222 §2's first
reason reaches a `SIGHTED_QUERY` record in its own words: ADR-0226 §2 calls that ask *"a
relevance selection"* performed through `assemble_by_band` with *"the band precedence,
per-band composition and kind selection of the retrieval stage's own read unchanged"*,
so its records were selected against a key their replies are not in, exactly as the
retrieved group's were. Rendering them would spend prompt on prose no part of the
selection read, on a population whose size is decided by how many slots the hop left.

**Render only the hop's records that entered the fourth group, and let a deduplicated
one stay phrase-only.** The positional reading, and the one a count-based carrier would
give for free. Refused in §1: the exact record a belief cites would render phrase-only
whenever the episodic supplement had already picked it up, which reproduces #1944's
failure on a turn that looks like a success and which no live probe would distinguish.

**Reinterpret ADR-0222 §2 as not reaching the fourth group at all, and write the rule
with no supersession.** Textually available — §2 names *"the **retrieved** group"*, and
ADR-0226 §7 makes the serviced records a **fourth** group distinct from it. Refused
because §2 says nothing about the episodic supplement either and plainly governs it, so
the clause means the assembler's non-tail population; because the implementation renders
it that way; and because #1944 read it that way. Where a clause's reach is genuinely
ambiguous the conservative direction is to supersede and show the working, which costs
one `Status` line and leaves no reader to rediscover the question.

**Widen ADR-0222 §1's population instead of stating a new rule.** Fewer words, and it
would have made §5's counting rule and §8's tests apply with no second scope. Refused
because §1's clause is stated over *"the **conversation-tail** group — the leading
episodic run `_split_conversation_tail` returns"*, and a hop-reached record is not in
that run and must not be rendered as though it were. Widening the text would have made
the tail's definition do work it does not do, and the group encoding
`_split_conversation_tail` expresses is the one thing ADR-0158 §4 and ADR-0226 §7 both
lean on.

**Infer the hop's records at the render site from `Provenance.evidence`.** No carrier,
no seam change, no widening of anything. Refused in §3: it marks every record any
supplied belief cites, on every turn, whether or not the planner named the belief and
whether or not a hop ran or succeeded — a superset that renders replies on turns
ADR-0226 §5 requires to be byte-identical to a turn that never fired.

**Carry the fact on the record, or on a new `core` field of `TurnResult`.** The most
direct carrier, and the one a reader expects. Refused because it is a `core/types.py`
change under golden rule 5 for a fact that never leaves one subsystem, because copying
or mutating a `MemoryRecord` to mark it would break ADR-0226 §7's *"constructed
**once**"* and would make the marked record unequal to the stored one, and because
`LearningLoop` and `ComposingStage` are both concrete classes in `orchestration` with a
single seam and a single call site between them. The cheapest true statement of the
fact is the one that stays inside the subsystem that owns it.

**Put a second elision-share pair on the statement, one per population.** Refused in §5:
it buys a comparison no decision turns on, at the cost of ADR-0141 §6's one-statement
discipline that ADR-0222 §5 adopts by name.

**Cap the number of reply lines a serviced group may render.** Attractive because §4
cannot bound the count by ten in full generality. Refused because ADR-0222 §4's third
clause forbids this ADR to introduce another budget, because the bound that matters —
what a belief actually cites — is measured at *"one or two beliefs citing one to three
episodes each"*, and because a cap chosen with no measurement behind it is the failure
ADR-0222 §4 declines to commit for the ceiling itself. It is named as a follow-up
instead.

**Fix the test by driving the renderer harder, and write no fidelity rule.** Refused
because the renderer was already driven: the finding is about the fixture's shape, and a
repair that does not name the shape leaves the next render rule exposed to the same
green.
