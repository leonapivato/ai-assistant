# 277. A ruling has an address, and the record is checked for drift

- Status: Proposed
- Date: 2026-09-26
- Authorization: the owner accepted proposal #2558 on 2026-09-26, after the
  design-doc pilot #2553 was dropped.
- **Partially supersedes** [ADR-0088](0088-a-citation-is-a-checkable-form.md) —
  §6's "Two things, and only two" Tier 1 set and its closing "Nothing else is
  checked", as they reach the clause identifier and the record checks of §2 below;
  and §1(a)'s list of decision-citation forms, which gains the clause identifier.
  §6 below classifies every other ADR this touches.

## Context

### What the design-doc pilot found

The owner reopened #597 on 2026-09-25 and ran a pre-registered pilot (#2553): fold
one area's ADRs into a rewritable design doc and test whether it serves better than
the ADRs. It was **dropped**. An agent answering twelve questions from the ADRs alone
scored 86% against 73% from the design doc, so agents can find what the ADRs rule.

What the pilot and the surveys behind it showed instead is that **the record drifts
and nothing notices**:

- **Nine** header notes said ADR-0275 or ADR-0276 "remains Proposed" after both were
  ratified (#2555, fixed by #2560). The cause is structural. A superseding ADR writes
  its reciprocal notes onto earlier ADRs while it is still `Proposed`, and ADR-0165's
  exempt ratification commit may change only the ratified ADR's own Status line. So
  every such note goes stale on the day it becomes true.
- ADR-0131 marks quotations of ADR-0124 §10 and ADR-0094 §2 as its own rulings
  (#2556). The ADR template already says a shown mark belongs in a fence (ADR-0089
  §2); nothing checks that it is.
- Nothing checks ADR-0089 §5's rule that "Every ADR ratified after this one marks
  every normative clause it states". Every ADR ratified since does, but only by
  care. (ADR-0092, the one later-numbered ADR with no mark, was ratified a week
  before ADR-0089 and is outside the rule.)
- `scripts/check_citations.py` reported **no** finding for any of these.

The pilot also produced one tool worth keeping. It gave every marked clause an
address, `ADR-0094 §5:2` (the second marked clause of ADR-0094 §5), and addressed all
844 rulings of 15 ADRs with no collision.

### What was measured and is not decided here

Two checks on amendment records were considered and measured on 2026-09-26.

- **The Status line agreeing with the header notes.** Both sit at the top of one
  file, so a reader who misses an amender on one line meets it a few lines down. A
  mismatch is untidy, not misleading.
- **Reciprocity**: when ADR-Y says it supersedes or amends ADR-X, ADR-X's header
  names ADR-Y (ADR-0082 §1's record). A scan for "supersedes / amends / narrows
  ADR-X" found 111 such pairs. 88 are recorded on ADR-X. The other 23, read one by
  one, are all false positives: a third ADR's supersession being described, a
  rejected alternative, a hypothetical, or a negation. Where an ADR states its
  supersession, the discipline holds.

The miss that matters is the one no ADR states, and no check on the text finds it.
#2557 looked like one; it turned out to be a stacked addition (#2560).

### What earlier ADRs left open

- ADR-0088 §6 passes section numbers silently, because "ADR-0076 §9's obligation
  set" may name the *citing* ADR's §9, and it waits for "a mechanically distinct
  scope-reference form". A suffix that only means "the k-th ruling of the ADR just
  named" is that form.
- ADR-0070 §4 declined to impose "a stable-identifier scheme" on supersession
  scopes, because retrofitting anchors onto unsectioned ADRs is impossible. An
  identifier derived from marks imposes nothing on an unmarked ADR and rewrites no
  existing text.
- ADR-0089 §5 forbids adding a mark to a ratified ADR, and ADR-0001 makes a
  ratified body append-only, so the order of an ADR's marks is fixed once it is
  `Accepted`.

## Decision

### 1. A marked clause has an address

> **Normative.** The **clause identifier** `ADR-NNNN §S:k` names the *k*-th marked
> clause of ADR-NNNN within section *S*, counted from 1 in file order. A marked
> clause is one ADR-0089 §2's grammar selects, including ADR-0257's labelled forms.

> **Normative.** *S* is the number of the nearest numbered heading above the clause
> (`5`, `10a`). Where no numbered heading precedes the clause within its top-level
> section, *S* is the first word of the nearest level-2 heading above it
> (`Context`, `Consequences`). An unnumbered heading below level 2 does not start a
> section.

> **Normative.** `ADR-NNNN §S:j-k` names clauses *j* to *k* inclusive of section
> *S*, and several identifiers may share one ADR prefix, separated by commas.

> **Normative.** The clause identifier is an additional form of ADR-0088 §1(a)'s
> decision citation. It replaces no form: `ADR-NNNN`, `ADR-NNNN §K` and a scope
> written in words stay valid, and no lane rewrites an existing citation or scope
> into it.

**Why this address is stable.** Once an ADR is `Accepted`, ADR-0089 §5 and ADR-0001
fix its marks and their order, and header notes sit above every section, so an
identifier keeps naming the same clause. A `Proposed` ADR's identifiers can still
move while it is drafted; a citation of one is checked for existence only.

### 2. The checker reads the record

All checks run inside `scripts/check_citations.py` and the pytest corpus test that
already runs it, so the gate keeps five steps (ADR-0088 §6's precedent).

> **Normative.** A clause identifier that names no marked clause of its ADR is a
> Tier 1 finding: it fails the gate. ADR-0088 §6's Tier 1 set is two items and this
> one.

> **Normative.** A header note that says an ADR "remains Proposed" (or "remains
> `Proposed`") while that ADR's own Status is not `Proposed` is a Tier 2 finding.

> **Normative.** An ADR numbered above 0277, not `Withdrawn`, that has no marked
> clause is a Tier 1 finding.

> **Normative.** A marked clause whose text, after whitespace and blockquote
> markers are normalised, equals a marked clause of another ADR is a finding: Tier 1
> when it stands in an ADR numbered above 0277, Tier 2 in any other.

**Why the checks split at this ADR.** A finding in an older ADR is in ratified text
that no edit may change (ADR-0001, ADR-0089 §5), so a failing check would stay red
forever over ADR-0131's quotations. Reporting it and failing only new ADRs turns the
check into a regression guard with no backlog, which is ADR-0088 §6's own stance.
The marks check does not reach back at all: which older ADRs ADR-0089 §5 binds
depends on ratification order, which the text does not carry, and every ADR it binds
already marks. The stale-note check stays in Tier 2 for every ADR: a note written by a
`Proposed` ADR is true until that ADR's ratification, and ADR-0165's one-line flip
would otherwise turn `main` red on the day it lands. §3's first rule removes the
cause instead.

### 3. Two authoring rules

> **Normative.** A header note that an ADR writes onto an earlier ADR does not state
> the writing ADR's status. It may say that the change takes effect on that ADR's
> ratification, and it says nothing further about whether that has happened.

> **Normative.** A quotation of another ADR's marked clause carries no
> `**Normative.**` token. It is shown in a fenced block, as ADR-0089 §2 provides, or
> as a blockquote without the token.

### 4. A rules view

> **Normative.** `just adr-rules NNNN` prints the ADR's title, its complete Status
> line, and every marked clause verbatim, each under its section heading and
> prefixed by its clause identifier. It prints nothing else of the ADR's body.

> **Normative.** For an ADR with no marked clause, `just adr-rules` prints the title,
> the Status line and a statement that the ADR is unmarked and binds as prose, and
> prints no clause.

> **Normative.** `just adr-rules` states nothing about whether a clause is in force,
> replaced or narrowed. It shows the Status line and leaves that reading to the
> reader and to the ADRs the Status line names.

The view gives a reader an ADR's rulings without its argument: ADR-0094 is 1,133
lines, and its 34 rulings are 109. It adds no annotation because supersession scopes
are prose ("only as it reaches…"), and a guessed annotation would put a second,
possibly wrong statement of the law in front of the reader.

### 5. The work order

One implementing lane, after this ADR merges:

1. `scripts/check_citations.py`: clause-identifier extraction and resolution, and
   the checks of §2, each with tests under `tests/scripts/`.
2. `scripts/brief_check.py`: resolve clause identifiers in a dispatch brief, using
   the same extraction.
3. `just adr-rules`, with tests.
4. `CONTRIBUTING.md` → "Cite in form, and mark what binds" and `docs/adr/template.md`:
   the clause identifier and §3's two rules.

### 6. This ADR classified under ADR-0070 §1 and ADR-0082 §1

- **ADR-0088** is **partially superseded**. §6's statement that Tier 1 fails on "Two
  things, and only two", and its closing "Nothing else is checked", become false
  once §2 above adds a Tier 1 check, two more for new ADRs, and two reported ones. §1(a)'s list of the
  decision citation's forms gains a form. Its Status line and a dated header note
  record this.
- **ADR-0089** gains a stacked addition: §3's second rule states for quotations what
  §2's fence provision already allows. No sentence of ADR-0089 becomes false.
- **ADR-0082** gains a stacked addition: §3's first rule constrains what a
  reciprocal note says, not whether one is written.
- **ADR-0070 §4** is unchanged. Its scopes stay pointers in words, and the clause
  identifier is optional.

## Consequences

- A citation, a review finding, a brief or a supersession scope can name one ruling
  and have the checker confirm it exists. Old citations keep their meaning.
- Two drift patterns that went unreported are now reported, and a new ADR that
  marks nothing or marks a quotation fails the gate.
- The #2555 trap stops recurring by rule, not by cleanup.
- An agent or a reader can read one ADR's rulings in a fraction of its length.
- Not done here, and left open: a rules view annotated with what is in force, which
  becomes possible once supersession records name clause identifiers; making #597's
  fifth-amender trigger fire mechanically (21 ADRs are past it); and the ADR form
  itself (a Decision section holding every ruling, a separate rationale, a length
  budget; the median ADR is 869 lines). Each is a later decision.
- Revisit if a clause identifier is found to move in a ratified ADR, which would
  mean the stability argument of §1 is wrong.

## Alternatives considered

- **Rewritable per-area design docs as the authority.** Piloted and dropped (#2553).
- **Checks on who amended an ADR.** Measured above and found to catch nothing today.
- **Other clause forms.** `§5.2` reads as a subsection number, a meaning readers bring
  from every other document. `§5¶2` is unambiguous but hard to type. A global per-ADR
  ordinal (`ADR-0094 #17`) hides the section readers navigate by.
- **Failing immediately on the whole corpus.** Rejected: the findings are in text no
  edit may change, so the gate would never be green again.
- **Checking bare section numbers too.** Still declined on ADR-0088 §6's ground; only
  the new form escapes the ambiguity.
