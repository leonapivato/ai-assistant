# 243. A review loop diagnoses itself at the fourth reviewed tree and chooses one next activity, and a verified low-impact finding may be acknowledged without an issue

- Status: Proposed
- Date: 2026-09-10
- **What this changes and what it does not.** It adds two obligations, both on
  the author's side of a review loop. A **dispatched lane** writes a diagnosis on
  its pull request at a counted point and names one next activity; and any author
  may dispose of a **verified** low-impact finding as *acknowledged, no action
  warranted* instead of filing an issue for it. No review round is forbidden, no
  round count is capped, no merge is authorised, no check fails on either
  mechanism, and `scripts/codex-review.sh` and `scripts/ship.sh` are untouched.
  ADR-0138 §1's handoff trigger is not moved and gains no second arm. No Protocol,
  no `core/types.py` value and no runtime behaviour is decided here.

## Context

### Where this came from

Two rulings on the dev-process umbrella **#2166**, taken together because they are
one text: **#2160** ("pilot a diagnosis checkpoint for expensive review loops") and
**#2164** ("allow a grounded no-action disposition without creating a backlog
issue"). Each names the other's half of the loop — what an author does when the
loop stops converging, and what an author does with a finding that is true and not
worth acting on. Both issues keep a pilot deliverable open past this change; this
ADR closes only their ADR half.

### ADR-0138 changed who holds the loop; it did not change what the loop does

ADR-0138 §1 hands a dispatched lane's review loop to a successor at seven rounds
per lens or churn 1.5, and §4 requires a comment carrying the standing findings.
Its own account of why that is worth the successor's spin-up:

> **The successor is a genuinely different reader (§4).** What made #475 and #945
> expensive was not that rounds were spent but that they were spent by the author
> of the text under review, re-reading their own prose. Round 8 under a new holder
> is the first round in the loop conducted without that.

**PR #2136 is that mechanism working exactly as written and not being enough.** It
carried ADR-0238 through **four** ADR-0138 §1 handoff comments — dated 2026-09-06,
two on the rounds arm, one on the churn arm, one unlabelled as to arm — and three
STOPs, under **five** holders, and its ship comment records the aggregate at the
end:

> _round 26 · 2256 lines net across 27 commit(s) · churn ≥2.4× (5374 touched;
> lower bound — history rewritten, earlier rounds not counted)_

Every handoff did what §4 asks. The first one's own summary of the standing
findings was accurate, its per-lens counts were right, and it named the next
action. What no holder was ever obliged to do — and what none of the five did — was
say **why the loop was expensive**: whether round *N*'s findings were new defects,
or the previous fix coming back, or two readings of one clause being alternated
between. Each new holder read a list of findings and ran the next round, which is
the activity the loop was already failing at.

That is the gap. ADR-0138's remedy is a change of **reader**; it has no clause
that changes the **activity**, and a loop can pass through five readers still
doing the one thing that is not working.

### The activity that does not work, twice on the record

**#1684 — alternating fixes for two readings of one sentence.** ADR-0202 §8 says
two things that cannot both be literal, and PR #1679's adversarial lens found each
half in turn:

> PR #1679's review found the first reading on rounds 2 and 4 (blocker: "can bind
> an already-expired certificate") and the second on round 3 (blocker: "can
> disclose a bootstrap value before refusing to start"), having taken the fix for
> round 2 in between. Each finding is correct about the code and each is forbidden
> by the other's reading — the deadlock shape #1155 records.

Three rounds, three correct findings, no possible convergence — because the
question was not about the code at all. Another round could not have answered it,
and the loop had no obligation to notice that.

**#1155 — a factually false finding has no channel back.** The architecture lens
twice returned `BLOCK` on ADR-0155 on a miscount of ADR-0154 §6's marked clauses,
recurring "in substantially identical form on a tree whose only change was
returning a header from `Accepted` to `Proposed`". #1155's own statement of the
author's position:

> So when a lens raises a finding that is **factually false**, an author has
> exactly two moves: comply (introducing the defect the finding describes), or
> waive and proceed. There is no third move that puts the counter-evidence in
> front of the lens and lets it reconsider on the merits.

The rebuttal channel #1155 asks for is a change to how `scripts/codex-review.sh`
assembles its prompt and is **not built here**. What this ADR takes from #1155 is
narrower and needs no code: where the loop has reached the state #1155 describes,
the author is obliged to say so and to take a named exit, rather than to spend
another round discovering it again.

### What ADR-0020 refused, quoted, and why a diagnosis is not it

ADR-0020's `Alternatives considered`, in full, because it has been misquoted from
memory before:

> **A stop-rule the author applies to themselves** — "if a round's findings are
> all about text the previous round introduced, stop." This was option C's
> original form. Rejected: it asks for exactly the self-diagnosis that failed
> twice, the second time in an agent that had already articulated the failure mode
> in writing.

> **A hard round cap or diff-size threshold.** Rejected: see §2. It would have
> cost #90 its most valuable finding.

The first refusal is the one this ADR has to answer, because §1 below asks a
holder for a **diagnosis** in as many words, where ADR-0138 §1 was careful to ask
only for arithmetic. ADR-0138 §7 drew that line explicitly:

> What that refusal's own reason rejects is self-*diagnosis*, not
> self-*arithmetic*, and the two are different in exactly the way ADR-0020's
> evidence is about.

**Three things distinguish §1 from the refused rule, and each matters
separately.**

- **It is not a stop-rule; it stops nothing.** ADR-0020 refused a self-diagnosis
  *as the thing that decides whether the loop ends*. §1's diagnosis decides
  nothing about ending: no round is forbidden, no merge is authorised, no lens is
  made terminal, and no handoff is triggered by it. It selects an **activity** for
  a loop that continues either way.
- **The trigger is arithmetic, and only the content is judgement.** What fires §1
  is the same number ADR-0138 §1 reads and `scripts/codex-review.sh` already
  prints. ADR-0020's evidence is that an agent cannot tell round 9 from round 2;
  it is not that an agent cannot read a counter that says 4, and it is not that an
  agent cannot write down what the last four rounds contained.
- **The output is published and read by someone else.** ADR-0020's finding is that
  the loop was broken "from outside, by someone holding an aggregate view", and
  ADR-0138's mechanism is to route it there at seven. A diagnosis on the PR routes
  the same view to the same reader at four, in a form that reader can act on — and
  it does so *before* the successor's spin-up is spent rather than after.

That third point is the whole economy of this ADR. ADR-0138's remedy costs a
handoff; §1's costs a comment.

### The second question: the triage rule's "otherwise" branch

`CONTRIBUTING.md` → "Triage every finding — do not let the PR grow to absorb them"
has two branches and the second is unconditional:

> - **Fix it now** if it is `blocker` or `major` **and** concerns code in the
>   current diff.
> - **Otherwise open an issue** and leave the PR alone — a `minor`, a `nit`, or
>   anything about code the PR merely sits next to.

The rule is right about what it was built for: it is what stops a PR growing under
review, one finding-fix commit at a time, and #2164 says so before asking for the
change. What it also does is convert every true `nit` into a tracker row that
someone will later read, triage and close, and #2164's ground is that this "can
turn low-value suggestions into permanent tracker work". The missing verdict is
not *rejected* — the finding is true — and not *deferred* — nobody intends to do
it. It is **acknowledged, and no action is warranted**.

### What the published disposition record actually carries

#2164 asks for the disposition rendering to be updated "only if necessary". It is
not sufficient, and the reason is worth recording because the name misleads.

`scripts/ship.sh` → `render_dispositions` publishes a snapshot written by
`scripts/codex-review.sh` → `_write_snapshot`. That snapshot's `status` field takes
exactly two values, and both are written from the **reviewer's** behaviour, never
the author's: a finding this round raised is `open`; one present in the prior
snapshot and absent now is carried forward `retired` — the script's own comment
calls it "Codex's own reassessment: it stopped raising it", and the rendered
section warns the reader that "its withdrawal is not separately recorded".

So the published list is the **reviewer's** ledger. It carries no author triage
verdict at all today — not fix-now, not deferred, not rejected-as-false, not
waived-with-rationale. Adding one of five verdicts to a two-valued reviewer-side
field would misreport the other four as absent; carrying all five is a change to
both scripts and to ADR-0025 §4's finding schema, and that is a different lane's
work. §8 states where the verdict is recorded instead, and files the mechanical
carry as an issue rather than half-building it here.

## Decision

**We will require a dispatched lane to diagnose its own review loop at a counted
point and to name one next activity, and we will allow a verified low-impact
finding to be disposed of without an issue.**

### 1. The checkpoint's trigger

> **Normative.** A dispatched lane writes a **diagnosis** on its pull request once
> **four substantively reviewed trees** have been recorded under its current
> holder, and before that holder invokes a further review round.

