# 90. A number that was never issued is not a missing ADR

- Status: Accepted
- Date: 2026-08-01
- Partially supersedes: ADR-0088 — §6's Tier 1 rule for a decision citation
  naming an absent ADR file, as it applies to a number that lies in a gap below
  the highest issued number. The rest of §6 stands: the tracker half of Tier 1,
  Tier 2, the silence on section numbers, the asymmetric failure handling and the
  input-set rules are untouched, and §3's rule that no code citation may fail is
  not reached. **No code changes with it** and no `core` surface is touched. §2
  is explicit that this decides a rule and does not implement one: the check that
  `scripts/check_citations.py` runs today is unchanged by this ADR, and the lane
  that changes it is the lane that deletes the pin.

## Context

### Tier 1 fails a correct document on `main` today

ADR-0088 §6 puts two things in the tier that may fail a build. One of them is
"a decision citation naming an **ADR file that does not exist**". Running the
checker that #598 shipped over `docs/adr/**` at `origin/main` produces exactly
one Tier 1 finding, and it is against a sentence that is true. The ADR is
ADR-0067, and the sentence is this one:

```text
Since that commit, measured at `e6558f4` — the state of `origin/main` this
decision was written against — the trunk has taken 262 commits and ratified
31 further ADRs, ADR-0036 through ADR-0066, no ADR-0035 having been issued,
over four days.
```

The token is written in ADR-0088 §1(a)'s canonical form, in running prose,
outside any fence, and the file it names is absent because **the number 0035 was
never issued**. Nothing about the sentence is wrong. It is the natural way to
write the fact it records, and the fact it records is what makes the count of
31 correct.

So §6 as ratified fails a correct document. §6 itself names that as the one
outcome the whole tier design exists to avoid: "**A miss is benign; a false
report is not** … A confident wrong finding costs the reader's trust in every
other finding".

### The premise Tier 1 rests on covers deletion, not issuance

§6 justifies putting this check in the failing tier in one clause: "These have no
legitimate non-resolving case at all: ADRs are append-only so a file is never
deleted, and an issue number once assigned stays assigned."

Append-only (ADR-0001) guarantees that a file, once written, stays. It says
nothing whatever about a number that was assigned and then never written. The
premise is true and the conclusion drawn from it is not, because the conclusion
quietly requires a second premise — that every cited number was *issued* — which
no rule in the corpus supplies. ADR-0015 §5 assigns a number at dispatch; a lane
that is never dispatched, or is dispatched and abandoned, leaves a number
assigned and unwritten. That is what happened to 0035.

This is the same shape ADR-0088 §3 already found on the other side of the corpus:
"an append-only corpus correctly cites what is not in the tree". §3 drew the
conclusion for code citations and made all of them non-failing. The decision
citation kind reaches the identical shape by a different route — a number that
never existed rather than a symbol that no longer does — and §6 did not carry §3's
reasoning across.

### The corpus has exactly one gap, and it is measurable

Every number from 1 to the highest present in `docs/adr/` is present except 0035.
That is not an assumption about the corpus's tidiness: it is read off the
filenames, and the set it produces is what §1 below keys the rule to. One gap, one
citation into it, and a rule that is decided by arithmetic over a directory
listing rather than by reading any prose.

### Three sentences of ADR-0088 are false, and one is a mislabelled measurement

The defect is not confined to §6's rule. ADR-0088 states the passing corpus as a
fact three times, and each statement is false against the tree it was measured on
and against `origin/main` today:

- Context: "0035 is absent, and nothing cites it." ADR-0067 cites it.
- §6: "The corpus's 3,387 decision citations pass today, so this is a regression
  guard rather than a backlog." One does not pass.
- Consequences: "It passes today, so it guards against regression rather than
  presenting a backlog", and "3,387 decision citations, zero dangling files, zero
  real section misses."

The figure carries a separate, smaller error worth recording because it changes
what the sentence claims. **3,387 is Context's count of `ADR-NNNN §K`
references** — "There are **3,387** `ADR-NNNN §K` references" — and §6 and
Consequences reuse it as the count of *decision citations*. Those are different
populations: §1(a) makes the section reference optional, so the decision-citation
population is every `ADR-NNNN` token, with or without a `§K`. Measured at
`123bdbc` — the state of `origin/main` this decision was written against —
`scripts/check_citations.py` reports **5,885** decision citations, and the same
token scan finds 3,515 of them carrying a `§K`. So §6's denominator is roughly
three-fifths of the set its own §1 defines.

