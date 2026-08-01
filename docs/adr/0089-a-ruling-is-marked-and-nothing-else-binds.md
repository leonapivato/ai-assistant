# 89. A ruling is marked, and in a marked ADR nothing else binds

- Status: Proposed
- Date: 2026-08-01
- **This ADR supersedes nothing.** It gives a ruling a delimited written form and
  says what that form obligates. Under ADR-0082 §1 every addition it makes is a
  **stacked addition** — no sentence of an earlier ADR becomes false or
  over-wide — so no `Status` edit is owed on any earlier ADR, and §8 classifies
  every one of them. It is deliberately **forward-only**: §5 marks nothing that
  is already ratified, so no existing ADR is read differently after this change
  than before it. **No code changes with it** and no `core` surface is touched;
  nothing here is behavioural, and §7 does not decide that any check exists.

## Context

### A ruling has no single canonical statement

An ADR states what was decided and argues why, in one document, with no line
between the two. The corpus's ADRs run to 44,796 physical lines across 87 files;
a ruling is some small part of that, and which part is a judgement each reader
makes again. Three instances were on the record when this ADR was opened. All
three were re-checked against the tree, and the check changed two of them.

**#586 — confirmed, and sharper than the issue states it.** ADR-0086 §2 states
its bound twice, in two different shapes. It is first set off in a block quote:

```text
> **No `MemoryWriter` *installs* a record whose `provenance.evidence` exceeds
> `MAX_EVIDENCE_CITATIONS`.** …
```

Then, seventeen lines below and *outside* that block quote, at column 0:
"**It applies to every *install*, not only to a fold.**" Then §8 item 6 — a
numbered list item, a third shape — narrows it back: `Engine._project` "calls
`get_many` once per belief instead of `get` per citation. **That is the whole of
what this lane owes there**."

So one ADR states one obligation in three shapes, at three widths, and a lane
obeying the narrowest ships a migration leaving §6's stated 3,200 reads in place.
This is not a defect of care — ADR-0086 is a careful document, and §2's author
wrote the widening sentence *because* they judged the block quote alone might be
read narrowly. It is a defect of form: **there was no shape available that both
carried the rule and bounded it**, so the rule was written three times and the
three drifted. (#586's other half, `ConversationService`, is a citation defect
and is ADR-0088's subject, not this one's.)

**The `testing/store.py` instance — confirmed, and it has no issue.** ADR-0045's
Consequences name `testing/store.py` as the fake store's home; the fake
store is `FakeMemoryStore` in `testing/memory.py`, which ADR-0026 cites
correctly.
ADR-0088's Consequences found this and called it "the one this ADR is confident
about". **#597 attributes it to #596, and #596 is a different defect** — two
symbol citations, `ClassifiedToolError` and `UserProfile`, that resolve nowhere.
No issue tracks the `testing/store.py` case. It is filed with this change.

It is also, on inspection, **not an instance of this ADR's problem at all**. It
is a wrong citation inside a ruling, which is ADR-0088 §2(b)'s subject and is
already Tier 2 there — marking the clause it sits in would not have caught it,
and this ADR claims no credit for it. It is recorded here because #597 offers it
as motivating evidence and it does not carry the weight.

**~25 normative lines in ~880 — unverifiable, and that is the finding.**
ADR-0088 is 877 lines and carries **zero** block-quoted rulings; its rules are
written as column-0 bold-led paragraphs, indistinguishable in form from its
measurements and its arguments. So its author's count of its own normative core
cannot be checked by anyone, including its author. The number is offered here
neither as confirmed nor as refuted: **no reader of the corpus today can produce
that number for any ADR**, and a claim nobody can check is exactly what a
delimited form makes checkable.

### The convention already exists, in four shapes, and none of them selects

Measured over the 87 ADRs at `origin/main` (`ea47dac`), outside fenced blocks:

