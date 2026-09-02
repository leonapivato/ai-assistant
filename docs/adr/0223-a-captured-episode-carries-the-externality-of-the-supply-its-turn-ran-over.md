# 223. A captured episode carries the externality of the supply its turn ran over

- Status: Accepted
- Date: 2026-09-02
- **Partially supersedes:**
  [ADR-0221](0221-an-episode-carries-the-reply-a-typed-disposition-and-how-the-turn-was-captured.md)
  — **§6's first clause, and within it only its first sentence.** *"Capture writes
  the captured episode's `Provenance.derived_from_external` exactly as it does
  today — it is not set, and takes its `False` default"* is a statement about
  capture, and §1 below makes it false. The rest of that clause and the whole of
  §6's second clause are statements about ADR-0221 itself and stay true; §13's
  deferral of the mark is discharged rather than superseded. The closing section
  works ADR-0082 §1's test through, clause by clause, for this and for every other
  ADR this decision touches.

## Context

### Where this comes from

ADR-0221 §6 deferred one field and §13 named its trigger — *"The origin mark on the
captured episode (§6). Its own ADR and its own lane. Fired by whoever picks it up"*.
This is that ADR. It was filed as **#1868** out of the design note **#1845**, and the
batch that dispatches it is **#1885**.

The gap is one sentence long. `ConversationLifecycle._episode` builds the one
`EpisodicMemory` a turn deposits and leaves `Provenance.derived_from_external` at its
`False` default on every captured episode — unconditionally, whatever the turn ran
over. So the externality this system honours while a record is *in the supply* is
washed off the moment the turn is written down. The label does not survive the diary.

### The gap, read from the tree rather than recalled

`_episode`'s own docstring states it, and states that it was left open on purpose:

> **`provenance.derived_from_external` stays at its `False` default** (ADR-0221 §6).
> Capture stamps no origin mark, threads no origin value to this point, and changes
> no value any component computes for that field.

What lands in the record is not neutral text. `content` is `Engine._exchange_of`'s
rendering of the exchange — the user's goal statement **and the plan rationale**,
which is prose this system's own model wrote — and since ADR-0221 §1, `outcome`
carries the composed reply, which is a second piece of model prose in the same
record. That is ADR-0098 §5's worked example exactly, quoted there against this very
path:

> The attacker's sentence reaches a durable belief through a plan rationale that our
> own model authored and `engine._exchange_of` recorded truthfully. The episode is
> `OBSERVED` because an exchange really did occur. Every provenance field along that
> path is correct, and **there is no field to read**.

There is a field to read now. `Provenance.derived_from_external` exists (ADR-0106
§2), and the producer that would fill it is `orchestration`, which selected the
supply and holds it as data it fetched.

### The three deferral grounds, and which have expired

ADR-0098 §5 gave three grounds for not adding the field, and named them carefully
because an earlier draft had named the wrong one.

- **"It is `core/types.py` surface."** Expired. The field was added by ADR-0106 §2.
  Stamping it is not a contract change, and this ADR makes none.
- **"Where it would land decides its blast radius."** Expired with it: the landing
  place is decided and shipped, on `Provenance`, and ADR-0106 §7 rules out a
  band-keyed validator, so a stamped `OBSERVED` provenance is constructible today.
- **"The standing test is unmet"** — ADR-0073 §4 wants a `Provenance` field decided
  *"with a producer in hand"*. Met. Capture is the producer, and it has been in hand
  since ADR-0074.

ADR-0098 §5 also disposed, in advance, of the objection that would otherwise be
raised against a producer stamping this at all: an engine-stamped *this exchange's
prompt carried external spans* *"is a deterministic, non-inferring record of
something `orchestration` itself just did. It lands on the **recording** side of that
line"* — so ADR-0075 §2's producer boundary is not engaged and does not need
re-deciding. That paragraph exists because a previous draft got it wrong, and it is
quoted here so that no lane re-derives it.

**ADR-0217 did not discharge this.** `MemoryBase.placement` (ADR-0217 §1, moving what
ADR-0204 §2 wrote) and `Provenance.derived_from_external` (ADR-0106 §2) are different
fields answering different questions — *who may receive this* and *what its warrant
rests on*. Only the first moved.

### Three consequences, read from `origin/main`

ADR-0221 §6 declined to ride the stamp because it is *"not prompt-neutral or
permission-neutral"* and named two consequences. A third was found while writing this
ADR and is named here for the first time. All three are read from the tree.

1. **The composing prompt's origin phrase moves.** `orchestration/composing.py`'s
   `_render_record` derives an origin phrase from
   `rests_on_recorded_external_content`, in three arms — `ATTESTED` renders *"reported
   by a connected source"*, a record satisfying the predicate renders *"resting on
   what a connected source reported"*, and everything else renders *"recorded by this
   system"*. A captured episode is `OBSERVED`, which `band_of` maps to `DERIVED`, so a
   stamped one falls into the second arm and renders *"resting on what a connected
   source reported"* where it renders *"recorded by this system"* today.
