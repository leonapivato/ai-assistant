# 165. Numbering stays at dispatch, and the ratification flip is the one exempt commit shape

- Status: Proposed
- Date: 2026-08-20
- **What this changes and what it does not.** It retains ADR-0015 §5's
  dispatch-time numbering unchanged, and it relaxes exactly one thing: which
  commit's content the review-coverage rule is evaluated against, in one
  mechanically recognisable case. The required review set, the gate and its two
  anchors (ADR-0136 §1, ADR-0166), ADR-0027 §3's floor, ADR-0027 §4's disclosure
  and ADR-0070 §1's rules on what an in-place header edit may be are all
  untouched (§7). No Protocol, no `core/types.py` value and no runtime behaviour
  is decided here.
- **Amends on ratification:** ADR-0020 §3 and ADR-0027 §2, the review-coverage
  rule. The edits are **not** made by this change — writing "amended by ADR-0165"
  onto a live ADR while ADR-0165 is only `Proposed` is the state claim ADR-0019
  forbids. §9 records their exact form, applies ADR-0082 §1's test to every ADR a
  reader might expect a record on, and states which get nothing and why.
- **Follow-on:** the implementation is a separate lane, briefed after this
  merges (§8). Nothing implements against this ADR before then (ADR-0015 §5).
- Resolves: #1044 (two ADR lanes shipped ready with `Status` still `Proposed`,
  and nothing mechanical caught either).
- Refs: #1226 §5 as replaced by its amendment 3 of 2026-08-20 — the ruling this
  ADR records; PR #1242, the withdrawn wide version, and issues #1244, #1245 and
  #1246 raised against it.

## Context

### The ruling, and the ruling it replaced

#1226 §5 originally moved **both** ADR numbering and ADR ratification to merge
time: one mechanical commit at merge would take `max(main) + 1`, rename the
file, substitute the number throughout, flip `Status` and stamp the date, and
that commit would be exempt from a fresh review round if its diff matched that
shape.