| shape | count | what it actually carries |
|---|---|---|
| block quote, bold-led (`> **…`) | 67 | mostly rulings — and 5 amendment notes |
| block quote, not bold-led | 56 | some rulings, some quotations of other documents |
| column-0 bold-led paragraph (`**…`) | 1,605 | rulings, measurements, arguments, headings-in-prose |
| numbered list item | uncounted | ADR-0086 §8's checklist, among others |

Authors have been reaching for this distinction for weeks. The word `normative`
appears on 37 lines of the corpus, almost always to do by hand what no form does:
"What is normative is each rule stated in prose" (ADR-0039), "Each member's
normative content is exactly the sentence above" (ADR-0040), "What is *normative*
is …" (ADR-0029 §3), "So this ADR makes non-reuse **normative**" (ADR-0044 §1).
ADR-0085 and ADR-0087, the two most recent contract ADRs, put 20 and 10 rulings
respectively into bold-led block quotes without any rule telling them to.

**The natural implementation is to ratify that emergent shape, and the corpus
refuses it in both directions.** Of the 67 bold-led block quotes, **5 are
amendment or supersession notes** and not rulings at all — ADR-0014's "**Amended
by ADR-0044 §1 (2026-07-23).**", ADR-0038's "**Discharged by ADR-0040
(2026-07-22).**", and three more. And the shape misses rulings that are plainly
rulings: ADR-0029 sets its central biconditional in a block quote with no bold
lead —

```text
> An id is invocable **if and only if** it is registered. `all_tools()` and the
> set of ids `invoke` will act on are the same set, always.
```

— while ADR-0018 uses the identical shape to *quote ADR-0001*. One shape, three
jobs, no way to tell them apart.

This is ADR-0088 §6's finding arriving from a second direction. There, the
natural implementation — extract `###` headings — was wrong on 92 citations.
Here, the natural implementation — extract bold-led block quotes — is wrong on 5
of 67 in one direction and on an uncounted number in the other, and it would be
wrong **silently**, because a ruleset built from it would simply not contain the
rules it missed. §2 therefore requires a literal token that no line of the
corpus carries, and the reason is not fastidiousness: it is what keeps the 87
existing ADRs mechanically outside the new regime (§5).

### What the append-only rule has already decided about retrofit

#597 lists "marking the normative core" among three things that "need retrofit
and become infeasible at scale", and reasons that a bounded retrofit is feasible
at 87 ADRs and will not be at 1,000. The premise about growth is roughly right
and slightly overstated: 87 ADRs in 17 days is ~5.1/day on average, but the rate
peaked at 15/day on 2026-07-24 and has run at **2.7/day over the last seven
days**. The door is closing more slowly than the figure suggests.

It does not matter, because **the door was never open.** ADR-0070 §1 is
unambiguous: "A permitted amendment is append-only in mechanism, too. It is
recorded as an **appended, dated note** …; ratified decision text — the Context,
Decision and Consequences — is never rewritten." §1 then enumerates the permitted
header edits, and none of them reaches Decision text. Marking a ratified ADR's
Decision would rewrite it.

Worse, under §3 below it would **change what that ADR obligates**: everything the
retrofitter did not mark would stop binding. That is not an amendment on
ADR-0070 §1's test — a reader would act differently — so a retrofit is 87
partial supersessions, not an editing pass.

And #597's own Direction says so first: "**ADRs stay exactly as they are** — an
append-only timeline of work. Unchanged: no status-line retirement, no
restructuring, no shortening." Marking 87 ratified files in place is
restructuring them. The retrofit premise contradicts the direction it appears in,
and §5 resolves it in favour of the direction.

**What retrofit would have bought is worth stating precisely, because it is not
nothing.** #597's constraint 2 requires a later ruleset to quote verbatim and be
checked. A marked clause is a delimited span, so a verbatim check against it is a
byte comparison. An unmarked ADR offers no span, so the same check is a substring
search over ~80-column wrapped prose — which ADR-0088 §6 already identifies as
the case where a naive matcher fails on the majority and a relaxation converts a
benign miss into a false assurance. That cost is real, it is paid by whoever
backfills, and §9 records that it is not paid twice: selecting the clauses is the
same reading either way, and only one of the two places to write the result is
legal.