2. **A user-facing surface moves, and nobody had noticed.** `Engine._summarise` calls
   `belief_summary_from_record`, which projects
   `rests_on_recorded_external_content(provenance)` for **any** `MemoryRecord` — and
   `AssistantEngine.beliefs` accepts `kinds`, so `assistant beliefs --kind episodic`
   lists captured turns through that projection. `interfaces/cli.py` renders it:
   `_render_belief_fields` → `_why` → `_why_derived` → `_outside_warrant`, which on a
   `True` prints *"Some of what I worked it out from came from a connected source
   rather than from you — the belief above is still my own sentence, but its warrant
   is not entirely mine."* The gateway's `assets/app.js` carries the same sentence
   through `outsideWarrant(belief.rests_on_recorded_external_content)`. So a stamped
   episode makes both surfaces say the system *worked out* a recorded exchange from a
   connected source's report. **ADR-0189 §4's third clause obliges a surface to convey
   the fact** where the band is `DERIVED` and the answer is `True`, so silence is not
   available; what is available is saying it truthfully.
3. **Egress loses its automatic `ALLOW` on later turns.** `Engine._run_turn` computes
   `SelectionOrigin.over(turn.memories)`, and `turn.memories` is the supply
   `LearningLoop.respond` assembled — *"the conversation's recent turns, then the
   relevance-retrieved beliefs, then the episodic supplement"*. A stamped episode
   entering that first group carries `planned_with_external_content` to the egress
   seam on **later** turns of the same conversation, and ADR-0181 §5's third clause is
   ratified: *"no ruling an `ActionPolicy` returns is `ALLOW` on a request whose
   binding carries `planned_with_external_content` except under ADR-0148 §3's route
   (a)"*. So one external record in a conversation costs that conversation its
   automatic allow for as long as the episodes it produced stay in the tail.

### What this ADR is not allowed to settle

The mark closes the **recorded-origin** half of ADR-0098 §5's gap and no more. The
corridor that section describes — an attacker's sentence reaching a durable belief
through text whose *recorded* origin is the user or this system — stays open, and
stays open permanently, because nothing on the record can close it. A user who pastes
a hostile email into a turn is exercising judgement (ADR-0098 §1) and their utterance
is not external however it was composed; no stamp this ADR writes reaches it. §7
restates the prohibition that follows.

## Decision

### 1. Capture stamps the mark from the turn's own selection, threaded per call site

> **Normative.** `ConversationLifecycle.capture` takes the value of the captured
> episode's `Provenance.derived_from_external` as an argument, and `_episode` stamps
> it into the `Provenance` it builds. Every other field of that `Provenance` and of
> the episode is stamped exactly as ADR-0074 §4, ADR-0204 §2, ADR-0217 §3 and
> ADR-0221 §1, §2 and §5 already fix them, and no other field changes.

> **Normative.** The value is `SelectionOrigin.over(turn.memories).planned_with_external_content`
> for the turn whose rendering the episode carries — the disjunction of
> `rests_on_recorded_external_content` over the records that turn selected, computed
> by `orchestration` from a supply it holds as data it fetched. No producer's claim
> reaches it, no model is asked, and nothing about it is derived by reading `content`,
> `outcome`, a goal statement, a plan rationale, a composed reply or any other span.

> **Normative.** The value is **threaded to the capture point and never computed
> there**. `ConversationLifecycle` reads no record, no supply and no store to obtain
> it, and evaluates no predicate over any selection: "capture judges nothing" holds
> for this field exactly as it does for `placement`, `disposition`, `capture` and
> `content`. A capture site that has no value to thread states which of §3's cases it
> is in, in code, rather than falling back on a default.

> **Normative.** This ADR changes nothing in `core`. `Provenance` gains no field,
> loses none, and gains no validator — ADR-0106 §7's refusal of a band-keyed validator
> on this field stands, and this ADR does not read it as having been reconsidered.
> `core/protocols.py` is untouched: no Protocol, no member, no signature. No
> `MemoryStore` read gains an argument, no wire operation is added, no `Settings`
> field, no `PROTOCOL_VERSION` movement, and no member of the promoted
> `AssistantEngine` surface changes.

**Why the caller and not the recorder.** ADR-0106 §3 already rules this shape for
every model-backed producer — the marker *"is computed by the component that
**selected the input set**"* — and ADR-0098 §4's third clause gives the reason it
generalises: putting the marking on the selector rather than the producer *"is
fail-closed against a producer that forgets, because the producer never had the
choice"*. Capture is not a model-backed producer, so ADR-0106 §3 does not reach it by
its own terms; the clause above is the same discipline applied by this ADR at this
site, and §8 is explicit that this ADR does not widen §3.

### 2. One computation per pass, so the two facts cannot disagree

> **Normative.** On a pass that produced a turn, the value is computed **once**,
> immediately after the turn is in hand and before anything is driven, and the same
> value is used for both consumers: the episode's stamp, and the `SelectionOrigin` the
> runner is given for the egress seam. No branch of the pass recomputes it, and no
> branch obtains it from a second `SelectionOrigin.over(...)` call over a supply that
> has moved on.

**This is a repair as much as a rule.** Today `Engine._run_turn` computes
`SelectionOrigin.over(turn.memories)` **inside** the branch that has a step to run;
the no-action branch — `if not turn.plan.steps:` — captures having never computed it.
A stamp threaded from the existing call site would therefore be unavailable on
exactly the passes that plan nothing, which are not rare. The value belongs beside
`withheld` and `modality`, which `_run_turn` already reads once and comments *"so
every capture below stamps the same turn's own value and no branch can recompute it
from a supply that has moved on"* — the same sentence, for the same reason, one field
over.

