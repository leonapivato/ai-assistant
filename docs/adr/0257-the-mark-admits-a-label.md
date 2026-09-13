# 257. The mark admits a label, and the 321 labelled clauses in seven ratified ADRs bind

- Status: Proposed
- Date: 2026-09-13
- **Partially supersedes** [ADR-0089](0089-a-ruling-is-marked-and-nothing-else-binds.md)
  — **one scope: §2's first clause, in its first-line sentence alone.** *"Its first line
  begins `> **Normative.**`"* gains a second admitted opening — the token followed by a
  **label separator** and a non-empty label. §2's every other part binds **verbatim**: the
  run's column-0 `> `-or-bare-`>` shape, the blank-line precedence, the run's end at the
  first line of neither shape, the no-fenced-block rule, the fenced-line-is-display clause,
  the *"fails any part of that grammar is not a mark"* clause and the one-obligation rule —
  the last three read over the widened first line. **§5 is untouched and is what rules out
  the alternative**: no mark is added to any ratified ADR here and no byte of one changes.
  §§1, 3, 4, 6, 7, 8 and 9 stand entire, and §7's *"whether any check runs"* is left exactly
  where it was. §6 shows the working.
- **No other ADR is superseded in whole or in part**, and §6 says why none of the seven
  ADRs this decision reaches owes a record: not one sentence of any of them becomes false
  or over-wide, because not one of their bytes moves.

## Context

### §2 makes the mark a literal prefix, and seven ratified ADRs wrote a different one

ADR-0089 §2 is exact about the opening: *"Its first line begins `> **Normative.**` and is
immediately preceded by a blank line or by the start of the file."* Its third clause is
exact about a near-miss: *"A line that fails any part of that grammar is not a mark, and no
ADR is marked by it."* And §3 is exact about the consequence: *"In a marked ADR the marked
clauses are the whole of what it obligates … An obligation not stated in a marked clause
does not bind."*

Read at the base of this decision (`2ce4c193`), `docs/adr/` carries **7,826** lines opening
`> **Normative` at column 0. **321 of them do not carry the literal prefix**, in two shapes:

| shape | count | example opening |
|---|---|---|
| `> **Normative — <label>` (U+0020 U+2014 U+0020) | 315 | `> **Normative — the resolution is **before** the ruling…` |
| `> **Normative. <label>` (U+002E U+0020) | 6 | `> **Normative. The undescribed key.** The seam refuses…` |

They sit in seven ratified ADRs and nowhere else:

| ADR | token lines | exact | labelled |
|---|---|---|---|
| 0152 | 120 | 114 | 6 |
| 0249 | 116 | 100 | 16 |
| 0250 | 148 | 127 | 21 |
| 0251 | 90 | 57 | 33 |
| 0252 | 112 | 58 | 54 |
| 0253 | 106 | 20 | 86 |
| 0254 | 178 | 73 | 105 |

Every other ADR carrying the token is exact. Under §2 read literally none of the 321 is a
mark; under §3 each of those seven documents is nonetheless *marked*, because each also
carries well-formed clauses. So the literal reading discards 321 obligations — including
most of ADR-0254 §12's expiry ladder, whose implementing lanes are not yet briefed.

### Nobody has ever read them as unmarked

The labelled form is the same author's hand as the exact form, in the same section, one
paragraph apart. Its authors marked it; its reviewers reviewed it as binding — both lenses
raised the defect on PR #2301 the moment it appeared in a *new* document, which is how
#2303 came to be filed; and the lanes that implemented ADR-0249, ADR-0250, ADR-0251 and
ADR-0252 were briefed against those clauses and built to them. No reader, author, reviewer
or lane has ever acted on the literal reading. What is being decided is not what these
documents mean — that was never in doubt — but which of two instruments makes the text say
it.

### The two candidate fixes are not symmetric, and one of them is forbidden

**Normalising the 321 lines** — rewriting each to the exact prefix and preserving the label
after it — edits **seven ratified ADRs**. ADR-0070 §1 is flat: *"ratified decision text —
the Context, Decision and Consequences — is never rewritten"*, and its enumeration of
permitted in-place edits is to header lines only. ADR-0089 §5's second clause is flatter
still, and is precisely about this operation:

```text
> **Normative.** A normative clause is added only before ratification. No mark is
> added to a ratified ADR, by a dated note or otherwise.
```