PR #1242 implemented it, over fifteen adversarial rounds under three holders.
The record of those rounds is the evidence behind the ruling now in force: every
one of the six defects found, and all three residual issues filed, sat in the
**numbering** half — allocation skipping a number and stranding it, recovery
from an `OSError` between the rename and the commit, staleness inferred from
filenames rather than ancestry, a base selected that was not current `main`, a
prefix match that silently deleted a caveat on the `Status` line, and a
duplicate-number mode that leaned on `strict` branch protection to close it
(#1245, #1246; #1244 for the `max()` ceiling). Both recurring benefits — the
saved review round and the #1044 class below — came from the **flip** half,
which nothing found a defect in.

Amendment 3 of 2026-08-20 repealed the numbering half before it was implemented
and left the flip half standing. This ADR records the narrow version. It is not
a continuation of #1242: numbering does not move, no file is renamed, no number
is substituted, and the exempt shape is a single line in a single file.

### What the flip costs today

`CONTRIBUTING.md` → "Finishing an ADR PR" fixes the order: an ADR is drafted,
reviewed and revised while `Proposed`; the status is flipped only once the whole
required set is green **on one tree**; and then — step 3 — the required reviews
are **re-run on the flipped tree**. Step 3 is not a judgement call and the
document is explicit about why it is owed: the flip edits a reviewed byte, so
the recorded tree no longer equals `HEAD`'s and ADR-0020 §3's unmoved-base test
refuses; the moved-base path does not rescue it either, because the flip moves
the reviewed patch identity as well. The round buys **coverage**, which is
mechanical, and nothing triages a status line.

So the round is paid, per ADR, for a commit whose entire content a reviewer
could not have judged differently — the decision text it ratifies is byte for
byte the text the reviewer already returned green on.

### How big the flip actually is, measured

The shape matters, so it was counted rather than assumed. Across the 121 commits
on `main` whose subject begins `docs(adr): ratify`:

| shape | count | share |
| --- | --- | --- |
| exactly one file, `- Status: Proposed` → `- Status: Accepted`, one line | 48 | 40% |
| anything larger (a ratification note, records on other ADRs, revisions) | 73 | 60% |
| any commit that also edited the `- Date:` line | 1 | 0.8% |

Over the twenty-five most recent, the bare-flip share is 6 of 25. The trend is
towards larger ratification commits, because recent ADRs increasingly append a
note recording the review set they ran and what the loop changed (ADR-0163 is
the largest at 54 lines). Two facts follow, and both are decision inputs rather
than afterthoughts: the exemption is worth **less than one round per ADR**, and
whether it applies is substantially the *author's choice* of whether to write a
ratification note in the same commit.

The `- Date:` figure is why §2 ends up excluding that line. Amendment 3 describes
the exempt shape as the `Status` flip "plus the date stamp"; on this corpus the
`- Date:` line records when the ADR was authored and ratification almost never
restamps it — once, on ADR-0019, in July. §2 records what that second line cost
when it was tried.

### The other half: #1044

Twice in two days an ADR PR was shipped and flipped ready with `Status` still
`Proposed` — ADR-0140 on PR #1027, caught after merge and corrected by a
follow-up flip PR, and ADR-0142 on PR #1037, the same remedy. #1044 records that
the written sequence is followable, that a lane in the same window followed it
correctly, and that **nothing mechanical catches the omission**: the gate has no
opinion on `Status` lines, `ship` anchors on content and not on ratification
state, and `gh pr ready` is a flag. The issue names the fix and its one
constraint — the refusal belongs at the *ready* boundary, because shipping a
genuinely `Proposed` ADR for an intermediate round is legitimate.

The two halves belong in one ADR because they are one mechanism read from two
sides: the flip becomes a shape a script can recognise, and the same knowledge of
that shape is what lets the finishing path refuse when the flip never happened.

## Decision

### 1. ADR numbers stay dispatch-assigned, and are computed rather than reserved

> **Normative.** An ADR's number is assigned by whoever dispatches the work, at
> the moment of dispatch, exactly as ADR-0015 §5 requires, and is **computed at
> that moment** from the highest number on `main` together with the numbers
> already claimed by in-flight lanes.

> **Normative.** No "next free" ADR number is recorded — in a document, an issue,
> a file or a dispatch brief — and none is read from such a record.

This is a retention and a writing-down, not a change. ADR-0015 §5 decides *who*
assigns and *when*; it says nothing about *how* the assigner arrives at the
number, and this clause supplies that and nothing else — a stacked addition under
ADR-0082 §1, recorded here and nowhere else (§9).

It is written down because the failure it forbids has happened: a recorded
next-free number goes stale the moment a lane merges ahead of the one holding it,
and the holder then either collides or leaves a gap. Computing at handoff cannot
go stale, because the computation happens after every merge that could have
changed its answer. The dispatch playbook has carried this as a standing lesson;
it is now a ruling.

**What #1226 §5 originally proposed here is not adopted.** Numbers do not move to
merge time, ADR files are not renamed after review, and `ADR-XXXX` self-references
are not substituted by a script. An ADR is authored numbered, as it always has
been, and cites its own number in its own text.

### 2. The exempt shape: one file, one line, and a predicate that is the whole of it

> **Normative.** A commit `C` with exactly one parent `P` is a **ratification
> flip** when every one of the following holds, and is not one otherwise: the
> diff `P..C` names exactly one path; that path matches `docs/adr/NNNN-*.md` with
> `NNNN` four digits; the path is *modified* — present in both trees, same mode,
> not an addition, deletion, rename, copy or binary change; the two blobs are
> identical except on header lines, meaning lines preceding the file's first line
> beginning `## `; the differing `Status` line reads exactly `- Status: Proposed`
> in `P` and exactly `- Status: Accepted` in `C`; and **no other line differs at
> all**, the `- Date:` line included.

Every clause of that predicate is there to remove a way for content no reviewer
read to ride along. One path, because a second file is unbounded. Modified and
not added or renamed, because a rename carries no hunks and its identity is a
function of its paths alone — ADR-0027 §2 measured that, and it is the case where
a byte-identical patch identity can cover content nobody saw. Header lines only,
because the Context, Decision and Consequences are the decision. Exact string
equality on both `Status` values rather than a prefix match, because a prefix
match on `Accepted` is precisely the defect PR #1242's round found: it silently
deleted a qualifier the line carried.

**The `- Date:` line is excluded, and this ADR's own review is why.** Amendment 3
describes the exempt shape as "the two-line flip in one ADR file", the second line
being the date stamp, and this ADR proposed it that way. Two adversarial rounds
took it apart, each correctly. A merely date-*shaped* second line lets an
unreviewed commit write `- Date: 1970-01-01` — historical metadata a reviewer
could have rejected, which is the one thing the predicate exists to exclude.
Binding that value to the commit's own author date does not repair it either,
because the author date is itself caller-supplied: `git commit --date=…` and
`GIT_AUTHOR_DATE` both set it, so the "trusted" source is the same hand writing
the line. There is no third source of a ratification date inside the commit, and
inventing one — a signature, a server-side clock — is machinery out of all
proportion to what it buys.

**What it buys is measured, and it is one commit.** Of 121 ratification commits on
`main`, exactly one ever edited the `- Date:` line, in July. So the exclusion
takes the exemption from a shape whose safety needed an argument down to a shape
that needs none — one line, one file, two exact strings — and costs the corpus a
case that has arisen once. **This narrows the shape the ruling authorised rather
than reversing the ruling**: it exempts strictly less than amendment 3 permits,
on the strength of amendment 3's own stated principle, which §6 records as
normative. An author who does need to restamp the date at ratification writes it
in the flip commit and pays the round, exactly as an author who writes a
ratification note does.

> **Normative.** One implementation of §2's predicate serves both sides: the
> recipe that *makes* a ratification flip and the check that *recognises* one are
> the same code, never two statements of one rule.

> **Normative.** The recogniser decides by rebuilding `C`'s blob from `P`'s under
> that same transform and comparing bytes, never by matching the diff against a
> pattern restating the rule.

A second, restated statement of a rule in a second place is what #751 records the
cost of — a hand-built replica of `scripts/ship.sh`'s floor test returned "clear"
for a base move that breached the floor, twice, because the replica and the rule
had drifted apart. The predicate above is small enough to state in prose *and*
small enough that one function is the whole of it; those two facts are the same
fact, and §6 is where that is made a principle.

### 3. Where the exemption enters the coverage rule

> **Normative.** Where a PR's `HEAD` is a ratification flip as §2 defines it,
> ADR-0027 §2's acceptance loop is evaluated against `HEAD`'s parent — its tree
> and its patch identity — and paths (a) and (b) then run exactly as written. In
> every other case the loop is evaluated against `HEAD`, unchanged.

This is a **re-anchoring, not a third acceptance path**. Nothing in ADR-0027 §2
is relaxed: (a) still refuses on any changed byte anywhere in the tree it
compares, (b) still requires a proper-ancestor base, a hashable and unchanged
patch identity, a clear floor and a published drift record, and an entry with
neither a hunk nor an `index` line still makes (b) unavailable. What changes is
one input to a rule that is otherwise untouched.

> **Normative.** The re-anchoring is not recursive and applies to `HEAD` alone: a
> ratification flip whose parent is itself a ratification flip earns the
> exemption only for the head commit, and the loop is then evaluated against that
> parent, which is not itself re-anchored.

> **Normative.** Nothing here bears on ADR-0027 §3's floor or §4's disclosure.
> Those govern a **base move** — a change to the history the PR is measured
> against — and a ratification flip is a commit the PR itself carries. A base move
> touching `docs/adr/**` still breaches the floor and still costs its round,
> whether or not `HEAD` is a ratification flip.

The exemption is available to `scripts/ship.sh` and to its `--drill` mode alike,
because the drill exists to answer the acceptance rule's own question with the
acceptance rule's own code (ADR-0027; `CONTRIBUTING.md` → "Report the review,
then mark it ready"). A drill that did not know about the exemption would predict
a round the ship would not charge, which is the drill disagreeing with `ship` —
the condition a lane is required to stop on.

### 4. An exemption that is used is disclosed, never silent

> **Normative.** Where the exemption is applied, the comment `ship` posts to the
> PR states that it was applied and names the flip commit and the parent the
> artifact was judged against, in the same comment that carries the review and
> the aggregate.

ADR-0027 §4 already refuses to let a moved base be "silently absorbed" and
publishes the whole file set instead, in front of the human at merge. The same
reasoning applies with more force here, because this exemption is asserted by the
repository's own code about the repository's own commit: the merge reviewer is
the only reader positioned to notice that a flip commit was not what it claimed,
and they can only notice if the claim is on the page.

### 5. The finishing path refuses to mark a PR ready with an ADR still `Proposed`

> **Normative.** A PR is marked ready through one documented recipe, and that
> recipe refuses while any `docs/adr/*.md` file the PR adds or modifies carries a
> `- Status: Proposed` header line. The refusal names the file.

> **Normative.** The refusal sits at the ready boundary and nowhere else.
> `just ship` continues to post a review for an intermediate round on a PR whose
> ADR is legitimately still `Proposed`, and refuses nothing on that ground.

That split is #1044's own constraint, and it is what makes the guard usable: the
whole reviewed life of an ADR is spent `Proposed`, so a refusal at ship would
refuse the normal case.

**What this guard binds, stated plainly, is the documented path** — a lane that
types `gh pr ready` directly is not stopped by it, because that command is
GitHub's and not this repository's. That is a real limit and it is accepted here
rather than engineered around: both #1044 occurrences were lanes following the
documented finishing sequence and skipping a step of it, not lanes evading a
check. A required CI job refusing a non-draft PR that carries a `Proposed` ADR
would bind harder, and is declined **now** as scope on a one-recipe remedy — it is
this ADR's stated Revisit condition, and the evidence that would trigger it is a
third occurrence of #1044's pattern past this guard.

### 6. The design principle: an exemption is as safe as its shape is small

> **Normative.** An exemption from a required review is admitted only for a
> commit shape decidable by rebuilding the commit from its parent under a single
> transform — so a shape needing a multi-step recogniser, a shape whose recogniser
> can disagree with its producer, and a shape carrying a free-form field are each
> outside what may be exempted.

> **Normative.** Widening the shape §2 defines takes a superseding ADR, and is
> never an implementation choice.

An exemption's safety is inversely proportional to the complexity of the shape it
exempts, and this is the clause that holds the line. The exempted commit is
unreviewed by construction, so everything a reviewer would have caught in it must
instead be excluded by the predicate — and a predicate is only as trustworthy as
a reader's ability to hold all of it at once. The wide version's shape had four
moving parts (allocate, rename, substitute, flip), of which three needed
filesystem state, ancestry or a `max()` over `main`; every defect found in fifteen
rounds was in those three. The narrow shape has one part and needs neither
filesystem state nor ancestry.

**What is deliberately not exempted, each for the same reason.** A flip commit
that also appends a ratification note. A flip commit that also applies the
amendment records an ADR schedules for its ratification, as ADR-0026 §6 and
ADR-0027 §7 do and as §9 of this ADR does. A flip that also restamps the
`- Date:` line. A flip that also corrects a typo. A flip of two ADRs at once. Each of these is a legitimate, common commit, and each
carries text no reviewer has read; each therefore falls outside §2's predicate
and costs its round exactly as today. This is the fail-closed direction, and it
is why §2's predicate refuses rather than accommodates.

The consequence is stated rather than hidden: on the corpus as it stands the
exemption would have applied to 48 of 121 ratification commits, and to 6 of the
most recent 25. An author who wants it can have it by not writing a ratification
note in the flip commit; an author who wants the note pays the round. Both are
correct outcomes.

### 7. What this ADR does not change

- **The required review set.** Adversarial for most changes, adversarial *and*
  architecture for a contract-surface one, unchanged (ADR-0015 §1;
  `CONTRIBUTING.md` → "Stop when the required reviews are green"). The exemption
  removes a *round*, never a lens: the required set still runs green on the
  `Proposed` tree before the flip, which is `CONTRIBUTING.md` → "Finishing an ADR
  PR" steps 1 and 2, untouched.
- **The gate.** ADR-0136 §1's two anchors bind exactly as before, and the closing
  anchor falls **after** the flip, so the full gate still runs on the flipped
  tree; ADR-0166 governs which `pytest` invocation discharges it. Nothing here is
  an exemption from any gate step.
- **ADR-0070 §1.** The flip is the same in-place ratifying header edit §1 already
  permits, made at the same point in the sequence, on the same branch, before the
  same merge. The append-only rule and the four permitted header edits are
  untouched, including the return-to-`Proposed` correction a post-flip finding
  triggers — a lane taking that route has left the exempt shape behind and is back
  at step 1 with the whole required set to earn.
- **ADR-0027 §§3–4 and §§5–7,** and ADR-0020 §§1–2. §9 states this against the
  texts.
- **ADR-0138.** Round counting is untouched; an exempted flip runs no round and
  so counts none, in either the per-lens count or the churn ratio.

### 8. The implementation is a separate lane, and what it may salvage

> **Normative.** Nothing implements against this ADR until it has merged
> (ADR-0015 §5, golden rule 5).

> **Normative.** The implementation is one lane, briefed after that merge, and
> its deliverables are exactly these: the producer recipe that makes a
> ratification flip; §2's predicate as one shared implementation; §3's
> re-anchoring in the acceptance loop, reaching `--drill` by the same code path;
> §4's disclosure in the posted comment; §5's ready recipe and its refusal; and
> the corresponding wording in `CONTRIBUTING.md` → "Finishing an ADR PR" step 3
> and "Report the review, then mark it ready", and in `CLAUDE.md`'s review
> paragraph.

**What that lane may salvage.** PR #1242's branch is kept for this purpose; its
pre-trim head is `acb7230f`. What still applies: exact-string matching on both
`Status` values rather than a prefix match, the refusal to run on a dirty tree,
the recovery discipline around a partially-applied commit, and the test shape
that pins each of those with a case that fails without its fix.

**What it may not salvage, because the ruling repealed it:** everything
concerning number allocation, `max(main) + 1`, file renaming, `ADR-XXXX`
substitution, staleness against a fetched base, and the `--no-fetch` and
`--base-branch` selection those needed. Issues #1244, #1245 and #1246 were filed
against that machinery; #1244 (the `max()` ceiling) and #1245 (duplicate numbers
shadowing) describe a mechanism this ADR does not adopt, and the follow-on lane
should close or re-scope them rather than implement toward them. #1246 —
`CONTRIBUTING.md` and ADR-0010 disagreeing about what `--admin` bypasses — is
independent of either version and stands on its own.

