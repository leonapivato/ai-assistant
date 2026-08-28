# 210. On a channel of unbounded audience the withholding fires on what the turn was retrieved for, and the conversation's own recent turns fire nothing

- Status: Accepted
- Date: 2026-08-29
- **Partially supersedes:**
  [ADR-0204](0204-a-record-carries-whether-the-supply-it-was-produced-over-held-withheld-content.md)
  — §2's second clause, **scoped to an operation whose output channel's audience is
  unbounded**, in the one respect that its disjunction is evaluated over the supply
  "as assembled and retrieved" *whole*. On such an operation the disjunction is
  evaluated over the part of that supply retrieval placed there for the turn's own
  goal statement, and not over the conversation's own recent turns. Both terms of
  the disjunction, both grounds on which a producer sets the field, §1's field, §3's
  withholding, §4's bounded-channel rule and §5's no-clearing ratchet are untouched,
  and the evaluation on a channel of bounded audience is untouched entirely.
- **Partially supersedes:**
  [ADR-0199](0199-the-audience-of-the-output-channel-decides-what-may-be-said-and-a-withheld-class-is-deflected-rather-than-redacted.md)
  — §5's third clause, **scoped to the same operations**, in the one respect that
  the composing stage is told a withholding occurred wherever any content was
  withheld from the turn's supply. It is told where the withholding removed
  something retrieval placed in that supply for the turn's own goal statement.
  §5's first, second and fourth through ninth clauses are untouched, §3's placements
  are untouched, §2's recorded-origin discipline is untouched, and no class becomes
  speakable.

## Context

### Where this comes from