> **Normative.** A *substantively reviewed tree* is a tree of the branch for which
> **any** review lens has a recorded `.review/` artifact and whose content differs
> from the previously reviewed tree. The count is **persona-agnostic**: it is the
> quantity `scripts/codex-review.sh` already counts, so a byte-identical rebase, a
> squash, an amend and a second lens on one tree each count no tree, an ADR-0165
> §2 ratification flip counts none because the round it takes reviews and records
> its parent's tree, and a round that recorded no artifact counts none whatever
> figure its launch printed.

> **Normative.** A holder's count is the number of substantively reviewed trees
> recorded on the branch, less the number recorded in the handoff comment
> (ADR-0138 §4, as §6 below extends it) under which the holder took the lane; a
> lane's first holder counts from zero. A holder whose tenure ends before four
> owes no diagnosis.

The count is per **holder** and not per branch for ADR-0138's own reason, applied
to this mechanism: its §8 declines a per-branch count — "Declined in §2" — because
"it hands a successor a spent budget, so the second holder hands off on its first
round and the loop degenerates into a relay". A checkpoint counted per branch
fails the same way from the other end: it fires once and is then silent for
exactly the loops that have run long enough to need it. PR #2136 is the case — five holders, and a
per-branch checkpoint would have obliged one diagnosis, at round 4 of 26, from the
holder with the least to diagnose.

**The count is persona-agnostic where ADR-0138 §1's is per lens, and that is a
choice rather than an oversight.** ADR-0138 §2 needs the per-lens figure because
its trigger is about one lens exhausting a budget; the checkpoint is about the
*loop* — whether the change is converging at all — and every recorded round is
evidence about that whichever lens ran it. Defining it any other way would also
put the clause out of step with the only counter that exists:
`scripts/codex-review.sh` filters its round arithmetic on `branch=` and `tree=`
and on **no** `persona=` field, so a lens-restricted definition would oblige a
holder to compute a figure nothing prints, and would diverge from the printed one
on exactly the lane that runs a lens its required set does not demand — which
this ADR's own lane does.

**What is recorded at a handoff is the count of trees, not the number a launch
printed.** The printed round is recorded trees *plus the one in flight*, and a
round can print it and then record nothing: PR #2136's handoff comment reports
"round 4's launch was refused on the Codex usage limit and recorded nothing".
Handing a successor the printed figure of such a round would overstate its
baseline by one and push its diagnosis a tree late, so §6 requires the recorded
count.

Four is chosen against seven so that the checkpoint precedes the handoff under
every holder (§5), and because three rounds is what #1684 took to alternate twice.

### 2. What the diagnosis classifies

> **Normative.** The diagnosis classifies every finding still open at the
> checkpoint, and every finding fixed under the current holder since its previous
> diagnosis — or since it took the lane, where there was none — as exactly one of:
> a **new independent defect**; a **regression** from an earlier fix in this loop;
> a **specification dispute**, meaning two readings of one clause or a finding that
> contradicts a sentence of a ratified ADR; or **scope expansion**, meaning a
> finding about ground the change did not previously touch.

The four are the classes the record already contains. #1684 is the specification
dispute in its two-readings form, exhibited whole. PR #2136's round-6 architecture
`blocker` is the other form — a finding contradicting a sentence of a ratified
ADR, which its holder rebutted from ADR-0082 §7's text and left a standing
instruction about in the handoff comment: *"If a later round raises it again,
rebut — do not edit."* That is §3's grounded waiver, taken ad hoc and without a
name, by a holder who had no obligation to classify anything. ADR-0020's own
runaway cases were regressions, and its §2 gives the churn ratio as "the
mechanical proxy for 'consecutive commits fixing what the previous commit
introduced'". Scope expansion is the growth `CONTRIBUTING.md`'s triage rule exists
to refuse.

The classification is a judgement and this ADR does not pretend otherwise. What
makes it safe is §4: nothing turns on it mechanically, and a misclassification
costs a paragraph read by the coordinator, not a round or a merge.

### 3. The one chosen next activity

> **Normative.** The diagnosis names exactly one next activity for the loop, from:
> an **executable probe** — a test, a script or a run that decides the question the
> loop is circling; a **smaller decision**, including splitting the pull request or
> cutting its scope; an **adjudication request** to the coordinator, written on the
> pull request; a **grounded waiver**; or **continued review**, with the reason
> stated.

> **Normative.** Where the diagnosis classifies any finding as a **specification
> dispute**, the chosen activity is the adjudication request or the grounded
> waiver, and not continued review. An adjudication request quotes the clause and
> states both readings.

