# 88. A citation is a checkable form: what an ADR may cite, and what "resolves" means

- Status: Partially superseded by ADR-0090 (§6's Tier 1 rule that a decision citation naming an absent ADR file always fails, as it applies to a number lying in a gap below the highest issued number)
- Date: 2026-08-01
- **This ADR supersedes nothing.** It supplies the rule ADR-0070 §4 reserved for
  "any liveness-classifying consumer added later", and it constrains the
  *authoring* form of a citation so that consumer has something to read. Under
  ADR-0082 §1 every addition it makes is a **stacked addition** — no sentence of
  an earlier ADR becomes false or over-wide — so no `Status` edit is owed on any
  earlier ADR, and §8 classifies every one of them. **No code changes with it**
  and no `core` surface is touched, so nothing here is behavioural until the
  check of §6 is built.
- Partially superseded: 2026-08-01 by ADR-0090 — **§6's Tier 1 fails a correct
  document, and three sentences of this ADR asserting that it does not are
  false.** ADR-0067 writes, in §1(a)'s canonical form, in prose and outside any
  fence, that a number between the two it ranges over was never issued. That
  number has no ADR file, because it was assigned and never written, so §6's
  Tier 1 reports it — and the sentence reporting it is correct. §6's premise,
  "ADRs are append-only so a file is never deleted", covers a *deleted* target
  and silently assumes every cited number was *issued*, which no rule in the
  corpus supplies (ADR-0015 §5 assigns a number at dispatch, and an abandoned
  assignment leaves a gap). Firing on it is the "false report" §6's own
  asymmetric failure handling calls the one dangerous outcome, and it is the
  shape §3 already conceded on the other side of the corpus — an append-only
  corpus correctly cites what is not in the tree.

  **Replaced**, one clause of §6: the Tier 1 rule for a decision citation naming
  an absent ADR file, *only* as it applies to a number that is absent from the
  issued set and below that set's maximum. ADR-0090 §1 passes such a citation
  silently; every other non-resolving decision citation still fails Tier 1,
  including one above the issued maximum. The rest of §6 stands whole — the
  tracker half of Tier 1, Tier 2, the silence on section references, the
  asymmetry rule and the input-set rules — and §3 is not reached.

  **Amended**, three stale phrases, recorded here and not rewritten (ADR-0070
  §1; the record is this note alone, because the `Status` line now carries a
  leading supersession token — ADR-0082 §2):

  1. Context's "0035 is absent, and nothing cites it". ADR-0067 cites it.
  2. §6's "The corpus's 3,387 decision citations pass today, so this is a
     regression guard rather than a backlog". One does not pass.
  3. Consequences' "It passes today, so it guards against regression rather than
     presenting a backlog" and "3,387 decision citations, zero dangling files,
     zero real section misses".

  The figure carries a smaller error of its own. **3,387 is Context's count of
  `ADR-NNNN §K` references**, and §6 and Consequences reuse it as the count of
  *decision citations* — a wider population, since §1(a) makes the `§K`
  optional. Measured at `123bdbc`, `scripts/check_citations.py` reports 5,885
  decision citations, of which 3,515 carry a `§K`. Context's own sentence about `ADR-NNNN §K`
  references — "**None** points at a missing ADR file" — is **not** among the
  errors: the citation that fails is written bare, with no `§K`, so it is
  outside that sentence's population. The measurement was right about what it
  measured. Refs #603, ADR-0090 §4.

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
  `ConversationLifecycle`, in `orchestration/conversations.py`, which ADR-0086 §8
  item 7 then names correctly. One ADR names one object two ways, and only one of
  the two names resolves.
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

- **8 of the 10 line numbers point at unrelated text.** Three, as written in
  ADR-0026 and as they land today:

  ```text
  ClockContextSource   context/sources.py:69  ->  def _time_of_day(hour: int) …
  FakeMemoryStore      testing/memory.py:41   ->  an import statement
  InMemoryMemoryStore  memory/store.py:54     ->  a blank line
  ```

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

**(b) A code citation** — a backticked name identifying something in the
repository. It has **three sub-forms, and they are deliberately separated by
whether a machine can tell them apart from ordinary prose**, because §6 forbids
the checker to infer its own input set and *intent is not in the text*:

- **b1, a module path** — `` `memory/ingest.py` ``, `` `scripts/ship.sh` ``,
  `` `tests/memory/memory_store_contract.py` ``. **Defined by root, not by
  shape**: a path is a code citation when it lies under `src/ai_assistant/`,
  `tests/` or `scripts/`, written either in full or relative to one of them.
  A path under any other root is a **document reference and not a code
  citation** — `` `docs/review/guide.md` ``, `` `.github/workflows/gate.yml` ``,
  `` `docs/adr/template.md` `` — and nothing resolves it against the code. Root
  membership is mechanical, where "contains a `/`" is not: this ADR cites
  `docs/review/guide.md` itself, and a shape rule would report it as an
  unresolved symbol.
- **b2, a dotted symbol** — `` `MemoryStore.get_many` ``,
  `` `Provenance.evidence_elided` ``, `` `MemoryDecisionKind.MERGE` ``. A
  qualified name whose tail is an identifier. **Near-unambiguous**, once
  document filenames are excluded — `` `CONTRIBUTING.md` `` and
  `` `CLAUDE.md` `` share the shape and are not code.
- **b3, a bare single token** — `` `ConversationLifecycle` ``, `` `Engine` ``.
  **Not mechanically separable** from the vocabulary the corpus also backticks,
  and therefore **not checked at all** (§6). It stays a legitimate way to write a
  citation — it is how most of the corpus names a symbol — but no tool selects
  it, because selecting it *is* the inference §6 forbids.

**A code citation carries no line number** (§5).

**(c) A tracker citation** — `#NNN`, a GitHub issue or PR number.

**Two exclusions, both mechanical, neither requiring intent.**

- **A fenced block is display, not citation.** Everything inside a ``` fence is
  quoted or illustrative material — a status line being shown, a signature being
  drafted, a defect being exhibited — and nothing in it is checked. This is what
  lets an ADR quote a form it forbids, including this one (§5).
- **A document reference is not a code citation**, whether bare
  (`` `CONTRIBUTING.md` ``, `` `CLAUDE.md` ``, `` `CHANGELOG.md` ``) or rooted
  (`` `docs/review/guide.md` ``). Bare ones alone account for 168 of the 203
  apparently-unresolved dotted names; b1's root rule covers the rooted ones.

**Backticks alone still do not make a citation, and b3 is where that bites.**
The corpus backticks status vocabulary (`` `Accepted` ``, `` `Proposed` ``,
`` `Status` ``), enum members (`` `MERGE` ``, `` `ALLOW` ``), Python literals
(`` `None` ``, `` `False` ``), tool codes (`` `DTZ` ``) and git refs
(`` `HEAD` ``). Roughly **one bare backticked token in five** resolves to no
definition and is not meant to. That ratio is not reducible by a cleverer
checker, which is why §2 grades the three sub-forms rather than promising one
check over all of them.

### 2. What "resolves" means, per kind

**(a) A decision citation resolves** when `docs/adr/NNNN-*.md` exists **and**,
where a `§K` is given, that file defines a section numbered `K`. Nothing about
the ADR's status is part of resolution — that is liveness, and §4 keeps the two
apart deliberately. **The section half of this definition is for authors and for
a future check; §6 does not check it**, because a `§K` in prose cannot be
distinguished from a restatement of a supersession scope. The definition is
stated all the same, so the rule is written down when a form that separates them
exists.

**A joined or ranged citation resolves on the numbers it writes, and only
those.** `§5/§6` and `§3, §5` resolve when **every** section named resolves. A
range `§§3–5` resolves when **its two endpoints** resolve; intermediate numbers
are not expanded and not required to exist, because a range is a span of
document that a reader reads, not a set a checker enumerates — and expanding it
would invent members (`§4`) the author never wrote. An item or sub-letter
suffix — `§8 item 6`, `§8c` — resolves on the section number; **the item or
letter is not checked**, since the corpus numbers items in running prose and no
uniform structure exists to resolve them against. This is deliberately the
weakest reading available: it makes the result determinate, which is what §6
needs, without inventing structure.

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

**(b) A code citation resolves** against `src/ai_assistant/`, `tests/` **and**
`scripts/`. All three, not `src/` alone: conformance suites and their factories
live under `tests/` by `CONTRIBUTING.md`'s "Adding a Protocol", and the corpus
cites `scripts/` by name nine times.

**Resolution is a definition lookup, not a text search, and the difference is
not pedantic.** A free-text search for the name finds it in any docstring or
comment that happens to use the word, so `` `Status` `` "resolves" against prose
in a `.py` file. A module path resolves against the **filesystem**; a symbol
resolves against a **definition site** — a `class`, a `def`, an assignment or a
class-body annotation.

**The three sub-forms differ sharply in how much noise they carry**, which is
why §1 separates them at all:

| form | occurrences | not resolving | disposition |
|---|---|---|---|
| **b1** module path | 574 | 3 (0.5%) | reported (Tier 2) |
| **b2** dotted symbol | ~770 (excl. document names) | ~4% | reported (Tier 2) |
| **b3** bare token | 6,675 | ~20% | **not checked** |

**b3 is not checked because it cannot be *selected*.** A checker would have to
decide that `` `ConversationService` `` is a citation and `` `Status` `` is
vocabulary, from two tokens of identical shape, with intent nowhere in the text.
Reporting both is a false report on `Status`; reporting neither is what §6
requires. There is no third option, so b3 leaves the checker entirely — and with
it the ~20% noise that made the naive check unusable.

**And neither b1 nor b2 may *fail* a check, which is §3.** The measurement above
was taken to justify failing on them. Reading the flags refuses it: of b1's
three, one is a genuine defect and **two are correct citations that an
append-only corpus must be able to write**. That result generalises, and §3
states it.

**Resolution is not correctness.** `Engine._project` resolves and is still the
wrong symbol for the claim ADR-0086 §8 attaches to it (#586). §6 promises to
catch a name that points at *nothing*. It cannot catch a name that points at the
wrong thing, and this ADR does not pretend otherwise: that defect is found by
reading, and by review.

**(c) A tracker citation resolves** when the issue or PR exists. **That is the
whole of it, and issue *state* is not checked at all.**

This is a deliberate retreat from where this ADR started. A sentence like "`#NNN`
tracks the conversion" or "**#281 is discharged**" makes a claim about state, and
checking it means first recognising that a claim was made — separating an
assertion from a quotation, an attribution, or a negation. This very ADR quotes
ADR-0085's "**#281 is discharged**" in order to say it is *false*; a
phrase-matching checker would report this document as making the claim it
refutes. That is prose inference, §6 forbids it, and no smaller grammar rescues
it, because the corpus phrases these claims freely.

**So two real defects are conceded to reading rather than tooling**: #593
(ADR-0085 asserts a discharge the tracker contradicts) and #588's defect 2 (a
claim falsified four hours after it was written, while its PR sat in review).
They are genuine and they stay the author's and the reviewer's to catch. What
survives mechanically — the number exists — is worth having anyway, and it is
Tier 1 because there is no case where a cited issue number legitimately fails to
exist.