The milestone-20 QA run (#1765) drove ADR-0199, ADR-0203 and ADR-0204 end to end on
a live scratch hub with a real model, and filed **#1775**. Its finding is not that
any of the three is wrong. Every clause of each behaved exactly as ruled, and the
run confirmed the arm ADR-0204 was written for: a belief the observer distilled from
a stamped episode, whose own `about_person` is `None`, carried
`supplied_withheld_content = True` and was withheld aloud while the typed channel
still got it.

What the run measured is a **composition**. On a store seeded with exactly one
`about_person` belief and driven for a dozen ordinary turns, **12 of 13 episodes**
carried `supplied_withheld_content = True` — including *"The user asked: What is the
time?"* — and the spoken channel answered the time of day with *"There's something
else related to that I'd rather not say out loud; ask me again where you can read
it."* Asked what the previous message had been about, the spoken channel said it did
not have it.

#1775 names two consequences, and they are separable. One is the **stamp**: the
episodic record fills with stamped episodes, and ADR-0204 §3 then withholds all of
them from the spoken channel, so that channel has no history. The other is the
**deflection**: ADR-0199 §5's third clause fires on turns that have no bearing on the
withheld class at all. #1775 sizes the pair `major` and states the reason plainly:
the withholding "is **monotonic and unbounded in practice**: it only ever spreads, it
never contracts, and on a real store it will spread through the whole episodic record
within a session or two of the owner mentioning anyone by name."

This ADR is that sentence's answer.

### What the three ADRs actually compose into, read against the tree

**ADR-0204 §2's second clause** fixes what is evaluated:

> The value carried to capture is the **disjunction of two terms over the one supply
> the turn already holds**, and is `True` where either is. The first is §2's direct
> route: that evaluation found at least one record or one context facet ADR-0199 §3
> withholds from a channel of unbounded audience, in the supply **as assembled and
> retrieved** and before any subtraction. The second is §5's inherited route: at
> least one record in that same supply carries `supplied_withheld_content` already.
> It is `False` only where neither holds.

**ADR-0199 §5's third clause** fixes what the composing stage is told:

> Where content was withheld, the composing stage is told **that** a withholding
> occurred, and composes an answer that states it.

One boolean serves both. `orchestration/disclosure.py`'s
`supply_for_unbounded_audience` returns it as its third value, `UnboundedAudienceSupply`
latches it, `Engine` reads it once and hands it to the composing stage and to capture.
That is ADR-0204 §2's own "one evaluation, two uses", and this ADR does not disturb it.

**And ADR-0203 §2's fourth clause fixes what "the one supply the turn already holds"
contains**, by name:

> The order of what survives is the order it had. The subtraction removes members
> and reorders nothing, so ADR-0074 §5's three groups — the conversation's recent
> turns, then the relevance-retrieved beliefs, then ADR-0158's episodic supplement —
> arrive in that order still.

The first of those three groups is the load-bearing fact of this ADR, and ADR-0074 §5
minted it while declining to call it relevance at all:

> **`memories` carries the records the pipeline has assembled for this turn — the
> conversation's recent turns in order, then records retrieved as relevant, best
> first within that group.**

§5 gives its reason in the same breath. A conversation tail is "*usually* the most
relevant thing the store holds for a continued exchange — but not always, and the
counterexample is ordinary: a user who changes the subject mid-conversation is handed
prior turns that are not relevant to the new goal at all. Calling that 'best first'
would be a strain, so the contract is restated instead". The tail is in the supply
because it is **the conversation**, not because it answered the question.

`LearningLoop.respond` builds exactly that sequence — `recent + retrieved`, then the
supplement — and hands the whole of it to the `SupplyFilter` between retrieval and
planning.

### The mechanism, measured in this clone rather than inferred

The tail is where the spread lives, and it needs no store at all to demonstrate. One
stamped episode in the conversation's recent turns, with **nothing retrieved**, over
`supply_for_unbounded_audience`:

```text
tail-only stamped   -> kept=[] withheld=True
tail-only unstamped -> kept=['e2'] withheld=False
```

That is the whole engine of #1775's "monotonic and unbounded". A turn deflects and
its episode is stamped. The next turn's tail holds that episode; ADR-0204 §3 withholds
it; the boolean comes back `True`; the composing stage states a withholding and
capture stamps the new episode. The next turn's tail holds two. **Nothing ever leaves
the tail unstamped again**, on any store, for as long as the conversation runs — and
each conversation seeds the next through ADR-0158's episodic supplement.

ADR-0204 §6 states the property this defeats, in terms: "continuity on the spoken
channel survives for every turn on which nothing was withheld". After one withholding
there are no such turns.

### Three hypotheses in the record that do **not** survive contact with the tree

**The retrieval floor is not the mechanism.** #1775's first bullet reads "The
retrieval floor is what makes the direct route fire on unrelated turns", and the
brief that dispatched this lane inherited it. It does not hold for the case #1775
measured. `assemble_by_band` fills one budget in `BAND_PRECEDENCE` order, so the
`ASSERTED` band is read first and allocated first: with `limit` 30 and two lower bands
holding records, the asserted page's take is `min(len(page), 28)`. The belief #1775
seeded was written by `learn`, which `learning/processor.py` gives
`MemorySource.USER_ASSERTED`, and `band_of` puts that in `ASSERTED`. A single
`USER_ASSERTED` record is therefore taken by **precedence**, on every query, whether
or not ADR-0187 §4's floor exists. The floor reserves a slot for a band precedence
would otherwise have exhausted the budget before reaching — a *lower*-precedence band
— so it is a mechanism for a withheld record in `ATTESTED` or `DERIVED`, and is inert
for the one that was measured. An ADR that narrowed on the floor would have changed
nothing #1775 saw.

**"Earned its slot by relevance" is not decidable from anything recorded.** The
directive this lane was given was to evaluate over records that earned their slot by
relevance rather than by the floor or by an unbinding budget. On a store whose band
holds fewer records than the budget, retrieval **makes no selection**: the band's read
returns its whole eligible set and the composition takes it. The only fact that then
separates *"what is the time?"* from *"what is Alice seeing a doctor about?"* is the
magnitude of `MemoryRecord.score` — `SqliteMemoryStore` fills it with the cosine
similarity and the in-memory store with term overlap — because in both turns the
record is rank 1 of 1. §6 refuses that instrument and gives its grounds.

**No context facet fires today.** `CurrentContext` carries exactly two facet fields,
`calendar` and `email`, and `disclosure._PLACED_FACET_KINDS` places both. Its
temporal members are scalars this system read off its own clock and are not facets.
So the facet arm of ADR-0204 §2's first term contributes nothing to what #1775
measured, and this ADR leaves it exactly as it is (§3).

### What is not in dispute, and is used as given

- ADR-0199 §3's placements, its Tier 0 floor and its fourth clause's obligation on an
  admitting ADR. No class becomes speakable or unspeakable here.
- ADR-0199 §2's recorded-origin discipline, in full. Nothing decided here reads
  `MemoryBase.content`, a facet's rendered text, a goal statement, a plan, a composed
  reply or any other span of content, and nothing here asks a model what a passage is
  about.
- ADR-0203 §1's subtraction, whole. On a channel of unbounded audience the withheld
  content still "reaches no stage of that turn: not the planner, not the composing
  stage, and not whatever renders what either produced."
- ADR-0203 §2, whole — one assembly, one retrieval, one filter, no refetch, no
  widening, no backfill, and retrieval channel-blind.
- ADR-0204 §1's field, §3's withholding at supply, §4's bounded-channel rule and §5's
  ratchet. This ADR narrows what **fires**; it unmarks nothing and clears nothing.

### An honest statement of what this ADR is not allowed to settle

It cannot decide whether a withheld record was *responsive to the question*, because
no fact this system records answers that. It cannot reach ADR-0204 §5's absence of a
clearing route, which #1775's second bullet names and ADR-0204 §6 already records as
residue. It cannot make retrieval channel-aware. And it may not weaken the disjunction
in a way that reopens #1708, which is what makes the bounded channel untouchable here.

## Decision

We will evaluate the two facts a withholding produces — the stamp ADR-0204 §2 carries
to capture, and the "a withholding occurred" fact ADR-0199 §5's third clause carries
to the composing stage — over the part of a spoken turn's supply that **retrieval
placed there for that turn's own goal statement**, and not over the conversation's own
recent turns, which are in the supply whatever was asked.

### 1. On a channel of unbounded audience the evaluation is taken over the retrieved groups

> **Normative.** On an operation whose output channel's audience is **unbounded**
> (ADR-0199 §1, declared as ADR-0200 §3 declares `converse_spoken`'s), ADR-0204 §2's
> disjunction and the fact ADR-0199 §5's third clause carries to the composing stage
> are evaluated over the members of the turn's supply that retrieval placed there for
> **this turn's own goal statement** — ADR-0074 §5's second and third groups, the
> relevance-retrieved beliefs and ADR-0158's episodic supplement — and over the
> turn's context facets. They are **not** evaluated over ADR-0074 §5's first group,
> the conversation's own recent turns.

> **Normative.** Both terms of ADR-0204 §2's disjunction are evaluated over that same
> narrowed set, and neither is dropped: a record of the retrieved groups that ADR-0199
> §3 withholds fires the first term, and a record of the retrieved groups already
> carrying `supplied_withheld_content` fires the second. What changes is the set the
> two range over and nothing about either term.

> **Normative.** The **subtraction is unchanged and is applied to the whole supply**,
> the first group included. A record ADR-0199 §3 or ADR-0204 §3 withholds does not
> reach any stage of the turn wherever it stood, and this ADR gives no stage a record
> it did not have before. What a member of the first group loses is only the power to
> set a boolean.

> **Normative.** This narrows one evaluation on one channel. On an operation whose
> output channel's audience is **bounded** the evaluation is exactly ADR-0204 §2's and
> §4's, over the whole supply as assembled and retrieved, first group included, with
> nothing subtracted from that turn.

**The first group is in the supply for a reason that is not about the question, and
ADR-0074 §5 said so when it put it there.** Its own words are quoted in the Context:
the tail is not "records retrieved as relevant", the counterexample of a user changing
the subject is called *ordinary*, and calling the tail "best first" is called *a
strain*. A boolean whose meaning is "something bearing on this turn was held back"
cannot be set by a group whose membership does not depend on the turn.

**And it is what makes the withholding monotone.** The measured behaviour in the
Context needs no store: one stamped episode in the tail, nothing retrieved, and the
boolean comes back `True`. Every later turn inherits it, so the property ADR-0204 §6
asserts — that continuity survives "for every turn on which nothing was withheld" —
is defeated by the second turn after any withholding at all. Removing the first group
from the evaluation restores it exactly, and restores nothing else: the tail's stamped
episodes stay withheld, and the spoken channel still cannot read back the turns on
which the withholding did bite.

**The second and third groups keep the evaluation honest.** Both are read with the
turn's own goal statement as the query — `LearningLoop._retrieve` through
`assemble_by_band`, and `_supplement` through a second relevance read of the same
query. A withheld record in either was surfaced *for this question*, so ADR-0199 §5's
third clause has something to be about, and #1703's path is exactly a turn whose
retrieval surfaced one.

**Facets stay in, and the direction is fail-closed.** A facet is assembled rather than
retrieved, so it earns nothing and this clause could as easily have dropped it. It
does not, for two reasons that point the same way: no unplaced facet exists today, so
the choice costs nothing now; and ADR-0199 §3's sixth clause puts the obligation on
the ADR admitting a facet to state its posture, so a facet arriving unplaced should be
loud rather than quiet.

### 2. What a spoken turn's episode is stamped for, after this

> **Normative.** On such an operation the episode capture writes is stamped where
> §1's evaluation is `True` and not otherwise, and ADR-0204 §2's remaining clauses
> govern it unchanged — the value is a property of the turn whose rendering the
> episode carries, a parked turn's second capture carries that turn's own retained
> value and is never recomputed, a pass carrying no turn carries `False`, and capture
> changes no other field.

> **Normative.** Nothing here authorises writing `False` over a `True` on a record
> that already carries one, in a fold, a supersession, a consolidation or anywhere
> else. ADR-0204 §5 binds whole, and a record this ADR causes not to be stamped is a
> record that was never stamped rather than one that was cleared.

**The two are different acts and only one of them is available.** Narrowing what a
producer *writes* on a new record is a decision about the producer; clearing a value
an earlier producer wrote is the ratchet ADR-0204 §5 forbids, and ADR-0106 §4's reason
for it is untouched here.

### 3. The placements, the subtraction and the withholding are untouched

> **Normative.** ADR-0199 §3's placements are computed exactly as they are, ADR-0199
> §2 decides every class exactly as it does, and ADR-0204 §3's test at a supply site
> for a channel of unbounded audience is applied to every record alike, whichever
> group of the supply it stands in. No record becomes speakable on such a channel by
> anything in this ADR.

> **Normative.** ADR-0199 §5's first, second and fourth through ninth clauses are
> untouched. A deflection is still composed rather than filtered, still carries no
> span of and no value derived from what was withheld, still names a bounded channel
> where one can be named, and a turn on which nothing speakable remains still says so.
> Where §1's evaluation is `True`, everything §5 requires of a deflection is required
> of it.

**The one thing that changes is when the stage is told.** ADR-0199 §5's third clause
obliges an answer that *states* the withholding; this ADR does not touch what such an
answer must contain, must not contain, or must name. It decides which turns owe one.

### 4. #1703 and #1708 stay closed, and each on its own path

> **Normative.** No lane, implementation or later ADR cites this ADR as authority that
> a question naming a third party may be repeated on a channel of unbounded audience.
> ADR-0204 §6's second clause governs that question unchanged, including its statement
> that the case of a turn "supplied nothing ADR-0199 §3 withholds" is "not decidable
> from recorded origin".

**#1708 — a typed turn laundering a rationale into the spoken channel — is not
reached at all.** Its path runs entirely on a channel of bounded audience, where §1's
last clause leaves ADR-0204 §2 and §4 exactly as they are: the typed turn is supplied
everything it retrieved, the tail included, the disjunction is evaluated over the whole
of it, and its episode is stamped and then withheld from the spoken channel by
ADR-0204 §3. Every arm of the chain ADR-0204 §2 describes — "one more typed turn is
all it takes to strip the stamp off the whole warrant" — runs on the untouched side of
this decision.

**#1703 — a withholding turn's own question read back aloud — closes on the path
ADR-0204 §6 names for it.** That section's words are "a withholding turn is exactly a
turn whose supply held content §3 withholds — so §2 stamps its episode and §3 withholds
that episode from a later unbounded-channel turn." A turn that asks about the withheld
class is a turn whose *retrieval* surfaces the withheld record: the question is the
query, and the record's placement in the second or third group is the whole of what §1
evaluates. So the deflecting turn's episode is stamped exactly as it is today, and a
later spoken turn cannot read the question back.

**What #1703's path does not include, and did not include before this ADR.** A turn
whose supply held a withheld record *only* in its first group is a turn whose own
question caused no withheld record to be retrieved. Its episode is not stamped, and its
question may be read back aloud. That is the same case ADR-0204 §6's second clause
already declines — a question naming a third party where the turn asking it was
supplied nothing §3 withholds — and this ADR neither widens nor narrows it. Under
ADR-0204 as it stands the case is reached accidentally, by the tail of a conversation
in which some earlier turn deflected, and the accident is what #1775 measured; the
question itself is no more decidable after this decision than before it.

### 5. ADR-0187 §4's floor is not narrowed, and retrieval stays channel-blind

> **Normative.** ADR-0187 §4 is untouched. Its floor keeps its number, its condition
> and its shape, and no band's read is skipped, bounded to zero or reserved
> differently because the answer is bound for a channel of unbounded audience.

> **Normative.** ADR-0203 §2's third clause binds unchanged: retrieval stays
> channel-blind, no store read behaves differently because the answer is bound for such
> a channel, and no ADR-0199 posture is expressed as a query parameter. This ADR adds
> nothing to what retrieval is asked and takes nothing away.

**#1775's first bullet is answered "no, and the premise does not hold".** The Context
shows why: precedence allocates the `ASSERTED` band first, so a lone `USER_ASSERTED`
record — which is what #1775 seeded — is taken on every query with or without the
floor. The floor reserves a slot only for a band precedence would have exhausted the
budget before reaching, so it is a mechanism for a withheld record in a *lower* band
and not for the case that was measured. Narrowing on it would have been a change with
no effect on the finding that motivated it.

**And a channel-dependent floor is foreclosed anyway**, by the clause quoted above.
A floor that reserved differently for a spoken turn would be ADR-0199's posture
expressed inside retrieval, which ADR-0203 §2 refuses in terms and refuses for a stated
reason: the posture lives in one module, and a reader auditing what this hub will say
aloud reads that module.

### 6. What is refused, and why each refusal is the corpus's own

> **Normative.** No implementation, lane or later ADR narrows the evaluation this ADR
> rules by a **retrieval score, a rank, a similarity threshold or any other magnitude
> the ranking produced**. The set §1 names is decided by which group of the supply a
> record stands in, and by nothing about how well it scored.

> **Normative.** No implementation, lane or later ADR narrows it by **reading
> content** — not `MemoryBase.content`, not a facet's rendered text, not the goal
> statement, not a plan, not a composed reply — and not by asking a model whether a
> withholding bears on a question. ADR-0199 §2's second clause binds whole.

**A score threshold is refused on three grounds and any one of them is sufficient.**
It is a number nobody has measured, which is the shape ADR-0187 §4's last clause
refuses in terms — "a bet on a frequency [that] waits for the measurement ADR-0112 §7's
first clause gates and #789 owns". It is not comparable across stores: `SqliteMemoryStore`
scores cosine similarity in `[0, 1]` and the in-memory store scores term overlap, so one
ratified number would mean two different postures, and the posture would move with the
embedder. And it points the disclosure rule at a quantity derived from the content —
which is not the letter of ADR-0199 §2's second clause, whose subject is deciding a
*class*, but is close enough to its reason that a rule taking it should say so out loud
rather than quietly.

**A model's judgement is refused for the failure it would cause rather than the one it
would prevent.** The composing stage holds the question and the speakable supply, so it
could be asked whether the answer it composed was short of what was asked. Nothing about
that reads withheld content, so no *content* guarantee turns on it. What turns on it is
#1703: under §2 the same boolean stamps the episode, so a model that judged wrongly
would leave a question naming a third party speakable on a channel of unbounded
audience. A disclosure ratchet whose latch is a completion is not a ratchet.

### 7. The residue, stated rather than papered over

> **Normative.** This ADR does not decide, and no lane cites it as deciding, whether a
> withheld record was **responsive to the turn's question**. On a store whose band
> holds fewer records than the retrieval budget, every record of that band stands in
> every turn's second group whatever was asked, so §1's evaluation is `True` on every
> turn and #1775's experience persists unchanged. That is this decision declining to
> buy the narrowing with an instrument §6 refuses, and it is recorded as open.

> **Normative.** The residue is tracked as its own question (**#1785**) and is fired by
> either of two conditions: a measurement of retrieval relevance on a real store of the
> kind #789 owns, or a decision widening what a supply site is told about how a record
> reached it. Neither is authorised here, and a lane may not adopt one on the strength
> of this section.

**What this ADR does and does not buy, said plainly.** It removes the mechanism that
makes the withholding permanent and store-independent: after it, a spoken turn deflects
because *this turn's* retrieval surfaced a withheld record, and never because an earlier
turn did. On a store that exercises retrieval — where a band holds more records than the
budget admits, which is every store after a few weeks of use — that is the whole of
#1775's second harm, and the whole of its first. On the store #1775 measured, a store
holding one belief against a budget of thirty, it changes nothing observable, because
there the store *is* the supply. Saying that here is cheaper than a later reader
discovering it against the QA rig.

**And #1775's second bullet is not this ADR's.** "§5 has exactly one route out —
supersession, which retires the record" is a statement about ADR-0204 §5, which stands,
and about the mirror of the residue ADR-0204 §6's third clause already declines. Nothing
here reaches it.

### 8. Scope: no `core` definition moves, no Protocol, and the one meaning this narrows

> **Normative.** This ADR's implementation changes no **definition** under
> `src/ai_assistant/core/`. It adds no Protocol and no member to one, adds no `core` type
> and no member to one, removes none, and moves no member's type, default, validator or
> wire shape: `Provenance`, `MemoryRecord` and `CurrentContext` all keep the shape they
> have, and the conduct §10 describes is confined to `orchestration`.

> **Normative.** It does require **one prose edit inside `core/types.py`**, and that edit
> is owed rather than merely permitted. `Provenance`'s class docstring says the field is
> `True` "directly, where the supply the turn that produced this record ran over held
> content ADR-0199 §3 withholds from a channel of unbounded audience — whether or not a
> subtraction then kept that content from the stages that produced it", and
> `supplied_withheld_content`'s own `Field` description says the same in shorter form.
> Both sentences stop being true of an episode captured from an operation whose output
> channel's audience is unbounded, and a `core` type whose documentation describes a rule
> the system no longer follows is worse than the narrowing it hides. The implementing lane
> states the exception in both places, cites this ADR beside ADR-0204 §1, and changes
> nothing else in that file.

> **Normative.** It does, on **one class of record**, narrow what
> `Provenance.supplied_withheld_content` *means*. ADR-0204 §1 defines the field as
> recording "whether content ADR-0199 §3 withholds from a channel of unbounded audience
> stood anywhere in this record's warrant", and §1 above narrows what stands in the
> warrant of an episode captured from an operation whose output channel's audience is
> unbounded. That is the partial supersession of ADR-0204 §2's second clause this ADR's
> header states; it is why this decision is a **contract-surface change** owing both the
> adversarial and the architecture lens (ADR-0015 §1) although it moves no `core`
> definition; and it is why the implementation is a lane of its own, merged after this ADR (ADR-0015
> §5, golden rule 5). A reader of the field on any **other** record — an episode of a
> bounded-channel turn, a belief, a record written before this decision — reads exactly
> what ADR-0204 §1 says.

> **Normative.** `PROTOCOL_VERSION` does not move for this change, and ADR-0124 §9's
> test is applied rather than asserted past. That rule bumps the version for "any change
> after which a frame a conforming peer at the new version may send would be refused by a
> conforming peer at the old version, or would be accepted by it with a different
> meaning". No frame changes shape or encoding, no member is added or removed, no
> promoted method's arguments or results change, and every `Provenance` a hub at the new
> version emits is valid for a peer at the old one and reads every member it names. What
> changes is a value the hub **computes**, on one class of record.

**The precedent is ADR-0203's, on a larger change of the same kind.** Its §1 subtracts
from the supply the whole turn runs over, so on a spoken operation `TurnResult.memories`
— wire-carried inside `TurnOutcome.turn` — went from the whole retrieved set to the
speakable subset of it. ADR-0203 §5 rules "no wire operation and no `PROTOCOL_VERSION`
bump" for that, under this same test, and gives the reason in its next clause: "what
changes is which records the pipeline puts in `memories` on one class of operation, which
is the pipeline's own decision and was already its own decision." The same sentence is
true here of one boolean. Reading ADR-0124 §9 as reaching what a hub *decides* to put in
a wire-carried field would have bumped for ADR-0203 §1, for ADR-0187 §4's floor and for
ADR-0158's supplement, none of which did; §9's reach is the frame — its encoding, the
validity of a wire-carried `core` type, and the promoted surface's method set.

**And ADR-0204 §7's second ground is untouched.** The field is hub-authoritative: "No
client sets it, no component reads it off a wire-received record to decide a placement",
and the withholding happens in the hub, at supply, inside the turn. There is no direction
in which a client emits a `Provenance` at all, and no peer at any version acts on the
value, so there is nothing for a version skew to disagree about.

> **Normative.** Nothing here authorises egress, relaxes any permission floor, widens
> any grant, or is cited toward a designation, a registration or a destination.
> ADR-0017 §1 and §3, ADR-0154 §2 and ADR-0155 §1 and §3 are untouched.

**The boundary a spoken turn's supply already carries is enough to implement this.**
`LearningLoop.respond` builds `memories` as `recent + retrieved + supplement` and knows
`len(recent)` before it calls the filter, so the group boundary is a number the loop
already holds. Carrying it to `orchestration/disclosure.py` is a change inside one
subsystem, over the `SupplyFilter` alias `orchestration/loop.py` owns.

### 9. The representative-input tests this decision owes

> **Normative.** The implementing lane pins **#1775's engine**: on a spoken operation
> whose supply holds a stamped episode in the conversation's recent turns and no
> withheld record in either retrieved group, the composing stage is **not** told a
> withholding occurred and the captured episode carries `supplied_withheld_content =
> False` — while that stamped episode is still absent from what the planner and the
> composing stage were supplied.

> **Normative.** The lane pins **the exit test's arm**: on a spoken operation whose
> relevance-retrieved group holds a record ADR-0199 §3 withholds, the composing stage is
> told a withholding occurred and the captured episode is stamped, exactly as today.

> **Normative.** The lane pins **the inherited term over the retrieved groups**, on a
> fixture ADR-0199 §3 would otherwise place as **speakable** — `about_person` unset and
> a placed `Provenance.source` — carrying `supplied_withheld_content = True`. Such a
> record in the relevance-retrieved group, or in ADR-0158's episodic supplement, fires
> the evaluation, and the same fixture is asserted to be withheld by the stamp alone. A
> fixture ADR-0199 §3 withholds on its own account fires the **first** term and proves
> nothing about the second, so a test written over one cannot distinguish §1's narrowing
> from an implementation that dropped ADR-0204 §2's second term.

> **Normative.** The lane pins **the bounded channel unchanged**: the same conversation
> tail, the same stamped episode, on `converse`, evaluates `True` and stamps its
> episode, and the turn is supplied everything it retrieved.

> **Normative.** The lane pins **#1703's chain end to end**: a spoken turn that
> deflects over a withheld belief is captured stamped, and a later spoken turn is not
> supplied that episode.

> **Normative.** The lane pins **the facet arm unmoved**: an unplaced facet in a spoken
> turn's context fires the evaluation, and `placed_facet_kinds()` still matches ADR-0199
> §3's list.

> **Normative.** The lane pins **the subtraction unmoved**: on a spoken turn whose only
> withheld record is in the conversation tail, that record is absent from the supply the
> `TurnResult` carries, from the planner's inputs and from the composing stage's inputs,
> though the boolean is `False`.

### 10. What the implementing lane owes

The implementation is one lane, briefed after this ADR merges (ADR-0015 §5, golden
rule 5). It owes:

1. **The group boundary**, carried from `LearningLoop.respond` to the supply filter
   inside `orchestration`, and the filter evaluating the boolean over the members past
   it while subtracting over the whole supply. No `core` **definition** change and no
   Protocol change; the two prose edits item 5 names are the whole of this lane's reach
   into `core/types.py`.
2. **`UnboundedAudienceSupply` alone.** `BoundedAudienceSupply` keeps the whole-supply
   evaluation, and the module docstring's account of what the two share is extended to
   say where they now differ.
3. **The seven tests of §9.**
4. **The docstring records**: `supply_for_unbounded_audience`'s Returns section states
   what its third value is now taken over, and `orchestration/disclosure.py`'s module
   docstring gains the group distinction beside its account of the three groups.
5. **The two prose edits in `core/types.py`** §8's second clause requires — `Provenance`'s
   class docstring and `supplied_withheld_content`'s `Field` description — and nothing
   else in that file. They put the lane's diff on `core/types.py`, so ADR-0209 §4 governs
   its merge and it is scheduled when the dispatcher can afford that.
6. **Closing #1775** on the half this decision reaches, with #1785 left open for the
   half it does not.

> **Normative.** The records this decision owes on ADR-0204 and on ADR-0199 are owed by
> the **first** change after this one to touch each file, and the implementing lane is
> that change unless a nearer one arrives. Each is one change making two edits together:
> the earlier ADR's `Status` line takes the leading `Partially superseded by ADR-0210
> (<scope>)` form of ADR-0070 §4 and `docs/adr/template.md` — accumulating a third pair
> on ADR-0199's line without dropping either of the two it carries, and converting
> ADR-0204's plain `Accepted` into a leading-token line under ADR-0082 §2 — and an
> appended dated note records the supersession (ADR-0070 §1, ADR-0082 §2). The scope
> names the clause as this ADR's header names it, and nothing else of either ADR is
> touched. Applying one edit without the other is not a partial record.

**Scheduling both records rather than making them here is permitted and is stated
rather than assumed.** ADR-0082 §7 "puts the condition at the superseding ADR *existing*
rather than at its being ratified", and ADR-0203 §7 took exactly this order for its own
record on ADR-0200, "because the change authoring this ADR was scoped to ADR-0199's
header and may not widen its own reach to a second ADR's". The same is true here: this
lane's change is scoped to one new file. What is **not** permitted is the record never
being made, which the clause above closes.

### 11. What this ADR does not decide

> **Normative.** Beyond §§1–10 and §12, this ADR decides nothing. It changes no ADR's
> text, adds no Protocol, adds no `core` member, moves no default, and creates no
> permission. Where a reader finds a rule they think follows from this decision but
> which no clause above states, it is not decided here.

Named, so that silence is not read as a ruling:

- **Whether a withheld record was responsive to the question.** §7, open, #1785.
- **Whether a clearing route for `supplied_withheld_content` should exist.** ADR-0204
  §5 and §6, untouched.
- **Whether ADR-0187 §4's floor is right.** §5, untouched; ADR-0187 §4's own
  no-larger-share clause governs any change to it.
- **What a deflection says, and in what register.** ADR-0199 §5 and #1779's lane.
- **Anything about a bounded channel.** §1's last clause.

### 12. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a reader
holding only that ADR now act differently?

**ADR-0204 §2's second clause — a record is owed, and it is a partial supersession.**
The clause evaluates the disjunction over "the one supply the turn already holds" and
says so twice — "in the supply **as assembled and retrieved**", "at least one record in
that same supply". A reader holding only ADR-0204 evaluates it over the conversation's
recent turns as well; after this decision, on one channel, they do not. That is acting
differently, which is ADR-0070 §1's line, so it is a supersession; and it is partial in
ADR-0070 §3's sense, because it names one clause of one section and scopes it to one
class of operation. Both of the clause's terms survive, §1's field survives, §3's
withholding survives, §4's bounded-channel rule survives untouched, and §5 survives
whole.

**ADR-0199 §5's third clause — a record is owed on the same test.** Its condition is
"Where content was withheld"; a reader holding only ADR-0199 tells the composing stage
whenever anything was withheld from the supply, and after this decision, on one channel,
they tell it where the withholding removed something retrieval placed there for the
turn's own question. The obligation the clause imposes on the answer — that it *states*
the withholding, names a bounded channel where one can be named, and says nothing
further — is untouched; only its condition is narrowed.

**No record is owed on ADR-0203 or ADR-0187.** ADR-0203 §1's subtraction, §2's five
prohibitions and §4's surviving clauses are all applied verbatim after this decision;
this ADR relies on them and contradicts none. ADR-0187 §4 is quoted to be refused as a
mechanism, which is a statement about what it does rather than a change to what it
decided. A reader holding either acts identically.

**And no record is owed on ADR-0074 §5.** Its three-group sentence is used exactly as
written, as the fact that makes this decision expressible; the distinction between the
tail and "records retrieved as relevant" is §5's own.

## Consequences

**Easier.**

- **The spoken channel keeps its conversation.** After one withholding, every later
  spoken turn on which this turn's retrieval surfaced nothing withheld is captured
  unstamped and stays speakable, so *"What did I just ask you about?"* has something to
  answer from. The property ADR-0204 §6 asserts becomes true again.
- **The deflection means something.** A spoken answer that says something is being held
  back says it because *this question* reached something held back. #1775's *"It's
  currently 8:55 in the evening... there's something else related to that I'd rather not
  say out loud"* stops being reachable from a conversation's history alone.
- **The withholding stops being monotone.** It still never contracts on a record — the
  ratchet is untouched — but it stops propagating to records that had nothing to do with
  it, which is the property #1775 sized `major` for.
- **One boolean, one narrowing, one module.** The change is where ADR-0203 §2 put the
  posture, and a reader auditing what the hub says aloud still reads one file.

**Harder.**

- **The supply filter now needs to know something about the shape of the supply.** It is
  handed a group boundary rather than a flat sequence, and a future group added between
  the tail and the retrieved records would have to say which side of the line it is on.
  §1 names the groups by ADR-0074 §5's own vocabulary so that the question is asked
  rather than answered by accident.
- **A spoken turn can be diminished without being told so.** Where the only thing
  withheld was in the conversation tail, the owner is not told, and the answer is quietly
  short of the earlier turn. That is deliberate: the alternative is the sentence on every
  turn forever, and the thing withheld is the owner's own earlier exchange rather than
  something the store knows about the world.
- **A question that named a third party may be read back aloud** where the turn asking
  it retrieved nothing withheld. This ADR does not widen that hole and §4 says so, but it
  does make it reachable in a case where the tail's accident used to cover it.
- **The QA rig will not show the difference.** On a one-belief store the finding
  reproduces unchanged, and a reader who tests only there will conclude nothing happened.
  §7 says so in the ADR rather than leaving it to be rediscovered.

**What would make us revisit this.** A measurement showing that on a real store the
relevance-retrieved group routinely carries a withheld record the question had no bearing
on — which would mean the second group is no better a proxy than the first, and #1785's
question is the whole question. Or a decision that gives a supply site a recorded fact
about *how* a record reached it, which would let §7's residue be decided on origin
instead of on group.

## Alternatives considered

**Evaluate over the records that earned a budget slot against competition.** The
direction this lane was given. Refused because it does not hold: precedence allocates the
highest band first, so a lone `USER_ASSERTED` record is taken on every query with or
without ADR-0187 §4's floor, and on a store smaller than the budget nothing competes at
all. It would have changed nothing #1775 measured (§5).

**Narrow on a retrieval score.** Refused in §6: an unmeasured number, incomparable
across stores, moving with the embedder, and pointing a disclosure rule at a magnitude
derived from content.

**Let the composing stage decide whether to state the withholding.** Refused in §6.
It reads no withheld content and would break no content guarantee, but the same boolean
stamps the episode, so a wrong judgement leaves a question naming a third party speakable
aloud.

**Drop ADR-0204 §2's direct route on the unbounded channel entirely**, on the ground that
ADR-0203 §1 subtracted the content before any stage of the turn saw it, so nothing in the
episode can trace to it. Refused because the exception swallows it: the turn's own goal
statement is not a member of the supply §1 subtracts from (ADR-0203 §4's third clause),
and it is exactly what #1703 is about. Without the direct route the deflecting turn's own
question becomes speakable aloud on the next turn, which is the path ADR-0204 was written
to close.

**Drop ADR-0204 §2's inherited route on the unbounded channel entirely**, on the ground
that §5's inheritance is about "a producer that derives a record from other records in
this store" and a spoken turn derives from none of the stamped ones, because §3 withheld
them. The argument is sound and it is half of why §1 is safe. It was refused as a *rule*
because it is wider than the finding: a stamped belief that this turn's retrieval
surfaced is a record the question reached, and the owner is better served by being told
than by a rule tidier than the problem. §1 takes the narrower cut and reaches the same
place for the tail.

**Rate-limit the deflection to once per conversation.** Decidable with no content read
and it would have removed the repetition. Refused because it puts the notice on the wrong
turn: the first turn to trip it consumes it, and the turn that actually asks about the
withheld class gets silence.

**Withhold nothing and mark nothing on the spoken channel, trusting the subtraction.**
Refused: it is ADR-0204 §3 undone, it reopens the laundering path #1708 records through
the bounded channel's captures, and the batch that dispatched this lane puts any clearing
route for the stamp out of scope.
