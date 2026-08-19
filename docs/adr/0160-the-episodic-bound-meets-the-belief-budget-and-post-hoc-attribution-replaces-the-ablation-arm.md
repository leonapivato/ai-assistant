# 160. The episodic bound meets the belief budget, and post-hoc attribution replaces the ablation arm

- Status: Partially superseded by ADR-0162 (§1's episodic bound value of 15, and §1's clause fixing the evidence that moves it)
- Date: 2026-08-16
- **Partially supersedes:**
  [ADR-0158](0158-an-episode-may-supplement-the-answering-prompt-and-never-shares-the-belief-budget.md)
  in three scopes, each named and argued below: §3's **value clause** — *"The
  episodic bound's ratified initial value is **5**, against a belief budget of 15.
  It moves only on the measurement §6 specifies"* (§1 here); §6's **arm mandate,
  its four reporting clauses and its retraction predicate** (§§3–4 here); and §8's
  **first bullet**, *"The bound's value beyond its ratified initial 5. §6's arm owns
  it, in both directions"* (§1 here). [ADR-0070](0070-amendment-and-supersession-rules.md)
  §1's test decides the form and decides it against an amendment in every case: each
  replaced clause is a rule a reader obeys rather than an explanation of one, and a
  reader holding only ADR-0158 would configure the bound at 5, would wait for a run
  that will never be registered, and would retract the capability on baselines
  measured against a harness that no longer exists. So it is a partial supersession
  taking ADR-0070 §3's form and §4's status vocabulary.

  **What is *not* replaced is most of ADR-0158, including the clause this ADR is
  most often going to be misread as weakening.** §3's ceiling — *"The configured
  episodic bound never exceeds the configured belief budget"* — stands untouched and
  §2 below explains why meeting it is not exceeding it. §3's read shape (`kinds`,
  `bands`, a budget of its own), §3's non-`DERIVED` revisit clause, §2 in whole, §4
  in whole, §5 in whole, §7 in whole, and every bullet of §8 but the first are
  untouched. ADR-0158's `Status` line and dated note land **in this same change**,
  so that line never names an ADR that does not exist — the hazard ADR-0070 §1
  guards against — and if this change does not land, neither does the note. While
  this ADR stands `Proposed` the line names a supersession that is **drafted rather
  than ratified**, which [ADR-0083](0083-the-hub-is-a-resident-process.md)
  §15 rules outright: *"the existence condition is that the naming ADR ships in the
  same change, not that it has ratified"*.
- **Changes no Protocol and no `core` type**, adds no `Settings` field, and changes
  no code. It moves two integers and retires a measurement obligation. §7 states
  what the follow-on implementation lane owes; nothing implements against this ADR
  until it has merged ([ADR-0015](0015-simplify-the-agent-workflow.md) §5, golden
  rule 5).

  By `CONTRIBUTING.md` → "Stop when the required reviews are green" the required
  set here is **adversarial** alone: this ADR decides no contract surface. It is
  run with **architecture** as well, on the dispatching coordinator's instruction,
  because it reopens the clause in which ADR-0158 put the product thesis in
  checkable form and retires that ADR's falsifiable half. A brief may require more
  review than the minimum; that is not a conflict with the rule.
- **Ratified on `CONTRIBUTING.md` → "Finishing an ADR PR", which is where that
  sequence is argued rather than re-argued here.** This ADR is drafted, reviewed and
  revised as `Proposed`; its status is flipped only once the required set returns
  clean on one tree, and that set is re-run on the flipped tree. A finding arriving
  after a flip returns it to `Proposed` and is folded there, per that block's step 3.
  The tense is deliberate: written prospectively, this bullet is true in both states
  the document passes through, so the ratifying commit changes the `Status` line and
  nothing else.
