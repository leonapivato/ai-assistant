# 165. An ADR is numbered and ratified at merge, and that commit is not reviewable content

- Status: Proposed
- Date: 2026-08-20
- Partially supersedes on ratification: ADR-0015 §5's ADR-number-assignment
  clause ("The operator dispatching an agent assigns its ADR number"); §2 below.
  ADR-0015 §5's other clause — a substantive contract ADR ships as its own PR,
  ratified before the implementation that depends on it — stands untouched.
- Amends on ratification: ADR-0027 §2's acceptance rule, as to which commit's
  content it reads (§4); and ADR-0070 §1's ratifying-edit clause, as to what that
  edit carries (§2). The edits are **not** made by this change; §8 records their
  exact form and why they wait (ADR-0019).
- Directs: `CONTRIBUTING.md`'s ADR-numbering paragraph, its "Finishing an ADR PR"
  sequence and its review-round conditions; `CLAUDE.md`'s golden rule 5; and
  `docs/adr/template.md`'s heading and its displayed placeholders (§§3, 7).
- Refs: #1226 §5, the ruling this records; #751, the replica hazard §4's
  implementation is built against.

## Context

#1226 §5 rules that an ADR's number and its ratification both move to merge time.
This ADR records that ruling, and it is written against two costs the present
arrangement carries.

**The number is allocated at dispatch, and the allocation is a promise about the
future.** ADR-0015 §5 put number assignment with the dispatcher to remove the
race the in-flight ledger failed to arbitrate. What it did not remove is the
*coupling*. A number handed out at dispatch is a claim on `docs/adr/NNNN-…` that
has to hold until the lane merges — across every reordering, every lane that
stops, every batch that is re-planned. `CONTRIBUTING.md` carried the fallback for
when it does not, in the very paragraph this change replaces — the second branch
to merge renumbers, a file rename plus its internal references and its trailers —
and the dispatcher carries the bookkeeping for when it might: a number reserved
for a lane that never ran is a gap, and a gap is a thing
`scripts/project_status.py` reports and a reader has to be told about. The
allocation is only actually needed at one instant — the moment the file lands on
`main` — and it is being made hours or days early, by a person, against a
counter that only `main` knows.

**The ratification flip costs a review round, every time, by construction.**
`CONTRIBUTING.md` → "Finishing an ADR PR" sets the sequence and is right about
each step: the ADR is reviewed while `Proposed`, flipped to `Accepted` only once
the required set is green on one tree, and *then* the required reviews are re-run,
because the flip edits a reviewed byte and `ship`'s unmoved-base path — "(a) —
ADR-0020 §3 exactly as written. The tree is the whole test here." — refuses the
artifact. That document is explicit that the re-run buys **coverage**, which is
mechanical, and that no exemption in it lifts a mechanical requirement. So every
ADR PR in the corpus pays one Codex round to re-read a diff that is one status
line, and two ratified ADRs (ADR-0130 §12, ADR-0136 §7) record having paid it.

The two costs share a shape: a byte that no reviewer can have an opinion about is
being treated as content, and an allocation that only `main` can make is being
made off `main`. #1226 §5 rules that both move to the one place that can settle
them — the merge — and that the second is made cheap by a mechanism rather than
by a judgement, because "this diff is trivial" is exactly the self-assessment
ADR-0020 §3's content anchor exists to stop taking anyone's word for.

## Decision

### 1. An ADR lane's PR is the ADR alone, authored unnumbered

> **Normative.** An ADR lane's PR contains the ADR document and nothing else. The
> file is `docs/adr/<slug>.md` with no number in its name, its H1 is
> `# XXXX. <title>`, every self-reference in it is written `ADR-XXXX`, and its
> `Status` stands `Proposed` throughout the review.

The lane therefore never holds a number, and there is nothing for it to collide
on. What it holds is a slug, which is unique because a branch is.

> **Normative.** The required review set is run against that unnumbered,
> `Proposed` document, and is what decides the ADR — adversarial for most ADRs,
> adversarial *and* architecture for one deciding a contract surface
> (`CONTRIBUTING.md` → "Stop when the required reviews are green"). Nothing about
> which lenses are required, or what a green set means, changes here.

