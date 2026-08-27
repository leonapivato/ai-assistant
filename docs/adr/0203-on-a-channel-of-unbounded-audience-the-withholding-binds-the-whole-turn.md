# 203. On a channel of unbounded audience the withholding binds the whole turn, and nothing downstream inherits what it removed

- Status: Proposed
- Date: 2026-08-28
- **Partially supersedes:**
  [ADR-0199](0199-the-audience-of-the-output-channel-decides-what-may-be-said-and-a-withheld-class-is-deflected-rather-than-redacted.md)
  — §5's second clause, that "the `TurnResult` the turn produced is unchanged",
  **scoped to exactly one case**: an operation whose output channel's audience is
  unbounded. There the withholding binds the supply the whole turn runs over, so
  the turn is *produced* over the subtracted supply rather than produced over
  everything and narrowed for the composing stage. The rest of that clause — that
  the stage gains no `ContextProvider`, no `MemoryStore`, no second context
  assembly and no second retrieval, and that its context and memories reach it
  from the turn and from nowhere else — is kept and restated as §2 below, and
  every other clause of §5 is untouched, the deflection's shape most of all.
- **Partially supersedes:**
  [ADR-0200](0200-a-spoken-turn-is-one-operation-on-the-promoted-surface-and-speech-is-two-seams-beside-the-model-provider.md)
  — §4's second-difference clause, that everything other than `reply` "is what
  that transcript would have produced either way" and that no lane reads it "as
  licence for a second difference". The turn such an operation returns now also
  differs — it carries the context, the memories and the plan of the turn that
  actually ran on that channel — and so does **the step that plan drives**, which
  is not independent of it. §3 below states the whole of that difference, names
  the step as part of it, and bounds it: everything the plan does not determine is
  unchanged. Everything else §4 decides — `SpokenTurn`'s four members, the
  `heard`/`outcome` pairing, the blank-transcript shape, the byte-for-byte
  transcript, and every clause of the degradation ladder — is untouched. §9
  classifies both records and the ADRs against which none is owed.
- **This is not a contract change.** It adds no `core` name, no Protocol member,
  no `Settings` field and no member of the promoted surface; it moves no method
  signature and no promoted method's contract. What moves is where one filter
  inside `ai_assistant.orchestration` is applied, and two sentences of two ADRs.
  It is still decided in its own PR and ratified before anything implements
  against it (ADR-0015 §5), and it owes the adversarial lens alone, on
  `CONTRIBUTING.md` → "Stop when the required reviews are green".

## Context

### Where this comes from

