# A new ADR states its rulings in fewer words

**The question:** what should a new ADR look like, so that it states the same
obligations in far fewer words and no obligation is lost?

The ADR corpus is append-only. Nothing here touches a ratified ADR; this is
about ADRs written from now on.

## Baseline

- `docs/adr/template.md` gives an ADR a Context, a Decision and a Consequences
  section. It gives no guidance on length, on scope, or on what a marked
  clause should contain.
- ADR-0089 decides that only marked clauses bind (§3), and that every ADR
  ratified after it marks every clause it states (§5).
- ADR-0277 and ADR-0278 give each marked clause an address (`ADR-NNNN §S:k`)
  and add record checks to `scripts/check_citations.py`.
- `docs/review/adversarial.md` reviews ADR PRs. Nothing in it weighs how long
  an ADR has become.

## What was measured

All counts are words (whitespace-separated tokens). They were taken on
`main` at `8265b204`, using the shared clause extractor `scripts/clauses.py`
and the git history of each ADR file. The medians are per band of 25 ADRs.

| ADRs | median ADR | Context | Decision | Consequences | share of Decision in marks |
|---|---|---|---|---|---|
| 0001–0025 | 2,399 | 259 | 1,028 | 240 | 0% (before ADR-0089) |
| 0076–0100 | 9,568 | 873 | 6,458 | 414 | 5% |
| 0151–0175 | 11,627 | 904 | 7,974 | 481 | 27% |
| 0226–0250 | 17,394 | 1,351 | 12,640 | 441 | 51% |
| 0251–0275 | 14,575 | 882 | 11,510 | 423 | 61% |

At the far end, ADRs 0250–0255 run from 22,700 to 51,300 words each, and
carry 90 to 178 marked clauses. At about 1.3 tokens a word, a lane that reads
three of them has spent 100,000 tokens or more before it writes a line.

### Where the length comes from

1. **The Decision section is almost all of the growth.** Context and
   Consequences stayed roughly flat. Header notes added after ratification
   are about 5–10% of an ADR.
2. **Most of the length is in the first draft.** For ADRs 0151 onwards, the
   median first commit is 7,655 words, and the ADR is 11,369 words when
   ratified. First drafts jumped about threefold at ADR-0076 (2026-07-28),
   from about 1,900 words to about 5,800. We have not established why.
3. **Review adds about 45%, and half of that lands inside marked clauses.**
   Across 125 ADRs (0151 onwards), review added 673,648 words, 51% of them
   inside marks. The median ADR gained 12 clauses during review, going from
   30 to 42. Growth does not track the number of review commits
   (correlation 0.07). So it is not that a few long review loops made a few
   ADRs long: every round adds some text.
4. **Each clause got longer.** The median clause went from 50 words
   (0101–0150) to 98 words (0251 onwards), and the 90th percentile went from
   88 words to 208.
5. **Clauses carry their own justification and their own defences.** In
   ADRs 0251 onwards:
   - 22% of marked clauses contain their reasoning ("because…", "so that…"),
     up from 2% for 0076–0100;
   - 22% contain a "no lane…" rule that pre-empts a misreading, up from 3%;
   - many list what does *not* count ("Not a listing, not an export, not a
     retrieval, …").
6. **Each ADR decides more things.** The median number of Decision
   subsections went from 6 (0001–0025) to 12–15 (0226 onwards).

### What this means for the obvious fix

Splitting each ADR into a Decision and a separate Rationale section, the
idea this proposal started from, would help less than expected. In recent
ADRs, 61% of the Decision section is already binding text. The rulings
themselves got long: through reasoning written into the clause, defences
against misreadings, and an ADR deciding a dozen things at once.

## The change

Each option below applies only to ADRs written from now on. Numbers left
open are for the pilot to set.

1. **One obligation per clause, with the reason outside it.** A marked
   clause states what must hold, not why. The reason goes in ordinary prose
   directly after the clause, where it is still read but binds nothing
   (ADR-0089 §3). `check_citations.py` reports, at Tier 2, any clause in a
   new ADR that is longer than a word limit. Tier 2 means it reports and
   never fails.
2. **A closed list is stated positively.** "Only X and Y move this field",
   rather than a list of everything that doesn't. The two are equivalent, and
   the positive form is shorter and cannot miss a case. This would be
   guidance in the template and in `CONTRIBUTING.md`, with no check.
3. **A Decision budget.** A new ADR aims for no more than a set number of
   words in its Decision section and a set number of subsections. When it
   would go over, it becomes several ADRs, each deciding one thing.
   `check_citations.py` reports an ADR over budget at Tier 2.
   - The cost: more ADRs, more cross-references between them, and a review
     cycle for each.
4. **Review weighs added text.** When an adversarial finding on an ADR PR
   calls a clause misreadable, the first fix to consider is rewording that
   clause, not adding a new one next to it. The review prompt would show how
   many words each round added inside marks.
   - This changes `docs/review/adversarial.md`, which is a standing review
     contract, so it would merge last in any wave.

## Pilot first

This follows the same method as pilot #2553, which established that agents
read ADRs better than a synthesized design doc.

- Take one ADR from 0226 onwards whose length is near that band's median.
- Rewrite it under options 1–3, without changing what it obliges. The rewrite
  is for measuring only and is never merged, because a ratified ADR stays as
  it is.
- Before the rewrite, the answer key and questions come from the original's
  marked clauses.
- Two cold agents each answer the same questions, one from the original and
  one from the rewrite.

**The pre-registered outcome is a keep or drop:**
- **Keep** if the rewrite uses at least 40% fewer words and its agent scores
  no lower.
- **Drop** otherwise.

The pilot also sets the numbers the options leave open: the clause word
limit, and the Decision word and subsection budget.

## Options considered

- **A Decision / Rationale split on its own.** Declined, for the reason in
  "What this means for the obvious fix" above.
- **A hard Tier 1 length limit.** Declined for now. ADR-0088 §6 prefers a
  check that misses to one that is wrong, and a hard word limit would push
  authors into trimming words rather than trimming what the ADR decides.
  Revisit once the Tier 2 numbers are known.
- **Rewriting existing ADRs.** Not possible: they are append-only (ADR-0001, ADR-0070).
  A shorter restatement of an existing ADR would itself be a new ADR, and
  that is out of scope here.

## What this leaves open

- The numbers: the clause word limit and the Decision budget. The pilot sets
  them.
- Why first drafts tripled at ADR-0076. The data shows when it happened, not
  why.
- Whether option 4 is worth a round on every open lane when it merges.
