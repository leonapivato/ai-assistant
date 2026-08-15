# 156. A distilled belief states its event time in its content, and no record type grows a field for it

- Status: Accepted
- Date: 2026-08-15
- **Not a substantive contract ADR; contract-surface only for the review set, and
  the two are different questions.** [ADR-0015](0015-simplify-the-agent-workflow.md)
  §5 defines a substantive contract ADR as "one adding or changing a Protocol or a
  `core/` type crossing subsystem boundaries", and §1 below adds and changes
  neither — so §5's land-ahead rule and golden rule 5 are **not** what govern this
  PR, and the implementing lane owes no triad. What *is* true is narrower and is
  about which lenses review it: the decision space §1 surveys includes a structured
  temporal field on the record types in `src/ai_assistant/core/types.py` and rules
  against one, and `CONTRIBUTING.md` → "Stop when the required reviews are green"
  makes a change contract-surface "when it is the ADR deciding that surface, even
  though such a PR is prose only". So the required set here is adversarial **and**
  architecture, on the ground that a ruling *against* a field is still a ruling
  about it and binds the wave-2 lane's surface either way. It is docs-only and **no
  code changes with it**, because the implementation is a separate lane — which is
  #1163's wave structure and the plain fact that the lane needs this text as its
  authority, not a rule ADR-0015 §5 imposes.
- **Amends on ratification:**
  [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) §3, in one named
  sentence. §3's *"The prompt carries the episodes' canonical `content` (ADR-0005
  §1) and what the model needs to cite them (§5)"* enumerates the payload
  exhaustively, and §2 below adds each episode's `occurred_at` to it. Applying
  [ADR-0070](0070-amendment-and-supersession-rules.md) §1's test to that sentence:
  a reader holding only ADR-0077 builds the observation prompt without the
  instants, which is what §2 requires it to carry, so the reader acts differently
  and the record is owed. It is an **amendment and not a supersession**, because
  what §3 *decided* is untouched and is in fact the reason the addition is
  admissible: the bolded ruling is "**The payload is the batch and nothing else**",
  and an `occurred_at` is a field of the batch rather than a second class of data —
  §3's refusals (the user's existing beliefs, the profile, the context facet, a
  plan) all stand verbatim, as do the named route, the no-fallback rule and the
  on-device direction. The dated note **lands on ADR-0077 in this same change**,
  which is the form ADR-0080 and ADR-0111 each took and the existence condition
  [ADR-0083](0083-the-hub-is-a-resident-process.md) §15 states — so the note never
  names an ADR that does not exist, and is `Accepted` at merge alongside it, which
  is ADR-0070 §1's hazard answered rather than deferred. ADR-0077's `Status` line
  is **not**
  edited: it is led by `Partially superseded by`, and
  [ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md) §2 puts
  the record in the note alone on such a line.
- **Amends nothing else.** Applying ADR-0070 §1's test to each decision this one
  leans on: **ADR-0077 §2**'s utility bar ("Do not summarise the exchange. Do not
  propose what merely happened") is untouched and §2's fourth clause below says so
  in terms — the anchor rides on beliefs that bar already admits and widens it by
  nothing. **ADR-0077 §5**'s "Confidence is computed by the producer, and never
  taken from the model" is about a *field*, and §1 below adds no field.
  **ADR-0109 §4**'s third clause ("`last_confirmed_at` … is never taken from a
  model's output") likewise binds a field, holds verbatim, and §3 below is what
  keeps it from being read as forbidding a date in a belief's sentence.
  **ADR-0103 §9** and **ADR-0045 §2** are relied on for the distinctions they drew
  and are not narrowed. **ADR-0005 §1**'s `content` as "a canonical text rendering
  … used for lexical and (later) embedding retrieval" is the clause §1 rests on,
  applied rather than changed.
