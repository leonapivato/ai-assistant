# 162. What the user tells the assistant is recorded, and selectivity moves to retrieval and forgetting

- Status: Partially superseded by ADR-0220 (§7's window-overlap clauses, as they reach an observation walk paged by the observation watermark) and ADR-0221 (§8's first clause alone — the observation prompt states the phrase for an episode's recorded `disposition` where it records one, and its `outcome` where it does not; §8's four other clauses and every other section stand)
- Date: 2026-08-19
- Amended: 2026-08-19 (§7 — its progress-over-overlap sentence names one instance of
  a property that has two). §7 rules that consecutive windows overlap by *k* episodes
  and states one exception, an `observation_batch_size` of 1, together with the reason
  that carries it: *"An overlap of 1 on a window of 1 advances the tiling by nothing,
  so no value satisfies progress and overlap together — a property of a one-turn
  window rather than something this section can repair."* **A window whose episodes
  have thinned to *k* or fewer can acquire that same property**, and §7 states the
  reason generally while naming only the one-turn instance of it. The second instance
  is recorded here:

  > **Normative.** Where a window holds no more than *k* episodes, progress takes
  > precedence over the overlap: the next window begins strictly after the turn this
  > one began at, and carries every episode of this one from that start onward. Where
  > honouring the overlap in full already begins the next window later than this one
  > began, this clause asks for nothing further and the clauses above are satisfied
  > whole. Where it does not, the carry is short by the episodes the advance drops,
  > and it is empty where the window resolved no episode at all.

  **When the two conflict, and when they do not.** `ObservationStage` holds no cursor
  and takes no offset: it reads a conversation's most recent `observation_batch_size`
  turns and nothing else (ADR-0077 §8, which §7 cites for exactly this). A window is
  therefore fixed by the turn it begins at, and a driver reaches the next one by
  deferring its call until the turns being dropped have been captured — it needs no
  new selection mechanism for any of this. A window holding **more** than *k* episodes
  hands over a proper tail of what it holds, which begins later than the window does,
  so the floor above is never its binding constraint and nothing here reaches it. A
  window holding *k* or **fewer** must hand over everything it has — and where its
  episodes reach back to the turn it began at, the window the overlap then demands
  begins where this one began, so it **is** this window, and so is every window after
  it: the tiling never advances and the walk never terminates. Where its episodes
  begin later, the demanded window begins later too, the floor does not bind, and §7
  governs whole; that window is then carried into a successor whose own episodes do
  reach its start, so the floor binds at the following pass instead. The walk is
  paced, not stalled: one turn per pass across a stretch of unresolvable turns until
  new material comes into reach. Honouring the overlap where it does conflict would
  also leave §7's own protasis, *"Where consecutive observation passes tile a sequence
  of episodes **rather than re-reading one window**"*.

  **What reaches it, and what removes it.** A window reaches the conflict only when at
  least `observation_batch_size − k` of its turns carry no resolvable episode. §7
  ratifies a bound on *k* rather than a value, so the rate is stated as that bound and
  not as a figure. ADR-0077 §8 rules that such a turn is skipped and the batch is not
  backfilled, and `ObservationStage._select` reaches that state from a failed episode
  write, an expiry or a `forget` alike, so this clause names no cause and turns on the
  shape it can see. §8 already rules the short window itself *"the honest consequence
  of a gap"*, its bound being *"a maximum rather than a quota"*; what this note settles
  is only which of two clauses yields where both cannot hold. In the harness driver §7
  binds today, a run in which the conflict can arise already carries a non-zero
  `turns_degraded`. The durable cursor ADR-0077 §11 filed, which §7's last clause names
  as ADR-0111 §1's walk, is what would remove the conflict rather than yield to it —
  and that clause already binds whoever builds it; nothing is designed for it here.

  **Classification: an amendment under [ADR-0070](0070-amendment-and-supersession-rules.md)
  §1, and the scope is what makes it one.** The floor binds only where honouring the
  overlap in full would leave the next window beginning where this one began, and there
  §7 demanded of a reader something no value satisfies — so no action it prescribed is
  abandoned, on either reading of the section. Read as §7's protasis and its stated
  property have it, the case was never inside the overlap clause; read with the
  exception list closed, the clause was unsatisfiable and no reader could act on it at
  all. **The two shapes that reach the floor are each unsatisfiable before this note in
  their own right.** A window holding *fewer* than *k* episodes has no *k* episodes to
  hand over, so the overlap asks it for something it does not contain, whatever a
  driver does. A window holding exactly *k* whose episodes reach its own start can
  satisfy the overlap only by being read again, unchanged, for ever. And where the
  floor does **not** bind — every window holding more than *k*, and every thinned one
  whose episodes begin later than it does — the overlap stays *k* episodes and nothing
  moves. Two readings of one section, one of which makes it demand the impossible, is
  the internal contradiction ADR-0070 §1 admits as an in-place amendment; it is not a
  decision being replaced, and the ratified clauses below are **not** rewritten. It
  names no other ADR as its cause, so it is a self-amendment and no `Status` edit is
  owed ([ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md) §1).
  The fork was raised against PR #1227's tiling driver, whose two lenses read the
  exception list as closed; the owner ruled it on 2026-08-19 under #1210 and it is
  recorded here rather than re-argued. Refs #1210, #1227, ADR-0070 §1, ADR-0077 §8,
  ADR-0111 §1.