## Decision

### 1. What a normative clause is

> **Normative.** A clause is normative when a reader could disobey it: it
> constrains what an implementation, a lane, or a later ADR may do. A
> measurement, an argument, a worked example, or a classification of the change
> being made is not normative, however load-bearing.

The test is *conduct, not weight*. ADR-0088's 3,387-reference count is
load-bearing and nobody can disobey it. Its rule that a code citation carries no
line number is a sentence long and binds every ADR written since.

**A refusal is normative.** "We will not add an engine-facing Protocol to
`core/protocols.py`" (ADR-0042 §1) bound work for weeks and took ADR-0084 §12 to
undo — a partial supersession, which is what is required to move a decision and
is never required to move a sentence that decided nothing. So an ADR's declined
alternatives are marked where they refuse something a later lane could otherwise
do, and left unmarked where they merely record that an option was weighed.

**Emphasis does not make a clause normative and the absence of emphasis does not
unmake one.** ADR-0070 §1's "**The test controls, not the label**" is the same
rule one level up: bold, position, a section titled "Decision", and the author's
conviction all leave the question exactly where §2 puts it, which is on the mark.

### 2. The mark

> **Normative.** A normative clause is written as a Markdown block quote,
> preceded by a blank line, whose first line begins at column 0 with `> `
> followed by the literal `**Normative.**`. Every physical line of the clause
> carries the same column-0 `> ` prefix, or is a bare `>`. The clause contains no
> fenced block.

> **Normative.** A `**Normative.**` line inside a fenced block is display, not a
> mark.

> **Normative.** One block quote is one clause. A clause that states two separable
> obligations is two block quotes.

**Extraction is a scan, and that is the whole requirement.** Read the file line by
line, tracking fence state; every column-0 `> ` run whose first line carries the
token is one clause. Nothing is inferred: not a section, not a heading, not a
list, not a paragraph. This is what ADR-0088 §6 demands of a checker — "the
checker touches only what it can pick out of the text without guessing what the
author meant" — and it is the property the whole design is bought for.

**Column 0 is load-bearing, and ADR-0043 is the precedent.** Its `PROPOSAL`
markers open and close "on their **own column-0 line**, preceded by a blank
line", because a marker that may be indented is a marker whose block boundary
depends on the enclosing structure. The consequence here is deliberate: **a
normative clause cannot live inside a list item.** ADR-0086 §8's checklist could
not have narrowed §2's bound in the form it used; it would have had to state the
narrowing as its own marked clause at column 0, where the contradiction with §2's
marked clause is two block quotes apart and visible in one extract. That is the
whole of what marking buys against #586, and it is worth being exact about it:
**marking does not remove a contradiction, it makes one local.**

**The fence escape is the same mechanism ADR-0088 §5 used**, for the same reason:
"the rule's own ADR is the one document guaranteed to contain what the rule
forbids, and a rule whose own statement violates it … is not a rule an
implementation can apply." This ADR's Context exhibits block-quoted rulings
twice, and both are fenced. No ADR on `main` carries a block-quote-shaped line
inside a fence, so the escape is defined before it is first needed rather than
after — and this document is the first to need it.

**One block quote is one clause because the corpus has already broken it.**
ADR-0086 §2's block quote carries two rules joined by a bare `>` — the install
bound and the retirement exemption — so an extraction of it yields one span
holding two obligations, of which a ruleset can adopt neither separately. A bare
`>` still joins *paragraphs of one clause*; what it may not join is two rules.
That distinction is a reading, so it is a reviewer's to enforce, not a checker's.

**Why a literal token and not the emergent shape.** Three reasons, and the third
decides it:

