# 220. The watermark-driven observation walk tiles contiguously, and forgoes ADR-0162 §7's window overlap

- Status: Accepted
- Date: 2026-08-29
- **Partially supersedes:**
  [ADR-0162](0162-what-the-user-tells-the-assistant-is-recorded-and-selectivity-moves-to-retrieval-and-forgetting.md)
  — §7's window-overlap clauses, **only as they reach an observation walk whose page is
  selected by the watermark ADR-0212 decides**. §7's remainder, and every other tiling
  it binds, stay accepted. The scope is stated in §6(a), where the ADR-0082 §1 test is
  applied to the clause.
- **Amends:**
  [ADR-0212](0212-the-observation-cursor-is-a-per-conversation-watermark-on-the-conversation-index.md)
  — §10's closing stacked-addition clause, whose "no other ratified clause read
  differently after it" is over-wide by exactly the clause §6(a) names. Header-only,
  and under [ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md) §2
  the record is the dated note alone, because that `Status` line already carries a
  leading `Partially superseded by` token. Named in §6(b).
- **Both records are made in this change**, header-only in each case — no ratified text
  of either ADR is rewritten, which is the whole of what
  [ADR-0070](0070-amendment-and-supersession-rules.md) §1 permits in place. ADR-0082 §7
  settles that "§1's condition is that the superseding ADR **exists**, not that it is
  ratified", and ADR-0205 §10's "**Both records are made in this change**" is the
  corpus practice this follows.
- **Not a substantive contract ADR.** No Protocol member, no `core/types.py` field, no
  `Settings` field and no `PROTOCOL_VERSION` move; this ADR adds no mechanism and
  removes none. It decides which of two ratified clauses yields where both cannot hold.
  Both review lenses are run regardless, because `CONTRIBUTING.md` → "Contract ADRs land
  before their implementation" says "**Run both on an ADR PR**" without qualification.
- **Durability clause.** Every quotation below — from an ADR, from
  `benchmarks/memory/ingest.py`, or from an issue — is of its text as it stood at this
  ADR's base, `0fddb9e7`, and not of its text on any later day.
- Refs #1237, #1789, #1782, #1829, #1210, #1029, ADR-0162, ADR-0212, ADR-0111,
  ADR-0077, ADR-0074, ADR-0070, ADR-0082

## Context

**Two ratified marked clauses reached the same walk and gave it opposite
instructions.** ADR-0162 §7 rules:

> **Normative.** Where consecutive observation passes tile a sequence of episodes
> rather than re-reading one window, consecutive windows overlap: the last *k*
> episodes of one window are the first *k* of the next.

with *k* "at least 1 and at most `observation_batch_size // 2`", and a last clause that
forward-binds a walk nobody had built yet:

> **Normative.** The product's explicit-trigger path tiles nothing today, so these
> clauses bind the benchmark harness's ingestion driver now and any durable-cursor walk
> (ADR-0111 §1) if one is built. A lane that introduces tiling elsewhere inherits them.

ADR-0212 built that walk. Its §1 rules the watermark's meaning to be "the observation
walk over that conversation has advanced past that ordinal, and **no later pass of a
build that reads the watermark selects a turn at or below it**". Its §3 rules that a
pass reads "that conversation's **turns above its watermark**, ordinal ascending, at most
`observation_batch_size` of them — the lowest such page, not the tail". Its §5 rules that
the position a pass records is "**the highest ordinal in the page whose episode
resolved**", and that where no turn resolved it "names the page's highest ordinal
instead".

**An overlap of *k* ≥ 1 is exactly a re-selection of turns at or below the watermark**,
so §7 asks the walk for the one thing §1 forbids it. The only way to buy it back through
the watermark is to advance to the highest resolved ordinal *minus k*, and §5's clause
names the position without subtraction; §5's closing paragraph refuses the family such a
rule belongs to in terms — "What is deliberately *not* bought is a rule that gives every
gap a second reading. Such a rule has to stop the watermark below the lowest unresolved
turn […] Each fallback is another place for the rule to disagree with itself." Neither
clause yields to the other on its own text.

