# 162. What the user tells the assistant is recorded, and selectivity moves to retrieval and forgetting

- Status: Proposed
- Date: 2026-08-19
- **Not a substantive contract ADR; contract-surface for the review set, and the
  two are different questions.** [ADR-0015](0015-simplify-the-agent-workflow.md) §5
  defines a substantive contract ADR as one "adding or changing a Protocol or a
  `core/` type crossing subsystem boundaries", and nothing below adds or changes
  either — no `Observer` member moves, no field of `core/types.py` moves, and the
  implementing lane owes no triad. What is true is narrower: this ADR decides what
  the `Observer` contract's shipped implementation may propose, which is the
  behaviour [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) §2
  ratified for it, and it re-values two composition-root cardinality controls. So
  the required set is adversarial **and** architecture, on
  `CONTRIBUTING.md` → "Stop when the required reviews are green"'s ground that a
  change is contract-surface "when it is the ADR deciding that surface, even though
  such a PR is prose only". Docs only, and **no code changes with it**: the
  implementation is its own lane (#1210's 2.4), which needs this text as its
  authority.
- **Partially supersedes on ratification:**
  [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) §2, in two named
  scopes and no others.

  **The warrant bar**, and only as it reaches an episode recording what the user
  said to the assistant. The replaced sentences are *"The bar for proposing at all
  is durable usefulness, not interestingness"*, *"A proposal is warranted only when
  the belief is **about the user** and would change a later answer — a preference, a
  durable fact about them or their world, a workflow they follow"*, and *"Summarising
  the exchange is the failure mode: it turns the belief store into a second
  transcript, at indefinite retention, behind the surface that answers 'what do you
  believe about me'"*. §1 below replaces them for that class of episode and §2 leaves
  them standing, unchanged and in force, for every other.

  **The proposal bound's value and its ground.** The replaced clauses are
  *"`Settings` gains `observation_max_proposals: int`, **positive, defaulting to
  5**"* — the figure only — and *"Five is the selectivity bar above, in numbers: a
  batch that genuinely yields more durable beliefs than that is a batch worth
  observing twice"*. §6 sets the default to 40 and states a different ground for it.
  That the bound exists, that it is positive, that excess is discarded rather than
  queued, and that it binds the producer's **return value** are untouched.

  [ADR-0070](0070-amendment-and-supersession-rules.md) §1's test decides the form
  and decides it against an amendment on both scopes: an amendment is available
  "only when the amendment changes no decision", such that a reader acts
  "**identically** before and after", and "a change to what was decided is anything a
  reader would act on differently". A reader holding only ADR-0077 builds an observer
  that refuses to record what merely happened and caps its return at five. Both are
  precisely what §1 and §6 require it to stop doing. So this takes ADR-0070 §3's
  partial-supersession form and §4's status vocabulary, and ADR-0077's `Status` line
  accumulates a third pair beside the ADR-0084 and ADR-0156 ones rather than
  replacing them.

  **What is not replaced is nearly all of ADR-0077, including three clauses of §2
  itself.** The three kinds an observer may propose and its refusal to propose an
  `EpisodicMemory`; the two epistemic steps and ADR-0072 §3's test between them;
  `sensitivity` as `PERSONAL` on every proposal, with the observer-side category
  taxonomy declined — all stand. So do §1 whole, §3 whole (as ADR-0156 already
  partially superseded it), §4, §5, §6, §7, §8, §9, §10 and §11.
- **Partially supersedes on ratification:**
  [ADR-0156](0156-a-distilled-belief-states-its-event-time-in-its-content.md) §2's
  **fourth clause**, and only in the respect that it makes ADR-0077 §2's bar the
  standing test. The clause is *"A temporal anchor never widens what may be
  proposed. ADR-0077 §2's bar — a belief must be about the user and would change a
  later answer, and the exchange is not summarised — is applied unchanged, and the
  availability of a date is not a reason to propose a belief that bar would otherwise
  refuse."* For an episode §1 reaches there is no such bar to apply unchanged, so a
  reader holding only ADR-0156 applies a test that is no longer there — ADR-0070 §1's
  test again, and again against the softer form. What the clause was *for* survives
  and is restated in §4's terms: a date is neither a reason to record something the
  intake rule would not record, nor a reason to withhold something it would.
  ADR-0156 §2's first three clauses, §3, §4, §5, §6, §7 and §8 stand — and §2's third
  clause, which refuses a belief a date it did not earn, carries more weight after
  this ADR than before, because §1 admits far more datable records.
- **Partially supersedes on ratification:**
  [ADR-0160](0160-the-episodic-bound-meets-the-belief-budget-and-post-hoc-attribution-replaces-the-ablation-arm.md)
  §1, in both its clauses and in no other scope. The value clause — *"The configured
  episodic bound is **15**"* — becomes 10 under §9. The evidence clause — *"The
  episodic bound moves on the post-hoc attribution §3 requires, read off a scored
  benchmark run"* — is widened by §9 to admit the measured retrieval reach #1210's
  probe reports, because that is the quantity the attribution is a proxy for and this
  ADR moves the bound on it before a scored run exists. The rest of that clause —
  *"No separately registered arm is owed for it"* — stands and is relied on. ADR-0160
  §2 (parity permitted, ADR-0158 §3's ceiling standing), §3, §4, §5, §6 and §7's
  mechanism are untouched; §9 satisfies the ceiling with slack rather than at it.
- **Amends, as an appended dated note:**
  [ADR-0099](0099-one-hub-one-principal-and-a-household-member-is-a-subject.md)'s
  Context sentence *"So `assistant observe` is **not** authorised to write about
  third parties, and nothing here authorises it"* — narrowed, not falsified, under
  [ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md) §1's
  second limb. §3 below states exactly what moves and what does not, and
  [ADR-0100](0100-a-belief-states-whom-it-is-about-and-the-label-resolves-to-nothing.md)
  §5's refusal — an observer proposal states no subject — is untouched by this ADR.
- **No contract surface moves.** No Protocol gains or loses a member, no
  `core/types.py` field changes, no `Settings` field is added or removed. `Settings`
  gains no field for §7's overlap either: §7 leaves that placement to the lane.
- **Ratified on `CONTRIBUTING.md` → "Finishing an ADR PR", which is where that
  sequence is argued rather than re-argued here.** This ADR is drafted, reviewed and
  revised as `Proposed`; its status is flipped only once **both** required lenses —
  adversarial and architecture, per the bullet above — return clean on one tree, and
  that set is re-run on the flipped tree. A finding arriving after a flip returns it
  to `Proposed` and is folded there, per that block's step 3. The tense is
  deliberate: written prospectively, this bullet is true in both states the document
  passes through, so the ratifying commit changes the `Status` line and nothing else.
- Refs #1210, #1029, #1179, #1185, #545, #1162, ADR-0077, ADR-0156, ADR-0158,
  ADR-0159, ADR-0160, ADR-0100, ADR-0121

## Context

ADR-0077 gave the observer a bar and a reason for it. The reason was that a
producer emitting one record per turn "turns the belief store into a second
transcript, at indefinite retention", and the bar was the producer-side half of
VISION §Principle 2's "remember selectively… avoid preserving sensitive or
incidental details without justification" — the half "a gate cannot enforce,
because a policy judging one proposal at a time cannot see that all twenty of them
are a retelling". Nothing about that argument was wrong. What has changed is that
the cost of the bar is now measured, and it is the largest single loss in the
system.

**What pilot 4 measured.** On the scored LoCoMo run from `bench-pilot-4`
(#1029, 1,986 questions graded, headline 71.8%), gold evidence was cited by some
belief record for 60.7% of answerable questions with a gold mapping — so **39.3%
of them had gold evidence that no belief record cited at all**. The anatomy calls
this "the ingestion-coverage loss… now the largest memory-side bucket", and it is
not a ranking failure: an offline re-rank over the kept stores puts belief recall
saturated at that same 60.7% ceiling, "the ceiling of what its distilled records
cite at all". No retrieval budget reaches a fact that was never distilled.

**The bar was not being enforced by the cap.** #1029's pilot-4 configuration ran
`observation_max_proposals` at 15 through the harness environment, against a
shipped default of 5, and `discarded_over_limit` was 0 on every conversation. The
probe reports the corresponding rate as **3.5 proposals per pass**. The observer
was refusing material on the bar, with room to spare — which is the bar doing
exactly what it was written to do.

**What the probe measured** (#1210, Phase 0.1, 2026-08-19; three LoCoMo
conversations re-ingested from `bench-pilot-4` with the observation prompt's head
replaced by a complete-intake head and the cap raised to 60; retrieval reach only,
no answering and no judging; answerable questions n=430):

| limit *K* (beliefs = episodes) | control beliefs | complete beliefs | control union | complete union |
|---|---|---|---|---|
| 5 | 31.2% | 55.1% | 57.2% | 66.0% |
| 15 (pilot-4) | 36.0% | **69.5%** | 71.9% | **79.8%** |
| 30 | 37.4% | 77.9% | 78.1% | 88.6% |
| 50 | 38.8% | 81.2% | 83.0% | 91.6% |

Three readings, and the third is the one that decides. Beliefs alone under complete
intake reach at 15 what beliefs *and* episodes reached under the bar (69.5% against
71.9%). The control's belief curve is flat — 36% to 39% from *K*=15 to *K*=50 —
because it has run out of records to return, while the complete curve keeps
climbing. And belief-slot redundancy at 15 falls from 15% to **4.6%**: the extra
records are not restatements of what was already there. Intake was the store's
content problem, and the 0.2 offline bench confirms it from the other side —
re-ranking the same stores with MMR, hybrid BM25 and exchange-unit retrieval moves
reach by at most 1.5 points where intake moved it by 8 to 13.

**The measured cost of removing the bar.** Beliefs written per conversation
117→286, 98→263, 111→306 — about **2.6×** — with preferences almost flat (38→46,
20→27, 23→36). The growth is event and semantic records: what the user said
happened. Proposals per pass 8.7 / 9.1 / 9.0 against a cap of 60 that never bound.
Gold-turn coverage by any belief rose from 52% to about 74% of gold turns at
question level.

**The owner ruled the direction on 2026-08-17/18** (#1210): what the user says to
the assistant is remembered by default — the act of telling the assistant is the
signal — and the selectivity moves to retrieval and to forgetting. This ADR is that
ruling written down, with the probe's numbers where the ruling needs one.

**What makes it a decision rather than a tuning change.** Three things. It replaces
a ratified producer-side rule with its opposite for one class of input, so it has to
say exactly which class and what keeps the old rule (§2). It accepts, deliberately,
the very outcome ADR-0077 §2 named as the failure mode, which is only defensible if
the thing that pays for it is named and owed rather than assumed (§5). And it moves
two cardinality controls one of which is fixed by a ratified clause (§9).

## Decision

### 1. Intake is complete for what the user tells the assistant

> **Normative.** For an episode recording what the user said to the assistant, the
> observation stage proposes one record for each distinct thing the user stated that
> a later question could ask about — an event that happened, a person, place,
> organisation or thing named, a durable fact, a preference, a workflow — **up to the
> per-pass bound §6 sets**, which is the one exception and which §6 makes visible when
> it binds. Pure conversational filler is what it passes over, and is the only thing
> it passes over.

> **Normative.** That clause replaces ADR-0077 §2's warrant bar for such an episode.
> That a thing merely happened, that it may not change a later answer, and that
> recording it makes the pass read as a retelling of the exchange are no longer
> grounds to refuse a record.

> **Normative.** One record states one thing. A record combining several distinct
> facts or events into one sentence is not the compliant form of this section: the
> unit is the thing a later question could ask about, because that is the unit
> retrieval returns.

> **Normative.** ADR-0077 §5 stands whole for a record proposed under this section.
> It cites at least one episode of the batch by a label the producer maps to a store
> id; an `INFERRED` record rests on at least two distinct episode ids; confidence is
> the producer's deterministic function of the step and the support count; and a
> record left citing nothing is discarded and counted.

**The signal is the telling, and that is the whole argument.** ADR-0077 §2's bar
asks the observer to judge whether a thing is worth believing. Under it the observer
is a filter, and the measurement says the filter's false-negative rate is the
system's dominant loss. The replacement asks a question the observer can actually
answer from the batch in front of it: *did the user say this?* The user chose to say
it to an assistant whose stated purpose is to remember them; treating that choice as
insufficient evidence of worth is the system second-guessing the one party entitled
to decide.

**"Proposing nothing is a perfectly good answer" is not repealed; it is relocated.**
It remains the right answer for a batch that is only filler — a greeting, an
acknowledgement, a restatement of the assistant's own last line. What it stops being
is the answer to a batch full of things that happened.

**What does not move, listed because a replacement of a bar invites over-reading.**
The observer still proposes only `SemanticMemory`, `PreferenceMemory` and
`ProceduralMemory` and never an `EpisodicMemory` (ADR-0077 §2) — §4 is where that
bites. It still takes one of the two epistemic steps on ADR-0072 §3's test, and the
`INFERRED` floor of two distinct episodes is unchanged, which matters more rather
than less: complete intake multiplies the `OBSERVED` population, and a generalisation
from a single instance is exactly the failure ADR-0005 §Context named. It still
stamps `PERSONAL` on every proposal and declines a category taxonomy. The prompt is
still identity-free and still carries the batch and nothing else (ADR-0077 §3, as
ADR-0156 partially superseded it). The gate still rules on every proposal, one at a
time, and the user can still read and destroy any of it — which is the sentence in
VISION §Principle 2 this ADR relies on where it stops relying on the other one.

**The half of VISION §Principle 2 this gives up, stated plainly.** "Remember
selectively" was implemented at intake and is not implemented at intake any more.
§5 is where it goes, and §5 is owed rather than shipped; the interval between them
is a real, accepted regression in that principle, not a redefinition of it.

### 2. What §1 reaches, and what keeps the bar

> **Normative.** §1 reaches an episode whose content is what the user said to the
> assistant, and no other episode. An episode a reader ingested (ADR-0097) or a
> sensor captured (ADR-0094) keeps ADR-0077 §2's bar exactly as ratified.

> **Normative.** Which rule governs a pass is a property of the batch the selecting
> stage handed the producer, never of a line in the prompt or of a field the producer
> reads. A batch never mixes the two classes.

> **Normative.** ADR-0077 §3's payload is untouched by this section. Nothing about
> the user, no existing belief, no profile, no context facet and no plan enters the
> prompt to carry the distinction.

**The asymmetry is the ruling, and it is not a compromise.** The user choosing to
tell the assistant something is a *speech act directed at the assistant*. A calendar
entry a reader ingested, a room a microphone was in, a mail file a fetcher replaced
whole — none of those is the user choosing to tell the assistant anything, and the
argument in §1 does not reach them. ADR-0077 §2's bar is the right rule for content
that arrives whether or not the user meant it to, and it keeps it. A later ADR may
revisit that when there is a sensor with a measurement behind it; nothing here
forecloses it and nothing here invites it.

**Why the class rides with the call rather than with the record.** The observer
cannot compute the class from an `EpisodicMemory` it is handed: capture stamps
`MemorySource.OBSERVED` on every episode it writes, `participants` is left empty by
design, and no field distinguishes a told episode from a sensed one. Putting the
distinction in the prompt would breach ADR-0077 §3 and hand a model a fact it could
be misled about. So it is the selecting stage's, which is where ADR-0077 §1 already
put selection and for the same reason — "the scope of observation" is a property of
a ratified seam rather than of a producer's code.

**This binds no code today, and the check is cheap to state.** `EpisodicMemory` is
constructed at exactly one site under `src/` — `orchestration/conversations.py`'s
`ConversationLifecycle._episode`, on the conversation capture path. There is no
second producer of episodes, so there is no batch that could mix classes and no lane
owes an implementation for the second clause. It is written now so the widening does
not silently reach the first sensor that arrives: a rule stated only after the
sensor exists is a rule stated after the code that would have broken it.

### 3. The subject axis does not move, and the volume on it does

> **Normative.** This ADR opens no route by which an observer states `about_person`,
> and no lane implementing it may add one. ADR-0100 §5's refusal — an observer
> proposal states no subject, one that would is not proposed and is counted in
> `ObservationOutcome.discarded_unusable`, and the shared conformance suite pins it —
> is untouched and stands.

**What ADR-0099 said, and what is now true.** ADR-0099's Context reasons that
"`assistant observe` is **not** authorised to write about third parties, and nothing
here authorises it", on ADR-0077 §2's warrant sentence. That sentence's own scope was
already wider than the phrase suggests — it warrants "a durable fact about them **or
their world**" — and ADR-0099 says in terms that the boundary is unsettled: "whether
the owner's partner's seat preference is a fact about the owner's world is a question
that sentence does not settle and no field records". §1 pushes hard on exactly that
unsettled boundary. A user who tells the assistant that their friend's daughter got
into Berkeley now has that recorded, and it is a record whose grammatical subject is
not the user.

**Nothing about the axis changes, and that is deliberate.** Such a record states no
subject, because ADR-0100 §5 forbids the observer to state one and the shipped
envelope has no subject key to state it with. ADR-0100 §3's reading then applies
unchanged: an unstated subject is read as the owner's own, "about the owner or the
owner's world". So the record is not mislabelled — it is unlabelled, exactly as every
observer record has been since ADR-0100, and it sits in the population ADR-0099's
Context already describes as accumulating "deliberately, with no way to tell them
from the rest".

**What changes is the size of that population, and that is worth stating rather than
discovering.** The probe's 2.6× is concentrated in semantic and event records, which
is precisely where third-party content lives. ADR-0099 §5 fires the subject axis on
"anything that has to *check* ADR-0077 §2's 'about the user' rule rather than instruct
it"; this ADR does not fire it, because it removes the rule for told episodes rather
than needing to check it. What it does is make the *deletion and export by subject*
consequence ADR-0099 §5 defers materially more valuable, and that is filed as an issue
rather than decided here (§11).

**ADR-0100 §5's first clause is not falsified.** It reads "ADR-0077 §2's warrant rule
is unchanged **by this ADR**" — a claim scoped to ADR-0100's own change, true when
written and true now. A later ADR changing the rule does not make ADR-0100's statement
that *it* did not change it retroactively false, which is the distinction ADR-0077's
own ADR-0084 note draws about its Consequences.

### 4. An event is recorded as a belief about what happened, and the episode is still the event

> **Normative.** A record proposed under §1 for an event is a `SemanticMemory`
> stating what happened and, where the cited evidence establishes it, when — under
> ADR-0156 §2's second clause and in ADR-0156 §3's absolute form. No new record kind
> is created and ADR-0077 §2's refusal to propose an `EpisodicMemory` is why.

> **Normative.** A date is neither a reason to record something §1 would not record,
> nor a reason to withhold something §1 would. This restates ADR-0156 §2's fourth
> clause in §1's terms, replacing its reference to a bar §1 removes; ADR-0156 §2's
> third clause — where the evidence establishes no time, the record states none — is
> unchanged and binds every record this section admits.

**#545's claim, engaged rather than deferred.** #545 argues that "calendar events, an
activity log, and 'what the user is doing now' are not a new faculty beside memory.
They are episodic memory with more than one input channel", and it is right. This
section does not contradict it: the *event* is still the episode, and the episode is
still the only thing entitled to record that something happened, written by the
deterministic capture path that was present when it happened. What §1 adds is a
*belief about* the event in the distilled layer — a claim, with an epistemic step, a
confidence, provenance citing the episode, and no privilege the observer did not earn.

**Where the two come apart, and it is not cosmetic.** An episode is verbatim Tier 1
text under a finite retention horizon (ADR-0074 §7), destroyed with its conversation
(ADR-0074 §8), and reachable only by the supplementary read ADR-0158 §3 bounds. A
belief about the event is a distilled sentence, retained indefinitely, retrieved on
the belief budget, deletable one at a time through the surface ADR-0073 built, and —
by ADR-0077 §6 — it outlives its evidence with a tombstone where the evidence was.
Complete intake is therefore not "retain the episodes"; it is "distil the events so
the fact survives the transcript". That difference is the entire reason the store
grows 2.6× rather than by the size of the transcript.

**And where #545's worry lands, conceded.** At the limit — one record per distinct
thing said, over a long enough conversation — the distilled layer approaches a second
transcript at indefinite retention, which is verbatim the outcome ADR-0077 §2 named
as the failure mode. This ADR does not argue that away. It accepts it, on the
measurement in §Context, and names forgetting as the thing that pays it back (§5).
Accepting a named cost with a named creditor is a different act from not noticing it,
and the corpus should be able to tell which one this was.

### 5. Where the selectivity goes: retrieval now, forgetting owed

> **Normative.** Selectivity at retrieval is what decides relevance now, and it is
> already ratified: ADR-0128's eligibility predicates binding before the ranking cut,
> the belief budget and the separate episodic bound ADR-0158 §3 refuses to share, and
> §9's values.

> **Normative.** A retention and forgetting policy — what stops being kept — is owed.
> This ADR names it as the destination of the selectivity §1 removes and deliberately
> does not design it.

> **Normative.** Its mechanism is decided after pilot 5, triggered by whichever
> arrives first: the store-growth figures pilot 5 reports, or the first deployment in
> which belief-store growth is what makes a retrieval or the `assistant beliefs`
> surface unusable.

> **Normative.** Complete intake without a forgetting policy is an accepted interim
> state and not the end state. No later ADR may read this one as ruling that nothing
> needs forgetting.

**Why forgetting rather than a smaller intake, when the store grows either way.** A
bar at intake decides what to keep before anything knows what will be asked. A
forgetting policy decides what to stop keeping after the store has evidence about
what was asked, what was retrieved and what was never touched — the strictly better
information position, and the one no intake rule can occupy. That is the whole
structural argument for the move, and it is why the answer to "the store is too big"
is not "put the bar back".

**Why the trigger is stated and not left to judgement.** An owed mechanism with no
firing condition is a deferral wearing a ruling's clothes — ADR-0158 §3's phrase for
a different declined value. Two conditions are named because the two failure routes
differ: pilot 5 measures growth against a corpus, and a real deployment feels it as a
surface going bad. Either is sufficient; neither waits for the other.

**What is already there and is not forgetting.** ADR-0074 §7's episode retention
horizon bounds the *episodic* store and is untouched by this ADR; it does nothing for
the distilled layer, which is retained indefinitely by design. ADR-0072 §10's
consolidation, decay and salience — filed to leg 7 and still unbuilt — is adjacent
and is not the same question: consolidation asks what a belief becomes, forgetting
asks whether it is kept. The policy owed here may well consume the other; that is the
lane's call and not this ADR's.

### 6. The cap must not bind

> **Normative.** `Settings.observation_max_proposals` defaults to **40**.

> **Normative.** The bound's ground is cost and egress on one pass, not the intake
> rule expressed as a number. Nothing sets it to express selectivity, and ADR-0077
> §2's ground for the figure does not survive with the figure.

> **Normative.** `ObservationOutcome.discarded_over_limit` above zero is read as the
> bound binding where it should not. It is never read as the intended steady state.

> **Normative.** A pass in which the bound binds is an **incomplete pass** rather
> than a compliant one: §1's obligation is met up to the bound and no further, and
> `discarded_over_limit` is what says so. No implementation may treat a truncated
> return as satisfying §1.

> **Normative.** The response to a binding bound is to raise
> `observation_max_proposals`, to lower `observation_batch_size`, or both.

**Why the cap cannot be allowed to bind at all under §1, which is a stronger claim
than "40 is roomy".** The cap truncates the producer's return value, and the observer
prompt states no number — #1029 records that in terms: "the observer prompt never
states a number, so the cap is post-hoc truncation only". Under ADR-0077 §2 a binding
cap discarded the *least* selective tail of an already-selected set, and ADR-0077's
own remedy applied — "a batch that genuinely yields more durable beliefs than that is
a batch worth observing twice". Under §1 there is no selection to be the tail of: the
model emits one record per thing said, in whatever order it read them, and truncation
drops facts by position. A cap that binds under complete intake is a content-arbitrary
loss of exactly the material this ADR exists to stop losing — arbitrary because
position in a model's reply is not a ranking, and nothing downstream can tell a
truncated pass's output from a complete one's without the counter.

**Why the bound is an exception on §1 rather than a tension with it, and why the two
knobs together always close it.** Two normative clauses that can both be in force and
cannot both be satisfied would be a defect in this document, so §1's clause carries
the bound as its own exception and §6 carries the report. The remaining question is
whether a deployment can always *reach* a configuration in which §1 holds in full, and
it can: `observation_max_proposals` bounds records per pass while
`observation_batch_size` bounds the episodes a pass reads, and distinct things stated
scale with the latter. Raising the cap alone is the move that merely relocates the
boundary — the reviewer's richer batch always exists — while halving the batch halves
the material each pass must fit, so for any finite batch some pair of values satisfies
§1. The two are a pair and §6's third clause names both.

**The bound destroys nothing itself, and the recovery it leaves is bounded by the
episode's own life — which is the honest form of the claim.** ADR-0077 §2's reasoning
for discarding rather than queueing is untouched and is the mechanism: "a queue is
durable state this ADR does not ratify, and the episodes remain in the store, so a
later run over the same batch can propose what this one dropped". The counter says a
pass was incomplete; the episodes it read can be observed again under a configuration
that fits them **for as long as they remain live**. They may not. An episode expires
under ADR-0074 §7's finite horizon and is destroyed with its conversation under
ADR-0074 §8, and `ObservationStage.observe` skips a turn whose episode no longer
resolves without backfilling it — so a residue left unobserved until its evidence is
gone is gone with it. That is not a loss class this ADR introduces: ADR-0077's own
Consequences name it, "episodes can expire unobserved", as the accepted price of an
explicit trigger. What this ADR adds is that a binding bound makes the race *visible*
before it is lost, through a counter with a stated response, where under ADR-0077 §2 a
binding cap was reported and had no rule about it.

What this ADR does not do is *automate* the second run — that is #1179's second half,
left open in §11 for want of any evidence about what should trigger it, and it is the
mechanism that would close the residual rather than merely surface it.

**Why 40.** The probe measured 8.7, 9.1 and 9.0 proposals per pass across three
conversations at `observation_batch_size` 20, under a cap of 60 that never bound. 40
is more than four times that mean — two records per episode in the batch — which
leaves headroom for a stretch of unusually dense turns while staying a bound rather
than an absence of one. It is stated as a judgement with measured headroom, not as a
measured optimum: the probe reports means and not a distribution, so the honest claim
is about the margin and not about the tail. 60, the probe's own value, is not chosen
for the reason ADR-0077 §1 gives for bounding at all — a prompt nobody sized and a
payload nobody measured — and the tripwire is what converts a wrong guess into a
visible one.

**The two bounds are coupled and the coupling is worth naming.** 40 is a bound per
*call* and `observation_batch_size` is 20 turns. A deployment that raises the batch
raises the expected proposals per pass proportionally, and 40 will bind for it. That
is what `discarded_over_limit` is for; no clause here ties the two numbers, because a
formula would ratify a linearity nothing has measured.

**#1179 is disposed on its first half and left open on its second, explicitly.**
Its first bullet — that `observation_max_proposals` discards rather than queues and
may start binding — is answered: the value moves and the tripwire stays. Its second —
that nothing re-observes the residue of a batch whose proposals were discarded — is
**not** ruled here, and §11 says so. Its motivating condition is what §6 removes: with
no residue there is nothing for a second pass to recover. (#1179's own text cites
ADR-0077 §3 for the setting; the setting is ruled in §2.)

### 7. Where windows tile, they overlap

> **Normative.** Where consecutive observation passes tile a sequence of episodes
> rather than re-reading one window, consecutive windows overlap: the last *k*
> episodes of one window are the first *k* of the next.

> **Normative.** An episode carried in by that overlap is a full member of the window
> it is carried into — labelled, rendered and citable exactly as any other — and a
> record resting on it is proposed and ruled on like any other.

> **Normative.** *k* is at least 1 and at most `observation_batch_size // 2`. The
> value inside that bound is the implementing lane's.

> **Normative.** Where `observation_batch_size` is 1 that bound is empty and *k* is
> **0**: the clauses above are satisfied vacuously and the deployment forgoes this
> section's remedy. An overlap of 1 on a window of 1 advances the tiling by nothing,
> so no value satisfies progress and overlap together — a property of a one-turn
> window rather than something this section can repair.

> **Normative.** The product's explicit-trigger path tiles nothing today, so these
> clauses bind the benchmark harness's ingestion driver now and any durable-cursor
> walk (ADR-0111 §1) if one is built. A lane that introduces tiling elsewhere inherits
> them.

**The loss being closed.** A fact stated across a window boundary — the user names a
trip in the last turn of one window and says where they went in the first turn of the
next — is visible to neither pass as a whole. Under ADR-0077 §2's bar this was rare,
because a fragment cleared the bar seldom enough to be noise. Under §1 every fragment
is proposable, so a boundary now cuts through material that would otherwise have been
recorded, and it does so at a rate set by an arbitrary alignment rather than by the
data. #1185 records the same class of defect from the other direction, where a
per-session frame line reached only some windows: "the observer's reading of who is
speaking would then vary with tiling alignment rather than with the data — a confound,
not a frame".

**Why re-proposing rather than carrying context the model may not propose from.** The
alternative shape — show the previous window's tail as context, forbid proposals that
rest only on it — needs the prompt to carry two classes of episode, needs the producer
to drop proposals by which episodes they cite, and puts a rule about citation in a
place ADR-0077 §5 does not have one. The overlap shape needs none of that, because
duplication is already solved: ADR-0077 §3 puts de-duplication at the gate
deterministically and locally, ADR-0121 §1's `agrees` predicate decides a verbatim
restatement with no model call, and ADR-0159 §3's first rung labels it `RESTATES`
unconditionally, folding to a `REINFORCE` that costs nothing. A design whose extra
cost is absorbed by a mechanism the corpus already ratified beats one that adds a
second class of prompt entry.

**Why the bound on *k* and not the value.** The re-read cost is exactly
`batch / (batch − k)` in observation passes over a corpus, so *k* at half the batch
doubles ingestion spend and anything above it more than doubles it. The floor of 1 is
what makes the clause a rule rather than a permission — 0 is today's behaviour. Inside
that range the right value is an empirical question about how far a fact spreads
across turns, which no run has measured, and ADR-0077 §11's posture applies: the bound
is named here so the producer does not ship without one, and the figure is the lane's
with a real model and a real corpus in hand.

**What tiles today, verified, because the clause's scope depends on it.**
`orchestration/observation.py`'s `ObservationStage.observe` reads one conversation's
most recent `batch_size` turns on every call and holds no cursor — ADR-0077 §8 ruled
that explicitly and §11 filed the durable cursor to leg 5. So consecutive product
invocations re-read one window and overlap totally; there is nothing to split. The
benchmark harness's `benchmarks/memory/ingest.py::ingest_case` is what tiles: it
captures turns and calls `observe` every `batch_size` captures, in non-overlapping
tiles, and its own docstring names the requirement — "must be the same value the
harness's `ObservationStage` was built with, or the windows stop tiling". That is
where this section binds first, and naming it is what keeps the clause from reading as
an obligation on a lane that owes nothing for it.

### 8. The assistant's half of an exchange

> **Normative.** The observation prompt states an episode's `outcome` where the
> episode carries one, beside the label, the recorded instant and the `content` that
> ADR-0077 §3 and ADR-0156 §2 already put there.

> **Normative.** An episode is cited whole. A record cites the episode and never one
> half of it, and ADR-0077 §5's floor counts distinct episode ids exactly as before.

> **Normative.** What the assistant said is evidence about what happened and never a
> licence to propose an `EpisodicMemory`. ADR-0077 §2's refusal stands.

**The state of the tree, verified, because the brief for this ADR asked whether the
assistant's half is "already there" and the answer is half of each.** It is *stored*:
`EpisodicMemory.outcome` exists and the benchmark harness fills it — `exchanges_of`
pairs a user run with the assistant run that follows it and puts the latter in
`Exchange.outcome`, which `ingest_case` passes to capture. It is *not rendered*:
`learning/observer.py`'s `_render_batch` emits the label, the localised instant and
`record.content`, and nothing else. #1185 records the same finding and its
consequence — under the pre-#1184 LoCoMo mapping "every `speaker_b` line went into
`outcome`, so roughly half the corpus was never visible to distillation at all". So
the assistant's half has been in the store and outside the prompt, and this section
closes that.

**No supersession is owed for widening the payload, and the argument is ADR-0156's
own.** ADR-0077 §3's ruling is "**The payload is the batch and nothing else**", and
`outcome` is a field of the very `EpisodicMemory` records whose `content` §3 already
sends — the identical ground on which ADR-0156 §2 admitted `occurred_at`. §3's four
refusals stand verbatim: no existing beliefs, no profile, no context facet, no plan.
ADR-0156 §2's first clause requires `occurred_at` and forbids nothing beside it. What
is superseded here is ADR-0077 §3's enumerating sentence, and that was already
replaced by ADR-0156 rather than by this ADR.

**Why the episode is cited whole.** Splitting an episode into two citable halves would
let one episode supply the two distinct supports an `INFERRED` record owes, which is
exactly the failure ADR-0077 §1's duplicate-batch refusal and §5's distinct-id counting
exist to prevent. The prompt shows two texts for one label; the floor counts labels.

**The product-side gap, named and not decided here.** In the product the assistant's
half is not its reply. `orchestration/engine.py`'s `_exchange_of` renders "The user
asked: …" plus the plan rationale and the tool selected, and `_outcome_of` returns a
fixed phrase per `Disposition` — "the selected tool ran", "no action was needed". The
assistant's actual answer text is captured nowhere, so §1 cannot record what the
assistant told the user however completely it records what the user told the assistant.
That is a defect in capture, it sits in `orchestration` under ADR-0074 §4's ruling
rather than in this ADR's subject matter, and it is filed rather than fixed here (§11).
LongMemEval's single-session-assistant questions are where it shows up in a
measurement, and #1029 records that arm at 50% with half its errors abstentions.

### 9. Allocation, provisional: thirty beliefs and ten episodes

> **Normative.** `app/composition.py`'s `RETRIEVAL_LIMIT` is **30** and
> `orchestration/loop.py`'s `_DEFAULT_RETRIEVAL_LIMIT` is held equal to it.

> **Normative.** `app/composition.py`'s `EPISODIC_SUPPLEMENT_LIMIT` is **10** and
> `orchestration/loop.py`'s `_DEFAULT_EPISODIC_LIMIT` is held equal to it.

> **Normative.** Both values are provisional. Whatever the byte-budgeted single ranked
> pool ADR-0160 §5 leaves open decides replaces them, and pilot 5's post-hoc
> attribution (ADR-0160 §3) re-tests them.

> **Normative.** This replaces ADR-0160 §1's episodic value of 15 and widens the
> evidence that moves the bound to include measured retrieval reach. ADR-0160 §1's
> remaining half — that no separately registered arm is owed for the bound — stands
> and is relied on here.

> **Normative.** ADR-0158 §3's ceiling stands and is satisfied with slack, 10 against
> 30. ADR-0160 §2's admission of parity is untouched and is simply not exercised.
> ADR-0160 §7's construction-time refusal that a stated episodic bound may not exceed
> the belief budget is kept.

**The measurement.** The probe swept the allocation under complete intake, on union
all-gold-reached: 15+15 79.8%, 20+10 80.9%, 20+20 83.3%, **30+10 85.1%**, 30+15 86.5%,
30+30 88.6%, 50+10 88.4%. 30+10 beats 20+20 at a comparable prompt size (~6.5k against
~5.9k characters), and beats the incumbent 15+15 by 5.3 points at about 1.5× the
context.

**Why the belief budget is now the slot worth buying, which is the reversal.**
ADR-0160 §1 took the episodic bound to 15 on a correct reading of a store that no
longer exists: the belief layer was "saturated at 63.1% — the ceiling of what its
distilled records cite at all", so depth in beliefs bought nothing and depth in
episodes bought seventeen points. Complete intake removes that ceiling. The probe's
belief curve runs 55.1% at 5 to 81.2% at 50 and is still climbing, while the control's
runs 31.2% to 38.8% and is flat by 15. Spending the marginal slot on a layer that is
still returning new gold, rather than on verbatim transcript, is ADR-0160's own
reasoning applied to the store its ruling helped create.

**What the ceiling clause is doing here, since ADR-0160 §2 made it bind in both
directions.** At 15 against 15 it was tight; at 10 against 30 it is slack again, and
the coupling ADR-0160 §2 warned about — that dropping belief depth would drag the
episodic bound down — is not exercised because belief depth rises. Nothing in that
clause is weakened by not touching it.

**Why 10 rather than 15 for episodes, when 30+15 measures higher.** 30+15 is 86.5%
against 30+10's 85.1% — 1.4 points for half again as much transcript in every prompt,
where an episode is a verbatim turn against a belief's distilled sentence (ADR-0158
§3). ADR-0160 §5 left the byte bound open precisely because count is a weak guard on
volume, and it named the next scored run's `context_chars` as what decides it. Taking
the smaller episodic number here spends less of an unmeasured budget while the layer
that is demonstrably still returning gold gets the depth. It is the reversible
direction: raising a bound on the pilot's evidence is one integer, and unwinding a
prompt that grew past a byte bound nobody has set is not.

**Why the evidence clause has to widen and not merely the value.** ADR-0160 §1's
second clause admits only post-hoc attribution off a scored run, and there has not been
one since — the probe is a retrieval-reach measurement with no answering and no
judging. A reader holding only ADR-0160 would refuse to move the bound on it. Rather
than move the number while leaving standing a rule that forbids moving it, the clause
is superseded in terms: reach is the quantity the attribution is a proxy for, it is
measured here directly, and pilot 5's attribution is what re-tests both numbers. What
is *not* widened is the arm question — no separately registered ablation arm is owed,
which is ADR-0160 §3's whole point and stays.

**`RETRIEVAL_LIMIT` needs no supersession, and this is the check rather than an
assumption.** No ratified clause fixes it: ADR-0158 §3 mentions "a belief budget of 15"
inside a clause ADR-0160 §1 has already replaced, and ADR-0160 §6 lists "`RETRIEVAL_LIMIT`
stays 15" among what that ADR *does not decide*, in unmarked text of a marked ADR —
which under ADR-0089 §3 supplies no obligation. Its 5→15 move was made on #1029's
rank-miss analysis as a composition-root tuning change with no ADR, and this is the
same kind of move on the same kind of evidence.

### 10. What this costs

Stated at the resolution the probe supports, and no finer.

- **Store: about 2.6×** in belief records per conversation (117→286, 98→263,
  111→306). Preferences barely move; the growth is semantic and event records.
- **Ingestion output tokens: about 2.5×**, from 3.5 to about 9 proposals per pass at
  the same batch size, each a sentence of comparable length.
- **Reconciler load scales with proposals, not with the store.** Every proposal is one
  ingest and ADR-0159 §3 allows at most one model request per ingest, bounded to the
  first `reconciler_max_conflicts` (default 3) unlabelled members. So requests rise
  about 2.6× and the per-request size does not. The denser store does mean more
  conflict-set members fall beyond that bound and stay **unlabelled** — ADR-0159 §3's
  degradation, arriving more often. Nothing in that path is unsafe: an unlabelled
  member folds nothing, which is ADR-0159's floor and the direction it chose. The
  probe's redundancy figure suggests the pressure is milder than the record count
  implies — belief-slot redundancy fell from 15% to 4.6%, so the extra records are
  largely not near-duplicates of each other.
- **Prompt: about 1.5×** the answering context at §9's allocation, ~6.5k characters
  against ~4.4k at 15+15, against a median `context_chars` of 4,349 on pilot 4.
- **The `agrees` rung is free and does more work.** §7's overlap re-proposes carried
  episodes' facts by design, and ADR-0121 §1's predicate settles a verbatim
  restatement with no model call. What it does not settle is a *re-worded* restatement,
  which reaches the model like any other member; ADR-0159 §7 already records that the
  narrow predicate makes the measured rate a lower bound.
- **What is not measured, and is not claimed.** Answer accuracy under complete intake
  — pilot 5's arm measures it, and reach is not correctness. LongMemEval, which the
  probe did not touch. The overlap and the assistant-half rulings, neither of which
  the probe exercised. Store growth over a long-lived real deployment, which is §5's
  trigger and not a figure this ADR has.

### 11. What this ADR does not decide

- **The forgetting mechanism.** §5 states the principle, the destination and the
  trigger, and nothing else. What is retained, on what evidence, destructively or by
  retirement, and whether it consumes ADR-0072 §10's consolidation and decay are that
  lane's.
- **A second observation pass over a discarded residue** — #1179's second half. Left
  open in terms (§6), with its motivating condition removed rather than its question
  answered.
- **Retrieval diversity and the ranking family.** #1210's Phase 0.2 measured MMR at
  about a point and dropped hybrid BM25 and exchange-unit retrieval from pilot 5;
  whether MMR ships is that lane's call and touches no clause here.
- **The byte-budgeted single ranked pool.** ADR-0160 §5's non-decision stands whole,
  and §9's two integers are provisional against it.
- **Decomposition and iterative retrieval.** The multi-hop residual the probe still
  shows — 4+ evidence turns at 8% — is a query-side question and is deferred past
  pilot 5 (#1210).
- **Which participant is the user**, and any marker that would carry it. #1162's
  question is untouched: identity stays structural, and §2 deliberately puts the
  told/sensed distinction on the *batch* rather than on a field precisely so this ADR
  does not pre-empt that ruling.
- **`about_person` on an observer proposal.** ADR-0100 §5 forbids it, §3 keeps the
  refusal, and the subject axis's consumers — subject-scoped delete and export —
  remain ADR-0099 §5's deferral (filed, §12).
- **Capturing the assistant's reply text.** §8 rules what the observation prompt shows
  of an episode; what an episode *contains* is ADR-0074 §4's and the capture path's,
  and the gap is filed rather than closed (§12).
- **The bar for sensed inputs, beyond keeping it.** §2 keeps ADR-0077 §2 in force
  there and neither revisits it nor promises when someone will.
- **Any change to the gate, the policy, the writer or the reconciler.** Complete
  intake multiplies what reaches them and changes nothing about what they do.

### 12. What this records against earlier ADRs, under ADR-0082 §1

**ADR-0077 §2 — partial supersession, two scopes.** Argued in the header. Both replaced
passages are rules an implementer obeys rather than explanations of one, which is the
discriminator ADR-0156 states for its own classification and ADR-0128's amendment of
ADR-0045 §6 sits on the other side of. The scope of the first is bounded by episode
class rather than by clause, which is unusual in this corpus and is stated that way
deliberately: §2 needs those sentences to keep binding, verbatim, for the inputs it
leaves them on.

**ADR-0156 §2's fourth clause — partial supersession, one respect.** Argued in the
header, restated in §4. The clause's operative effect survives; its reference to a test
that no longer exists for told episodes does not.

**ADR-0160 §1 — partial supersession, both clauses.** Argued in the header and in §9.
The value and the evidence rule move together on purpose: moving the number while
leaving standing the clause that forbids moving it on this evidence would leave the
corpus contradicting itself in the direction that is hardest to notice.

**ADR-0099's Context — amendment, appended dated note.** ADR-0099 decided the principal
axis; its Context *described* the observer's authority to argue for the subject axis,
and the sentence "so `assistant observe` is **not** authorised to write about third
parties" is unmarked text of a marked ADR, so ADR-0089 §3 already keeps it from
supplying an obligation. What ADR-0082 §1's second limb catches is a reader taking it
more widely than it now holds, and §3 above is the correction. It is an amendment and
not a supersession because ADR-0099 decided nothing this ADR changes (ADR-0070 §1): a
reader acts identically on every clause of ADR-0099's Decision before and after.

**ADR-0100 — nothing recorded, and the check is stated because the absence of a record
is the claim.** §5's first clause is scoped to ADR-0100's own change ("unchanged **by
this ADR**") and stays true. §5's second, third and fourth clauses — no stated subject,
the conformance suite pinning it, no downstream implementation of the refusal — are
untouched and §3 restates the first of them as a constraint on this ADR's own lane.
ADR-0100 §3's reading of an unstated subject is relied on rather than changed.

**ADR-0077 §3, ADR-0121 §1, ADR-0128, ADR-0158 §3, ADR-0159 §3 and ADR-0111 §1 —
relied on, not changed.** Each was checked by asking what this ADR relies on it *for*,
which is the method ADR-0084 §12 requires after a lexical enumeration missed ADR-0077
once. §8 rests on ADR-0077 §3's ruling admitting a field of the batch; §7 rests on
ADR-0121 §1's predicate and ADR-0159 §3's first rung doing the de-duplication;
§5 and §9 rest on ADR-0128's eligibility ordering and ADR-0158 §3's two budgets and
ceiling; §7's last clause rests on ADR-0111 §1's placement of a durable cursor. None of
them is asked to mean anything it did not already mean.

## Consequences

- **The largest measured memory-side loss is addressed at its cause.** 39.3% of
  pilot-4's answerable LoCoMo questions had gold no belief cited; the probe takes
  belief-only reach from 36.0% to 69.5% at the same budget and union reach from 71.9%
  to 85.1% at §9's allocation. If pilot 5 does not show it, the intake ruling is what
  is falsified, and the probe's numbers are on the record to be held against it.
- **The observer stops being a judge of worth and becomes a recorder of what it was
  told**, which is a smaller and more checkable job. "Did the user say this?" is
  answerable from the batch; "would this change a later answer?" never was.
- **VISION §Principle 2's "remember selectively" is, for an interval, not implemented
  at intake and not yet implemented at forgetting.** That is the honest cost of this
  ADR, it is §5's clause rather than a footnote, and the interval is bounded by a
  trigger rather than by intent.
- **The store's third-party population grows without the axis that would let anyone
  see it**, which raises the value of the subject-scoped delete and export ADR-0099 §5
  defers. Nothing is mislabelled — ADR-0100 §3's unstated subject reads as the owner's
  world — but "forget everything about Marta" has more to bite on and still nothing to
  index on.
- **The belief layer becomes the load-bearing retrieval layer and the episodic
  supplement becomes the smaller partner**, reversing ADR-0160 §2's picture within one
  batch. The tension ADR-0158 §2 identified is relieved from the direction ADR-0158 §8
  said would relieve it: the answer to a fact that never became a belief is to distil
  it.
- **Two composition-root integers are now provisional in a stated way**, which is a
  cost: a reader of `app/composition.py` has to know that 30 and 10 are pilot-5
  settings pending a byte pool, not settled values. §9's clause and the module
  docstrings the lane writes are where that is carried.
- **A binding cap becomes a defect rather than a design.** `discarded_over_limit` was a
  counter nobody had a rule about; it is now a tripwire with a stated response.
- **Revisit if** pilot 5's complete-intake arm does not move the headline; if store
  growth in a real deployment reaches §5's trigger before the mechanism exists; if the
  reconciler's unlabelled-member rate rises far enough that ADR-0159 §3's bound needs
  its own measurement; if a sensor arrives whose content the §2 asymmetry turns out to
  serve badly; or if the byte-budgeted pool ADR-0160 §5 leaves open lands and makes
  §9's two integers the wrong shape of control entirely.

## Alternatives considered

- **Keep the bar and raise the cap.** The cheapest change, and the measurement says it
  is not the constraint: the cap was at 15 with `discarded_over_limit` 0 on every
  pilot-4 conversation and 3.5 proposals per pass. The observer was declining
  material, not running out of room, so more room buys nothing.
- **Keep the bar and add a second observation pass** (#1179's second half). Same
  refutation: a second pass re-reads a batch a filter has already declined, and a
  filter run twice declines the same things. It is the right lever for a binding cap
  and this was never one.
- **Fix retrieval instead of intake.** Tested, offline, at no model cost (#1210, Phase
  0.2): MMR, hybrid BM25+vector and exchange-unit retrieval over the same stores move
  union reach by at most 1.5 points where intake moves it by 8 to 13, and hybrid
  *hurts* at 30 beliefs. The store's content was the lever; the ranker is worth about
  a point and is a separate, smaller lane.
- **Complete intake for sensed inputs too.** Rejected in §2. The argument for §1 is
  that the user *chose* to tell the assistant, and a reader's file or a microphone's
  room is not a choice. Extending it would import the bar's removal into the one place
  ADR-0004 §7's minimisation is doing the most work, on no measurement at all.
- **Design the forgetting policy in this ADR.** Rejected in §5. There is no evidence
  yet about what a complete-intake store looks like after a long deployment, and a
  retention policy written before that would be the shape of guess this corpus keeps
  having to supersede. What is not deferred is the *obligation* and its trigger, which
  is the difference between filing a decision and dropping one.
- **Ship the bar's removal with a smaller store by folding aggressively at the gate.**
  Rejected: ADR-0159 exists because a similarity fold destroyed half of everything it
  saw (#1188), and buying store size with the mechanism that was just fixed for
  destroying facts is the exact trade the corpus has already ruled against. The probe's
  4.6% redundancy says there is little to fold anyway.
- **Carry the previous window's tail as un-proposable context** instead of §7's
  overlap. Rejected in §7: two classes of prompt entry, a citation rule with nowhere to
  live, and it declines a de-duplication mechanism the corpus has already ratified and
  measured.
- **Raise the episodic bound with the belief budget, to 30+15 or 30+30.** Rejected in
  §9. 30+30 measures 88.6% against 30+10's 85.1%, and it buys those 3.5 points with
  three times the verbatim transcript in every prompt while ADR-0160 §5's byte bound is
  still undecided. The count guard is a weak guard on bytes and the ADR that said so
  most recently is the one being partially superseded here; spending against an
  unmeasured budget on its authority would be reading it backwards.
- **State a proposal count in the observer prompt** so the cap and the instruction
  agree. Rejected: a number in the prompt is a target the model hits, which reinstates
  a selection rule — the thing §1 removes — with no evidence behind the figure.
  Truncation stays post-hoc and the tripwire stays the signal.
