# Lane feedback

A dispatched lane sees the ADR corpus from an angle nobody else does: from
inside a change, under a deadline, with the documents as the only source of
authority. Most of what it learns there is never written down. The PR records
what the lane decided; it does not record which documents fought back, which
question needed three files open, or which sentence would have saved a review
round.

This document is the request that collects that. It is asked of a lane **after
its work is closed**, and it is asked for evidence, not for a rating.

## When to ask

Ask in the lane's own session, as soon as it reports and before its context is
discarded. Almost nothing below can be reconstructed afterwards — not by
reading the PR, not by reading the diff, and not by asking a fresh agent to
re-derive it. A lane that has moved on has already lost the answers.

Ask it of every lane, not only the ones that went well. A lane that stalled,
guessed wrong, or shipped something that had to be corrected knows things a
successful lane structurally cannot.

## Why it is shaped this way

Four properties of the request do the work, and each answers a way this kind
of feedback fails:

- **It asks for counts and citations.** Unquantified impressions of a document
  corpus are not actionable and do not compare across lanes.
- **It separates "my bug" from "the document handed me this."** Both are worth
  knowing; a report that conflates them supports no decision.
- **It asks, of every friction, whether it sat inside one document or at a
  join between several.** Whether the corpus needs better documents or a
  better index turns on that distinction, and a lane is the only thing that
  can observe it.
- **It bars a lane from judging a cost whose alternative it never saw.** A
  lane can report what a decision cost it. It cannot weigh that against the
  counterfactual where the decision went the other way, because it did not
  work in that world. Asking anyway produces confident verdicts on rounds that
  closed before the lane opened.

## The request

Paste from here down.

---

Your work is closed; this is not a review of it and there is nothing to fix.
Report only — do not edit ADRs, open issues, or change any file in response to
this. I want evidence about the ADR corpus and the workflow, from the one
vantage point that cannot be reconstructed later: yours, just after finishing.

Four rules, because they are what make the answers usable:

1. **Quantify.** Counts, rounds, `file:§` citations. "The ADRs were mostly
   clear" is the least useful sentence you can send.
2. **Separate "my bug" from "the document handed me this."** Both are worth
   reporting; conflating them is not.
3. **For every friction, say whether it was inside one document or at a join
   between two or more.** This distinction decides more than it looks like it
   does, so do not skip it.
4. **Do not judge whether a cost was worth it if you never saw the
   alternative.** Report the cost, then say what you could not see. You are
   not positioned to evaluate decisions made before your lane opened.

### A. Everyone

1. Which documents did you actually keep open while working, and which did you
   read once and never return to?
2. Where did you have to hold **two or more documents open simultaneously** to
   answer one question? List each. What did each cost — a review round, a
   wrong first attempt, an hour?
3. When you cited an earlier ADR's `§`, how did you confirm that section was
   still live and not amended or superseded? What did that cost, and were you
   ever unsure whether you had it right?
4. Where did you make a call the documents did not license you to make? Name
   each one, and the sentence that was missing.
5. What did you read that you did not need? Of the lines you read in the
   largest document, roughly how many were load-bearing for your work?
6. Which mechanical checks (gate steps, conformance suites, the triad test,
   `lint-imports`) told you something you would otherwise have had to
   remember? Which fired too late — after you had already built on the wrong
   assumption?

### B. If you implemented against an existing ADR

7. How many design decisions did you have to make that you expected the ADR to
   have made? List them.
8. Did any normative clause reference something that does not exist yet — a
   setting, a type, a module? How did you resolve it?
9. Did any ADR contradict itself, or defer something its own argument shows
   the current change needs? Quote both sides.
10. Were the ADR's fences (the files or packages in scope) unambiguous for
    every file you wanted to touch? Where did you have to guess?

### C. If you authored or amended an ADR

11. Of your review rounds, roughly what split changed a **ruling** versus
    changed **wording, ordering, or an amendment record**?
12. Which rounds would have been unnecessary if ratified text were
    **rewritable** afterwards rather than append-only?
13. How much effort went to supersession bookkeeping — finding every earlier
    ADR your decision touched, and phrasing the status lines — against
    deciding the thing itself? Give a rough proportion.
14. Was there a point where you knew further rounds were not improving the
    decision? What kept them going?
15. What did you defer, and did you say who improvises in the meantime?

### D. Close

16. **The single change** to the corpus or the workflow that would have saved
    you the most. One item, not a list. Say what it would have saved, in the
    units from question 2.
17. What should **not** change — something that looks like overhead but earned
    its cost in your lane, with the evidence that it did.
18. Anything you noticed that none of these questions asked about.

Length: as long as it needs to be. A short answer with citations beats a long
one without.

---

## Reading what comes back

Question 3 is the load-bearing one. It measures, in a unit comparable across
lanes, what it costs to establish that a cited clause is still live — the cost
the corpus's amendment and supersession machinery imposes on every reader. A
corpus where that is cheap needs a better index; a corpus where lanes lose
rounds to it needs the live rules consolidated somewhere a reader can trust
without traversal.

Weigh the answers by what the lane could see. A lane reports its own costs
first-hand and everything else at second hand, and the rules above ask it to
mark the difference — so a verdict on something outside its view is an
observation to check, not a finding to act on. The same reading applies here
as to a review finding (`guide.md`): what comes back is a hypothesis.