This is the same state `CONTRIBUTING.md` → "Finishing an ADR PR" step 1 already
names as the one in which a finding can still change the decision, and in which
the ADR's own text is corrected rather than annotated (ADR-0095 §7). Removing the
number from the file removes nothing from that state: no finding has ever turned
on which four digits the document was going to get.

### 2. The number is taken at merge, by one mechanical commit

> **Normative.** The number an ADR takes is `max(main) + 1` — one greater than the
> highest number `docs/adr/` carries on `main` — computed at the moment the ADR
> is merged, and never before. It is not a number anyone chooses: a number that
> skips ahead collides with nothing and strands every number it jumped over, so
> it is refused exactly as a duplicate is.

> **Normative.** It is taken by exactly one commit, whose whole content is: the
> file renamed from `docs/adr/<slug>.md` to `docs/adr/NNNN-<slug>.md`; the H1's
> `XXXX` replaced by the number, unpadded; every `ADR-XXXX` replaced by
> `ADR-NNNN`, zero-padded; the header's one `- Status: Proposed` replaced by
> `- Status: Accepted`; and the header's one `- Date:` line replaced by the
> ratification date. **Nothing else.** This is the *ratify commit*.

> **Normative.** The ratify commit is made by whoever merges the PR, immediately
> before merging it and after the branch's final rebase. A lane does not make its
> own.

That last clause is the whole of the race removal, and it is why the commit is
not simply moved to the end of the lane's own work. A number taken while a PR
sits ready is a number taken against a `main` that another lane is about to
advance; a number taken by the merger is serialised behind the merge itself,
which is the only serialisation this repository actually has. It also keeps
ADR-0015 §2's clone-per-agent model intact — the merger is already the only party
holding a view across lanes.

`just adr-ratify` produces the commit. It reads the ADR's *committed* content,
refuses on a dirty tree, on `main` and on a detached `HEAD`, refuses a document
that is not in §1's shape, refuses any number that is not the next one, offers no
way to point itself at a different or a stale base — every such escape is an
escape from the property §4 rests on — and
refuses outright on a branch that does not contain its base's tip — staleness
tested as ancestry, not as a comparison of ADR numbers, because a base advance
that adds no ADR leaves the numbers equal and the branch just as stale, and §2
puts this commit after the final rebase for the whole tree rather than for the
part that decides the number. `--number` states the number the operator expects
and is checked against the computed one; it does not select. And because a ratify
commit that §4's test does not recognise is worse than no exemption at all, it
verifies its own output against that test, restoring the branch — from a failed
write as readily as from a failed check — if anything does not hold.

> **Normative.** The ratify commit's message is a Conventional Commit naming the
> number it took, with a matching `Refs:` trailer. The commits that precede it on
> the branch are not rewritten, so a lane's own commits legitimately carry
> `Refs: ADR-XXXX`; the ADR's number enters the history with the ratify commit.

### 3. `XXXX` is reserved, and a survivor is a hard failure

> **Normative.** In an unnumbered ADR the token `XXXX` is reserved for that ADR's
> own number. An ADR that needs to *display* the placeholder — quoting
> `docs/adr/template.md`, exhibiting ADR-0070 §4's status grammar — writes it some
> other way.

> **Normative.** If any `XXXX` remains after the substitution, ratification fails
> and no commit is made.