- **Note (2026-08-19): ratified.** `Proposed` → `Accepted` on the content this ADR
  merges with, after **both** required lenses returned **`APPROVE` with no findings on
  one tree** — adversarial and architecture, the set the bullet below commits it to.
  `just ship` posts their terminal verdicts and the aggregate to PR #1219; the round
  count and the churn ratio are taken from that comment rather than restated here, so
  this note cannot disagree with it. That sequence is `CONTRIBUTING.md` → "Finishing an
  ADR PR", pointed at rather than re-argued.

  **Seven findings changed this text while it stood `Proposed`**, and each is named
  because none is a wording repair. Two arrived together on the first adversarial
  round: §1's completeness rule and §6's finite cap could both be in force and not both
  be satisfiable, so §1's clause now carries the bound as its own exception and §6
  reports a binding pass as **incomplete** with both knobs named; and §7's overlap
  bound was *empty* at an `observation_batch_size` of 1, which `Settings` permits, so
  *k* is 0 there as a stated exception. The second adversarial round found the
  over-limit recovery claim unbounded by ADR-0074 §7's horizon — "the episodes remain
  in the store" is a recovery only while they remain live — and §6 now says so.

  **The architecture rounds moved a ruling and the ADR's own classification.** §2
  imposed a told-versus-sensed rule with no carrier a producer could read while
  forbidding the available ones; the carrier is now deferred to the ADR introducing the
  second class of episode, on the surface-with-no-consumer ground, with a fail-closed
  obligation on the selecting stage meanwhile. Following that finding out found the
  wider one: §1 replaces a sentence that lives in `Observer.observe`'s docstring in
  `core/protocols.py`, so **this is a substantive contract ADR and the header declared
  the opposite**. It is corrected in place with §13 added to name what the implementing
  lane owes. The second architecture round then found §8 admitting the assistant's own
  assertion as warrant for a belief about the world — the laundering failure §8 now
  refuses — and the adversarial round after it found the two clauses that refused it
  overlapping, so they are partitioned by what a record *claims*: the assistant's act,
  which its `outcome` independently supports, against the proposition it asserted,
  which it never supports. The last finding completed §13's edit list, which had
  omitted `learning/observer.py`'s `DEFAULT_OBSERVATION_MAX_PROPOSALS` and said nothing
  about the canonical fake.

  **ADR-0070 §1's no-rewrite rule now protects this text**, so any further correction
  is an appended dated note.