**ADR-0212 does not record the conflict.** Its §10 declares partial supersessions of
ADR-0077, ADR-0074 and ADR-0111, names their scopes clause by clause, and closes with
"Everything else about this ADR is a **stacked addition** under ADR-0082 §1: one member
on one `core` type, three operations on one non-promoted Protocol, and **no other
ratified clause read differently after it**." ADR-0162 is named nowhere in it.

**The corpus's standing expectation was the opposite one.** Issue #1237 — raised against
PR #1227's tiling driver and parked — says closing it needs "either a second amendment
note on §7 covering the terminal remainder […] or the durable cursor ADR-0077 §11 filed
and §7's last clause names as ADR-0111 §1's walk, **which would let the final window
begin where the carry asks**". The cursor was expected to *serve* §7. It forbids it.

**Where the conflict surfaced.** The ADR-0212 implementation lane (PR #1829) reports 12
failures in `tests/benchmarks/` on its branch — 11 in `test_ingest_tiling.py`, 1 in
`test_run_end_to_end.py` — with the same tests passing at its base, and stopped rather
than re-pin them. The failures are not stale assertions. `ingest_case` does not select
turns; the stage does. The driver buys §7's overlap by **pacing captures against a tail
read**, which its own docstring states as the mechanism — `_next_pass_at` "takes that
window's episode-bearing ordinals, picks the ``overlap``-th from the end, and fires the
next pass when the window would *begin* there" — and the module docstring's premise for
it is that "the window is always *the most recent ``batch_size``* — there is no offset on
the read". ADR-0212 §3 removes that premise. With the page fixed by the watermark rather
than by the tail, no pacing a driver can perform makes consecutive pages share an
episode, so the overlap is not merely unimplemented at that seam: it is unbuyable there.

## Decision

### 1. ADR-0212's clauses stand, and the overlap is forgone for the walk they decide

> **Normative.** Where an observation pass's page is selected by the watermark ADR-0212
> §1 decides, **every turn the page holds is strictly above the watermark that pass
> read** — ADR-0212 §3's page, unchanged in bound and in kind, "the lowest such page, not
> the tail", holding at most `observation_batch_size` turns — and **nothing extends it
> downward**: no driver's pacing, no selector, no setting and no later clause may cause a
> page to reach below the watermark its own pass read in order to carry episodes forward
> from an earlier page. ADR-0162 §7's overlap is **forgone** for such a walk and *k* is
> **0** there, in the same sense §7 itself gives an overlap of 0 where its bound is
> empty: "the clauses above are satisfied vacuously and the deployment forgoes this
> section's remedy".

> **Normative.** The invariant above is over a pass that read a **recorded** watermark. A
> conversation with **none** is ADR-0212 §4's case and is untouched here: that pass reads
> "ADR-0077 §8's window unchanged — that conversation's most recent
> `observation_batch_size` turns", and nothing in this ADR initialises a watermark, reads
> forward from the conversation's first turn, or otherwise disturbs §4 — whose own second
> clause, "`None` is the only spelling of 'no pass has recorded one'", binds unchanged.
> The anti-extension rule is vacuous for that pass in any case, since there is no earlier
> page to carry episodes forward from. It binds every pass after it, from the watermark §5
> records off that first window onward.

> **Normative.** That is a rule about what a page may be *extended* to include, and it
> narrows no clause of ADR-0212. Three readings of one turn survive it, each of them
> ADR-0212's own, and **none is an overlap in ADR-0162 §7's sense**: a page whose highest
> turns did not resolve advances only to the highest *resolved* ordinal, so the next page
> begins at the lowest turn of that trailing unresolved run and selects it again (ADR-0212
> §5's second worked case, where "The next page begins at 120"); two passes over one
> conversation may run concurrently and select the same page,
> which ADR-0212 §5 permits in terms and resolves by `record_observed`'s monotonicity;
> and a pass whose advance attempt **did not commit** — every failure before it, and the
> half of ADR-0212 §6's ambiguous case "in which the stamp did not land" — has its page
> re-read whole "by the next pass that reaches that conversation" (§6). The other half is
> not a third reading at all: where the stamp *did* commit, §6 rules the page "is not
> re-read and does not need to be", and where the conversation is stamped deleted first
> "there is no re-read and none is owed".
> Each is incidental to the advance rule rather than produced by a
> driver, none is guaranteed to happen, none carries a chosen number of episodes forward,
> and this ADR neither removes nor relies on any of them.

> **Normative.** ADR-0162 §7's window-overlap clauses — the overlap itself, its bound
> "*k* is at least 1 and at most `observation_batch_size // 2`", and the last clause
> forward-binding "any durable-cursor walk (ADR-0111 §1) if one is built" — **no longer
> bind the walk ADR-0212 decides**, and no lane owes an overlap through them. The floor of
> 1 goes with them, which is what makes a *k* of 0 available above rather than a
> contradiction. They bind every other tiling exactly as they did.

> **Normative.** No implementation may buy the overlap back by advancing the watermark to
> a position below the one ADR-0212 §5 names for that pass — the highest ordinal in the
> page whose episode resolved, or the page's highest ordinal where none did. §5 names it
> without subtraction, and its monotonicity and its never-stands-still guarantee both rest
> on it. A lane that wants re-reading asks for a new operation (§2's third bullet), never
> a lower watermark.

**Why ADR-0212's clauses are the ones that stand, and not §7's.** Three reasons, and the
third is the decisive one.

- **§7's clause is conditional on its own protasis; ADR-0212's are not.** §7 rules
  "*where* consecutive observation passes tile", and it names its subjects — the harness
  driver "now", and a durable-cursor walk "if one is built". It is a rule about a shape
  that may or may not exist. ADR-0212 §1's non-selection guarantee is unconditional over
  every pass of every build that reads the watermark, and §3 and §5 are the selector and
  the advance themselves. Yielding ADR-0212's clauses does not narrow them; it removes
  the mechanism.
- **§7 anticipated the cursor and got it wrong, on its own record.** Its own reasoning
  cites ADR-0077 §8 for the premise that makes the overlap purchasable — "`ObservationStage`
  holds no cursor and takes no offset" (ADR-0162's 2026-08-19 amendment note, saying so
  in terms) — and ADR-0212 §10(a) replaces exactly that sentence of ADR-0077 §8. The
  clause forward-binding the cursor was written against a stage that no longer exists.
- **Honouring §7 would cost a ratified guarantee, and honouring ADR-0212 costs a
  remedy.** §7's overlap is a *mitigation* of a named loss, whose value §7 itself calls
  "an empirical question about how far a fact spreads across turns, which no run has
  measured". ADR-0212 §1's guarantee is what makes the walk terminate, makes a repeated
  pass a no-op, and makes the scheduled job safe to enable — "a conversation with turns
  above its watermark cannot be re-read indefinitely" (§5). Trading a measured
  termination guarantee for an unmeasured mitigation is the wrong direction, and it is
  the direction §5 already refused when it declined to give every gap a second reading.

**This is not reconcilable by reading, and the two readings that look like escapes are
not.** Reading the walk as outside §7's protasis fails: consecutive pages over one
conversation's ordinals are the plainest case of tiling "a sequence of episodes rather
than re-reading one window" there is, and §7's last clause names a durable-cursor walk
by name so that nobody has to decide the protasis for it. Reading §7's 2026-08-19
amendment as covering it also fails: that amendment rules "Where a window holds no more
than *k* episodes, progress takes precedence over the overlap" — a floor for a *thinned*
window, which with *k* at 0 is satisfied vacuously here and settles nothing about a full
one.

### 2. The boundary loss is accepted with a record, and what remains of the remedy

> **Normative.** The loss ADR-0162 §7 was closing is **accepted** for the watermark-driven
> walk, not repaired and not deferred to a lane. A fact stated across a page boundary —
> the user names a trip in the last turn of one page and says where they went in the
> first turn of the next — is visible to neither pass as a whole, at a rate set by the
> alignment of the pages rather than by the data. No clause of this ADR mitigates it.

Three things in the corpus bear on that loss, and this section states each at its true
size so that none is later mistaken for a remedy this ADR bought.

- **A build that does not read the watermark still tails, and still overlaps.** ADR-0212
  §7 requires such a build to exist and to work — "A build that does not read the
  watermark **ignores it and must not refuse to start over it**" — and the selector it
  runs is today's tail read. ADR-0162 §7 binds it unchanged. This is not a mitigation of
  the loss on an upgraded deployment; it is the statement that §7's remainder is live
  text with a live subject.
- **ADR-0212 §5's page bound already bounds how much the walk can miss at a boundary**,
  because it names a position from the page the pass actually read and never above it.
  The loss is one page boundary's worth of adjacency per pass, not an unbounded gap.
- **#1789 is where a deliberate re-observation would be spelled, and it is a buy-back
  nobody has bought.** ADR-0212 §9 defers "a re-observation that deliberately ignores the
  watermark" to it, and rules that whatever it turns out to be it is "never a change to
  what the watermark means, and never a caller resetting one". Naming it here is naming
  the place such a capability would live. **It is not a promise that it will be built**,
  and its condition to fire is #1789's own: a user-facing need being reported.

**Two shapes are refused rather than left open.** An overlap threaded through the
watermark — advance to highest resolved minus *k* — is forbidden by §1 above and by
ADR-0212 §5 in terms. And the alternative §7 itself rejected, showing the previous page's
tail as context the observer may not propose from, is **not** reopened here: §7's reasons
against it are unaffected by anything this ADR decides, and reopening it would need the
prompt to carry two classes of episode and put a rule about citation where ADR-0077 §5
has none.

### 3. The benchmark harness follows the product

> **Normative.** `benchmarks/memory/ingest.py::ingest_case`'s overlap pacing is removed
> where it drives a watermark-reading `ObservationStage`. It computes no overlap, defers
> no pass to place a carried tail, and creates no re-observation of its own.

> **Normative.** **The cadence stays in store-allocated turn ordinals and is not restated
> in capture counts.** A pass is due once the conversation holds `observation_batch_size`
> turns **above its watermark** — one full page in ADR-0212 §3's sense, which is a bound
> in turns and never in captures. The driver's existing reason for that unit is unchanged
> by this ADR and is the reason here: "The two sequences are not the same one, so a driver
> pacing on its own capture count delivers §7 only while nothing fails" — a lost append
> stores no turn and moves no ordinal, so a capture count and an ordinal disagree the
> first time one fails, and a cadence in captures would fire a short page against a
> `Settings` bound that counts turns. How the driver learns the watermark is the lane's;
> ADR-0212 §7 puts the member on `Conversation`, so "every read that returns a
> `Conversation` […] carries it too".

> **Normative.** The closing flush **stays**, and the cadence above does not replace it:
> when a case's captures are exhausted and its conversation still holds turns above its
> watermark, the driver keeps passing until it holds none. A case whose turn count is not
> a multiple of the batch is an ordinary input, and a case shorter than one batch outright
> is the commonest one — `ingest_case`'s docstring refuses to skip the closing pass for
> exactly that reason, "a LongMemEval haystack is often shorter than one batch outright,
> so skipping would ingest a conversation and distil nothing from it", and that reason
> survives this ADR whole. **The loop is over passes that return.** A pass that raises is
> not retried inside it: the flush stops there and the raise surfaces, leaving the
> watermark wherever ADR-0212 §6 leaves it — moved by nothing where the pass raised
> before its advance attempt, and in the ambiguous state where it raised at one, of which
> §6 rules "Both outcomes are safe and neither is a defect". Repairing either is no part
> of this loop; ADR-0111 §5, which §6 inherits whole, gives the same disposition — the
> run "stops immediately […] without processing any later chunk". Over passes that return
> the loop terminates on ADR-0212 §5's guarantee that "the watermark never stands still
> across a pass over a non-empty page", which reaches every pass the flush makes: it
> passes only while the conversation holds turns above its watermark, so no page it reads
> is empty.

> **Normative.** What the flush costs changes, and in the direction #1237 wanted. Against
> a tail read the closing pass re-read `batch_size − remainder` turns an earlier pass had
> already distilled — the module docstring's "The last window overlaps, and it cannot be
> made not to". Against the watermark it reads only turns above the watermark, bounded by
> `observation_batch_size` like every other page, so it re-reads nothing an earlier pass
> distilled.

> **Normative.** `IngestionSummary.episodes_reobserved` **is not removed and is not
> redefined here.** What this ADR rules about it is one thing only: the driver no longer
> produces a re-observation of its own, because `ingest_case` runs its passes serially
> and no longer overlaps them, and a turn ADR-0212 §5 leaves for a later page was never
> handed to the observer, so reading it later shows it once. This ADR rules **nothing**
> about the value the property computes.

> **Normative.** That value is not a per-episode count, and the implementing lane neither
> relies on it nor repairs it. `episodes_reobserved` is
> `max(0, episodes_read − turns_captured)` — a difference between two counters incremented
> on different tests, not a tally of episodes some pass read twice. `ingest_case` counts a
> capture under `turns_degraded` whenever it is `degraded` **or** carries no episode id,
> while recording its landing off the episode id alone, on the ground that "a report that
> is `degraded` and still carries an id has something a pass can read". This ADR rules
> nothing about what that difference computes in any given run, and changes nothing about
> it: that is the property's shape before this ADR and after it. **#1837** records it, and
> closing it is a rename or a true per-episode metric, neither of which this ADR decides.

> **Normative.** The tiling tests re-pin to contiguous tiling rather than being deleted
> or skipped. What they assert is the driver's cadence against the store's own ordinals,
> which is still the property worth pinning; only the expected relation between
> consecutive pages changes. The re-pinned set covers the **remainder** case in terms — a
> case whose turn count is not a multiple of the batch, and a case shorter than one batch,
> because that is where the clauses above differ most from the ones they replace and it is
> the shape #1237 was raised about — and it keeps a **lost-append** case, because that is
> what makes the ordinal cadence above observably different from a cadence in captures.

> **Normative.** **#1237 closes against this record.** Its question — where the closing
> pass may place the carried tail — is dissolved rather than answered: with *k* at 0
> there is no carried tail to place, and the closing pass reads the page above the
> watermark like every other pass.

> **Normative.** A benchmark run performed after this change is **not comparable on
> ingestion** to a run performed before it, and no comparison between the two may be
> reported without re-running the earlier arm. Pilot-5's headline figures — LoCoMo 77.4%
> and LongMemEval 80.0%, recorded on #1029 and #1210 — were produced on `bench-pilot-5`
> with the overlap in force, so they are the standing reference this change invalidates
> on the ingestion side.

**Why the harness follows rather than keeps the overlap.** It has no choice that is not a
fork of the product: the overlap was never the driver's to grant. `ObservationStage`
selects the turns; the driver only chooses *when* to call it, and its docstring says so —
"the driver reads the conversation's own ordinal after every capture and schedules on
that". Once §3 of ADR-0212 fixes the page from the watermark, every schedule produces the
same contiguous tiling, and a driver that kept computing an overlap would be computing a
number nothing consumes. The alternative — a harness that drives a deliberately older,
tail-reading stage in order to preserve the overlap — would make the benchmark measure a
pipeline the product does not run, which is the one thing a benchmark may not do.

**What the incomparability is, precisely, so it is not read as wider than it is.** The
change is to *how much the observer is shown*, not to what it may propose. Under the
overlap the observer saw `batch_size` turns of which *k* were a repeat, so the same
corpus bought more passes and more model calls, and each boundary fact got a second
reading. Contiguous tiling reads each turn once. Ingestion cost falls and boundary
coverage falls with it; retrieval, the reconciler and the answer path are untouched. A
figure that moves after this change may have moved for that reason alone, which is why
the clause above requires the earlier arm re-run rather than adjusted.

### 4. What the implementation lane owes

> **Normative.** The lane implementing this ADR is the ADR-0212 implementation lane
> (PR #1829), whose fence is widened to `benchmarks/memory/ingest.py`,
> `tests/benchmarks/test_ingest_tiling.py` and `tests/benchmarks/test_run_end_to_end.py`
> and nothing else. It rides the harness change with the ADR-0212 implementation rather
> than deferring it, because the branch cannot be green without it.

> **Normative.** That lane adds no `core` member, no `Settings` field, and does not move
> `PROTOCOL_VERSION`. This ADR decides a scope; it buys no surface.

**The widening is ADR-0137 §1's adaptation clause — not a §2 pairing, and not a §4
consumer group.** §1 rules this case in terms: "Adaptation does not count against the
bound in this section. A lane may carry adaptation across any number of subsystems." The
harness change is adaptation and nothing else — it *removes* the overlap schedule, and
what replaces it reads a member ADR-0212 §7 already puts on every `Conversation` a read
returns. It builds no store, loop, codec, producer or policy engine, which is §1's own
enumeration of the machinery the bound counts; `benchmarks/` is not an `ai_assistant`
subsystem in any case.

**So §4 is not engaged, and reading it to reach adaptation would contradict §1.** What
§4 defers is a *further consumer group* — a consumer whose own work would be its own
lane. It cannot mean every call site that touches the contract, because §1's worked
example is exactly that and comes out the other way: "A contract change that ripples a
new argument through six call sites is one lane, because six adaptations draw one class
of finding." Six call sites are six consumers; if §4 deferred each of them there would be
no such lane. The two sections are read together here, with §1 governing what may ride
and §4 governing what must wait.

**§4's own verbs name the act it sequences, and it is not the contents of a diff.** A
consumer "is **briefed** only after the paired lane has merged", and those consumers "are
**dispatched** as consumer groups, one lane per group". Briefing and dispatching are
things done to a *lane*, and §4's rationale names the harm they are sequenced against: "a
brief written against an unmerged contract is written against a draft in its author's
head". A hunk riding inside the implementation lane is neither briefed nor dispatched as a
lane of its own — it is briefed by *this* ADR, ratified ahead of that lane under golden
rule 5, and reviewed in the same tree as the contract it adapts to. Neither the unmerged
contract nor the absent brief §4 guards against is present here, so its sentence does not
reach this widening.

The practical reason is the one §1's asymmetry is there to serve — the tests this change
re-pins are the tests the ADR-0212 contract change turns red, so landing them apart would
put a knowingly red tree on `main` between two merges.

### 5. What this ADR does not decide

- **Whether a deliberate re-observation is wanted.** #1789's, unchanged, with its own
  condition to fire. §2 names it as the place a buy-back would live and buys nothing.
- **Anything about the observer's proposals.** ADR-0077's bar, prompt, payload,
  confidence function and proposal bound are untouched, exactly as ADR-0212 §9 leaves
  them. This ADR changes which turns reach the producer on one path and nothing about
  what it does with them.
- **The value of *k* anywhere §7 still binds.** ADR-0162 §7 ratifies a bound and leaves
  the figure to the implementing lane; that is unchanged for every tiling this ADR does
  not reach.
- **Whether the retention horizon should stretch so that fewer episodes expire
  unobserved.** ADR-0074 §7 declines it and ADR-0212 §9 declines it again; nothing here
  reaches it.
- **When the next benchmark run happens, or what it costs.** §3 rules only that a
  cross-change comparison needs the earlier arm re-run. Scheduling that is the owner's.

### 6. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is applied below to a **named clause** of each earlier ADR, in that
section's own currency: "Would a reader holding only the earlier ADR now act differently,
or read one of its clauses more widely than it now holds?"

> **Normative.** **(a) This ADR partially supersedes ADR-0162**, in ADR-0070 §3's sense,
> in exactly one scope and no other: **§7's window-overlap clauses, as they reach an
> observation walk whose page is selected by the ADR-0212 watermark.** A reader holding
> only ADR-0162 today builds such a walk with an overlap of *k* ≥ 1, because §7's last
> clause tells them to in terms; after this ADR they build it with *k* at 0. That is
> ADR-0070 §1's test met on its first limb. The pair on ADR-0162's `Status` line is
> `Partially superseded by ADR-0220 (§7's window-overlap clauses, as they reach an
> observation walk paged by the observation watermark)`, plus the appended dated note
> ADR-0070 §1 requires.
>
> **Inside the scope, and named so no reader has to derive it: §7's bound on *k* goes
> with the overlap clause it bounds.** "*k* is at least 1 and at most
> `observation_batch_size // 2`" is one of the window-overlap clauses this scope names,
> and for a watermark-paged walk it is replaced rather than narrowed — otherwise §1's *k*
> of 0 and §7's floor of 1 would both be in force over one walk, which no implementation
> could satisfy. Inside the scope for the same reason, and in that walk only: §7's
> batch-of-1 exception, which decides *k* from the batch size, and the 2026-08-19
> amendment's progress-over-overlap floor, whose protasis ("Where a window holds no more
> than *k* episodes") cannot be met at a *k* of 0. Neither of those two is contradicted by
> §1 above; both are simply left without work to do there.
>
> **Not replaced — every other application of §7, and every other section of ADR-0162.**
> Outside a walk paged by the watermark, §7 binds exactly as it did, with its bound on
> *k*, its batch-of-1 exception, its amendment floor and its reasons whole: it binds the
> benchmark harness's driver while that driver drives a tail-reading build, it binds any
> tiling a later lane introduces elsewhere, and its clause making a carried episode "a
> full member of the window it is carried into" governs wherever an overlap exists. Every
> other section of ADR-0162 — §1's completeness rule above all — stands exactly as
> ratified, and no sentence of §7 is rewritten.

**Why the pair names this ADR and not ADR-0212, when ADR-0212's clauses are what do the
replacing.** The substantive work is ADR-0212 §§1/3/5's, and this ADR says so throughout
rather than claiming a mechanism it did not build. But ADR-0082 §1 makes the record owed
of the later ADR that "amends a named clause of that earlier ADR, **and the later ADR
states which clause, in its own text**", and ADR-0212's text names no clause of ADR-0162,
contains no reference to it, and states no scope a reader could defer extent to. ADR-0070
§4's machine-legible half exists so a reader learns "which ADRs to defer extent to"; a
pair pointing at ADR-0212 would send them to a document that never mentions ADR-0162 and
from which the extent cannot be read at all. This ADR is also not merely clerical: the
conflict admitted a genuine fork — §7 could have been honoured and ADR-0212 amended
instead — and §§1–3 above rule that fork, accept the loss, and bind the harness. Naming
this ADR in the pair is therefore both the reading ADR-0082 §1 supports and the one that
leaves a reader of ADR-0162 somewhere useful.

> **Normative.** **(b) This ADR amends ADR-0212** — §10's closing clause, which reads
> "Everything else about this ADR is a **stacked addition** under ADR-0082 §1: one member
> on one `core` type, three operations on one non-promoted Protocol, and **no other
> ratified clause read differently after it**." Its last limb is over-wide: ADR-0162 §7
> is a ratified clause that is read differently once ADR-0212 §§1/3/5 bind, and a reader
> holding only ADR-0212 would take §10 as the exhaustive list of what it disturbs and
> would not think to check ADR-0162. That is ADR-0070 §1's test met on its second limb.
> The record is the **appended dated note alone** — ADR-0212's `Status` already carries
> the leading `Partially superseded by` token from ADR-0218, and ADR-0082 §2 rules that
> "Where an ADR's `Status` carries the leading `Partially superseded by` token, no
> amendment qualifier is written on that line."
>
> **Not replaced — everything else of ADR-0212.** §10(a), §10(b) and §10(c)'s three
> partial supersessions and their scopes; §1's meaning and its two named cases; §2's
> order; §3's candidacy, order and per-pass bound; §4's tail start; §5's advance, its
> monotonicity and its residual; §6 as ADR-0218 left it; §7's upgrade discipline; §8's
> surface; and §9's deferrals all stand as written and are relied on here.

**An amendment, not a supersession, and the difference is that nothing of §10 is
withdrawn.** ADR-0212's three declared supersessions remain correct and complete as
declarations; what this ADR adds is a fourth ratified clause to the list §10's closing
sentence implicitly closed. ADR-0070 §1's amend-in-place rule fits it exactly — the
change alters no decision ADR-0212 made and rewrites none of its text.

**One reading would make this record unowed, and it is not taken.** If ADR-0220 rather
than ADR-0212 is what changes ADR-0162's reading, then §10's "after it" stayed literally
true until this ADR existed, and no record would be owed on ADR-0212 at all. That reading
is too clever to act on: the two marked clauses became incompatible the day ADR-0212 was
ratified, and this ADR rules which yields rather than creating the collision. Recording it
is the direction that cannot leave a reader of ADR-0212 acting on a clause the corpus has
since contradicted — ADR-0136 §7's precedent, quoted by ADR-0212 §10 itself: "a merged
ADR-0136 sitting beside an unrecorded ADR-0015 is the window ADR-0082 exists to close."

> **Normative.** Everything else about this ADR is a **stacked addition** under ADR-0082
> §1. It adds no obligation that contradicts a sentence of ADR-0111, ADR-0077 or
> ADR-0074, and no clause of any of the three is read differently after it: ADR-0111 §3's
> at-least-once guarantee is about repetition after a crash and is untouched, ADR-0077
> §8's skip-without-backfill rule is untouched, and ADR-0074 §5's rule that an
> unresolvable id is "skipped, not an error" is untouched.

## Consequences

**Easier.**

- **PR #1829 can go green.** The 12 failing benchmark tests fail for one reason, that
  reason is now decided, and the lane has a fence and a ruling instead of a stop.
- **The walk terminates and a repeated pass is a no-op, with nothing arguing otherwise.**
  ADR-0212 §5's guarantee no longer sits beside a ratified clause demanding the
  re-selection it forbids, so a reader implementing the selector has one instruction.
- **Ingestion gets cheaper on the benchmark path.** The overlap cost
  `batch / (batch − k)` in passes over a corpus, which ADR-0162 §7 states; at *k* of 0
  that factor is 1.

**Harder.**

- **The boundary loss is real, uncounted and unmitigated on this path.** §2 accepts it
  deliberately; it is not measured, and nothing in the pipeline reports it. A run that
  wanted to know its size would have to be designed to measure it.
- **Benchmark history is cut on the ingestion side.** Comparing a post-change figure to
  pilot-5's needs the earlier arm re-run, which is real spend the owner has to schedule.
- **`IngestionSummary.episodes_reobserved` loses the explanation it used to have.** The
  driver produces no re-observation any more, so a reader meeting a non-zero value has no
  expected cause for it and will read it as a defect in the walk — where #1837 records
  that the value is a difference between two counters incremented on different tests
  rather than a per-episode count. The counter is left exactly as it is here,
  deliberately.

**What would trigger revisiting this.**

- **Evidence that boundary facts are being lost at a rate that matters.** The measurement
  §7 called "an empirical question […] which no run has measured" is still unmade; a run
  that made it and found the loss large would put a mitigation back on the table — as a
  new operation under #1789 or as an ADR of its own, never as a lower watermark.
- **A user-facing need for deliberate re-observation being reported**, which is #1789's
  own condition and would give the buy-back §2 names a spelling.
- **A second tiling walk being built that is not paged by the watermark**, which ADR-0162
  §7 binds unchanged and which this ADR deliberately does not reach.
