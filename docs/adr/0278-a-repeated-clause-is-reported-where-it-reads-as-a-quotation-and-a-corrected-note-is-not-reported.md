# 278. A repeated clause is reported where it reads as a quotation, and a corrected note is not reported

- Status: Proposed
- Date: 2026-09-26
- Authorization: on 2026-09-26 the owner answered the coordinator's recommendation on
  #2564 — that the repeated-clause check stop failing on wording the corpus restates on
  purpose — with "do your recommendations".
- **Partially supersedes** [ADR-0277](0277-a-ruling-has-an-address-and-the-record-is-checked-for-drift.md)
  — **§2's sixth clause (ADR-0277 §2:6), in which equal marked clauses are findings
  and which member of an equal set is reported; and §2's fourth clause (ADR-0277
  §2:4), as it reaches a stale note that a later dated header note in the same ADR
  has already corrected.** Those two scopes, and nothing else in that ADR: §2's
  normalisation, its tier split at ADR-0277 and its other four clauses, §1, §3, §4
  and §5 bind as written. §5 below classifies every ADR this touches.

## Context

### What the two checks report

ADR-0277 §2 added two record checks to `scripts/check_citations.py`. Measured on
`main` at `d2c25133` with the shipped implementation (`scripts/clauses.py`), both
reports are mostly noise.

**The repeated-clause check** (ADR-0277 §2:6) finds **47 sets** of equal marked
clauses across ADRs, **117 clauses** in all, and reports every one of them. Read set
by set, they are three different things:

