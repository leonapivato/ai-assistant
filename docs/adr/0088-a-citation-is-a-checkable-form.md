# 88. A citation is a checkable form: what an ADR may cite, and what "resolves" means

- Status: Proposed
- Date: 2026-08-01
- **This ADR supersedes nothing.** It supplies the rule ADR-0070 §4 reserved for
  "any liveness-classifying consumer added later", and it constrains the
  *authoring* form of a citation so that consumer has something to read. Under
  ADR-0082 §1 every addition it makes is a **stacked addition** — no sentence of
  an earlier ADR becomes false or over-wide — so no `Status` edit is owed on any
  earlier ADR, and §8 classifies every one of them. **No code changes with it**
  and no `core` surface is touched, so nothing here is behavioural until the
  check of §6 is built.

## Context

### Nothing in the gate reads an ADR

The gate has five steps — `ruff format`, `ruff check`, `mypy`, `lint-imports`,
`pytest`. **None of them opens a file under `docs/adr/`.** `mypy` and
`lint-imports` are scoped to `src/` (`.pre-commit-config.yaml` scopes
`import-linter` to `^(src/|pyproject\.toml$)`); `ruff` reads Python; `pytest`
reads `tests/`. The only hooks that touch a Markdown file at all are
`end-of-file-fixer` and `trailing-whitespace`, which read whitespace and not
content.

So a change whose entire diff is `docs/adr/**` runs a five-step gate that is
structurally incapable of failing on the only defect such a change can have.
#588 reports this from the inside: PR #584 ran the whole gate and 11,125 tests,
passed first time, and "none of them could have told me whether a sentence I
wrote about the code was true."

### The defect class is real, and it is measurable

Four instances were on the record when this ADR was opened. All four were
re-checked against the tree, and the check changed two of them:

- **#586, defect 2 — confirmed.** ADR-0086 §6 writes ``ConversationService``.
  `ConversationService` appears **nowhere** in `src/`; the class is
  `ConversationLifecycle`, in `orchestration/conversations.py`, and ADR-0086 §8
  names it correctly two hundred lines later.
- **#586, defect 1 — confirmed as a defect, but *not* of the kind #588 thinks.**
  §8 item 6 names `Engine._project` for a saving §6 argues about the listing.
  The defect is real — the listing goes through `Engine._summarise`, and the loop
  that issues one `get` per citation is `Engine._resolved_citations`. But
  `Engine._project` **resolves**: it is defined in `orchestration/engine.py`, and
  a second `_project` exists in `orchestration/questions.py`. #588 claims symbol
  resolution "catches … both halves of #586". It catches one. A name that
  resolves to the wrong object is invisible to a resolution check, and this is
  the sharpest limit on what §6's check can promise.
- **#572 — confirmed, and since fixed.** ADR-0085 §8c's `hub_max_frame_bytes`
  now exists, in `core/config.py`. The issue is correctly closed. It is retained
  here because it is the **false-positive story in its pure form**: the citation
  was wrong on the day it was written and right three days later, with the ADR
  text unchanged. A check that had run when ADR-0085 merged would have been
  correct to fire; the same check run today is correct to stay silent.
- **#593 — confirmed.** ADR-0085's Consequences state "**#281 is discharged**".
  `#281` is **open**.

### What a corpus-wide measurement says, and it is not what the brief for this ADR assumed

Every count below was taken over the 86 files in `docs/adr/` at
`origin/main` (numbered 1–87; **0035 is absent, and nothing cites it**).

**Cross-ADR section references are in excellent health.** There are **3,387**
`ADR-NNNN §K` references. **None** points at a missing ADR file. Two appear to
name a section their target does not define, and **both are the measuring
script's own false positive** — see below. This is the one citation kind that is
already effectively sound, and the decision below reflects that by asking least
of it.

