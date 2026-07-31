# 82. Recording an amendment on an earlier ADR's status line: when, and where it goes

- Status: Proposed
- Date: 2026-07-30
- **This ADR supersedes nothing.** It decides a question ADR-0070 left open —
  ADR-0070 §4 says what an amendment qualifier *means to a consumer* on a line
  that already carries one, and never says when one is written or where it goes
  — and it corrects two `Status` lines under ADR-0070 §1's third permitted header
  edit. §5 applies §1's test to every edit this change makes and records why each
  is an amendment. **No code changes with it**, and no `core` surface is touched:
  the sole `Status` consumer, `scripts/project_status.py`, only *displays* the
  field (ADR-0070 §4), so nothing here is behavioural.

## Context

Two issues are the same governance question seen from two sides, and deciding
them apart risks a second contradiction of the kind that produced them.

### #477 — two ratified ADRs give opposite instructions about one field

**ADR-0080 §8 removed an amendment qualifier from ADR-0045's `Status`.** Giving
ADR-0045 the leading-token partial-supersession form ADR-0070 §4 requires, it
replaced the whole value `Accepted, §10's #248 conclusion narrowed by ADR-0046`
and argued nothing was lost, "since it is an *amendment*, which §4 says 'is not a
status token and never bears on this read,' and it is recorded in full in
ADR-0045's own `Amended: 2026-07-23 by ADR-0046` header note directly below."

**ADR-0078 §10 required adding one to the same line.** Its ratification list
instructs `Status` on ADR-0045 "qualified with '§5 clause 1 amended by
ADR-0078'", and the same for ADR-0050 and ADR-0028. Applied a day later, that
produced the two values `main` carries now:

```text
- Status: Partially superseded by ADR-0080 (…); §5 clause 1 amended by ADR-0078
- Status: Partially superseded by ADR-0079 (…); §1's `USER_ASSERTED` hold-out amended by ADR-0078
```

and, on ADR-0045 and ADR-0050 alike, a dated note arguing the opposite of
ADR-0080 §8 in as many words: "**The Status line accumulates; it does not
replace.**"

Both are ratified, a day apart, about the same field of the same file.

**What actually breaks is narrower than it looks.** ADR-0070 §4 states an
extraction invariant — "**a scope names a clause, not another ADR**: it carries
no `ADR-NNNN` token, so every `ADR-NNNN` after the leading `Partially superseded
by` is a target." The authoring constraint proper is satisfied on both lines: the
`(<scope>)` parentheses carry no ADR token. What fails is the *consequence*,
because a construct §4 did not contemplate — a `;`-joined qualifier after the
pairs — puts an `ADR-NNNN` after the leading token that is not a target. A
consumer built on §4's ratified sentence reads ADR-0078 as a partial-supersession
target of ADR-0045 and of ADR-0050. It is neither; it amends.

### #479 — nothing says when the record is written at all

`main` treats the same shape two ways:

- **ADR-0040, ADR-0045 and ADR-0078** each added to ADR-0028 §8's conformance
  list, and each is recorded on ADR-0028's `Status`.
- **ADR-0077 §5/§9.1** and **ADR-0079 §3/§4** each added a `MemoryWriter.ingest`
  obligation *and* its conformance clause, and neither is recorded there.

ADR-0081 §5 names the distinction descriptively — ADR-0040, ADR-0045 and
ADR-0078 "each changed what §8 *said*", while ADR-0077 §9.1 and ADR-0079 §3 did
not — and then says, correctly, that "the boundary between those two treatments
is not itself written down anywhere", parking it because "settling it is an
ADR-governance decision and not a memory one". This ADR is that decision.

The cost of leaving it unwritten is on the record: PR #478 spent rounds 5, 6 and
7 with reviewers demanding, in opposite directions, that ADR-0077 be given a
supersession pointer, then that its amendment record be removed entirely, then
approving the tree unchanged — a deadlock on a rule that does not exist.

### What the corpus already decides, read as evidence

Every `Status` line in `docs/adr/` was surveyed for this decision, and three
facts fall out.

**The affected set is exactly two lines.** Six ADRs carry the leading-token form
(ADR-0001, ADR-0005, ADR-0045, ADR-0047, ADR-0050, ADR-0074). Only ADR-0045 and
ADR-0050 carry an amendment qualifier beside it.