Until that lane lands, every ratification flip costs its round exactly as today,
because §2's predicate has no recogniser and §3's re-anchoring therefore never
fires. The intervening window is safe by construction rather than by care: the
absence of the mechanism is the conservative state.

### 9. What ratification does to ADR-0020 and ADR-0027, and to nothing else

ADR-0082 §1 decides whether a record is owed on an earlier ADR — "exactly when
the later ADR amends a named clause of that earlier ADR", by ADR-0070 §1's test
applied to the earlier ADR's *text*: would a reader holding only that ADR now act
differently, or read one of its clauses more widely than it now holds? §2 of the
same ADR decides where the record goes. The test is applied below clause by
clause, to every ADR a reader might expect a record on, and the answers include
two records and six explicit nothings. **The test controls, not the label**
(ADR-0082 §1): recording an amendment against an ADR no clause of which fails the
test is the mis-declaration that section names.

The edits are made **on ratification**, in this PR's own ratification commit, in
the form ADR-0026 §6 set and ADR-0027 §7 followed — a qualified `Status` line
plus a dated header note, with no ratified text rewritten. They wait for the same
reason those two waited: writing them while this ADR is `Proposed` is ADR-0019's
state claim. They are not deferred to the follow-on lane: a record is decision
bookkeeping and travels with the decision, and an ADR-0020 that still told its
reader the flipped tree is refused, after this merged, would be false for as long
as that lane took.