So normalising would itself need to partially supersede ADR-0089 §5 *as well as* editing
1,300-odd bytes across seven ratified documents, two of which (ADR-0251, ADR-0254) are under
edit by another lane as this is written.

**Widening the grammar** edits one clause of one ADR and no ratified byte anywhere. §7 gives
the rest of the comparison; this section records only that the cheaper instrument is also
the one the corpus's own rules permit.

### The obvious widening is too narrow, and the corpus says so

A first draft of this decision admitted a first line whose bold run **closes on that line**
with `.**`. Measured against the corpus that grammar recognises **173 of the 315** dash-form
openings. The other 142 wrap: the label runs past the line break and the bold closes on a
later line of the same run. A further **24** close the bold with `**` not preceded by a full
stop (`…where all of the following hold**:`), and two nest a second bold run inside the
label. The label is prose an author wrote to be read, not a field, so the grammar does not
get to say where it ends — §1 constrains only how the mark **opens**, which is the one thing
a scan needs.

## Decision

### 1. The mark admits a label

> **Normative.** A normative clause's first line begins, at column 0, with `> **Normative`
> immediately followed by either the two characters `.**`, or by a **label separator** —
> a full stop and a space (U+002E U+0020), or a space, an em dash and a space
> (U+0020 U+2014 U+0020) — and then at least one non-space character on that same line.
> This replaces ADR-0089 §2's first clause in its first-line sentence alone; every other
> part of §2 governs unchanged, including its blank-line precedence, its run shape and end,
> its no-fenced-block and fenced-line-is-display rules, its one-obligation rule, and its
> rule that a line failing any part of the grammar is not a mark and marks no ADR.

**Extraction is still a scan, with nothing added to it.** The scan gains one alternative at
one position of one line. It infers nothing, reads no section, heading, list or paragraph,
and decides the run's extent exactly as before. That is what ADR-0088 §6 demands of anything
mechanical — *"the checker touches only what it can pick out of the text without guessing
what the author meant"* — and the widened opening is picked out without guessing: the token,
then one of three fixed byte sequences.

**It is still greppable to zero**, which is §2's second reason for a literal token. One
pattern finds every ruling in a document and a reviewer can diff the set:

```text
grep -n '^> \*\*Normative\(\.\*\*\|\. \| — \)' docs/adr/<file>.md
```

**And a near-mark still fails closed.** `> **Normative —**` with no label, `> **Normative—x`
with no spaces, `> **Normatively` and an indented or fenced token line are all not marks, so
none of them becomes a clause and none switches an ADR into the marked regime. §2's
fail-closed direction is the property that makes the widening safe to state at all, and it
is untouched.

### 2. What follows the token is clause text

> **Normative.** Text on the first line after the token and its separator is clause text,
> read exactly as every other line of the run is read. A label is not a title and is not
> outside the clause: where its words state the obligation, they state it as the clause's
> own, and where they name the subject they are read as the clause's first words.

The corpus is unambiguous that this is what the labels are. ADR-0253's *"— the resolution is
**before** the ruling, and nothing moves after it."* is the rule itself, not a heading over
it. A grammar that treated the label as a caption outside the clause would discard the
obligation a second way, having just admitted the line.

### 3. The grammar reaches the whole corpus, and the 321 bind

> **Normative.** §1's grammar is how every ADR in the corpus is read — ratified or not,
> written before this decision or after it. No ADR is exempt and no date bounds it.

> **Normative.** The 321 labelled clauses in ADR-0152, ADR-0249, ADR-0250, ADR-0251,
> ADR-0252, ADR-0253 and ADR-0254 are marks. They bind as marked clauses of their own
> documents under ADR-0089 §3, from each document's own ratification and not from this
> decision's date.

**Retroactive by construction, and that is the point rather than a cost.** The clauses were
written as marks by authors under ADR-0089 §5's first clause — *"Every ADR ratified after
this one marks every normative clause it states"* — reviewed as marks, and implemented as
marks. Dating their force from today would invent an interval in which they did not bind,
which no reader, author or lane ever occupied, and would retroactively make four merged
implementation lanes unfounded.

**It narrows nothing, and that is checked rather than asserted.** §2's third and decisive
reason for a literal token was that *"a token no existing line carries is what keeps the 87
ratified ADRs outside the new regime"*: a mark that the old corpus already wrote would have
switched ADR-0085 and twenty others into the marked regime the day ADR-0089 merged, silently
narrowing them to whatever they happened to block-quote. That hazard is the one thing a
widening could reopen, so it was measured at this decision's base:

- **No ADR numbered below 0089 carries a `> **Normative` line at all** — 164 files carry the
  token and the lowest is ADR-0089 itself. Nothing predating the regime is touched.
- **No file in the corpus carries a labelled mark and no exact one.** Each of the seven
  already carries exact marks and is already marked under ADR-0089 §4, so **not one ADR's
  marked/unmarked regime changes**. The widening adds clauses to documents that are already
  bounded by their marks; it moves no document across the boundary.

The measurement is a scan of `docs/adr/*.md` implementing §2 fence-aware, reported in this
change's PR body with its before/after figures: **7,498 recognised marks before, 7,819
after, and 321 near-misses before and 0 after.** It is a measurement, so it is unmarked and
will go stale; the two properties above are what the reasoning rests on and either can be
recomputed with the `grep` in §1.

### 4. The exact form stays the one the template teaches

Nothing here asks an author to write a label, and the template's
`> **Normative.** <one obligation…>` needs no correction to stay correct — it remains a
well-formed mark and the shorter one. The labelled form is admitted because 321 ratified
clauses use it and because a label earns its place in a document carrying 178 clauses, where
*"— `PROTOCOL_VERSION` …"* is how a reader and a reviewer tell one from the next.

**Two authoring documents are owed an edit and this ADR does not write them.**
`docs/adr/template.md` and `CONTRIBUTING.md` → "Cite in form, and mark what binds" both
state the form, and both should state the widened one. ADR-0089 §8 is the precedent for
directing the correction rather than writing it — it filed #600 and #601 and they landed in
PR #607 — and there is a second reason here: `CONTRIBUTING.md` is in ADR-0027 §3's review
floor and ADR-0209 §1 invalidates *every* artifact of *every* persona for any PR whose base
move carries it, so folding a two-paragraph edit into this diff would charge a review round
to every lane in flight. Filed as an issue, named in Consequences.

### 5. What this does not decide

- **Whether anything reports a near-mark.** ADR-0089 §7 *"leaves to a later decision whether
  anything reports it"*, and this decision leaves it there. No script under `scripts/`
  implements §2's scan today — `check_citations.py` and `citations.py` implement ADR-0088 §6
  — so no checker changes with this ADR, and none is created by it.
- **Whether the 321 clauses are correct, or whether the right sentences were marked.** Both
  are reading and review, exactly as ADR-0089 §3 leaves them. This decision says those lines
  are marks; it says nothing about what they should have said.
- **Any other near-miss shape.** A third separator, a bracketed label, a numbered one: none
  is admitted, and a later one would need its own decision. The two admitted separators are
  the two the corpus wrote.

### 6. This ADR classified under ADR-0070 §1 and ADR-0082 §1, edit by edit

- **ADR-0089 — a partial supersession of §2's first clause, and the header record is owed.**
  ADR-0070 §1's test comes out on the supersession side without argument: a reader holding
  only ADR-0089 reads `> **Normative — x.**` as not a mark before and as a mark after, and
  acts differently on 321 lines. The record is the `Status` line edit ADR-0070 §1 permits
  and ADR-0001 requires, carrying the scope; no other byte of ADR-0089 moves.