**The qualifier on a plain `Accepted` line is the established, working practice —
about sixteen lines of it**, including ADR-0007, ADR-0008, ADR-0020, ADR-0022,
ADR-0023, ADR-0025, ADR-0026, ADR-0028, ADR-0029, ADR-0032, ADR-0038, ADR-0040,
ADR-0061, ADR-0065 and ADR-0077. Any rule that pushed amendments off `Status`
altogether would delete sixteen live pointers to fix two.

**The post-ADR-0070 precedent does not run one way.** ADR-0065's `§3 amended
2026-07-25 by ADR-0069` predates ADR-0070 (2026-07-26) and stands under §4's
"Existing status lines are not retrofitted", and §4's legacy-qualifier consumer
rule is scoped in terms to "A **pre-ADR-0070** line". But ADR-0080 §8 is not
therefore the only *post*-ADR-0070 precedent: ADR-0078 §10 added `and ADR-0078`
to ADR-0028's qualifier, and ADR-0081 §5 added `§5's check-not-a-guarantee clause
amended by ADR-0081` to ADR-0077's — both ratified, both after ADR-0070, and both
on a plain `Accepted` line. ADR-0081 §5 says why that is not the contradiction
#477 records: "ADR-0077's `Status` is a plain `Accepted` … No leading
partial-supersession token is present or added, so the coexistence question #477
records … does not arise on this line."

So the corpus's two treatments are not in conflict *except* on the two
leading-token lines. That is the whole of #477, and it is what makes a narrow
answer possible.

## Decision

### 1. The record is owed when the later ADR declares an amendment — and not otherwise

**A later ADR's change is recorded on an earlier ADR's `Status` line exactly
when the later ADR declares, in its own text, that it amends a named clause of
that earlier ADR.** Adding an obligation that contradicts no sentence the earlier
ADR wrote is a **stacked addition**: it is recorded in the ADR that makes it, and
nowhere else.

**The classification test is ADR-0070 §1's, unchanged, applied to the earlier
ADR's *text*.** Would a reader holding only the earlier ADR now act differently,
or read one of its clauses more widely than it now holds? If yes, the later ADR
amends it (or supersedes it — §1 decides which, and this ADR does not touch that
line). If no — the earlier ADR's sentences all stay true, merely joined by
another obligation stated elsewhere — nothing is owed on its `Status`.

**The judgement belongs to the later ADR's author, and is made in the later
ADR's text.** This is the operative half. A reviewer reads the declaration where
the author made it and checks it against §1's test on the quoted clause; a
reviewer may not demand a `Status` record on ADR-N that the ADR under review has
not declared, nor demand the removal of one it has. That is what PR #478's
deadlock was: two rounds of book-keeping demands in opposite directions against
an ADR that had already declared exactly one amendment and argued it clause by
clause (ADR-0081 §5).

**This classifies `main` as it stands, with nothing to retrofit.** ADR-0040
amended ADR-0028 §8 — §8's ratified sentence excluding "the fold's own rule" from
the suite became false, and ADR-0028 §8 carries the in-text amendment note saying
so. ADR-0045 and ADR-0078 each declared theirs (ADR-0078 §10 by name). ADR-0077
§9 declared the opposite about its own addition — "a **third** obligation on that
method, **stacked** on the two ADR-0079 §4 landed … and conflicting with neither"
— and made no record, and ADR-0079 §3 likewise. Both treatments were right, for
the reason now written down.

**A self-amendment names no ADR and is recorded as a dated note only.** Where an
ADR is reconciled with its own text or with a fact that postdates it, and no
other ADR is the cause, ADR-0070 §1's appended dated note is the whole record;
no `Status` edit is owed. ADR-0065's "§4 amended 2026-07-25 (its `ModelProvider`
row was false)" is the pre-ADR-0070 shape of this, grandfathered where it stands
and not the going-forward form.

**Nothing here bears on liveness.** ADR-0070 §4 is unchanged on that: an
amendment "is not a status token" — it is not one of §4's four canonical tokens
and never changes the live/superseded read — and a qualifier that names a later
ADR is "not a reliable liveness signal", so a consumer resolves it against the
ADR it names. §4 scopes that consumer rule to a pre-ADR-0070 line because those
were the only lines carrying qualifiers when it was written; two ratified ADRs
have since written more (ADR-0078 §10, ADR-0081 §5). This ADR records that the
same consumer rule governs a post-ADR-0070 qualifier, which supplies an
instruction where §4 gave none rather than replacing one it gave — a stacked
addition to §4 under §1's test, which is why §5 records it here and not on
ADR-0070's `Status`.

### 2. On a leading-token line the record lives in the dated note, not on `Status`

**Where an ADR's `Status` carries the leading `Partially superseded by` token, no
amendment qualifier is written on that line.** The amendment is recorded in the
appended dated note ADR-0070 §1 already requires for it. On a line with no
leading token — `Accepted`, or a grandfathered `Accepted, partially superseded
…` — the qualifier stays permitted and accumulates in the established shape
(`Accepted, §8 amended by ADR-0040, ADR-0045 and ADR-0078`).

**And when a line takes the leading token, any qualifier already on it moves to
the dated note in the same change.** That is ADR-0080 §8's operation, generalised
from the case it performed: ADR-0045's `narrowed by ADR-0046` came off the line
and the record stayed whole in the `Amended: 2026-07-23 by ADR-0046` note
directly below. Nothing is lost by the move, because §1 requires an amendment to
carry a dated note anyway, so the record exists before the line is touched; where
a pre-ADR-0070 line recorded only on `Status`, the move writes the note carrying
the same substance rather than dropping it.

**This is #477's option 2, and the reasons are these.**

- **It leaves ADR-0070 §4's ratified invariant standing verbatim.** "Every
  `ADR-NNNN` after the leading `Partially superseded by` is a target" is true
  again the moment the two lines are corrected. Option 1 — restating the
  invariant as "every `ADR-NNNN` in a `(<scope>)`-bearing pair after the leading
  token is a target" — would change what a consumer built on §4 extracts, which
  is a change to what §4 decided under §1's own test, so it would require
  *partially superseding ADR-0070 §4*. That is a heavy instrument for two lines,
  and this ADR would then be the third ratified statement in four days about the
  same field.
- **Option 1 would make the scope parenthesis a parsing grammar, which §4
  refused.** §4 is explicit that "the `(<scope>)` text and the `and` joining are
  a **human-reading convention, not a parsing grammar**: no consumer segments
  scope text or binds a scope to an ADR by delimiter." Extracting targets by
  whether an `ADR-NNNN` is followed by a parenthesis is exactly that binding. The
  minimal machine-legible surface §4 kept deliberately is worth more than two
  qualifiers.
- **The asymmetry with a plain `Accepted` line is principled, not arbitrary.**
  The extraction invariant exists only on a line that carries the leading token;
  where there is none, no consumer is reading trailing `ADR-NNNN` references as
  supersession targets, and §4's consumer rule already says what to do with the
  qualifier. The harm is specific to one shape, so the rule is too. ADR-0081 §5
  drew this same line for ADR-0077 before the question was settled.
- **The `Status` field loses nothing it is for.** Under §4 the field's
  machine-legible job is the supersession state; an amendment "never bears on
  this read". The reader who needs the amendment is reading the ADR, and the
  dated note is on the same screen.

### 3. The two lines on `main` are corrected, not grandfathered

**ADR-0045 and ADR-0050 lose their trailing amendment qualifier.** The values
become `Partially superseded by ADR-0080 (§4's window-close instruction for a
target carrying a producer-set bounded window)` and `Partially superseded by
ADR-0079 (§1's over-limit surplus clause)`. Each file gains a dated note
recording the move and pointing at the ADR-0078 note directly below it, which is
untouched and carries the amendment in full — so the change is legible as a
re-rendering rather than a deletion, the way ADR-0080 §8 made its own legible.

**Why corrected and not grandfathered.** ADR-0070 §4's non-retrofit rule and
#71's reasoning behind it are about lines written *before* the rule they would be
judged by: "converting a merged, ratified decision to satisfy a rule adopted
after it is the append-only violation the rule exists to prevent, pointed
backwards." These two lines were written after ADR-0070, under a reading of it
that §4's own invariant does not support, and the rule they breach is ADR-0070's
own. Grandfathering them would also not settle #477: a consumer would still meet
the shape, so §4's consumer rule would have to be widened to cover it — which is
the change to §4 that option 2 exists to avoid. Correcting the corpus to the
ratified rule is smaller than bending the ratified rule to the corpus.

**Everything else stands.** ADR-0028's and ADR-0077's qualifiers are correct
under §1 and §2 and are not touched. The pre-ADR-0070 lines — ADR-0038,
ADR-0040, ADR-0065 and the rest of the sixteen — are grandfathered exactly as §4
already grandfathers them, and this ADR adds no retrofit of its own. Under §1
nothing on ADR-0028 changes for ADR-0077 or ADR-0079 either: their silence was
right.

### 4. What ADR-0078 §10 gets, and why this is not a supersession of it

ADR-0078 §10's instruction for ADR-0045 and ADR-0050 is undone as *rendering* and
kept as *substance*. Applying ADR-0070 §1's test: §10 is a ratification checklist
— "What ratification edits" — and it borrowed its form rather than deciding one,
saying so in its opening line ("Recorded in the form ADR-0028 §6 applied"). The
form it borrowed is ADR-0070 §4's to set. What §10 *required* is that the
narrowing of ADR-0045 §5 clause 1 and of ADR-0050 §1's hold-out be recorded on
those files with no ratified text rewritten; that requirement is met in full,
before and after, by the dated notes it also required and which are untouched. No
reader acting on ADR-0078 — on the deferral queue, the confirmation gate, the
`_refuse_unsafe_fold` narrowing — acts differently. So this is an amendment, not
a supersession, and ADR-0078's `Status` is not qualified: under §1 the record is
owed only where the earlier ADR's own text would now mislead, and §10's
instructions are spent, not live.

**A dated note is added to ADR-0078 all the same**, because a reader who opens
§10 and then opens ADR-0045 will find a line §10 does not describe, and the note
is where that reader is. A note is a permitted header edit under ADR-0070 §1
independently of whether a `Status` record is owed; the two are different
instruments and this ADR uses only the one the reader needs.

**And the two 2026-07-29 notes are not rewritten.** Each contains a paragraph
headed "**The Status line accumulates; it does not replace.**", which this
decision makes false about the rendering. ADR-0070 §1 is append-only in
mechanism, so the paragraphs stand and the new dated note above them records that
their rendering claim is settled the other way by this ADR, and that the
amendment substance they carry is untouched. Rewriting them would be the
violation this ADR is about.

### 5. This ADR classified under its own rule, edit by edit

- **ADR-0045, ADR-0050 — `Status` edited.** ADR-0070 §1's third permitted header
  edit, "correcting a Status line to match what actually landed", read to its
  purpose: the line is made accurate about what the ADR's supersession state is,
  and it changes no decision because the amendment it drops is recorded whole
  four lines below. Not a supersession of either ADR — nothing they decided
  moves.
- **ADR-0045, ADR-0050, ADR-0078 — dated notes appended.** ADR-0070 §1's fourth
  permitted header edit. No ratified text is rewritten anywhere in this change.
- **ADR-0070 — nothing.** §1 and §4 are unchanged, and §1's own test says why:
  §1 stands whole, and §2 here restores §4's invariant rather than restating it.
  §1's rule 1 addition to §4's consumer rule is a stacked addition — §4 gave a
  post-ADR-0070 line no instruction, so no sentence of §4 becomes false — and
  under this ADR's own rule 1 a stacked addition is recorded in the ADR that
  makes it. It is recorded here.
- **ADR-0028, ADR-0077 — nothing.** Correct as they stand under §1 and §2.
- **This ADR's `Status`.** It ships `Proposed` and is reviewed while `Proposed`
  so a finding can still change the decision, then flipped to `Accepted` before
  merge (`CONTRIBUTING.md`, "Contract ADRs land before their implementation";
  ADR-0015 §5). It touches no Protocol and no `core` type, so the adversarial
  review is the required set.

### 6. Explicitly declined

- **A mechanical cross-check** — #479's third question, an assertion in
  `scripts/project_status.py` that an ADR claiming to amend ADR-N is named on
  ADR-N's `Status`. Declined on three grounds. It would be **wrong** under §1:
  the check's premise is that every declared amendment is recorded, and §1's
  answer is that a stacked addition is deliberately not; it would fire on every
  correct silence. It would give this decision behavioural impact it does not
  have — the field is displayed and classifies nothing (ADR-0070 §4) — and the
  rule's failure mode is a reader misreading a record, which a script does not
  catch. And `project_status.py` reads only the first physical line of a wrapped
  `Status` field (#404), so any check built on it today would be built on a
  truncated read. If a liveness-classifying consumer is ever added, ADR-0070 §4
  already binds it and #404 is the prerequisite.
- **Re-adjudicating a ratified classification.** #479 asks whether ADR-0078
  recording an *exception to a ratified refusal* as `amended by` is arguably a
  decision change under ADR-0070 §1. This ADR does not reopen it. ADR-0081 §5
  argued the point on the merits and is ratified, ADR-0045's own note argues that
  clause 1's "surviving justification is not weakened but honoured", and §4's
  non-retrofit principle points the same way. Reclassifying a ratified amendment
  as a supersession is a decision change and needs its own ADR making that case
  on the clause, not a book-keeping rule making it wholesale.
- **A form for the amendment note.** §1 requires a dated note and §2 says the
  leading-token line's record lives there; neither prescribes its wording,
  headings or length. The corpus's notes vary from one line to several
  paragraphs, appropriately, and a template would be a convention with no failure
  behind it.

### 7. What this ADR does not decide

- **The amend-versus-supersede line itself.** ADR-0070 §1 owns it, unchanged.
  This ADR decides only where the *record* goes once §1 has classified the
  change.
- **#404 — `project_status.py` stops at the first physical line of a wrapped
  `Status` field.** Untouched and still open; §6 names it as the prerequisite for
  any mechanical check. Correcting the two lines makes them shorter, which
  reduces the wrapped population by two but does not close the issue.
- **#458 — the recurring misreading of ADR-0070 §1's "a supersession that has
  landed" clause.** Not a governance gap but a reviewer failure mode, so this ADR
  states the condition rather than re-deciding it: §1's condition is that the
  superseding ADR **exists**, not that it is ratified — the hazard §1 names is a
  `Status` line pointing at nothing, and an atomic pair makes that unreachable.
  That is §1's own wording and ADR-0081 §5's reading of it, restated here because
  #479 asks for it and because it recurred on PR #478.
- **Whether an ADR may carry more than one leading-token pair alongside an
  amendment.** It cannot, by §2, and no such line exists; the accumulation rule
  for multiple partial supersessions is §4's and is untouched.

## Consequences

**Easier.**

- **A reviewer has a rule to converge on.** The `Status` record follows the later
  ADR's declaration, checked against ADR-0070 §1 on the quoted clause. The two
  book-keeping demands that deadlocked PR #478 — supply a record the ADR did not
  declare, remove one it did — are both answerable by pointing at §1 here.
- **The corpus states one thing about one field.** After this change ADR-0070
  §4's extraction invariant is true of every line in `docs/adr/`, and an ADR
  author choosing where to record an amendment has a single sentence to consult
  instead of two ratified ADRs pointing opposite ways.
- **Silence stops looking like an omission.** ADR-0077's and ADR-0079's absence
  from ADR-0028's `Status` is now a recorded, correct outcome rather than an
  inconsistency a future reviewer re-litigates.

**Harder.**

- **Two records move off the field a scanner reads first.** Someone grepping
  `Status` lines for `ADR-0078` will now miss ADR-0045 and ADR-0050. That is the
  price of §4's invariant, and it is the trade ADR-0080 §8 already made and
  `main` already carries for ADR-0046.
- **The rule has two shapes, keyed on the leading token.** An author must notice
  which line they are writing on, and a line that later takes a partial
  supersession has to move its qualifier at that moment (§2). The alternative —
  one shape everywhere — costs either sixteen deleted records or a partial
  supersession of ADR-0070 §4.
- **The classification stays a judgement.** §1 locates it in the later ADR's
  author and makes it reviewable, but it is not mechanical and §6 declines to
  make it so. A wrong declaration produces a wrong record, and the correction is
  another ADR.

**Revisit when** a consumer that classifies liveness from `Status` is actually
built — ADR-0070 §4 binds it, #404 gates it, and it is the first thing that would
make any of this behavioural — or if a third leading-token line is ever proposed
to carry a qualifier, which §2 forbids and which would mean the trade above is
being paid more often than twice.
