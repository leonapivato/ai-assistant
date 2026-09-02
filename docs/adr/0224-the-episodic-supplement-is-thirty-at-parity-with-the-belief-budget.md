# 224. The episodic supplement is thirty, at parity with the belief budget

- Status: Proposed
- Date: 2026-09-02
- **Partially supersedes:**
  [ADR-0162](0162-what-the-user-tells-the-assistant-is-recorded-and-selectivity-moves-to-retrieval-and-forgetting.md)
  in two scopes, each named and argued below: §9's **episodic value clause** —
  *"`app/composition.py`'s `EPISODIC_SUPPLEMENT_LIMIT` is **10** and
  `orchestration/loop.py`'s `_DEFAULT_EPISODIC_LIMIT` is held equal to it"* (§1
  here); and §9's **ceiling-slack clause** — *"ADR-0158 §3's ceiling stands and is
  satisfied with slack, 10 against 30. ADR-0160 §2's admission of parity is
  untouched and is simply not exercised"* (§2 here). Both are marked clauses of a
  marked ADR, so [ADR-0089](0089-a-ruling-is-marked-and-nothing-else-binds.md) §3
  makes them obligations and
  [ADR-0070](0070-amendment-and-supersession-rules.md) §1's test decides the form
  against an amendment: a reader holding only ADR-0162 would configure 10 and
  would read the ceiling as slack. Each is a rule a reader obeys rather than an
  explanation of one, so this is a partial supersession taking ADR-0070 §3's form
  and §4's status vocabulary. ADR-0162's `Status` line already leads with
  `Partially superseded by`, so this ADR's pair is **added** to it and the two
  existing pairs are not dropped (ADR-0070 §4's accumulation rule), beside the
  dated header note ADR-0070 §1 requires. §9's other three clauses stand and §3
  below states which and why.
- **Changes no Protocol and no `core` type**, adds no `Settings` field, and changes
  no code. It moves one integer, and it moves a ceiling from slack to met. §5
  states what the follow-on implementation lane owes; nothing implements against
  this ADR until it has merged
  ([ADR-0015](0015-simplify-the-agent-workflow.md) §5, golden rule 5), which is
  the sequence both prior moves of this constant took.

  By `CONTRIBUTING.md` → "Stop when the required reviews are green" the required
  set here is **adversarial** alone: this ADR decides no contract surface, adds and
  widens no `Protocol`, and touches no `core` type.
- **Ratified on `CONTRIBUTING.md` → "Finishing an ADR PR".** This ADR is drafted,
  reviewed and revised as `Proposed`; its status is flipped only once the required
  set returns clean on one tree. The ratifying commit changes the `Status` line and
  nothing else.
- Refs #1844, #1294, #1029.

## Context

### Where this comes from

The offline replay recorded on **#1844** on 2026-09-01 priced the sighted-read
envelope that design note proposed, and returned a result about something else. Of
pilot-5's published 75.7% union retrieval reach on LoCoMo (n=1531 answerable), the
blind pass **holds** the gold turn in the assembled prompt for 52.9%, reaches it
only through a belief's `Provenance.evidence` — a citation hop this system does not
perform — for 22.8%, and misses it entirely for 24.3%. Pilot-5's own answer accuracy
on those three populations was 90.1%, 76.2% and 40.3%.

Against that, the replay measured what the **existing blind read** recovers when only
its episodic budget is widened, holding the same key, the same order and the same
belief budget: at 15 it holds the gold turn for 15.8% of `hop` and 6.5% of `miss`
cases; at 30, for **42.1%** and **18.8%**; at 60, for 62.8% and 33.9%. Converted
through the accuracy column, the replay's own table reads:

| lever | model calls | projected LoCoMo accuracy |
|---|---|---|
| sighted query + citation hop, **oracle** trigger | 1 extra call/turn | ≈ +4.3pt |
| the same, **measured** trigger | 1 extra call on 13.6% of turns | ≈ **+0.9pt** |
| `EPISODIC_SUPPLEMENT_LIMIT` 10 → 30 | **none** | ≈ **+3.6pt** |

The owner accepted the change on 2026-09-02 — "upgrade supplement to 30" — on the
30-arm, and this ADR records it.

### The arithmetic, checked rather than quoted

The `+3.6pt` is reproducible from the replay's own two tables and is checked here
because an ADR that moves a number on a projection owes the reader the projection's
working. At 30: `hop` 349 × 0.421 = 146.9 questions move from 76.2% to 90.1%, worth
146.9 × 0.139 = 20.4 additional correct answers; `miss` 372 × 0.188 = 69.9 questions
move from 40.3% to 90.1%, worth 69.9 × 0.498 = 34.8. Together 55.2 additional correct
answers over 1531 questions — **+3.6 points**. The same working gives **≈ +1.3pt** at
15 and **≈ +6.1pt** at 60.

Three properties of that curve matter more than the headline.

**There is no knee.** The marginal return is 1.3 points for 10→15, a further 2.3 for
15→30, and a further 2.5 for 30→60. Nothing in the measurement says 30. What says 30
is ADR-0158 §3's ceiling, and §2 below is about that.

**It is a projection, not a measured answer-side arm**, and the replay flags it as
such in its own text. No answer was re-generated at a wider bound; the conversion
assumes a question whose gold turn becomes held answers at the held population's
rate. That assumption is favourable — a question that needed rank 25 to reach its
gold is plausibly a harder question than one that reached it at rank 3 — so the
figure is better read as an upper bound on this corpus than as a point estimate.

**The corroboration is directional only.** ADR-0162 §9's own probe sweep, on
different stores with complete intake, ranked the same three arms in the same order
on union all-gold-reached: 30+10 85.1%, 30+15 86.5%, 30+30 88.6%. That two
independent instruments order the arms identically is the useful fact. The figures
are in **different units** — reach against projected accuracy — and must not be
compared numerically or added; their near-coincidence at both arms is arithmetic
accident, not confirmation.

### What is on the tree today, read rather than recalled

At `main` `47640fcf`: `app/composition.py`'s `EPISODIC_SUPPLEMENT_LIMIT` is `10` and
`RETRIEVAL_LIMIT` is `30`; `orchestration/loop.py`'s `_DEFAULT_EPISODIC_LIMIT` is
`10`, held equal by the comment contract its docstring states, and
`_DEFAULT_RETRIEVAL_LIMIT` is `30`. `LearningLoop.__init__` resolves an unstated
episodic bound against the belief budget it was given and refuses a *stated* bound
above it. Two tests pin the pair: `tests/app/test_composition.py`'s
`test_the_episodic_supplement_is_bounded_at_ten_and_never_above_the_beliefs`, whose
second assertion is **strictly** less-than, and `tests/orchestration/test_loop.py`'s
default-resolution cases, which assert symbolically.

The replay confirmed both constants against `main` at `c25e697f` rather than assuming
them, which is why its blind arm is the production read and not a lookalike.

### Why this is a supersession and not a composition-root re-tuning

`RETRIEVAL_LIMIT`'s own 5→15 move was made with no ADR at all, and ADR-0162 §9 states
the check that permitted it: *"No ratified clause fixes it … ADR-0160 §6 lists
'`RETRIEVAL_LIMIT` stays 15' among what that ADR **does not decide**, in unmarked text
of a marked ADR — which under ADR-0089 §3 supplies no obligation."*

That route is now closed for both constants, and §9 is what closed it: it fixed each
by a marked clause. Under ADR-0089 §3 a marked clause of a marked ADR is the whole of
the obligation, and it is an obligation. So moving the episodic bound is a change to
what was decided, ADR-0070 §1 sends it to a superseding ADR, and this is that ADR.
The corpus has taken this exact route twice for this exact constant already — ADR-0160
§1 over ADR-0158 §3's value clause, ADR-0162 §9 over ADR-0160 §1 — and both times the
integers landed in a **separate later change** (`101b5210`, `07d42fa6`), neither of
which touched `docs/adr/`.

### The proof, in two lines of two tests

The clearest evidence that this is not a re-tuning is that pinned assertions have to
change their **operator**, not their literal. There are two, one per subsystem, and
ADR-0160 §7 already identified the pair when it moved this constant before: *"Two
existing tests pin the old value and both are the ceiling clause and the value clause in
checkable form rather than incidental assertions — one in `tests/app/`, one in
`tests/orchestration/`."*

- `tests/app/test_composition.py`'s
  `test_the_episodic_supplement_is_bounded_at_ten_and_never_above_the_beliefs` asserts
  `EPISODIC_SUPPLEMENT_LIMIT < RETRIEVAL_LIMIT`, under a docstring saying *"At 10
  against 30 it is satisfied with slack again rather than at the parity ADR-0160 §2
  admitted, so the second assertion records slack once more."*
- `tests/orchestration/test_loop.py`'s
  `test_the_episodic_bound_is_ten_and_never_exceeds_the_belief_budget` asserts
  `_DEFAULT_EPISODIC_LIMIT < _DEFAULT_RETRIEVAL_LIMIT`, under a docstring saying *"The
  relation is back to holding with slack rather than at the parity ADR-0160 §2
  admitted."*

Both are strictly less-than, and at 30 against 30 both **fail** rather than merely
reading oddly. In each the literal moves *and the operator does too*, from `<` to `<=`,
because the reading they encode is the one this ADR replaces. A change that only
re-tuned a number would leave both operators alone.

## Decision

### 1. The episodic supplement is thirty

> **Normative.** `app/composition.py`'s `EPISODIC_SUPPLEMENT_LIMIT` is **30** and
> `orchestration/loop.py`'s `_DEFAULT_EPISODIC_LIMIT` is held equal to it.

The evidence is the #1844 replay's measured widening of the existing blind read,
converted through pilot-5's own scored answers: ≈ **+3.6 points** of LoCoMo accuracy
for **no additional model call, no new read, no envelope and no trigger**. It is the
cheapest lever the replay priced and it beats every sighted mechanism the same replay
measured with a real trigger by about four times.

**Why 30 rather than 15, which was the cheaper alternative and is the one the owner
was choosing against.** 30+15 costs half the transcript and buys ≈ +1.3pt where 30+30
buys ≈ +3.6pt — 2.3 points of projected accuracy for the second half of the budget, on
a curve with no knee in it. The replay and #1294's step C both offered the pair
("30+15 or 30+30"), and the choice between them is not one the measurement makes: it
is a judgement about how much unmeasured prompt volume to spend for a measured
accuracy gain, and §4 below is honest that the volume is unmeasured. **The owner made
that call on 2026-09-02 and took the larger arm.** This ADR records the ground rather
than manufacturing one: the gain is roughly three times the cheaper arm's, the cost is
prompt bytes on a budget nobody has bounded yet, and the direction is reversible in
one integer where a byte bound set on a guess would not be.

**Why not 60, which measures higher still.** ADR-0158 §3's ceiling forbids it. 60
against a belief budget of 30 is a configuration asking for more transcript than
belief, and that is the one thing the ceiling exists to make unconfigurable. §2 is
about what it means that the ceiling — and not the measurement — is what picked this
number.

**The two constants move together because §9's clause makes their equality the rule,
not a convention.** They are held equal for a reader's sake and neither depends on the
other: `orchestration` may not import the composition root (golden rule 1), so the
equality is maintained by the lane and asserted by the tests, exactly as ADR-0160 §7
required of the previous move.

### 2. Parity is exercised: the ceiling is met, and it is binding against a measured gain

> **Normative.** ADR-0158 §3's ceiling stands and is **met**: 30 against a belief
> budget of 30. ADR-0160 §2's admission that a bound equal to the belief budget is
> permitted is exercised rather than untouched, and its coupling consequence is in
> force — the episodic bound cannot rise without the belief budget rising first, and a
> lane lowering the belief budget lowers this bound with it.

ADR-0158 §3 says the ceiling is *"where the thesis is actually expressed… whatever the
numbers become, nobody can configure a system that asks for more transcript than
belief."* ADR-0160 §2 ruled that meeting it is not exceeding it, on three grounds this
ADR does not reopen: the clause means what it says; the hollowing risk is
*displacement* below a shared cut and there is none, because the belief composition
keeps its full 30 unreduced and unconditional (ADR-0158 §3's second clause, untouched);
and parity is not a claim that transcript is as valuable as belief.

**What is new, and is worth stating plainly, is that the ceiling is now refusing
something measured.** At 5 against 15 the clause cost nothing. At 15 against 15 it was
tight but nothing was pressing on it. Here the replay puts 60 at ≈ +6.1pt — 2.5 further
points, on the same corpus, for no model call — and the ceiling is the only thing
standing between that measurement and the configuration. This ADR takes the ceiling's
side, and does so knowing the price.

That is the clause working as designed rather than an awkwardness to be explained away.
A rule that only ever forbids what nobody wanted is documentation; ADR-0158 §3 was
written to be the one statement of the product thesis that survives whoever tunes the
numbers next, and the first time it costs something is the first time it is worth
having. The long-run answer to a fact that never became a belief remains distillation,
not carrying the transcript forever — ADR-0158 §8's retrieval-triggered distillation
and #1178's miss-driven variant are still the shape that resolves this tension instead
of balancing it, and this ADR does not touch either.

**The coupling ADR-0160 §2 warned of is now live, and a later lane must know it.** §9
recorded that coupling as *"simply not exercised"* at 10 against 30. It is exercised
now: any lane that lowers `RETRIEVAL_LIMIT` — #1029's cost knob is a live option and
ADR-0160 §6 keeps it a separate decision — drags this bound down with it, and any lane
that wants the episodic bound above 30 must raise the belief budget first and argue
that raise on its own evidence. Both numbers are one decision again, as they were at
15 and 15.

### 3. What this replaces in ADR-0162 §9, and what stands

> **Normative.** This replaces ADR-0162 §9's episodic value clause and its
> ceiling-slack clause, and nothing else of that section. §9's belief-budget clause —
> `RETRIEVAL_LIMIT` is 30 with `_DEFAULT_RETRIEVAL_LIMIT` held equal — its
> provisionality clause, and its clause replacing ADR-0160 §1's value and widening the
> evidence that moves the bound all stand and are relied on here.

Three of §9's five marked clauses survive untouched, and this ADR depends on each:

- **The belief-budget clause.** `RETRIEVAL_LIMIT` stays 30. Nothing here moves it, and
  §2's parity is stated against it.
- **The evidence-widening clause.** §9 replaced ADR-0160 §1's rule that only post-hoc
  attribution off a scored run may move the bound, widening it to admit *measured
  retrieval reach*. Without that widening this ADR would have no admissible evidence,
  because the #1844 replay is a retrieval-reach measurement. With it, the replay
  qualifies on both halves: it measures reach directly on pilot-5's as-run stores, and
  it converts through pilot-5's own scored answers. The remainder of that clause — that
  no separately registered ablation arm is owed — stands and is relied on here too, so
  this change owes no arm.
- **The provisionality clause.** *"Both values are provisional. Whatever the
  byte-budgeted single ranked pool ADR-0160 §5 leaves open decides replaces them, and
  pilot 5's post-hoc attribution (ADR-0160 §3) re-tests them."* It stands, and it has
  **worked**: the re-test it named has now happened, over pilot-5's stores, and it is
  this ADR's evidence. Naming an instrument and then being moved by it is the clause
  discharging rather than failing, and it stays live for the next move — the value at
  30 is no less provisional than the value at 10 was, and the byte-budgeted single
  ranked pool ADR-0160 §5 leaves open still replaces it when it lands.

The value clause and the ceiling-slack clause move **together**, and that pairing is
deliberate for the reason ADR-0162 §9 gave when it moved a value and an evidence rule
together: leaving standing a clause that says the ceiling is satisfied with slack while
setting the number that meets it would leave the corpus contradicting itself in the
direction hardest to notice — a reader would check the ceiling against a sentence
asserting slack and conclude the configuration was wrong.

### 4. The byte question: unmeasured, and now being spent from two directions

No byte bound is decided here. ADR-0007 §5's deferral of size caps and ADR-0160 §5's
two clauses stand exactly as ratified, including its second — *"The measurement that
would inform a byte bound is the scored run's per-question rendered-context size,
reported alongside the bucket figures"* — which is an obligation on the next scored
run and is not discharged by this ADR or by the replay.

**What this costs, stated at the resolution the evidence supports and no finer.**
ADR-0162 §10 measured the answering prompt at roughly **6.5k characters** at 30+10,
against ~4.4k at 15+15. The only per-episode figures in the corpus are #1029's
~35 tokens per additional episode, from the 5→15 move, and #1189's ~150 characters of
content per retrieved record on the pilot-3 mix. On those, twenty further episodes is
of the order of +3k characters — call it **~9–10k characters**, roughly 1.4× today's
answering prompt and a little over 2× the 15+15 baseline §10 measured against. That is
an extrapolation from two measurements taken on other corpora, and it is offered as an
order of magnitude, not a figure.

**ADR-0222's reply lines add to that total; they do not multiply with it, and the
distinction is worth getting right.** ADR-0222 §4 admits up to 736 characters per
rendered reply line and up to 14,720 characters across a twenty-turn tail. Those lines
land in the **conversation tail** and the observation batch only: §2 keeps the retrieved
group phrase-only, and §1's third clause keeps the line out of `_render_record`, which
is the function the episodic supplement's records are rendered through. So tripling this
bound multiplies nothing of ADR-0222's, and a reading that it does would overstate the
cost by an order of magnitude.

What is true, and is the reason this section exists, is that **both** additions land on
the same answering prompt in the same release, and both are drawn from the same
unbounded budget ADR-0158 §8 and ADR-0160 §5 left open. ADR-0162 §9 chose 10 over 15
partly because *"taking the smaller number spends less of an unmeasured budget"*. This
ADR takes the larger number and says so: it spends more of it, on better evidence than
§9 had, while that budget is being spent from a second direction at the same time. The
`context_chars` measurement ADR-0160 §5 named is therefore more owed after this change
than before it, and the first scored run after it should be read for that number as
much as for its buckets.

**The count guard is still a weak guard on volume**, exactly as ADR-0158 §3 said when
it chose 5 — an episode is a verbatim turn where a belief is a distilled sentence. That
argument has not been refuted; it has been outweighed, on this corpus, by a measured
accuracy gain the guard was costing.

### 5. What the follow-on implementation lane owes

> **Normative.** The implementing lane's edits are the episodic bound in
> `app/composition.py`, the corresponding default in `orchestration/loop.py`, the
> comments attached to both, and the tests pinning those two values. It adds no member
> to any Protocol, changes no field in `core/types.py`, and adds no `Settings` field.

> **Normative.** The lane keeps the two values equal to each other, and keeps
> `LearningLoop`'s construction-time refusal that a *stated* episodic bound may not
> exceed the belief budget. At parity that refusal accepts 30 against 30 and refuses 31.

> **Normative.** The lane changes **both** pinned ceiling assertions from
> strictly-less-than to not-greater-than — `tests/app/test_composition.py`'s
> `test_the_episodic_supplement_is_bounded_at_ten_and_never_above_the_beliefs` and
> `tests/orchestration/test_loop.py`'s
> `test_the_episodic_bound_is_ten_and_never_exceeds_the_belief_budget` — and updates
> each test's name and docstring, both of which are written to the slack reading §2
> replaces. Neither assertion merely reads oddly at parity; both fail.

It is one change under ADR-0137 §1 — two constants held equal by a stated contract plus
the tests pinning them — and it is the same cut the two prior moves of this constant
took (`101b5210`, `07d42fa6`), each of which touched exactly `app/composition.py`,
`orchestration/loop.py` and their two test modules.

Three further notes for that lane, from reading the tree rather than from memory:

- `tests/orchestration/test_loop.py` holds **both** shapes, and only one of them is
  free. `test_the_episodic_bound_is_ten_and_never_exceeds_the_belief_budget` pins the
  literal and the strict relation and must move, per the clause above. The
  *default-resolution* cases beside it assert **symbolically** —
  `min(_DEFAULT_EPISODIC_LIMIT, retrieval_limit)` — and stay correct without edit. Their
  behaviour changes even so: the cap in `LearningLoop.__init__` was a no-op for every
  construction stating a belief budget of 10 or more and now bites for every one below
  30, which is a wider band and worth a line in the constant's comment.
- `test_an_untuned_bound_at_the_belief_budget_is_the_default_itself` was named at
  parity, renamed away from it by ADR-0160 §7's lane, and describes the configuration
  again at 30 against 30. Its docstring's parenthetical about "ten against thirty" is
  the part that goes stale.
- `tests/benchmarks/` refers to the constant symbolically in three places and asserts
  `episodic_limit <= retrieval_limit`, which holds at parity. Nothing there is expected
  to move; the lane should confirm rather than assume it.

### 6. What this does not decide

- **The belief budget.** `RETRIEVAL_LIMIT` stays 30 by ADR-0162 §9's standing clause.
  Raising it — which is the only route to an episodic bound above 30, and which the
  replay's 60-arm makes newly interesting — is a separate decision on its own evidence.
  ADR-0162 §9's probe has the belief-side curve still climbing at 50 and 50+10 at 88.4%
  on reach; none of that is ruled here.
- **A byte bound on the prompt.** §4. ADR-0007 §5 and ADR-0160 §5 stand.
- **Anything about the supplement's read.** ADR-0158 §3's `kinds`, `bands`, ordering,
  tail deduplication, degradation behaviour and non-`DERIVED` revisit clause are
  untouched. This ADR moves one integer.
- **The sighted-read envelope of #1844** — a planner-emitted query, a sighted citation
  hop, a sighted outward fetch. The replay recommended against opening it now and
  ordered this change ahead of it; ADR-0222 §10 already records that ordering. Taking
  the allocation is not evidence for or against the envelope, and this ADR is not to be
  cited either way on it. What it does do is move the denominator every later
  measurement of that envelope is read against, which is a reason to re-price the
  envelope after this lands rather than before.
- **The trigger (#838).** The replay ranks it as the question worth spending on next.
  Nothing here bears on it.
- **Retrieval-triggered distillation.** ADR-0158 §8's deferral and #1178 stand, and §2
  above says why they remain the shape that resolves the thesis tension rather than
  balancing it.

### 7. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1 puts the judgement in the later ADR's text, where it is reviewed: a record
is owed on an earlier ADR exactly when this ADR amends or supersedes a named clause of
it, tested by whether a reader holding only that ADR would now act differently or read
one of its clauses more widely than it holds.

- **ADR-0162 — record owed, and it is a partial supersession.** Two named clauses of §9
  are replaced; a reader holding only ADR-0162 would configure 10 and would read the
  ceiling as slack. Its `Status` line already leads with `Partially superseded by`, so
  ADR-0070 §4's accumulation rule adds this ADR's pair to it without dropping the two
  already there, and ADR-0070 §1's dated note carries the substance. ADR-0082 §2's
  leading-token rule removes an *amendment* qualifier from such a line; it does not
  touch a supersession pair, which is what the leading token is for. The scope text
  names clauses and carries no `ADR-NNNN` token, so ADR-0070 §4's extraction invariant —
  every `ADR-NNNN` after the leading token is a target — holds.
- **ADR-0158 — no record owed.** §3's ceiling clause is *"never exceeds"*, and 30
  against 30 does not exceed. Every sentence of §3 stays true and none is read more
  widely: the second clause (the belief budget is never reduced or shared) is unaffected,
  and §3's value clause was replaced by ADR-0160 §1 and again by ADR-0162 §9, so it is
  not this ADR's to touch. §8's byte-bound bullet is left standing, undischarged.
- **ADR-0160 — no record owed.** §2's parity clause is *exercised*, which is the clause
  being used rather than changed; a reader holding only ADR-0160 acts identically. §5's
  two clauses stand and §4 relies on them. §7's clauses spoke to its own lane's edits and
  §1 was already superseded by ADR-0162 §9.
- **ADR-0222 — no record owed, and this is the one worth arguing rather than asserting.**
  §4's clause reads *"No other budget, ceiling or elision is introduced by this ADR. The
  tail depth, the retrieved group's size, `EPISODIC_SUPPLEMENT_LIMIT`,
  `observation_batch_size` and `observation_max_proposals` are all unmoved."* Its subject
  is what ADR-0222 does, and that stays true after this ADR: ADR-0222 still moves none of
  them. It is a scope-limiting clause, not a clause fixing those values — a reader
  holding only ADR-0222 does not learn the episodic bound from it, they learn that
  ADR-0222 did not touch it. ADR-0222's *unmarked* text does count the retrieved group
  with `EPISODIC_SUPPLEMENT_LIMIT` "being `10`", and that sentence goes stale as a fact;
  under ADR-0089 §3 unmarked text in a marked ADR supplies no obligation, and under
  ADR-0082 §1 a record is owed for a clause that fails ADR-0070 §1's test, not for a
  narration that ages. ADR-0222's own budget arithmetic is unaffected either way, because
  §2 keeps the retrieved group phrase-only and its 14,720-character figure is twenty
  **tail** turns.
- **ADR-0221 — no record owed.** Nothing here reaches the episode's `disposition`,
  `outcome` or `capture`, or any read filtered on them.
- **ADR-0223 — no record owed, and one interaction worth stating rather than burying.**
  Its §1 stamps a captured episode's `Provenance.derived_from_external` with
  `SelectionOrigin.over(turn.memories).planned_with_external_content` — the disjunction
  of `rests_on_recorded_external_content` over the records *that turn selected*.
  `LearningLoop` builds `memories = preceding + supplement`, so the episodic
  supplement's records are in that set and this ADR widens it. No clause of ADR-0223
  becomes false or is read more widely: the rule is a disjunction over whatever the turn
  selected, and it is stable under a wider selection by construction — which is precisely
  why §1 states it over `turn.memories` rather than over a fixed count. A reader holding
  only ADR-0223 acts identically. The *effect* is real, and Consequences records it
  rather than this section hiding it in a no-record finding.

## Consequences

**Easier.** The single cheapest lever the #1844 replay found is taken, for no model
call and no new machinery: ≈ +3.6 projected points of LoCoMo accuracy from the read
that already runs. Every later measurement of a sighted-read envelope is read against a
denominator that already contains this, which is what stops an envelope being credited
with recall the blind pass could have had for free. The implementing lane is one integer
in two places plus its tests.

**Harder.** The answering prompt grows by an unmeasured amount on a budget nobody has
bounded, in the same release as ADR-0222's tail reply lines, so the two together make
`context_chars` on the next scored run the number that matters most and the least
excusable to omit. ADR-0158 §3's ceiling is met, so the two constants are coupled again:
neither number moves alone, in either direction, and a lane that lowers the belief budget
must now expect to lower this bound with it. And the corpus has, for the first time,
refused a measured gain on principle — the replay's 60-arm — which is a decision this
ADR should be re-read against if the gain is ever re-measured larger.

**And more turns will be marked as resting on external content.** ADR-0223 §1 takes a
captured episode's `derived_from_external` as the disjunction of
`rests_on_recorded_external_content` over `turn.memories`, and the supplement's records
are in that set — `LearningLoop` builds `memories = preceding + supplement`. Tripling
the supplement can only widen that disjunction's *domain*, never narrow it, so the
effect on the flag is **non-decreasing**: it turns `True` on any turn where a newly
selected episode rests on recorded external content, and is unchanged on every turn
where the added episodes do not qualify or where the read and its tail deduplication
return no extra episode at all. Where it does turn, the `SelectionOrigin` the runner
hands the tools egress seam tightens with it. That is the field working as specified rather than a
defect — it is a disjunction over what the turn actually selected, and the turn now
selects more — but it is a live consequence of this integer that nothing here has
priced, and a lane watching egress behaviour after this lands should expect the rate to
move. It is also an argument *for* the ceiling in §2: the externality surface grows with
the supplement, not with the belief budget.

**What would revisit this.** The byte-budgeted single ranked pool ADR-0160 §5 leaves
open, which replaces both numbers rather than tuning them. A scored run whose
`context_chars` shows the answering prompt has outgrown what the models in use handle
well. A measured answer-side arm that fails to reproduce the projection in §1 — the
figure is a projection through pilot-5's buckets, and a run that widens the bound and
re-answers is what would confirm or refute it. And retrieval-triggered distillation
landing, which would make carrying thirty verbatim turns the wrong shape rather than an
expensive one.

## Alternatives considered

**1. 30+15 — the cheaper arm.** ≈ +1.3pt for half the added transcript. It is the arm a
conservative reading of the byte question picks, and the replay and #1294's step C both
offered it. Declined by the owner on 2026-09-02 in favour of the larger arm: the curve
has no knee, so there is no measured point at which the cheaper arm is the natural stop,
and the difference is 2.3 projected points of accuracy against prompt bytes that remain
unmeasured in either case. Recorded here because a reader should be able to see what was
given up, and because it is the arm to fall back to if `context_chars` says the prompt
has grown too far.

**2. 60, or the ceiling raised to permit it.** Measures ≈ +6.1pt and is refused by
ADR-0158 §3's ceiling at the current belief budget. Raising `RETRIEVAL_LIMIT` to unlock
it is a real option with its own evidence — §9's probe has the belief curve still
climbing at 50 — and it is a separate decision under ADR-0160 §6, not something to take
by implication while moving the other number. Deferred by name in §6.

**3. Setting a byte bound in this ADR, so the volume is bounded before it grows.**
Rejected for ADR-0160 §5's reason, unchanged: the measurement that would inform one is
the scored run's per-question rendered-context size, and it has not been taken. A bound
invented now would be a bound on a guess, and ADR-0222 §4 makes the same admission about
its own 640 — *"No measurement stands behind 640, and this ADR says so rather than
implying one"*. Two unmeasured bounds set in one release, interacting on one prompt,
would be worse than one measurement owed.

**4. Making the bound a `Settings` field so a deployment can choose.** Rejected for
ADR-0158 §5's reason, which this ADR does not reopen: how many episodes help an answer
is not a preference, it is a fact nobody has fully measured, and offering it as a knob
would imply a user could know it. The contrast that decides it is `episode_retention`,
which is a setting because ADR-0074 §7 makes it a privacy choice the user owns.

**5. A dynamic bound — the supplement capped at the number of beliefs actually
retrieved.** Rejected by ADR-0158 §3 and not reopened: it zeroes the supplement exactly
where the belief layer is emptiest, which is the population the capability exists for.
The replay strengthens that: 59.1% of multi-hop questions are total misses, and those
are the prompts where beliefs are thinnest.