- **ADR-0089 §5 — untouched, and deliberately.** Its first clause (*"marks every normative
  clause it states"*) is what the seven authors were writing under; its second (*"No mark is
  added to a ratified ADR"*) forbids the alternative in §7 and is satisfied here by
  construction, since this decision edits no ratified ADR's text. ADR-0089's leading header
  note — *"It is deliberately forward-only: §5 marks nothing that is already ratified"* — is
  a true statement about **ADR-0089's own change** and stays exactly as written; ADR-0070 §1
  forbids rewriting it and nothing here needs it rewritten. The forward-only property it
  protects also survives this decision on the measurement in §3: every ADR this widening
  reaches was ratified *after* ADR-0089 and authored under its §5.
- **ADR-0152, ADR-0249, ADR-0250, ADR-0251, ADR-0252, ADR-0253, ADR-0254 — nothing owed on
  any of them, and this is the one a reader should check.** ADR-0082 §1's test is applied to
  *the earlier ADR's text*: no sentence of any of the seven becomes false or over-wide,
  because not one of their bytes moves and not one of their clauses says anything about the
  grammar. The clause that changes is ADR-0089 §2's, and that is where the record goes.
  Writing seven `Status` edits would record on seven documents a change none of them made,
  and each would be an in-place header edit with no supersession of *that* ADR behind it,
  which ADR-0070 §1 does not permit.
- **ADR-0088 — nothing owed.** No citation form, resolution rule or tier changes; §6's
  without-guessing standard is applied in §1 and narrowed nowhere. A stacked addition under
  ADR-0082 §1, recorded here and nowhere else.
- **ADR-0070, ADR-0082, ADR-0001 — nothing owed.** Their amend-vs-supersede test, their
  record-placement rule and the append-only `Status` mechanism are used as written.
- **ADR-0015, ADR-0027 — nothing owed.** §5's ADR-number assignment and contract sequencing
  are untouched; `docs/adr/**` stays in ADR-0027 §3's floor and this decision does not ask
  to change that.
- **This ADR's own marks are written in the exact form**, all of them, so that nothing about
  this document's force depends on the widening it proposes.
- **This ADR's `Status`.** It ships `Proposed`, is reviewed while `Proposed`, and flips to
  `Accepted` before merge (ADR-0015 §5; `CONTRIBUTING.md` → "Finishing an ADR PR"). It
  touches no Protocol, no `core` type and no behaviour, but it decides how every ADR's
  ruling surface is read, so **both lenses are run** rather than adversarial alone.

### 7. Explicitly declined

- **Normalising the 321 lines to the exact prefix.** The alternative #2303 recommends, and
  the honest one: it leaves §2's grammar at its narrowest and edits the documents that are
  wrong. Declined on ratified grounds rather than on cost. ADR-0089 §5's second clause
  forbids adding a mark to a ratified ADR *"by a dated note or otherwise"*, and re-marking
  a line is adding a mark to it by any reading; ADR-0070 §1 forbids rewriting ratified
  decision text, and 321 lines in seven Decision sections is that rewrite at scale. So the
  cheap-looking fix needs **two** partial supersessions before it may touch anything, after
  which it still edits seven ratified documents — two of them under concurrent edit — to
  reach a state the widening reaches by changing one clause. The cost argument only breaks
  the tie: on the evidence in Context the labels wrap, nest bold, and end without a full
  stop, so a mechanical rewrite of 321 lines would need review line by line, and the failure
  mode of getting one wrong is a silently discarded obligation, which is the exact defect
  being fixed.
- **Admitting the dash form alone.** #2303's second option as stated (*"begins
  `> **Normative.**` or `> **Normative —`"*). It recognises 315 of the 321 and leaves
  ADR-0152's six — the period-separated ones — exactly as broken as before, in a document
  the issue's own table names. A fix that leaves part of its own inventory unfixed is worse
  than either whole option, because the residue is then invisible.
- **Requiring the label's bold run to close on the first line** with `.**`. Recognises 173
  of 315 (Context). It would also make an author's line-wrapping decide whether their rule
  binds, which is the class of defect ADR-0089 exists to remove.
- **Deprecating the labelled form while admitting it.** Two forms with one preferred invites
  a reviewer to spend rounds on which was used. The label is prose; §2 does not legislate
  the prose of a clause and this decision does not start.
- **Adding a gate check in this change.** #2303's third recommendation, and a good one — the
  `grep` in §1 would have caught all seven documents at authoring time. It is a separate
  decision under ADR-0089 §7 (no tier, no gate step, no hook was decided there), it is
  ADR-0088 §6's *"a miss is benign; a false report is not"* asymmetry applied to a new
  report, and putting it inside an ADR about the grammar would decide in passing what §7
  left open. Filed as an issue.

## Consequences

**321 obligations start binding, and 105 of them are ADR-0254's.** Its §12 expiry ladder is
the immediate beneficiary: the lanes ADR-0254 §20 has yet to brief now inherit a document
whose rules are all inside marks. No lane's completed work is invalidated — every one of
them built to these clauses already.

**The mark is two shapes instead of one**, which is a real cost paid against a real one. A
reader now checks the token and then one of three byte sequences rather than one. The
mitigation is that all three are found by a single `grep` and that a near-miss still fails
closed, so the failure direction — the one §2 bought — is unchanged.

**What would trigger revisiting this.** A third separator appearing in the corpus would mean
the widening taught authors that the opening is negotiable, which it is not; that is the
signal the check under ADR-0089 §7 should be decided rather than the grammar widened again.

**Follow-on work, filed rather than written here** (§4, §7): the `docs/adr/template.md` and
`CONTRIBUTING.md` corrections, and the ADR-0089 §7 question of whether a near-mark is
reported by the gate.