Continued review is on the list and is not a failure state — some loops are
expensive because the change is genuinely not right yet, which is ADR-0025's own
"honest limit" ("shared memory cannot shorten a loop where the reviewer is correct
and the change is not yet right"). What §3 costs such a loop is one sentence
saying so.

The exclusion is narrow and is the only thing in this ADR that removes an option.
It removes the one activity that provably cannot resolve the class it is excluded
from: on #1684's sentence, another round produced another correct finding
forbidden by the previous round's fix, indefinitely. `.claude/skills/dispatch-agents/SKILL.md`
§4 already defines the receiving end — the coordinator resolves an authority
conflict from the texts — so the exit exists and this clause routes to it.

### 4. What the checkpoint does not do

> **Normative.** Reaching the checkpoint, and writing the diagnosis, authorises no
> merge, forbids no review round, caps no round count, makes no lens terminal, and
> is not grounds for flipping a pull request out of draft.

> **Normative.** The checkpoint is not a handoff trigger. ADR-0138 §1's two arms
> are the only triggers of a handoff and neither is moved, narrowed or widened
> here. A diagnosis at four neither obliges nor forbids a handoff.

> **Normative.** Nothing here is mechanical. No check fails and no `just` recipe
> refuses on a missing or late diagnosis, and neither `scripts/codex-review.sh`
> nor `scripts/ship.sh` changes.

The first clause is #2160's own bound — "reaching the checkpoint never authorizes
a merge" — and it is the sentence that keeps ADR-0020's cap refusal intact from
the other direction as well: a checkpoint that licensed shipping would be a cap
wearing a diagnosis, and #2160 says in terms that "late findings can still be
valuable, so a round limit must not imply approval". ADR-0138's title says the same
thing about its own mechanism: it *forbids no round*.

The third clause is not modesty. Making it mechanical is the gate ADR-0020 §2
refused and ADR-0138 §8 refused again; the exposure it leaves is stated in
`Consequences`.

### 5. How the checkpoint and ADR-0138 §1 relate

> **Normative.** The checkpoint precedes the handoff: under every holder, four
> substantively reviewed trees are reached before seven rounds of any required
> lens are, so a holder that reaches ADR-0138 §1's rounds arm has already written
> at least one diagnosis, and a holder that hands off on the churn arm before its
> fourth tree writes none.

Both counts are per holder and both restart at a handoff, and ADR-0138 §2 supplies
the arithmetic that makes the first half unconditional: the persona-agnostic tree
count "is an upper bound on each lens's count", so a lens reaching seven under a
holder means that holder has recorded at least seven trees, and therefore passed
four. The relation is one of order and not of dependence: neither mechanism
conditions on the other, and §4's second clause says so.

### 6. A handoff carries the diagnosis

> **Normative.** A handoff comment under ADR-0138 §4 carries, in addition to what
> §4 already requires of it, the current holder's most recent diagnosis — its
> classification of each finding and the activity it chose — or states that none
> was owed, and the **number of substantively reviewed trees recorded on the
> branch** at the moment of handoff — which is the round number
> `scripts/codex-review.sh` printed for the last round that actually recorded an
> artifact, and never the figure printed by a launch that recorded none.

The diagnosis is the part of the record a successor most needs and ADR-0138 §4
does not ask for: §4 gets the successor the findings and the lane's assessment of
each, which is what to look at, and the diagnosis is why the loop is expensive,
which is what to do differently. ADR-0138's own `Revisit if` anticipates the
failure this closes — "if a successor is observed spending its rounds
re-litigating the predecessor's settled findings".

The tree count is required because §1's subtraction reads it and nothing else on
the record carries it. ADR-0138 §4 requires the *per-lens* counts, which are a
different quantity — equal to the persona-agnostic figure on a single-lens lane
and on a both-lens lane run as one round of both lenses, and not in general — so
§1 needs the number it actually subtracts stated in its own terms.

### 7. Acknowledged, no action warranted

> **Normative.** A review finding may be disposed of as **acknowledged, no action
> warranted** — a fifth verdict beside fix-now, deferred to an issue, rejected as
> false, and waived with a rationale — where the holder has verified the finding is
> true, states its concrete consequence, and judges that consequence too small to
> justify any future work.

> **Normative.** That verdict is never available for a finding of `blocker` or
> `major` severity, and never for a finding the holder has not verified against
> the text it describes. At those severities the available dispositions are
> exactly the ones `CONTRIBUTING.md` → "Triage every finding — do not let the PR
> grow to absorb them" already gives and this ADR does not move — fixed now where
> the finding concerns code in the current diff, deferred to an issue where it
> does not, or waived with a rationale on the record — and nothing here lets such
> a finding leave the loop with no disposition at all.

> **Normative.** A run whose remaining findings are all disposed of as
> *acknowledged, no action warranted* is terminal in ADR-0138 §3's sense, on the
> same ground as one whose remaining findings are deferred to issues: the triage
> rule does not require this pull request to fix them.

> **Normative.** This verdict is available prospectively, on a finding raised in a
> review round. It authorises no closure, relabelling or sweep of issues already
> filed.

The verdict is distinguished from its two neighbours by what the holder asserts.
**Rejected as false** asserts the finding is *wrong*; this one asserts it is
*right*. **Deferred to an issue** asserts the work is worth doing later; this one
asserts it is not worth doing at all. Requiring the concrete consequence in
writing is what keeps the three apart — a holder who cannot state the consequence
has not verified the finding, and the second clause then forbids the verdict.

The severity floor is #2164's own bound and it is not negotiable here: "no-action
must not silently hide a blocker". A holder who believes a `blocker` warrants no
action has one it believes is false, one about ground this PR does not touch, or
one it will waive with a rationale — and all three of those verdicts already
exist. **The floor removes one option and adds none**: in particular it does not
withdraw the issue branch of the triage rule, which is where a verified `major`
about adjacent, unchanged code has always gone and still goes. Saying otherwise
would have made this clause contradict the rule it restates, which is what
architecture review found on round 1.

### 8. Where the verdict is recorded, and what the published record can carry

> **Normative.** Each *acknowledged, no action warranted* disposition is recorded
> in the pull request — its description or a comment — as the verdict together
> with the one-line concrete consequence that justifies it, so that the
> coordinator and the reviewer at merge see every one.

The pull request is where `CONTRIBUTING.md` already puts a waiver's rationale
("write the rationale in the PR or the commit") and where `just ship` posts its
comment, so the verdict sits beside the review it disposes of and no new surface
is invented for it.

**The published disposition list cannot carry it, and this ADR does not change
that.** Context states what
`scripts/ship.sh` → `render_dispositions` publishes: a two-valued reviewer-side
`status`, `open` or `retired`, written by `scripts/codex-review.sh` from whether
Codex re-raised the finding. No author verdict appears in it. Putting one of five
there would misreport the other four as absent, and putting all five there is a
change to two scripts and to ADR-0025 §4's finding schema. That change is filed as
an issue rather than taken here, and §7's obligation stands on the pull request
record in the meantime — which is the surface every other triage verdict has
always used.

### 9. The five verdicts, worked

Four are drawn from the record; the fifth is constructed, and labelled, because
the verdict does not yet exist and no case can carry it.

- **Fix now.** Adversarial review of ADR-0138 itself, round 1, found that the
  successor-being-a-different-agent requirement sat in prose and therefore
  "obligated nothing (ADR-0089 §3) while every stated obligation was met by
  handing the loop back to the same agent". A `blocker`-class defect in the text
  under review; it was fixed into a marked clause in the same PR and the account
  kept in §4.
- **Deferred to an issue.** PR #1679's loop found that ADR-0202 §8's sentence
  cannot be satisfied both ways. The finding is true and the fix is real, but
  "`docs/adr/` was outside PR #1679's fence": the PR took the explicit ordering and
  recorded the reading, and the amendment became **#1684**.
- **Rejected as false.** ADR-0020 §1's two cases: a `blocker` claiming
  no-force-push protection covers feature branches when "it covers `main` only",
  and one claiming the `ai-assistant-*` glob included the primary clone when "it
  does not". Both stated with full confidence and specific-looking grounding.
  "Both were correctly rejected with grounding."
- **Waived with a rationale.** Adversarial review of PR #538 read ADR-0070 §1's
  gloss as a standalone test and concluded on that basis that correcting a
  misstated environment-variable name required a partially-superseding ADR,
  raising it as a `blocker`. ADR-0070 records that "the finding was waived on the
  merits with the reasoning recorded on that PR, and the change merged" — and that
  it was "a good-faith reading of one sentence". A `major`-or-above finding leaving
  the loop without a code change, because the rationale is on the record.
- **Acknowledged, no action warranted** *(constructed)*. A `nit`: a docstring's
  worked example names its variable `result` where every other example in the same
  module names it `outcome`. Verified — the inconsistency is really there.
  Consequence, stated: a reader of that one docstring pauses for a moment; no
  caller is affected, no test is weaker, and nothing later depends on it. Too small
  to justify a tracker row that someone must later read, triage and close. Recorded
  on the PR as one line, and the finding leaves the loop.

### 10. Scope

> **Normative.** §§1–6 bind a **dispatched lane** — an agent working in a clone
> under a coordinator who can brief a successor into it (ADR-0015 §2) — on the same
> test ADR-0138 §5 states. An author with no such coordinator has nobody to
> address an adjudication request to and is not bound by them.

> **Normative.** §§7–8 bind every author, dispatched or not.

The split is not symmetry for its own sake. §3's adjudication exit is the
checkpoint's load-bearing activity and it presupposes the coordinator ADR-0015 §2
supplies; a solo author asked to diagnose and then offered no exit would be asked
for the self-diagnosis ADR-0020 refused, with nowhere to send it. §7 presupposes
nothing but a finding and a pull request.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Each edit, with §1's test applied: would a reader holding only the earlier text now
act differently, or read one of its clauses more widely than it now holds?

- **ADR-0020's `Consequences` clause** *"The aggregate is advisory, so an author
  can still ignore it — deliberately; the alternative forbids findings worth
  having"* — **yes**, and it is the same clause ADR-0138 narrowed. A reader holding
  only ADR-0020 would read it as licensing a dispatched lane to run past four
  reviewed trees with no diagnosis owed. **Amendment**, and an ADR-0082 §1 record
  is owed: a qualifier on ADR-0020's `Status` and an appended dated note. **No
  ratified text of ADR-0020 is rewritten** (ADR-0070 §1).
- **ADR-0020's refusal of "a stop-rule the author applies to themselves"** —
  **no**, and this is the closest call in the document. §§1–3 stop nothing: §4's
  first two clauses forbid no round, authorise no merge, and trigger no handoff, so
  the refused rule's operative half — that the author's own diagnosis decides
  whether the loop ends — is not taken. The refusal's stated **reason** is that
  such a rule "asks for exactly the self-diagnosis that failed twice"; what failed
  twice was an author's judgement that the loop was fine, held privately and acted
  on by continuing. §1 asks for the opposite act: a classification written down and
  published to the reader ADR-0020 says is the only one that has ever ended a loop.
  A reviewer who disagrees should name which refusal's **reason** §§1–4 defeat, not
  which label they resemble — ADR-0082 §1's "**The test controls, not the label**"
  cuts in this direction too, as ADR-0138 §7 also observed.
- **ADR-0020's refusal of "a hard round cap or diff-size threshold"** — **no**.
  §4's first clause forbids no round; the cap's ground, that it "would have cost
  #90 its most valuable finding", loses nothing.
- **ADR-0020 §2 and §3** — **no**. §2's "Nothing here blocks" stays literally true:
  §4's third clause keeps both figures gating nothing and changes neither script.
  §3's acceptance rule, its tree anchor and its base half are untouched, and
  nothing here bears on what an artifact covers.
- **ADR-0020's `Revisit if`** — already discharged by ADR-0138 and not re-read
  here. This ADR does not rest on it.
- **ADR-0138 §4's enumeration of what a handoff comment carries** — **yes**. A
  reader holding only ADR-0138 would write a comment with §4's four items and
  believe it complete; §6 requires two more. **Amendment**, in that enumeration
  alone. §4's three-things definition of a handoff, its no-merge and
  no-self-succession clauses, and its definition of a successor are untouched.
- **ADR-0138 §3's terminality clause, in its second sentence** — **yes**. That
  sentence enumerates the two ways a run's remaining findings leave it terminal,
  "deferred to issues, or waived with a rationale recorded in the PR"; §7 adds a
  third, and a reader holding only §3 would read the pair as closed and refuse to
  call a no-actioned run terminal. **Amendment**, in that enumeration alone. §3's
  first sentence — the operative test, that the run leaves no finding
  `CONTRIBUTING.md`'s triage rule requires this PR to fix — is untouched and is
  what §7's third clause satisfies.
- **ADR-0138 §1, §2 and §5** — **no**, on all three. §1's arms are not moved and
  §4's second clause says so in terms. §2's per-lens arithmetic is used exactly as
  written and §1 above borrows its subtraction rather than changing it. §5's
  scope, and its promise that an author with no coordinator "reads ADR-0020 exactly
  as it stands", both stay true: §10 scopes the checkpoint the same way, and §7,
  which binds every author, bears on `CONTRIBUTING.md`'s triage rule rather than on
  ADR-0020.
- **ADR-0138 §8's declined alternatives** — **no**. It declined a cap, a
  ship-time confirmation, letting the lane judge whether it is close to terminal,
  and a mechanical trigger. §4 declines the same four again; §1's checkpoint is
  none of them, and in particular it makes no judgement about closeness to
  terminal — it reads a counter.
- **ADR-0025 §4** — **no**. Its two invariants, the per-finding disposition as the
  auditable unit, the bounded published rendering and the snapshot's anchoring are
  used as written and none is moved. §8 declines to extend the schema and files
  the extension instead.
- **ADR-0015 §§1–2 and §5, ADR-0027, ADR-0165, ADR-0136, ADR-0209** — **no**. What
  a review artifact covers, when a base move costs a round, the ratification-flip
  exemption and the gate anchors are theirs and are untouched. A diagnosis is
  neither a commit nor a round, so it opens no anchor and changes no coverage.
- **`CONTRIBUTING.md` and `docs/review/guide.md`** — **directed**, not amended in
  the ADR sense: `CONTRIBUTING.md` is ratified by ADR-0003 and this ADR is its
  authority for the triage rule's third branch and the checkpoint's statement
  there. `.claude/agents/worker.md` and `.claude/skills/dispatch-agents/SKILL.md`
  restate both for the readers who work from them.

### 12. Marking, review and ratification

This ADR is **marked** under ADR-0089: every obligation it imposes is in a
`> **Normative.**` block quote, and unmarked prose determines what a marked clause
means and supplies no obligation of its own. ADR-0020 stays unmarked — marking is
forward-only (ADR-0089 §5) — and its clause named in §11 is read as the prose
obligation it is.

It decides no Protocol, no `core/types.py` value and no contract surface, so
`CONTRIBUTING.md` → "Stop when the required reviews are green" makes **adversarial**
the mechanically required set. It was nonetheless dispatched to run **both lenses
from round 1**, on the same tree, and that is a dispatch decision rather than a
clause of ADR-0015 §1: what this change moves is `docs/review/guide.md`,
`CONTRIBUTING.md` and two ratified ADRs' clauses — the standing contracts a
reviewer is conducted under, and the subject of the architecture rubric's "ADR
adherence" limb. Running a lens the test does not require is always available;
this ADR does not widen the test, and a later change to review protocol owes only
what `CONTRIBUTING.md` says it owes.

It follows `CONTRIBUTING.md` → "Finishing an ADR PR": drafted and reviewed as
`Proposed`, and flipped by `just adr-ratify` once the required set is terminal on
one tree.

Nothing implements against §§1–8 until this has merged. Because §§1–6 widen the
review protocol every open lane is working under, and ADR-0209 §1 makes the
standing review contracts bind every artifact of every persona outright, the
merge is the coordinator's to time against the open lanes.

## Alternatives considered

**A second handoff trigger at four rounds.** Declined in §4. It is the cheapest
thing to write and the most expensive to run: PR #2136 shows what four handoffs
bought, and a trigger at four would have bought eight. ADR-0138 §1's arms are set
where a change of reader is worth its spin-up; four is where a change of
*activity* is worth a comment, and they are not the same threshold because they do
not cost the same thing.

**A round cap, in any form.** Refused again, for ADR-0020's reason and not a new
one: #90's round 6 is worth more than the rounds a cap would save. §4's first
clause is the operative refusal.

**Making the checkpoint mechanical** — a `ship` refusal, or a `codex-review.sh`
exit, past four undiagnosed trees. Declined: it is the gate ADR-0020 §2 refused
and ADR-0138 §8 refused again, and it would forbid the fifth round rather than
change what the fifth round is for. What a script can check is whether a comment
exists, not whether it diagnoses anything, so the check would be satisfied by a
comment saying nothing.

**Building #1155's rebuttal channel here.** Declined as scope. It is a change to
how `scripts/codex-review.sh` assembles a round's prompt and to what ADR-0025 §1's
injection budget carries; #2160 says in terms not to duplicate it. §3's
adjudication exit routes a specification dispute to a human instead, which is a
different remedy for an overlapping problem and needs no code.

**A diagnosis template, a new file, or a script that renders one.** Declined.
#2160 asks for "the existing PR/handoff record" and this ADR takes that literally:
the diagnosis is a comment. A template would be a second place for the corpus to
drift from, and a file would conflict across lanes for the reason ADR-0015 gives
about a tracked TODO file.

**Extending *acknowledged, no action warranted* to `blocker` and `major` findings**
— on the argument that a holder who has verified a finding is best placed to judge
its consequence at any severity. Declined on #2164's own bound: at those
severities the verdict is indistinguishable at a glance from a silent dismissal,
and *waived with a rationale* already occupies the ground with the rationale made
compulsory. The floor costs a sentence in the rare case and closes the failure
mode entirely.

**Changing the published disposition rendering to carry the verdict.** Declined in
§8 on what the code actually does rather than on cost. The rendered `status` is the
reviewer's, not the author's, so the change is not "add a value" but "add an
author-side record to a reviewer-side schema" — two scripts and ADR-0025 §4. Filed
rather than half-built.

**Requiring the diagnosis at every fourth tree, repeating.** Considered and not
adopted, and this is the weakest of the declines. §1 as written obliges one
diagnosis per holder past four, so a holder running to round 12 owes one, at four.
The repeating form is the obvious improvement and the reason to wait is that
nothing yet says what the second diagnosis contains that the first did not.
`Consequences` carries it as the first revisit condition.

## Consequences

**Easier.**

- **A long loop now says why it is long.** ADR-0138 routes the loop to an outside
  reader and hands them a list of findings; §1 hands them the shape of the loop —
  new defects, regressions, a dispute, or growth — which is the thing the
  coordinator can act on and the successor cannot reconstruct.
- **A specification dispute has a named exit and a forbidden one.** #1684 took
  three rounds to produce three correct, mutually exclusive findings. §3 sends the
  fourth to the coordinator instead, and `.claude/skills/dispatch-agents/SKILL.md`
  §4 already says what happens when it arrives.
- **The checkpoint costs a comment, not a spin-up.** It fires at four and the
  handoff at seven, so the cheap intervention is always available before the
  expensive one, and a loop that the diagnosis fixes never reaches ADR-0138 §1 at
  all.
- **A true `nit` can leave the loop without becoming tracker debt.** The verdict
  says something the previous four could not, and requiring the consequence in
  writing means the record is more informative than the issue it replaces would
  have been.

**Harder.**

- **The trigger is arithmetic and the diagnosis is not.** §1 fires on a counter,
  but §2 asks a holder to classify findings about text it wrote, which is
  judgement of exactly the kind ADR-0020 is sceptical of. §4 is what makes that
  affordable — nothing turns on the classification mechanically — but a
  wrong classification published confidently can mislead the coordinator, which a
  silent loop cannot.
- **Nothing fires the checkpoint.** No check, no hook, no `ship` refusal. This is
  ADR-0138's exposure inherited exactly, mitigated the same way: the number is
  printed in front of the holder on every round, and the living documents carry
  the obligation.
- **A fifth verdict is a fifth thing to get wrong.** *Acknowledged, no action
  warranted* is one sentence away from "I could not be bothered to file an issue",
  and the only thing separating them is the stated consequence. A holder that
  writes the verdict without the consequence has produced the failure #2164 warns
  about, and §7's second clause is prose.
- **The disposition record is now two records.** The reviewer's ledger is
  published by `ship`; the author's verdicts are in the PR text beside it. Until
  the issue §8 files is taken, reading the full disposition of a loop means reading
  both.
- **One more per-holder count to carry across a handoff, and it is a third
  quantity.** §6 adds the recorded-tree count to the handoff comment for §1's
  subtraction. ADR-0138 §4 already carries the per-lens counts and the churn, and
  the new figure is neither — it coincides with the per-lens counts on a
  single-lens lane and on a both-lens lane run as one round of both lenses, and
  parts from them otherwise. Exactly as ADR-0138 §2 records of its own
  subtraction, a handoff that omits it leaves the successor unable to compute its
  own budget.

**Revisit if** a second diagnosis under one holder is wanted — the repeating form
declined above should be ruled on once there is a case where the diagnosis at four
went stale before the handoff at seven; or if a diagnosis is observed being written
to satisfy §1 rather than to say anything, which would argue for a coordinator
reading it at the checkpoint rather than at the handoff; or if
*acknowledged, no action warranted* is observed used on a finding whose consequence
is not stated, which would mean §7's second clause is not carrying its weight and
the remedy is the published record §8 declines to build; or if the checkpoint fires
and the loop still reaches ADR-0138 §1's arms across several lanes, which would say
the diagnosis is the wrong intervention rather than the wrong threshold.

**Follow-on.** The living-document edits ride with this change:
`CONTRIBUTING.md` → "Triage every finding — do not let the PR grow to absorb them"
and "Report the review, then mark it ready — on your own judgement",
`docs/review/guide.md` → "For the author receiving findings",
`.claude/agents/worker.md`, and `.claude/skills/dispatch-agents/SKILL.md` §2 and
§4. The ADR-0082 §1 records on ADR-0020 and ADR-0138 ride with it too, for
ADR-0136 §7's reason as ADR-0138 §7 restates it: a merged ADR-0243 sitting beside
an unrecorded ADR-0020 is the window ADR-0082 exists to close. The mechanical carry
of author verdicts into the published disposition record is filed as an issue and
is a later lane's. **#2160 and #2164 each keep a pilot deliverable open**, by their
own terms; this change closes neither issue.
