# Checking the ADR record, and naming one ruling

**The question.** How do we catch an ADR record that has drifted — two notes
disagreeing, a ratified ADR still called pending, an ADR with no rulings — and how
does a reader cite one ruling rather than a whole section?

## Why now

The owner revisited #597 on 2026-09-25 and ran a pre-registered pilot (#2553). The
pilot tested moving authority to rewritable per-area design docs, and that was
**dropped**: an agent answering from the ADRs alone was more accurate than one
answering from the design doc. So agents can *find* things in the ADRs. What the
pilot and the surveys behind it showed instead is that the **record drifts and
nothing notices**:

- In about **54** ADRs the `- Status:` line and the dated header notes disagree
  about which later ADRs amended them (ADR-0029's Status names only ADR-0192; its
  notes record amendments by ADR-0031, 0032, 0034 and 0039). The figure comes from a heuristic parse on 2026-09-25;
  the check below gives the exact one.
- Header notes in ADR-0274 and ADR-0275 still call ADR-0275 and ADR-0276
  "Proposed" after both were ratified (#2555). The pilot's answer key singled this
  out as a trap.
- ADR-0092 is the one ADR after ADR-0089 with no marked rulings, which ADR-0089
  requires of every later ADR.
- ADR-0131 marks quotations of ADR-0124 and ADR-0094 as its own rulings (#2556), a
  second statement of the same obligation — the drift ADR-0089 exists to prevent.
- `just citations` reports **zero** liveness findings over all of this, because its
  liveness test reads only the 16 column-0 `Supersedes` records.

The #597 risk — a missed obligation silently stops binding — is live *inside* the
current regime. These are all mechanical, so a checker can find them.

The pilot also produced one tool worth keeping: an identifier for **one marked
ruling**, `ADR-0094 §5:2`. It addressed all 844 rulings of 15 ADRs without a
collision.

## The baseline

- No wiki page describes the ADR process; nothing on the wiki changes.
- **ADR-0088** — §1(a) the decision-citation form; §6 the two tiers, and its
  refusal to check section numbers "until a mechanically distinct scope-reference
  form exists"; §9's declines.
- **ADR-0089** — §2 the mark's grammar; §3 marked clauses are the whole
  obligation; §5 forward-only.
- **ADR-0257** — labelled marks.
- **ADR-0070** §4 (the status vocabulary) and **ADR-0082** §1 (reciprocal records),
  which the checks read but do not change.
- `scripts/check_citations.py`, `scripts/adr_status.py`,
  `tests/scripts/test_adr_citations_corpus.py`, `scripts/brief_check.py`.

## The change

### 1. A clause identifier

`ADR-NNNN §S:k` names the *k*-th marked clause (ADR-0089 §2, including ADR-0257's
labelled forms) under section *S* of ADR-NNNN, counted from 1 in file order.

- *S* is the number of the nearest numbered heading above the clause (`5`, `10a`),
  or the first word of the nearest unnumbered top-level heading (`Context`,
  `Consequences`). Deeper unnumbered headings do not start a section: ADR-0094's
  "#### The custody handoff is deferred…" stays inside §8.
- A range is `§S:1-3`. The existing forms `ADR-NNNN §S` and `§§3–5` are unchanged.
- **It is stable.** ADR-0089 §5 forbids adding a mark to a ratified ADR, and a
  ratified body is append-only, so ordinals never move once an ADR is `Accepted`.
  Header notes sit above the first section and do not shift them. A `Proposed`
  ADR's ordinals can still move; citing one is at the citer's risk until it is
  ratified.
- **It is mechanically distinct.** ADR-0088 §6 passes section numbers silently
  because "ADR-0076 §9's obligation set" may name the *citing* ADR's §9. The `:k`
  suffix removes that ambiguity: it only means "the k-th ruling of the ADR just
  named". This is the scope-reference form §6 was waiting for.

Where it is used: ADR text, issues, review findings, dispatch briefs, and — most
usefully — **supersession records**, which today say things like "§5's closing
paragraph, as it reaches…" and could name the exact ruling replaced.

### 2. The checks

All inside `check_citations.py`, so the gate keeps five steps (ADR-0088's
precedent).

| Check | Finds | Today |
| --- | --- | --- |
| **Clause citation resolves** | `ADR-NNNN §S:k` naming a clause that does not exist | new form, 0 uses |
| **Status and notes agree** | an amender named in a dated header note (`Partially superseded: <date> by ADR-X`, `Amended: <date> by ADR-X`) but not on the Status line, or the reverse | ~54 ADRs |
| **No stale pending note** | a header note saying ADR-X "remains Proposed" when ADR-X's Status is not `Proposed` | 2 ADRs (#2555) |
| **A marked ADR has marks** | an ADR numbered 0089 or later, not `Withdrawn`, with no marked clause | 1 ADR (0092) |
| **A quotation is not a mark** | a marked clause whose text repeats another ADR's marked clause verbatim (after whitespace and `>` normalisation) | 1 ADR (0131, #2556) |

The Status/notes check applies ADR-0070 §4's vocabulary as written: where §4 does
not require an amendment to appear on the Status line, its absence is not a
finding. Settling that reading for pre-ADR-0070 `Amended` notes is part of the
lane that builds the check.

**Tiers.** A clause citation that does not resolve has no legitimate
non-resolving case once the form is distinct, so it joins **Tier 1** and can fail
the gate. The other four start in **Tier 2** (reported in CI, never failing). Each
moves to Tier 1 when its backlog is zero, by a later one-line decision, so the
gate never turns red on arrival.

### 3. One authoring rule

A quotation of another ADR's ruling is written as a plain blockquote, **without**
the `**Normative.**` token. The quoting ADR owns only what it rules itself.

### 4. The backlog

One lane clears the Tier 2 findings with header-only records (ADR-0070 / ADR-0082
forms): the Status/notes disagreements, #2555, ADR-0092 (a note that it rules
nothing, or which of its sentences a later ADR marks), and #2556. Clause
identifiers are **not** back-filled into old records; they are used from now on,
and an old record is converted only when something next touches it.

## Options considered

- **Clause form.** `§5.2` reads naturally but looks like a subsection number, a
  meaning readers bring from every other document, and no ADR has subsections; `§5¶2` is unambiguous but hard to type; a global per-ADR ordinal
  (`ADR-0094 #17`) moves whenever a section gains a clause during drafting and hides
  where the clause is. `§S:k` keeps the section, which is what readers navigate by.
- **Fail immediately vs. report first.** Failing at once turns the gate red on some
  58 findings nobody introduced. Report-first matches ADR-0088's regression-guard
  stance: Tier 1 stays a guard against new defects.
- **A separate script** instead of `check_citations.py`. Rejected: the parser,
  the ADR loader and the CI reporting already exist there, and #588's reasoning
  for running inside `pytest` still holds.
- **Checking plain section numbers too.** Still declined, on ADR-0088 §6's own
  ground: the ambiguity is real for `§K`, and only the new form escapes it.

## What it leaves open

- **A generated "current state" view** of an ADR (each ruling annotated in force,
  replaced, or partly replaced), which becomes possible once supersession records
  name clauses. A follow-up, once there are enough clause-level records to render.
- **Making #597's fifth-amender trigger fire mechanically** (21 ADRs are past it)
  and consolidating by wholesale supersession.
- **An ADR length budget.** The median ADR is now 869 lines.
- **Partial supersession of a single clause** ("only as it reaches…") is still
  prose; the identifier names the clause, not the part of it.
- Whether `brief_check.py` should resolve clause identifiers in dispatch briefs
  (likely yes, cheaply, in the same lane).