- **Refs:** #1029 (the scored pilot's pre-registration, its results comment of
  2026-08-14 and its error-anatomy addendum of 2026-08-15 — the measurements
  §Context quotes); #1163 (the batch this lane belongs to); #786 (ADR-0045 §10's
  three surviving temporal deferrals, the adjacent question §5 draws the line
  against); #791 (cross-conversation episodic recall, whose budget question is a
  separate ADR's and is not taken here); ADR-0005 §1 (the four kinds, the shared
  envelope, `content` as the canonical rendering), §2 (`Provenance`); ADR-0008 §5
  (`Settings.timezone` as the temporal context's local calendar), §6 (no second
  timezone source); ADR-0030 §4 (`core`'s one UTC canonicaliser); ADR-0045 §1
  (one axis shipped deliberately; as-of deferred), §2 (the `Validity` window, and
  why it sits on the envelope rather than on `Provenance`), §3 (`last_updated` is
  transaction time), §6 (read semantics), §10 (the deferrals #786 carries);
  ADR-0074 §7 (the episode horizon), §8 (deleting a conversation); ADR-0077 §1 (the
  observer reads episodes it is handed), §2 (what it may propose, and the utility
  bar), §3 (the payload), §5 (evidence discipline; confidence is the producer's),
  §6 (a destroyed citation becomes a tombstone; the belief outlives its evidence);
  ADR-0088 §1 (citation forms); ADR-0089 §1–§3 (what is marked and what marks bind);
  ADR-0092 §3 (a source instant in our future is neither refused nor rewritten);
  ADR-0103 §9 (which event confirms a belief in each band); ADR-0106 §3 (a
  provenance field is computed by the component that selected the input set, never
  taken from the model); ADR-0109 §3 (unknown currency), §4 (what a producer
  supplies and who computes it); ADR-0112 §9 (no quantity joins the retrieval
  order); ADR-0128 §1 (every eligibility predicate binds before the ranking cut).

## Context

The scored benchmark pilot (#1029) measured a loss this ADR exists to answer. Of
LoCoMo's 1,540 answerable questions, **416** had a record citing the gold evidence
**in the answering prompt** and were still declined; the error-anatomy addendum
reads them and reports that "the distilled fact dropped the queried detail, dates
above all (116 of the 416 are temporal questions)", concluding that "distillation
strips temporal anchors — semantic records carry no event dates". The temporal
categories score accordingly: **1.6%** on LoCoMo category 2 and **0%** on
LongMemEval's temporal-reasoning slice. The sampled failure the addendum leads
with is the shape in one line — the question *"When did Caroline go to the LGBTQ
support group?"* (reference answer 7 May 2023), the gold-citing record in the
prompt reading *"Caroline is passionate about supporting the LGBTQ+ community and
finds meaning in helping create a more loving world"*, and the model's answer *"I
don't know."* The addendum's own verdict on that decline is that, given the record
it was shown, it is **rational**.

Stated at the product level, without the benchmark: a user asking *"when did I
last …"* cannot be answered from records that carry no event time. That is a
capability the accumulated user model is supposed to have and does not.

**The system holds the time and drops it at exactly one seam.** Every episode
carries `EpisodicMemory.occurred_at` — a required, capture-stamped instant — and
the observer is handed the episodes themselves (ADR-0077 §1). What reaches the
model is less: `learning/observer.py`'s batch renderer emits one line per episode
carrying the label and the episode's `content`, and nothing else; and the system
prompt closes with *"Do not include ids, confidence values, or timestamps; those
are assigned downstream."* So the producer that writes the belief sentence is both
**blind to the instants** and **told not to write one**. Nothing downstream can
recover what was never in the sentence.

**Four forces make this a decision rather than an implementation detail.**

1. **The time the belief needs and the time the system holds are different
   quantities, and the gap between them is the whole difficulty.** The pilot's
   sampled evidence is deictic almost throughout: *"I went to a LGBTQ support group
   **yesterday**"*, *"**Last weekend** I joined a mentorship program for LGBTQ
   youth"*, *"**Last Friday** I went to a council meeting for adoption"*, *"We even
   had a picnic **last week**!"* The episode's `occurred_at` is when the sentence
   was *said*; the event is displaced from it by an expression only a reader of the
   text can resolve. Neither half alone answers the question, and the prompt has
   never carried both halves at once.
2. **A structured field would have to be filled by somebody entitled to fill it,
   and nobody is.** A field filled from `occurred_at` records the observation's
   instant, which is a quantity the store already holds twice over — on the episode,
   and, as the latest over an evidence set, in `Provenance.last_confirmed_at`
   (ADR-0103 §9, ADR-0109 §4). A field filled from a date the model read out of the
   text is a model's claim installed in machinery, which this repository refuses on
   a standing rule: ADR-0106 §3 has such a value "computed by the component that
   **selected the input set**" and discards what the producer emitted, and
   ADR-0109 §4 restates it for the neighbouring instant. So the obvious schema
   change has no admissible producer, which is a fact about the decision rather
   than an implementation difficulty.
3. **An instant that *is* carried would answer the question wrongly if read as an
   event date.** `Provenance.last_confirmed_at` is populated on every distilled
   belief with the latest `occurred_at` among the cited episodes, and the pilot's
   harness renders each retrieved record through `model_dump_json()`, so that
   instant was in the answering prompt throughout. It is **currency** — "the most
   recent observation supporting it" (ADR-0103 §9) — and for a belief inferred
   across sessions it is the *last* of them, not the one the question asks about.
   A cheap-looking fix that surfaced it as the event date would convert declines
   into confidently wrong dates, which is worse than the measured failure.
4. **What the answering path actually reads is narrow.** `planning/planner.py`
   renders each retrieved record as one bullet carrying its kind, its provenance
   source and its `content` — nothing else. A field added to a record type, or an
   instant added to `Provenance`, reaches the assistant's own answer prompt only if
   a second change in `planning` renders it. The pilot's harness is more generous
   than the product here, so a decision tuned to the harness would measure well and
   ship nothing.

The forces against are real and are not waved away. A date in retrieval text
changes the embedded string, and the question that asks *for* a date contains no
date to match it — so the anchor is a small dilution paid on every record against
a gain concentrated on temporal questions, and the pilot has not measured that
trade. A resolved date can also be resolved *wrongly*, and a wrong date stated
confidently is a worse artefact than an absent one. §6 and §7 state both costs
and what would overturn the decision on them.

## Decision

### 1. The anchor is carried in the record's `content`, and no record type grows a field for it

`content` is already "a canonical text rendering of the record, used for lexical
and (later) embedding retrieval" (ADR-0005 §1), and it is already wholly
model-authored on a distilled belief: every word of the sentence is the observer
model's, gated afterwards by the evidence floor, the confidence function and the
`MemoryPolicy` (ADR-0077 §2, §5). A date inside that sentence adds no new
authorship — it is one more clause of a claim the system already treats as a
claim, rendered beside its provenance and its confidence to a reader who can
weigh it.

> **Normative.** The event time a distilled record carries is carried in that
> record's `content` and nowhere else. No field is added to `MemoryBase`, to any
> member of `MemoryRecord`, or to `Provenance` for this purpose; an implementing
> lane that concludes such a field is needed stops and takes a new ADR rather than
> adding one.

> **Normative.** No read-time predicate, eligibility rule, ordering, retention
> rule or store filter reads a temporal anchor. It is rendered text a reader
> weighs, never an input to machinery.

**Why a structured field is refused, stated as the difference that decides it.** A
field is read by machinery, and a wrong value in one is acted on silently: this is
what `Validity` does at the read cut (ADR-0045 §6, ADR-0128 §1), what `expires_at`
does to retention, and what `last_confirmed_at` does to currency. Nothing
mechanises `content`. The standing refusal to take a temporal value from a model
(ADR-0106 §3, ADR-0109 §4) is written about fields for exactly that reason, and
the second clause above is what keeps this decision from smuggling the same hazard
in under a different name — an anchor that no predicate reads cannot silently
hide, reorder or expire a record, whatever it says. That is also why the refusal
is marked rather than left as an assurance: it is the property that makes the
first clause safe, and a later lane could disobey it.

**And a field would not reach the answer.** `planning/planner.py`'s per-record
bullet carries the kind, the provenance source and the `content`. Choosing
`content` means the anchor reaches the assistant's own answering prompt with no
change in `planning` at all — the subsystem this lane's fence excludes — and
reaches the benchmark harness's prompt as well, since that renders the whole
record. Every other candidate needs a second lane in a second subsystem before it
answers a single question.

### 2. What the observation prompt shows, and what a belief may state

> **Normative.** The observation prompt states each episode's `occurred_at`
> alongside the label and the `content` it already carries for that episode,
> rendered in the deployment's configured local calendar — `Settings.timezone`,
> the value ADR-0008 §5 already gives the temporal context — and naming that zone.

> **Normative.** Where the evidence a proposed belief cites establishes a time —
> for an event the belief asserts, or for the onset or change of a state it
> asserts — the belief's `content` states that time.

> **Normative.** Where the cited evidence establishes no such time, the belief's
> `content` states none. An episode's `occurred_at` alone never supplies one: it
> records when something was said, not when what it describes happened, and a
> belief that is not about a datable event or state-change acquires no date by
> having been observed on a particular day.

> **Normative.** A temporal anchor never widens what may be proposed. ADR-0077
> §2's bar — a belief must be about the user and would change a later answer, and
> the exchange is not summarised — is applied unchanged, and the availability of a
> date is not a reason to propose a belief that bar would otherwise refuse.

**The first clause is the whole enabling change, and it is small.** The observer
already holds every `occurred_at` in the batch: `LearningObserver.observe`
snapshots them off the same frozen tuple it builds the labels from, and computes
`last_confirmed_at` from that snapshot. The instants are ours, deterministic, and
already egressed as part of the batch in every meaningful sense — showing them
adds one field per episode of data whose *content* is already in the prompt.
ADR-0004 §7's minimisation is satisfied rather than strained: this is the minimum
necessary context for the belief the stage asked for, and it is the batch's own
data rather than a second class of it, which is why §3's ruling ("the payload is
the batch and nothing else") admits it and only §3's enumerating sentence is
amended.

**The third clause is what stops the naive implementation.** The cheapest reading
of "carry the date" is to append the session's date to every belief — *"Caroline
is passionate about supporting the LGBTQ+ community (as of 7 May 2023)"*. That
would state a falsehood about a trait, pay the embedding dilution on every record
in the store rather than on the datable ones, and put a date beside beliefs where
a reader would take it for an event time. The clause refuses it in terms, and the
refusal is the operative half of this section.

**The fourth clause holds a line a reviewer should test.** The measured
ingestion loss is much larger than the measured anchor loss — 652 of LoCoMo's
answerable questions had gold evidence cited by no belief record at all — and the
temptation is to let this ADR buy some of that back by admitting event-shaped
beliefs the utility bar refuses. It does not, and §6 says what that costs.

### 3. A relative expression is resolved at distillation, never stored

> **Normative.** A time stated under §2 is stated absolutely — a calendar date, or
> a range bounded by one — and never as an expression relative to the moment of
> observation. Where the cited evidence gives the time only relatively, the
> producer resolves it against that episode's `occurred_at` **in the local calendar
> §2 renders it in**; where it cannot be resolved to a calendar anchor, no time is
> stated.

> **Normative.** A producer that has not been supplied the zone §2 names resolves
> no relative expression, and never substitutes a UTC calendar or a zone it chose
> for itself. As the one exception to §2's second clause, such a producer states no
> time for evidence that establishes one *only* relatively; a time the cited
> evidence states absolutely needs no calendar and is stated exactly as it would be
> with a zone in hand.

A stored belief reading *"joined the mentorship programme last weekend"* is worse
than one with no date at all: it is relative to an anchor the belief does not
carry, and the anchor is an episode that will not outlive it. Episodes carry a
finite retention horizon (ADR-0074 §7), a user may destroy a conversation at any
time (ADR-0074 §8), and ADR-0077 §6 is built on the premise that the belief
survives the destruction of its evidence with a tombstone rather than a rewrite.
So an unresolved deixis is a dangling reference of exactly the kind this system
already refuses to create — and resolving it is cheap and possible only at
distillation, which is the one moment both halves are in hand.

**The calendar is local, and that is load-bearing rather than cosmetic.**
`EpisodicMemory.occurred_at` is a `UtcInstant` — `core`'s one canonicaliser
rebuilds every instant in UTC (ADR-0030 §4) — while *"yesterday"* is said in the
speaker's calendar and means whatever their local day boundary makes it mean. For
any deployment west of UTC, every evening utterance sits on the following UTC day,
so resolving *"yesterday"* against the UTC calendar is wrong by a day for a fixed
and non-trivial fraction of all evidence, silently and in one direction. Naming
the local calendar costs nothing: `Settings.timezone` is an IANA name validated at
load, and `app/composition.py` already hands it to the temporal context and to the
notification policy under the standing rule that §6 of ADR-0008 "introduces no
second timezone source". The observer becomes the third consumer of the same
value, not a fourth source of truth.

**The second clause is a refusal, and it is what keeps the first honest.** A
producer built without the zone has two tempting fallbacks — UTC, or the host's
locale — and both would state a calendar date the deployment never authorised, on
text a reader takes at face value. Stating nothing is the honest answer over an
unknown calendar, and it is the same posture ADR-0109 §3 takes for an unmeasurable
currency: unknown is a state, not a reason to invent a value.

**It is scoped to the resolution and not to the anchor, because only the
resolution needs a calendar.** Evidence reading *"I went to the gym on 7 May
2026"* establishes a date that no zone is required to carry, and §2's second clause
requires it to be stated; a blanket "no zone, no time" would make that input
unsatisfiable under both sections at once. So the refusal reaches exactly the
inference that would be unsound without a calendar — *"yesterday"* against an
instant — and reaches nothing else. Where it does bite, §2's third clause is
already the right outcome by a different route: the producer holds no time it is
entitled to state.

**One residual is named rather than closed.** The configured zone is the
deployment's, not a record of where the user was when they spoke, so a user who
travels — or a deployment whose zone is set wrongly — shifts an anchor by up to a
day. That is the same bounded error the paragraph below admits for a
mis-resolution, it is strictly smaller than the error UTC resolution guarantees,
and closing it would need a capture-time zone on the episode, which is contract
surface with no consumer and is filed in §8 rather than taken here.

**A resolution can be wrong, and that is a distillation error like any other.**
The producer is reading cited text against a system-supplied instant, which is
what distillation *is*; a mis-resolution yields a wrong sentence, carrying the
producer's sub-1.0 confidence and its citations, rulable by the policy, visible in
`assistant beliefs` and destroyable by `forget`. It is not a corrupted field, and
nothing reads it as one (§1). The alternative on the table is the measured one:
1.6% and 0%.

**Precision follows the evidence and is not manufactured.** LoCoMo's own reference
answers are themselves bounded rather than exact — "The week before 9 June 2023",
"The weekend before 17 July 2023" — and a belief that states a week or a month is
answering the question. What the clause forbids is a *relative* anchor, not an
imprecise one.

### 4. `last_confirmed_at` is currency, and no surface renders it as an event time

> **Normative.** No surface, prompt renderer or consumer presents
> `Provenance.last_confirmed_at` as the time of an event the record's `content`
> describes.

ADR-0103 §9 rules what that instant measures — the most recent event that
*confirmed* the belief, which for a `DERIVED` record is "the latest `occurred_at`
among the episodes `Provenance.evidence` cites" — and ADR-0109 §4 has the producer
compute it from the set it selected. It answers *"does the assistant still believe
this?"* Read as an event date it is wrong in a specific and repeatable way: it is a
maximum over an evidence set, so for any belief supported by more than one episode
it names the latest supporting session rather than the event asked about, and for
a belief reinforced later it moves while the event does not.

This clause exists because the field is *already in the answering prompt* under
the pilot's harness and would be the cheapest imaginable "fix" — rename nothing,
render the instant, watch the temporal categories move. They would move by
converting rational declines into confident errors, and the pilot's own decision
rule would score that as an improvement. Foreclosing it is the point.

**The two instants coexist and are not reconciled here.** A belief may carry an
anchor in its content and a `last_confirmed_at` in its provenance, and the two may
differ — the event happened in May and the belief was confirmed again in July.
That is not drift; it is two facts, and ADR-0109 §8's reasoning about
`last_confirmed_at` and `last_updated` disagreeing after a fold applies here
unchanged.

### 5. This is not a validity window, and #786 is untouched

Issue #786 carries ADR-0045 §10's three surviving temporal deferrals: as-of
retrieval, the full transaction-time axis, and reconciling
`SemanticMemory.valid_until` with the envelope window. All three are about **when
a record is operationally live, or what the system believed when**. This ADR is
about **when the thing the content describes happened**. The two are conflated
easily and must not be, so the line is drawn concretely rather than asserted:

- **Nothing reads the anchor** (§1's second clause), so it bounds no eligibility,
  joins no ordering, and closes no window. `Validity` remains the sole valid-time
  axis and it is set operationally by supersession (ADR-0045 §2).
- **Closing a window does not change an anchor, and an anchor does not close a
  window.** A retired belief keeps the date its content states; the date passing
  says nothing about whether the belief is live.
- **"When did I last go to the gym?" is not an as-of query.** It is a question
  asked of the live belief set *now*, whose *answer* happens to be a date. #786's
  as-of deferral is about reads that ask what was believed on an earlier day, and
  this ADR creates no such consumer — which is precisely the trigger #786 states
  ("(1) and (2) fire when something wants temporal retrieval"). It is not fired.
- **`SemanticMemory.valid_until` is a third thing again** — a content-declared
  world-expiry, "the author says this fact self-expires on date X" (ADR-0045 §2).
  It says when a fact *stops* being true; an anchor says when an event *happened*.
  This ADR neither populates it nor reconciles it, so #786's third deferral stands
  exactly as filed.

**Episodic retrieval is a different lane's question and is not taken here.**
Whether the answering turn may retrieve raw episodes beside beliefs is #791's
deferred budget-and-consumer question. Raw episodes carry `occurred_at` and would
supply event times by a different route; that route is complementary to this one
and substitutes for neither, since it routes around distillation rather than
fixing it, and a store under a finite episode horizon has no episodes to retrieve.
Nothing in this ADR presumes either answer to it.

### 6. What this does not buy, stated at the same resolution as what it does

The measured 416 is not 416 dates waiting to be restored, and the honest scope is
narrower than the headline.

- **A trait generalised over many episodes gains nothing, and the ADR's own
  leading example is one of them.** *"Caroline is passionate about supporting the
  LGBTQ+ community"* asserts no event and no dated state-change, so §2's third
  clause gives it no time — and the question *"When did Caroline go to the LGBTQ
  support group?"* stays unanswered by that record. What was lost there is the
  *event*, not merely its date, and recovering it is the ingestion question this
  ADR does not touch.
- **A state with a datable onset does gain.** *"Caroline mentors LGBTQ youth …
  through a mentorship program"*, cited to *"Last weekend I joined a mentorship
  program for LGBTQ youth"*, is a state whose onset the evidence dates; under §2
  and §3 the belief states it, and *"When did Caroline join a mentorship
  program?"* becomes answerable from the record that was already in the prompt.
- **The 116 temporal questions inside the 416 are the ceiling, not the floor's
  complement.** They bound what this decision could recover on that corpus at all,
  and the bullets above say only some of them are the datable-state shape.
- **Ingestion recall is untouched.** LoCoMo's 652 never-distilled questions and its
  56.7% ingestion recall are a separate finding with a separate cause (observation
  tuned for first-person dialogue against a third-person corpus), recorded on #1029
  as a documented validity limitation. Nothing here moves it.

Saying this in the ADR rather than in the write-up is deliberate: the next lane
reads this document as its authority, and a decision that implied it would rescue
the whole 416 would be measured against a claim it never made.

### 7. What the implementing lane owes, and what it may not touch

The lane is `learning`'s: the batch renderer and the system prompt in
`learning/observer.py`, plus tests — and the one wiring line in
`app/composition.py` that hands the producer `Settings.timezone`, beside the
injected clock and id factory it is already constructed with. That is the same
composition-root shape every injected seam in this system takes, and it is named
here so the lane does not read §1's "no contract surface" as forbidding it.

> **Normative.** The implementing lane changes no file under
> `src/ai_assistant/core/`. It adds no field, no Protocol and no conformance
> clause; a finding that one is needed is grounds to stop and take a new ADR, not
> to widen the lane.

> **Normative.** The lane pins, as tests: that the rendered observation batch
> carries every episode's `occurred_at` in the configured zone, including an
> episode whose UTC and local calendar dates differ; that a producer built without
> a zone renders none; that a value a model emits for any structured temporal field
> is discarded rather than installed; and that the producer's existing refusals —
> the evidence floor, the label mapping, the confidence function — are unchanged by
> the prompt edit.

**The prompt's existing timestamp ban is narrowed, not lifted, and the narrowing
is the delicate part.** `learning/observer.py`'s system prompt says *"Do not
include ids, confidence values, or timestamps; those are assigned downstream"* —
one sentence doing two jobs. It correctly forbids the model to supply values for
*fields* the producer computes, which is ADR-0106 §3 and ADR-0109 §4 stated to the
model, and it incorrectly forbids a date in the belief *sentence*, which no
ratified decision requires. The lane rewrites it so the first job survives intact
and the second stops; the second test clause above is what keeps the first job
verifiable independently of the prompt's wording, since a prompt instruction is
not an enforcement point and never was.

**What is not unit-testable is said plainly.** Whether the model actually writes
the dates it is now shown is behavioural, and no test in this repository can
assert it. The obligations above are the mechanical half; the behavioural half is
measured by the re-run (§Consequences), and the ADR is written so that a lane
cannot mistake a green suite for a discharged decision.

### 8. What this ADR does not decide

- **Whether a datable milestone warrants a belief of its own.** ADR-0077 §2's bar
  refuses "what merely happened" on the premise that the episode records it; that
  premise weakens under a finite episode horizon and vanishes under
  `episode_retention` of none. Filed, not answered — it is the ingestion question
  (§6), and it would widen what the observer may propose, which is a decision about
  the gate's input and not about a record's text.
- **Any retrieval-side use of time.** Temporal scoring, recency weighting, or a
  date-aware query decomposition are all ordering questions, and ADR-0112 §1 rules
  that no quantity joins the ordering. Nothing here proposes one.
- **The episodic retrieval budget** (§5, #791). A separate ADR's.
- **#786's three deferrals** (§5). Untouched, and this ADR fires none of their
  triggers.
- **A format for a stated date.** §3 fixes that it is absolute, bounded and in the
  configured local calendar; the words are the model's, as the rest of the sentence
  already is.
- **A capture-time zone on the episode.** §3's residual — the deployment's zone is
  not a record of where the user was — would be closed by stamping the speaker's
  zone at capture, which is a field on `EpisodicMemory` and therefore contract
  surface. There is no consumer beyond a bounded-by-a-day improvement to this
  anchor, so it is filed on the same discipline §1 applies to a temporal field:
  ADR-0045 §1, ADR-0028 §7 and ADR-0072 §7 each declined surface ahead of a
  consumer, and this ADR does not make an exception for its own convenience.
- **Whether `SemanticMemory.valid_until` should ever be populated by the
  observer.** No producer sets it today; this ADR adds none.

## Consequences

- **A belief can answer "when", where the evidence dated it.** That is a
  capability the accumulated user model is meant to have; the pilot measured it at
  1.6% and 0%, and §6 bounds how much of that this decision can recover.
- **No contract surface moves.** `src/ai_assistant/core/types.py` and
  `src/ai_assistant/core/protocols.py` are untouched, every construction site is
  unaffected, no migration is owed, and no triad is due. The wave-2 lane is a
  `learning` change plus tests. This is the cheapest available shape and it is a
  consequence of the argument in §1 rather than the reason for it.
- **Retrieval text changes, and the effect is unmeasured.** A date in `content`
  is embedded with it. The gain is concentrated on questions that name or ask
  about a time; the cost is a dilution paid on the datable records. The pilot's
  own re-rank data says ranking is the small tail — 277 of LoCoMo's errors against
  652 ingestion losses, with none of the gold records ranked 1–5 — so the expected
  magnitude is small, but "expected" is the operative word.
- **Two dates now coexist per belief in the general case, and they have different
  authors** — a model-authored anchor in the content, and a system-computed
  instant in the provenance, `last_confirmed_at` being taken from the citations
  the producer resolved and never from the model (ADR-0109 §4, §4 above). That
  split of authorship is the decision, not an accident of it: §1 puts the
  model's claim where nothing mechanises it, and leaves the mechanised field
  computed as it always was. §4 keeps the two apart at every surface. This is a
  known cost of
  not conflating currency with event time, and it is the same shape as the two
  `valid_until` notions ADR-0045 §2 chose to leave coexisting.
- **A new failure mode is admitted deliberately: a confidently stated wrong date.**
  §3 argues why it is the right trade and §1's second clause bounds its blast
  radius to text. It is called out here so that a re-run showing wrong dates is
  read as this decision's predicted cost rather than as a surprise.
- **Revisit if** the combined re-run (#1163's `bench-pilot-2`) leaves the temporal
  categories flat, which would mean the anchor is not reaching the answer and the
  cause is elsewhere; if overall accuracy falls while temporal accuracy rises,
  which is the dilution cost exceeding the gain; if a consumer arrives that wants
  to *filter or order* by event time, which is the trigger for revisiting §1's
  refusal of a field, and which would be a new ADR under §1's first clause; or if
  #791's episodic retrieval lands and supplies event times by a route that makes
  the anchor redundant.
- **This ADR merges before the implementing lane is briefed** — not because
  ADR-0015 §5 compels it (the header explains why it does not) but because #1163
  sequences it that way and the lane has no authority for §7's obligations until
  this text is merged. That is why §7 states the deliverables and §6 states the
  limits: the merged document is what the lane reads.

## Alternatives considered

- **A structured event-time field on the record types** — `event_at` on
  `SemanticMemory`, or an envelope field beside `validity`. **Rejected in §1**, on
  three independent grounds, any one of which is sufficient. *No admissible
  producer*: filled from `occurred_at` it duplicates a quantity the store already
  holds and answers the wrong question (§Context force 1); filled from the model it
  installs a model's claim in machinery, against ADR-0106 §3 and ADR-0109 §4. *It
  reaches no prompt*: `planning/planner.py` renders kind, source and `content`, so
  the field would need a second lane in a second subsystem before answering a
  question. *It is surface bought ahead of a consumer*: nothing would read it, and
  this repository has declined exactly that trade repeatedly — ADR-0045 §1 on
  as-of retrieval, ADR-0028 §7 on batch ingestion, ADR-0072 §7 on a read's
  signature.
- **A second instant on `Provenance`, beside `last_confirmed_at`.** Rejected in
  §1 and §4. `Provenance` is about trust and source and its fields are the
  producer's (ADR-0045 §2); a second temporal instant beside a currency instant
  invites precisely the confusion §4 forecloses, and a consumer would have to read
  the right one of two. It also inherits the no-admissible-producer objection
  whole.
- **Render `last_confirmed_at` into the answering prompt as the event date.**
  Rejected in §4, and refused there rather than merely declined. It is the cheapest
  change available and it would move the measured number by turning rational
  declines into confident errors, because the instant is a maximum over an evidence
  set rather than the event's own time.
- **Let the observer propose `EpisodicMemory` records for datable events.**
  Refused outright: ADR-0077 §2 rules that only the deterministic capture path that
  was present when something happened may write an episode, and that "a
  model-authored episode would be a fabricated event wearing the type reserved for
  witnessed ones" which later beliefs would then *cite as evidence*. Nothing in the
  measured gap justifies reopening that.
- **Retrieve raw episodes beside beliefs so the dated turn reaches the prompt.**
  Out of scope by §5 and a separate ADR's question (#791). On the merits it is
  complementary rather than substitutive: it routes around distillation instead of
  fixing it, and it supplies nothing in a deployment whose episode horizon has
  passed — which is the deployment the belief store exists for.
- **Extract the date at read time, from the cited episodes, when a question looks
  temporal.** Rejected: it re-reads evidence that may be expired or destroyed
  (ADR-0074 §7, §8), which is the state ADR-0077 §6 handles with a tombstone rather
  than a re-derivation; it puts a model call on the answering path for a value that
  was free at distillation; and it makes the answer depend on retention in a way
  the belief is designed not to.
- **Append the observation's date to every distilled belief.** Rejected by §2's
  third clause. It states something false about a trait, pays the embedding cost on
  every record rather than on the datable ones, and presents an observation instant
  where a reader will read an event time — the same error §4 refuses one field over.
- **Resolve relative expressions against the UTC calendar, since `occurred_at` is
  already UTC.** Rejected in §3, and it is the shape the first draft of this ADR
  admitted by saying nothing. `occurred_at` is a `UtcInstant` by ADR-0030 §4's
  canonicalisation, but *"yesterday"* is said in the speaker's calendar: for any
  deployment west of UTC every evening utterance falls on the next UTC day, so the
  resolution is wrong by exactly one day for a fixed fraction of all evidence,
  always in the same direction, and stated as a calendar date a reader will trust.
  A bounded, systematic error is worse than a random one here, because it is the
  kind that survives a spot check. `Settings.timezone` closes it at no cost.
- **Require an ISO-8601 date in the content.** Rejected in §3 and §8. It buys
  machine-readability nothing reads (§1's second clause), reads unnaturally in a
  sentence that a model consumes as prose, and would force a false precision on
  evidence that establishes a week or a month — which the corpus's own reference
  answers show is often all there is.
- **Do nothing, and treat the 416 as an ingestion problem.** Rejected: 116 of them
  are temporal questions whose gold record *was in the prompt*, so retrieval and
  ingestion both succeeded and the loss is entirely at distillation. Folding it into
  the ingestion finding would attribute a measured failure to the wrong stage and
  leave the one cheap fix unmade.
