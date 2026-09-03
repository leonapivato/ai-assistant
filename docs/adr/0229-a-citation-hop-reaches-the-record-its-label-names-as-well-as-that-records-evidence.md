# 229. A citation hop reaches the record its label names, as well as that record's evidence

- Status: Proposed
- Date: 2026-09-03
- **Amends** [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
  — **§2's servicing clause for the `CITATION_HOP` kind, and §3's "follows only"
  clause, in one respect each: the hop's *reach* is the record a label names as well
  as that record's evidence.** §2 reads *"The loop resolves each label **in code** to
  the record it labelled, reads that record's own `Provenance.evidence`, and resolves
  those identifiers through `MemoryStore.get_many`"*, and §3 reads *"A `CITATION_HOP`
  follows **only** the labelled record's own stored `Provenance.evidence`."* A reader
  holding only ADR-0226 builds a hop whose result excludes the record the planner
  pointed at — which is what the tree does and what #1960 measures — so ADR-0082 §1's
  test is met on both clauses and the record is owed. **What §3 forbids is untouched:**
  the hop still follows exactly one level, still follows no evidence of a record it
  reached, and §3's namer rule, its no-identifier rule, its ordinal scheme and its
  resolves-to-nothing rule bind entire and are load-bearing here. §6's budget, §7's
  fourth group and deduplication, and §9's audit are **not** amended and do not move,
  because §2 below puts the named record in ADR-0227 §3's carrier and in nothing else.
  ADR-0226's `Status` line carries the leading `Partially superseded by` token, so
  under ADR-0082 §2 no qualifier is written on it and the record stands whole in the
  appended dated note.
- **Amends** [ADR-0227](0227-a-record-the-citation-hop-reached-renders-its-reply-and-the-test-that-says-so-runs-the-real-renderer.md)
  — **§1's statement of the population, and §3's statement of the carrier's contents
  and order.** §1's second sentence restricts to *"A record the hop resolved **through
  a named label's `Provenance.evidence`**"*, which is narrower than its own first
  sentence — *"'Reached by the citation hop' is the whole of the test"* — and a reader
  holding only ADR-0227, handed a carrier containing a named record, could read the
  second sentence as excluding it. §3 says the carrier holds *"the distinct records
  the hop resolved … in ADR-0226 §6's order"*, and §6 fixes an order over the records
  the servicer **appends**, which does not place a record the servicer appends
  nothing for. §3 below places it. Both are ADR-0082 §1's test met, and neither is a
  supersession: **§1's field test, its tail exclusion, its caller-emitted-line rule
  and its silence at `planning/planner.py` and `learning/observer.py` all bind
  unchanged; so do §3's supplied-never-inferred rule, its division of labour between
  servicer and render site, its empty-set cases, its namer rule and its no-`core`,
  no-Protocol, no-`PROTOCOL_VERSION` clause.** §2, §4, §5, §6, §7, §8 and §9 of
  ADR-0227 are untouched.
- **No other ADR is superseded or amended.** ADR-0222 §§1 and 2 are not reached — this
  ADR changes which records are in ADR-0227 §1's population and states no render rule
  of its own. ADR-0228's one-level-per-servicing clause, its second-level-across-
  iterations clause and its item 14 all bind as ratified, and §1 below is written to
  ADR-0228's reading of the carrier rather than against it. ADR-0074 §4, ADR-0221 §§1
  and 2, ADR-0208 §1's keyed-load clause and golden rule 1 bind as ratified; §8 shows
  the working for each one a reader would expect to have moved.
- **This ADR changes no code, adds no `core` type, adds no field to one, adds no
  Protocol and no member to one, and moves no `PROTOCOL_VERSION`.** §7 states what
  the implementing lane owes; nothing implements against it until it has merged
  ([ADR-0015](0015-simplify-the-agent-workflow.md) §5, golden rule 5). Refs #1960,
  #1945, #1908.

## Context

### What was measured

Milestone 27's exit clause 1 asks that *"a cross-conversation reply-vocabulary
question ('which lender did you recommend?') answers through the hop"* (#1908). On
the deploy carrying ADR-0227's implementation, #1960 records two probes of exactly
that shape — a novel recommendation and a board game, each named only in a reply the
user was shown in an earlier conversation, each asked again in a fresh conversation.
Both fired, both were serviced, and both answered *"I wasn't able to pull up that
original reply."* The audit line reads
`trigger=fired kinds=('sighted_query','citation_hop') servicing=serviced returned=10 new=0 deduplicated=10`,
and the plan's own rationale says what it wanted: *"The specific novel named is in the
wording of the prior recommendation reply, not in the summaries shown, so I request
that original exchange."*

The planner asked for the right thing, the loop serviced the request, and the record
carrying the answer was never rendered.

### What the tree does, verified against `origin/main`

`orchestration/reads.py::_hop_records` resolves each label to a record of the supply,
collects that record's `Provenance.evidence`, resolves the identifiers through
`MemoryStore.get_many`, and returns `cited` — built from
`resolved[cite] for cite in record.provenance.evidence`. **The labelled record itself
is in no return value.** It is fetched: the function batches `record.id` into the same
`get_many` call as its evidence, deliberately, so that liveness and evidence are
judged against one snapshot. It is then used for one thing — deciding whether the
label resolved to nothing — and dropped.

`service_read_request` computes ADR-0227 §3's carrier from that same sequence, keeping
the ids of `resolved_by_hop` that `union.held` holds. So a record the hop did not
return cannot be in the carrier; a record not in the carrier reaches no
`_hop_reply_lines`; and a record `_hop_reply_lines` does not admit renders no reply.
The chain is intact and every link works as ratified. What is wrong is the first one.

### Why it fails on an episode and not on a belief

ADR-0074 §4 decides that a captured episode cites nothing, and gives the reason in one
sentence: *"An episode is the terminal citation: the thing other records cite.
Requiring it to cite something would demand a regress or a self-reference."*

So the hop, as ADR-0226 §2 describes it, is a mechanism that traverses **exactly one
edge** toward the terminal citation. Where the planner names a belief distilled from
the exchange, the episode is one edge away and everything works. Where the planner
names **the episode**, the destination is zero edges away, the traversal of one edge
lands nowhere, and the single record holding the answer is the one that was pointed at.

An episode is in front of the planner on most turns — ADR-0224 puts thirty of them in
the episodic supplement — and it renders there under ADR-0222 §2 as a bullet with a
`how it turned out:` phrase and no reply. That is precisely the shape
`planning/planner.py`'s act-record guidance tells the planner to point at: *"a memory
that says what this assistant did or said in an earlier conversation … is a summary of
that exchange, written afterwards … This is what `labels` is for: name that memory's
label, and what comes back is the original exchange it was drawn from, in the wording
it actually had."*

**The prompt already promises what this ADR delivers.** When the record named is a
summary, *"the original exchange it was drawn from"* is one edge away. When the record
named **is** the exchange, it is the record itself — and the promise is broken by a
mechanism that can only travel outward.

### Why this is a decision and not a repair

#1844's replay saw a real planner name an episode on 30% of hop firings, and ADR-0226
§2 quotes that figure as a **failure mode**: *"its failure mode is that the planner
names an episode (30%) or nothing (32%) — the 'which belief do I open' problem is the
same unsolved trigger problem in a different costume."*

That reading was available when the hop was written and is no longer. It was written
before ADR-0221 gave an episode its `outcome`, before ADR-0222 §1 rendered a reply at
all, and before ADR-0227 made *being reached by the hop* the thing that unlocks a
reply line. Under those three decisions, naming the episode is not a planner failing to
find the right belief; it is the planner taking the **shortest honest path** to the one
thing it cannot see. Nearly a third of the replay's "failures" were the emission this
system now wants.

So the question this ADR settles is not "how do we make the probe pass" but **what a
label means**: whether a label is an instruction to *depart from* a record, or the
name of a **destination**. ADR-0226 answered the first, for a reason that has expired.
This ADR answers the second.

### What is not in dispute

The trigger fired, the servicing completed, the carrier reached the renderer and the
render rules are right. Nothing in ADR-0227 is being reopened, and nothing about the
prompt is being changed: #1929's separate trigger question and #1945's Lane C own that
ground, and this decision reaches neither.

## Decision

### 1. A label names a destination, and the hop reaches it

> **Normative.** A `CITATION_HOP`'s **reach** is, for each of its labels, the record
> that label resolves to **together with** that record's own stored
> `Provenance.evidence`. A record a label resolved to is a record *"this turn's
> citation hop reached"* in ADR-0227 §1's sense.

> **Normative.** Every label that resolves to a live record reaches that record.
> **No class, kind or field test is applied at the servicer** — not on
> `MemoryKind`, not on `disposition`, not on `outcome`, not on whether
> `Provenance.evidence` is empty. What a reached record *renders* is ADR-0227 §1's
> question, decided at the render site over `disposition` and `outcome`, unchanged.

> **Normative.** The reach is stated over **the turn** and not over one servicing.
> Where a turn services two emissions ([ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md)),
> each servicing's named records join ADR-0227 §3's carrier and the second replaces
> nothing — which is ADR-0228's own rule for the carrier, applied to the population
> this section adds: *"ADR-0227 §3's hop-set carrier **accumulates across both
> servicings** rather than the second replacing the first."*

> **Normative.** **Reaching the named record is zero levels of traversal, not two.**
> ADR-0226 §3's prohibition — a hop *"does not follow the evidence of a record reached
> by that hop, and no lane adds a second level"* — and ADR-0228's restatement of it
> within a servicing bind entire and are not weakened: no implementation reads
> `Provenance.evidence` for any record but the ones the labels named.

**The narrow rule is the honest one, and the field test at the servicer is the
tempting mistake.** The case that motivates this ADR is an episode carrying an
`outcome` beside a `disposition`, and a clause admitting only that shape would be
observably identical — a belief has no `disposition` field at all, so ADR-0227 §1
renders nothing under its bullet, and `_hop_reply_lines` skips a record its
`_reply_lines` finds ineligible *before* counting it against §4's cap, so a
non-episode in the carrier costs nothing anywhere. What such a clause would buy is a
second implementation of ADR-0227 §1's field test, at the one site ADR-0227 §3 divides
away from it: *"each component states what it alone knows, and neither holds a second
implementation of the other's rule."* Two copies of a render rule are two things to
keep in step, and the servicer's copy would be the one no render test exercises.

**And the general statement is the one that is true.** The hop reached the record: the
planner named it, the loop resolved it, `get_many` returned it. That is a fact about
how the record was fetched, which is exactly what ADR-0227 §1 says its test is a fact
about — *"The test is the **reason** the record is there, not the position it
occupies."* Narrowing it to episodes would make the carrier's contents depend on a
field, and a later decision widening what a reached record renders would then have to
find and widen this clause too.

### 2. Reach is not supply: no group, no budget, no count

> **Normative.** A record reached because a label named it enters **no group of the
> turn's supply**. It is not appended to ADR-0226 §7's fourth group, it is not offered
> to that section's deduplicated union as a candidate, and it consumes **no slot** of
> ADR-0226 §6's budget of ten. ADR-0226 §6's budget, its hop-first precedence, its
> two-label cap and its second-budget rule are untouched.

> **Normative.** **ADR-0226 §9's audit is unchanged in every field's meaning and in
> every field's value, and this ADR adds no field to it.** *"How many records the
> servicing returned"*, how many were new after deduplication and how many the
> deduplication removed are counted over what the servicing **fetched into the
> union** — the named records' evidence, and the sighted query's records — and a
> record named by a label is counted in none of the three. `labels_unresolved`,
> the truncation fields and the two failure fields are untouched.

**There is nothing to admit, and that is a fact about ADR-0226 §3 rather than a
concession.** The label space *is* the supply: §3 rules that *"the loop resolves a
label by parsing *n* and indexing **the very sequence it passed on this call**"*. So a
record a label resolves to is, by construction, already in the pre-servicing supply —
it is in `_Union`'s seen set before the hop runs, it can never be new, and it can never
spend a slot. This section states the consequence rather than granting an exemption.

**Counting it anyway would corrupt the one instrument the milestone has.** Feeding a
named record through the union would add one to `returned` and one to `deduplicated`
for every label that resolved, on every serviced hop, deterministically. ADR-0226 §8
defines the novelty rate as saying *"a fired read returned records the supply did not
already hold"*; a hop that fetched three genuinely new evidence records would report
3 of 5 instead of 3 of 3, and the depression would be a constant that tells a reader
nothing they could not compute from the labels alone. The audit would be measuring the
mechanism's book-keeping instead of the read.

**So the two questions separate cleanly, and each is answered where it belongs.** What
the turn *holds* is ADR-0226's question, and this ADR moves none of it: the same
records, the same groups, the same order, the same ten slots, the same counts. What the
turn's citation hop *reached* is ADR-0227 §3's question, and that is the one thing this
ADR widens.

### 3. The named record precedes its own evidence

> **Normative.** Within one servicing, ADR-0227 §3's carrier orders each named record
> **immediately before that record's own evidence**, with labels in the order the ask
> names them and each named record's evidence in the order that record stores it.
> This extends ADR-0226 §6's order to the one element that order had nothing to say
> about, and changes the relative order of no element §6 already placed.

> **Normative.** ADR-0227 §4's deduplication over the carrier is unchanged: the cap is
> taken over **distinct** identifiers, deduplicated before it is applied, with the
> **first** occurrence keeping the place. A record that is both named by one label and
> cited by another appears once, at the earlier of the two positions.

**The order has to be fixed because the cap is taken over it.** ADR-0227 §4 renders the
first ten admitted records in the carrier's order and the rest not at all, so two
conforming implementations placing the named record differently would render different
prompts from one supply and one request. ADR-0226 §6 fixes its order for exactly this
reason — *"given one request, one pre-servicing supply and one set of candidates, two
conforming implementations append the same records in the same order"* — and this is
that clause carried one element further.

**Before its evidence, because it is the record the planner pointed at.** Where a
label names a belief citing several episodes, the cap could otherwise starve the very
record the label named behind the evidence it cites; where a label names an episode,
the record and its (empty) evidence are the same thing either way. Putting the
destination first makes the named record the last thing a cap can cut rather than the
first, which is the ordering ADR-0226 §6 already chose between the two kinds, for the
same reason: the capped, pointed-at read goes ahead of the open-ended one.

### 4. Three cases that do not move

> **Normative.** **A label that resolves to nothing reaches nothing.** ADR-0226 §3's
> three ways of resolving to nothing are unchanged and are counted in
> `labels_unresolved` exactly as they are today: a string that does not match the
> form, an ordinal outside the shown range, and a record `MemoryStore.get_many` does
> not return. A label of the third kind puts **nothing** in the carrier — not the
> named record, not any evidence — even though the turn's supply still holds that
> record and still renders its bullet.

> **Normative.** **ADR-0227 §1's conversation-tail exclusion binds a named record
> exactly as it binds an evidence-reached one.** A label naming a tail record adds no
> second line under its bullet, consumes no position of ADR-0227 §4's cap, and
> contributes **one** record to §5's pair. ADR-0222 §1 stays the single rule for the
> tail, and `_split_conversation_tail` at the render site stays the single authority
> on which group a record is in.

> **Normative.** **ADR-0227 §4's cap of ten is unchanged and is not widened.** It is
> taken at the render site, over the carrier's order, after ADR-0227 §1's tail
> exclusion, and a carrier entry ADR-0227 §1 does not admit consumes no position of
> it. This ADR states no second cap, no second constant and no second render rule.

**The liveness case is the one worth arguing, because the tempting answer is the wrong
one.** The turn *has* the record — it is in the supply, the planner saw it, its bullet
will be rendered — so honouring the label from the supply's copy is available and would
make the mechanism marginally more robust to a delete racing a turn. It is refused for
two reasons. It would change what `labels_unresolved` counts, which is an audit field
ratified in ADR-0226 §9 and one this ADR has just said it does not touch. And it would
render, into a model prompt, the reply of a record the store no longer holds — reading
a forgotten exchange back to the user by a route no forgetting mechanism is watching.
A label whose record has been deleted between assembly and servicing resolving to
nothing is the safe answer as well as the ratified one.

### 5. Why the planner's emission was right and the mechanism was wrong

ADR-0226 §2 built the hop around a belief because #1844 measured naming an episode as
a failure, and the finding was correctly read at the time. Three later decisions
changed what the measurement means.

**ADR-0221 gave the episode an `outcome`.** Before it, the reply was *"stored nowhere
at all"*; naming an episode reached a record that did not carry the answer either, so
the replay's 30% really was wasted. Now it carries the reply whole.

**ADR-0222 §1 made a reply renderable, and §2 made it renderable only under a
rule.** An episode in the supplement renders its disposition phrase and not its words,
which is exactly the shape `planning/planner.py`'s guidance describes as *"a summary
… written afterwards"* and steers the planner to point at.

**ADR-0227 made being reached by the hop the thing that unlocks the reply line.** With
that, "reached by the hop" stopped being a statement about which records were *added*
to the supply and became a statement about which records the turn may *quote*. Under a
reach that can only travel one edge, a planner that points straight at the exchange
gets less than one that points at a summary of it — the shortest path is the only one
that fails.

**So the emission is right and this is not a prompt fix.** #1960 states it plainly:
*"the planner pointing at the exchange directly is the *right* emission; the mechanism
should honour it."* A change to `planning/planner.py` steering the planner away from
episodes would be teaching the model to take a longer route to the same record because
the shorter one is unimplemented, and it would fail outright whenever no belief cites
the exchange — which is every recent exchange, since a belief is distilled from an
episode only after an observation pass has run. #1929's separate finding is that the
trigger over-trusts a summary; the answer to both is a system in which pointing at the
exchange works.

### 6. The tests this decision owes

> **Normative.** The implementing lane owes a test for each of the following. Each is
> a test over behaviour rather than over a call count, and each that asserts a fact
> about what a model was shown is subject to **ADR-0227 §7's fidelity rule** entire:
> the production renderer, over records shaped as the production capture site writes
> them — the reply's distinctive word in `outcome`, beside a `disposition`, and absent
> from `content`.

1. **#1960's probe, as a fixture.** An episode in the **episodic supplement** whose
   `outcome` carries a word the user never used and whose `content` does not; a
   planner that names **that episode's own label**; and an assertion that the word is
   in the prompt `orchestration/composing.py` assembles, through the real renderer.
   This is the test that fails on `origin/main` and is the reason for the ADR.
2. **A belief label still hops to its evidence, and the belief itself renders as it
   does today.** A labelled belief citing an episode: the episode's reply renders, the
   belief grows no line, and the assembled prompt is otherwise byte-identical.
3. **A named record spends no budget and moves no count.** A hop naming one record and
   reaching *n* new evidence records reports `returned`, `new` and `deduplicated`
   identically to what the same servicing reports today, and the fourth group holds
   the same records in the same order.
4. **A label naming a conversation-tail record renders exactly one reply line**, under
   ADR-0222 §1, and contributes one record to ADR-0227 §5's pair.
5. **A label whose record `get_many` does not return reaches nothing**, is counted in
   `labels_unresolved`, and renders no reply line although the supply still holds the
   record.
6. **Order.** A hop over two labels places each named record immediately before its own
   evidence, asserted over the carrier the servicer produced.

### 7. What the implementing lane owes

> **Normative.** One lane, briefed from this ADR's merged text, touching
> `src/ai_assistant/orchestration/reads.py` and `tests/orchestration/**` and nothing
> else. It changes **no** file under `src/ai_assistant/core/`, adds no Protocol and no
> member to one, moves no `PROTOCOL_VERSION`, and changes no file under
> `src/ai_assistant/planning/` or `src/ai_assistant/interfaces/`.

> **Normative.** The change is confined to what `_hop_records` returns and to how
> `service_read_request` builds ADR-0227 §3's carrier from it. **No second store call
> is added**: the named records' identifiers already ride in the one `get_many`
> `_hop_records` issues, for the liveness check §4 above leaves unchanged, so the
> records this ADR admits are already in that call's result.

> **Normative.** The lane owes **both** required lenses, adversarial and architecture:
> the change is at the servicer seam whose division of labour ADR-0227 §3 fixes.

`orchestration/composing.py` is not in the lane's fence and needs no change: it already
takes the carrier as data, already looks each identifier up in the non-tail group, and
already skips a record its render rules do not admit without spending a cap position.
That the fix reaches one function is the measure of how much of ADR-0227 was right.

### 8. Scope, and what this records against earlier ADRs

**This ADR amends two ratified ADRs, in four scopes, and supersedes none.** The header
carries the records; this section shows ADR-0082 §1's working, and shows it for the
clauses a reader would most expect to have moved and which did not.

**ADR-0226 §2 and §3 are amended, and each fails ADR-0070 §1's test on its own words.**
§2's servicing clause and §3's *"follows **only** … `Provenance.evidence`"* both
describe a hop whose result is the evidence and nothing else. A reader holding only
ADR-0226 builds exactly `_hop_records` as it stands, and ADR-0227 §3's carrier is then
missing the record the planner named. That reader *"would now act differently"*, which
is the test. Neither is a supersession, because nothing either clause forbids becomes
permitted: §3's prohibition is on a **second level** of evidence, and this ADR reads no
`Provenance.evidence` the labels did not name.

**ADR-0226 §6, §7 and §9 are not amended, and §2 above is why.** §6 fixes a budget over
what the servicing admits; §7 fixes the fourth group and the deduplicated union; §9
fixes counts over what the servicing returned into that union. A named record enters
none of them, so no sentence of any of the three becomes false or over-wide, and a
reader acting on them acts identically before and after. That is ADR-0070 §1's test
coming out the other way, and under ADR-0082 §1 there is nothing to record: *"Absent a
clause that fails §1's test, there is nothing to record."*

**ADR-0227 §1 and §3 are amended, in one respect each.** §1's first sentence is the
rule and is right — *"'Reached by the citation hop' is the whole of the test"* — but
its second sentence states the population as records *"resolved through a named label's
`Provenance.evidence`"*, which is over-narrow the moment a named record can be in the
carrier; a reader could apply it to exclude one. §3's order clause points at ADR-0226
§6, which places every element it knows about and does not place this one; §3 above
places it, and until it did, two implementations could order the carrier differently.

**ADR-0227 §2, §4, §5, §6, §7, §8 and §9 are not amended.** §2's rule that a
query-serviced record stays phrase-only is untouched and this ADR admits no record
through the query. §4's cap, its ceiling, its deduplication and its silence about
excluded records bind unchanged over a carrier that now has more in it — a cap is a
statement about a count, not about a population's provenance. §5's pair still counts
records once each. §7's fidelity rule is applied by §6 above rather than changed. §9's
statement of what ADR-0227's own lane owed is spent.

**ADR-0222 is not reached at all.** This ADR states no render rule: it changes which
records are in ADR-0227 §1's population, and ADR-0227 already carries the supersession
of ADR-0222 §2 that the population needs. A reader holding ADR-0222 acts identically.

**ADR-0228 is not amended and is honoured in both directions.** Its
one-level-per-servicing clause is untouched, because a named record is zero levels
rather than two. Its second-level-across-iterations clause is untouched, because it
governs a record's *evidence* being reachable on a later call and this ADR reaches no
evidence a label did not name. And its item 14 — *"ADR-0227 §3's hop-set carrier
accumulates across both servicings"* — is the rule §1 above adopts for the population
it adds, rather than a rule it competes with.

**ADR-0074 §4 is not amended and is the ground.** *"An episode is the terminal
citation: the thing other records cite"* is the decision that makes an episode's
evidence empty, and this ADR takes it as given rather than moving it: the answer to a
terminal citation being unreachable by traversal is to reach it by name, not to give it
something to cite.

**ADR-0208 §1's keyed-load clause is not amended, and the reason ADR-0226 §2 gave for
it applies harder here.** A hop is *"records the turn already names, fetched by
identifier"*. A record the label itself named is the purest possible case of that: no
relevance, no query, no ranking, and no second read site.

**Golden rule 1 is untouched.** Nothing crosses between `planning` and `orchestration`
beyond `memories` and the `ActionPlan`; no label, table or identifier is shared; and
ADR-0226 §3's ordinal scheme is read exactly as ratified.

**#1908's own text describes milestone 27's hop as** *"the planner names a belief it
can see; the loop follows that record's own `Provenance.evidence`"*. That is issue
text and not a ratified decision, so nothing is recorded against it; this ADR widens it
and #1960 is the finding that fired the widening.

## Consequences

**What becomes easier.** The exit clause milestone 27 was held on has a mechanism
behind it: a question about the wording of an earlier reply is answerable whether the
planner points at the exchange or at a belief distilled from it. Nearly a third of the
hop emissions #1844's replay recorded — the ones ADR-0226 §2 counted as failures — stop
being wasted. And the shortest path stops being the one that fails, which matters for
the case no belief covers: an exchange from this week that no observation pass has yet
distilled into anything is reachable **only** by naming it.

**What becomes harder, and what it costs.** A named record's reply now reaches a model
prompt, so a hop naming two episodes with long replies spends up to two more of
ADR-0227 §4's ten reply lines and up to 1,472 more characters of prompt than the same
hop spent before. That is ADR-0227 §4's ceiling doing its job rather than a new cost,
and the ten-line cap is unchanged. The audit's novelty rate becomes a slightly weaker
proxy for "was this read worth it", because a firing whose whole value is a named
record's reply reports `new=0` — the read genuinely added no record, and what it added
was permission to quote one. §2 above prefers that to a corrupted numerator; a reader
of ADR-0226 §8's rate should know the case exists.

**What would trigger revisiting this.** A measurement showing that a hop naming a
record whose reply is long crowds a prompt in a way ADR-0227 §4's cap does not catch.
A decision making some third kind of record renderable on reach, which would want §1's
class-free rule re-read rather than re-narrowed. Or ADR-0225 §12's archive-fetch kind
being fired, at which point *"the original exchange in the wording it actually had"* has
a second possible source and this ADR's answer becomes one of two.

## Alternatives considered

**Fix the prompt instead.** Steer the planner away from naming episodes and toward the
belief that cites them. Rejected: it teaches a longer route to the same record because
the shorter one is unimplemented, it fails entirely for an exchange no belief cites yet,
and #1960's own reading is that the emission is right. It would also make the system's
behaviour depend on a prompt paragraph rather than on a mechanism, which is the failure
#1929 is separately about.

**Admit the named record to the fourth group.** Return it from `_hop_records` into the
union like any other candidate. Rejected in §2: it is in the supply by construction, so
it can only ever be deduplicated out, and the sole effect is a deterministic constant
added to `returned` and `deduplicated` on every serviced hop, depressing ADR-0226 §8's
novelty rate for no informational gain. It would also, on a strict reading, need
ADR-0226 §9 amended to keep its fields truthful — a heavier record for a worse result.

**Admit only episodes**, or only records whose `Provenance.evidence` is empty, as
#1960's own sketch suggests. Rejected in §1: observably identical today, and it buys a
second copy of ADR-0227 §1's field test at the site ADR-0227 §3 divides away from it.
The empty-evidence variant is worse still — it makes reachability depend on whether a
record happens to cite anything, so a future capture site that gave an episode a
citation would silently switch the mechanism off.

**Honour a label from the supply's copy when `get_many` no longer returns the record.**
Rejected in §4: it changes what `labels_unresolved` counts, and it renders a deleted
exchange's reply into a prompt by a route no forgetting mechanism watches.

**Follow a second level of evidence** so that naming a belief reaches the belief's
episodes' own citations. Not considered here at all: ADR-0226 §3 forbids it, ADR-0228
decides where the second level lives, and this ADR reaches no evidence a label did not
name.