- The shape does not select: 5 of 67 bold-led block quotes are amendment notes,
  and rulings appear without the bold lead (Context).
- The token is greppable to zero, so an author can find every ruling in a
  document and a reviewer can diff the set.
- **A token no existing line carries is what keeps the 87 ratified ADRs outside
  the new regime** (§5). If the marker were a shape the corpus already writes,
  ADR-0085 would become a marked ADR the day this merged, and the 20 obligations
  it happens to have block-quoted would become the whole of what it obligates.
  That is a silent, retroactive narrowing of a ratified decision, and no rule
  stated later could undo it.

`**Normative.**` rather than ADR-0043's bare upper-case `PROPOSAL`: that marker
is a machine protocol in review output, and this one sits in prose a person
reads. `normative` is already the corpus's own word for the distinction, on 37
lines.

### 3. The marked set is the whole of what a marked ADR obligates

> **Normative.** In a marked ADR the marked clauses are the whole of what it
> obligates. Unmarked text is read to determine what a marked clause *means*; it
> never supplies an obligation. An obligation not stated in a marked clause does
> not bind.

**This is the crux, and the answer is yes: a lane may act on the marked clauses
alone.** Not because the argument is worthless — it demonstrably is not, and
#597's Direction is right that it "earns its place and has been shown to improve
the tests written against it" — but because the two failure modes are not
comparable. Today a lane can **miss** an obligation, silently, and ADR-0086 §8's
lane did. Under §3 a lane can only **misread** one, and a misreading is arguable
against a quoted span. Missing has no signal; misreading has a text.

**So the argument is demoted from a source of obligation to evidence of meaning,
and that is the entire change.** A lane that finds a marked clause ambiguous
reads the sections around it, exactly as it does now — but it reads them *on
demand*, to settle a question it can point at, rather than sweeping 880 lines
against the possibility that something in there binds.

**The constraint this puts on authors is the real cost, and it is not small.**

> **Normative.** A marked clause states its own scope, its conditions and its
> exceptions. Where the surrounding argument is what establishes *that* an
> obligation exists, or how far it reaches, the marking is not finished.

ADR-0086 §2 is the worked example on the other side. Its bound was marked; its
scope — every install, not only a fold — was a column-0 paragraph below the
mark. Under §3 that paragraph obligates nothing, so §2's author would have had to
put the width inside the clause or accept the narrow reading. Either outcome is
better than the one that shipped, and neither is free: writing a clause that
carries its own scope is harder than writing a rule and widening it in the next
breath.

**What this does not do.** It does not make a marked clause correct, it does not
resolve two marked clauses that contradict each other, and it does not stop an
author marking the wrong sentence. Those are reading and review, exactly as
ADR-0088 §2 concedes for a citation that resolves to the wrong object.

### 4. A marked ADR is bounded by its own marks; an unmarked one is read as it is today

> **Normative.** An ADR is *marked* when it carries at least one normative
> clause, and unmarked otherwise. An unmarked ADR is read exactly as it is read
> today: its Decision binds as a reader reads it, and §3 does not narrow it.

**The regime is per file, mechanical, and binary.** A lane determines which one
it is in by looking for the token, not by consulting a date, a number or a
manifest. This matters more than it looks: #597's constraint 3 requires coverage
to be "binary and mechanical … so a lane never judges whether a subsystem is
covered", and the same requirement applies one layer down, to the ADR itself.

**Partial marking is the hazard, and §3 is what makes it one.** An author who
marks three of five obligations has silently discarded two. No mechanical test
finds that — it is the same reading §3 concedes — so it is a review obligation:
a reviewer of a marked ADR checks that every obligation the document intends is
inside a marked clause. That is a new thing for a reviewer to do, and
Consequences records it as a cost rather than a detail.