- Refs #1190, #1029, #1187, #1189, #1186.
- Partially superseded: 2026-08-19 by ADR-0162 — **§1's two clauses are replaced:
  the episodic bound becomes 10 against a belief budget of 30, and the evidence that
  moves the bound widens to admit measured retrieval reach. §2, §3, §4, §5, §6 and
  §7's mechanism stand.** The replaced clauses are *"The configured episodic bound is
  **15**"* and *"The episodic bound moves on the post-hoc attribution §3 requires,
  read off a scored benchmark run"*.
  [ADR-0162](0162-what-the-user-tells-the-assistant-is-recorded-and-selectivity-moves-to-retrieval-and-forgetting.md)
  §9 sets 30 and 10 on #1210's complete-intake probe, which measured union
  all-gold-reached at 85.1% for 30+10 against 79.8% for 15+15 and 83.3% for 20+20.
  The remainder of the second clause — *"No separately registered arm is owed for
  it"* — **stands** and ADR-0162 §9 relies on it.

  **Both clauses move together, and that is the reason this is a supersession rather
  than a re-tuning.** §1's second clause admits only post-hoc attribution off a scored
  run, and the probe is a retrieval-reach measurement with no answering and no
  judging; a reader holding only this ADR would refuse to move the bound on it. Moving
  the number while leaving standing the rule that forbids moving it on that evidence
  would leave the corpus contradicting itself in the direction hardest to notice. Both
  are rules a reader obeys, so [ADR-0070](0070-amendment-and-supersession-rules.md)
  §1's test lands on partial supersession exactly as it did for this ADR's own
  replacement of ADR-0158 §3.

  **What this ADR ruled that ADR-0162 leans on rather than unpicks.** §2's admission
  that a bound *equal* to the belief budget is permitted is untouched and simply not
  exercised — at 10 against 30, ADR-0158 §3's ceiling is satisfied with slack, and the
  coupling §2 warned of (a falling belief budget dragging the episodic bound down) is
  not engaged because the belief budget rises. §3's post-hoc attribution obligation
  stands and is what re-tests both of ADR-0162 §9's values on pilot 5. §5's refusal to
  fix a byte bound stands, and ADR-0162 §9 states its own two integers provisional
  against it. §7's construction-time refusal — a stated episodic bound may not exceed
  the belief budget — is kept, and §7's requirement that `app/composition.py` and
  `orchestration/loop.py` hold their figures equal is the mechanism ADR-0162 §9
  restates for its own lane.

  **§6's sentence "`RETRIEVAL_LIMIT` stays 15" is not superseded, because it obligates
  nothing.** It sits in unmarked text of a marked ADR, which ADR-0089 §3 reads for
  meaning and never for obligation, and §6 is this ADR's list of what it *does not*
  decide. ADR-0162 §9 moves that constant as the composition-root tuning change its
  5→15 move already was, and says so rather than leaving the absence of a record to be
  read as an oversight.

  ADR-0162 lands **in the same change as this record**, the existence condition
  ADR-0083 §15 states. Appended per ADR-0070 §1: no text below is rewritten, and §1's
  two clauses stand exactly as written. Refs #1210, #1029.

## Context

### What ADR-0158 ratified, and why 5 was the right number then

ADR-0158 §1 admitted `EPISODIC` records to the answering prompt and §3 gave them a
second `MemoryStore.search` under a budget of their own — never a share of the
belief budget, which had just moved 5→15 for beliefs on #1029's rank-miss
measurement. It set that budget to **5** and said plainly what kind of number it
was: *"5 is chosen as the value at which the count guard and a plausible byte
parity roughly meet, and it is stated as a judgement rather than as a measured
optimum"*. Nothing had measured five episodes. §6 paired that initial value with a
retraction predicate stated as arithmetic, so the commitment was falsifiable rather
than one-way, and §8 assigned the value's future to §6's arm.

That was correct on 2026-08-15. Every part of it that this ADR replaces is
replaced because a measurement or a ruling arrived after it, not because the
reasoning was wrong.