**But a section is not a markdown heading, and assuming it is breaks the healthy
kind.** 72 ADRs number their sections with `### N.` headings. **Three do not:**
ADR-0015, ADR-0019 and ADR-0067 number theirs in **bold** (`**5. ADR numbers are
assigned at dispatch…**`). A further 12 have no numbered sections at all. The
measurement above only reported two failures because it happened to skip a target
whose extracted section set came back empty; **without that guard it reports 92
more, every one of them false** — 78 against `ADR-0015 §K` alone, which is the
most-cited clause set in the workflow (golden rule 5 is `ADR-0015 §5`), 12
against ADR-0019, and 2 into unsectioned ADRs.

That is the whole hazard of this ADR in one number. The citation kind that is
currently sound is the one a naively-built checker would damage most, and it
would do so with 92 confident, specific, false findings.

**Line-number citations are neither rare nor dying.** 16 ADRs carry the
`path.py:NNN` form, **219 occurrences**. They are not a legacy habit: ADR-0083
(17), ADR-0084 (18), ADR-0085 (40) and ADR-0087 (3) were written in the last
three days and carry 78 between them. **The premise that "no `:NNN`" is a
universally-followed unwritten convention is false**, and a rule ratified on that
premise would have been a rule nobody was following.

**Line numbers rot; the symbols beside them do not.** Of 142 backticked
`path.py:NNN` citations, 27 do not resolve even at file-and-line granularity —
11 name a file not present under `src/`, 16 point past the end of the file they
name. That understates it, because a line that still exists need not hold what
the citation says. ADR-0026's Context carries a ten-row table pairing a symbol
with a `file.py:line`. Checked against the tree today:

- **8 of the 10 line numbers point at unrelated text** — `ClockContextSource` at
  `context/sources.py:69` lands on `def _time_of_day(hour: int) -> TimeOfDay:`;
  `FakeMemoryStore` at `testing/memory.py:41` lands on an `import` statement;
  `InMemoryMemoryStore` at `memory/store.py:54` lands on a blank line.
- **All 10 symbol names still resolve**, each to exactly one definition in
  `src/`.

One table, one edit horizon: the half of each citation that was greppable
survived, and the half that was positional did not. That is the whole argument
of §5, and it is measured rather than asserted.

**A naive symbol check is mostly noise.** ADRs contain **687** distinct
backticked `CamelCase` tokens over 7,165 occurrences. **80 distinct tokens
(479 occurrences, 6.7%) resolve nowhere in `src/`** — which is what #588's first
check would flag. Reading the flags, almost none are code:

```text
Status x141   Accepted x65   MERGE x57   WITHDRAW x32   PROPOSAL x30
Date x7       HEAD x5        DTZ x5      Refs x3        LICENSE x2
```

These are ADR status vocabulary, enum *members*, a ruff rule code, a git ref and
a filename. `ConversationService` — the one true positive — appears three times
in that list of 479. And a further class is not noise but a scoping error in the
proposal: `ModelProviderContract`, `MemoryWriterContract` and `WriterFactory`
resolve fine, in **`tests/`**, because that is where conformance suites live
(`CONTRIBUTING.md`, "Adding a Protocol"). #588 says a symbol "should resolve
somewhere in `src/`". It must read `tests/` too.

The conclusion this drives is the load-bearing one: **the problem is not that
the checker is insufficiently clever, it is that nobody has said which tokens
are citations.** A check that must infer its own input set from backticks pays
479 false positives to find 3 defects. A check whose input set is *declared* pays
almost none. So the primary act of this ADR is to define the citation forms — §§1
and 2 — and only then to say what a checker does with them.

### The checker's trap, observed on the first attempt

The script that produced the 3,387-reference count above reported two failures,
both in ADR-0074, both of the shape "ADR-0076 §9, but ADR-0076 has no §9". Both
are false. ADR-0074's `Status` reads:

```text
Partially superseded by ADR-0076 (§9's `ConversationStore` obligation set and …)
```