**The failure of an author to mark at all is benign, and deliberately so.** An
ADR written after this one whose author marks nothing is unmarked, so it binds as
prose exactly as the existing corpus does. Nothing is lost except its
contribution to a later ruleset. ADR-0088 §6's asymmetry is the reasoning: "A
miss is benign; a false report is not." The dangerous direction here is an ADR
that is treated as marked when its obligations are not all marked, and §4's
default runs the other way.

### 5. Marking is forward-only, and nothing ratified is marked

> **Normative.** Every ADR ratified after this one marks every normative clause
> it states.

> **Normative.** A normative clause is added only before ratification. No mark is
> added to a ratified ADR, by a dated note or otherwise.

**The 87 ADRs on `main` at this ADR's date stay unmarked, permanently.** Context
gives the ground and it is ratified law rather than a cost calculation: ADR-0070
§1 forbids rewriting ratified Decision text, and §3 above would make such a
rewrite a decision change rather than an amendment, so a retrofit is 87 partial
supersessions. ADR-0070 §4 and #71 already settled the general form of this —
"converting a merged, ratified decision to satisfy a rule adopted after it is the
append-only violation the rule exists to prevent, pointed backwards" — and
ADR-0088 §5 applied it to line numbers three days ago.

**The second clause closes a trapdoor rather than adding a rule.** A dated note is
a permitted header edit under ADR-0070 §1, so absent this clause an unmarked ADR
could acquire its first mark by amendment — and under §4 it would become a marked
ADR, whereupon everything else it decided would stop binding. That edit would
already fail ADR-0070 §1's own test; the clause states the consequence so no
author has to derive it.

**There is exactly one legal route by which an old rule enters the marked
regime, and it is not an edit.** A later ADR may restate an earlier ADR's rule as
its own marked clause and partially supersede the earlier one for that scope
(ADR-0070 §3, which ruled partial supersession "the sanctioned tool" and refused
to require pre-splitting). That is expensive per rule and is not proposed here
for any rule. It is recorded because it is the answer to "what if a specific old
ruling must be in the ruleset", and the answer is not "mark it".

**The other route is that the ruleset is authored, not extracted.** #597's own
sequence backfills `memory`, then `tools`, then `interfaces` — and selecting
which clauses of ADR-0028, ADR-0045 and ADR-0077 are the law is the same reading
whether the result is written into those files or into the ruleset. Retrofit
would not save the reading; it would only move where the result is written, and
of the two places only one is legal. What is genuinely lost is the byte-exact
anchor for #597's constraint 2, and Context states that cost in full.

### 6. Composition with ADR-0088

> **Normative.** A citation inside a normative clause is written in ADR-0088 §1's
> forms and resolves by its §2, unchanged.

**Nothing about ADR-0088's checker changes, and this is checked rather than
asserted.** §1's three citation forms, §2's three definitions of "resolves", §3's
rule that no code citation may fail, §4's liveness report and §6's two tiers all
stand exactly as ratified. A mark selects a *clause*; it selects no citation that
ADR-0088 §1 leaves unselectable. In particular **b3 stays unselectable inside a
marked clause**: `` `ConversationLifecycle` `` in a marked ruling is the same bare
token it was outside one, and ADR-0088 §9 declined a marker syntax for exactly
that problem on grounds this ADR does not disturb.

**Two nearby things are deliberately not done.** A marked clause is *not* given a
citable identifier — no `ADR-NNNN R3` form — because ADR-0088 §1 says "a
reference not written in one of these forms is prose, not a citation", so
inventing one would amend §1 and owe ADR-0088 a record. A rule is addressed as it
always was, by its section. And a marked clause does *not* carry a subsystem tag,
though a per-subsystem ruleset will eventually need one: choosing the routing key
now would decide a piece of the ruleset's model inside an ADR nobody read for it.
§7 leaves both to whoever writes that decision.

**The one thing marking would make tractable is named and not taken.** ADR-0088
§6 leaves section references unchecked because "a `§K` in prose cannot be
distinguished from a restatement of a supersession scope", and §9 declined
inventing a distinct form on the ground that it buys a check over a category with
no known real misses. A delimited clause is a candidate for that distinct form.
It is not proposed here — the evidence §9 asked for has not appeared, and
proposing it would put a change to ADR-0088 §6 inside an ADR about something
else.

