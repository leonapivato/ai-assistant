# 158. An episode may supplement the answering prompt, and never shares the belief budget

- Status: Accepted
- Date: 2026-08-15
- **Changes no Protocol's *shape* and no `core` type's fields, and widens the
  documented semantics of two — flagged under golden rule 5 rather than smuggled.** The read §1 admits is
  `MemoryStore.search` called with a different `kinds` argument, which
  [ADR-0072](0072-the-profile-and-the-inferred-model-are-bands-of-one-store.md) §5
  already rules is the caller's to choose; no member is added, no signature moves,
  and no field or shape in `src/ai_assistant/core/types.py` changes. But §4's
  ordering makes the assembled sequence carry **three** meaningful groups where it
  carries two, and the wording both `Planner.plan`'s `memories` and
  `TurnResult.memories` share — "then the records retrieved as relevant, best
  first *within that group*" — does not describe a post-tail region holding beliefs
  ahead of episodes. That is a change to a Protocol's and a `core` type's
  documented meaning, so [ADR-0015](0015-simplify-the-agent-workflow.md) §5
  governs. §5 below states both widened contracts and §7 puts the two docstrings
  in the implementing lane's hands, which is exactly the form
  [ADR-0074](0074-conversation-is-an-entity-and-every-turn-is-an-episode.md) §5
  took for the first widening of this same sequence.

  **No triad is owed.** `CONTRIBUTING.md` → "Adding a Protocol" binds a *new*
  Protocol; `Planner` is not new, and its conformance suite and canonical fake
  exist. The required review set is **adversarial and architecture**, both because
  of the widening and because the decision space §5 surveys includes a
  `MemoryStore` member and a `core.config.Settings` field and rules against both —
  a ruling *against* surface still binds the implementing lane's surface. **No code
  changes with this ADR**; the implementation is #1163's lane 7, which needs this
  text as its authority.
- **Ratified on `CONTRIBUTING.md` → "Finishing an ADR PR", which is where that
  sequence is argued rather than re-argued here.** The required set is adversarial
  **and** architecture (above). This ADR is drafted, reviewed and revised as
  `Proposed`; its status is flipped **only once both return clean on one tree**,
  and both are re-run on the flipped tree. A finding arriving after a flip returns
  it to `Proposed` and is folded there, per that block's step 3 — this ADR took
  that route once, so it records its ratification on its second flip. Nothing
  implements against it until it has merged (ADR-0015 §5, golden rule 5).

  **The tense is deliberate.** Written prospectively, the bullet is true in both
  states the document passes through, so the ratifying commit changes the `Status`
  line and nothing else — which is what makes that block's step 3 round "cheap by
  construction: the flipped tree differs from the one already judged by a status
  line".