**ADR-0020 §3 — amended.** Its acceptance rule accepts an artifact "when its
recorded base **and** its recorded tree both match the PR's current merge base
and `HEAD`'s tree". Under §3 above, where `HEAD` is a ratification flip the tree
compared is the parent's, so a reader holding only ADR-0020 refuses what this
accepts: the clause is read more widely than it now holds, and the record is
owed. It is an **amendment and not a supersession** because §3's decision is the
*content anchor* — that coverage is decided by the content a review read rather
than by the commit it was filed under — and this ADR applies that decision rather
than replacing it. The bytes the reviewer read are exactly the bytes the parent
carries; the flip adds one the reviewer had no standing to judge. This follows the
corpus's own two prior treatments of this same clause: ADR-0025 and ADR-0027 each
changed what §3 accepts and each recorded an amendment scoped to §3, and ADR-0027
§7 states the form. Its `Status` line becomes

`- Status: Accepted, §3 amended by ADR-0025, ADR-0027 and ADR-0165; Consequences' advisory-aggregate clause amended by ADR-0138`

and a dated note is added to its header in the position that file already uses
for its most recent one — leading the existing notes, where the ADR-0138 note
currently sits above the ADR-0025 and ADR-0027 ones:

`Amended: <ratification date> by ADR-0165 — §3's acceptance rule compares the artifact's recorded tree against HEAD's tree. Where HEAD is a ratification flip as ADR-0165 §2 defines it — one ADR file, one changed line, Status Proposed to Accepted and nothing else — the comparison is made against HEAD's parent instead, so the review that covered the Proposed tree covers the Accepted one and the flip costs no round. Nothing else in §3 moves: the anchor is still content and not the commit, the base half is still ADR-0027 §2's, and every commit that is not a ratification flip is still judged against its own tree.`