### 7. What this does not cover

- **The ruleset.** Whether a rewritable per-subsystem ruleset becomes the live
  law, what wins when it and an ADR disagree, how coverage is declared, and
  whether it quotes or paraphrases — all of #597's Direction — is a later ADR's.
  This one supplies a delimited span for it to quote and decides nothing about
  what it is. Nothing here forecloses it: §3 makes a marked clause self-contained,
  which is what a verbatim-quoting ruleset needs, and §5's non-retrofit bounds
  what it can be built from without bounding what it may be.
- **Whether any check runs, and where.** Extraction is a scan (§2) and
  well-formedness — an unterminated mark, a fenced block inside a clause, a
  marked clause on an ADR predating this one — is mechanically decidable. None of
  that is decided here: no tier, no gate step, no hook. ADR-0088 §6 said the same
  of its own check's location, for the same reason, and the lane implementing
  ADR-0088's checker (#588) is not asked to carry this.
- **Bounding the live set.** #597's second half — wholesale supersession when an
  ADR would take a fifth amender, and the growth of the partially-superseded
  set — is untouched. It is a separate decision and this ADR neither helps nor
  hinders it.
- **`CONTRIBUTING.md`, `CLAUDE.md` and the rubrics.** They are ratified normative
  documents too (ADR-0003, ADR-0019), and §1's test would apply to them cleanly.
  Extending marking there is a bigger rule than this ADR was read for, and it
  collides with ADR-0019's living-document treatment in ways nobody has worked
  out.
- **Whether a marked clause is correct**, and whether the right sentences were
  marked. Both are reading, and both stay with the author and the review (§3).

### 8. This ADR classified under ADR-0070 §1 and ADR-0082 §1, edit by edit

- **ADR-0070 — nothing owed.** §1's amend-vs-supersede test, its append-only
  mechanism and its enumeration of permitted header edits are relied on
  throughout and narrowed nowhere; §5 above derives its non-retrofit *from* §1
  rather than adding to it. §3 and §4 are untouched. Under ADR-0082 §1 this is a
  **stacked addition**: a form for stating a ruling is an obligation ADR-0070
  never addressed, so no sentence of it becomes false or over-wide, and it is
  "recorded in the ADR that makes it, and nowhere else."
- **ADR-0088 — nothing owed, and §6 above is the showing.** Its §1 forms, §2
  resolution rules, §3 no-failing rule, §4 liveness report and §6 tiers are all
  unchanged. This ADR adds no citation form and makes no token selectable that §1
  leaves unselectable, so §9's declined marker syntax is not reopened. A reader
  of ADR-0088 acts identically before and after.
- **ADR-0082 — nothing owed.** §6's refusal of a mechanical `Status` cross-check
  and §1's stacked-addition test are applied here, not narrowed.
- **ADR-0043 — nothing owed.** §2's column-0 marker discipline is cited as
  precedent for a marker in a different document class. Nothing about the review
  protocol's markers changes.
- **ADR-0086, ADR-0045 and every other ratified ADR — nothing owed, and §5 says
  why.** The rule is forward-only, so none of them is marked, none is read
  differently, and no sentence of any of them becomes false. ADR-0086 §2 and §8
  are quoted as evidence of a defect in the *form available to them*, which is
  not a claim that either decided anything wrongly.
- **ADR-0015, ADR-0027 — nothing owed.** Neither the contract-ADR sequencing nor
  the review floor is touched; `docs/adr/**` remains in ADR-0027 §3's floor and
  this ADR does not ask to change that.
- **`docs/adr/template.md` — an edit is owed and this ADR does not write it.**
  The template is where an author meets the form, and §2's mark belongs in its
  Decision guidance. ADR-0070 §4 is the precedent for an ADR directing a template
  correction. Filed as an issue rather than written here, because this lane's
  fence is one file (Consequences).