`track:voice` milestone 19 (#1318) is push-to-talk in the browser, and ADR-0199
is the disclosure ruling it ships under: the audience of the output channel
decides what may be said, a class is decided from recorded origin, three classes
are withheld from a channel whose audience is unbounded, and a withheld class is
**deflected** rather than redacted. ADR-0200 decides the mechanism — one
operation, `converse_spoken`, whose channel it declares unbounded outright — and
`orchestration/disclosure.py` implements the ruling at the site ADR-0200 §7 fixes.

The milestone-19 QA run (#1691) drove the finished milestone end to end against a
live hub, with real synthesized speech in and the answers transcribed back, and
filed two findings it deliberately did not repair:

- **#1692** (`backlog:blocker`) — a withheld class is read aloud **one turn
  later**, through the episode the deflecting turn captured.
- **#1693** (`backlog:major`) — `converse_spoken` returns the withheld records
  verbatim on `outcome.turn.memories`, and two ratified clauses point opposite
  ways about whether that is permitted.

Both name decisions no lane may take, and both hold milestone 19's exit criterion
— *"a content class ruled unspeakable is deflected, not read aloud"* — open. This
ADR takes them.

### The chain, read against the tree rather than against the issue

Six steps, each of them checked in this repository rather than accepted from the
report:

1. `Engine.converse_spoken` runs the ordinary pipeline: `_run_turn` with
   `compose=self._composed_spoken` and `compose_routed=self._composed_routed_spoken`.
2. `_run_turn` calls `LearningLoop.respond`, and **planning happens inside it**,
   over everything the turn assembled — `plan = await self._planner.plan(goal,
   context=context, memories=memories)`, with `memories` the conversation's recent
   turns, then the relevance-retrieved beliefs, then the episodic supplement.
3. Only afterwards does `Engine._composed_spoken` call
   `disclosure.supply_for_unbounded_audience`, which builds a narrowed **copy** for
   the composing stage and leaves the turn as the turn made it. Its own docstring
   says so: the `TurnResult` is "**Not modified** — ADR-0199 §5 keeps it exactly as
   the turn made it, and the outcome carries that one back."
4. `Engine._capture` renders the episode's content with `_exchange_of`, which is
   two lines: `f"The user asked: {turn.goal.statement}"` and, where there is one,
   `f"The assistant's plan: {turn.plan.rationale}"`. The rationale is a model
   completion authored over the **unnarrowed** supply.
5. `ConversationLifecycle._episode` stamps it `Provenance(source=MemorySource.OBSERVED,
   …)` and leaves `about_person` unset. ADR-0199 §3's third clause places exactly
   that shape — `OBSERVED`, `about_person` not stated — as **speakable** on a
   channel of unbounded audience, and `disclosure._speakable` keeps it under every
   configuration, correctly.
6. The next spoken turn retrieves it (ADR-0074 §5, ADR-0158 §5) and it arrives at
   the composing stage as ordinary speakable supply. #1691 heard the result:
   *"You also asked me what I know about Alice, which we discussed twice."*

Each component is faithful to its own clause, which is what makes this a hole in
the corpus rather than a defect in a lane. ADR-0199 §2 decides a class from
recorded origin and forbids deciding one by inspecting content; an episode's
recorded origin genuinely **is** `OBSERVED` with `about_person` unstated; and
nothing anywhere records that this particular episode's warrant traces to content
that was withheld. #1693 is the same root cause one stage earlier and visible on
the first turn: `SpokenTurn.outcome.turn` is the turn as produced, so
`turn.memories` carries the withheld records and `turn.plan.rationale` carries a
model-written summary of them, on a surface ADR-0200 §3 declares unbounded.

### The two clauses that point opposite ways

> "The withholding subtracts from what the turn produced and adds nothing. The
> `TurnResult` the turn produced is unchanged" — ADR-0199 §5, second clause.

> "There is **one** answer on this call and `outcome.reply` is it… No larger
> answer is composed first, none is retained, and **nothing on this surface
> carries what was withheld**." — ADR-0200 §7, third clause.

An implementation cannot satisfy both, and #1693 says so and declines to
adjudicate. This ADR adjudicates: **§5's clause yields and §7's stands.** The
ground is that §7's sentence states the safety property #665 was opened about,
while §5's clause states a mechanism chosen to protect a *different* property —
that the composing stage performs no second retrieval and reaches for no
collaborator of its own. That property is preserved here in full (§2). What is
replaced is the part of the clause that fixes the turn's own supply, and it is
replaced because the QA run demonstrated where it leads.

### What is not in dispute, and is used as given

- **ADR-0199 §1's audience test**, and its fourth clause that one session may own
  channels of differing audience. The rendered page is bounded; the loudspeaker on
  the same device is not.
- **ADR-0199 §2's recorded-origin discipline**, in both directions: a class is
  decided from recorded origin, and content whose origin the supplying component
  did not record has no class and is withheld from an unbounded channel.
- **ADR-0199 §3's placements**, unchanged. No class becomes speakable or
  unspeakable here.
- **ADR-0199 §5's first clause** — withheld at supply, and never a filter over
  composed prose. This ADR moves the supply site earlier; it does not move the
  ruling to the output.
- **ADR-0200 §3's declaration** that `converse_spoken` is the output channel and
  its audience is unbounded, declared on the operation and computed nowhere.

### Why marking the episode is the wrong instrument, stated before the decision

The obvious repair for #1692 is to mark the episode a withholding turn produced,
so that a later turn can withhold it. Three things are wrong with it, and they are
worth stating first because it is the repair a reader arrives with.

It does not reach #1693 at all. The return value carries the withheld records on
the same call, before any episode exists; a mark on a record fixes nothing about a
value already handed to a caller.

It is `core` surface for a question that does not need it. A mark is an additive
field on `EpisodicMemory` or on `Provenance`, which is golden rule 5's own case —
its own ratified ADR, merged ahead of any lane. ADR-0074 §11 names that extension
route as open and unstarted for a *different* question (which device a turn came
from), and ADR-0200 §8 declines it in terms: "This ADR adds no field to
`EpisodicMemory`, no field to `Provenance`, and no record of the channel a turn
arrived on."

And it would still leak, because the episode is not the only thing the rationale
reaches. `Engine._run_turn` persists the plan through `PlanStore.save_plan` before
the step is driven, and the gateway renders `outcome.turn.plan.rationale` in its
"What happened" panel. A mark on the episode leaves both, and leaves the model
completion itself — a value with no recorded origin, which ADR-0199 §2's third
clause says has no class. Marking is a rule about one copy of a value the system
has already made several times.

The cheaper move is to not produce the value.

### An honest statement of what this ADR is not allowed to settle

It decides conduct: which supply a turn runs over on an operation whose channel
has an unbounded audience. It adds no Protocol and no member to one, no `core`
type and no field on one, no setting and no method on the promoted surface. It
does not revisit ADR-0199 §3's placements, does not decide person identity or
household disclosure (#691, ADR-0199 §7), does not decide the audio mechanism, and
does not decide whether a routed operation or a composed answer joins the captured
episode — which is ADR-0170 §9's and ADR-0197 §11's deferral to `track:memory`
(#1314), left exactly where it was found.

## Decision

We will make the withholding a property of **the supply the whole turn runs
over** on an operation whose output channel's audience is unbounded — so that no
stage of such a turn ever authors text over content ADR-0199 §3 withholds;
require that this cost one assembly and one retrieval and no backfill; rule that
what such an operation returns is the turn that actually ran; and record that
with those in place the turn's capture inherits nothing the withholding removed
and no episode is marked.

### 1. On an operation whose channel audience is unbounded, the withholding binds the supply the whole turn runs over

> **Normative.** On an operation whose output channel's audience is **unbounded**
> (ADR-0199 §1, declared as ADR-0200 §3 declares `converse_spoken`'s), the content
> ADR-0199 §3 withholds from that channel is subtracted from the turn's supply
> **before the turn plans**. It reaches no stage of that turn: not the planner,
> not the composing stage, and not whatever renders what either produced.

> **Normative.** The subtraction is ADR-0199 §3's placement applied to ADR-0199
> §2's recorded origin, unchanged. No class becomes speakable or unspeakable by
> this ADR, no second decision procedure is introduced, and nothing here is
> decided by reading `MemoryBase.content`, a facet's rendered text, a goal
> statement, a plan, a composed reply or any other span of content.

> **Normative.** The `TurnResult` such a turn produces is therefore produced over
> the subtracted supply: its `memories` are the records that were placed as
> speakable on that channel, its `context` carries only the facets §3 places, its
> `goal` is the owner's utterance as ADR-0074 §3 carries it, and its `plan` is
> what those inputs produced. No implementation
> composes, plans or renders anything over a wider supply and narrows afterwards,
> and no implementation edits a `TurnResult` after the turn has produced it.

> **Normative.** On such an operation the planner **may not act on** content
> ADR-0199 §3 withholds from that channel. No lane restores a withheld record to
> the planner's supply on the ground that the plan is better for it, that the step
> cannot otherwise be chosen, or that the answer will be deflected anyway.

> **Normative.** This binds an operation, not a session, a transport, a device or
> a caller. An operation whose channel audience is bounded — `converse` and
> `converse_streaming` as they stand — runs over its whole supply exactly as
> before, and ADR-0199 §5's second clause governs it unchanged. A caller cannot
> put an operation on either side of this line (ADR-0200 §3).

**The reason is that a model completion is unplaceable, and this system keeps
them.** ADR-0199 §2's third clause already rules that "content whose origin the
supplying component did not record has no class, and content with no class is
withheld from a channel whose audience is unbounded". A plan rationale is exactly
that: a completion produced from inputs of several classes, with nothing recorded
about which. The reason it nevertheless reached a loudspeaker is that
`Engine._capture` stores it inside an `EpisodicMemory`, and the episode's *own*
recorded origin is `OBSERVED` with `about_person` unstated, which §3 places as
speakable. Capture is not doing anything wrong — it stamps what it witnessed — but
the effect is that storing an unplaced value launders it into a placed one. A rule
that tried to catch this after the fact would have to decide a class by looking at
what a completion appears to be about, which is the one procedure §2 forbids
outright.

So the rule has to bind on the **input** side, which is where §2's discipline is
decidable: every record and every facet in the turn's supply carries a recorded
origin, and the subtraction is three field reads per record and an exact type
match per facet — `disclosure._speakable` and `disclosure._is_unplaced_facet` as
they already stand. Applied one stage earlier, they mean that no model on this
path ever sees a withheld record, so nothing downstream of a model can have
derived from one.

**The fourth clause is a refusal, so it is marked** (ADR-0089 §1). "The planner
should still be allowed to *use* the belief, since the answer will deflect anyway"
is the reading a later lane will most want, and it is the one this decision exists
to close: what the planner produces is retained in the `PlanStore`, captured into
an episode, retrieved into a later turn's prompt and rendered on a surface. There
is no such thing as a model call on this path whose output is used once.

**What it costs, stated rather than minimised.** On a channel of unbounded
audience the planner cannot plan over a belief about another person, over a
source no ADR has placed, or over an unplaced context facet. An owner who asks
aloud for something that needs one gets the deflection ADR-0199 §5 shapes, with
the instruction to ask where they can read it — and the same request on the typed
or rendered channel plans over everything, because that channel's audience is
bounded. That is the right trade for the reason ADR-0199 §1 gives: what this
channel emits "reaches whoever is within range of the device with no act of
theirs". A capability paid for by everybody in the room is not a capability the
owner asked for, and #665's framing — "Speaker ID gates who the hub thinks asked;
nothing gates who hears the answer" — is a statement about exactly that asymmetry.

**And it costs milestone 19 nothing, which is the test the trade has to pass.**
#1318's exit for milestone 19 is the owner asking aloud about their own life and
hearing an answer drawing on accumulated memory. Every record that answer is made
of — a belief of the owner's own, `USER_ASSERTED`, `OBSERVED` or `INFERRED`, with
`about_person` unstated, and the calendar facet — is placed speakable by ADR-0199
§3 and survives the subtraction untouched. So does conversational continuity: the
conversation's recent turns reach `memories` as captured episodes, which are
`OBSERVED` with `about_person` unset by construction (ADR-0074 §4), so the
subtraction never removes one and ADR-0074 §5's continuity seam is unaffected.
What the planner loses on this channel is precisely the set §3 already forbade the
answer to contain.

### 2. One assembly, one retrieval, one filter, and nothing is refetched to replace what it removed

> **Normative.** The subtraction is a **filter over what the turn already
> assembled and retrieved**, applied between retrieval and planning. It performs
> no second context assembly and no second retrieval, it reaches no
> `ContextProvider` and no `MemoryStore` of its own, and it issues no store query
> of any kind.

> **Normative.** No implementation widens, re-runs or re-parameterises retrieval
> to replace what the subtraction removed, and none backfills the retrieval budget
> to the limit it would have reached on another channel. A spoken turn may reach
> the planner with fewer records than a typed one for the same utterance; that is
> the decision working.

> **Normative.** Retrieval itself is unchanged and stays channel-blind. No store
> read, no listing, no export, no `forget` lookup and no retrieval query behaves
> differently because the answer is bound for a channel of unbounded audience,
> and no ADR-0199 posture is expressed as a query parameter.

> **Normative.** The order of what survives is the order it had. The subtraction
> removes members and reorders nothing, so ADR-0074 §5's three groups — the
> conversation's recent turns, then the relevance-retrieved beliefs, then
> ADR-0158's episodic supplement — arrive in that order still.

**Every prohibition here is ADR-0199 §5's second clause, kept.** That clause's
load-bearing half is that the composing stage "gains no `ContextProvider`, no
`MemoryStore`, no second context assembly and no second retrieval", and ADR-0199
§10 explains why: it is what makes the arrangement compatible with ADR-0170 §2,
whose subject is the *provenance* of the stage's inputs rather than their
cardinality. Moving the subtraction earlier keeps every one of those properties
and in fact simplifies the picture — with the turn produced over the narrowed
supply there is no second `TurnResult` in flight at all, so the `model_copy` the
current implementation makes for the stage disappears rather than moving.

**The backfill clause exists because the helpful version of this is the dangerous
version.** A lane that noticed a spoken turn retrieving twelve records and
planning over four would reasonably reach for a second read to fill the budget.
That read is a second retrieval, which the clause above forbids, and it is worse
than that: to be useful it would have to ask for "more like these, but speakable",
which is a retrieval shaped by what was withheld — a value derived from the
withheld set, of exactly the kind ADR-0199 §5's fourth clause refuses to let a
deflection carry, and a decision procedure over content §2 forbids.

**Retrieval stays channel-blind for a reason worth one sentence.** Pushing the
posture into the store read would make the same query return different rows on
different channels, which is the property that breaks every other reader of the
same store — `forget`'s lookup (ADR-0201 §1), the belief listing, an export — and
would make a disclosure rule into a data-access rule. Keeping the read identical
and filtering after it means the store's behaviour is the same on every channel
and the whole of the posture lives in one module, which is where a reader will
look for it.

### 3. What such an operation returns is the turn that ran

> **Normative.** Where an operation whose channel audience is unbounded returns
> the turn it ran, it returns that turn: the `TurnOutcome` carries the
> `TurnResult` produced over the subtracted supply and nothing else. No component
> retains, returns or renders a second, wider turn beside it.

> **Normative.** This is achieved with **no new type and no new member**. No
> `core/types.py` model gains a field, `TurnOutcome` gains no narrowed variant,
> `SpokenTurn` keeps the four members ADR-0200 §4 gives it, and no ADR-0170 §4,
> ADR-0173 §6 or ADR-0197 §8 clause about a `TurnOutcome` is relaxed.

> **Normative.** ADR-0200 §4's clause that everything other than `reply` "is what
> that transcript would have produced either way" no longer holds on such an
> operation, and is replaced by this section for it: the **turn** is what that
> transcript produced **on this channel** — its `context`, its `memories` and the
> `plan` those inputs produced.

> **Normative.** What that plan determines moves with it, and is named here
> rather than left to be discovered: the plan's steps, which step the engine
> drives, and the `StepOutcome` that step produces. A plan authored over a
> narrower supply may drive a different step, or no step at all, and an
> implementation neither is obliged to nor may attempt to reproduce the step a
> wider supply would have chosen.

> **Normative.** Everything the plan does not determine is unchanged, and that is
> the bound on this replacement: the conversation the turn runs under and its
> resolution, the routing account of a routed pass, `heard`,
> `TurnResult.memory_degraded`, and every degradation flag ADR-0200 §4 places on
> `SpokenTurn`. No lane reads this section as licence for a difference outside
> what §1's subtraction and the plan it feeds produce.

**This is #1693 answered in the direction that costs nothing.** The issue frames
the choice as "is the withholding a property of what the composing stage is
supplied, or of what the operation returns?" and observes that the second answer
needs a narrowed `TurnOutcome`, which is `core/types.py` surface and its own ADR.
This decision makes the question dissolve: with the turn itself run over the
subtracted supply there is only one turn, so the operation returns the withheld
content only if the turn saw it, and it did not. ADR-0200 §7's third clause —
"nothing on this surface carries what was withheld" — is then satisfied
**literally**, not on the narrow reading #1693 offers as the alternative, and the
sentence #1693 flags as overstating ("What the owner does *not* get from this
operation is the withheld content") becomes true as written.

**Why the second difference has to be admitted rather than argued away.**
ADR-0200 §4 says in terms that `reply` is the one thing that differs and that no
lane may read it as licence for another. Under this decision the turn differs too,
so the clause becomes false rather than over-wide, and §9 records it as a partial
supersession rather than pretending the sentence survives. The replacement is
narrow in the way that matters: the difference is not a second *kind* of outcome
and not a second shape — it is the same type carrying what this channel's turn
actually ran on.

**And it reaches the step, which is worth saying out loud because the alternative
is a rule no implementation could keep.** §4's clause names "the turn, the step,
the conversation, the routing account, and every degradation flag" together. The
step is not independent of the turn: `Engine._run_turn` drives `turn.plan.steps[0]`
and builds the `StepOutcome` from what the runner did with it, so a plan authored
over a narrower supply can drive a different step or leave the plan with no steps
at all — the no-action branch, which composes and captures without reserving
capacity. An ADR that subtracted from the planner's supply and then required the
step to be unchanged would be asking for the plan's consequence to be independent
of the plan. So the step moves with the plan and the clause above says so; what
does *not* move is everything decided before the turn planned or outside it, which
is the rest of §4's list. The negative arm of §6 is what keeps this from becoming
an excuse: on a store holding only speakable records the plan, and therefore the
step, is what the same transcript produces on either channel.

### 4. What the capture carries, and why no episode is marked

> **Normative.** The turn a spoken call runs is captured exactly as ADR-0074 §3
> captures every turn, with the content and the stamps §3 and §4 fix. This ADR
> adds no field to `EpisodicMemory`, adds no field to `Provenance`, records no
> channel on a turn, and adds no condition under which a turn is not captured.

> **Normative.** No episode is marked, filtered or withheld on the ground that a
> withholding occurred during the turn that produced it. With §1 in force there is
> nothing to mark: every record and every facet the captured rendering's plan half
> was derived from was placed as speakable on that channel before any stage saw
> it.

> **Normative.** The turn's own **goal statement** is the owner's utterance,
> carried unrewritten (ADR-0074 §3, `LearningLoop.respond`). It is the turn's
> subject and is not a member of the supply §1 subtracts from, so §1 does not
> reach it: no implementation omits it from the capture, trims it, or withholds it
> from the stages of the turn that asked it — which ADR-0199 §5's third clause
> requires, since a stage that was not given the question has no question to
> compose an answer to.

> **Normative.** What a **later** turn on such a channel may do with the episode
> carrying that statement is decided by ADR-0199 §3's placement of that episode,
> exactly as §3 places it today. This ADR neither widens nor narrows that
> placement and issues no permission about it; §8 defers whether the record of an
> asking should be withholdable, with the conditions that fire it.

> **Normative.** Should a later decision put content ADR-0199 §3 withholds in
> front of any stage of a turn on such a channel again, that decision owes the
> marking this section declines: an additive field on `EpisodicMemory` or on
> `Provenance` recording that the record's warrant traces to withheld content, and
> the rule by which a supply site reads it. That is `core` surface and takes its
> own ratified ADR ahead of any lane (golden rule 5, ADR-0015 §5). Until such a
> decision exists, no lane infers a marking, and none is read off the band:
> `OBSERVED` says the assistant witnessed something and says nothing about what
> the turn was supplied.

**This is #1692's first question — "what a turn's capture may carry when a
withholding occurred" — answered by making the question empty.** The episode's
content is the goal statement and the plan rationale (`_exchange_of`, in
`orchestration/engine.py`). With
§1 in force the rationale is authored over a supply from which §3's classes were
already removed, so the episode carries no span of withheld content and no value
derived from one. Nothing about capture changes; what changed is what capture is
handed.

**The goal-statement clauses are stated because the residue is honest, and because
a reader would otherwise find it and think the fix incomplete.** After this
decision the episode of the QA run's first turn still reads *"The user asked: What
do you know about Alice?"*, and a later spoken turn may draw on it, because
ADR-0199 §3 places that episode as speakable. Three things are true of that, and
the third is the one that matters.

It is not the withheld content and not a value derived from it. The beliefs about
Alice reached no stage of that turn, so the rendering paraphrases nothing,
summarises nothing and counts over nothing — which is the property ADR-0199 §5's
fourth clause names and the one #1692 recorded as defeated.

It cannot be withheld from the turn that asked it. ADR-0199 §5's third clause
obliges the composing stage to be told a withholding occurred and to compose an
answer that states it; a stage that was not given the question has nothing to
compose about, and `composing`'s prompt opens with "The user said, in their own
words". So the current turn's goal statement reaching its own stages is ADR-0199's
own requirement, not a permission this ADR invents.

And what a **later** turn may do with it is genuinely open, so this ADR declines
to settle it rather than arguing it away. The tempting argument — the owner said
those words aloud into the same room, so repeating them discloses nothing new —
does not survive ADR-0199 §1's third clause, which rules that the posture "is not
a function of the modality, the transport, the device, the authority the request
carried, the session that admitted the request, or the identity of whoever asked".
ADR-0200 §3 fixes that this operation takes a `SpokenAudio` from a **caller** and
asserts nothing about where that recording came from; nothing on the surface
establishes that the utterance was ever audible in the room the answer is emitted
into, and deriving a permission from how the input arrived is exactly the
inference ADR-0199 §1 refuses in terms. What is true instead is narrower and is
all this decision needs: the goal statement is not a member of the supply §1
subtracts from, so §1 leaves it where it found it, and whether ADR-0199 §3 should
place the episode carrying it differently is §8's deferral rather than this
section's ruling.

**Withholding it would not be free either, which is what makes that a real
question rather than a formality.** The goal statement is in *every* episode
ADR-0074 §3 writes — it is what makes an episode "citable and retrievable" and it
is the substrate the whole conversation seam rests on (ADR-0074 §5) — so a rule
omitting it would end continuity on the spoken channel for every turn, withheld or
not. A decision there has to be about the record of an asking specifically and
needs a way to recognise one, which is why §8 fires it on conditions rather than
leaving it to a lane. It would arrive as a rule about **capture**, or about §3's
placement of an episode, and not as a widening of ADR-0199 §3's placements of the
records a turn retrieves. ADR-0201 already ruled the adjacent question in the other direction —
that a routed `forget`'s lookup does not name the record of the asking — and this
ADR neither extends nor contradicts it, because §1 there is about what a phrase
may name and this is about what may be spoken.

**And the deferral above is ADR-0074 §11's form, deliberately.** §11 records
"nothing on a turn records where it came from" and names the additive field as the
extension route, open and unstarted; ADR-0200 §8 declines to start it. This ADR
declines to start it too, and states what a decision that did start it would owe —
which is the difference between a deferral and a hole.

### 5. Scope: conduct in `orchestration`, and no contract surface

> **Normative.** This ADR decides conduct inside `orchestration` and adds no
> contract surface. It adds no Protocol and no member to one, no `core` type and
> no field on one, no `Settings` field, no member of the promoted engine surface,
> no wire operation and no `PROTOCOL_VERSION` bump.

> **Normative.** The `Planner` contract is unchanged. ADR-0014 §6's `plan(goal,
> *, context, memories)` keeps its signature and its meaning; what changes is
> which records the pipeline puts in `memories` on one class of operation, which
> is the pipeline's own decision and was already its own decision.

> **Normative.** Nothing here authorises egress, relaxes any permission floor, or
> is cited toward a designation, a registration or a destination. ADR-0017 §1 and
> §3, ADR-0021 §5, ADR-0148 §3, ADR-0154 §2 and ADR-0155 §1 and §3 are untouched.

**ADR-0181 §4 continues to describe exactly what it describes, and the direction
is the safe one.** That clause puts `planned_with_external_content` on "the
component that **selected the material** put in front of the model, as the
disjunction of `rests_on_recorded_external_content` over that material".
`Engine._run_turn` computes it as `SelectionOrigin.over(turn.memories)`, and after
this decision `turn.memories` is still exactly the material put in front of the
model on that turn — so the clause is satisfied more literally than before, not
less. Where the subtraction removes an external record, the model was not shown it
and the disjunction correctly does not carry it; §4's monotonicity clause is about
a later step clearing a value an earlier step's selection set, and nothing here
clears anything. The egress gate therefore rules over a strictly smaller set of
material actually seen, which is the direction that cannot weaken it.

### 6. The representative-input tests this decision owes

> **Normative.** The implementing lane pins **#1692's two-turn chain**: on a store
> holding a belief whose `about_person` is stated, a first turn on the operation
> whose channel audience is unbounded is asked a question that retrieves it and
> deflects; the episode that turn captured is then read, and carries no span of
> that belief and no value derived from it. A second turn on the same operation,
> asked what has been discussed, is composed from a supply that carries the first
> turn's episode, and the composing stage is handed nothing naming what the first
> turn withheld.

> **Normative.** The lane pins **#1693's return value**: the same first turn's
> result carries, on the turn it returns, no record ADR-0199 §3 withholds from
> that channel — `memories` and `context` alike — and its plan was produced over
> that same supply.

> **Normative.** The lane pins the **negative arm**, without which the two above
> are satisfiable by withholding everything: a turn on the same operation over a
> store holding only records ADR-0199 §3 places as speakable reaches the planner
> with all of them, plans over them, drives the step that plan chooses, and
> answers rather than deflecting. This is milestone 19's exit criterion asserted
> as a test rather than argued, and it is also what bounds §3's step clause — on a
> supply the subtraction does not touch, the plan and the step are what the same
> transcript produces on either channel.

> **Normative.** The lane pins **the step consequence §3 admits**: a turn on the
> operation whose channel audience is unbounded, over a store where the record the
> plan would have been built from is one ADR-0199 §3 withholds, reaches the runner
> with the plan the subtracted supply produced and not the one the whole supply
> would have produced. The arm exists so that the divergence §3 admits is observed
> once rather than inferred, and so that a later lane cannot quietly restore the
> wider supply to keep the step stable.

> **Normative.** The lane pins **the bounded channel unchanged**: the same
> utterance through `converse`, over the same store, reaches the planner with the
> whole supply. A subtraction that leaked into every operation would pass every
> test above.

**Pinned at the engine, over the canonical fakes, and not against a live hub.**
The chain is an orchestration-level property — retrieval, planning, capture,
retrieval again — and every seam it crosses has a fake in `ai_assistant.testing`.
#1691 found it by driving a hub because that is what a QA run does; a regression
test that needed one would run nowhere and hold nothing. What the gate has to hold
is that the second turn's supply is clean, and that is observable at the composing
seam.

### 7. What the implementing lane owes

The implementation is one lane in `orchestration`, briefed after this ADR merges
(ADR-0015 §5, golden rule 5). It owes:

1. **The change itself**: the subtraction applied between retrieval and planning
   on an operation whose channel audience is unbounded, with the fact that a
   withholding occurred reaching the composing stage as it does today
   (`composing.compose`'s `withheld` argument). The narrowing predicate is
   `orchestration.disclosure`'s and is not rewritten; what moves is where it is
   applied. `Engine._composed_spoken`'s narrowing is removed rather than
   duplicated, so the subtraction has exactly one site.
2. **The docstrings that now read more widely than they hold.**
   `orchestration/disclosure.py`'s module docstring ("before the composing stage
   sees anything", and the paragraph beginning "**The withholding subtracts and
   adds nothing**"), `supply_for_unbounded_audience`'s `turn` argument
   documentation ("**Not modified** — ADR-0199 §5 keeps it exactly as the turn
   made it"), and `Engine._composed_spoken`'s second paragraph
   ("**The** `TurnResult` **the turn produced is unchanged**"). Each is re-pointed
   at this ADR rather than deleted: the sentences are still true of a bounded
   channel, and what changes is where the subtraction sits on an unbounded one.
3. **The five tests of §6.**
4. **The record on ADR-0200**, which is the item below.
5. **Closing #1692 and #1693**, which this decision answers and that lane fixes.

**The record owed on ADR-0200 is specified here so the lane applying it cannot get
it wrong.** ADR-0200's `Status` reads `Accepted`, a plain line with no leading
token, so recording this partial supersession makes it a leading-token line and
ADR-0082 §2 governs the form.

> **Normative.** The record owed on ADR-0200 is one change making two edits
> together: its `Status` line takes the leading `Partially superseded by ADR-0203
> (<scope>)` form of ADR-0070 §4 and `docs/adr/template.md`, and an appended dated
> note records the supersession (ADR-0070 §1). The scope names §4's
> second-difference clause as the header of this ADR names it, and nothing else of
> ADR-0200 is touched. Applying one edit without the other is not a partial
> record.

> **Normative.** That change is owed by the **first** change after this one to
> touch ADR-0200, and the implementing lane of §§1–4 is that change unless a
> nearer one arrives. It is not conditional on the implementation landing: it
> records a decision, and the decision is ratified when this ADR merges.

**Why ADR-0199's record is made in this ADR's own change and ADR-0200's is not.**
ADR-0082 §1 decides **whether** a record is owed and §2 decides **where on the
earlier ADR it goes**; neither decides which change carries it, and ADR-0082 §7
puts the condition at the superseding ADR *existing* rather than at its being
ratified. Both orders are permitted and the corpus works both: ADR-0201 §8
scheduled its record on ADR-0197 into the implementing lane, while today's two
nearest cases wrote the record beside the ADR that earned it — ADR-0177's record
for ADR-0200 (`a96f4552`, "make ADR-0177's record for ADR-0200 rather than filing
it") and ADR-0004's and ADR-0174's for ADR-0202 (`a77b4d76`). This change makes
ADR-0199's record for the same reason those did, and schedules ADR-0200's because
the change authoring this ADR was scoped to ADR-0199's header and may not widen
its own reach to a second ADR's. What is **not** permitted is the record never
being made, which the clause above closes.

### 8. What this ADR does not decide

> **Normative.** Beyond §§1–7 and §9, this ADR decides nothing. It changes no ADR
> other than the two clauses named in its header, adds no name to `core`, and
> moves no method signature on the promoted surface.

- **ADR-0199 §3's placements.** Which classes are speakable on an unbounded
  channel is untouched, in both directions. This decision changes *when* the
  placement is applied and nothing about *what* it places.
- **Whether the record of an asking is withholdable** (§4). Deferred with two
  conditions, either of which fires it. **Person identity and household
  disclosure** (#691, ADR-0199 §7), which is the setting in which a second person
  in the room a day later makes it a live question. And **the first caller of an
  operation of this class whose utterance did not reach the room the answer is
  emitted into** — a spoke on the surface ADR-0094 §10 defers, or any caller
  supplying a recording it did not just capture. ADR-0200 §3 makes that second
  condition real rather than hypothetical: the operation takes a `SpokenAudio`
  from a caller and asserts nothing about its provenance, so the intuition that
  the room already heard the question is a property of today's one front end and
  not of the operation.
- **A bounded spoken channel.** ADR-0200 §3 rules it a later ADR's, arriving as
  its own declared channel rather than as an argument, and nothing here starts
  it. When one arrives, §1's rule keys on the declaration it makes, with no
  clause here to amend.
- **Whether the composed answer joins the captured episode** (#1314). ADR-0170 §9
  and ADR-0197 §11 leave it to `track:memory` and this decision leaves it there.
  Where it lands, the answer joining a spoken turn's episode is the deflection
  composed for that channel, so §1's property survives it — but that is a
  consequence to check then, not a permission granted now.
- **The delivery path.** ADR-0199 §5's delivery clauses stand exactly as written:
  a delivery whose content §3 withholds is not emitted on that channel and stays
  in the outbox. There is no turn there, so §1 has no subject on it.
- **Anything about egress, retention or deletion.** ADR-0074 §7's episode horizon
  and ADR-0074 §8's deletion protocol are untouched, and this decision does not
  lean on either. A finite horizon would drain the offending episodes eventually,
  which is not a fix — #1692 is at its worst in the minutes after the first ask.
- **Speaker identification, voiceprints and presence.** ADR-0199 §4 stands whole,
  and nothing here is cited toward moving a channel's audience from unbounded to
  bounded.

### 9. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

**ADR-0199 §5 — a record is owed, and it is a partial supersession.** Its second
clause opens "The withholding subtracts from what the turn produced and adds
nothing. The `TurnResult` the turn produced is unchanged". A reader holding only
ADR-0199 builds what `main` carries today: the turn runs over everything, the
subtraction produces a supply for the composing stage alone, and the turn is
handed back untouched — which is the chain #1692 recorded. After this decision
they subtract before the turn plans, and the turn the outcome carries is the
narrowed one. That is a reader acting **differently**, which is ADR-0070 §1's line
between an amendment and a supersession, so it is a supersession and partial
supersession is the sanctioned form (ADR-0070 §3).

It is **narrow, and the clause's other half is kept rather than merely preserved**.
What is replaced is the sentence fixing the turn's own supply, and only as it
reaches an operation whose output channel's audience is unbounded; on every other
operation the clause governs unchanged. The rest of the clause — that the stage
gains no `ContextProvider`, no `MemoryStore`, no second context assembly and no
second retrieval, and that its context and memories reach it from the turn and
from nowhere else — is restated as this ADR's §2 and is *more* nearly satisfied
after the change, because the narrowed copy the current implementation makes
disappears instead of moving. §5's first clause (withheld at supply, never a
filter over composed prose), third, fourth, fifth, sixth, seventh, eighth and
ninth clauses are untouched, and the deflection §5 shapes is the same deflection.

**ADR-0200 §4 — a record is owed, and it is a partial supersession.** Its clause
reads: "Everything else — the turn, the step, the conversation, the routing
account, and every degradation flag — is what that transcript would have produced
either way. No lane reads this clause as licence for a second difference." Under
§§1 and 3 above the turn is *not* what that transcript would have produced on
`converse`: its `context`, its `memories` and its `plan` are the narrowed ones,
and **the step is not independent of the plan** — `Engine._run_turn` drives
`turn.plan.steps[0]`, so a plan authored over a narrower supply can drive a
different step or none. The sentence becomes false of two of the five things it
names, and a reader holding only ADR-0200 would refuse the implementation this ADR
requires — so the test comes out at supersession, narrowly and on that clause
alone. The three it names that the plan does not determine — the conversation, the
routing account and the degradation flags — stay true, and §3 above says so as a
bound rather than leaving the scope open. Everything else §4 decides stands: `SpokenTurn`'s four
members, the `heard`/`outcome` pairing, the blank-transcript shape, the local
refusals ordered ahead of it, the byte-for-byte transcript, `spoken` as the
rendering of `outcome.reply` and of nothing else, and every clause of the
degradation ladder. §3 above states the whole of the difference this ADR admits
and forbids a third, so the replacement is bounded in its own text.

**ADR-0200 §7 — no record is owed, and it is worth stating rather than omitting**,
because it is the section a reader will check first. Its first clause fixes where
ADR-0199's rules are applied — "in `orchestration`, **inside the turn**, and
nowhere else" — and stays true, more literally than before. Its second clause
("The withholding is **at supply**… content withheld from this channel does not
reach the composing stage among the inputs the reply is composed from") stays true
word for word; this ADR adds that it does not reach the planning stage either,
which is a stacked addition contradicting no sentence §7 wrote. Its third clause
— "nothing on this surface carries what was withheld" — is the clause this
decision makes *true*, and a reader acting on it as written would already have
refused today's implementation. Its fourth clause invokes ADR-0199 §5's second
clause for the four things it forbids the composing stage, all four of which §2
above keeps verbatim; the half this ADR replaces is not what §7 invokes it for,
and §2 restates the four prohibitions in its own terms so the reference resolves to
a live obligation either way. Recorded here because a reader checking §4's record
will look for a companion on §7, and because ADR-0082 §1 forbids a record demanded
on book-keeping grounds alone.

**ADR-0200 §8 — no record is owed.** Its clause that the turn a spoken call runs
"is captured exactly as ADR-0074 §3 captures every turn", and that the ADR adds no
field to `EpisodicMemory`, none to `Provenance` and no record of the channel, is
restated and obeyed by §4 above rather than narrowed. Its audio-retention clauses
have no subject here.

**ADR-0074 §3, §4 and §5 — no record is owed.** §3's capture rule and §4's stamps
are unchanged: the same episode is written, with the same content rendering, the
same `OBSERVED` source, the same sub-1.0 constant and the same open validity. What
differs is the value `turn.plan.rationale` holds when capture reads it, which is a
fact about the turn rather than about capture, and §4's own closing sentence —
`content` is "the canonical rendering of the exchange — what was asked, and how it
turned out" — stays exactly true of it. §5's continuity seam is untouched, and §1
above shows why in the strong form: a captured episode is `OBSERVED` with
`about_person` unset, so the subtraction never removes one and the conversation's
recent turns reach the planner in full.

**ADR-0170 §1, §2 and §9 — no record is owed.** §1's rule that no reply is gated
is untouched; nothing here gates a reply or adds a permission check to the reply
path. §2 is the clause ADR-0199 §10 already applied this test to, finding that it
fixes the **provenance** of the composing stage's inputs and not their
cardinality — "an implementation satisfying §5 still satisfies every clause of
ADR-0170 §2" — and the same holds a stage earlier and for the same reason: the
stage still holds no provider and no store, assembles nothing a second time,
retrieves nothing a second time, and receives what it receives from the turn. §9's
deferral of whether the answer joins the episode is named and left where it is.

**ADR-0014 §6 — no record is owed.** The `Planner` Protocol is unchanged in
signature and in meaning. §6's ruling is that `context` and `memories` are
parameters rather than things the planner fetches, "because the pipeline already
assembles context and retrieves memory *before* planning"; it says nothing about
how many records the pipeline puts in them, and a pipeline that selects fewer on
one class of operation contradicts no sentence of it. §5 above states this in
terms so it is a rule rather than a reading.

**ADR-0158 — no record is owed.** The episodic supplement is a second read with a
budget of its own, and it runs unchanged. Its output passes through the same
subtraction as the rest of `memories`, and since every captured episode is
`OBSERVED` with `about_person` unset, in practice nothing of it is removed.

**ADR-0181 §2 and §4 — no record is owed**, and §5 above argues it: the value is
still computed by the component that selected the material, over the material
actually put in front of the model, and the change moves that set only in the
direction of showing the model less.

**ADR-0199 §§1, 2, 3, 4, 6, 7, 8, 9 and 10 — no record is owed.** Each is read and
applied as given. §8's second clause — no lane ships an unbounded output channel
until a ratified ADR decides how a channel's audience reaches the composing stage
— is satisfied by ADR-0200 §3 as before and is neither relaxed nor re-discharged
here. §8's first clause, that ADR-0199 adds no contract surface, is matched by §5
above for this ADR.

**ADR-0201 — no record is owed**, and the adjacency is named in §4 because a
reader will feel it: §1 there rules what a routed `forget`'s lookup may *name*,
which is a rule of query resolution over the store; §1 here rules what a turn may
be *supplied* on a channel. Neither reaches the other, and ADR-0201 §2's rule that
an episodic record passed to the typed `forget` is still destroyed is untouched.

**Everything else is a stacked addition and no record is owed**: ADR-0100 (the
`about_person` field is read as ADR-0199 §3 already reads it), ADR-0092 and
ADR-0093 §7 (the attested join, used as given), ADR-0015 §5, ADR-0070 §§1, 3 and
4, ADR-0082 §§1 and 2, ADR-0088 and ADR-0089 (followed, in the forms they
prescribe).

**This ADR marks its rulings** (ADR-0089 §5), so the marked clauses are the whole
of what it obligates and the prose beside them is read to determine what a marked
clause means.

**This ADR's own ratification.** Drafted, reviewed and revised as `Proposed`. The
required set is **adversarial alone**: it touches neither `core/protocols.py` nor
`core/types.py` and decides no contract surface — §5 is the statement of that — so
`CONTRIBUTING.md` → "Stop when the required reviews are green" puts it outside the
contract-surface case. The status was flipped only once that review returned clean
on one tree, by the one-line flip ADR-0165 §2 exempts, with `just adr-ratify`
making it; the sequence is `CONTRIBUTING.md` → "Finishing an ADR PR". The record
this change makes on ADR-0199 is committed **before** the flip, so the flip commit
is the exempt shape and the reviewed tree is the one carrying both. Nothing
implements against §§1–7 until this has merged (ADR-0015 §5, golden rule 5).

## Consequences

**Milestone 19's exit criterion becomes provable rather than argued.** "A content
class ruled unspeakable is deflected, not read aloud" held on turn one and failed
on turn two; after this decision it holds on both, and §6's two-turn test is what
holds it there. #1692 and #1693 close with the implementing lane.

**The disclosure posture gets one site instead of two.** Today the subtraction
happens in `Engine._composed_spoken` and the turn survives it; afterwards it
happens once, between retrieval and planning, and there is no wider turn anywhere
in the process. That is fewer places for a later stage to be added downstream of
the ruling by accident — which is exactly how the planner ended up upstream of it.

**A spoken turn is less capable than a typed one, deliberately and visibly.** The
planner cannot act on a belief about another person, or on an unplaced source or
facet, when the answer is bound for a loudspeaker. Owners will encounter this as a
deflection where the typed channel answers, and the deflection's own instruction —
ask where you can read it — is the remedy. If that proves too blunt, the instrument
is ADR-0199 §6's "may be spoken" record, whose surface is deferred with its own
trigger; it is not a relaxation of this decision.

**Retrieval budgets are spent on records some turns will not use.** A spoken turn
retrieves under the same limit as a typed one and then discards what §3 withholds,
so it can reach the planner with fewer records. §2 forbids backfilling, so the
observable effect is a thinner prompt on that channel. Making retrieval itself
channel-aware would fix the waste and cost the properties §2 explains; if the waste
ever matters, it is a retrieval-efficiency question and takes its own decision.

**Two ratified clauses are narrowed, and both `Status` lines say so.** ADR-0199
§5's second clause and ADR-0200 §4's second-difference clause, each only as it
reaches an operation whose output channel's audience is unbounded. A reader landing
on either ADR is pointed here.

**What would trigger revisiting this.** A bounded spoken channel (ADR-0200 §3
defers it), which would give the same modality two postures and make §1's keying on
the operation load-bearing in a way it is not today. Person identity landing
(#691), which is when the record-of-the-asking question in §4 becomes real. And a
stage arriving between retrieval and planning — an intent classifier, a reranker,
a summarizer — which would have to sit on the subtracted side of the line, and
which §1's first clause already says.

## Alternatives considered

**Mark the episode a withholding turn produced, and withhold it later.** The
repair the finding suggests. Rejected in the Context above and again in §4: it does
not reach #1693, it is `core` surface for a question that does not need one, and it
leaves the same rationale in the `PlanStore` and on the rendered surface. It also
requires §2's recorded-origin discipline to gain a notion of "derived from
withheld", which is the one thing an origin cannot record about a model completion
without the completion's producer recording it.

**Narrow only what the operation returns**, giving `SpokenTurn` a narrowed
`TurnOutcome`. #1693's own second option. Rejected: it fixes the return value and
nothing else — the episode is written hub-side whatever the caller receives, so
#1692 survives it entirely — and it costs a `core/types.py` change and a second
outcome shape, which ADR-0200 §4's own history (two drafts, one removed type) is a
warning about.

**Withhold every episode from a spoken channel.** A blunt version of the marking,
needing no new field: never place a captured episode as speakable. Rejected on
ADR-0074 §5 — the conversation's recent turns *are* episodes, and withholding them
would end conversational continuity on the spoken channel for every turn, withheld
or not. It also over-withholds by a wide margin, since the great majority of
episodes record turns in which nothing was withheld at all.

**Stop capturing the plan rationale on a spoken turn.** Change `_exchange_of` for
that path. Rejected on three grounds: it needs the channel recorded on the turn,
which ADR-0200 §8 and ADR-0074 §11 both decline; it leaves #1693 and the persisted
plan untouched; and it makes the *content* of an episode depend on the channel its
turn arrived on, which is a change to ADR-0074 §3's shape reaching every consumer
of `content`, the observer's citations included.

**Apply the subtraction at retrieval — read fewer records from the store.** The
narrowly-missed alternative, and the one an implementer will reach for because it
looks like it saves work. Rejected in §2: it makes one query return different rows
on different channels, which is a disclosure rule expressed as a data-access rule
and reaches every other reader of the same store; it puts ADR-0199's posture into
`retrieval` and into query parameters rather than in one module; and a retrieval
shaped to backfill what it excluded would be a read parameterised by what was
withheld. Filtering after a channel-blind read costs one pass over a bounded list
and keeps the store's behaviour identical everywhere.

**Leave ADR-0199 §5 as written and correct ADR-0200 §7's sentence instead.**
#1693's first reading: declare that §7's summary overstates, that the withholding
is a property of the composing stage's supply alone, and that a caller of
`converse_spoken` legitimately receives the withheld set. Rejected because it
answers #1693 by weakening the property and does not answer #1692 at all: the
episode would still be written from a rationale authored over withheld content,
and the loudspeaker would still speak it a turn later. It would also leave any
future client of the operation — a spoke, on ADR-0094 §10's deferred surface —
receiving the whole withheld set under no clause about what it may do with it,
which is the exposure #1693 measures as "on the surface, not low".