**ADR-0027 §2 — amended.** Its acceptance loop is stated in terms of `HEAD`: (a)
requires the recorded tree to equal "`HEAD`'s tree", and (b) is computed over the
patch identity of the range ending at `HEAD`. §3 above takes both from the parent
in one enumerated case, so the same limb of ADR-0082 §1's test is met. Amendment
rather than supersession for the reason above, and scoped to §2 alone. Its
`Status` line becomes

`- Status: Accepted, §2's acceptance loop amended by ADR-0165`

and a dated note is appended to its header, after `Refs`:

`Amended: <ratification date> by ADR-0165 — §2's two acceptance paths are evaluated against HEAD's tree and HEAD's patch identity. Where HEAD is a ratification flip as ADR-0165 §2 defines it, both are taken from HEAD's parent and (a) and (b) then run exactly as written; the re-anchoring is not recursive and adds no third path. §2's two properties, the git patch-id --verbatim choice, the proper-ancestor requirement and the rules making (b) unavailable are untouched, as are §§1 and 3-7 — in particular §3's floor and §4's disclosure, which govern a base move and not a commit the PR itself carries.`

Nothing else in either document is edited.

**ADR-0015 — nothing owed, on both of its clauses a reader would suspect.** Its
§5 — "The operator dispatching an agent assigns its ADR number" — is *retained* by
§1 above, which supplies a computation §5 never addressed; every sentence of §5
stays true, so what §1 adds is a stacked addition recorded in this ADR alone
(ADR-0082 §1). Its Decision 1 says `ship` "refuses unless one exists for the exact
commit the PR head is on", which this ADR does change the shape of — but that
clause is already superseded, by name: ADR-0020's header reads "Supersedes:
ADR-0015 §1's freshness clause — that `just ship` 'refuses unless [a review
artifact] exists for the exact commit the PR head is on'. §3 below replaces the
commit with the reviewed *content* as the anchor", ADR-0015's own `Status` line
records the partial supersession, and ADR-0025 restates it ("ADR-0020 already
superseded §1's commit anchor"). A superseded clause takes no further record, and
the record this ADR does owe is written against ADR-0020 §3, the clause that
replaced it. Decision 1's live half — that the whole
loop including marking the PR ready is the author's to run without asking — is
untouched by §5 above: a mechanical precondition is not an escalation, and
ADR-0015 §1 itself enumerates the refusals `ship` already carries.

**ADR-0070 — nothing owed.** §1's four permitted in-place header edits include
"ratifying an ADR — `Proposed` → `Accepted`", and this ADR neither adds to that
list nor removes from it nor moves when the edit is made. §1's closing clause —
"These bound the append-only *form* of an edit, not the review a decision needs.
A substantive contract ADR is still reviewed while `Proposed` and ratified only
after … the ratifying edit records that review's outcome, it does not replace it"
— stays true word for word: the required set still runs green on the `Proposed`
tree, and what §3 above lifts is the *second* run of the same lenses over the same
decision text. §1 nowhere obliges that second run; it is obliged by ADR-0020 §3's
mechanical refusal, which is where the record is written. #1226 §5 originally
asserted that ADR-0070 carried the numbering line to be amended. It does not: its
mentions of numbering are ADR-0001's sequential-numbering rule, quoted in passing,
and §4's supersession-cycle argument that "an ADR is only ever superseded by a
*later*, higher-numbered ADR". Neither says who assigns a number or when. The
narrow version does not touch numbering at all in any case.

**ADR-0082 — nothing owed.** Its §§1–2 are what *decide* the records above rather
than being changed by them; every sentence of both stays true. #1226 §5 named it
alongside ADR-0070 as carrying a numbering line; it contains none.

**ADR-0025 — nothing owed.** Its §4 describes the shippable artifact as "pinned
to the final `(base, tree)`", which would be a stale description of the live rule —
except that ADR-0027 already re-pointed it, in the dated note ADR-0025 carries:
"§4's decision is unchanged — the shippable artifact is still the conversation's
terminal verdict, pinned to **whatever anchor ADR-0020 §3 defines**". This ADR
changes that anchor, which is exactly what the existing note anticipates, so no
sentence of ADR-0025 becomes false or over-wide. Recording a second amendment
would re-record what ADR-0027 already recorded.

**ADR-0136 and ADR-0166 — nothing owed.** Both anchors bind unchanged, the flip
sits before the closing one, and the gate is not what this ADR exempts anything
from (§7).

**ADR-0138 — nothing owed.** A round that is not run is not counted, in either
the per-lens count or the churn ratio; §§1–5 stay true as written.

**ADR-0019 — nothing owed; it governs.** It is the reason §9's edits wait for
ratification rather than being written now.

## Alternatives considered

**Keep #1226 §5's wide shape and fix the defects.** Rejected on the evidence the
ruling turned on: fifteen rounds, six defects and three residual issues, all in
the numbering half, against a benefit that lives entirely in the flip half. The
wide shape also acquires a dependency the narrow one does not have — its
`max(main) + 1` allocation is only collision-free while `strict` branch
protection holds, and #1245/#1246 are the residue of arguing about what
`--admin` does to it.

**Exempt the flip by a diff pattern rather than by reconstruction.** Rejected.
A pattern is a second statement of the rule, in a second place, maintained
against the first by care alone; #751 is the case study, where a hand-built
replica of `ship`'s floor test reported "clear" for a move that breached it. One
transform, used to produce and to recognise, cannot drift from itself.

**Widen the shape to admit a ratification note.** Rejected, and it is the
tempting one — it would roughly double the exemption's hit rate on the measured
corpus. A note is free text of unbounded length carrying the author's account of
the review, exactly the material a reviewer is for. There is no predicate over
free text that a reader can check, which is §6 restated.

**Put the `Proposed` guard in `ship` rather than at the ready boundary.**
Rejected on #1044's own analysis: an ADR is `Proposed` for its entire reviewed
life, and shipping an intermediate round is the normal case, so a refusal at ship
would refuse it.

**Add a required CI check for the `Proposed` guard instead of a recipe.** Not
rejected on the merits — it binds harder — but declined as scope here, and named
as this ADR's Revisit condition (§5).

**Admit the `- Date:` line into the exempt shape, as amendment 3's "two-line
flip" describes.** Tried, in two forms, and declined in both — the two rounds are
recorded in §2 because the reasoning is the ADR's own subject matter. A
date-*shaped* value is a value an unreviewed commit chooses (`- Date:
1970-01-01`). Binding it to the commit's author date does not fix that, because
`git commit --date=…` and `GIT_AUTHOR_DATE` set the author date; the repository
holds no third source for a ratification date that the committing hand does not
also control. Weighed against one occurrence in 121 ratification commits, the
exclusion is the trade §6 requires. **This declines latitude the ruling granted;
it does not reverse the ruling** — the exempt set is a strict subset of the one
amendment 3 authorised, and the ground for narrowing it is amendment 3's own
principle. Widening back to two lines is a superseding ADR's business under §6,
and would need the third source this one could not find.

## Consequences

**Easier.** A bare ratification flip costs no Codex round: on the measured corpus
that is 48 of 121 ratification commits, about two in five, and the round it saves
is one no reviewer could have used. `CONTRIBUTING.md` → "Finishing an ADR PR"
step 3 stops being a step a lane must be told is normal — the #1242 record shows
lanes treating the post-flip refusal as a bug to debug. And the #1044 class —
shipped ready with `Status` still `Proposed`, twice in two days, caught both times
by a human after the fact — becomes a mechanical refusal naming the file.

**Harder.** There is now a commit shape the repository's own code asserts
something about, and that assertion has to stay true; §2's predicate and §6's
principle exist to bound how much it can ever assert. The exemption is invisible
in the common case and visible only in `ship`'s posted comment (§4), so a merge
reviewer who does not read that comment learns nothing. An author who wants both
a ratification note and the exemption cannot have both, and the corpus's recent
trend is towards the note — so the realised saving will run below the historical
40%. And ADR-0020 §3's acceptance rule now has three amendments layered on it
(ADR-0025, ADR-0027, this one); a fourth would be the point at which restating it
whole in a superseding ADR is cheaper than reading four notes.

**Revisit if** a third instance of #1044's pattern occurs past §5's guard — which
would mean lanes are reaching `ready` without the documented recipe, and the
remedy is the required CI check §5 declines; or if any commit is ever accepted
under §2's predicate that a reviewer would have found something in, which would
mean the predicate is wrong rather than merely narrow.

**Follow-on.** One implementation lane, briefed after this merges, with the
deliverables and the salvage boundary §8 sets.