- **`CONTRIBUTING.md` — an edit is owed and this ADR does not write it**, for the
  same reason and on ADR-0070 §5's precedent. It rides with #595, which already
  owes it ADR-0088's forms.
- **This ADR's `Status`.** It ships `Proposed` and is reviewed while `Proposed`,
  so a finding can still change the decision, then flips to `Accepted` before
  merge (ADR-0015 §5; `CONTRIBUTING.md`, "Contract ADRs land before their
  implementation"). It touches no Protocol and no `core` type and decides no
  contract surface, so **adversarial is the required set** — the same reading
  ADR-0082 §5 and ADR-0088 §8 recorded for themselves.
- **This ADR is its own worked example.** It states **ten** normative clauses
  occupying **29 of its 567 physical lines**, and both figures are verifiable by
  anyone with `grep` — which is the property ADR-0088's "~25 in ~880" does not
  have, and the difference is the whole point.

### 9. Explicitly declined

- **Retrofitting the 87 ratified ADRs.** #597 asks for it and calls it a one-way
  door. Declined on ratified grounds (§5), not on cost: ADR-0070 §1 forbids the
  edit, §3 above would make it a decision change rather than an amendment, and
  #597's own Direction — "ADRs stay exactly as they are … no restructuring" —
  refuses it two paragraphs earlier. The door metaphor also does not hold:
  selecting which clauses are the law is the same reading whether it is written
  into the ADR or into the ruleset, so the work is not lost by waiting, only
  relocated to the one place it may legally go. **Revisit if** a ruleset is
  ratified and its verbatim-quote check proves unworkable against unmarked
  spans — that is the one cost non-retrofit really imposes (Context), and it is
  measurable once the check exists.
- **Ratifying the emergent bold-led block quote as the mark.** It is what 21 ADRs
  already write and it would cost authors nothing to adopt. Refused because it
  does not select — 5 of 67 are amendment notes, and unbolded rulings exist — and,
  decisively, because it would retroactively mark ADR-0085 and twenty others,
  narrowing ratified decisions to whatever they happened to block-quote (§2).
- **A `## Ruling` section holding the ADR's rules.** Top-level structure is
  uniform enough to make this extractable — `## Context` and `## Decision` appear
  in 87 of 87 files, `## Consequences` in 86 — so the objection is not
  mechanical. It is that a rule stated in a dedicated section and argued in
  another is a rule written twice, and two statements of one rule drifting apart
  is the defect this ADR exists to fix. #586 is that defect at a distance of
  seventeen lines; a section boundary would make it a defect at a distance of
  four hundred. Marking is in place for that reason and no other.
- **A citable identifier per clause** (`ADR-NNNN R3`). Declined in §6: it would
  amend ADR-0088 §1's citation forms and owe ADR-0088 a record, for a benefit
  that only a ruleset needs. **Revisit if** the ruleset ADR needs to cite an
  individual clause, which is the point at which it is worth its record.
- **A subsystem tag on the mark.** Declined in §6 as deciding part of the
  ruleset's model inside the wrong ADR. **Revisit** in that ADR.
- **Requiring marks in `## Decision` only.** It would bound extraction to a
  section, and a section boundary is structure — the thing §2 refuses to infer.
  Marks are recognised by form wherever they appear, which costs an author who
  marks a clause in Context nothing worse than having stated an obligation in an
  odd place.
- **Making ADR-0088 §6's section references checkable off the back of this.**
  Named and refused in §6; it is a change to ADR-0088 in an ADR about something
  else.

## Consequences

**Easier.**

- **A lane knows what it owes.** The marked clauses, all of them, nothing else
  (§3). The judgement that stays with the lane is what a clause *means*, which is
  arguable against a quoted span, rather than which sentences of 880 were rules,
  which is arguable against nothing.
- **A ruling can be extracted without inferring document structure.** A fence-aware
  line scan, no headings, no sections, no lists. That is the property ADR-0088 §6
  demands and it is what makes a later ruleset possible at all.
- **An author has one place to put the rule and one obligation about it** — state
  its scope inside the mark (§3). ADR-0086 §2's author wrote the widening sentence
  because no shape carried it; the shape now exists.
- **A contradiction becomes local.** #586's three-shape drift becomes two block
  quotes in one extract, adjacent and comparable. This is a narrower claim than
  "marking prevents contradiction", which it does not.
- **The corpus is not touched.** No file changes, no status line moves, no
  ratified sentence is rewritten, and every existing ADR binds tomorrow exactly
  as it binds today.

**Harder.**

- **This ADR fixes none of the three instances that motivated it, and that is the
  honest headline.** ADR-0086, ADR-0045 and ADR-0088 are ratified and unmarked, and
  §5 keeps them that way. #586 stays open. The `testing/store.py` defect is
  ADR-0088 §2(b)'s subject and was never this ADR's to catch. What this delivers
  is a form for the ADRs written after it, and it earns out over months — the same
  thin, honest promise ADR-0088 §4 made about its reverse record.
- **Two reading regimes coexist indefinitely.** 87 ADRs bind as prose; everything
  from here binds by its marks. A lane meets both and must know which it is in.
  The mitigation is that the test is a `grep`, not a judgement (§4), and the
  ratio moves the right way with every ADR written.
- **Authors pay for it, on every ADR.** A clause must carry its own scope,
  conditions and exceptions (§3), which is harder than stating a rule and
  qualifying it in the next paragraph. Rules that were comfortable spread over a
  section have to be written once, whole.
- **Reviewers gain an obligation no tool can discharge.** Checking that *every*
  obligation is inside a mark is exactly the reading a checker cannot do (§4), and
  under-marking silently discards rules. This is the sharpest risk the design
  carries: §4's default protects an ADR that marks nothing, and protects nothing
  about an ADR that marks most.
- **The ruleset's verbatim anchor is lost for the existing corpus.** #597's
  constraint 2 wants quoted-and-checked rules; against a marked clause that is a
  byte comparison and against 87 unmarked ADRs it is a substring search over
  wrapped prose, which ADR-0088 §6 already identifies as the hard case. Backfill
  pays this, once per clause, and §9 records the revisit condition.
- **A `docs/adr/**` change still cannot fail on any of this.** No check is decided
  (§7), so nothing mechanical enforces §2's form or §5's forward-only rule until
  someone decides one. Until then this is a convention with a reviewer behind it,
  which is what #588 complained about in the first place.

**Follow-on.**

- **`docs/adr/template.md` owes §2's mark** in its Decision guidance, and
  **`CONTRIBUTING.md` owes §1's test and §3's rule**. Both filed as issues; neither
  written here (§8). The `CONTRIBUTING.md` edit rides naturally with #595, which
  already owes it ADR-0088's citation forms.
- **ADR-0045's `testing/store.py` citation has no issue and gets one.** #597
  attributes it to #596; #596 is `ClassifiedToolError` and `UserProfile`. It is an
  ADR-0088 §2(b) Tier 2 defect, not this ADR's.
- **#597 is the tracking issue and stays open.** This ADR is its third step. The
  fourth — putting ruleset content into a `memory` lane's brief and observing
  whether the lane still opens the ADRs — is unaffected by anything here and can
  run on unmarked ADRs, since a brief quotes whatever a human selects.

**Revisit when** the first five ADRs are written under §2. Whether a clause can
in practice carry its own scope (§3) is the assumption everything else rests on,
and five documents' worth of marks — read against the arguments beside them — is
the cheapest real test of it. Revisit also **if** a ruleset is ratified and finds
that unmarked spans cannot be verbatim-anchored, which is the one cost §5's
non-retrofit genuinely imposes.