- **A substantive contract ADR, and the ground is narrow and named.**
  [ADR-0015](0015-simplify-the-agent-workflow.md) §5 defines one as "adding or
  changing a Protocol or a `core/` type crossing subsystem boundaries". No `Observer`
  member, no signature and no field of `core/types.py` moves — but **a documented
  behavioural obligation of `Observer.observe` in `src/ai_assistant/core/protocols.py`
  does**: the bar paragraph beginning *"The bar for proposing at all is durable
  usefulness, not interestingness"*, which is the same sentence §1 replaces in
  [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md) §2 and which that
  module states as the producer-side obligation every conforming `Observer` carries.
  That module is where this corpus writes a Protocol's obligations and where
  [ADR-0100](0100-a-belief-states-whom-it-is-about-and-the-label-resolves-to-nothing.md)
  §5 put its own producer-side refusal, so changing a clause of it is changing the
  Protocol. **An earlier draft of this bullet declared the opposite and was corrected
  on review**, which is recorded because under-declaring is the error ADR-0015 §5
  exists to prevent: a lane editing `core/protocols.py` under golden rule 5 needs a
  ratified ADR behind it, and this is that ADR.

  **What follows from the declaration, and what does not.** Golden rule 5 and
  ADR-0015 §5's land-ahead rule govern: this ADR is its own PR, ratified and merged
  before anything implements against it, which is the shape this PR already has.
  **No triad is owed** — `CONTRIBUTING.md` → "Adding a Protocol" binds a *new*
  Protocol, and `Observer`, its conformance suite and its canonical fake all exist;
  §13 names the edits to each. The required review set is adversarial **and**
  architecture either way, which is what `CONTRIBUTING.md` → "Contract ADRs land
  before their implementation" asks of an ADR PR and what "Stop when the required
  reviews are green" asks of a change that decides a contract surface. Docs only, and
  **no code changes with it**: the implementation is its own lane (#1210's 2.4).
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
- **What moves on the contract, exactly.** One paragraph of `Observer.observe`'s
  docstring in `core/protocols.py` — the bar — and the reasoning (not the assertion)
  in the shared conformance suite's `test_no_proposal_states_a_subject`, whose
  docstring argues from the bar that a conforming proposal "has no non-owner subject
  to state". §3 keeps that test's refusal and supplies it a ground that survives §1.
  **Nothing else:** no Protocol gains or loses a member, no signature changes, no
  `core/types.py` field changes, and no `Settings` field is added or removed —
  `Settings` gains none for §7's overlap either, whose placement §7 leaves to the
  lane. §13 is the whole list.
- **Ratified on `CONTRIBUTING.md` → "Finishing an ADR PR", which is where that
  sequence is argued rather than re-argued here.** This ADR is drafted, reviewed and
  revised as `Proposed`; its status is flipped only once **both** required lenses —
  adversarial and architecture, per the bullet above — return clean on one tree, and
  that set is re-run on the flipped tree. A finding arriving after a flip returns it
  to `Proposed` and is folded there, per that block's step 3. The tense is
  deliberate: written prospectively, this bullet is true in both states the document
  passes through, so the ratifying commit changes the `Status` line and appends the
  note that names the set and its outcome, and nothing else.
- Refs #1210, #1029, #1179, #1185, #545, #1162, ADR-0077, ADR-0156, ADR-0158,
  ADR-0159, ADR-0160, ADR-0100, ADR-0121
- Partially superseded: 2026-08-29 by ADR-0220 — **§7's window overlap is forgone for
  an observation walk whose page is selected by the ADR-0212 watermark: *k* is 0 there,
  and nothing extends a page below the watermark its own pass read.**
  [ADR-0220](0220-the-watermark-driven-observation-walk-tiles-contiguously-and-forgoes-the-window-overlap.md)
  §1 rules the resolution and §6(a) names the scope; this note records the ruling declared
  there.

  **Replaced — §7's window-overlap clauses, only as they reach that walk.** §7's overlap
  clause and its floor of *k* ≥ 1 cannot hold together with
  [ADR-0212](0212-the-observation-cursor-is-a-per-conversation-watermark-on-the-conversation-index.md)
  §1's rule that "no later pass of a build that reads the watermark selects a turn at or
  below it", §3's page of "turns above its watermark … the lowest such page, not the
  tail", and §5's advance to "the highest ordinal in the page whose episode resolved". An
  overlap of *k* ≥ 1 is exactly such a re-selection, and the only way to buy it back is an
  advance to the highest resolved ordinal minus *k*, which §5 names no position for.
  ADR-0220 rules that ADR-0212's clauses stand. So §7's last clause — "these clauses bind
  … any durable-cursor walk (ADR-0111 §1) if one is built" — no longer reaches the walk
  ADR-0212 decides, and the benchmark harness's ingestion driver, once it drives such a
  build, tiles contiguously rather than overlapping. A reader holding only this ADR would
  build that walk with an overlap; that is ADR-0070 §1's test met.

  **Inside the scope: the bound on *k* goes with the clause it bounds.** "*k* is at least
  1 and at most `observation_batch_size // 2`" is one of the window-overlap clauses the
  scope names, so for a watermark-paged walk it is replaced rather than narrowed —
  otherwise a floor of 1 and a *k* of 0 would both be in force over one walk. §7's
  batch-of-1 exception and the 2026-08-19 amendment's progress-over-overlap floor are
  inside the scope for the same reason and in that walk only; neither is contradicted,
  both are left without work to do. ADR-0220 §6(a) states this.

  **Not replaced — every other application of §7, and every other section of this ADR.**
  Outside a walk paged by the watermark, §7 binds exactly as it did, bound on *k*,
  batch-of-1 exception, amendment floor and reasons whole: it binds the benchmark
  harness's driver while that driver drives a tail-reading build, it binds any tiling a
  later lane introduces elsewhere, and its clause making an episode carried in by an
  overlap "a full member of the window it is carried into" governs wherever an overlap
  exists. §1's completeness rule and every other section stand as ratified.

  **This ADR's `Status` gains the leading `Partially superseded by` token**, which under
  ADR-0070 §4 drops `Accepted`. No amendment qualifier was on the line, so ADR-0082 §2's
  move-to-the-note operation has nothing to carry. Appended note per ADR-0070 §1: no text
  below is rewritten and §7's clauses stand as written. This note lands in the same change
  as ADR-0220 itself, which is the existence condition ADR-0082 §7 states. Refs #1237,
  #1829, #1782.

- **Partially superseded: 2026-09-01 by ADR-0221 — §8's first clause and no
  other.** Design note **#1845** asks for the assistant's composed reply to be
  recorded on the episode, and ADR-0221 §1 puts it in `EpisodicMemory.outcome` — the
  field this ADR's §8 admitted into the observation payload. §8's first clause reads
  the field directly, so it can no longer say what it says without putting model prose
  in front of the observer.

  **Replaced — what the observation prompt states.** *"The observation prompt states an
  episode's `outcome` where the episode carries one, beside the label, the recorded
  instant and the `content` that ADR-0077 §3 and ADR-0156 §2 already put there"*
  becomes: the observation prompt states the phrase for the episode's `disposition`
  where the episode records one, and its `outcome` where it does not — beside the same
  label, instant and `content`. ADR-0221 §2 is the enum the phrase comes from, and the
  fallback is what keeps three populations rendering identically: a record written
  before ADR-0221 carries its phrase in `outcome` and no disposition, and renders it;
  a record written after carries the reply in `outcome` and a disposition, and renders
  the phrase; and a benchmark-harness row, which `benchmarks/memory/ingest.py`'s
  `exchanges_of` fills with the assistant's text and no disposition, renders that text
  exactly as it does today.

  **What is untouched.** §8's other four clauses bind unchanged — an episode is cited
  whole; what the assistant said independently supports a record of its own act; it
  never supports a record adopting the proposition it asserted; and it is never a
  licence to propose an `EpisodicMemory`. The third clause's phrase *"which the
  `outcome` field witnesses"* describes where a fact is stored rather than obliging
  anything, and ADR-0221 §4 reads it against the new field layout rather than
  superseding it. §8's widening argument on ADR-0077 §3 and ADR-0156 §2's ground is
  about the *record* and not the field's contents, so ADR-0077 §3's four refusals are
  untouched. So are §1's completeness rule, §2's classifier — an episode carrying a
  reply in `outcome` is still an episode whose `content` is what the user said, so it
  is a widening within §1's own episodes and not a second class — and every other
  section.

  **The two pairs on the `Status` line name different scopes** and accumulate under
  ADR-0070 §4: ADR-0220 reaches §7's window-overlap clauses and this one reaches §8's
  first clause. No amendment qualifier is on the `Status` line — the `Amended` line is
  its own — so ADR-0082 §2's move does not arise. Appended note per ADR-0070 §1; no
  text below is rewritten. This note lands in the same change as ADR-0221 itself, which
  is the existence condition ADR-0082 §7 states. Refs #1845, #1314, #1866.

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

> **Normative.** How an observer comes to know which rule a batch falls under is
> **not decided here**. It is the ADR introducing the second class of episode that
> decides it, and this ADR forecloses no shape that decision may take.

> **Normative.** Until such an ADR lands, a stage selecting a batch for a producer
> implementing §1 selects only episodes of §1's class, and a producer implementing §1
> is never handed one outside it.

> **Normative.** This ADR widens ADR-0077 §3's payload only as §8 does. Nothing
> enters the observation prompt to carry the told-versus-sensed distinction, and
> §3's four refusals — no existing beliefs, no profile, no context facet, no plan —
> stand verbatim.

**The asymmetry is the ruling, and it is not a compromise.** The user choosing to
tell the assistant something is a *speech act directed at the assistant*. A calendar
entry a reader ingested, a room a microphone was in, a mail file a fetcher replaced
whole — none of those is the user choosing to tell the assistant anything, and the
argument in §1 does not reach them. ADR-0077 §2's bar is the right rule for content
that arrives whether or not the user meant it to, and it keeps it. A later ADR may
revisit that when there is a sensor with a measurement behind it; nothing here
forecloses it and nothing here invites it.

**Why the carrier is deferred rather than designed, which is the corpus's own move
and not an evasion.** An observer cannot compute the class from an `EpisodicMemory`
it is handed: capture stamps `MemorySource.OBSERVED` on every episode it writes,
`participants` is left empty by design, and no field distinguishes a told episode
from a sensed one. So some carrier would have to be built — a field, a typed batch,
a second construction-time mode, a second `Observer` route — and every one of those
is a surface whose *shape* is decided by the consumer that needs it. There is no such
consumer. `EpisodicMemory` is constructed at exactly one site under `src/` —
`orchestration/conversations.py`'s `ConversationLifecycle._episode`, on the
conversation capture path — so every episode in the system today is §1's, and a
carrier ratified now would be designed against an imagined sensor. That is the
surface-with-no-consumer refusal ADR-0045 §1, ADR-0028 §7 and ADR-0092 §10 each made
in their own lane, and the one ADR-0099 §5 invokes to defer the subject axis's field
to "the first consumer that must distinguish".

**What is ruled now is the boundary, and it is ruled now for a reason.** Deferring the
carrier is not deferring the *rule*: §1's scope and the bar's survival outside it are
fixed here, so the sensor lane inherits a settled question about which rule applies
and an open one about how to say so. A boundary stated only after the sensor exists is
a boundary stated after the code that would have crossed it — which is what the second
clause fails closed against in the meantime, at no cost, because a stage that selects
from one producer of episodes cannot select from a second that does not exist.

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

> **Normative.** What the assistant said **independently supports** a record of its
> own act: that it was asked something, that it answered or did a particular thing,
> and when. That is a record of something that happened, which the `outcome` field
> witnesses, and it needs no further ground.

> **Normative.** What the assistant said **never supports** a record that adopts the
> proposition it asserted as a fact about the world or about the user. Such a record
> is proposed only where the user said it; `outcome` may corroborate or contextualise
> one grounded that way and supplies no warrant of its own for it.

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

**Why the assistant's assertions are not the user's, which is the same boundary §1 and
§2 rest on and the one this section could most easily have breached.** §1's rule is
that the user *told* the assistant something, and the assistant's own answer is not
that: it is the system's output. The two clauses above therefore partition by **what a
record claims** rather than by how much support it has — an act the assistant
performed, which the episode witnesses, against a proposition it asserted, which the
episode witnesses only the *saying* of. Admitting the proposition as warrant would let
the assistant launder its own assertions into the user's model — the assistant answers
"Paris is the capital of France", or worse a guess about the user, and a pass later
that assertion is a belief with the user's model behind it and an episode as its
citation. It is the same shape as the failure ADR-0077 §2 refuses one layer down when
it forbids a model-authored episode, "a fabricated event wearing the type reserved for
witnessed ones" that "later beliefs would *cite* as though it were evidence". Here the
fabrication would be a *belief* rather than an episode, and the type it wears is the
user's world model. What is legitimately supported, on the `outcome` alone, is the act
— "the assistant recommended the coastal route on 3 May" is something that happened,
and it is precisely the material LongMemEval's single-session-assistant questions ask
about (#1029 scores that arm at 50%). What is not is the proposition inside it: that
the coastal route *is* the better one is a claim about the world, and the assistant
having said so is not the user having said so. The same episode supports the first and
not the second, which is why the line is drawn at the record and not at the evidence.

**This is a producer-side obligation and it is not mechanically checkable, which is
said rather than glossed.** Which proposition supports a record is a fact about
meaning, so no field carries it and no conformance test sees it. That is the same
limit ADR-0077 §2 named of its own bar — "the half of that principle a gate cannot
enforce" — and that ADR-0100 §5 restated when it declined to claim its field made the
bar enforceable. So the clause lands in the prompt and in this text, where every other
producer-side obligation in this seam lands, and the honest claim is that it directs a
conforming producer rather than that it stops a non-conforming one.

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
- **How an observer is told which class a batch falls under.** §2 defers the carrier
  to the ADR introducing the second class of episode, on the corpus's
  surface-with-no-consumer ground, and fails closed until then.
- **Which participant is the user**, and any marker that would carry it. #1162's
  question is untouched: identity stays structural, and nothing here needs a marker,
  which is part of why §2 can defer its own carrier without pre-empting that ruling.
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
ADR-0100 §3's reading of an unstated subject is relied on rather than changed. What
§13 does put on the shared conformance suite is a restated *ground* for
`test_no_proposal_states_a_subject` — its docstring argues from the bar that a
conforming proposal "has no non-owner subject to state", and §1 makes that argument
false while leaving the refusal it justifies exactly as ADR-0100 §5 ruled it. A test's
reasoning is not an ADR's clause, so nothing is recorded against ADR-0100 for it; it
is named here because a reviewer reading §3 will look for the place the corpus's
prose goes stale, and this is it.

**ADR-0077 §3, ADR-0121 §1, ADR-0128, ADR-0158 §3, ADR-0159 §3 and ADR-0111 §1 —
relied on, not changed.** Each was checked by asking what this ADR relies on it *for*,
which is the method ADR-0084 §12 requires after a lexical enumeration missed ADR-0077
once. §8 rests on ADR-0077 §3's ruling admitting a field of the batch; §7 rests on
ADR-0121 §1's predicate and ADR-0159 §3's first rung doing the de-duplication;
§5 and §9 rest on ADR-0128's eligibility ordering and ADR-0158 §3's two budgets and
ceiling; §7's last clause rests on ADR-0111 §1's placement of a durable cursor. None of
them is asked to mean anything it did not already mean.

### 13. What the implementing lane owes, and what it may not touch

> **Normative.** The lane replaces `Observer.observe`'s bar paragraph in
> `core/protocols.py` with §1's rule, scoped as §2 scopes it. The `Output is bounded`
> paragraph beside it is untouched but for the figure §6 sets.

> **Normative.** The lane restates the ground of the shared conformance suite's
> `test_no_proposal_states_a_subject` docstring, which argues from the bar that a
> conforming proposal "has no non-owner subject to state". Its assertion is unchanged
> and its refusal is not weakened: §3 supplies the ground that survives §1.

> **Normative.** The lane's remaining edits are `learning/observer.py`'s `_PROMPT_HEAD`
> — §1's recording rule, and §8's boundary between what the user said and what the
> assistant asserted — and `_render_batch` (§8); `core/config.py`'s
> `observation_max_proposals` default with `learning/observer.py`'s
> `DEFAULT_OBSERVATION_MAX_PROPOSALS` held equal to it, and the comments stating their
> ground (§6); `app/composition.py`'s `RETRIEVAL_LIMIT` and `EPISODIC_SUPPLEMENT_LIMIT`
> with `orchestration/loop.py`'s two defaults held equal to them (§9); the tiling in
> `benchmarks/memory/ingest.py`'s `ingest_case` (§7); and the tests pinning each.

> **Normative.** The canonical fake in `ai_assistant.testing` changes in no respect,
> and `testing/observation.py`'s `DEFAULT_MAX_PROPOSALS` in particular **stays 5**
> rather than following §6.

> **Normative.** The lane adds no member to any Protocol, changes no signature, and
> changes no field in `core/types.py`. It opens no route by which an observer states
> `about_person` (§3), and it implements no part of §1 or §3 downstream of the
> producer — ADR-0100 §5's fourth clause binds unchanged.

**Why the canonical fake is on the list as an explicit non-change rather than absent
from it.** `FakeObserver` synthesises one `OBSERVED` belief per episode plus one
`INFERRED` over the first two, and its docstring says why: "a batch of *n* therefore
asks for more proposals than *n*, which is what makes the configured maximum bite". At
`DEFAULT_MAX_BATCH_SIZE` 20 that is 21 proposals against a maximum of 5. Taking the
fake's maximum to 40 would put 21 under it and stop the bound biting, retiring the very
clause the fake exists to exercise — so its number follows the *fixture's* purpose and
not a deployment's, which is the difference between a canonical fake and a default.
Nor does §1 oblige the fake to synthesise more records per episode: §1 is a rule about
which propositions a producer takes from real content, no clause of it is mechanically
checkable (§8's last paragraph gives the reason and ADR-0077 §2 with ADR-0100 §5 give
the precedent), and the shared suite gains no assertion here that a deterministic
script could fail. §13 says so rather than staying silent, because silence about the
third member of a Protocol's triad reads as an omission.

**Two things about the shape of that work, stated because they are the dispatcher's
and not this ADR's.** The edits cross `core/`, `learning/`, `app/`, `orchestration/`
and `benchmarks/`, which is more than `CLAUDE.md`'s one-subsystem rule admits by
default; whether that is one lane or several is a scoping decision, and the only thing
this ADR requires is that nothing implements against it before it merges (ADR-0015 §5).
And §7's *k* has no placement ruled here: a module constant and a `Settings` field are
both open, the latter being a configuration addition rather than contract surface, and
the argument that decides it is `observation_max_proposals`'s own (ADR-0077 §2) against
`EPISODIC_SUPPLEMENT_LIMIT`'s (ADR-0158 §5) — whether the right value is a thing an
operator can know about their corpus.

**What the lane does *not* inherit from §7.** The product's observation path tiles
nothing, so `orchestration/observation.py` is not on the list above. A lane that later
builds the durable cursor ADR-0077 §11 files inherits §7 at that point.


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
