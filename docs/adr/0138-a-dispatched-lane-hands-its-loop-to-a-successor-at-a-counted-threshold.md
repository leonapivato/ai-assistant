# 138. A dispatched lane hands its review loop to a successor at a counted threshold, and forbids no round

- Status: Proposed
- Date: 2026-08-12
- **What this changes and what it does not.** It adds one obligation on one class
  of author: a **dispatched lane** stops holding its own review loop past a
  counted threshold and hands it to a successor. No review round is forbidden, no
  change is capped, no check fails on a number, and `scripts/codex-review.sh` and
  `scripts/ship.sh` are untouched. No Protocol, no `core/types.py` value and no
  runtime behaviour is decided here.

## Context

### Where this came from

Batch #986's lane 2 wrote a handoff threshold into `.claude/agents/worker.md` and
raised a STOP against its own brief: the clause contradicted ADR-0020, which
rejects by name both a self-applied stop-rule and a hard round cap. **The STOP was
upheld** (PR #988, coordinator ruling 2026-08-11), the hunk was reverted, and the
substance was ruled to be this ADR's.

The trigger itself is the owner's, ruled 2026-08-11: **handoff at seven rounds per
required lens, or a churn ratio of 1.5, whichever fires first.** This ADR records
that ruling and supplies the definitions it needs to be applied. It does not
re-decide it — §6 carries the one part still open, as an open question rather than
a variation.

### What ADR-0020 refused, quoted

Two of its `Alternatives considered`, in full:

> **A stop-rule the author applies to themselves** — "if a round's findings are
> all about text the previous round introduced, stop." This was option C's
> original form. Rejected: it asks for exactly the self-diagnosis that failed
> twice, the second time in an agent that had already articulated the failure mode
> in writing.

> **A hard round cap or diff-size threshold.** Rejected: see §2. It would have
> cost #90 its most valuable finding.

And §2's ground for the second:

> Nothing here blocks. **A round cap would forbid round 6 of #90, which found
> `gh pr merge --match-head-commit` and closed a hole the author had wrongly
> called unfixable.** Value at the tail is real; the defect is that the tail is
> invisible, not that it exists. The failure mode this addresses is illegibility,
> so the remedy is a number, not a gate.

These are the sentences the STOP was right about, and they are quoted rather than
summarised because they have been misquoted from memory before. §7 says what this
ADR does and does not do to each.

### ADR-0020's revisit condition, and the measurement that fires it

ADR-0020's `Consequences` names its own expiry:

> **Revisit if** the printed aggregate is observed being ignored across several
> changes, which would argue for a soft gate — a confirmation at ship past some
> round count — rather than the hard cap rejected here.

The aggregate is printed on every run and `just ship` carries it into the PR
comment, so what a lane did with it is on the record. Read off those comments:

| PR | subject | printed round | net lines | churn |
| --- | --- | --- | --- | --- |
| #475 | ADR-0078 | **71** | 2,635 | ≥2.0× |
| #945 | ADR-0131 | **58** | 2,254 | ≥1.7× |
| #959 | wire notification | **24** | 7,891 | ≥1.2× |
| #987 | ADR-0136 | 9 | 463 | 1.4× |
| #988 | CONTRIBUTING finishing block | 4, then 6 after a rebase | 73, then 82 | 1.7×, then ≥1.8× |
| #995 | ADR-0137 | 3 | 302 | 1.1× |

The top three are the condition. ADR-0020's own runaway cases were 9 rounds and
"58+ commits, **79 review records**"; three lanes since have run to 71, 58 and 24
rounds with the aggregate printed at every one of them and acted on at none. The
condition is not "the aggregate is ignored once"; it is "across several changes",
and three is several.

What the revisit clause *asks for* is a soft gate rather than the hard cap, and it
offers one shape: "a confirmation at ship past some round count". This ADR does
not take that shape, and the reason is in the figures. At `ship` the rounds are
already spent — a confirmation there is a record of a 71-round loop, not a
remedy for one. The clause's operative word is **soft**, and §4 is what makes this
mechanism soft: nothing is forbidden.

### What the printed aggregate actually counts

`scripts/codex-review.sh` computes its round figure as the number of **distinct
reviewed trees of this branch**, plus the one in flight — keyed on the `tree=` and
`branch=` fields its own artifacts record, deliberately not on commits, so a
squash or a rebase does not reset it. It is **persona-agnostic**: two lenses
reviewing one tree count once.

So the printed number is not the per-lens count the owner's ruling asks for, and
§2 supplies it. The relation between them is worth stating because it makes the
printed figure usable as a screen: each lens's own count is a subset of the same
tree set, so **no lens can have reached seven while the printed round is below
seven**. On a single-lens lane — every lane in the table above — the two numbers
are equal.

The churn ratio is branch-scoped and persona-agnostic in the same way, and it is
sometimes printed as a **lower bound** (`≥1.8×`), because a history rewrite
removes the rework commits `git log --numstat` would have counted.

### Why a handoff is not the mechanism ADR-0020 refused

ADR-0020's diagnosis is that the loop cannot see itself:

> Every round is locally defensible. … Round 9 looks exactly like round 2 from
> inside.

> In both cases the loop was broken from outside, by someone holding an aggregate
> view. Neither terminated on its own.

> Self-diagnosis is not available as a remedy.

Every one of those sentences is about **the author**, who in ADR-0020's frame has
no outside observer. A dispatched lane has one by construction: the coordinator
who briefed it (ADR-0015 §2). So the remedy ADR-0020 found unavailable — a view
from outside the loop — is available here, and the mechanism that reaches it is
not a stop but a **change of holder**.

That is the whole distinction, and it decides both refusals:

- **A cap ends the change.** Round *N*+1 does not happen, and #90's round 6
  finding is lost. A handoff ends *this agent's* tenure. Round *N*+1 happens, on
  the same branch in the same clone, run by a reader who did not write the text.
  #90 would have handed off after round 7 and still run rounds 8 and 9.
- **The rejected stop-rule asks for a diagnosis** — "if a round's findings are all
  about text the previous round introduced" — and ADR-0020's ground is that this
  is "exactly the self-diagnosis that failed twice". §1's trigger asks for no
  diagnosis. It reads two numbers a script already printed. An agent that cannot
  tell round 9 from round 2 can still read that the counter says 9.

The honest residue: the lane does apply the trigger to itself, and ADR-0020's
refusal names "a stop-rule the author applies to themselves". What that refusal's
own reason rejects is self-*diagnosis*, not self-*arithmetic*, and the two are
different in exactly the way ADR-0020's evidence is about. This is the closest
call in the document and §8 records the alternative that turns on it.

### The churn arm has already misfired, and the rounds arm has already fired early

Both are in the table, and neither is hypothetical.

- **#988 is the churn arm's false positive.** It ended at churn 1.7× while
  *converging* — terminal `APPROVE` at round 4, with each round narrower than the
  last — and its post-rebase re-run reached terminal again at round 6. A churn-1.5
  trigger would have handed that lane off two cheap commits from done. Its ratio
  was high because the diff was 73 net lines: churn is a ratio, and a small
  denominator makes ordinary revision look like rework.
- **#959 is the churn arm's false negative, and it is the worse one.** Twenty-four
  rounds and 7,891 net lines at churn ≥1.2×. The churn arm never fires on it at
  all. The one lane in the table that most needed an outside view is the one the
  churn arm cannot see.
- **#987 is the rounds arm firing early.** Nine rounds to terminal, single lens,
  so the arm fires after round 7 on a lane two rounds from done — and rounds 7 and
  8 each produced a real (minor) finding. What that costs is a successor's
  spin-up, not a finding: rounds 8 and 9 still run.

Counted over the six lanes: the rounds arm fires on four and is right on three;
the churn arm fires on three, is right on two, and misses the 24-round lane. §6
carries what follows from that, unadopted.

## Decision

**We will require a dispatched lane to hand its review loop to a successor at a
counted threshold, and we will forbid no round in doing so.**

### 1. The trigger

> **Normative.** A dispatched lane hands its review loop to a successor when a
> required review lens has recorded **seven rounds under the lane's current
> holder** (§2) and that lens is not terminal (§3). Where a change requires two
> lenses, the count is kept separately for each and the handoff is owed as soon as
> either reaches seven. The lane does not itself invoke an eighth round of that
> lens.

> **Normative.** A dispatched lane also hands its review loop to a successor when
> the churn ratio printed by `scripts/codex-review.sh` first reaches 1.5 during
> the current holder's tenure and **at least one required lens is not terminal**
> (§3). A holder
> that took the lane on a ratio already at or above 1.5 does not hand off on that
> ground. Where the ratio is printed as a lower bound, this clause is satisfied
> only when that lower bound is itself at least 1.5.

The two arms are separate clauses because they are separable obligations
(ADR-0089 §2): either can fire without the other, and the table in Context has a
lane for each case. "Whichever fires first" needs no clause of its own — each
obliges the handoff independently, so the first to be satisfied is the one that
does.

**The churn arm's condition is "at least one lens open", not "no lens closed",
and the difference only shows on a two-lens change.** Adversarial can go terminal
at round 1 while architecture runs on; a condition reading "no required lens is
yet terminal" would be false from that moment and would switch the churn arm off
for the rest of the loop — silently, and precisely on the lanes with two lenses to
spend. On a single-lens change the two readings are the same condition.

**There is no near-terminal exception, and that is deliberate.** #987 is the case
that would want one: two rounds from done when the arm fires. An exception for it
would read "unless the lane judges it is close", which is the self-diagnosis
ADR-0020's evidence says is unavailable — an agent two rounds from terminal and an
agent twenty rounds from terminal both believe they are close. The cost of the
fixed number is a successor's spin-up on a lane that was nearly done; the cost of
the exception is that the trigger never fires.

### 2. What a round counts, per lens

> **Normative.** A lens's round count on a branch is the number of distinct trees
> of that branch for which that lens has a recorded `.review/` artifact, plus the
> run in flight — `scripts/codex-review.sh`'s own round arithmetic restricted to
> one `persona=` field. A holder's count is that number less the count recorded in
> the handoff comment (§4) under which the holder took the lane; a lane's first
> holder counts from zero.

> **Normative.** The round figure `scripts/codex-review.sh` prints is
> persona-agnostic and is not the per-lens count §1 reads. It is an upper bound on
> each lens's count, so a printed round below seven is sufficient to show no lens
> has reached seven, and on a single-lens change the two figures are equal.

Subtracting at the handoff is what keeps the successor from inheriting a spent
budget and handing off on its first round. It costs one line in a comment the
handoff writes anyway, and it is why §4 requires the counts to be in it.

### 3. When a lens is terminal

> **Normative.** A lens is *terminal* for §1 when its latest recorded run leaves
> no finding that `CONTRIBUTING.md` → "Triage every finding — do not let the PR
> grow to absorb them" requires this PR to fix. A run whose remaining findings are
> all deferred to issues, or waived with a rationale recorded in the PR, is
> terminal.

This is the sense `CONTRIBUTING.md` → "Stop when the required reviews are green"
already uses; it is restated inside a clause because §1 conditions on it and a
marked clause carries its own conditions (ADR-0089 §3).

### 4. What a handoff is

> **Normative.** A handoff is three things and stops there: a comment on the PR;
> a report to the coordinator; and the lane ceasing work on the branch. The
> comment carries every standing finding with the lane's own grounded assessment
> of it, which findings the lane treats as settled and which it contests, the
> exact next action it would have taken, and the per-lens round counts and churn
> ratio at the moment of handoff.

> **Normative.** A handing-off lane does not merge, does not flip the PR out of
> draft on the strength of a lens that is not terminal, does not choose its own
> successor, and does not re-brief itself. Briefing a successor into the clone is
> the coordinator's act.

> **Normative.** A *successor* is an agent other than the handing-off holder,
> briefed fresh into the clone. The same run continued, or the same holder briefed
> again, is not a successor and does not discharge the handoff §1 requires; a
> holder that has handed off does not resume the loop on that branch.

**The successor being a different agent is a clause and not an aspiration.** It is
the entire mechanism: §1 is worth its cost only because round eight is read by
someone who did not write the text under review, and ADR-0020's finding is that
the author is the one reader who cannot see the loop. Left in the prose it would
have obligated nothing (ADR-0089 §3) while every stated obligation was met by
handing the loop back to the same agent — which is the self-diagnosis remedy
ADR-0020 tested twice, reached by a route this ADR would have opened. Adversarial
review found it on round 1, and it is recorded rather than quietly fixed because
it is the under-marking hazard ADR-0089 §4 names, occurring in a document that
cites §4 for it.

The comment is the artifact, not the report: a report reaches one reader and a
successor arriving days later reads the PR. `.claude/agents/worker.md` already
carries this protocol for the case where a lane reports standing findings rather
than spending another round, and `Consequences` → **Follow-on** records that its
one-line pointer to §1 is a follow-on lane's to write, not this ADR's.

### 5. Scope, and what the trigger does not do

> **Normative.** §§1–4 bind a **dispatched lane** — an agent working in a clone
> under a coordinator who can brief a successor into it (ADR-0015 §2). An author
> with no such coordinator is not bound by them, has no successor to hand to, and
> reads ADR-0020 exactly as it stands.

> **Normative.** A handoff forbids no review round. The round that would have been
> the trigger's eighth is run by the successor, on the same branch in the same
> clone. Nothing here ends a change, caps its rounds, authorises shipping a lens
> that is not terminal, or licenses merging one.

> **Normative.** Nothing here makes the printed aggregate a gate.
> `scripts/codex-review.sh` and `scripts/ship.sh` are unchanged, no check fails on
> a round count or a churn ratio, and neither figure is on its own grounds for a
> review finding.

The scope clause is load-bearing rather than tidy. It is what keeps ADR-0020's
refusal of a self-applied stop-rule true for the reader ADR-0020 was written
about: a solo author asked to stop at seven rounds would be asked to stop, full
stop, which is the cap. A dispatched lane asked to stop at seven rounds is asked
to pass the loop to the outside view ADR-0020 says is the only thing that has ever
ended one.

### 6. The open question, dated

**The churn arm is recorded as ruled and is flagged for the owner's return.** The
measurement in Context postdates the ruling of 2026-08-11: #988's own loop, and
the #959 comparison, were read off the record on 2026-08-12, after the trigger was
ruled. Against six lanes the churn arm has one false positive (#988, terminal at
round 4 with the arm firing), one false negative that matters (#959, 24 rounds and
7,891 lines at 1.2×), and no case where it fired on a lane the rounds arm missed.

The coordinator's recommendation, **recorded and not adopted**: make the rounds
arm primary and demote churn to advisory — a figure the handoff comment reports
rather than a condition that triggers one. It is not adopted because the owner
ruled both arms, the owner is away under a mechanism-exits-only standing order,
and watering a ruled trigger down to advisory on an author's own reading is the
thing a lane may not do. §1's second clause therefore binds as ruled.

**This section states no obligation.** It is unmarked, and in a marked ADR
unmarked text supplies none (ADR-0089 §3). The revisit condition in `Consequences`
is where it is answered.

### 7. What this records against earlier ADRs

- **ADR-0020's two refusals — not undone, and no supersession is owed.** Each is
  quoted whole in Context and each survives on its own stated ground. The cap was
  refused because "it would have cost #90 its most valuable finding"; §5 forbids no
  round, so #90 loses none. The self-applied stop-rule was refused because "it asks
  for exactly the self-diagnosis that failed twice"; §1 asks for arithmetic that is
  already printed. ADR-0089 §1 records that undoing a ratified refusal takes a
  partial supersession (ADR-0042 §1 → ADR-0084 §12); neither refusal is undone, so
  none is taken. A reviewer who disagrees should name which refusal's *reason*
  §§1–5 defeat, not which label they resemble — ADR-0082 §1's "**The test controls,
  not the label**" cuts in this direction as well as the other.
- **ADR-0020 §2 — untouched.** "Nothing here blocks" is about §2's printed
  aggregate, and §5's third clause keeps it literally true: the aggregate still
  gates nothing and no check reads either figure.
- **ADR-0020's revisit condition — discharged.** Context gives the measurement it
  asks for and says where this mechanism departs from the shape it suggested, and
  why.
- **ADR-0020 — amended, and the clause is named.** Its `Consequences` → **Harder**
  sentence *"The aggregate is advisory, so an author can still ignore it —
  deliberately; the alternative forbids findings worth having"* becomes over-wide:
  a dispatched lane may no longer ignore the two figures past §1's thresholds. That
  is ADR-0070 §1's test failing on a named clause, so ADR-0082 §1 owes a record on
  ADR-0020 — a qualifier on its `Status` line, which is a plain `Accepted, §3
  amended by ADR-0025 and ADR-0027` with no leading `Partially superseded by`
  token and so takes one (ADR-0082 §2), and an appended dated note. **No ratified
  text of ADR-0020 is rewritten** (ADR-0070 §1): the clause stays where it was
  written, and the note records what narrowed it.

  **The pair lands here, in this change.** ADR-0136 §7 is the precedent and it is
  on point: it landed the equivalent record on ADR-0015 atomically, on the ground
  that "a merged ADR-0136 sitting beside an unrecorded ADR-0015 is the window
  ADR-0082 exists to close". The same window is the reason here. An earlier draft
  deferred the record to an issue (**#998**) on ADR-0089 §8's precedent for a
  one-file fence, and adversarial review blocked that on round 2 — correctly:
  ADR-0089 §8 deferred a `docs/adr/template.md` edit, not an ADR-0082 §1 record on
  an earlier ADR, and an open issue is not the record §1 owes. The lane's fence was
  widened by the one file (coordinator ruling, 2026-08-12, PR #999), and #998 is
  closed by this change rather than outliving it.
- **ADR-0015 — nothing owed.** §2's one-clone dispatch and the dispatcher role are
  relied on as ratified and relied on *more* than before; §5's scope clause is the
  reliance. §1's required-lens rule and §5's contract-ADR sequencing are untouched.
- **ADR-0025, ADR-0027 — nothing owed and nothing read across.** Loop identity,
  what a recorded review covers, when a base move costs a round and what `ship`
  accepts are theirs and are untouched. A handoff changes who invokes the next
  round, not what any artifact covers.
- **ADR-0136 — nothing owed.** Its anchors bind the successor exactly as they bind
  the first holder; a handoff is neither a rebase nor a push, so it opens no
  anchor. §7 of that ADR is cited above as precedent for a record's placement, not
  narrowed.
- **ADR-0089 — this ADR is marked**, and marking is forward-only (§5 of that ADR),
  so ADR-0020 stays unmarked and the clause named above is read as the prose
  obligation it is.
- **This ADR's `Status`.** It decides no Protocol, no `core/types.py` value and no
  contract surface, so the required set is **adversarial alone** (ADR-0015 §1;
  `CONTRIBUTING.md` → "Stop when the required reviews are green"). It follows
  `CONTRIBUTING.md` → "Finishing an ADR PR", pointed at rather than re-argued:
  drafted, reviewed and revised as `Proposed`, the status flipped only once the
  required review returned clean on one tree, and the required review re-run on the
  flipped tree. Nothing implements against §1 until this has merged (ADR-0015 §5).

### 8. Explicitly declined

- **A confirmation at ship past a round count** — the shape ADR-0020's revisit
  clause names. Declined on the figures: at `ship` the loop is over, so it records
  a 71-round lane rather than shortening one, and the lane it would ask to confirm
  is the one ADR-0020 says cannot read its own loop. **Revisit if** §1's mid-loop
  handoff proves too expensive in successor spin-up, since a ship-time confirmation
  costs nothing until the end.
- **A cap, in any form.** Refused here for ADR-0020's reason and not for a new one:
  #90's round 6 is worth more than the rounds a cap would save. §5's second clause
  is the operative refusal.
- **Letting the lane judge whether it is close to terminal.** Declined in §1. It is
  the self-diagnosis ADR-0020 tested twice and found unavailable, reintroduced as
  an exception.
- **Making the trigger mechanical** — a check that fails, or a `ship` refusal, past
  seven rounds. Declined: it is the gate ADR-0020 §2 refused, it would forbid the
  eighth round rather than rehousing it, and the numbers it would read are already
  printed to the one reader who acts on them. §5's third clause states the refusal.
- **A per-branch rather than per-holder count.** Declined in §2: it hands a
  successor a spent budget, so the second holder hands off on its first round and
  the loop degenerates into a relay. The subtraction costs one line in a comment
  the handoff writes anyway.
- **Deciding the successor's brief.** What a coordinator *tells* a successor —
  fresh eyes, scope cut, a ruling on a contested finding — is a dispatch decision
  and is outside this ADR. §4 fixes what the handing-off lane must leave behind
  and that the successor is a different agent, which is the handoff's mechanism
  rather than a brief's content; everything else about the brief is the
  coordinator's.

## Consequences

**Easier.**

- **A runaway loop now has an owner other than the agent inside it.** ADR-0020
  identified the remedy — an aggregate view held from outside — and could only
  print a number toward it. §1 routes the loop to the reader who holds that view,
  at a point where rounds remain to be saved.
- **The successor is a genuinely different reader (§4).** What made #475 and #945
  expensive was not that rounds were spent but that they were spent by the author
  of the text under review, re-reading their own prose. Round 8 under a new holder
  is the first round in the loop conducted without that.
- **The handoff comment is a better artifact than the loop that produced it.**
  Standing findings with a grounded assessment, committed versus contested, and the
  next action (§4) is the summary a reviewer at merge wants and that a 71-round
  thread does not contain.
- **The trigger costs nothing to evaluate.** Both figures are printed on every run
  and §2's per-lens count is the same arithmetic restricted to one field. No new
  tooling, no new command, no judgement.

**Harder.**

- **A lane two rounds from terminal can be handed off.** #987 is that case, in the
  data, before the rule exists. The cost is a successor's spin-up — reading the
  branch, the PR and the standing findings — against a lane that would have
  finished. §1 accepts it rather than buying an exception that reintroduces the
  self-diagnosis.
- **The churn arm is the weaker of the two and is binding anyway.** One false
  positive and one significant false negative in six lanes (§6). It is ruled, so it
  binds; the record of its performance is in this document rather than in a memory
  someone has to hold.
- **Handoff is procedural and nothing fires it.** No check, no hook, no `ship`
  refusal (§5). A lane that does not read its own counter is not stopped by
  anything, which is the same exposure ADR-0020's aggregate has — mitigated only by
  the counter being printed in front of the agent on every round and carried to the
  PR.
- **The per-holder count depends on a comment.** §2 subtracts the figure recorded
  in the handoff comment, so a handoff that omits it leaves the successor unable to
  compute its own budget. §4 requires it for that reason, and nothing enforces §4.
- **Two readings of ADR-0020 now have to be held at once.** A solo author reads it
  as ratified; a dispatched lane reads it against §1. §5 makes the test mechanical
  — is there a coordinator who can brief a successor — but it is a distinction that
  did not exist before.

**Follow-on.** The one-line `.claude/agents/worker.md` pointer to §1 is batch
#986's lane 1b and is briefed after this merges; nothing here implements itself
(ADR-0015 §5). The ADR-0020 record §7 names rides with this change and closes
**#998**, so nothing about this decision is left outstanding at merge.

**Revisit if** the churn arm fires on a converging lane again — one more #988 and
§6's recommendation should be ruled on rather than recorded, since two false
positives against zero unique catches is the case for demoting it; or if a lane
runs past seven rounds per lens with a coordinator available and no handoff
(the procedural exposure above is real and the remedy would be to move the trigger
into `scripts/codex-review.sh`'s output as an explicit instruction rather than a
number); or if a successor is observed spending its rounds re-litigating the
predecessor's settled findings, which would mean §4's committed-versus-contested
split is not carrying the weight §1 puts on it.