### What has been measured since: the pilot-3 partial anatomy

Run `8a8f7a033b3c` (#1029, 2026-08-16) is a partial scored run of seven LoCoMo
conversations from `bench-pilot-3`, analysed offline against its kept stores and
traces. Three of its findings bear on the bound, and only these three are relied on
here:

- **The raw episode is what answers the question.** Partitioning the 1,032
  answerable questions that have a gold mapping by *what reached the prompt*: gold
  episode present, n=516 → **78–81% correct**; only a belief citing the gold,
  n=246 → **36.6%**; neither, n=183 → **19.7%**.
- **Belief depth is finished as a lever, and episodic depth is not.** Re-ranking
  every question against its whole store offline: belief recall@5/15/100 =
  49.7/58.7/**63.1%** — saturated, because 63.1% is the ceiling of what any belief
  cites at all. Episode recall@5/10/15/20/30 = **55.3/66.8/72.7/76.7/81.4%**, median
  gold-episode rank 4, p75 18.
- **The loss the supplement is aimed at is structural.** 4,124 episodes distilled to
  765 proposals to 380 beliefs. The largest pilot-1 error bucket was, and remains,
  facts that never became a belief record at all.

The bound is the whole of the difference between recall@5 and recall@15: **55.3% →
72.7%, seventeen points**, on records the ranking had already found and the store
already held. #1029 ranks this first among the levers it identifies, at roughly
+350 tokens per question.

### What has been ruled since: the arm was given up the day after ratification

ADR-0158 §6 required the supplement's effect to be measured *"in a separately
registered arm"*. That arm was never registered and will not be. Two operating
rulings, both recorded on #1029 before this ADR was drafted, took it away:

- **2026-08-15, cost.** The `bench-pilot-2` pre-registration commits to *"no
  per-fix arms (cost ruling, 2026-08-15). Attribution is by the bucket anatomy
  instead"*.
- **2026-08-16, explicitly for this capability.** The `bench-pilot-3`
  pre-registration addendum records: *"the planned beliefs-vs-episodes ablation arm
  is **given up** in favour of post-hoc attribution — weaker, and said so"*.

So the corpus has carried a live normative obligation to run a study that the
owner had already cancelled, since the day after ADR-0158 was ratified. §3 below is
the record catching up, not a fresh decision — and the honesty of the original
ruling ("weaker, and said so") is preserved rather than laundered.

### What makes post-hoc attribution newly viable, and the byte question newly different

Two harness defects found while costing the same run change what a scored run can
be asked for, and both are fixed in the wave this ADR belongs to (#1190's lane C):

- **#1187** — episodic records carry empty `retrieved_evidence` (6,735 of 6,735), so
  attribution of ADR-0158 from `records.jsonl` is zero by construction. The fix maps
  each episodic record to its own evidence key. Without it there is no post-hoc
  attribution to substitute for the arm; §3 makes that dependency normative rather
  than hopeful.
- **#1189** — `render_context` dumps each retrieved record as full JSON: ~800
  chars per record against ~150 chars of actual content, *"roughly 4× the product's
  prompt cost"*, where the product renders one line per memory. Every byte figure
  measured before that fix is a measurement of the harness, not of the product.

## Decision

### 1. The episodic bound is 15

> **Normative.** The configured episodic bound is **15**.

> **Normative.** The episodic bound moves on the post-hoc attribution §3 requires,
> read off a scored benchmark run. No separately registered arm is owed for it.

The value is no longer a judgement standing in for a measurement. Seventeen points
of episode recall sit between 5 and 15 (55.3% → 72.7%), on a corpus where the
episode's presence in the prompt is worth 78–81% correct against 36.6% for a belief
citing the same fact. The belief layer cannot close that gap at any depth, because
it is saturated at 63.1% — the ceiling of what its distilled records cite at all.

**Why exactly 15 and not 20, which measures higher.** Recall@20 is 76.7% and
recall@30 is 81.4%, so the curve has not flattened. 15 is chosen because it is the
largest value ADR-0158 §3's ceiling admits without also moving the belief budget,
and moving the belief budget is a separate decision with its own evidence — #1029
measures belief depth as costing ~2 points of recall going *down* from 15 to 10, so
the belief budget is under cost pressure rather than expansion pressure. Taking the
episodic bound to the ceiling and stopping there is the change that spends nothing
it has not measured, and it keeps this decision reversible by a single integer.

**This is a cardinality control moving on evidence, which is the pattern the corpus
already has.** ADR-0158 §3 states it about the sibling constant: *"`RETRIEVAL_LIMIT`
itself began at 5 with no measurement behind it and moved to 15 with one"*. The
episodic bound began at 5 with no measurement behind it. This is the one with it.

### 2. Parity with the belief budget is admitted, and the ceiling clause stands

> **Normative.** A configured episodic bound *equal* to the configured belief budget
> is permitted. ADR-0158 §3's ceiling forbids a bound that exceeds the belief
> budget, not one that meets it.

ADR-0158 §3 says the ceiling is *"where the thesis is actually expressed… whatever
the numbers become, nobody can configure a system that asks for more transcript than
belief"*. At 15 and 15 the prompt asks for as much transcript as belief. That is the
boundary of the clause, and this ADR admits reaching it rather than pretending the
question does not arise.

**Three reasons the boundary is the right place to stand.**

First, the clause means what it says. "Never exceeds" is satisfied by equality on
any reading, and the clause was written after `RETRIEVAL_LIMIT` had already moved to
15 by an author who knew both numbers. Reading it as "must remain materially below"
would be reading a ratified clause more widely than it holds, which is precisely
what ADR-0082 §1 forbids a later reader to do.

Second, the thesis the clause protects is about **displacement**, and there is none
here. ADR-0158 §2's hollowing risk is an episode pushing a belief below a shared
cut; §3 refuses a shared budget for exactly that reason, and this ADR does not
reopen it. The belief composition still gets its full 15, unreduced and
unconditional. What grows is the prompt, not the episode's claim on the belief
layer's budget.

Third — and this is the part worth stating rather than assuming — **parity is not a
statement that transcript is as valuable as belief.** It is a statement that the
belief layer is currently *saturated at 63.1%* and the episodic layer is not. The
long-run answer to a fact that never became a belief is to distil it, not to carry
the transcript forever: ADR-0158 §8 defers retrieval-triggered distillation ("an
episode that answered a question is fed back to the observer so the fact becomes a
belief") and #1178 holds the miss-driven variant. Those remain the shape that
resolves the tension. Until one lands, the episode is the only route to 652 LoCoMo
questions' worth of facts, and refusing that route on a principle would be choosing
the thesis's slogan over its substance.

**The ceiling stops being slack and starts binding, which is a real consequence.**
At 5 against 15 the clause cost nothing and constrained nobody. At 15 against 15 it
is tight in both directions: the episodic bound cannot rise without the belief
budget rising first, and #1029's cost knob — dropping belief depth 15→10 to save
about a third of the prompt — would now drag the episodic bound down with it. That
coupling is the clause working as designed, and any lane touching either number
should expect to touch both.

### 3. The ablation arm is retired; post-hoc attribution on a scored run takes its place

> **Normative.** No separately registered ablation arm is owed for the episodic
> supplement.

> **Normative.** The supplement's effect is measured by post-hoc attribution on a
> scored benchmark run.

> **Normative.** The scored run exercises the production composition path, not a
> harness-local imitation of it.

> **Normative.** The scored run imports the episodic bound from
> `ai_assistant.app.composition` rather than carrying a copy of it.

> **Normative.** The scored run reports conversion per pilot bucket, not a headline
> score alone.

> **Normative.** The scored run reports prompt bytes per answered question.

> **Normative.** Post-hoc attribution of the supplement requires every episodic
> record written to the run's record log to carry its own evidence key. A run whose
> episodic records carry none does not discharge this section, whatever else it
> reports.

The first two clauses record the owner's rulings of 2026-08-15 and 2026-08-16
(Context). The middle four are ADR-0158 §6's own obligations re-scoped from "the
arm" to "the scored run" — they are re-stated rather than dropped because their
subject disappeared, not their purpose. The clause requiring the bound to be
*imported* is the one most worth keeping: it is what stops a harness from acquiring
a private copy of a product constant, and it is the reason there is no cheap
harness-local route to a different bound. The last clause is #1187 in normative
form, and it is the load-bearing addition — without evidence keys on episodic
records the substitution this section performs does not exist, and the capability
would be measured at exactly zero by construction.

**What this costs, stated rather than glossed.** An arm is a controlled comparison:
the same questions, the same store, one configuration difference, so a delta is
caused by that difference. Post-hoc attribution is **observational**. It can say
that questions whose gold episode reached the prompt were answered correctly 78–81%
of the time and that questions with only a belief were answered 36.6% of the time;
it cannot by itself say the episode *caused* the difference, because the questions
whose episode retrieval succeeded are not a random sample — retrieval succeeding
correlates with the question being easier. The honest reading is a **bound on the
plausible effect, not an estimate of it**, and the corpus should not later cite
these figures as if an arm had produced them. ADR-0158 §6's arm was the better
instrument and it was given up for cost. This ADR records the substitution and its
price; it does not claim the substitute is equivalent.

**Comparison across successive pilots is what partially recovers the pairing.**
#1029's anatomy compares pilot-1 and pilot-3 on the same seven conversations, which
is a paired design assembled from runs that were going to happen anyway. That is
where a delta attributable to a named change can still be read, and it is why §4
requires the *within-run* partition as the predicate's subject and treats
cross-pilot comparison as evidence rather than as arithmetic.

### 4. ADR-0158 §6's baselines are retired, and the retraction predicate is restated

> **Normative.** ADR-0158 §6's baselines of 118 `correct` and 69 `attempted-wrong`
> are retired. They are not applied to any run after `bench-pilot-1`.

> **Normative.** The retraction predicate is evaluated within a single scored run,
> over populations partitioned by what reached the answering prompt, and not across
> runs by raw counts.

> **Normative.** The run's pre-registration fixes, before the run executes, a
> **positive** minimum size for each compared population and any threshold on the
> *magnitude* of the gap between them. Neither is chosen once the figures are known.

> **Normative.** Where either compared population is empty, or falls below its
> pre-registered minimum, the run does not discharge §3's measurement and the
> episodic bound does not move on it. An empty population never discharges it,
> whatever minimum was registered.

> **Normative.** Where both populations meet their minimum, the retraction test is
> met when, on the scored run's LoCoMo figures, the questions whose gold episode
> reached the prompt with **no** belief citing the gold present are answered no more
> accurately than the questions where neither reached the prompt — or, where the
> pre-registration set a magnitude threshold, when the gap falls short of it. A
> pre-registered threshold may only raise that bar and never lower it.

> **Normative.** A run that meets the retraction test takes the episodic bound to
> zero and removes the supplement, unless a controlled arm satisfying the two
> clauses below is run first and escapes it.

> **Normative.** The controlled arm is a paired comparison: the same questions, the
> same store and the same run configuration, with the episodic supplement enabled in
> one half and disabled in the other.

> **Normative.** The arm escapes the removal when its supplemented half is more
> accurate than its unsupplemented half over the questions the observational trigger
> was computed on. A threshold fixed in the arm's own pre-registration, before the
> arm executes, may only raise that bar and never lower it.

> **Normative.** The observational partition is never on its own evidence *for* the
> size of the supplement's effect. A claim that the supplement caused a measured
> gain rests on a controlled arm.

**The old baselines are not retired for convenience; applying them would retract
ADR-0158 for a reason that has nothing to do with the supplement.** 118 and 69 were
measured on `bench-pilot-1`, a configuration in which the harness declined **85.7%**
of answerable LoCoMo questions because of its own answer prompt — an artifact
#1029's error-anatomy attributed and #1163's lanes then fixed. Pilot-3 declines
21.8%. Converting four-fifths of a corpus from declines into attempts mechanically
raises *both* `correct` and `attempted-wrong`, and it does: pilot-3's partial shows
`wrong-with-gold-in-prompt` at **121** on seven conversations against a
whole-corpus pilot-1 baseline of 69. Read literally, ADR-0158 §6's cost condition —
*"`attempted-wrong` is not above its baseline of 69"* — is already breached, and its
predicate would remove the supplement. It would be removing it for the answer prompt
being fixed. A predicate that fires on a change it does not measure is not a
commitment; it is a trap, and the right response is to retire the baselines rather
than to quietly not apply them.

**The replacement keeps the question ADR-0158 was actually asking.** §6's
complementarity test — `I > L + R`, conversions from ingestion-loss exceeding
conversions from buckets the belief layer could have served itself — asks whether
the supplement adds *reach* or merely *substitutes*. The within-run partition asks
the same thing with the instrument that now exists: the questions whose gold episode
was in the prompt and whose gold was cited by **no** belief in the prompt are
exactly §1's justification population, the facts no belief could have carried.
Comparing them against the questions where neither reached the prompt isolates what
the episode added, on questions the belief layer had nothing to offer either way.

**The floor is deliberately a zero-threshold comparison, so it invents no number.**
ADR-0158 §6 refused to fold in a size threshold because that would mean *"inventing
a number this ADR has no measurement for"*, and that discipline is kept: "no more
accurately than" needs no constant. If the episode-only population answers no better
than the population with nothing, the supplement has bought nothing for the prompt
bytes it spends and it goes — which is the same conservative direction §6 chose when
it ruled that zero and ties both fail. Pilot-3's partial suggests the floor will be
cleared comfortably (78–81% against 19.7% for the coarser partition it can compute),
but that partition mixes episode-only with episode-and-belief, so the figure that
decides this predicate does not yet exist. That is precisely why the magnitude
threshold and the minimum populations are pre-registered rather than set here.

**The two compared populations are not exchangeable, and the predicate is built
asymmetrically because of it.** Retrieval succeeding is not independent of the
question: the episode-only group is selected for questions whose gold episode was
findable, and the neither group for questions where nothing was. So a gap can be
small — or inverted — while the episode is still doing real work, which is exactly
the causal claim §3 says this instrument cannot make. Three properties answer that
rather than wishing it away. The comparison **triggers** a removal instead of
*being* one, and the trigger is escapable by the better instrument: a controlled arm
over the same questions settles it, and the burden of paying for one falls on
whoever wants to keep a capability its cheap evidence no longer supports. The
asymmetry runs one way only — the partition can condemn the supplement and can never
on its own vindicate it — which is the conservative direction ADR-0158 §6 already
chose when it ruled that zero and ties both fail. And the minimum populations stop
the whole test being decided by a handful of questions, which is the shape the
confound does most damage in.

**The escaping arm is paired for the same reason the observational partition is
not trustworthy alone.** Its two halves differ in the supplement and in nothing
else, so the difference between them is caused by the supplement — which is the
property the within-run partition cannot have, and the whole reason an arm can
overturn it. It is scored over the questions the trigger was computed on rather
than the whole corpus, because those are the questions the removal would be
justified by, and a whole-corpus average would let a large untouched majority hide
the population in dispute. The bar is again a zero-threshold comparison inventing
no constant, and again a pre-registration may only make it harder to clear.

**This does not quietly re-impose the arm §3 retired.** No arm is owed, and none
needs to exist for the bound to stand: the escape is a route available to whoever
contests a removal, not an obligation on whoever runs the benchmark. What it buys is
that a removal is never final on evidence this ADR has already called weaker.

**Pre-registration is what keeps the substitution honest.** The one property an arm
had that post-hoc attribution lacks is that its comparison was fixed before the data
arrived. Requiring the magnitude threshold to be committed in the run's
pre-registration restores that property at the point where it does the work, and it
is the reason the fourth clause is normative rather than advisory.

### 5. No byte bound is decided here

> **Normative.** This decision fixes no byte bound on the answering prompt.
> [ADR-0007](0007-memory-data-rights.md) §5's deferral of size caps stands.

> **Normative.** The measurement that would inform a byte bound is the scored run's
> per-question rendered-context size, reported alongside the bucket figures.

ADR-0158 §3 chose 5 partly on a *byte* argument — an episode is a verbatim turn
where a belief is a distilled sentence, so a count guard is a weaker guard on volume
than it looks — and §8 left the byte bound undecided. Tripling the count makes that
argument worth revisiting, and the answer is that the evidence for it has improved
but is not yet the evidence a bound needs.

What is measured: #1029 prices the 5→15 move at roughly **+350 tokens per
question**, or about 35 tokens per additional episode, which is the same order as
the ~150 characters of actual content #1189 measures per retrieved record across the
pilot-3 mix. On that mix an episode and a belief are near parity per record, so the
count guard is a better guard on bytes than ADR-0158 §3 could assume — but only
*after* #1189 lands, because every byte figure measured before it is measuring the
harness's JSON dump at roughly 4× the product's rendering, not the product. A bound
set on pre-#1189 numbers would be a bound on a defect.

So the byte bound stays open, with `context_chars` on the next scored run named as
the measurement that decides it. This is the same posture ADR-0158 §8 took, held for
the same reason, and it is a deliberate non-decision rather than an oversight.

### 6. What this ADR does not decide

- **The belief budget.** `RETRIEVAL_LIMIT` stays 15. #1029's cost knob (15→10, ~2
  points of belief recall for about a third of the prompt) is a live option and a
  separate decision, and §2 notes that taking it would now drag the episodic bound
  down with it.
- **Whether an episode should be distilled once it answers.** ADR-0158 §8's
  retrieval-triggered distillation and #1178's miss-driven variant are untouched and
  remain the shape that would resolve the thesis tension rather than balance it.
- **Anything about the supplement's read.** §3's `kinds`, `bands`, ordering, tail
  deduplication, degradation behaviour and non-`DERIVED` revisit clause are
  ADR-0158's and stay exactly as ratified. This ADR moves one integer and one
  measurement obligation.
- **The reconciler.** #1188's 50% REINFORCE fold is the other lever #1029 ranks and
  it has its own ADR in this wave. Nothing here depends on it.
- **Any harness change.** #1187 and #1189 are #1190's lane C. §3 states what a run
  must carry for its figures to count; it does not specify how the harness gets
  there.
- **#1186's telemetry docstring.** It is left open and is *not* disposed here. Its
  premise — that the bound may be taken to zero, making the fourth search call
  absent on a healthy read — survives this ADR intact, because §4 keeps a live path
  to a zero bound. The docstring fix is still owed and still belongs with whatever
  next touches the harness's telemetry documentation.

### 7. What the follow-on implementation lane owes

> **Normative.** The implementing lane's edits are the episodic bound in
> `app/composition.py`, the corresponding default in `orchestration/loop.py`, and
> the tests pinning those two values. It adds no member to any Protocol, changes no
> field in `core/types.py`, and adds no `Settings` field.

> **Normative.** The lane keeps the two values equal to each other, and keeps the
> construction-time refusal that a stated episodic bound may not exceed the belief
> budget.

The two integers are held equal for a reader's sake and neither depends on the
other — `orchestration` may not import the composition root. The refusal to be kept
is the mechanical form of ADR-0158 §3's ceiling, which this ADR does not touch; at
parity it accepts 15 against 15 and refuses 16.

Two existing tests pin the old value and both are the ceiling clause and the value
clause in checkable form rather than incidental assertions — one in `tests/app/`,
one in `tests/orchestration/`. They move to 15 with their docstrings' reasoning
updated to cite this ADR rather than ADR-0158 §6's arm. One further test in
`tests/orchestration/` is named for the untuned bound being *above* the belief
budget; at parity that name no longer describes it and the lane renames it.

## Consequences

**Easier.** The single largest measured lever on the benchmark is taken, at the
cost of one integer and about 350 tokens per question. The corpus stops carrying an
obligation to run a study that was cancelled the day after it was ratified, which is
the kind of drift that makes a reader distrust the whole record. And post-hoc
attribution becomes a stated method with stated limits rather than an informal
practice that happens to be what the runs do.

**Harder.** The ceiling clause now binds, so the two cardinality controls are
coupled and neither moves alone. The evidence for the supplement is permanently
weaker than an arm would have made it, and §4's last clause forbids citing the
partition as if it measured an effect size.
And the retraction predicate now depends on a harness capability (#1187) that did
not exist when ADR-0158 was written — a run that ships without it cannot discharge
§3, which is a new way for a scored run to fail to answer the question it was run
for.

**What would trigger revisiting this.** §4's floor firing on a scored run removes
the supplement outright. Short of that, the byte figures §5 names may show the count
guard is a poor guard after all, which would reopen §8's byte bound rather than this
bound. And a landed retrieval-triggered distillation would change the argument in §2
from "the episode is the only route" to "the episode is a route", at which point the
right value is plausibly lower than 15 again.

## Alternatives considered

**1. Leave the bound at 5 until §6's arm runs.** This is what ADR-0158 as ratified
requires, and it was rejected because the arm is not going to run — the owner
cancelled it for cost on 2026-08-15 and again by name on 2026-08-16. Holding the
bound to a measurement that will never be taken is not conservatism; it is a
permanent freeze arrived at by inaction, and it would leave seventeen points of
episode recall on the floor for a scored run that costs real money.

**2. Move the bound to 20 or 30, where recall is higher.** Recall@20 is 76.7% and
recall@30 is 81.4%, so this buys more. Rejected because both exceed ADR-0158 §3's
ceiling at the current belief budget, and clearing the ceiling means moving the
belief budget on evidence that points the other way (#1029 measures belief depth as
a candidate for *reduction*). Taking two decisions in one, on evidence for one of
them, is how a cardinality control stops being reversible.

**3. Retire ADR-0158 §6's predicate entirely and rely on the headline score.**
Simplest, and wrong in the specific way §6 was written to prevent: a score that
rises because the belief layer improved would read as evidence for the supplement.
Keeping a complementarity predicate — even a weaker, observational one — is what
keeps the capability falsifiable, and ADR-0158 §6 is explicit that the predicate is
*"the falsifiable half of this decision"*. Retiring the arm without replacing its
question would have taken the ratchet ADR-0158 refused to build.

**4. Keep 118 and 69 and add a correction factor for the abstention change.**
Considered because retiring baselines looks like moving a goalpost. Rejected because
the factor would be invented: nothing measures how many of pilot-1's declines would
have been wrong rather than right had the prompt not suppressed them, and a derived
constant standing in for that would be less honest than a within-run partition that
needs no constant at all. The within-run form also survives the *next* harness
change, which a corrected cross-run baseline would not.

**5. Make the magnitude threshold part of this ADR.** Rejected on ADR-0158 §6's own
reasoning — the partition that decides it (episode-only versus neither) has not been
computed, because #1187 is what makes it computable. Fixing a number here would be
inventing one; deferring it to the run's pre-registration keeps it committed *before*
the data, which is the property that matters.