- **24 sets are quotations.** A later ADR shows an earlier ADR's ruling to argue
  from it and keeps the token. 22 of them stand in the later ADR's Context
  (ADR-0131 quoting ADR-0124 §10 and ADR-0094 §2 is the case ADR-0277's Context
  names). Two stand in a Decision section, each introduced by a sentence naming its
  source: ADR-0211 §5:3 ("what ADR-0176 §8 already ruled") and ADR-0214 §7:1 ("The
  clause reads:" under a paragraph naming ADR-0159 §4).
- **19 sets are boilerplate** each ADR states as its own ruling. Examples are
  "`PROTOCOL_VERSION` does not move for this change." (ADR-0211 §8:2, ADR-0213
  §11:2, ADR-0221 §8:3), the "settles nothing about the following" opener of a
  deferral section (18 ADRs across three wordings), and the "decides no
  `core/protocols.py`" sentence (six ADRs).
- **4 sets are restatements** that a sibling or superseding ADR marks as its own.
  ADR-0246 §2 ("What still binds, by name") restates three clauses of ADR-0245, and
  ADR-0255 §13 carries ADR-0253 §3's rule under the heading "Q4's rule, carried and
  not discharged".

So of the 117 reported clauses, 24 are the quoting halves the check exists to
catch. The other 93 are either the rulings being quoted (24) or wording that is
nobody's quotation (69). The report cannot be read. The forward cost is worse:
the next ADR that writes "`PROTOCOL_VERSION` does not move for this change." fails
the gate at Tier 1 though it quotes nobody, and the failure message says "a
quotation of another ADR's clause carries no **Normative.** token", which describes
a defect it does not have.

**The stale-note check** (ADR-0277 §2:4) reports **12** header notes that say an ADR
"remains Proposed" after that ADR was ratified. For nine of them, #2560 has already
appended a dated correcting note in the same header, of one shape: "ADR-0275 was
ratified on 2026-09-18 (`fb072c9a`), so the scoped replacements recorded by the
ADR-0275 note above took effect then". ADRs are append-only (ADR-0001), so the stale
note stays in the file, and a check that ignores the correction reports it forever.
It is permanent noise.

The three uncorrected notes at `d2c25133` were real. ADR-0212's and ADR-0237's
ADR-0275 notes wrap the phrase across a line, which is why #2555's line search
missed them, and `ce760137` has since appended the same correcting note to both
(#2562). ADR-0274 carries two stale notes, one naming ADR-0275 and one naming
ADR-0276, and its correcting note names ADR-0275 alone (#2569).

### What was measured

Each candidate test below was run over the 117 clauses at `d2c25133`. A test selects
a clause of an equal set. "Quoting" counts the 24 quoting halves, and "other" counts
everything else it selected.

| Test | Selected | Quoting | Other | Quoting missed |
| --- | --- | --- | --- | --- |
| Every member (ADR-0277 §2:6 as written) | 117 | 24 | 93 | 0 |
| The clause's own text names an ADR it equals | 0 | 0 | 0 | 24 |
| The clause stands outside its ADR's `## Decision` | 22 | 22 | 0 | 2 |
| The paragraph above names an ADR it equals | 19 | 17 | 2 | 7 |
| The same, where that paragraph is not a block quote | 17 | 17 | 0 | 7 |
| The same, where that paragraph also ends in a colon | 16 | 16 | 0 | 8 |
| Outside `## Decision`, or a colon-ended prose paragraph above names it | 24 | 24 | 0 | 0 |

The zeros in "Other" on the last three rows hold for the corpus as it stands and
do not carry to the next ADR. The paragraphs below say why, and why §1 takes the
third row alone.

The clause text never names its source, because a verbatim quotation repeats a
ruling that did not name itself. The section is the strongest single signal. Every
one of the corpus's 34 marks outside a Decision section stands in Context or
Consequences, and every repeated one is a quotation. It misses the two
Decision-section quotations.

The paragraph above can catch those two, but no form of it measured here is safe
for the next ADR. Read over any paragraph, it also selects ADR-0242 §2:9 and
ADR-0246 §10:5, because the paragraph above each is a neighbouring mark that
happens to cite the ADR it equals. Excluding a block-quote paragraph removes both.
It does not remove the case a new ADR can write, because a paragraph can name an
ADR in passing: "ADR-0211 changes planning; this change only adjusts local log
formatting." above a new ADR's "`PROTOCOL_VERSION` does not move for this change."
names an ADR whose clause that sentence equals, and quotes nothing. Requiring the
paragraph to end in a colon, as both Decision-section quotations do, does not
close it either: "ADR-0211 changes planning. For this change to local logging we
decide:" ends in a colon and introduces the new ADR's own ruling. Each tighter
form admits a new ordinary sentence that fails it, because whether a paragraph
attributes the clause that follows to another ADR is a reading, and ADR-0088 §6
has the checker adjudicate no reading.

On the stale notes, "a later header list item that carries a date and says the
same ADR `was ratified`" passes the nine #2560 corrected. At `d2c25133` it still
reports the three it did not correct, including ADR-0274's ADR-0276 note, whose
neighbour corrects only ADR-0275. At `ce760137` it also passes #2562's two notes
and reports ADR-0274's alone. The repeated-clause figures are the same at both.

## Decision

### 1. A repeated clause is a finding where it reads as a quotation

> **Normative.** A marked clause whose text, normalised as ADR-0277 §2:6 normalises
> it, equals a marked clause of another ADR is a finding only when it stands outside
> its own ADR's `## Decision` section.

> **Normative.** The clause that stands outside its `## Decision` section is the
> finding. The clause it equals is not reported for that equality unless it too
> stands outside its own ADR's `## Decision` section.

> **Normative.** A repeated clause selected by this section is a Tier 1 finding
> when it stands in an ADR numbered above 0277 and a Tier 2 finding in any other
> ADR.

> **Normative.** An equal clause standing inside its ADR's `## Decision` section is
> not a finding at any tier. The report states how many such clauses it passed, and
> lists none of them.

> **Normative.** Each repeated-clause finding names the clauses it equals and the
> level-2 section it stands in.

**Why the section and nothing else.** A ruling an ADR makes belongs in its Decision
section, and boilerplate is a ruling each ADR makes for itself. A mark in Context or
Consequences is either a quotation or a ruling out of place, and one that repeats
another ADR's ruling word for word is a quotation in every case the corpus holds.
Inside a Decision section the check cannot tell a quotation from a restatement
without reading the prose around it, so it passes both. That misses two quotations
the corpus has and fails no sentence an ADR states as its own, which is the
direction ADR-0088 §6 chooses ("A miss is benign; a false report is not").

### 2. A corrected stale note is recorded and not reported

> **Normative.** A header note that ADR-0277 §2:4 would report is **corrected**
> when a later list item of the same header stands below it, carries a
> `YYYY-MM-DD` date on its first line, and writes `ADR-NNNN was ratified` for the
> number the stale note names. The words follow the number directly, and the
> whitespace between them may cross a line break.

> **Normative.** A corrected note is not a finding. The report states how many
> notes it passed as corrected, and lists none of them.

**Why the correction lives in the ADR and not in the checker.** ADR-0070 §1's dated
note is how the corpus already records that a sentence of a ratified ADR went stale,
and #2560 used it. Recognising that note keeps the record in the file, where a
reader meets it a few lines below the stale sentence, and lets the report shrink to
what nobody has recorded yet.

### 3. What this leaves as it was

> **Normative.** No lane reads §1's narrower selection as permitting a marked
> quotation that §1 does not select. ADR-0277 §3's second clause binds every
> quotation of another ADR's marked clause, wherever it stands.

The check is narrower than the rule, by design. A marked quotation in a Decision
section passes the check, as ADR-0211 §5:3 and ADR-0214 §7:1 would, and ADR-0277 §3
still forbids it. That is ADR-0088 §6's benign miss.

Also unchanged: ADR-0277 §2's normalisation; its split at ADR-0277 between failing
and reported; the stale-note check's Tier 2 in every ADR; the marks check; and §3's
rule that a header note written onto an earlier ADR does not state the writing
ADR's status.

### 4. The work order

> **Normative.** `scripts/check_citations.py` implements §1 and §2, and tests
> under `tests/scripts/` cover at least: a quotation in Context of an ADR above
> 0277 (Tier 1, and the clause it equals not reported); the same sentence in the
> Decision sections of two ADRs above 0277 (no finding, and counted as passed); a
> Decision-section clause equal to another ADR's, under a colon-ended paragraph
> naming that ADR (no finding); a corrected note (counted, not listed); and a
> correcting note naming a different ADR (the stale note still reported).

> **Normative.** `CONTRIBUTING.md` → "Cite in form, and mark what binds" and the
> guidance comment in `docs/adr/template.md` describe the repeated-clause check and
> the stale-note check as §1 and §2 decide them, citing this ADR.

All of it is one implementing lane, dispatched after this ADR merges.

### 5. This ADR classified under ADR-0070 §1 and ADR-0082 §1

- **ADR-0277** is **partially superseded**. A reader holding it alone would fail,
  at Tier 1, a new ADR that restates boilerplate, and would report every member of
  an equal set. That is ADR-0070 §1's test, so §2:6 is replaced in its selection
  and in which member it reports. §2:4 is over-wide in the same way for a note
  already corrected. Its Status line and a dated header note record this. Its prose
  argument for splitting the checks at ADR-0277 stays true, and so does its
  Consequences line that a new ADR marking a quotation fails the gate, for every
  quotation §1 selects.
- **ADR-0088** is not touched. Its header note records the checks ADR-0277 added;
  this ADR narrows ADR-0277's text and no sentence of ADR-0088. A reader reaches
  the narrowing through ADR-0277's Status line, which is ADR-0070 §4's consumer
  rule.
- **ADR-0089** and **ADR-0082** are not touched. What a mark is and when a record
  is owed are unchanged, and the note this ADR writes onto ADR-0277 follows
  ADR-0277 §3's first clause.

## Consequences

- The repeated-clause report falls from 117 clauses to 22, every one a quotation.
  The stale-note report falls from 12 notes to 1 at `ce760137`: ADR-0274's
  ADR-0276 note, which has no correcting note (#2569).
- A new ADR can state "`PROTOCOL_VERSION` does not move for this change." or any
  other sentence the corpus repeats on purpose, word for word, in its Decision
  section.
- A new ADR that marks a quotation in its Context still fails the gate. One that
  marks a quotation in its Decision section passes the check and breaks ADR-0277
  §3's rule, which review enforces there as it did before ADR-0277.
- A restatement that a superseding ADR marks as its own, as ADR-0246 §2 does, is
  not selected. Whether such a restatement is a quotation under ADR-0277 §3 is not
  decided here.
- Revisit if marked quotations in Decision sections recur in new ADRs, which would
  make the miss worth a mechanically explicit quotation form, or if a clause outside
  a Decision section is found repeating another ADR's ruling without quoting it.

## Alternatives considered

- **Tier 2 for every ADR.** This was the fallback if no test separated quotations
  from boilerplate. The section test does, with no false report measured, and a
  117-line report goes unread.
- **A list of permitted boilerplate sentences.** Each new house phrase would fail
  first and be listed second, and the list would be a second statement of the
  corpus's wording to maintain.
- **A lead-in arm beside the section test**, in any of the three forms measured
  above: the paragraph above names the equal ADR, the same excluding block quotes,
  or the same ending in a colon. Each catches the two Decision-section quotations,
  and each fails an ordinary sentence a new ADR may write above its own
  boilerplate, as the Context shows. That is the false report this ADR exists to
  remove.
- **A required attribution form for quotations**, such as a fixed phrase before
  each one. It would make the Decision-section miss checkable, but it is a new
  authoring rule for a miss the corpus shows twice. It is left to the
  revisit condition in Consequences.
- **Requiring a stale note to be rewritten.** A ratified header note may not be
  edited in place (ADR-0001), so the correcting note is the only record available.
- **Dropping the stale-note check.** It found three stale notes that nobody had
  found by hand, so it earns its place once its corrected entries stop being
  reported.