### 3. An append-only corpus correctly cites what is not in the tree, so no code citation may fail a check

**"Resolves against today's `src/`" is the wrong test for a decision record, and
this is the central finding of this ADR.** ADRs are append-only (ADR-0001): they
record what was decided *at a moment*, and a corpus of them necessarily
accumulates correct citations to things the tree does not contain. There are
three such classes and **all three are indistinguishable, by form, from a stale
citation** — each is a backticked name resolving nowhere.

**Class 1 — not yet built.** A contract ADR names a type before it exists;
ADR-0015 §5 requires exactly that ordering. `Provenance.evidence_elided` was
fictional until ADR-0086 §4 landed. `hub_max_frame_bytes` was fictional when
ADR-0085 §8c cited it and is real now (#572) — correct to flag the day ADR-0085
merged, correct to pass today, with no edit in between.

**Class 2 — deliberately removed.** The ADR that removes something must name it,
and every later ADR recording that history names it again. ADR-0015 §1 removes
`scripts/codex_review_decision.py`; the citation is right and the file is
correctly absent. `MemoryDecisionKind.MERGE` is the same case seen seven times:
ADR-0040 replaced it with two members, and ADR-0028, ADR-0038 and ADR-0040 all
name it while recording the replacement. **Every one of those seven is correct,
and every one resolves nowhere.**

**Class 3 — considered and declined.** An alternatives section names a shape the
ADR then refuses. ADR-0031 weighs "a new `core/invocation.py`, by analogy with
`core/clock.py`" and rejects it in the next sentence. The file never existed and
never should; the citation is not defective, it is the record of a road not
taken.

**Separating these from a real defect is a reading, and §6 keeps readings out of
the tool.** The distinguisher is tense and mood — a present-tense assertion about
current code versus a past-tense or hypothetical one — and recognising that is
prose inference, which §6 forbids for the reasons Context gives.

**Therefore no code citation may fail a check.** The two selectable sub-forms,
b1 and b2, are **reported and never failing** — the same disposition §4 gives
liveness, for the same reason: the tool surfaces, the reader decides. A checker
that failed on b1 today would fail this repository on ADR-0015's record of its
own deletion. **b3 is neither failed nor reported**, because §1 leaves it
unselectable; §6 states the boundary once for all three.

**What survives is still worth having.** Three flags corpus-wide on b1 is a list
a human reads in a minute, and it contains a real defect nobody had found:
ADR-0045 names `testing/store.py` as the fake store's home, and the fake store is
`FakeMemoryStore` in `testing/memory.py` — which ADR-0026 cites correctly. The
value is in the shortness of the list, not in the power to fail.

### 4. Liveness is in scope, is derived from both directions, and is reported rather than adjudicated

**Liveness is a distinct question from resolution and is answered separately.** A
decision citation to `ADR-NNNN §K` is **live** when §K has not been replaced. A
citation of a dead clause resolves perfectly and is still wrong, and verbatim
quotation establishes nothing about it (Context).

**For a reader, liveness is derived from both the earlier ADR and the later
one.** Read `ADR-A`'s whole `Status` **field** — every physical line, since a
legacy value may wrap (ADR-0070 §4) — then read each ADR it names, because §4
makes the later ADR the authority on extent, and follow the transitive walk
onward through that ADR's own status. The walk terminates: an ADR is only ever
superseded by a higher-numbered one. **A checker that read only `ADR-A`'s status
would have believed ADR-0074 and been wrong; the lane that trusted ADR-0086's own
declaration was right.**

**The reverse record is a header line, and this ADR ratifies it as the canonical
machine-readable form.** An ADR that supersedes another, wholly or partly, writes
`- Supersedes: ADR-A …` or `- Partially supersedes: ADR-A …` in its header. Seven
and two ADRs respectively carry one today, ADR-0070 and ADR-0015 among them. Like
the forward record it is a pointer: the superseding ADR's own text remains the
authority on extent. The check must not discover a supersession by reading prose.
A sentence of the shape

```text
ADR-0090 replaces ADR-0080's retry rule.
```

declares a supersession to a human and nothing to a checker, and recognising it
is exactly the structural inference §6 forbids. **That example is fenced for the
same reason §5's are**: it names an ADR that does not exist, and §1 excludes
fenced content from the input set, so this ADR does not fail its own Tier 1.
Every ADR that needs to write a hypothetical reference does the same.

**The target is the first `ADR-NNNN` in the record, and one record names one
ADR.** Everything after that token is scope prose and is not extracted. This is
necessary rather than tidy: ADR-0070 §4 forbade an `ADR-NNNN` inside the
*forward* record's scope, nothing ever bound the reverse record, and the corpus's
scopes use them freely — ADR-0020's names ADR-0012 and ADR-0015 while superseding
only ADR-0015; ADR-0067's points a reader at ADR-0019; ADR-0024's cites ADR-0017's
precedent and quotes its own number. Extracting every token instead of the first
turns all three into false reports. **An ADR superseding two earlier ADRs writes
two records**, which is also what keeps each scope attached to its own target.

**This rule was run against the corpus before being written here.** Over the nine
reverse records on `main` it produces **zero** reports — the quiet-by-construction
property claimed below is measured, not assumed. Extracting every `ADR-NNNN`
instead produces five, all false.

**The checker emits exactly one liveness report, and this is its whole rule.**
For every ADR `B` carrying a reverse record naming `ADR-A`: if `ADR-A`'s whole
`Status` field does not name `ADR-B` **in a supersession token** — `superseded
by` or `partially superseded by`, ADR-0070 §4's canonical vocabulary, **matched
case-insensitively** — **report the disagreement**. Otherwise, silence. Nothing
else about liveness is reported.

**The case-insensitive match is required, not incidental.** The token's first
letter is capitalised when it leads the line and lower-case when it follows a
grandfathered `Accepted,` — `Superseded by ADR-0015` on ADR-0012 against
`Accepted, partially superseded by ADR-0020 and ADR-0025` on ADR-0015. ADR-0070
§4 sets one vocabulary for both positions and says nothing about case. Matching
`superseded by` case-sensitively reports **one** pair on `main` — ADR-0015
against ADR-0012, a correct record — and matching case-insensitively reports
none. Both figures were measured on the corpus.

**The supersession token is required, and a bare mention is not enough.** A later
ADR may both amend one clause of `ADR-A` and supersede another; ADR-0070 §1
classifies edit by edit, so that is permitted. If `ADR-A`'s status then recorded
only the amendment — `Accepted, §1 amended by ADR-B` — a test that merely asked
whether `ADR-B` appeared anywhere in the field would see it, fall silent, and
miss exactly the omitted supersession record ADR-0070 requires. Requiring the
token closes that. Both rules report **zero** against `main`'s nine reverse
records, so the stronger one costs nothing in false positives; it was measured
before being written here.

Three properties make that rule implementable where the earlier drafts of this
section were not:

- **It never classifies the *later* ADR's own header.** It reads one enumerated
  vocabulary — ADR-0070 §4's supersession tokens, on the earlier ADR's status —
  and nothing else. How `B` describes its own relation to `A` is expressed six
  ways in the corpus (`- Amends on ratification:`, 6 ADRs; `- Amends:`, 5;
  `- Superseded:`, 4; plus legacy qualifiers reading `discharged by`, `narrowed
  by`, `amended by`) and **none of them is specified by this ADR**. So ADR-0038's
  `Accepted, §1b discharged by ADR-0040` never has to be classified: ADR-0040
  carries no reverse record naming ADR-0038, so the pair is never compared.
- **It reads the whole field, so every legacy shape works.** ADR-0015's
  grandfathered `Accepted, partially superseded by ADR-0020 and ADR-0025` is
  silent, where a rule keyed to a *leading* `Partially superseded by` would find
  an empty forward set and report a correct record as a disagreement. Extraction
  is safe because ADR-0070 §4's authoring invariant guarantees it: "**a scope
  names a clause, not another ADR**: it carries no `ADR-NNNN` token."
- **It is driven by the reverse record, so an absent one is silence, not a
  report.** A forward target with no reverse record produces nothing. ADR-0040's
  status names ADR-0086 while ADR-0086 carries no header line; under this rule
  that pair is simply never compared, where a two-set difference would have
  reported it in one direction and suppressed it in the other.

**What this buys, and when.** The reverse record is forward-only and no header is
retrofitted, on ADR-0070 §4's non-retrofit reasoning. So the check is quiet on
the existing corpus by construction, and **it would not have caught the
ADR-0074/ADR-0086 window**, because ADR-0086 declared its supersessions in §11
and carried no header. It earns out on ADRs written after this one. That is a
thinner promise than the brief for this ADR assumed, and it is the honest one.

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
naming ADR.** ADR-0074's "ADR-0076 §9's obligation set" names ADR-0074's §9 — the
collision recorded in Context, which the script written for this ADR walked into
twice on its first run. **No mechanical rule separates the two**, because the
distinction lives in the surrounding prose. That is precisely why §6 does not
check section references at all — neither failing nor reporting them — and why §9
declines to invent a form that would.

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
append-only violation the rule exists to prevent." **A legacy citation is handled
by stripping the line number and resolving the path**, which is b1 and therefore
selectable: `testing/memory.py:41` is checked as `testing/memory.py`. The bare
symbol beside it — `FakeMemoryStore` — is b3, so nothing selects it, and the
argument of this section survives that: the rule exists because a *reader*
follows a symbol name where a line number misleads them, which holds whether or
not a tool can pick the name out of the prose.

**Where a position genuinely must be conveyed**, name the enclosing symbol and,
if needed, quote the line. Both are stable under edits elsewhere in the file.

**This ADR's own Context exhibits three of the rotted citations, and they sit
inside a fenced block.** That is not a courtesy; it is the mechanism. §1 excludes
fenced content from the input set, so the examples are excluded **by their form**
rather than by anyone judging that they are illustrations. The rule's own ADR is
the one document guaranteed to contain what the rule forbids, and a rule whose
own statement violates it — or which needs a hand-written exception to avoid
doing so — is not a rule an implementation can apply. Any ADR needing to exhibit
a forbidden form does the same thing: it fences it.

### 6. What a checker may and may not report

This section binds the implementation lane; it does not write it.

**Two tiers, and the boundary is whether a legitimate non-resolving case
exists.**

**Tier 1 — may fail. Two things, and only two.** A decision citation naming an
**ADR file that does not exist**, and a tracker citation naming an **issue number
that does not exist**. These have no legitimate non-resolving case at all: ADRs
are append-only so a file is never deleted, and an issue number once assigned
stays assigned. A failure is always a defect. The corpus's 3,387 decision
citations pass today, so this is a regression guard rather than a backlog — and
it is the tier that answers #588's complaint that no gate step can fail on a
`docs/adr/**` change.

**A section number that does not resolve is not checked at all — not Tier 1, and
not Tier 2 either.** Two earlier drafts of this ADR put it in each tier in turn,
and both were wrong. A `§K` reference is not always a citation of the ADR beside
it: ADR-0074 writes "ADR-0076 §9's obligation set", where the §9 is ADR-0074's own
and names the scope ADR-0076 replaced. ADR-0076 has no §9. Failing on that fails
a correct document; *reporting* it is no better, because the ambiguity rule below
requires an unevaluable citation to pass silently, and a rule that both reports
and passes the same input is not implementable. **So section references are
passed silently until a mechanically distinct scope-reference form exists**, and
§9 declines to invent one here. The cost is measured and near zero: the corpus
contains **no** real section miss, so the check had nothing to catch and only
something to be wrong about.

**Tier 2 — reported, never failing.** Every **b1 or b2** code citation that does
not resolve (§3), and every liveness disagreement (§4). Each has a legitimate
class no mechanical test separates from a defect — but each is at least
*selectable and evaluable*, which is what b3 citations and section references are
not. Each is surfaced for a reader; none blocks.

**Nothing else is checked.** Not b3 (§1 — unselectable), not section numbers
(above — unevaluable), not issue state (§2(c) — unreadable without inference).
Three rules, one boundary: **the checker touches only what it can pick out of the
text without guessing what the author meant.**

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

- **ADR-0070 — nothing owed, on two counts.** First, §4 anticipated a
  liveness-classifying consumer and bound it in advance ("this rule binds any
  liveness-classifying consumer added later"); §4 above supplies that consumer's
  rule where §4 gave none, contradicts no sentence of §4, and in fact rests on
  two of them — the pointer/authority distinction and the transitive walk.
  Second, §4 above requires a `- Supersedes:` header line on the **later** ADR.
  ADR-0070 §4 legislates the **earlier** ADR's `Status` field and says nothing
  about the later ADR's header, which ADR-0070's own header nonetheless carries.
  Neither is a change to what §4 decided. Under ADR-0082 §1 both are **stacked
  additions**: "recorded in the ADR that makes it, and nowhere else." No `Status`
  edit and no dated note are owed on ADR-0070.
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
- **This ADR's `Status`.** It shipped `Proposed` and was reviewed while
  `Proposed` — so a finding could still change the decision, which it did, seven
  times — then flipped to `Accepted` before merge (ADR-0015 §5;
  `CONTRIBUTING.md`, "Contract ADRs land before their implementation"). It
  touches no Protocol and no `core` type and decides no contract surface, so
  **adversarial is the required set** — the same reading ADR-0082 §5 recorded for
  itself.

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
- **An allowlist of known-absent symbols**, to let code citations fail on
  everything else. §3 removes the need by making them all Tier 2, and the
  allowlist was the wrong instrument anyway: a hand-maintained file that decays
  exactly when it matters — ADR-0015 §4's finding about `WORKING.md`, in
  miniature — and one more list of citations nothing checks. It would also have
  had to grow an entry for every road not taken in every alternatives section.
- **A new marker syntax for code citations** — a sigil or role that would make
  every citation unambiguous, as `` :py:class:`X` `` does elsewhere. It is the
  clean answer to b3's irreducible ~20% and it is declined on cost: it is worth
  nothing until the corpus is marked, marking 86 ratified ADRs is the retrofit
  §5 and ADR-0070 §4 both refuse, and marking only new ADRs buys a check that
  sees almost nothing for a long time. §1's b1/b2/b3 grading keeps the
  precision without rewriting the corpus — the two checkable forms cover 1,344
  citations at ~1% error — and pays for it by leaving b3's 6,675 unchecked.
  **Revisit if** a b3 defect of `ConversationService`'s kind recurs often enough
  to be worth marking for, which is the condition under which a marker starts
  paying for itself. That is the one thing this decision knowingly gives up.
- **A distinct written form for a supersession-scope restatement**, which would
  let §6 check section numbers. It is the honest fix for ADR-0074's "ADR-0076
  §9's obligation set" and it is declined on the same ground as the marker
  syntax: it buys a check over a category with **no known real misses**, and it
  would ask the corpus to re-render prose that reads correctly to a human.
  **Revisit if** a real section miss ever appears, which is the evidence this
  decision currently lacks.
- **Extending §1's forms to `src/` docstrings** (#579's amplifying half). §7
  records why: it is a bigger rule than this ADR was read for.
- **Verifying quotation text as a hard check.** §6 permits a quotation check but
  gives it the strictest failure handling in the ADR, and nothing here requires
  one to exist. Against paraphrase it is useless, and against wrapped text a
  naive one is worse than useless.

## Consequences

**Easier.**

- **A `docs/adr/**` change can fail — on Tier 1.** The five-step gate's
  structural blind spot is named, and §6 gives the implementing lane a check
  whose input set is defined rather than inferred. Tier 1 is deliberately tiny —
  a dangling ADR file reference and a nonexistent issue number, the only two
  things in the corpus with no legitimate way to fail. It passes today, so it
  guards against regression rather than presenting a backlog.
- **The corpus turned out to be much healthier than the brief assumed, and that
  is a finding.** Four instances motivated this ADR; the measurement found the
  cross-reference graph essentially sound (3,387 references, no real failures)
  and the code-citation "failures" mostly correct history. The expensive mistake
  available here was to ratify a failing check over 1,344 citations and spend the
  implementation lane's time on false positives. §3 is what prevents it.
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

- **The corpus is asked to change, in two places.** Line numbers were being
  written three days ago and stop being written now (§5); and a superseding ADR
  now writes a `- Supersedes:` header line, which only nine ADRs carry today
  (§4). Both are real costs paid by authors, and both are stated as changes
  rather than dressed up as conventions that already existed.
- **The liveness check is worth little until the reverse record is habitual.**
  §4 is honest that ADR-0086 — the case that motivated it — would not have been
  caught, because ADR-0086 carries no header line. The check earns out on ADRs
  written after this one, and a reader expecting it to audit the existing corpus
  will be disappointed.
- **Two citation shapes coexist indefinitely.** New ADRs carry no `:NNN`; 16 older
  ones keep 219. A reader meets both, and §5's non-retrofit is what makes that
  permanent. The mitigation is that the *path* in a legacy citation is still b1,
  so `testing/memory.py:41` is checked as `testing/memory.py` and the old form
  degrades to a checkable one rather than to nothing.
- **The check catches none of the four defects that motivated it, and this is
  the honest headline.** #586's `ConversationService` is a b3 bare token, so
  nothing selects it; its `Engine._project` half resolves; #593 and #588's
  defect 2 are issue-state claims, which §2(c) does not read; #572's
  `hub_max_frame_bytes` is a §3 class-1 citation that was correct all along. A
  reader who expected this ADR to mechanise the cases in its own Context should
  stop here: it does not. What it delivers is a Tier 1 that cannot regress, a
  small Tier 2 that found a defect nobody had (`testing/store.py`), and — mostly
  — a written account of exactly which of these a tool can never do.
- **Tier 2 needs someone to read it.** A report nobody reads is worse than no
  report, because it looks like coverage. §3's three legitimate classes mean the
  list is permanently non-empty — `MemoryDecisionKind.MERGE` will be on it
  forever, correctly — so whoever builds §6 has to make a standing non-zero
  report legible, and that is harder than making a list that should be empty.
- **Two of the motivating defects are conceded outright.** #593 and #588's
  defect 2 are both claims about issue *state*, and §2(c) rules that state is not
  checked, because recognising a state claim means separating an assertion from a
  quotation or a negation. An ADR can still be made false by someone closing an
  issue, and nothing here will notice. That is the honest boundary of a tool that
  refuses to read prose, and it is where this ADR ends up after four review
  rounds each pushed it to promise less.

**Follow-on.**

- **`CONTRIBUTING.md` owes §1's forms and §5's rule** in its ADR-authoring
  guidance, under ADR-0070 §5's precedent. Filed as an issue; not written here
  (§8).
- **#588 is the implementation issue and survives; #579 is reconciled into it.**
  They are one defect class seen at two radii. #588's three checks became §§2
  and 4 of this ADR, and all three came back weaker than proposed: symbol
  resolution must read `tests/` and `scripts/` as well as `src/`, it does not
  catch #586's first half, and — §3 — **no unresolved code citation may fail at
  all**, whatever the citing ADR's status, because an append-only corpus
  correctly cites what the tree does not hold. #588's cited-section liveness
  check is not built either: §6 leaves section references unchecked. #579's distinctive half — quotation
  verification, and propagation into `src/` docstrings — is **declined here** (§7,
  §9) and its concern is met obliquely: §1's citable forms and §5's greppable
  symbols are what #579 itself proposed as the better instrument ("Cite
  `file:symbol`, not prose … A pointer to code is checkable by the gate in a way a
  quotation is not"). #579 should close, pointing here and at #588.
- **#586 and #593 remain open, and neither is caught by §6.** #586's
  `ConversationService` is a b3 bare token, which §1 leaves unselectable and §6
  therefore never reports; its `Engine._project` half resolves. #593 is an issue
  state claim, which §2(c) does not check. Both need a `docs/adr/**` amendment or
  a tracker action, and neither is written by this lane, whose fence is this
  file.
- **Three further candidates surfaced by the measurement, filed for triage.**
  `ClassifiedToolError` and `UserProfile` are backticked in ADR text and resolve
  in none of `src/`, `tests/` or `scripts/`; each is either a §3 class or a
  genuine instance, and only a reading tells which. **ADR-0045's
  `testing/store.py` is the one this ADR is confident about** — the fake store is
  `FakeMemoryStore` in `testing/memory.py`, which ADR-0026 cites correctly, so
  one ADR names it right and another names it wrong. That is #586's shape
  exactly, found by the method rather than by a lane tripping over it.

**Revisit when** the check of §6 has run over the whole corpus for the first
time. Its true-positive and false-positive counts against §1's forms are the only
real test of whether the forms were drawn in the right place, and they are
cheaply measurable once it exists. Revisit also **if** a defect of the
`Engine._project` kind — a resolving name attached to the wrong claim — recurs
often enough to be worth a different instrument, since §2 concedes that ground
outright.