**And the invariant it buys is worth stating on its own.** The episode's mark and the
egress binding's `planned_with_external_content` are then the *same boolean*, not two
booleans that happen to agree. That matters because §6 makes the first the cause of
the second on later turns: if the two could be computed differently, a conversation
could carry an episode saying its turn ran over external material while that turn's
own egress call said it did not, and the corpus would hold two answers to one
question. ADR-0181 §4's third clause forbids the laundering shape at the level of
combining selections; this forbids it at the level of counting them twice.

### 3. The three-case partition, which is ADR-0204 §2's and not ADR-0221 §5's

> **Normative.** Every capture site falls in exactly one of the three cases below, and
> no implementation, setting or later lane adds a fourth without the ADR that decides
> it.

> **Normative.** **The pass produced the turn the episode renders.** The value is that
> turn's own — §1's disjunction over `turn.memories`, computed as §2 requires and
> carried to capture unchanged.

> **Normative.** **The episode renders a turn an earlier pass produced** — the
> resolution of a parked step, which ADR-0074 §3 captures a second time and whose
> `content` renders that turn's goal statement and plan rationale. The value carried
> is **that turn's own**, retained with the parked turn and applied unchanged. No
> implementation re-evaluates, recomputes or defaults it at the second capture. This
> is ADR-0204 §2's fourth clause applied to a third field, for that clause's own
> reason.

> **Normative.** **The pass carries no turn.** The value is `False`, and it is true of
> what that episode holds rather than a default it falls back on. Three passes are in
> this case: a **routed** pass, which produces no `TurnResult` and selects nothing; the
> resolution of a **routed** park; and a resumption **recovered from durable state**,
> which has no turn to retain from. It is the same partition, at the same sites, that
> ADR-0204 §2's fifth clause already draws for the withholding stamp.

**The partition is ADR-0204 §2's, and it differs from ADR-0221 §5's on one site —
deliberately.** ADR-0221 §5 puts a routed pass in its **first** case, because
`modality` names how *the user material the episode renders* reached this system, and
a routed pass does have user material: the utterance ADR-0197 §10 threads to the
capture point. `derived_from_external` is not about the user material. It is about
**the supply the turn ran over**, which is what `supplied_withheld` is about, and a
routed pass has none — `_routed_exchange_of` builds its episode from the utterance and
a phrase for the route's outcome with *"no part of the routed account"*, and there is
no selection for the predicate to find. So the routed pass sits in the third case
here and in the first case there, and a lane reading the two partitions as one table
will stamp it wrong. ADR-0204 §2's fifth clause names the routed pass in the
no-turn case in terms; this ADR follows it.

**`False` on a routed pass is a fact, not a fallback, and that distinction is the
whole of why the third case is written out.** ADR-0181 §3 and
`orchestration/origin.py`'s `NOTHING_EXTERNAL` establish the shape: *"a caller stating
in code that it selected nothing rather than defaulting into the permissive answer …
a lane that never wired a selection through cannot get the permissive answer for
free."* The same applies here. A capture site with nothing to thread says so.

### 4. Consequence one, ruled: the composing prompt gets an episodic origin arm

> **Normative.** `orchestration/composing.py`'s `_render_record` renders an origin
> phrase for a stamped `EpisodicMemory` that is **distinct from the phrase it renders
> for a stamped belief**. The existing phrase — *"resting on what a connected source
> reported"* — is not rendered for an episode.

> **Normative.** The episodic phrase satisfies three conditions and is otherwise the
> assembler's, under ADR-0098 §2's fourth clause. It **does not attribute the
> episode's content, or any part of it, to a connected source or to any source outside
> this system**. It **does not state that the episode's warrant traces to an external
> report**. And it **does** state the fact the mark actually records: that the exchange
> this episode renders was conducted over material that included a record resting on
> recorded external content.

> **Normative.** The unstamped episodic phrase is unchanged, the two belief arms are
> unchanged, and `planning/planner.py`'s and `learning/observer.py`'s renderings gain
> no origin phrase by this ADR. No lane extracts the phrases of the three prompts into
> a shared module, a `core` mapping or a helper any two of them import: ADR-0221 §3's
> rule stands, and golden rule 1 is its reason.

