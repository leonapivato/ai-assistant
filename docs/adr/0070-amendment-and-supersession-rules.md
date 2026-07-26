# 70. Amendment and supersession rules for ADRs

- Status: Accepted
- Date: 2026-07-26
- Partially supersedes: ADR-0001 — its change-a-decision clause ("to change a
  past decision, write a new ADR that supersedes the old one and update the old
  one's status"); §2 below. ADR-0001's other decisions — ADRs in `docs/adr/`,
  one file per decision, sequential numbering, the Context/Decision/Consequences
  structure, and append-only — stand.
- Directs: `CONTRIBUTING.md`'s "Trivial ADRs" wording (ratified by ADR-0003; §5
  below) and `docs/adr/template.md`'s status vocabulary (§4 below).

## Context

The ADR process runs on a rule with an undecided edge, surfaced by three issues.

**#65 — may an ADR be amended in place, and when?** ADR-0001 says ADRs are
append-only: "to change a past decision, write a new ADR that supersedes the old
one and update the old one's status." It names no amendment mechanism and no
exception. `CONTRIBUTING.md` says "Trivial ADRs (amendments, status changes,
supersedes) skip both the separate PR and the review," naming amendments as a
first-class category. Practice ran ahead of both — ADR-0004 §2 carries an
in-place amendment (2026-07-19) made before any mechanism was ratified, which
ADR-0017 §5 later found retroactively irregular (#71).

ADR-0017 §5 already reconciled the two documents on **authority**:
`CONTRIBUTING.md`'s line "is about review cost … not authority to change a
decision in place," it "never claimed the power ADR-0001 reserves, so there is no
conflict between the documents." This ADR does not reopen that finding. What
ADR-0017 §5 left open — and what #65 turns on — is the **mechanism** itself:
neither document defines a *permitted* in-place amendment for a change that
decides nothing, nor states where the line between an amendment and a
supersession falls. ADR-0070 extends the rule to supply both, and aligns the two
documents' wording to it, rather than resolving a contradiction ADR-0017 §5
already showed does not exist.

**#87 — the status vocabulary has no partial form.** `docs/adr/template.md`
defines `Proposed | Accepted | Superseded by ADR-XXXX`; all three assume
supersession is total. ADR-0004 is only partly superseded by ADR-0017 (its §2
egress clause), and neither `Accepted` (reads as fully current, so a reader or a
tool treats the replaced clause as live) nor `Superseded by ADR-0017` (reads as
wholly replaced by an ADR that touched one clause) is correct.

**#71 — a pre-existing in-place amendment.** ADR-0004 §2's configured-set
amendment (2026-07-19) was made in place under the looser reading, before any
strict rule existed. It is deliberately not to be retrofitted.

This ADR does not invent its answers. ADR-0017 already adopted both locally and
in force:

- **ADR-0017 §5** adopts the strict reading of ADR-0001 — "`CONTRIBUTING`'s
  'trivial ADRs … skip both the separate PR and the review' is about **review
  cost** … not authority to change a decision in place" — and, finding that its
  own change "ripples into two other ratified ADRs," writes itself as a
  superseding ADR rather than an amendment.
- **ADR-0017 §7** records a `Partially superseded` status token with the
  supersession named and the replaced scope in parentheses, "following the
  precedent ADR-0018 set for ADR-0016," and flags its weakness — "anything
  matching a leading `Accepted` misses the qualifier" — as #87's to settle
  repo-wide.

This ADR ratifies both canonically — into ADR-0001, where the supersession rule
lives, and into the template — so they stop being local to one ADR. It
generalises an already-tested local decision (the pattern ADR-0016/0018 and
ADR-0004/0017 established) rather than proposing an untried one.

## Decision

### 1. The amend-vs-supersede test

**An ADR may be amended in place only when the amendment changes no decision.**
The amendment reconciles the ADR with its own text — an internal contradiction,
a stale phrase, a broken cross-reference — or with a fact that postdates it, such
that a reader acting on the ADR would act **identically** before and after.

**Any change to what was decided requires a new ADR that supersedes the old one**
— wholly, or partially (§3). A change to what was decided is anything a reader
would act on differently.

The line is the **decision**, not the size of the edit, not its review cost, and
not whether it is "trivial." A one-word edit that reverses a decision is a
supersession; a paragraph that only restates the existing decision more clearly
is an amendment.

**A permitted amendment is append-only in mechanism, too.** It is recorded as an
**appended, dated note** (or dated sub-section); ratified decision text — the
Context, Decision and Consequences — is never rewritten. In-place edits to the
header lines are permitted only where they change no decision (§1's test applied
to the Status field and header themselves):

- **ratifying** an ADR — `Proposed` → `Accepted`, which finalises the current
  decision rather than changing a past one;
- **recording a supersession that has landed** on the Status line (ADR-0001
  already requires this). This presupposes the superseding ADR *exists*: flipping
  a live decision to `Superseded` with no such ADR is not a status change but an
  unrecorded decision change, and is not permitted;
- **correcting a Status line to match what actually landed** — repointing a
  broken or mistyped supersession reference to the ADR that in fact superseded the
  clause, or restoring `Accepted` where a marked supersession never landed. This
  changes no decision; it makes the Status field accurate;
- adding a **dated header note**.

These bound the append-only *form* of an edit, not the review a decision needs.
A substantive contract ADR is still reviewed while `Proposed` and ratified only
after (ADR-0015 §5; `CONTRIBUTING.md`, "Contract ADRs land before their
implementation"); the ratifying edit records that review's outcome, it does not
replace it.

Append-only means an amendment *adds*; it does not overwrite. This is exactly how
ADR-0017 §7 operated: notes appended, no accepted text rewritten, one status line
edited.

This resolves #65. ADR-0001 is authoritative on the rule; `CONTRIBUTING.md` is
corrected to state the same test (§5), not a looser one.

### 2. How ADR-0070 changes ADR-0001 — and how it classifies its own change

ADR-0001 gave exactly one mechanism for changing a decision: total supersession.
This ADR replaces that with three — in-place amendment (§1), whole supersession,
and partial supersession (§3). A reader of ADR-0001 would now act differently:
they may amend where ADR-0001 admitted only supersession, and supersede
partially where ADR-0001 admitted only the total form.

Applying §1's own test to this very change: it **changes what ADR-0001 decided**
about how a decision is changed. It is therefore a supersession, not an
amendment. It is **partial** — only ADR-0001's change-a-decision clause is
replaced; everything else ADR-0001 decided stands. So this ADR obeys the rule it
sets: it partially supersedes ADR-0001 rather than amending it in place, and
edits ADR-0001 only where §1 permits — its Status line and an appended dated
header note. ADR-0001's Decision text is left legible and unrewritten, so the
prior rule stays readable as history beside the pointer to this one.

The append-only *principle* is not superseded — it is refined and kept. §1's
amendment mechanism is append-only in form (appended notes, no rewrites), so
ADRs remain append-only after this change; what changes is that "change a
decision" is no longer synonymous with "total supersession."

### 3. Partial supersession is a first-class form, not a discouraged one

When a later ADR replaces **part** of an earlier one, it partially supersedes it:
the named scope is replaced and the remainder stays accepted. The status form is
§4's.

#87 asks whether partial supersession should instead be **discouraged** in favour
of splitting the superseded clause into its own ADR that can later be wholly
superseded. We rule **no**:

- Retroactively, splitting a ratified ADR's clause into a separate file would
  rewrite and relocate ratified text — the append-only violation §1 exists to
  prevent — and is impractical besides.
- Prospectively, an author may keep a decision's separable concerns in separate
  ADRs where that is natural, but there is **no requirement to pre-split** in
  anticipation of a future partial supersession. A leading-token status naming
  the exact scope (§4) makes partial supersession legible enough that the split
  buys nothing over it.

So partial supersession is the sanctioned tool when a later ADR replaces part of
an earlier one, decided once here rather than re-argued per case.

### 4. The status vocabulary

`docs/adr/template.md` gains the partial form:

```
- Status: Proposed | Accepted | Superseded by ADR-XXXX | Partially superseded by ADR-XXXX (<scope>)
```

`Partially superseded by ADR-XXXX (<scope>)` means: ADR-XXXX replaces the named
scope of this ADR; the remainder of this ADR stays accepted.

**A canonical status is one physical line** — a leading token plus, for a partial
supersession, one or more `ADR-XXXX (<scope>)` pairs — so the value is read whole
without reconstructing wrapped continuations. That single-line rule is a going
-forward requirement; the multi-line status fields several ADRs already carry
(ADR-0003, ADR-0029, ADR-0038, ADR-0040, ADR-0065) are the exception the consumer
rule and issue #404 handle, not a licence to write new ones.

**Independent partial supersessions accumulate on the one line.** When a later
ADR replaces a *different* scope of the same ADR, its `ADR-XXXX (<scope>)` pair is
added — `Partially superseded by ADR-B (<scope-a>) and ADR-C (<scope-b>)` — each
pair naming exactly what that ADR replaced (ADR-0015 already carries two, by
ADR-0020 and ADR-0025). Adding the second pair is a §1 Status edit (recording a
supersession that landed) and it does **not** drop the first: replacing the whole
value would lose the earlier dead scope. This is why §3 needs no pre-split — a
decision with separately-superseded parts is representable in place, one line, one
leading token.

Where two pairs' scopes overlap — a later ADR replaces a subset of an
already-superseded clause — the **later, higher-numbered ADR governs the
overlap**, the same monotonic rule as the transitive walk above, so no
disjointness constraint is needed. This is an *interpretive reading rule*, not a
coverage computation: scopes are free-form pointers (above), so a tool does not
decide containment — it surfaces the pairs and defers each to its ADR, and the
later ADR, narrowing an already-superseded clause, says so in its own text. The
precedence rule tells a *reader* which pair wins when both name the same clause.

Two properties are load-bearing, both from ADR-0017 §7:

- **The supersession leads; `Accepted` is dropped.** So a filter that
  prefix-matches `Accepted` cannot silently read a partially-superseded ADR as
  fully current — the exact failure #87 names. "Partially" already carries that
  the remainder is live, so no leading `Accepted` is needed; the record is its own
  scope-bearing state, not plain `Accepted` (the consumer rule below).
- **The scope names exactly what was replaced.** It is a specific, human-legible
  clause reference — a section number where the ADR is sectioned (ADR-0004's
  `§2's egress clause`), else a named clause (ADR-0001's `the change-a-decision
  mechanism`) — required and specific, not a gesture. It is a **pointer, not a
  machine-resolvable anchor**: the authoritative extent of what was replaced is
  stated by the superseding ADR itself (ADR-0017 §7 stated ADR-0004's; ADR-0070
  §2 and ADR-0001's own header note state ADR-0001's), and that is what a consumer
  defers the scope to. No stable-identifier scheme is imposed — the corpus's
  free-form clause labels are sufficient signal, and imposing anchors
  retroactively on unsectioned ADRs like ADR-0001 is neither possible nor needed.

ADR-0001 is where supersession rules live, so it states the partial form
alongside the total one (via this ADR's §2 pointer and its own header note); the
template carries the vocabulary itself.

**Existing status lines are not retrofitted.** Several accepted ADRs already
carry the older `Accepted, <qualifier> …` shape adopted before this ADR —
`Accepted, partially superseded …` (ADR-0002, ADR-0003, ADR-0004, ADR-0014,
ADR-0015, ADR-0016) and `Accepted, § … amended/discharged/narrowed …`
(ADR-0038, ADR-0040). Reformatting a ratified status line to the new
leading-token form is a forward-only convention, not a licence to rewrite settled
records — the same reasoning as #71 (§Consequences). New partial supersessions
use the leading-token form; the existing ones stand.

**Partial supersession is a distinct, scope-bearing state; a consumer must not
collapse it.** The canonical vocabulary is §4's — `Proposed | Accepted |
Superseded by ADR-XXXX | Partially superseded by ADR-XXXX (<scope>)`.
`Partially superseded` is neither `Accepted` (which would hide the replaced
scope — #87's failure) nor whole `Superseded` (which would hide the live
remainder): the named scope is replaced by ADR-XXXX and everything else stays
accepted. A consumer that classifies liveness must therefore represent **both**
parts — defer the named scope to ADR-XXXX, keep the remainder live — rather than
force the record into a binary live/dead bucket or drop it from a live-ADR
collection (which would lose rules like ADR-0001's sequential numbering and
append-only history). Under §1 an amendment is an appended dated note that changes
no decision, so it is not a status token and never bears on this read. Two
concrete collapses the whole-line read rules out:

- **Prefix-matching `Accepted`.** The leading-token form keeps a
  `status.startswith("Accepted")` filter from reading a partial supersession as
  fully current; the grandfathered `Accepted, partially superseded …` forms carry
  the token *after* `Accepted`, so a consumer scans the whole line. Recognising
  the partial state is the goal — not dropping the record, which would lose its
  live remainder.
- **Trusting a legacy qualifier's word.** A pre-ADR-0070 line may carry a
  qualifier after `Accepted`, and it falls into one of two cases. **If it names a
  later ADR** — `amended by`, `narrowed by`, `discharged by`, `retired by
  ADR-XXXX` — the change came from another decision and the word is not a
  reliable liveness signal (ADR-0040's `§§3/5a/5b amended by ADR-0045` names
  clauses ADR-0045 replaced), so a consumer **resolves it against the ADR it
  names**. **If it names no ADR** — a self-correction such as ADR-0065's `§4
  amended 2026-07-25 (its ModelProvider row was false)` — it is an amendment in
  §1's sense: it reconciles the ADR with a fact and changes no decision, so the
  ADR stays fully live and there is nothing to resolve.

**Supersession resolves transitively to the terminal live rule.** A consumer that
defers a scope to ADR-B follows ADR-B's own status onward — if ADR-B is itself
superseded by ADR-C, the live rule is ADR-C's. The walk terminates and cannot
cycle: an ADR is only ever superseded by a *later*, higher-numbered ADR (ADR-0001,
sequential numbering), so each hop strictly increases the number. A pointer to a
nonexistent ADR is a broken cross-reference: it is corrected in place to the ADR
that actually superseded the clause, or to `Accepted` if none did (a §1 Status
correction — it changes no decision), never treated as a liveness state.

That is why the legacy lines need no retrofit: a consumer that reads the whole
Status **field** — all its physical lines, since a legacy value may wrap — treats
a partial supersession as its own scope-bearing state, resolves a qualifier that
names a later ADR against it, and takes one that names none as a no-decision
self-amendment reaches the right answer on every shape in the corpus. New records
carry a one-line status (above), so only the enumerated legacy fields wrap, and
folding those is issue #404's — a reader that stops at the first physical line
misses a continuation qualifier.

Today nothing classifies ADR liveness from status: the sole status consumer,
`scripts/project_status.py`, only *displays* it, and even that display stops at
the first physical line (issue #404). Because it classifies nothing, no liveness
decision is wrong today; this rule binds any liveness-classifying consumer added
later, which must read the whole field.

### 5. Reconciling `CONTRIBUTING.md`

`CONTRIBUTING.md` is ratified by ADR-0003, so an ADR outranks it and may direct
its correction. Its "Trivial ADRs" paragraph is rewritten to state §1's test
rather than merely list "amendments" as a permitted category: it keeps the
review-cost point (already correct, from ADR-0017 §5), points at §1 for **when**
an in-place amendment is permitted (no decision change, recorded as an appended
dated note), and names partial supersession and its scoped status. It states the
same rule as §1 — not a looser one — so the two documents agree.

## Consequences

- **The ADR-0001 / `CONTRIBUTING.md` edge is closed.** ADR-0017 §5 already
  reconciled the two on authority (no conflict; the trivial-ADR line is review
  cost only); this ADR supplies the in-place amendment mechanism neither
  previously defined, bounded by §1's test and append-only in form, and aligns
  both documents' wording to it. ADR-0001 stays authoritative on append-only and
  the change-a-decision mechanism (as partially superseded by this ADR);
  `CONTRIBUTING.md` states the same test and points here.
- **A citable line now exists for a recurring judgement.** "Does this change what
  was decided?" decides amend vs supersede at each case, without a size or
  review-cost heuristic to game.
- **Partial supersession is canonical.** The template carries the form; ADR-0001
  states it; splitting-into-own-ADR is explicitly not required (§3).
- **#71 — ADR-0004 §2's configured-set amendment is recorded and left as-is.** It
  predates this ADR's test and was made in place under the looser reading. It is
  **not** retrofitted: converting a merged, ratified decision to satisfy a rule
  adopted after it is the append-only violation the rule exists to prevent,
  pointed backwards (ADR-0017 §5 draws the same line; the amendment sits on the
  editorial side of it). It is **not precedent** for the next in-place decision
  change — §1 governs those now. A one-line dated note is added to ADR-0004's
  header saying it predates this rule, so a reader does not mistake it for
  precedent; under §1 that annotation is itself a permitted amendment — it is an
  appended dated note and changes no decision.
- **Existing `Accepted, partially superseded …` status lines are grandfathered**
  (§4), consistent with the #71 reasoning: forward-only, no retrofit of ratified
  records. ADR-0003, ADR-0004 and ADR-0016 keep their current status shape.
- **This ADR is its own smallest worked example.** It partially supersedes
  ADR-0001 (a decision change), amends ADR-0004's header (no decision change),
  and directs `CONTRIBUTING.md` and the template — each classified under §1's
  test, a self-consistency check the architecture review is expected to run.
- Issues #65 and #87 are closed by this ADR; #71 is recorded here and stays open
  only as the annotated record it asks for.