The `§9` is **ADR-0074's own**, naming the scope ADR-0076 replaced — and ADR-0074
then repeats it in prose without the parentheses ("ADR-0076 §9's obligation
set"), where it becomes syntactically identical to a citation of ADR-0076's §9.
ADR-0070 §4 predicted exactly this and forbade the inference that produces it:
the scope text is "a **human-reading convention, not a parsing grammar**: no
consumer segments scope text or binds a scope to an ADR by delimiter."

This is worth recording because it is not a bug in one script. It is the general
shape of the hazard in §6: a checker that guesses at structure it was not given
reports confident, specific, wrong findings — the same failure mode
`docs/review/guide.md` records for review findings, arriving now from a tool that
looks more authoritative for being mechanical.

### The liveness question, and why the status line is not the answer

A quotation lifted from a **superseded** clause matches its source byte for byte.
Verbatim-match therefore yields identical confidence whether or not the clause is
dead, which makes it feel like verification while establishing nothing about
whether the cited rule still holds. #588 reports having made exactly this
mistake by hand on PR #584.

The brief for this ADR proposed that a liveness check reading the cited ADR's
`Status` line alone is unsound because ADR-0015 §5 merges a decision ADR as its
own PR while the supersession record goes on the *earlier* ADR, opening a window
in which the earlier ADR misreports itself. **The window is real; the reasoning
for it does not hold, and the distinction changes the rule.**

- **The window is real.** ADR-0086 landed 2026-07-31 as a single-file commit
  (`9dfa607`, one file, 681 insertions). The partial-supersession records it owed
  on ADR-0074 landed 2026-08-01, in a separate change. For roughly a day,
  ADR-0074's `Status` named ADR-0076 and ADR-0084 and not ADR-0086, while
  ADR-0086 §11 — merged, ratified — declared the supersession.
- **It is not structural.** Nothing forces two merges. ADR-0070 wrote its own
  file, ADR-0001's `Status`, ADR-0004's note, `CONTRIBUTING.md` and the template
  in **one commit** (`93a349f`). ADR-0082 §7 says the atomic pair is what closes
  this hazard in terms: §1's condition "is that the superseding ADR **exists**,
  not that it is ratified — the hazard §1 names is a `Status` line pointing at
  nothing, and **an atomic pair makes that unreachable**." ADR-0086 departed from
  an available practice; ADR-0015 §5 did not compel it to.
- **And ADR-0082 §1 is the wrong citation for it.** §1 governs where an
  **amendment** record goes. A supersession record on a `Status` line is
  ADR-0070 §1's third permitted header edit and ADR-0001's rule. On a
  leading-token line ADR-0082 §2 in fact puts the amendment record in the dated
  note and *not* on `Status` at all.

So the window is a contingency, not a law, and a rule resting on it would rest on
whether lanes keep making a particular mistake. The sound ground is older and
already ratified. **ADR-0070 §4 says the scope on a `Status` line is a pointer,
not the authority:**

> It is a **pointer, not a machine-resolvable anchor**: the authoritative extent
> of what was replaced is stated by the superseding ADR itself … and that is what
> a consumer defers the scope to.

A status-line-only check reads the pointer and never opens what it points at. It
is unsound on a corpus with no merge windows at all, for the same reason a
verbatim quotation check is unsound: it terminates its search one document short
of the authority. §4 also already binds the consumer this ADR anticipates —
"this rule binds any liveness-classifying consumer added later, which must read
the whole field" — and requires the transitive walk onward through the
superseding ADR's own status.

## Decision

### 1. Three citation forms, and a citation is only what is written in one

An ADR **cites** in exactly three kinds, and each has one canonical written form.
A reference not written in one of these forms is prose, not a citation, and
nothing in §6 checks it.

**(a) A decision citation** — `ADR-NNNN`, optionally followed by a section
reference `§K`, where `K` is a section number the target ADR defines, optionally
with a sub-letter (`§8c`) and optionally an item (`§8 item 6`). Multiple sections
may be joined (`§5/§6`, `§§3–5`). `NNNN` is four digits.

**(b) A code citation** — a backticked name that identifies something in the
repository:

- a module path, `` `memory/ingest.py` `` or `` `orchestration/engine.py` ``,
  written relative to `src/ai_assistant/` or `tests/`;
- a symbol, `` `ConversationLifecycle` ``, `` `MemoryStore.get_many` ``,
  `` `Provenance.evidence_elided` ``;
- the two joined, as prose pairing a symbol with the file that holds it.

**A code citation carries no line number** (§5).

**(c) A tracker citation** — `#NNN`, a GitHub issue or PR number.

**Backticks alone do not make a citation.** The corpus backticks status
vocabulary (`` `Accepted` ``), enum members (`` `MERGE` ``), tool codes
(`` `DTZ` ``), git refs (`` `HEAD` ``) and filenames (`` `LICENSE` ``) — 479
occurrences of tokens that resolve nowhere in `src/` and are not meant to. Form
(b) is a claim *about the repository*; the test for whether an author has made
one is whether they intended a reader to go and find it. Where that is genuinely
ambiguous, §6 resolves it in favour of silence, not of a finding.

### 2. What "resolves" means, per kind

**(a) A decision citation resolves** when `docs/adr/NNNN-*.md` exists **and**,
where a `§K` is given, that file defines a section numbered `K`. Nothing about
the ADR's status is part of resolution — that is liveness, and §4 keeps the two
apart deliberately.

**"Defines a section numbered K" is not "has a heading K", and this is
normative.** The corpus marks sections three ways and a checker must accept all
of them: a markdown heading (`### 5.`, 72 ADRs), a **bold** line (`**5. …**` —
ADR-0015, ADR-0019, ADR-0067), and not at all (12 ADRs, including ADR-0001 and
ADR-0003). **Where the cited ADR numbers no sections, a `§K` citation into it is
unresolvable by construction and is passed silently** under §6, never reported:
the citation is a pointer to a clause a reader will find by reading, and the
absence of a numbering scheme is not evidence that the clause is absent. A
checker built on the heading assumption alone reports 92 false defects against
`main` as it stands, 78 of them against `ADR-0015 §K`. No new ADR is required to
adopt a numbering shape, and none is retrofitted.

**(b) A code citation resolves** when the name it gives is found by an
exact-token search of `src/` **or** `tests/`. Both, not `src/` alone:
conformance suites and their factories live under `tests/` by
`CONTRIBUTING.md`'s "Adding a Protocol", and three of the corpus's apparently
unresolved symbols are exactly that. A dotted name resolves on its final
component; a module path resolves as a path.

**Resolution is not correctness.** `Engine._project` resolves and is still the
wrong symbol for the claim ADR-0086 §8 attaches to it (#586). §6 promises to
catch a name that points at *nothing*. It cannot catch a name that points at the
wrong thing, and this ADR does not pretend otherwise: that defect is found by
reading, and by review.

**(c) A tracker citation resolves** when the issue or PR exists. Additionally,
where the citing sentence makes a **state claim** about it — "`#NNN` tracks the
conversion", "**#281 is discharged**", "closed by `#NNN`" — the claim is checked
against the tracker's state, and a claim contradicted by that state is a defect.
A citation that merely *refers* (`Refs #537`, "raised as #473") makes no state
claim and is checked for existence only.

### 3. A citation to something not yet built is exempt, and the exemption is dated, not permanent

ADRs routinely name a type before it exists — that is what a contract ADR *is*
under ADR-0015 §5, which requires the decision to merge before anything
implements against it. `Provenance.evidence_elided` was fictional until ADR-0086
§4 landed; `hub_max_frame_bytes` was fictional when ADR-0085 §8c cited it and is
real now (#572).

So a code citation in an ADR whose `Status` is `Proposed`, or in a section the
ADR itself marks as the work it commissions, **is not checked**. The exemption
attaches to the ADR's state, not to an allowlist an author edits, because an
allowlist entry is one more citation nothing checks.

**Where an ADR is `Accepted` and its implementing change has merged, the
exemption is spent** and its code citations are checked normally. #572 is the
worked example in both directions: correct to fire on the day ADR-0085 merged,
correct to stay silent today, with no edit to ADR-0085 in between.

### 4. Liveness is in scope, is derived from both directions, and is reported rather than adjudicated

**Liveness is a distinct question from resolution and is answered separately.** A
decision citation to `ADR-NNNN §K` is **live** when §K has not been replaced. A
citation of a dead clause resolves perfectly and is still wrong, and verbatim
quotation establishes nothing about it (Context).

**Liveness is derived from both the earlier ADR and the later one, and
disagreement between them is the finding.** Concretely, for a citation of
`ADR-A §K`:

1. read `ADR-A`'s whole `Status` **field** — every physical line, since a legacy
   value may wrap (ADR-0070 §4) — and collect the `ADR-NNNN` targets after a
   leading `Partially superseded by`, plus any whole `Superseded by`;
2. read each **naming** ADR's own text, which ADR-0070 §4 makes the authority on
   extent;
3. follow the transitive walk ADR-0070 §4 requires, onward through each target's
   own status, which terminates because an ADR is only ever superseded by a
   higher-numbered one.

**Where the two directions disagree, that is the report** — a later ADR declaring
it supersedes a clause of `ADR-A` while `ADR-A`'s `Status` does not name it, or
the reverse. This is the check that would have surfaced the ADR-0074/ADR-0086
window on the day it opened, and it does not depend on that window being
structural: it is the direct consequence of §4's ruling that the `Status` scope
is a pointer and the superseding ADR is the authority. A checker that read only
the pointer would have believed ADR-0074's `Status` and been wrong; a lane that
trusted ADR-0086's own declaration was right.

**A liveness result is surfaced, never adjudicated.** ADR-0070 §4 is explicit
that scopes are free-form pointers and that "a tool does not decide containment —
it surfaces the pairs and defers each to its ADR". So the check reports *that a
cited ADR has a superseded scope and which ADRs to read*; it does not compute
whether `§K` falls inside a scope, and it does not fail a build on that ground.
Deciding whether the cited clause is the replaced one is a reading, and §6 keeps
readings out of the tool for the same reason ADR-0082 §6 declined a mechanical
`Status` cross-check: "a script that cannot make it would enforce the label this
ADR says does not control."

**And a section reference inside a supersession scope is not a citation of the
naming ADR.** ADR-0074's "ADR-0076 §9's obligation set" names ADR-0074's §9. This
is the collision recorded in Context; under §1 the scope is part of the `Status`
record, not a decision citation, and a checker that treats it as one reports a
false defect — as the script written for this ADR did, twice, on its first run.

### 5. A citation carries no line number

**A code citation names a symbol or a file; it does not name a line.** The
`path.py:NNN` form is not written in new ADR text.

The reason is measured, not stylistic. A line number is a positional reference
into a file that every later edit above it silently invalidates, and it fails
**silently** — the citation still looks well-formed and still points somewhere.
A symbol name fails **loudly**: it either resolves or it does not, which is
exactly the property §6 needs. ADR-0026's table is the controlled experiment,
one document with both halves written on the same day: 8 of 10 line numbers now
point at unrelated text, 10 of 10 symbols still resolve.

**This is forward-only and nothing is retrofitted.** 219 occurrences stand across
16 ADRs. Rewriting them would be an append-only violation pointed backwards, on
exactly the reasoning ADR-0070 §4 and #71 already settled for status lines:
"converting a merged, ratified decision to satisfy a rule adopted after it is the
append-only violation the rule exists to prevent." The existing line numbers are
also not *removed* from checking — under §2(b) the symbol beside them is checked
and the line number is ignored, so the corpus gets the benefit without an edit.

**Where a position genuinely must be conveyed**, name the enclosing symbol and,
if needed, quote the line. Both are stable under edits elsewhere in the file.

**This ADR's own Context quotes three of the rotted citations** — `sources.py:69`,
`testing/memory.py:41`, `memory/store.py:54` — because they are the evidence for
this section. Quoting a defect to demonstrate it is not committing it, and the
rule's own ADR is the one document guaranteed to contain what the rule forbids.
A checker will flag them; that is a known and accepted cost, recorded here so the
implementing lane recognises the hits rather than treating them as a corpus
defect.

### 6. What a checker may and may not report

This section binds the implementation lane; it does not write it.

**The input set is §1's forms, and the checker does not infer its own.** This is
the difference between 479 false positives and a usable check.

**The checker does not infer document structure either.** §2(a)'s three section
shapes are the worked example: the natural implementation — extract `###`
headings — is wrong on 92 citations, and wrong in the direction that discredits
the tool. Where a structural assumption is needed and the corpus does not
uniformly satisfy it, the assumption is not made and the citation is passed.

**Asymmetric failure handling. A miss is benign; a false report is not.** A
citation the checker cannot evaluate — an ambiguous token, a quotation it cannot
locate, a form it does not recognise — is **passed silently**. A missed defect
costs a reader a trip to the source document, which they could always have made.
A confident wrong finding costs the reader's trust in every other finding, and
`docs/review/guide.md` already records what a confidently-worded, specifically-
grounded, factually false finding does to a lane.

**A fragment is never reported as a whole.** Where a check verifies a quotation,
it either matches the **entire** quoted span or reports nothing. It must not
match a leading fragment and report the quotation verified. This is not
hypothetical at this corpus's ~80-column wrapping: most quotations span a line
break, so a naive substring search fails on the majority of them and a
"first line matched" relaxation would convert that benign miss into the one
dangerous outcome — a reader concluding a whole quotation is verbatim on evidence
covering its first clause.

**No check adjudicates a reading.** §4's liveness surfacing, the amend-versus-
supersede line (ADR-0070 §1) and whether a record is owed (ADR-0082 §1) are all
readings. ADR-0082 §6 declined a mechanical check on precisely this ground and
that ruling is untouched here.

**Where the check runs is not decided here** — gate step, pre-commit hook,
review-time tool or `just` recipe are all open, and the tradeoffs differ. What
is decided is that it reads `docs/adr/**`, that it is capable of failing, and
that a `docs/adr/**` change is no longer gated by five steps that cannot see it.

### 7. What this does not cover

- **Prose outside the repository.** PR descriptions, issue bodies and issue
  comments carry the same rotting citations — #588 records `ConversationService`
  propagating out of ADR-0086 into PR #584's description and a comment on #575 —
  and they are in no diff and reviewed by nothing. They are **out of scope**: a
  check over them has no commit to run on and no tree to be true against at any
  fixed moment. This is named rather than left silent so the implementation lane
  does not widen into it.
- **Docstrings and comments in `src/`.** #579's amplifying case — a quotation
  re-propagated into `core/protocols.py` where the next lane trusts it at one
  further remove — is real and is **not** covered. §1's forms are defined for ADR
  text. Extending them to `src/` docstrings is a further decision with its own
  cost, and bundling it here would put a rule on every docstring in the repository
  in an ADR nobody read for that.
- **Paraphrase.** A sentence restating a cited clause without quoting it is
  unreachable by any of this. ADR-0084's lane found one at round 27 —
  ADR-0077 §10 paraphrasing rather than quoting ADR-0042 §1 — and nothing
  proposed here would have found it.
- **Whether a resolved name is the *right* name** (§2(b)), and **whether a
  quoted clause supports the argument built on it**. Both are reading, and both
  stay with the author and the review.
- **Commit messages**, for the same reason as PR descriptions: `Refs: ADR-NNNN`
  trailers are checked by nothing here.

### 8. This ADR classified under ADR-0070 §1 and ADR-0082 §1, edit by edit

- **ADR-0070 — nothing owed.** §4 anticipated a liveness-classifying consumer and
  bound it in advance ("this rule binds any liveness-classifying consumer added
  later"). §4 above supplies that consumer's rule where §4 gave none; it
  contradicts no sentence of §4 and in fact rests on two of them — the pointer/
  authority distinction and the transitive walk. Under ADR-0082 §1 that is a
  **stacked addition**: "it is recorded in the ADR that makes it, and nowhere
  else." No `Status` edit and no dated note are owed on ADR-0070.
- **ADR-0082 — nothing owed.** §6's declining of a mechanical `Status`
  cross-check stands whole and is relied on rather than narrowed; §4 above is a
  *reporting* check, not the adjudicating one §6 refused. Nothing ADR-0082
  decided moves.
- **ADR-0026, ADR-0083, ADR-0084, ADR-0085 and the other twelve — nothing owed,
  and §5 says why.** The rule is forward-only. Their line numbers are
  grandfathered exactly as ADR-0070 §4 grandfathers legacy status lines, on #71's
  reasoning. No sentence of any of them becomes false: each still decided what it
  decided, and a stale positional pointer is not a decision.
- **ADR-0015, ADR-0027 — nothing owed.** Neither the contract-ADR sequencing nor
  the review floor is touched. `docs/adr/**` remains in ADR-0027 §3's floor and
  this ADR does not ask to change that.
- **`CONTRIBUTING.md` — an edit is owed and this ADR does not write it.** §1's
  forms and §5's no-line-number rule are authoring rules, and `CONTRIBUTING.md`
  is where authoring rules are stated for a reader who is not reading ADRs.
  ADR-0070 §5 is the precedent for an ADR directing that correction. It is filed
  as an issue rather than written here because this lane's fence is one file
  (Consequences).
- **This ADR's `Status`.** It ships `Proposed` and is reviewed while `Proposed`,
  then flipped to `Accepted` before merge (ADR-0015 §5; `CONTRIBUTING.md`,
  "Contract ADRs land before their implementation"). It touches no Protocol and
  no `core` type and decides no contract surface, so **adversarial is the required
  set** — the same reading ADR-0082 §5 recorded for itself.

### 9. Explicitly declined

- **Ratifying "no `:NNN`" as a codification of existing practice.** That was the
  proposed framing and the measurement refuses it: 219 occurrences across 16
  ADRs, 78 of them written in the last three days. §5 ratifies the rule on
  evidence of *rot* instead, which is a different and stronger argument, and it
  is honest that the corpus is being asked to change rather than to keep doing
  what it does.
- **A liveness check reading the cited ADR's `Status` line alone.** Unsound under
  ADR-0070 §4 — it reads the pointer and never the authority — independently of
  any merge window (Context).
- **Requiring the supersession record to land atomically with the superseding
  ADR.** It is available (ADR-0070's own commit), it is what ADR-0082 §7 relies
  on, and requiring it would have closed the ADR-0074/ADR-0086 window. It is
  declined anyway: §4's both-directions derivation makes the window *detectable*,
  which is this ADR's business, and mandating one commit shape for governance
  changes is a workflow decision with costs — a wave of records across many files
  in one change — that belong to whoever is paying them. Detection does not need
  the mandate; if the window recurs after detection exists, that is the ADR to
  write.
- **An allowlist for not-yet-built symbols.** §3 keys the exemption to the ADR's
  own `Status` instead. An allowlist is a hand-maintained file that decays
  exactly when it matters — ADR-0015 §4's finding about `WORKING.md`, in
  miniature — and it would be one more list of citations nothing checks.
- **Extending §1's forms to `src/` docstrings** (#579's amplifying half). §7
  records why: it is a bigger rule than this ADR was read for.
- **Verifying quotation text as a hard check.** §6 permits a quotation check but
  gives it the strictest failure handling in the ADR, and nothing here requires
  one to exist. Against paraphrase it is useless, and against wrapped text a
  naive one is worse than useless.

## Consequences

**Easier.**

- **A `docs/adr/**` change can fail.** The five-step gate's structural blind spot
  is named, and §6 gives the implementing lane a check whose input set is defined
  rather than inferred — the difference between 479 flags for 3 defects and a
  usable signal.
- **An author has one place to look.** Three forms, three definitions of
  "resolves", one rule about line numbers. The judgement that stays with the
  author is now a small and stated one: is this a claim about the repository?
- **Liveness has a method that is not verbatim-match.** The trap #588 walked into
  by hand on PR #584, and named precisely ("verbatim-match feels like verification
  and yields identical confidence whether or not the section is dead"), has a
  written answer that does not depend on any lane's diligence.
- **The corpus's healthiest citation kind is left alone, and protected from the
  check.** 3,387 decision citations, zero dangling files, zero real section
  misses. §2(a) asks almost nothing of them because nothing is wrong with them —
  and it names the three section shapes explicitly, which is what stops the
  implementing lane shipping a heading-only checker that reports 92 false defects
  against a healthy corpus.

**Harder.**

- **The corpus is asked to change.** Line numbers were being written three days
  ago and stop being written now. This is a real cost paid by authors, and §5
  pays it deliberately rather than pretending the convention already existed.
- **Two citation shapes coexist indefinitely.** New ADRs carry no `:NNN`; 16 older
  ones keep 219. A reader meets both, and §5's non-retrofit is what makes that
  permanent. The mitigation is that the *symbol* beside a legacy line number is
  checked under §2(b), so the old form degrades to the new one rather than to
  nothing.
- **The check will not catch the defect that started this.** `Engine._project`
  resolves. #586's first half — a name that points at the wrong object — is
  outside anything §6 can promise, and §2 says so plainly rather than letting the
  implementing lane discover it. Of the four known instances, §6 catches two
  (`ConversationService`, `#281 is discharged`), would have caught a third at the
  time (#572), and cannot catch the fourth.
- **A tracker check is only as good as the tracker.** §2(c) makes an ADR's state
  claim about an issue falsifiable, which also means an ADR can be made wrong by
  someone closing an issue. That is the correct direction — #588's defect 2 was
  exactly a claim that expired while its PR sat in review — but it means ADR text
  can go stale without anyone touching it.

**Follow-on.**

- **`CONTRIBUTING.md` owes §1's forms and §5's rule** in its ADR-authoring
  guidance, under ADR-0070 §5's precedent. Filed as an issue; not written here
  (§8).
- **#588 is the implementation issue and survives; #579 is reconciled into it.**
  They are one defect class seen at two radii. #588's three checks are §§2 and 4
  of this ADR, corrected in three places: symbol resolution must read `tests/` as
  well as `src/`, it does not catch #586's first half, and its exemption is keyed
  to ADR status rather than an allowlist. #579's distinctive half — quotation
  verification, and propagation into `src/` docstrings — is **declined here** (§7,
  §9) and its concern is met obliquely: §1's citable forms and §5's greppable
  symbols are what #579 itself proposed as the better instrument ("Cite
  `file:symbol`, not prose … A pointer to code is checkable by the gate in a way a
  quotation is not"). #579 should close, pointing here and at #588.
- **#586 and #593 are the two live defects §6 would catch.** Both remain open and
  both need a `docs/adr/**` amendment or a tracker action; neither is written by
  this lane, whose fence is this file.
- **Two further candidate defects surfaced by the measurement, unverified:**
  `ClassifiedToolError` and `UserProfile` are backticked in ADR text and resolve
  in neither `src/` nor `tests/`. They may be proposed-but-unbuilt types under §3
  or genuine instances. Filed for triage.

**Revisit when** the check of §6 has run over the whole corpus for the first
time. Its true-positive and false-positive counts against §1's forms are the only
real test of whether the forms were drawn in the right place, and they are
cheaply measurable once it exists. Revisit also **if** a defect of the
`Engine._project` kind — a resolving name attached to the wrong claim — recurs
often enough to be worth a different instrument, since §2 concedes that ground
outright.