**Why the existing phrase overclaims, in the corpus's own words.** `_render_record`'s
docstring already argues one step of this, for the `ATTESTED`/`DERIVED` split (#1466):
saying a source *reported* a `DERIVED` record's content *"asserts an `ATTESTED`
attribution on this system's own words"*, which is the standing-inflation ADR-0072 §6
and ADR-0073 §4 forbid, and *"it inverts the marker, which exists so a taint reads as
caution rather than as corroboration"*. So the tainted derived arm was written to
*"predicate the warrant"* rather than the authorship — *"resting on what a connected
source reported"*.

An episode breaks that repair, because an episode's warrant is not a derivation at
all. ADR-0074 §4 is explicit: an episode *"is the terminal citation: the thing other
records cite"*, its `evidence` is empty by decision, and its warrant is *"that it
happened and was recorded as it happened"*. There is nothing for it to *rest on*. What
the mark records about it is a fact about the **occasion** — external material was on
the desk while this exchange was conducted — and predicating that of the warrant
asserts a derivation the record does not have. Both of the existing phrases are
therefore wrong for it, in opposite directions, and the third arm is what says the
true thing.

**Recommended wording, offered and not ruled:** *"recorded by this system, over
material that included a connected source's report"*. It keeps the authorship where
ADR-0074 §4 puts it, adds the mixed-origin fact, and predicates nothing of the
warrant. A lane that finds better words inside the three conditions above is free to
use them; ADR-0098 §2's fourth clause leaves this wording to the assembler and this
ADR does not take it back.

**ADR-0181 §6's prohibition on naming a source is not breached, and does not reach
here.** That clause binds *"a surface that renders a `Confirmation` whose `egress` is
present"* and governs how `planned_with_external_content` — a fact about a **call** —
is shown to an approver. This is a **prompt**, rendering a **record's own
provenance**, where the predicate being named is ADR-0106 §1's and where both existing
arms already say "connected source". The two clauses are about different facts on
different surfaces. A lane may not read either as governing the other.

### 5. Consequence two, ruled: the belief-inspection surface gets an episodic arm

> **Normative.** ADR-0189 §4's third clause is **not narrowed, exempted or
> conditioned** by this ADR. A surface still conveys that a warrant came from outside
> where the projected record's band is `DERIVED` and its externality answer is `True`,
> and a stamped episode satisfies both. No surface omits the fact for an episode, and
> no projection suppresses it: `belief_from_record` and `belief_summary_from_record`
> keep projecting `rests_on_recorded_external_content` over every record they are
> given, unfiltered by kind.

> **Normative.** A surface renders the fact for an `EPISODIC` record in wording
> distinct from the wording it uses for a belief, under §4's three conditions read at
> the surface: it does not attribute the episode's content to a source outside this
> system, does not state that the episode was worked out from an external report, and
> does state that the exchange it records was conducted over material that included a
> record resting on recorded external content. ADR-0189 §4 states what a surface
> conveys and leaves the wording to it; this clause constrains the wording it may not
> use and leaves the rest there.

> **Normative.** Every surface that renders the belief listing renders the episodic
> arm — the CLI and the gateway page alike — or renders neither. A fact stated on one
> surface and not on its sibling is a fact a user learns to distrust on both.

> **Normative.** No surface renders a `False` on an episode as an assurance. ADR-0098
> §5's and ADR-0106 §1's reading is unchanged: a `False` says *no selected record
> carried the marker*, never *no external content was involved*, and `_outside_warrant`
> stays silent on `False` rather than negative.

**This consequence was not in #1868, #1885 or the lane's brief, and it is the one that
reaches a user directly.** The chain is short and entirely ratified:
`AssistantEngine.beliefs` takes `kinds`; `assistant beliefs --kind episodic` is
documented in `interfaces/cli.py` as the way to *"see captured conversation turns"*;
`Engine._summarise` projects every listed record through `belief_summary_from_record`,
which computes the predicate for any `MemoryRecord`; and `_render_belief_fields`
prints `_why(belief)` for every row, which for the `DERIVED` band is `_why_derived`,
which appends `_outside_warrant`. Nothing in that chain looks at `kind`.

The sentence it would print of a stamped episode is *"Some of what I worked it out
from came from a connected source rather than from you — the belief above is still my
own sentence, but its warrant is not entirely mine."* Every clause of it is false of a
recorded exchange: the system did not work the episode out, there is nothing it worked
it out *from* — `evidence` is empty by ADR-0074 §4 — and the episode's warrant is that
it happened, which is entirely this system's own. The row above it, on the same
surface, already reads *"I worked it out, and no supporting evidence was recorded"*,
which is a pre-existing oddity of rendering an episode through a belief renderer;
appending this sentence turns an oddity into a claim.

**Ruled here rather than deferred, because the alternative is a known false sentence
on a user's screen.** ADR-0189 §4's own reasoning is the argument: the warrant clause
*"is written as a prohibition rather than as an invitation"* precisely because
ADR-0098 §7's round-6 mistake — reading a warrant marker as a fact about the text —
recurs whenever the marker reaches a new record shape. This is a new record shape.

**And it is a second subsystem, which the implementation must respect.** The stamp is
`orchestration`'s and the surface is `interfaces`'; those are two changes under
`CLAUDE.md`'s one-subsystem-per-change rule and this ADR does not merge them. §10
states the ordering obligation instead.

### 6. Consequence three, ruled: the egress allow, in terms, with the product sentence

> **Normative.** ADR-0181 §5's third clause applies to a request whose binding carries
> `planned_with_external_content` because a **stamped episode** was in the turn's
> supply, exactly as it applies for any other reason. It is not narrowed, exempted or
> conditioned for this cause, and no lane adds an episode-shaped carve-out to it.

> **Normative.** No implementation makes a captured episode invisible to
> `SelectionOrigin.over`, excludes episodes from the disjunction, excludes the
> conversation's own recent turns from it, or clears the mark when the record it was
> derived from leaves the tail. ADR-0106 §4's monotonicity binds this field wherever it
> is written: *"No fold, merge, reinforcement, or supersession clears
> `derived_from_external` on a record that carries it"*, and the exit is a user's
> assertion and nothing else.

> **Normative.** This ADR authorises no egress, relaxes no permission floor, widens no
> grant, and is not cited toward a designation, a registration or a destination.
> ADR-0154 §4's standing-authorisation floor is untouched.

**The product sentence, written rather than discovered.** Once a conversation has held
one record resting on recorded external content, the episodes captured from the turns
that saw it are stamped; those episodes are in the conversation's recent turns; and
every subsequent turn of that conversation that reaches the egress seam is a
confirmation rather than an allow, until the stamped episodes fall out of the tail.
**In a deployment with a reader enabled, this approaches "every outward call in a
conversation asks".**

**Stated against the bimodality, because that is what makes the sentence a decision
rather than an estimate.** #1845 read the hit rate off the tree and it is not a
distribution: only the calendar and email readers produce `EXTERNAL` records, both
ship disabled, and retrieval reads the attested band every turn with ADR-0187
guaranteeing it a slot. So the rate is **0% with no reader configured and
approximately 100% with one**. There is no measured taint rate anywhere in this
repository and this ADR does not invent one. That means the cost is not "some
conversations sometimes"; it is "no conversations at all" until a reader is enabled,
and "most conversations, most turns" the day one is. Both halves are accepted here.

**It is accepted because the alternative is the laundering ADR-0181 §4 exists to
forbid.** A `False` on that binding would not be a lenience; it would be a false
statement, made by the one component that holds the facts, about material this system
selected. `SelectionOrigin.over`'s own docstring names the shape: *"plan a step over
tainted material, re-plan over clean material, stamp the binding from the last
selection, and watch the fact clear … A warrant is never un-received, and neither is
a selection."* Capturing the turn and reading the capture back on the next turn is
that same move with a store in the middle, and the only difference is that it is
slower.

**And the containment it buys is the user's judgement, which is the only containment
this corpus claims.** ADR-0181 §5's own reasoning applies verbatim: a refused call
*"teaches the user nothing, where a call the user is asked about, with the fact in
front of them, is the containment #668 asks for — 'a visible, source-attributed
proposal — spam, not poison'"*. ADR-0181 §6 already rules what that user is shown,
in both states, before their answer is collected.

**What this does not do.** It does not refuse a call, rank one, reorder one, retry
one, route one differently, or change what any turn is supplied. ADR-0106 §8's second
clause — the marker *"does not rank, weight, filter, or order anything"* — is read
here on the egress axis and is unchanged.

### 7. The honesty clause, restated because it binds this ADR

> **Normative.** ADR-0098 §5's prohibition binds this ADR as it binds every other:
> *"No ADR, lane, or surface may state or imply that this posture detects external
> content embedded in text whose recorded origin is not external."* The stamp closes
> the **recorded-origin** half and no other half. No lane cites this ADR as authority
> that a captured episode's externality is *detected*, that ADR-0098 §5's gap is
> narrower than that section states, or that the corridor it describes has been
> closed.

> **Normative.** A `True` says *the supply this turn ran over held a record whose
> recorded origin is external*. A `False` says *no record in that supply carried the
> marker* — never *no external content was involved*, and never *nothing external
> influenced this exchange*. No consumer, prompt, surface or later ADR states or
> implies otherwise, in either direction.

**The corridor stays open, permanently, and saying so is the point of the clause.**
A user who pastes a hostile email into a turn is exercising judgement (ADR-0098 §1),
their utterance is `ASSERTED`, and no rule here touches it. A model-authored sentence
over such an utterance is recorded truthfully with every provenance field correct.
Neither is reachable by any field, and no field this corpus adds will make them
reachable — ADR-0098 §6 already rules that no bound may be bought from a detector.
What this ADR does is stop one *recorded* externality being erased at one place it was
being erased. That is a smaller claim than "the episode is now marked", and the
smaller claim is the true one.

**#1883 is the tripwire on the other side of the same seam, and it is verified
clear.** `SelectionOrigin.over` takes selections of `MemoryRecord`, and a context
facet is not a record and carries no `Provenance`, so no facet can reach either the
egress binding or this stamp. That costs nothing today because `CalendarFacet` and
`EmailFacet` carry counts and instants only — ADR-0096 §6 keeps entry text, subjects
and names out — so no attacker-authored sentence can ride a facet. The lane that first
puts free text on a facet inherits the origin duty for **both** seams, and #1883 is
where that is recorded.

### 8. The gate: what fires today, what does not, and what is reserved

> **Normative.** This ADR adds no `MemoryPolicy` rule, changes none, and adds no
> enforcement point. ADR-0106 §6's ceiling — no policy returns a committing ruling on
> a proposal that is in the `DERIVED` band, carries `derived_from_external` and
> carries no `UserConfirmation` — is unchanged, and this ADR is not cited toward
> restating, narrowing or widening it.

> **Normative.** This ADR does not extend ADR-0106 §3 to `learning/observer.py` or to
> `orchestration/observation.py`, and does not decide what the observer's "input set"
> would be for a proposal if a later ADR did extend it. A lane adding observer
> propagation states that answer in its own ADR and may not read this one as having
> supplied it.

**What fires today: nothing, and the reason is structural rather than lucky.**
`ConversationLifecycle.capture` writes the episode with a one-element `write_atomic`
in `INSERT_IF_ABSENT` mode and *"never through `MemoryWriter.ingest`"* — ADR-0075
partially supersedes ADR-0005's proposal-then-policy path for this producer, and
ADR-0074 §4 states why capture reaches no policy at all. So the stamped episode never
meets ADR-0106 §6's rule, and a stamp that would otherwise turn every captured turn
into an `ASK_USER` cannot.

**That is worth recording because ADR-0074 §4 wrote an obligation against exactly this
case and it is still unmet.** §4 required that *"the `MemoryPolicy` rule leg 3 owes
must exempt episodes"*, so that a band-wide rule would not *"make its own substrate
unwritable if capture were ever routed through the writer"*. `_cites_nothing_it_must_cite`
carries that exemption. ADR-0106 §6's rule, which arrived later, does **not** — it is
keyed on band, mark and confirmation, and an `EPISODIC` record satisfying all three
would be deferred. Nothing takes that path today. A lane that ever routes capture
through the writer inherits ADR-0074 §4's obligation for this rule too, and this
paragraph is where it is written down.

**And the gate is not future work: it is ratified and shipped.** #1868, #1885 and this
lane's brief each describe the third `MemoryPolicy` admissibility rule as a follow-on
deferred on volume. It is not. ADR-0106 §6 ratified it, `DefaultMemoryPolicy`
implements it as the third and last rule of its admissibility floor, `MemoryPolicyContract`
asserts it, and `testing/policy.py` mirrors it. What is deferred on volume is
**observer propagation of the mark**, which is a different decision at a different
seam — and the clause above is what keeps this ADR from making it by implication.

**The granularity question, reserved with both readings stated.** If a later lane does
propagate, it must decide what the disjunction ranges over, and the corpus currently
points two ways.

- **The input set.** ADR-0106 §3 rules, for a model-backed producer, that the marker
  is the disjunction *"over those inputs"* — the set the selecting component chose.
  `orchestration/consolidation.py` implements exactly that and refuses the other
  reading by name for the adjacent placement fold: *"never over the subset the model
  happened to cite, because `Provenance.evidence` is not the input set and folding
  over it would let one uncited narrowed input launder the whole warrant."*
- **The proposal's cited evidence.** The observer's citations are not the model's
  claim — `_resolve` resolves them to ids *this module* holds, ADR-0077 §5 sets an
  evidence floor per epistemic step, and each proposal already carries exactly the
  episodes it was derived from in `Provenance.evidence`. Read that way, one stamped
  episode taints the proposals that cite it and no others.

The difference is not academic. An observation batch is on the order of twenty
episodes and a pass emits several proposals; under the first reading one stamped
episode among them makes **every** proposal of that pass an `ASK_USER`, onto a
deferral queue capped at 50 with no batching — the volume ADR-0106 §6 itself declined
to solve (*"a scheduled consolidator can generate them faster than a user answers
them … This ADR does not solve the volume"*). Under the second, the same batch
produces the deferrals its evidence actually warrants. **This ADR does not choose.**
Choosing would either contradict a ratified clause without superseding it, or
entrench a reading the laundering argument has not been run against for this
producer. What it does is put both readings, and the arithmetic that makes the choice
matter, in front of the lane that has to make it.

### 9. What stays out, by name

> **Normative.** **Observer propagation stays out.** `learning/observer.py` and
> `orchestration/observation.py` compute no disjunction of this field over their
> batch today, and this ADR adds none, obliges none and is not cited toward one. The
> observer's proposals carry `derived_from_external` exactly as they do today.

> **Normative.** **Facet text stays out**, because there is none. No clause here adds
> a facet to any origin computation, and #1883 is where the duty for the lane that
> first adds free text to a facet is recorded.

> **Normative.** **Retention, retrieval and speakability are untouched.**
> `episode_retention` is unmoved and ADR-0074 §7's horizon is what bounds a stamped
> episode's life as it bounds an unstamped one's. No retrieval ranks, filters or
> orders on this field (ADR-0106 §8, ADR-0189 §4's penultimate clause). ADR-0199 §3's
> placements, ADR-0203 §1's subtraction, ADR-0210 §1's evaluation set and ADR-0217
> §2's read rule are each untouched, and an episode's `placement` is stamped exactly
> as ADR-0217 §3 fixes it — this ADR writes a different field and reads none of
> theirs.

**Why propagation stays out, in one paragraph, because the argument is the same one
§6 accepts and it points the other way here.** The hit rate is bimodal and unmeasured;
the downstream cost under ADR-0106 §6 is an `ASK_USER` per proposal on a capped queue;
and no number exists anywhere in this repository to size it. #1845's formulation is
the right one and is adopted: **stamp now, propagate when someone has a number.** §6's
egress cost is accepted without a number because the alternative there is a false
statement at a permission seam; there is no equivalent falsehood in leaving the
observer's disjunction where it already is, because the observer does not compute one
to be wrong about.

**And the coupling is recorded rather than buried**, because deferring propagation has
a price. #1845 states it: deferring propagation removes the one downstream gate, which
makes the reader lane's escaping fix (#672) the *only* control on an injected reply
rather than one of several. Stamping the episode does not restore that gate — §8 is
why — so the coupling stands after this ADR exactly as #1845 wrote it, and the lane
that closes #672 should know that nothing else is standing behind it.

### 10. What the implementing lanes owe

> **Normative.** The stamp (§1, §2, §3) and the composing arm (§4) are
> `orchestration`; the surface arm (§5) is `interfaces`. They are separate changes
> under `CLAUDE.md`'s one-subsystem-per-change rule and no lane merges them into one
> to save a round.

> **Normative.** No lane lands the stamp while leaving §4's or §5's arm unwritten and
> untracked. A lane that lands the stamp without one of them opens the issue that
> carries it, in the same change, naming this section — and the batch that lands the
> stamp does not close until both arms have landed.

> **Normative.** Neither arm may be discharged by suppressing the fact. §4 forbids
> reverting to the belief phrase; §5's first clause forbids omitting the sentence, and
> the projection stays kind-blind.

**The representative-input tests this decision owes**, each stated as behaviour rather
than as a call:

1. A live turn whose supply held an `ATTESTED` record captures an episode with
   `derived_from_external` true; the same turn with a supply of `OBSERVED` and
   `USER_ASSERTED` records only captures one with it false. (§1)
2. A live turn whose supply held a `DERIVED` record *carrying the mark* captures a
   stamped episode — the disjunction is over `rests_on_recorded_external_content`, not
   over the band, so a second-order case is caught. (§1)
3. A pass whose plan has **no steps** stamps the same value as an otherwise identical
   pass whose plan has one. This is the branch §2 exists for and it is the one a
   naive threading loses. (§2)
4. The episode's stamp and the `SelectionOrigin` handed to the runner are the same
   value on the same pass, exercised on a turn where it is true. (§2)
5. A parked turn whose supply was external, resolved by a pass that retrieves nothing,
   captures a **stamped** resolution episode. Exercised in the direction that fails a
   recompute — a stamped park resolved by a clean pass — because the opposite
   direction passes an implementation that recomputes. (§3)
6. A routed pass, a routed park's resolution, and a resumption recovered from durable
   state each capture `False`. (§3)
7. A stamped episode rendered into the composing prompt renders neither belief phrase,
   and renders no phrase attributing its content to a source. An unstamped episode's
   bullet is **byte-identical** to today's. (§4)
8. A stamped episode listed through `beliefs(kinds=[EPISODIC])` renders the episodic
   sentence on the CLI and on the gateway page, and neither renders the belief
   sentence for it. An unstamped episode's row is byte-identical to today's. (§5)
9. A second turn of a conversation whose first turn was stamped produces an egress
   binding carrying `planned_with_external_content`, and the policy returns no
   `ALLOW`. This is the product sentence of §6, pinned. (§6)
10. `planning/planner.py`'s and `learning/observer.py`'s renderings of a stamped
    episode are byte-identical to their renderings of an unstamped one. (§4's last
    clause, and the guard on §9's first.)

### 11. Deferred, by name, each with what fires it

- **Observer propagation of the mark**, and with it the granularity question §8
  reserves. Fired by a measured taint rate, or by a lane that argues the volume is
  acceptable without one. Its ADR states which set the disjunction ranges over and
  answers ADR-0106 §3 explicitly.
- **An episode exemption on ADR-0106 §6's rule**, owed under ADR-0074 §4 and unmet.
  Fired by any lane that routes capture through `MemoryWriter.ingest`; inert until
  one does (§8).
- **Facet origin**, both halves — the escaping half ADR-0098 §9 assigns and the origin
  disjunction #1883 records. Fired by the first lane that puts free text on a facet.
- **The user-pasted corridor.** Not deferred: unclosable, and §7 says so. Named here
  so that no future reader mistakes its absence from this list for an omission.
- **Speakability of a stamped episode** — ADR-0199 §3's placement rules are keyed on
  recorded origin and an episode's `placement`, not on this field, and nothing here
  changes what is speakable. Whether externality should reach that decision is its own
  ground, on #1318's milestone 21.

### 12. Scope

> **Normative.** This ADR changes no `core` surface, adds no Protocol member, no
> `Settings` field, no wire operation, no tool and no `RoutableOperation` member, and
> moves no `PROTOCOL_VERSION`. It adds no field to any record and removes none.

> **Normative.** No read returning records is filtered, ranked or ordered on
> `derived_from_external` by this ADR, and no surface, consumer or later lane adds
> such an argument without the ADR that decides it.

> **Normative.** This ADR changes no retention, no capture condition, and no
> episode's `content`. Every condition under which a turn is captured is what
> ADR-0074 §3, ADR-0197 §10 and ADR-0221 §1 make it, and the rendering is unchanged.

## Consequences

**What becomes easier.** A conversation's own history stops being a laundering path.
The fact that a turn ran over external material now survives into the record of that
turn, so the next turn's egress binding, the composing prompt, and the user's own
inspection surface all see it — three consumers that were each blind to it and none of
which needed a new field to stop being blind.

**What becomes harder, and by how much.** Egress in a reader-backed deployment: §6's
sentence is the cost, and it is large where it applies and zero where it does not.
This is the first decision in the corpus whose accepted cost is stated as a bimodal
rate rather than as a distribution, and it is stated that way because that is what the
tree supports.

**What would trigger revisiting.** A measured taint rate — the number #1845 and §9
both ask for — would let the observer-propagation question be decided, and would also
let §6's cost be sized rather than bounded. A deployment that finds §6's confirmation
rate intolerable has one honest exit and it is not clearing the mark: it is ADR-0148
§3's route (a) applied more cheaply, or a narrower reading of what belongs in the
conversation's recent turns. Both are their own decisions.

**What this leaves standing that a reader might expect it to have moved.** The
observer still proposes beliefs from stamped episodes carrying no mark, and those
beliefs still commit without a question. That is the coupling §9 records, and it is
the honest state of the system after this ADR.

## Alternatives considered

**Stamp the field at the capture point, computed there.** Rejected. `_episode`'s
contract is that capture judges nothing, and computing a disjunction over a supply
would require `ConversationLifecycle` to hold one — a supply it does not have, would
have to be given, and would then be a second site that could disagree with the egress
seam about the same selection. §1 and §2 take the threading instead, which is the
shape ADR-0204 §2 and ADR-0221 §5 already established for this producer twice.

**Rule the composing phrase byte-for-byte in this ADR.** Rejected. ADR-0098 §2's
fourth clause *"leaves this wording to the assembler"*, and `_render_record`'s existing
phrases were chosen under it. §4 rules the three things the wording may not do and the
one thing it must say, which is the part a review can check; fixing the bytes would
move a decision the corpus has twice put in the module and would make a better phrase
a supersession.

**Exempt episodes from the surface sentence.** Rejected, and it was the tempting
option because it keeps the change inside one subsystem. ADR-0189 §4's third clause is
unconditional over `DERIVED` and `True`, so an exemption is a supersession of a
ratified surface obligation, bought to avoid writing one sentence. Worse, it would
make the surface silent about precisely the records the mark was added for, which
inverts the marker in the direction ADR-0106 §1 and ADR-0181 §7 both warn about.

**Write `False` on the binding for a stamp that came from the conversation's own
episodes.** Rejected as the laundering ADR-0181 §4's third clause exists to forbid,
and §6 gives the argument. A value that said `False` there would be untrue about
material this system selected, and the only thing separating it from the re-plan
laundering that clause names is a store and a turn boundary.

**Defer the whole decision again until a taint rate exists.** Rejected on the batch's
own ground and it is worth stating: no reader ships enabled, so the corridor is empty
today and the stamp costs nothing to land. **Defences precede surface.** A decision
made while the cost is zero is a decision; the same decision made the week after a
reader is enabled is a regression argument.

**Ship the stamp and file the two render arms as follow-ups.** Rejected as stated, and
adopted as bounded. §10 does not require one change — that would breach
one-subsystem-per-change — but it does forbid the stamp landing with an arm neither
written nor tracked, and it keeps the batch open until both land. The middle position
is the only one that respects both rules.

## What this records against earlier ADRs, under ADR-0082 §1

**ADR-0221 §6's first clause is partially superseded, and only its first sentence.**
That clause opens *"Capture writes the captured episode's
`Provenance.derived_from_external` exactly as it does today — it is not set, and takes
its `False` default"*. That sentence is a statement about **capture**, and this ADR
makes it false: capture now stamps the field. A reader holding only ADR-0221 would act
differently, which is ADR-0082 §1's test, and ADR-0070 §1 makes a change to what was
decided a supersession rather than an amendment. The record is written on ADR-0221's
`Status` line and in an appended dated note.

**The scope is that sentence and nothing else, and the distinction is ADR-0221's
own.** The remainder of that clause — *"This ADR adds no mark, threads no origin value
to the capture point, and changes no value any component computes for that field"* —
is a statement about **ADR-0221 itself**, and it stays true after this one. So is the
whole of §6's second clause, which binds lanes implementing ADR-0221 and which §7
above restates rather than replaces. This is exactly the test ADR-0221 §5 applied to
ADR-0200 §8 and ADR-0203 §4 — *"What each marks is a statement about **itself** … Both
sentences stay true of their own ADRs after this one, so neither is replaced"* —
applied to ADR-0221 in its turn, and it comes out the other way for one sentence
because that sentence is about capture rather than about the document.

**ADR-0221 §13's first bullet is discharged, not superseded.** It defers the mark with
its trigger — *"Fired by whoever picks it up"* — and being picked up is what a
deferral invites. Nothing in §13 becomes false.

**No record is owed against ADR-0098, ADR-0106, ADR-0181, ADR-0189 or ADR-0074, and
each is checked rather than assumed.**

- **ADR-0098 §5** is restated by §7 and not narrowed; its prohibition binds this ADR
  and this ADR says so. Its three deferral grounds are *conditions*, and reporting
  that they have expired is not a change to what §5 decided. §2's fourth clause
  leaves the composing wording to the assembler and §4 leaves it there.
- **ADR-0106 §3** is not extended to a new producer by implication — §8's second
  clause is the explicit refusal. §6's ceiling and §7's refusal of a validator are
  untouched, and §4's monotonicity is restated in §6 rather than modified. §1's
  clause above states a discipline for `orchestration` at capture; ADR-0106 §3's own
  scope is model-backed producers, so nothing of §3 reads more widely after this.
- **ADR-0181 §5's third clause** gains a new subject and no new reading. A clause
  ratified over *"a request whose binding carries `planned_with_external_content`"*
  says the same thing before and after a new cause of that value exists; §6's first
  clause is a stacked addition recorded here.
- **ADR-0189 §4's third clause** is preserved verbatim by §5's first clause. §4 states
  what a surface *conveys* and does not fix the wording, so constraining the wording
  for one record shape adds an obligation without contradicting a sentence of it.
- **ADR-0074 §4** enumerates what capture stamps and rules that *"capture judges
  nothing else"*. Stamping a **carried** value is not judging, which is the reading
  ADR-0204 §2 and ADR-0221 §5 both took when they added a stamped field at this
  producer without a record against §4; this ADR follows that precedent rather than
  making a new one. §4's episode-exemption obligation is not discharged here and §8
  and §11 say so.
- **ADR-0204 §2** supplies the partition §3 adopts and is not modified by being
  followed; §2's clauses remain statements about the withholding stamp.