Context's neighbouring sentence — "**Cross-ADR section references are in
excellent health.** There are **3,387** `ADR-NNNN §K` references. **None** points
at a missing ADR file" — is **not** among the false ones, and the distinction is
the whole point. ADR-0067 writes the number bare, with no `§K`, so it is outside
that sentence's population. The measurement was right about what it measured; the
error entered when the figure was carried into a wider claim.

Under ADR-0070 §1 these are stale phrases in ratified text, so they are recorded
as an appended dated note on ADR-0088 and none of them is rewritten. §4 below
classifies each.

### What #598 shipped, and why it cannot simply be deleted

`tests/scripts/test_adr_citations_corpus.py` pins the Tier 1 finding set to the
single entry `main` carries. That keeps the gate green on a corpus that lane's
fence excluded, while leaving the check live: a *new* dangling citation changes
the set and fails, and so does correcting the corpus. #603 records the
arrangement and names deleting the pin as what closes it.

The pin cannot be deleted here, and the reason is mechanical rather than
procedural. The exemption §1 decides has to be implemented in
`scripts/check_citations.py` before the pin is wrong: until then the checker
faithfully implements §6 as ratified and reports the ADR-0067 occurrence, so a
test asserting an empty Tier 1 set fails on it. §2 states the sequencing rather
than leaving the next lane to discover it from a red gate.

## Decision

### 1. A decision citation into a gap below the highest issued number passes silently

> **Normative.** Under ADR-0088 §6, Tier 1 passes a decision citation silently
> when its `NNNN` is absent from the issued set and is less than that set's
> maximum. The issued set is every `NNNN` for which a file `docs/adr/NNNN-*.md`
> exists, read from the tree and from nothing else. Such a citation is neither
> failed nor reported. Every other decision citation that does not resolve under
> ADR-0088 §2(a) still fails Tier 1, including one whose `NNNN` is greater than
> that maximum.

**This is §6's own boundary applied to a case §6 misclassified.** §6 sets the
tier boundary at "whether a legitimate non-resolving case exists", and a citation
to a never-issued number is exactly such a case — legitimate, correct, and
non-resolving. What keeps it out of Tier 2 as well is that the tier boundary has a
second half: Tier 2 holds cases with "a legitimate class no mechanical test
separates from a defect". Here a mechanical test does separate them. Below the
maximum and absent is a gap; at or above it is a number nobody has issued yet.
Nothing about that reads prose or infers intent, which is what §6 requires of
anything the checker does.

**The residual is where Tier 1 keeps its value, and it is most of it.** The
overwhelmingly likely dangling citation is a typo or a stale forward reference,
and both land above the issued maximum far more often than inside a one-number
gap. A citation to a number that has not been assigned yet — the ADR someone
expects to write, or a mistyped digit that overshoots — still fails, which is the
regression guard §6 wanted and the thing #588 asked for.

**The width of the exemption is the width of the gap set, and today that is one
number.** The rule is self-maintaining in the sense that it needs no list and no
allowlist file — ADR-0088 §9 declined a hand-maintained allowlist on the ground
that it "decays exactly when it matters", and a set derived from the tree cannot
decay — but it is also self-*widening*: every number skipped in future adds a
number that can be cited silently. §3 records that this ADR does not legislate
number assignment, and Consequences prices the cost.

### 2. The pin is deleted by the change that implements §1, and by no earlier one

> **Normative.** The pinned Tier 1 set and its tracking-issue constant in
> `tests/scripts/test_adr_citations_corpus.py` are deleted by the same change
> that implements §1 in `scripts/check_citations.py`, and by no earlier change.