- **Partially supersedes:**
  [ADR-0022](0022-the-closed-learning-loop.md) §3's Retrieval row, in the scope of
  the episodic supplement's own read. That row assigns one outcome to the retrieval
  stage's failure — *"degrade to no memories, `memory_degraded=True`"* — and §4
  below gives a failing supplementary read a different one: the belief composition
  already in hand is kept and the flag is not set. [ADR-0070](0070-amendment-and-supersession-rules.md)
  §1's test decides the form and decides it against an amendment: the replaced
  clause is a **rule an implementer obeys** rather than an explanation of one, and
  a reader holding only ADR-0022 §3 would, on that failure, discard a good belief
  composition and report an unpersonalised answer that was not one. So it is a
  partial supersession, taking ADR-0070 §3's form and §4's status vocabulary.

  **ADR-0022's `Status` line and dated note land in this same change, with the
  `Proposed` commits and not deferred to the flip.** That is this corpus's
  established form rather than a novelty. ADR-0074's own note for ADR-0076 states
  the protection in terms — the superseding ADR "lands **in the same change as
  this note**, so this Status line never names an ADR that does not exist — the
  hazard ADR-0070 §1 guards against — and if that change does not land, neither
  does this" — and this ADR carries that sentence into ADR-0022's note verbatim in
  shape. ADR-0042, ADR-0045 and ADR-0073 add the sentence naming the intermediate
  state directly: while the superseding ADR is still `Proposed`, the line names a
  supersession that is **drafted rather than ratified**, "the form ADR-0075
  established", which `main` has carried since ADR-0005 was marked for a
  still-`Proposed` ADR-0075 (ADR-0076's header records that precedent). ADR-0083
  §15 rules the objection outright: "**The existence condition is that the naming
  ADR ships in the same change, not that it has ratified.**" So what protects the
  reader is the atomicity of the *change*, not of the commit.

  **It is staged with the `Proposed` commits because that is where it is
  reviewable.** The dated note is not ceremony: it states which clause is replaced
  and what survives, which is the same substantive determination §4 makes and is
  reviewable only while the decision can still change. ADR-0070 §1 says the
  ratifying edit "records that review's outcome, it does not replace it", and
  `CONTRIBUTING.md` → "Finishing an ADR PR" says of the post-flip round that
  nothing in it "triages a status line" — so a note staged at the flip would land
  with its substance never reviewed. The opposite exposure is bounded by
  comparison: the only tree from which a reader could resolve ADR-0022 to a
  decision still open is this unmerged branch, and ADR-0070 §1 keeps a repair path
  even for a supersession that never lands at all — restoring the `Status` line,
  which changes no decision.

  **The supersession takes effect on ratification, and ratification is this
  change merging.** The two are one event because the two files are one change: the
  `Proposed` → `Accepted` flip is the ratifying edit, made in this PR's final
  commit, and no reader of `main` ever sees ADR-0022 pointing at an unratified
  ADR-0158.

  **The scope is one row read against one read, and nothing else.** ADR-0022 §3's
  rule for the *belief* composition is untouched and still governs
  `ai_assistant.orchestration.loop`: a failure there degrades to no memories with
  `memory_degraded=True`, all-or-nothing across the bands, exactly as today. §3's
  framing sentence — "a stage aborts the turn when continuing would require
  inventing something; otherwise it degrades and says so" — is not replaced and is
  what §4's clause obeys: a supplement's absence invents nothing, and the paragraph
  under §3's table, on why `memory_degraded` is on `TurnResult` at all, is the very
  reasoning §4 applies to conclude the flag must **not** be set here. Every other
  row of the table, and every other section of ADR-0022, stands.
- **Amends and supersedes nothing else.** Applying
  [ADR-0070](0070-amendment-and-supersession-rules.md) §1's test, no clause of a
  prior ADR is replaced here. The contestable case is
  [ADR-0074](0074-conversation-is-an-entity-and-every-turn-is-an-episode.md) §6's
  sentence *"The turn's relevance retrieval passes a `kinds` filter excluding
  `EPISODIC`, so a captured turn does not compete with beliefs for the retrieval
  budget"* — and §2 below **keeps it, verbatim and for its own reason**. The
  belief composition's `kinds` filter still excludes `EPISODIC`, and an episode
  still never competes with a belief for the retrieval budget; what §3 adds is a
  *second* budget the belief composition does not draw on. A reader holding only
  ADR-0074 §6 would act identically on the clause this ADR touches, which is
  ADR-0070 §1's own test for an amendment being unnecessary rather than merely
  available. ADR-0074 §6's other half — the belief listing's default — is not
  reached at all. What is collected rather than replaced is ADR-0074 §11's
  **deferral**, which is an open item rather than a ruling, and
  [ADR-0112](0112-currency-never-ranks-and-retrieval-orders-by-relevance.md) §9's
  hand-off of its remaining half to **#791** (§1).
- **Refs:** #791 (the deferral's surviving half, and the framing this ADR takes
  up); #1029 (the scored pilot, its results comment of 2026-08-14 and its
  error-anatomy addendum of 2026-08-15 — the measured consumer); #1163 (the batch;
  lane 7 is the implementation, and the ablation arm is later still); #545
  (episodic memory as multi-channel — read as context, ratified in no part; §4's
  revisit trigger is where its calendar channel would land); ADR-0005 §1
  (`EpisodicMemory`, the four kinds, and `content` as a canonical rendering), §2
  (`Provenance`, and `evidence` as episode references); ADR-0022 §3 (failure
  behaviour stage by stage — the Retrieval row this ADR partially supersedes, and
  the framing sentence and `memory_degraded` rationale it does not); ADR-0084 §2
  (`TurnResult` is `core` contract surface — why §4 declines to widen
  `memory_degraded`'s meaning, and why §5 ratifies `memories`' rather than leaving
  it to a lane); #1175 (the `Planner.plan` wording this ADR widens is separately
  stale against ADR-0113's band composition — filed, not fixed here); ADR-0007 §2
  (retention
  enforced at read time), §5 (size caps deferred); ADR-0015 §5 (what a substantive
  contract ADR is); ADR-0028 §7 (batch ingestion declined for want of a consumer);
  ADR-0045 §1 (as-of retrieval declined on the same ground); ADR-0070 §1 (the
  amend-versus-supersede test; the permitted header edits, and the ratifying edit
  recording a review's outcome rather than replacing it); ADR-0074's ADR-0076 note,
  ADR-0042's, ADR-0045's and ADR-0073's (the in-change supersession note, and the
  `Proposed`-state sentence ADR-0075 established); ADR-0076's header (ADR-0005
  carrying a supersession by a still-`Proposed` ADR-0075); ADR-0083 §15 (the
  existence condition is shipping in the same change, not ratification);
  ADR-0072 §1 (one store), §2 (`band_of` is total),
  §3 (what a derived belief owes), §5 (search is band-neutral and
  confidence-neutral; precedence is the consumer's and is by band; the flood
  argument), §6 (confidence is presentation, not ranking), §7 (a read's signature
  deferred for want of a consumer); ADR-0073 §1 (`None` means every value);
  ADR-0074 §3 (every turn is an episode), §5 (continuity reaches the planner
  through `memories`), §6 (retrieval selects the belief kinds; the deferral), §7
  (the episode horizon, and why its default is finite), §11 (the deferral list);
  ADR-0077 §1 (the observer reads episodes it is handed), §2 (what it may
  propose); ADR-0086 §6 (`get_many` is on the contract); ADR-0088 §1 (citation
  forms); ADR-0089 §1–§3 (what is marked, and what marks bind); ADR-0103 §5
  (decay parameters deferred to leg 8's measurement); ADR-0112 §1 (no quantity
  joins the retrieval order), §5 (the band-scoped read), §9 (the ordering half
  closed, the budget half handed to #791); ADR-0113 §2 (a call may return fewer
  than `limit` while eligible records exist), §5 (no cross-call consistency; the
  deduplication obligation), §6 (the budget and the assembly order are the
  consumer's), §8 (headroom declined without #789's measurement); ADR-0119 §3
  (`TRACE_RECORD_SET_CAP`); ADR-0128 §1 (every eligibility predicate binds before
  the ranking cut), §2 (`capped`); ADR-0156 (the temporal anchor, the other half
  of the pilot's distillation finding).

## Context

### The deferral, and the half of it that survived

ADR-0074 §6 rules that a turn's relevance retrieval passes a `kinds` filter
excluding `EPISODIC`, "so a captured turn does not compete with beliefs for the
retrieval budget", and defers cross-conversation episodic recall — *"what did we
discuss last Tuesday?"* — **with its ranking question**. ADR-0074 §11 lists it as
due with leg 7's retrieval-under-load work.

ADR-0112 §9 is that lane, and it answered rather than passed on:

> **Its ordering half closes here**: the axis is relevance, kinds are the
> caller's argument as ADR-0074 §6 already rules, and no quantity joins the
> order, so "mixing raw turns with distilled beliefs in one relevance cut" is not
> an ordering question but a *budget* question — how much of a turn's retrieval
> budget episodes may take, and from which consumer's decision.

It then filed the remainder on **#791**, on the repository's standing discipline:
"That half has no consumer, and the repository's standing discipline is to defer
surface until one exists (ADR-0072 §7, ADR-0045 §1, ADR-0028 §7)."

So there is no ranking design left to do. An episode and a belief compete on
relevance exactly as two beliefs do. What #791 carries is a **budget** question
and a **consumer** question, and this ADR answers both.

### The consumer arrived, and it is measured

The scored benchmark pilot (#1029) ran both corpora from the frozen ref
`bench-pilot-1`, with `ASSISTANT_EPISODE_RETENTION=none` — which
`core.config.Settings.episode_retention` documents as "keep episodes forever", not
as "capture none of them". Every conversation turn of every dialogue was therefore
captured as an `EpisodicMemory`, embedded, and still in each case's store when the
error anatomy read it.

The addendum of 2026-08-15 decomposes LoCoMo's 1,540 answerable questions:

| Bucket | LoCoMo | LongMemEval |
|---|---|---|
| correct | 118 | 10 |
| attempted, wrong (gold in prompt) | 69 | 5 |
| gold in prompt, declined | 416 | 23 |
| gold distilled, ranked below cut | 277 | 3 |
| **gold never distilled into any belief record** | **652** | **9** |
| no usable gold mapping | 8 | 0 |

**652 of 1,540 — 42% of the answerable set — failed because the fact never became
a belief.** Ingestion recall was 56.7% on LoCoMo (each ~300-turn dialogue
distilling to 17–42 beliefs) and 82% on LongMemEval. The addendum's own reading is
that this residual is structural rather than a tuning miss: "observation is tuned
for first-person dialogue; LoCoMo is third-person", and the estimated headroom
from the pilot-2 fix lanes is "roughly +8–14 points LoCoMo — still far below P1's
predicted range, which is itself a finding".

For every one of those 652 the gold turn sat in the same store, in the same
embedding index, unreachable only because `orchestration/loop.py` asks for
`BELIEF_KINDS`. That is the consumer #791 was waiting for: not a hypothetical
capability, a quantified loss with the evidence already paid for.

### Three facts about the tree that make this a decision rather than a one-line change

**An episode is in the same band as an observed belief.** Capture stamps
`Provenance(source=MemorySource.OBSERVED, confidence=CAPTURE_CONFIDENCE)` in
`ai_assistant.orchestration.conversations`, and `ai_assistant.core.types.band_of`
maps `OBSERVED` to `BeliefBand.DERIVED`. So every episode this system holds is a
`DERIVED`-band record, sitting in the same band as every belief the observer
proposed.

**Band composition therefore contains nothing here.**
`ai_assistant.orchestration.retrieval.assemble_by_band` fills **one** budget in
`BAND_PRECEDENCE` order — `ASSERTED`, then `ATTESTED`, then `DERIVED` — each call
asking for whatever remains. Adding `EPISODIC` to its `kinds` would put episodes
and derived beliefs into the *same* band-scoped call, competing for the same
remainder. The one containment the assembly has does not apply to the one pair it
would need to separate.

**`kinds` binds before the cut, so this is not recoverable downstream.**
ADR-0128 §1 rules that every eligibility predicate becomes a `rowid` restriction
carried into the KNN itself: "an ineligible row never enters the candidate set and
never spends a candidate slot the cut is taken from". Read the other way, a row
made *eligible* does spend such a slot. Admitting episodes to the belief read is
not a matter of ordering the results afterwards; it changes which records exist to
be ranked.

### The budget the pilot's other lane just bought

The answering budget moved 5→15 in this same batch, and
`ai_assistant.app.composition.RETRIEVAL_LIMIT` records why in its own words: of
the 277 rank misses, "the gold-citing record's median cosine rank was 12, and 114
of 277 sat at ranks 6 to 10. A budget of 5 cut the answer off above almost all of
them; 15 covers about 80% of that population". It also prices it: "5 records
filled roughly 4KB, so this is about three times that in the prompt, per turn."

That budget was bought for *beliefs*, on measurement, days ago. Any design that
spends part of it on episodes is undoing a measured change with an unmeasured one.

### The thesis tension, stated as the owner states it

The product's claim is an accumulated user model — beliefs that are distilled,
corrigible, inspectable, and carry their provenance. Retrieval over the raw
transcript is a different product: retrieval-augmented generation over a chat log,
which is a solved commodity and is not what the belief layer is for. A system that
answers from episodes because its distillation is lossy has not fixed its
distillation; it has stopped depending on it, and the belief layer becomes an
ornament that no answer needs.

That tension is real, and it is not resolved by refusing the capability outright
either — a refusal leaves 42% of a measured answerable set permanently
unanswerable from a fact the system demonstrably holds. It is resolved by *where
the boundary sits*, which is what this ADR draws.

## Decision

### 1. The capability is admitted: an episode may reach the answering prompt

> **Normative.** An answering turn's prompt may carry `EPISODIC` records
> retrieved by relevance, subject to §§2–4.

#791's budget half and its consumer half are answered here, and the deferral is
not renewed.

The trigger #791 names first — "a user-facing capability that actually wants
cross-conversation recall" — has fired in the only form this repository can
currently produce. The benchmark is not a user, but the behaviour it scores is a
user-facing one: *answer a question about something the user said*. 42% of that
set fails for want of exactly this read, and the pilot's own reading says the
distillation loss behind it is structural rather than a tuning defect the
ingestion lanes will absorb.

The three deferral precedents #791 leans on all turn on the same condition and it
no longer holds. ADR-0072 §7, ADR-0045 §1 and ADR-0028 §7 each declined surface
"for want of a consumer"; the consumer is now quantified, and — unusually — the
substrate it needs is *already fully paid for*. Episodes are already captured
(ADR-0074 §3), already stored in the one store (ADR-0072 §1), and already
embedded: `ai_assistant.memory.sqlite_store` embeds every record it is given and
special-cases no `MemoryKind`. The store carries the write cost, the vector index
carries the space cost, and the re-embed path carries the migration cost, today,
for records nothing reads. Declining the read does not save any of that.

**A refusal was considered on its merits and is recorded in Alternatives
considered**, because "the ADR's job is to decide, not to admit" cuts both ways:
this section admits the capability, and §§2–4 are what stop the admission from
being unbounded.

### 2. `EPISODIC` never joins the belief kinds

> **Normative.** `ai_assistant.orchestration.conversations.BELIEF_KINDS` remains
> the `kinds` argument of the answering turn's belief composition, and
> `MemoryKind.EPISODIC` is never added to it.

> **Normative.** No caller passes a kind set to
> `ai_assistant.orchestration.retrieval.assemble_by_band` that contains both
> `EPISODIC` and any belief kind.

ADR-0074 §6's sentence is kept whole and for its own reason: a captured turn does
not compete with beliefs for the retrieval budget. What §3 adds is a second
budget, not a widening of this one.

**The ground is ADR-0072 §5's flood argument, transposed one level down.** §5
refuses a band-neutral top-k in terms that need only their nouns changed:

> A band-neutral top-k followed by a post-hoc partition does not implement
> precedence: a flood of low-confidence inferences can displace an assertion
> *below the cut*, where no amount of downstream ordering recovers it.

Put raw turns where the inferences are and a distilled belief where the assertion
is, and the sentence is this section. It is stronger here than there, in three
ways:

- **The band composition offers no protection.** Every episode is `DERIVED` by
  construction (Context), so episodes and observed beliefs land in the *same*
  band-scoped call. The precedence order ADR-0072 §5 built to stop exactly this
  displacement does not separate the one pair that needs separating.
- **It is a candidate-set effect, not a sorting effect.** ADR-0128 §1 binds
  `kinds` before the KNN cut, so an admitted episode spends a candidate slot the
  cut is drawn from. There is no downstream pass that can put the belief back.
- **The ratio is not close.** A store holds roughly one belief per distilled fact
  and one episode per turn. The pilot's own figures: 17–42 beliefs distilled from
  ~300 turns, an order of magnitude in the episodes' favour, on a corpus whose
  ingestion recall was 56.7%. Under a shared budget of 15 the belief layer would
  frequently be absent from its own answering prompt — not occasionally
  outranked, routinely displaced.

That last figure is the thesis tension made mechanical. "The system becomes naive
RAG over the transcript" is not a slippery-slope worry about this design; it is a
prediction about *the one-line version* of it, and it is the version this section
refuses by name.

### 3. The supplement is a second read with a bound of its own, and that bound never exceeds the belief budget

> **Normative.** The episodic supplement is a separate `MemoryStore.search`
> restricted to `kinds=(MemoryKind.EPISODIC,)` and to
> `bands=(BeliefBand.DERIVED,)`, bounded by a budget of its own.

> **Normative.** The belief composition's budget is never reduced, shared with the
> supplement, or made conditional on it.

> **Normative.** The configured episodic bound never exceeds the configured
> belief budget.

> **Normative.** The episodic bound's ratified initial value is **5**, against a
> belief budget of 15. It moves only on the measurement §6 specifies.

**Two budgets rather than a share of one.** A share — "episodes may take 20% of
the budget" — was the shape most obviously available, and it is wrong here for a
dated reason: `RETRIEVAL_LIMIT`'s 5→15 move was bought days ago on the pilot's
rank-miss measurement, for beliefs. A share takes part of it back on no
measurement at all, and takes it precisely in the deployments where the belief
layer is working and its budget is full. Two budgets cost prompt size, which is
the honest cost; a share costs belief recall, which is the cost that hollows the
thesis.

**The ceiling clause is where the thesis is actually expressed.** Every other
statement of "beliefs are the product" is documentation; this one is checkable and
survives future tuning by whoever tunes it: whatever the numbers become, nobody
can configure a system that asks for more transcript than belief.

**It bounds the configuration and not the prompt, and the gap between those is
real rather than an oversight.** ADR-0113 §2 refuses a full-page guarantee
outright — "a call may return fewer than `limit` records while eligible ones
exist" — so a query matching two beliefs and five episodes yields an
episode-majority prompt under any bound at all (a query matching *no* beliefs is
§4's separator case and drops the supplement entirely, for an unrelated reason).
That case is **accepted**, because
it is not the case the ceiling exists for. The hollowing risk §2 identifies is an
episode *displacing* a belief below a shared cut; a belief that was never
retrieved was not displaced by anything, and a prompt thin in beliefs is thin
because the belief layer had nothing to offer that query. Withholding episodes
there would withhold them precisely where nothing else can answer.

**A dynamic cap at the number of beliefs actually retrieved was considered and
rejected for that reason.** It reads as the stricter rule and is the wrong one: it
zeroes the supplement exactly where the belief layer is emptiest — a new user
whose store holds no distilled beliefs yet, or a topic the observer never reached
— which is the population §1 admits the capability for. It is also the count-shaped
fallback of Alternatives considered 4 with its sign flipped, and it inherits that
alternative's defect: a count of retrieved beliefs says nothing about whether they
answer the question.

**And the count bound is a weaker guard on volume than it looks — stated rather
than glossed over.** An episode is a verbatim turn; a belief is a distilled
sentence. `RETRIEVAL_LIMIT` prices 5 belief records at roughly 4KB, and there is
no comparable figure for 5 episodes because nothing has measured one. So 5 is
chosen as the value at which the count guard and a plausible *byte* parity roughly
meet, and it is stated as a judgement rather than as a measured optimum. §6 puts
prompt bytes in the arm's required output for this reason, and §8 leaves a byte
bound undecided — ADR-0007 §5's deferral of size caps stands untouched.

**Why not zero.** A bound of zero would ship the path dead in every deployment and
would be a deferral wearing a ruling's clothes. This corpus sets a cardinality
control to a defensible number and moves it on evidence — `RETRIEVAL_LIMIT` itself
began at 5 with no measurement behind it and moved to 15 with one — and §6 pairs
the initial value with a retraction condition, so the commitment is falsifiable
rather than one-way.

**One call rather than a band composition — bought by pinning the band, not by
assuming it.** Capture stamps `MemorySource.OBSERVED` unconditionally, so every
episode *this system writes* is `DERIVED` and a band-precedence composition over a
kind set of one would be three calls where one serves, ordering nothing. But the
store's episodic namespace is not closed to capture: `EpisodicMemory` accepts any
valid `Provenance`, ADR-0074 §3 reserves an id namespace precisely because "a
foreign producer took an id in the reserved namespace" is a fault it has to
contemplate, and `tests/orchestration/test_conversations.py`'s `_foreign_episode`
fixture constructs an `EXTERNAL`-sourced episodic record today. `band_of` maps
`EXTERNAL` to `ATTESTED`, so a band-blind flat read could put an `ATTESTED` record
into a bare relevance order beside `DERIVED` ones — bypassing the precedence
ADR-0072 §5 exists to impose, in the one read that has no composition to impose it.

So the band is **pinned**, not left at `None`. The single call is then correct by
construction rather than by an assumption about who writes: an episode outside the
`DERIVED` band is simply not retrieved, which is the conservative direction, and
the shape stays one call. The filter is on the *band* rather than on the source
because band is what ADR-0072 §5's precedence is defined over; an `INFERRED`-sourced
episode is `DERIVED` and is retrievable, and nothing about precedence turns on the
difference.

> **Normative.** The first `EPISODIC` record this system means to make retrievable
> from outside the `DERIVED` band is a decision of its own, and takes an ADR that
> settles how the supplement composes across bands.

That is where #545's calendar channel would land if it is ever adopted. Until such
an ADR, a non-`DERIVED` episode is out of the supplement's reach rather than
silently mixed into it — the difference between this clause and a bare revisit
note, and the reason it is stated as one.

### 4. Where the supplement sits in the prompt, and what it may not repeat

> **Normative.** The order of `memories` is the continuity tail (ADR-0074 §5),
> then the retrieved beliefs, then the episodic supplement — appended whole, never
> interleaved.

`ai_assistant.orchestration.loop` composes the turn's `memories` as
`recent + retrieved` today; this makes it `recent + retrieved + supplement`.

Position is how this corpus expresses precedence into a prompt — ADR-0072 §5's
assembler "fills its budget `ASSERTED` first, then `ATTESTED`, then `DERIVED`",
and the ordering *is* the precedence. A distilled belief outranks the raw turn it
was distilled from for the same reasons the belief layer exists: it has passed the
propose/dispose gate, it carries provenance and confidence, it is corrigible, and
it is what the user can inspect and kill. An episode is unjudged material. Sorting
the two together by relevance would restore §2's displacement in the renderer
immediately after refusing it in the reader, and would do so invisibly, because
nothing downstream reports which kind won a position.

**This clause is a compatibility requirement as well as a design choice, and the
planner already states it.** `ai_assistant.planning.planner` splits the records it
is handed into the conversation tail and the retrieved group by taking the
**leading run** of `EPISODIC` records — a prefix split, chosen because ADR-0074 §5
fixes the order and "a partition by kind could" reorder the sequence. Its docstring
then names this ADR's case in advance: "If the cross-conversation episodic recall
§11 defers ever lands, an episode retrieved *by relevance* arrives after the tail
and stays in the retrieved group, which is the group it belongs to." Appending is
therefore what the renderer was written to expect. Any other placement is a defect
rather than a preference: a supplement inserted between the tail and the beliefs
would extend the leading run, and the planner would render relevance-retrieved
episodes from other conversations **as this conversation's recent turns**.

**And a prefix split needs a separator, which the belief group only usually
supplies.** The split ends at the first non-`EPISODIC` record, so any belief at all
between the tail and the supplement keeps the two groups apart — three beliefs and
five episodes render correctly. Where the belief composition comes back *empty*,
there is no separator: the tail and the supplement form one unbroken run of
`EPISODIC` records, and the whole of it renders under the tail's heading. §3
accepts a thin or empty belief read as a normal outcome, so this is a reachable
state and not a corner.

> **Normative.** The supplement is appended only where the records preceding it
> contain at least one non-`EPISODIC` record. Where they do not, the supplement is
> dropped.

**This is a renderer constraint, stated as one, and it is narrow.** It is not the
dynamic cap §3 rejects: that would throttle the supplement in proportion to belief
richness across its whole range, penalising the sparse case everywhere. This
withholds it in exactly one degenerate state, and for a reason that is about the
prompt's group encoding rather than about how much transcript is appropriate.

**The cost of getting it wrong is a fabrication, not a thinner prompt.** An episode
retrieved by relevance from a conversation three weeks ago, rendered under "recent
conversation turns", tells the model the user said it moments ago. That is a false
claim about continuity, produced silently, and it is worse than the supplement
being absent. Dropping is therefore the conservative direction, and it is where a
positional encoding has to yield.

> **Normative.** Carrying an explicit tail/retrieved boundary to the planner, which
> would remove the clause above, is a `Planner` contract change and takes its own
> ADR.

ADR-0074 §5 refused a `history` parameter on `Planner` because "both groups are
`MemoryRecord`s the planner already renders and a second channel would split one
prompt input in two **for a distinction it does not act on**." That premise has
moved: the renderer now acts on the distinction — it labels the groups
differently — and a second episodic group is what makes position insufficient to
carry it. This ADR does not reopen that refusal, because doing so is golden rule 5
surface and the supplement is deliverable without it; it records that the ground
the refusal stood on has changed, so the next lane to reach it is not arguing from
a stale premise.

> **Normative.** An episode already present in the continuity tail is not repeated
> by the supplement; the tail's copy is kept and the supplement's is dropped.

This is not hypothetical bookkeeping. ADR-0074 §5 puts the conversation's recent
turns into `memories`, and ADR-0086 §6's `get_many` is how
`ConversationLifecycle.history` fetches them — they are records of the same store,
with the same ids, of kind `EPISODIC`. A relevance read over `EPISODIC` returns
them whenever the current conversation is on topic, which is the common case, not
the edge. Without this rule the supplement's whole budget is spent reprinting what
the prompt already carries, and the same record appears twice under two headings —
which `assemble_by_band` already treats as a fault for the band case, on ADR-0113
§5's cross-call deduplication obligation and ADR-0072 §6's presentation ground.
The tail's copy is the one kept because its position carries the conversational
order, which the supplement's does not.

> **Normative.** A failure of the episodic read drops the supplement alone, and
> the belief composition already in hand is kept.

> **Normative.** A failure of the episodic read does not set
> `TurnResult.memory_degraded`.

> **Normative.** A failure of the episodic read is logged at the stage, as the
> belief path's failure is.

The belief path's rule is all-or-nothing — a failure on any band's read discards
the whole retrieval — and #805 already carries the question of whether that is
right. This clause neither changes that rule nor waits on it. The supplement is
non-essential by construction, so discarding a successful belief composition
because a supplementary read failed would trade a good prompt for no prompt.

**And it must not be reported through `memory_degraded`, which is a narrower
signal than it looks.** `ai_assistant.core.types.TurnResult` documents that field
as whether assembling the records failed "making :attr:`plan` a *generic* answer
rather than a personal one", and adds why it exists: "an unpersonalised answer is
the one failure a user of this system most deserves to be told about." A failed
supplement produces neither. The beliefs are in hand and the plan is exactly as
personal as it would have been at a bound of zero — a bound §6 explicitly may set —
so setting the flag would put a false positive on the single signal the user is
told to trust, which costs more than the omission. It would also widen the
documented meaning of a field in `src/ai_assistant/core/types.py`, which §5 forbids
and which would make this a substantive contract ADR under ADR-0015 §5.

The failure is not thereby silent. The store emits its `RETRIEVAL` trace on the
fault path as well as the success path (ADR-0119 §8), and the stage logs as
`ai_assistant.orchestration.loop` already logs `memory_retrieval_degraded`. What is
absent is a *reported* signal on `TurnResult`, and whether a supplement's
degradation deserves one is a `core/types.py` question deferred with its consumer
(§8).

### 5. The contract surface: two widened docstrings, no member, no setting

> **Normative.** This decision adds no member to any Protocol in
> `src/ai_assistant/core/protocols.py`, changes no signature there, and changes no
> field, type or shape in `src/ai_assistant/core/types.py`.

`MemoryStore.search` already takes `kinds` and `bands`; ADR-0072 §5 and ADR-0113
already make the kind selection the caller's argument; `MemoryKind.EPISODIC`
already exists (ADR-0005 §1). The whole of the *read* this ADR admits is an
`orchestration` caller passing a different argument to a member that has been on
the contract since leg 1.

**What does move is `Planner.plan`'s documented meaning, and it is ratified here
rather than left for the lane to notice.** The member reads today:

> **`memories` is what the pipeline assembled for this turn, not one relevance
> cut** (ADR-0074 §5). It carries the conversation's recent turns **first**, in
> order, then the records retrieved as relevant, best first *within that group*.

§4 puts a third group after the second, so the post-tail region is no longer one
group ordered by relevance: a belief precedes an episode that outranks it, by
decision.

> **Normative.** `Planner.plan`'s `memories` carries three groups, in order — the
> conversation's recent turns, chronological; the retrieved beliefs; the episodic
> supplement. Each grouping is meaningful and the sequence is not globally ranked.
> A `Planner` implementation may rely on the grouping and may not rely on a global
> relevance order.

**`TurnResult.memories` is the same sequence and takes the same widening**, which
is stated separately because it is a `core/types.py` field rather than a Protocol
parameter and a lane could update one and not the other. Its wording carries the
same two-group description *and* a second clause the third group falsifies:
"Empty on the first turn of a fresh conversation, and empty for whichever **half**
degraded." There are no longer two halves, and a failing supplement empties the
supplement alone while the belief group stands (§4).

**But group degradation is not fully independent, and the contract must say so
rather than promise otherwise.** §4's separator rule keys on what *precedes* the
supplement, so an empty belief group takes the supplement with it whenever the
tail is non-empty — and a belief read that degrades is one way the belief group
comes back empty. So a `MemoryStore` failure on the *belief* composition can cost
both of the last two groups, while a failure on the supplement's read costs only
the supplement. The asymmetry is the separator's, not the failure handling's: the
supplement is dropped there for the reason §4 gives — it would otherwise render as
the conversation's own recent turns — and that reason does not care why the
beliefs are absent.

> **Normative.** `TurnResult.memories` carries the same three groups in the same
> order as `Planner.plan`'s `memories`.

> **Normative.** A degraded read empties its own group and no other — except that
> where the result leaves no non-`EPISODIC` record before the supplement, §4's
> separator rule applies and the supplement is empty too.

The exception rides inside the second clause rather than becoming a third, because
it states that clause's scope rather than a further obligation: ADR-0089 §2's form
is "one obligation, with its scope, conditions and exceptions", and the rule doing
the emptying is §4's, already marked there. Splitting it out would mark the same
obligation twice.

This is the same widening ADR-0074 §5 made and the same way it made it: the
signature is unchanged, `Planner` grows no parameter, and the change is **flagged
under golden rule 5 rather than smuggled** — which is the docstring's own phrase
for what ADR-0074 did to it. The clause about grouping-versus-ranking is carried
over deliberately: it was already the load-bearing caution, and a second retrieved
group is precisely the case it anticipated.

**Why a third group rather than one relevance cut over both.** Merging them is
§2's displacement moved into the renderer — an episode outranking a belief would
take the position, which is the outcome §2 refuses at the reader and §4 refuses at
the prompt. The Protocol's meaning has to widen because the design genuinely
demands it, not because a cheaper shape was available.

**A defect in the same sentence, found while ruling this and deliberately not
fixed here.** "Best first *within that group*" has been inaccurate for the
retrieved group since ADR-0113: `assemble_by_band` composes band by band, so an
`ASSERTED` record precedes a more relevant `DERIVED` one. That is a
description-versus-behaviour mismatch predating this ADR and independent of it, so
it is filed as **#1175** rather than absorbed into this PR.

**A `MemoryStore` member for episodic retrieval is declined.** Nothing here needs
one: a time-range read is a different capability with a different signature, the
measured consumer's questions are topical rather than range-scoped, and ADR-0072
§7's discipline applies to *this* surface as squarely as #791 applied it to the
capability. Recorded because it is the shape #545 gestures at ("a timeline is
queried by time range, not by semantic similarity") and a lane could reach for it
by analogy.

> **Normative.** The episodic bound is a composition-root constant beside
> `ai_assistant.app.composition.RETRIEVAL_LIMIT`.

> **Normative.** No field for the episodic bound is added to
> `ai_assistant.core.config.Settings`.

The belief budget is a composition constant, not a setting, and the episodic bound
is the same kind of thing: a cardinality control whose authority is measurement.
The contrast that decides it is `episode_retention`, which *is* a setting because
ADR-0074 §7 makes it a **privacy** choice the user owns — how long their own words
are kept. How many episodes help an answer is not a preference; it is a fact
nobody has yet measured, and offering it as a knob would imply a user could know
it. A setting is also user-facing surface, which this repository defers until a
consumer exists, and no user has asked for this one.

### 6. What the ablation arm measures, and what would retract this decision

The arm is not part of this lane and not part of `bench-pilot-2`.

> **Normative.** The episodic supplement is not cherry-picked into
> `bench-pilot-2`. Its effect is measured in a separately registered arm, run
> after #1163's lane 7 lands, from a ref containing it.

#1029's pilot-2 pre-registration fixes its ref as `bench-pilot-1` plus exactly
three named fix lanes and commits bucket-level predictions against them. Adding a
fourth change would make the predicted deltas unattributable, which is the precise
failure the "one configuration, no ablations" ground rule exists to prevent.

> **Normative.** The arm exercises the production composition path, not a
> harness-local imitation of it.

> **Normative.** The arm imports the episodic bound from
> `ai_assistant.app.composition`, as `benchmarks/memory/wiring.py` already imports
> `RETRIEVAL_LIMIT` and `CONFLICT_LIMIT`.

`benchmarks/memory/answer.py` performs its own retrieval —
`assemble_by_band(..., kinds=BELIEF_KINDS)` — so an arm written carelessly would
measure a harness that resembles the product rather than the product. The
harness's own stated guard against that drift is importing the cardinality
controls rather than copying them, and the supplement joins them.

> **Normative.** The arm reports conversion per pilot bucket, not a headline score
> alone.

> **Normative.** The arm reports prompt bytes per answered question.

The buckets are #1029's addendum's own, so the arm's output is comparable to the
baseline anatomy without reprocessing it.

**What the arm is testing is complementarity, not score.** The capability is
justified in §1 by one bucket — the 652 questions whose fact never became a
belief — and a score that rises for any other reason is not evidence for it.

- **Confirming shape.** Conversion concentrated in **ingestion-loss** (LoCoMo 652
  / LongMemEval 9). Those are the questions no belief could have answered, so an
  episode answering them adds reach the belief layer did not have.
- **Substitution, which reads as success and is not.** Conversion from
  **lossy-record** (416) or **rank-miss** (277) means the belief layer already
  held the fact and the episode won anyway. That is the hollowing, arriving as a
  higher score: the right response to it is to fix distillation (ADR-0156's lane)
  and the retrieval budget, not to keep the supplement.
- **Two required cost measures.** `correct` (118) must not shrink and
  `attempted-wrong` (69) must not grow — a supplement that converts right answers
  into wrong ones is distracting, not helping. And **cat-5 correct abstention**
  (446) must be reported: verbatim transcript material is exactly the near-miss
  content that makes an unanswerable question look answerable, and pilot 2 already
  predicts that figure degrading for an unrelated reason, so the two effects must
  be separated rather than netted.

**The retraction predicate is stated as arithmetic, because a word like
"dominated" is not decidable and a condition nobody can settle is not a
commitment.** Its terms:

- **A conversion** is a question that sat in a named baseline bucket and is
  `correct` in the arm. `I` is the count of conversions from **ingestion-loss**,
  `L` from **lossy-record**, `R` from **rank-miss**.
- **The figures are LoCoMo's.** LongMemEval is reported and is not decisive: its
  ingestion-loss bucket holds 9 questions, which cannot separate the readings this
  predicate turns on. Saying so in advance is what stops the smaller corpus being
  reached for after the fact.

> **Normative.** §3's bound goes to zero and the supplement is removed unless
> **all three** hold on the arm's LoCoMo figures: `I > L + R`; `correct` is not
> below its baseline of 118; and `attempted-wrong` is not above its baseline of 69.

**Why a strict inequality against the *sum*.** The capability is justified by
reach the belief layer does not have, so it has to be more complementary than
substitutive — not merely the largest of three buckets. The reviewer's own worked
case decides it the way this ADR intends: 40 ingestion-loss against 35 rank-miss
and 25 lossy-record is the *largest single* bucket and is still 60 conversions the
belief layer could have made itself, so `40 > 60` fails and the supplement goes.

**Zero and ties fall the same way, deliberately.** With no conversions anywhere,
`0 > 0` is false and the supplement is removed — which is the right answer, since
a supplement that converts nothing has bought nothing for the prompt bytes it
spends. A tie is likewise a failure to clear the bar rather than a pass.

**Magnitude is a separate question and is not this predicate's.** A result clearing
all three conditions by a small margin keeps the capability and bears on §3's
bound, which §6's per-bucket figures are what inform; it is not grounds for
retraction. Folding a size threshold in here would mean inventing a number this
ADR has no measurement for, which is the defect it would be trying to fix.

That predicate is the falsifiable half of this decision, and it is what makes §3's
non-zero initial value a commitment rather than a ratchet.

### 7. What the implementing lane owes, and what it may not touch

> **Normative.** The implementing lane's only edits under
> `src/ai_assistant/core/` are two documentation updates carrying §5's three-group
> wording — `Planner.plan`'s `memories` in `protocols.py`, and
> `TurnResult.memories` in `types.py`. It adds no member, changes no signature,
> changes no field, and touches `config.py` and `errors.py` not at all.

The lane pins each of the following as a test, and each is separately owed.

> **Normative.** The lane pins that the belief composition's `kinds` argument
> still excludes `EPISODIC` (§2).

> **Normative.** The lane pins that the belief budget passed to
> `assemble_by_band` is unchanged by the supplement's presence and by its bound
> (§3).

> **Normative.** The lane pins the supplement's read arguments in full, as
> observed at the call: `kinds` exactly `(MemoryKind.EPISODIC,)`, `bands` exactly
> `(BeliefBand.DERIVED,)`, and `limit` the composition-root bound (§3).

> **Normative.** The lane pins that the kind filter is *effective*, by leaving a
> `DERIVED` non-`EPISODIC` record relevant to the query eligible and asserting it
> does not reach the supplement (§3).

> **Normative.** The lane pins that the band filter is *effective*, by leaving a
> relevant `EPISODIC` record outside the `DERIVED` band eligible and asserting it
> does not reach the supplement (§3).

> **Normative.** The lane pins that the supplement's records follow the belief
> records in `memories` (§4).

> **Normative.** The lane pins that an episode present in the continuity tail is
> not repeated by the supplement (§4).

> **Normative.** The lane pins that a failing episodic read leaves the belief
> composition intact and `TurnResult.memory_degraded` unset (§4).

> **Normative.** The lane pins the separator case with a tail: a turn with a
> non-empty episodic continuity tail, an empty belief composition and a relevant
> cross-conversation episode, asserting the episode is absent from `memories`
> (§4).

> **Normative.** The lane pins the separator case without one: a turn with an
> empty history, an empty belief composition and a relevant cross-conversation
> episode, asserting the episode is absent from `memories` (§4).

The first five are the ones a refactor would break silently, and they are §2 and
§3 in executable form. The rest are §4. The band case is constructible from the
fixture that already exists — `tests/orchestration/test_conversations.py`'s
`_foreign_episode` — which is why §3 pins the band rather than trusting the
producer.

**The arguments are pinned as a set, and each filter is separately proved to
bite, because the two failures are different.** Pinning the arguments alone would
pass an implementation that computed them and then read something else; proving
only the effects would pass one that reached the right result through a wider
read and a post-filter, which §2's candidate-set argument rules out. And the two
filters fail differently: a `kinds` that widened to `None` while `bands` stayed
`DERIVED` would admit *derived beliefs* into the supplement, appending after the
belief group records that could already be in it — the one way a belief could
appear twice in one prompt, which §4's deduplication does not catch because it
is scoped to the continuity tail. Pinning `kinds` is what closes that, and it is
why no further deduplication rule is owed.

**The separator cases are called out because the obvious test does not cover
them.** "The supplement's records follow the belief records" passes with a single
belief present, while an implementation that appends unconditionally still
recreates the false-continuity rendering §4 exists to prevent — the empty-belief
state is where the clause binds and the ordering assertion is silent. Both are
asserted on `memories` rather than on the rendered prompt, so neither test depends
on the planner's private split.

**And there are two of them because §4's clause keys on the absence of a
separator, which two different states produce.** A resumed conversation whose
query matches no belief has a tail and no separator; a *fresh* conversation has no
tail either, so the supplement would be the whole of `memories` and the leading
`EPISODIC` run would be all of it. An implementation that reads the clause as "drop
when the history is non-empty and the beliefs are empty" passes the first test and
fails the second, and the state it fails on is the first turn of every new
conversation.

The lane also owes the retrieval trace's honesty: ADR-0119's `RETRIEVAL` trace is
emitted per `search` call inside the store, so a supplement is naturally a second
traced read rather than an untraced widening of the first. Nothing needs adding
for that; it is named so the lane does not "helpfully" merge the reads.

### 8. What this ADR does not decide

- **The bound's value beyond its ratified initial 5.** §6's arm owns it, in both
  directions.
- **Retrieval-triggered distillation** — the loop in which an episode that
  answered a question is fed back to the observer so the fact becomes a belief.
  This is the shape that would resolve the thesis tension rather than balance it:
  episodic retrieval that *strengthens* the user model instead of routing around
  it. It reaches `learning` and `orchestration` together and needs its own ADR;
  filed rather than sketched here.
- **A relevance threshold, or any "the belief layer answered thinly" trigger.**
  Both are new eligibility axes that ADR-0128 §1 would bind before the cut, and
  neither has a measured value. ADR-0103 §5 and ADR-0112 §9 keep thresholds with
  leg 8's measurement, and Alternatives considered records why the count-shaped
  version is measurably dead.
- **A byte bound on the prompt.** ADR-0007 §5's deferral of size caps stands; §6
  requires the measurement that would inform one.
- **Whether a degraded *supplement* deserves a reported signal of its own.** §4
  rules it out of `memory_degraded`, whose meaning is narrower, and adding a second
  field to `TurnResult` is `core/types.py` surface. Deferred with its consumer,
  which is a client that would show it; today nothing would.
- **Whether a non-`DERIVED` episode should be retrievable at all** (§3's clause).
  Ruled out of the supplement's reach here, and admitted only by an ADR that
  settles how it composes across bands.
- **Episodic retrieval anywhere but the answering turn's prompt.** The observer
  (ADR-0077 §1), consolidation, notifications and the correction drawer are
  untouched, and each reads what its own ADR gives it.
- **How an answer grounded in an episode is attributed or rendered.** Nothing here
  changes what a turn reports about where its answer came from.
- **#545 in any part.** §3's revisit trigger is where a non-`OBSERVED` episode
  channel would first bind; adopting one is a separate decision.
- **Symmetric retention of assistant-side turn content** (#1029's P6). Capture
  records the whole turn and this ADR does not reopen it.

## Consequences

**Easier.** A question whose answer was said once and never distilled becomes
answerable, from evidence the system already stores, embeds and pays for. The 652
is the largest single bucket in the pilot's anatomy and the only one none of
#1163's other lanes reach. #791 closes with both halves answered rather than
carrying an item whose trigger has already fired.

**Harder, and worth naming precisely.** The answering prompt grows by up to five
verbatim turns, which is a larger and less predictable increase than five beliefs
would be, and the answering model has already been shown to be highly sensitive to
what its context looks like — 1,309 of pilot 1's 1,320 declines were a single
exact string. There is now a second retrieval read per answering turn, so a
turn's retrieval latency and its trace count both rise. And the deduplication rule
is a cross-read obligation invisible to every store conformance case, exactly as
ADR-0113 §7 says of the band one: it can only be tested at the composition, and it
will be got wrong by anyone who adds a second episodic consumer without reading
§4.

**A standing asymmetry this decision deliberately does not remove.** Beliefs are
retained indefinitely; episodes are not. `episode_retention` defaults to a finite
30 days and ADR-0074 §7 ratifies that finiteness as "the whole decision", with
`None` reachable only by the user's own choice — the configuration the pilot ran
under. So the supplement's reach ends at the retention horizon, and a deployment
that shortens retention for privacy loses answers for it. That is not a defect to
engineer around: it is the correct expression of what the two layers are. A belief
is what survives, because it was judged worth keeping; an episode is evidence with
an expiry. Any future proposal to make answering *depend* on episodes has to face
that a default-configured system goes blank about anything older than a month, and
that the users who most protect their transcripts would be the ones penalised.
This ADR keeps episodes supplementary partly so that cliff can never become the
answering path's main road.

**What would trigger revisiting this decision.**

- §6's arm, in either direction: it raises the bound, or §6's retraction clause
  takes it to zero and removes the path.
- A wish to make episodes outside the `DERIVED` band retrievable (§3) — #545's
  calendar channel is the live candidate. Until then the band pin holds them out
  of reach rather than mixing them in, so the trigger is a decision to widen, not
  a fault waiting to be noticed.
- A change to `episode_retention`'s default, which changes what the supplement can
  reach without changing a line of retrieval code.
- Distillation improving enough that the ingestion-loss bucket stops dominating —
  at which point the supplement is answering questions the belief layer could have
  answered, and §6's substitution reading applies to production rather than to an
  arm.

## Alternatives considered

**1. Refuse outright, and keep `BELIEF_KINDS` as the whole answer.** The strongest
alternative, and the one the owner's steer most plainly protects. Rejected on
three grounds. It renews a deferral whose own stated trigger has fired, which
#791's framing does not license — the discipline was "defer until a consumer
exists", not "defer indefinitely". Its central argument, that episodes would flood
the belief cut, is answered by two budgets rather than by refusal; refusing on an
argument that a bounded design defuses is refusing the one-line version of the
proposal. And it leaves 42% of a measured answerable set unreachable while the
system pays every storage and embedding cost of the evidence that would answer
them. A refusal remains the right outcome if §6's arm reads as substitution, which
is why §6 states that outcome as a clause rather than as a hope.

**2. Drop `BELIEF_KINDS` — one budget, kind-blind.** The one-line version.
Rejected in §2: episodes and observed beliefs share the `DERIVED` band so the band
composition contains nothing, ADR-0128 §1 binds `kinds` before the cut so nothing
downstream recovers a displaced belief, and the population ratio (17–42 beliefs
against ~300 turns) says displacement would be routine rather than occasional.
This is the shape that would make the system naive RAG over the transcript, and it
is the shape the thesis objection is actually about.

**3. A capped episodic *share* of the one budget.** The shape the brief names, and
the closest rejected alternative. It bounds the flood correctly, and it is still
wrong: `RETRIEVAL_LIMIT`'s 5→15 move was bought for beliefs on the pilot's own
rank-miss measurement, and a share hands part of it straight back on no
measurement. It also fails worst where the system works best — a deployment with a
rich belief layer, whose budget is full, loses belief slots to episodes it does not
need. §3's separate bound costs prompt size instead, which is the cost that does
not touch belief recall.

**4. Episodes as a fallback when belief retrieval comes back thin, triggered by
count.** The most attractive shape on its face — zero cost when the user model
works, episodes only when it is empty — and it is **measurably dead in the exact
case that motivates this ADR**. `assemble_by_band` returns fewer than `limit`
records only when the store lacks eligible ones, and each LoCoMo case's store held
17–42 beliefs against a budget of 15. The composition fills; the remainder is
zero; the fallback never fires. The 652 failures are not failures of belief
*quantity* — the prompt was full of beliefs — they are failures of belief
*content*. A count of retrieved records cannot see that difference, which is the
general defect the LoCoMo figures happen to make concrete.

**5. The same fallback triggered by a relevance threshold.** Expressible —
`MemorySearchResult` carries a cosine `score` — and rejected for want of any
measured value for the threshold. It is a new eligibility axis that ADR-0128 §1
would bind before the cut, so a wrong value silently removes eligible records
rather than merely reordering them, and ADR-0103 §5 and ADR-0112 §9 both keep
threshold questions with leg 8's measurement. Not foreclosed: if §6's arm produces
per-question relevance data, this becomes answerable rather than guessed.

**6. Episodic-as-corroboration only — episodes reach the prompt solely as the
evidence cited by a retrieved belief.** Preserves the thesis exactly, needs no new
read (`Provenance.evidence` names episode ids and ADR-0086 §6 put `get_many` on the
contract), and is the right shape for *"why do you believe that?"*. It cannot serve
this consumer: the 652 are by definition questions where **no belief cites the gold
episode**, because no belief was formed. Recorded because it is a good design for a
different question and remains fully available — nothing in §§1–5 forecloses it.

**7. A time-range episodic read** (#545's timeline shape). Rejected here as a
different capability: it needs a `MemoryStore` member this ADR declines (§5), and
the measured consumer's questions are topical rather than range-scoped. It is the
natural read for an episodic *timeline* surface, which nothing has asked for.

**8. Fixing ingestion instead.** Not an alternative so much as the other half, and
it is already in flight: ADR-0156's temporal anchors and the observation lanes both
target distillation quality, and the pilot's own reading is that a large part of
LoCoMo's ingestion residual is structural to third-person dialogue rather than
fixable by tuning. This ADR takes the position that the two are complementary and
that §6's arm is what keeps them so — an episodic supplement is a reach extension
where distillation cannot go, and §6's substitution reading is exactly the alarm
for it becoming an excuse not to go there.