The constraint is the same kind ADR-0070 §4 already imposes on a scope text ("a
scope names a clause, not another ADR"), and for the same reason: a
context-sensitive substitution with no reserved token is one a tool cannot get
right, and getting it wrong here produces a document that merges looking ratified
while still carrying a placeholder nobody will ever resolve. The check makes the
constraint mechanical rather than advisory, and it costs an author who does need
to show the form one rephrasing.

**The check catches a leftover `XXXX`, and cannot catch a wrongly-substituted
one**, which is why the constraint is stated as a rule rather than left to the
tool. `ADR-XXXX` written to *display* the form is indistinguishable from
`ADR-XXXX` written as a self-reference, and it is substituted silently. The one
place that hazard was actually stocked is `docs/adr/template.md`, which an author
copies: it illustrated the status grammar with `ADR-XXXX`, so a copy carried a
displayed placeholder into every new ADR.

> **Normative.** `docs/adr/template.md`'s heading becomes `# XXXX. <short title>`,
> and the placeholders it uses to illustrate *other* ADRs' numbers become `NNNN`,
> `AAAA` and `BBBB`. ADR-0070 §4's status grammar is unchanged — only the
> metavariable it is displayed with moves, so that `XXXX` means one thing in an
> ADR file and only that: this ADR's own number.

### 4. The ratify commit is exempt from a fresh review round, mechanically

> **Normative.** Where a PR's `HEAD` is exactly a ratify commit, ADR-0027 §2's
> acceptance rule is computed over its **parent** rather than over `HEAD`. Both
> of §2's paths, and every clause of each, apply unchanged to that endpoint.

This is a **normalisation, not a third acceptance path**, and the distinction is
load-bearing. Nothing about (a)'s whole-tree comparison, (b)'s properness or
patch identity, §3's floor or §4's disclosure is relaxed or widened. What moves is
which commit's content the existing tests read, and it moves by one commit whose
content is fully determined by the commit before it. A base move still costs
exactly what ADR-0027 says it costs, including when it lands in `docs/adr/**`.

> **Normative.** "Exactly a ratify commit" is decided by reconstruction, not by
> pattern-matching the diff: the parent's unnumbered file is put through the same
> transform that *produces* a ratify commit, and the result is compared byte for
> byte against the child's numbered file, with the commit's tree diff required to
> be exactly one delete and one add and the number required to be exactly the
> **parent tree's** maximum plus one. A commit that changed one further byte,
> touched a second path, moved the slug, or took any number but the next one is
> not recognised.

**The allocation rule is tested, not assumed, and testing it is why the parent
tree is the reference.** The recogniser cannot see whatever `main` looked like
when the commit was made, so "max(main) + 1" would be an unfalsifiable claim
about the past; "the parent tree's maximum plus one" is a property the commit
*has*, checkable from the commit alone, and §2's requirement that the ratify
commit be made after the final rebase is what makes the two the same number.

`render_ratified` and `check_commit` in `scripts/adr_ratify.py` are that one
transform and that one test, and `scripts/ship.sh` reaches them by invoking the
script. It is deliberately not a second spelling of the rule inside `ship.sh`:
issue #751 records two distinct ways a hand-built replica of a ship-side rule
returned a confident clear for a case that was not clear, and the lesson taken
there — share the code, do not restate the reasoning — is the one taken here.

> **Normative.** The exemption fails closed. Any condition under which the shape
> cannot be established — no interpreter, no script, a non-zero exit, a commit
> with other than one parent — leaves the acceptance rule computed over `HEAD`,
> and the ratify commit then costs its round like any other commit.

> **Normative.** Where the exemption is granted, the comment `ship` posts
> discloses it: that the tip commit is a ratify commit, which ADR file it
> ratifies, and which parent the published reviews actually cover.

That disclosure is ADR-0027 §4's principle applied to the same kind of gap. The
comment's claim is that a review covers this head; where it covers the head's
parent, a reader comparing the verdicts against the PR's tip must be *told*, not
left to infer it from a SHA that matches nothing they can see.

> **Normative.** The exemption is from the Codex round, never from the ruling.
> The required review set is green on the unnumbered `Proposed` tree before the
> ratify commit is made, and a ratify commit made on a tree that has not earned
> that is a rule broken by the person who made it — nothing in this mechanism
> detects it, and nothing in it licenses it.

### 5. Implementation lanes cite the number from `main`

> **Normative.** An implementation lane takes the number of the ADR it implements
> from `main`, after the ADR's PR has merged. A brief that must name the ADR
> before then names it by slug or by PR number.

This follows from golden rule 5 and ADR-0015 §5's surviving clause without
straining them: nothing may implement against an ADR until it has merged, and
once it has merged its number is a fact on `main` rather than a promise.

### 6. What happens when a finding arrives after the ratify commit

> **Normative.** A finding that arrives once the ratify commit exists is folded by
> **removing that commit**, returning the ADR to §1's unnumbered `Proposed` shape,
> re-entering the review at §1, and ratifying again afterwards — with the number
> recomputed, because `main` may have moved.

This is the return-to-`Proposed` route `CONTRIBUTING.md` → "Finishing an ADR
PR" already carried, in its new shape, and it is available for the same reason:
every step here runs on the open PR, so an unmerged ratify commit has landed
nowhere and binds no reader. Removing it is free of review cost by the content
anchor — the branch is back on a tree a reviewer has already read (ADR-0020 §3,
and `CONTRIBUTING.md`'s "a commit that changes no reviewed byte does not cost a
review round"). After the merge the route is gone, and a change to what the ADR
decided is a new ADR that supersedes it (ADR-0070 §1).

### 7. What `CONTRIBUTING.md` and `CLAUDE.md` say instead

`CONTRIBUTING.md` is ratified by ADR-0003, so an ADR outranks it and may direct
its correction (ADR-0070 §5). Three passages are rewritten to state this decision:

- its **ADR-numbering paragraph** ("ADR numbers are assigned at dispatch"), which
  becomes §2's rule, together with the dispatcher bullet that repeats it;
- **"Finishing an ADR PR"**, whose steps 2 and 3 become the ratify commit and its
  exemption, with their return-to-`Proposed` route kept as §6;
- the **review-round conditions** in "Report the review, then mark it ready",
  which gain the ratify commit alongside the amend/squash/revert cases they
  already list as costing nothing.

`docs/adr/template.md` takes §3's respelling. Three smaller passages are
corrected to agree with all of it and decide nothing on their own: the dispatcher
bullet that repeats the numbering rule, the sentence telling an agent its ADR
number comes from its brief, and the "Trivial ADR edits" paragraph's mention of
the ratification flip, which now names where that flip lives.
`scripts/project_status.py`'s footer line carries the same stale claim in
generated output and is corrected with them.

`CLAUDE.md`'s **golden rule 5** loses "Your ADR number is assigned when the work
is handed to you — don't pick one yourself" and gains §1's unnumbered authoring
and §2's merge-time allocation; its Review section's "changing a reviewed byte
does" gains the one exception this ADR creates.

Nothing else in either document moves. In particular, `CONTRIBUTING.md` → "When
the full gate is owed, and when it is not" is untouched: the ratify commit
touches no file under `src/` or `tests/`, it is pushed after `gh pr ready`, and
so it falls outside both of ADR-0136 §1's anchors and re-opens neither. CI runs
the full gate on that push (ADR-0010) as it does on every other, which is also
where `scripts/check_citations.py` first sees the file — its `_ADR_FILENAME_RE`
requires four leading digits, so an unnumbered ADR is outside the Tier 1 corpus
until the ratify commit puts it in, and the ratify commit is pushed before the
merge rather than with it.

### 8. What ratification does to ADR-0015, ADR-0027 and ADR-0070 — and what it does not do to ADR-0082

ADR-0082 §1 decides whether a record is owed on an earlier ADR, and its test is
ADR-0070 §1's applied to that ADR's *text*: would a reader holding only it now act
differently, or read one of its clauses more widely than it now holds? The test is
applied here clause by clause, in this ADR's text, which is where ADR-0082 §1 says
it is reviewed. Every edit below is made **on ratification**, not by this change,
because writing "amended by ADR-0165" onto a live ADR while ADR-0165 stands
`Proposed` is the state claim ADR-0019 forbids (ADR-0026 §6 and ADR-0027 §7 are
the precedents this follows).

**ADR-0015 §5 — partial supersession.** Its sentence "The operator dispatching an
agent assigns its ADR number, removing the race the in-flight ledger failed to
arbitrate" is not made over-wide by this change; it is **reversed**. A reader
holding only ADR-0015 assigns numbers at dispatch, which is what §2 forbids. Under
ADR-0070 §1 a change to what was decided is a supersession, and it is partial —
§5's contract-ADR sentence, and everything in §§1–4, stand. Its `Status` line
carries the grandfathered `Accepted, partially superseded …` shape, which ADR-0070
§4 declines to retrofit, so the new pair is added in that line's own established
form rather than converting the line to the leading-token one:

`- Status: Accepted, partially superseded by ADR-0020 and ADR-0025, and by
ADR-0165 (§5's ADR-number-assignment clause); Consequences' every-commit gate
clause amended by ADR-0136`

with a dated header note appended after the ADR-0136 one, naming the reversed
sentence and the surviving clause.

**ADR-0027 §2 — amendment.** Its two paths and both their tests stand exactly as
ratified, and §4 above is what *applies* them; what changes is the endpoint they
read. But §2's operative sentence — "`ship` accepts an artifact when **either**
(a) … **or** (b) …" — is read as the complete acceptance rule, and after §4 that
reading is over-wide as a statement of when `ship` refuses. That is ADR-0082 §1's
second limb met, so the record is owed. It is an amendment and not a supersession
because no sentence of §2 becomes false: (a) still refuses on any changed byte in
the tree it is given, (b) is still the moved-base path only, and §2's two
properties of the patch identity are untouched. ADR-0027's `Status` is `Accepted`
with no leading token, so ADR-0082 §2 leaves the qualifier permitted there:

`- Status: Accepted, §2's acceptance rule amended by ADR-0165`

with a dated header note giving §4's rule and its bounds.

**ADR-0070 §1 — amendment, recorded in the note alone.** §1's ratifying-edit
bullet — "**ratifying** an ADR — `Proposed` → `Accepted`" — and its protection of
ratified decision text ("the Context, Decision and Consequences — is never
rewritten") are both, read strictly, unaffected: the ratify commit's substitution
edits text that is not yet ratified, which is the same adjudication ADR-0095 §7
makes for a `Proposed` ADR and which `CONTRIBUTING.md` → "Finishing an ADR PR"
step 1 already relies on. But a reader holding only ADR-0070 reads that bullet as
naming the whole of what a ratifying act does, and after §2 it does more — it
renames the file and substitutes the number in the body. Read that way the clause
is over-wide, which is ADR-0082 §1's second limb again, so the record is owed.
ADR-0070's `Status` carries the leading `Partially superseded by ADR-0127 …`
token, and ADR-0082 §2 is explicit that on such a line **no amendment qualifier is
written**: the record is the appended dated note and that is the whole of it. So
ADR-0070's `Status` line is **not** edited.

**ADR-0082 — no record, and this is a ruling, not an omission.** #1226 §5 names
ADR-0082 alongside ADR-0070 as carrying a numbering line to be amended. It does
not: ADR-0082 decides when a record on an earlier ADR is owed (§1) and where it
goes (§2), and says nothing about ADR numbering, ADR ratification, or review
rounds. Every sentence of it stays true after this change, and §§1 and 2 are what
*decide* the three records above rather than being changed by them. Under
ADR-0082 §1 that makes this a stacked addition as to ADR-0082, recorded here and
nowhere else — and recording one anyway is the error §1 names in its own words:
"a later ADR that calls its change an amendment of ADR-N without a clause of ADR-N
failing §1's test has mis-declared it, and the record is wrong however the
declaration reads."

**ADR-0020 — no record.** Its §3 already carries `§3 amended by ADR-0025 and
ADR-0027`, and ADR-0027 §7 moved the operative acceptance rule into ADR-0027 §2.
A reader following ADR-0020 §3 is sent to ADR-0027 for the live rule and lands on
the amended text. Nothing of ADR-0020's own becomes false or over-wide.

**This ADR is numbered the old way, and does not exercise its own mechanism.** It
was dispatched with the number 0165 under ADR-0015 §5, as ADR-0166 was, and the
two of them are the last numbered that way. §§1–2 bind every ADR
lane dispatched after this one merges. One consequence is worth stating plainly:
because this document was authored numbered, it is free to display `ADR-XXXX`
throughout, which §3 forbids to the documents that come after it.

## Alternatives considered

**Move ratification but keep numbering at dispatch.** This buys the cheaper half
— the exemption — without touching ADR-0015 §5, and it is the smaller change.
Rejected because the two halves are one mechanism: the exemption's safety comes
from the ratify commit's diff being *fully determined by its parent*, and a commit
that only flips a status and a date is a diff so small that recognising it says
almost nothing (the rename is what makes the commit structurally unmistakable,
where a two-line header edit is a shape an ordinary revision can wear by
accident). Keeping the number at dispatch also keeps the
allocation coupled to the plan, which is the cost #1226 §5 names first.

**Relax the tree comparison generally for `docs/adr/**`.** Rejected outright.
ADR-0027 §3 puts `docs/adr/**` in the review floor *because* a reviewer's
standing contracts live there; a rule that ADR changes cost less review is the
exact inversion of the one already ratified.

**Let the exemption be self-attested** — a trailer or a commit-message marker that
`ship` trusts. Rejected: ADR-0020 §3 exists because "the author says this diff is
trivial" is not a claim the record may rest on, and a marker is that claim in a
machine-readable costume. The reconstruction test asks nothing of the author.

**Recognise the shape by pattern-matching the diff** — a rename entry plus an
allow-list of changed lines. Rejected on #751's lesson. A pattern is a *restated*
version of the transform, and the two drift; a reconstruction cannot, because it
calls the producer's own function. The reconstruction is also strictly stronger:
an allow-list has to enumerate what may change, while a rebuild enumerates nothing
and admits only the one output.

**Extend the exemption to cover a rebase and a ratification together as one
step.** Declined, deliberately. It composes already — the normalisation moves the
endpoint, and ADR-0027 §2(b) then judges the base move on its own merits — so
nothing needs building. What is *not* bought back is a base move that lands in
`docs/adr/**`, which is a floor breach and costs its round; on a batch that merges
ADRs, that will be most rebases. The answer is operational rather than
mechanical: make the ratify commit last, after the final rebase, which §2 requires
anyway.

## Consequences

- **A dispatcher stops allocating numbers, and stops tracking them.** A brief
  names a lane's ADR by slug. There is no reserved number to leak when a lane
  stops, no gap to explain, and no renumbering when two lanes are reordered —
  `CONTRIBUTING.md`'s renumbering fallback is deleted rather than kept, because
  the second to merge simply takes the next number.
- **Every ADR PR saves one Codex round**, and the round it saves is the one that
  had the least to find. What it does not save is any round on the decision
  itself: §1 puts the whole required set on the document that decides.
- **Numbers become strictly merge-ordered.** ADR numbers now reflect the order
  ADRs landed rather than the order they were dispatched, which is what ADR-0001's
  sequential numbering meant in the first place and what ADR-0070 §4's transitive
  walk already assumes ("an ADR is only ever superseded by a *later*,
  higher-numbered ADR"). Under dispatch-time assignment that assumption was true
  only by the dispatcher's care.
- **A lane's own commits cite a number that does not exist yet.** `Refs:
  ADR-XXXX` sits in the branch's history and is not rewritten (§2). This is
  visible in `git log` and is the price of not rewriting a reviewed branch's
  commits; the ADR file itself carries the real number from the ratify commit
  onward, and `scripts/check_citations.py` reads files, not commit messages.
- **An unnumbered ADR is outside the Tier 1 citation corpus while it is
  unnumbered**, because `_ADR_FILENAME_RE` in `scripts/check_citations.py`
  requires four leading digits in the filename and `_ADR_FILE_RE` in
  `scripts/project_status.py` requires leading digits at all. Neither errors on
  the file; both skip it. The check does still run before the merge — the ratify
  commit is pushed to the PR, and CI runs the full gate on every push (ADR-0010)
  — so a broken citation in a new ADR fails on the PR, one commit later than it
  used to. Broadening either script to read the unnumbered
  file is not done here; it would mean teaching them a second filename shape for
  a window that lasts one commit.
- **The merge grows a CI wait.** The ratify commit is a push to the PR, so the
  gate runs on it before the merge can happen (ADR-0010, and branch protection's
  `strict`). That is the cost of putting the numbered file in front of the same
  checks as everything else, and it is paid once per ADR, by the merger, on a
  diff of one rename.
- **The merger now writes a commit on the lane's branch.** That is a change to
  what merging involves, and it is why `just adr-ratify` refuses on `main`, on a
  dirty tree and on a document out of shape rather than assuming a careful
  operator. Its self-check against `check_commit` closes the one failure that
  would otherwise be silent and expensive: a commit that exists, looks ratified,
  and costs a round because the exemption does not recognise it.
- **A ratify commit made before the required set is green is not detectable.**
  §4's last clause says so plainly rather than implying a guarantee the mechanism
  does not give. The shape test asks what a commit contains, never what was true
  when it was made — the same limit ADR-0020's content anchor has always had
  ("A pasted review is self-attested where the CI-posted one was not").
- **Revisit if** a lane is ever dispatched programmatically rather than by hand,
  which is already ADR-0015's own revisit trigger and would give the allocation a
  second serialisation point; or if the exemption is observed being granted for a
  commit anyone would want reviewed, which would mean the reconstruction is
  weaker than §4 claims.