**The two edits are each other's precondition, in both directions.** Delete the
pin first and the test asserts an empty Tier 1 set against a checker that still
reports the ADR-0067 occurrence. Implement §1 first and the test asserts one
finding against a checker that now reports none. Either order alone is a red
gate, which is the gate working — the pin was built to fail on exactly this
change (#603) — but a lane discovering that by running it has already split a
change that was never separable. **#610 carries the work** and names both files;
#603, which raised the question this ADR answers, is closed by it.

**This is not golden rule 5 and does not claim to be.** ADR-0015 §5 holds a
*contract* ADR back from its implementation, and this ADR decides no Protocol and
no `core` type, so nothing here is a contract-surface change and the sequencing
rule does not reach it. §2 is a narrower and more ordinary thing: two files that
have to move together.

### 3. What this does not decide

- **How ADR numbers are assigned, or whether a gap may be created.** ADR-0015 §5
  owns assignment. §1 makes a gap cheap to cite correctly; it does not make one
  cheap to create, and nothing here licenses skipping a number. If gaps ever
  accumulate enough that the silent-pass window stops being negligible, that is
  the ADR to write, and Consequences names the signal.
- **Anything else in ADR-0088 §6.** The tracker half of Tier 1 is untouched — an
  issue number, unlike an ADR number, is assigned by GitHub at creation and
  cannot be reserved and skipped, so §6's second premise holds for it exactly as
  written. Tier 2, the section-reference silence, the asymmetric failure
  handling and the input-set rules all stand as ratified.
- **Where the check runs.** §6 left that open and `tests/scripts/test_adr_citations_corpus.py`
  answered it for Tier 1; neither is reopened here.
- **What `CONTRIBUTING.md` says about the pin.** Its "Cite in form, and mark what
  binds" section describes the pinned set, and that description stops being
  accurate when §2's change lands. Correcting it belongs to that lane and is
  named in #610; ADR-0088 §8 is the precedent for an ADR directing a
  `CONTRIBUTING.md` correction it does not write.

### 4. Explicitly declined

- **Rewording ADR-0067 so the token is fenced or the prefix dropped.** This is
  #603's option 2 and it is the cheapest edit available, which is what makes it
  worth refusing explicitly. ADR-0070 §1 already forbids it: ratified text — "the
  Context, Decision and Consequences" — is never rewritten, and the sentence sits
  in ADR-0067's Context. The reasoning behind that rule is #71's, restated by ADR-0070 §4
  and applied by ADR-0088 §5 three days ago: "converting a merged, ratified
  decision to satisfy a rule adopted after it is the append-only violation the
  rule exists to prevent, pointed backwards." So this is not marked as a refusal
  — a later lane could not do it anyway — but it is named, because it is the
  option a reader reaches for first.
- **An allowlist of known-absent ADR numbers.** Declined by ADR-0088 §9's own
  reasoning about a hand-maintained file that decays, and unnecessary: §1's set
  is derived from the tree, so it is correct by construction and has nothing to
  maintain.
- **Moving the case to Tier 2 instead of passing it silently.** Tier 2 is for
  cases "no mechanical test separates from a defect", and §1 gives one that does.
  Reporting a correct citation forever, on every run, is a smaller version of the
  same trust cost §6's asymmetry rule prices — and §6 is explicit that a rule
  which both reports and passes the same input "is not implementable".
- **Widening the exemption to any absent number.** That is Tier 1's decision
  citation half deleted rather than corrected, and it gives up the one thing the
  tier buys: a typo or a stale forward reference above the issued range still
  fails, and that is the common case.
- **Correcting §6's `3,387` figure in place.** It is a measurement inside ratified
  Context and Decision text, and ADR-0070 §1 does not permit the rewrite. The
  correct figure and the mislabelling are recorded in this ADR's Context and in
  ADR-0088's dated note, which is the append-only form of the same correction.

### 5. This ADR classified under ADR-0070 §1 and ADR-0082 §1, edit by edit

- **ADR-0088 §6 — a partial supersession, and the `Status` record is owed.**
  §6 *decided* that a decision citation naming an absent ADR file fails Tier 1.
  §1 above decides that a subset of those citations does not. A checker built on
  §6 and a checker built on §1 behave differently on the same input, and a reader
  holding only ADR-0088 would act differently after this change than before it —
  which is ADR-0070 §1's test for a decision change, met. ADR-0082 §1's dated note
  of 2026-07-31 states the same conclusion from the other side and settles the
  case that might otherwise look like an amendment: "a misstated fact whose
  correction *reverses a decision the ADR made* … is a supersession under
  ADR-0070 §1 and it takes a new ADR, whatever bucket the defect sits in."
  ADR-0088's `Status` takes the leading `Partially superseded by` token and the
  scope names the clause, carrying no `ADR-NNNN` (ADR-0070 §4).
- **ADR-0088's three false sentences — amendments, recorded in the dated note
  only.** Each is a stale phrase in ratified text under ADR-0070 §1's first
  bucket, as ADR-0082 §1's note reads that bucket. None of them decided anything:
  a reader acting on ADR-0088 acts on §6's rule, not on Context's count of what
  passes. Under ADR-0082 §2 the line now carries a leading supersession token, so
  no amendment qualifier is written on it and the record is the note alone. The
  ratified sentences are not rewritten.
- **The record lands atomically with this ADR.** ADR-0070's own ratifying commit
  did the same — its file plus ADR-0001's status, ADR-0004's note,
  `CONTRIBUTING.md` and the template in one commit — and ADR-0082 §7 relies on the
  shape: "the hazard §1 names is a `Status` line pointing at nothing, and an
  atomic pair makes that unreachable." ADR-0088 §9 declined to *require* atomicity
  and left it available. It is taken here because the whole subject of this ADR is
  a false sentence sitting in ratified text, and splitting the change would open a
  window in which ADR-0088 asserts a passing corpus while the ADR refuting it sits
  beside it in the same directory.
- **ADR-0067 — nothing owed.** Its sentence is correct and unchanged. Nothing in
  it becomes false or over-wide; the rule that was about to fail it moved.
- **ADR-0070, ADR-0082 — nothing owed.** Both are applied here, not narrowed:
  §1's amend-versus-supersede test and §1/§2's record placement are used exactly
  as ratified. Under ADR-0082 §1 this ADR's own additions are **stacked
  additions** on them, recorded here and nowhere else.
- **ADR-0015, ADR-0027 — nothing owed.** Neither the contract-ADR sequencing nor
  the review floor is touched. `docs/adr/**` remains inside ADR-0027 §3's floor
  and this ADR does not ask to change that.
- **ADR-0089 — nothing owed, and this is the first ADR authored under it.** §1
  and §2 above are marked in §2's form; the marked clauses are the whole of what
  this ADR obligates (§3), and the argument around them is evidence of meaning
  rather than a source of obligation. Nothing is marked on any ratified ADR: the
  dated note appended to ADR-0088 carries no mark, as §5's second clause requires.
- **This ADR's `Status`.** It touches no Protocol and no `core` type and decides
  no contract surface, so **adversarial is the required set** — the reading
  ADR-0082 §5 and ADR-0088 §8 each recorded for themselves. ADR-0015 §5's
  ratify-after-review sequencing is scoped to a substantive contract ADR and does
  not reach this one, so it is ratified before review rather than after, which is
  also what lets the `Status` record on ADR-0088 point at a live decision from the
  first commit.

## Consequences

**Easier.**

- **Tier 1 stops being wrong about the corpus it guards.** The gate can run
  ADR-0088 §6's failing tier over `docs/adr/**` with no pinned exception and no
  standing false finding, which is what makes the check something a lane trusts
  rather than something a lane routes around.
- **A correct sentence about a number that was never issued stays writable.**
  ADR-0067's is the only one today; there is no reason it is the last. Under §1 a
  future ADR can write the same fact in the same natural form without fencing it
  or dropping the prefix.
- **The exemption needs no maintenance.** No list, no file, no annotation: the
  issued set is a directory listing and the gap set falls out of it. ADR-0088 §9's
  objection to an allowlist — that it decays exactly when it matters — does not
  apply to a set that is recomputed on every run.
- **The next lane's change is fully specified.** §2 names both files and says
  they move together, so the work is a checker predicate and a deleted pin rather
  than a diagnosis.

**Harder.**

- **A typo that lands inside the gap passes silently, forever.** Someone who
  means 0034 and writes 0035 gets no finding. That is one number wide today and
  it is the price of the rule; it is also the reason §1 keeps every number above
  the issued maximum failing, since that is where a typo more often lands.
- **Every future gap widens the silent window by one number.** The rule scales
  with the corpus's tidiness rather than bounding it, and §3 deliberately declines
  to legislate assignment. **Revisit this ADR** if the gap set stops being a
  handful of numbers — that is the signal that the exemption has outgrown the
  case it was written for, and the point at which a bounded form (a gap set fixed
  as of a date, say) starts being worth its cost.
- **ADR-0088 now has to be read with its note.** Three of its sentences state a
  passing corpus and stay in the file, because ratified text is not rewritten.
  The dated note carries the correction and the `Status` line carries the
  supersession, which is the append-only shape working as designed — but a reader
  who reads §6 and stops has read something false.
- **One more ADR sits between a reader and what Tier 1 actually does.** §6 is now
  read through §1 here, the way ADR-0070 §4 is read through ADR-0082 §2. That is
  the corpus's normal cost for a correction and it is worth naming.
