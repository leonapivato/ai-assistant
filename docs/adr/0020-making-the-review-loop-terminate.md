# 20. Making the review loop terminate

- Status: Accepted
- Date: 2026-07-20
- Supersedes: ADR-0015 §1's freshness clause — that `just ship` "refuses unless
  [a review artifact] exists for the exact commit the PR head is on". §3 below
  replaces the commit with the reviewed *content* as the anchor. The rest of
  ADR-0015 §1 (local-only execution, the `.review/` artifact, ship-not-push, the
  author owning the whole loop) and §§2–5 stand unchanged. ADR-0012 §5, the
  original statement of the same rule, was already retired by ADR-0015.

## Context

The review loop converges on short changes and does not converge on long ones.
Issue #91 carries the evidence; the two runaway cases:

| | #90 (skill) | #72 (ADR-0017) |
| --- | --- | --- |
| rounds / commits | 9 adversarial rounds | 58+ commits, **79 review records** |
| duration | — | ~2.5 hours |
| peak size | ~200 lines | **821 lines** |
| shipped at | 174 | 320 |
| what stopped it | operator said "don't let it get convoluted" | operator compared line counts |

ADR-0017 supersedes **one clause** of ADR-0004, a 175-line document. It cost ~79
Codex runs to do it. At its peak it was longer than ADR-0016 (792 lines), which
created an entire subsystem contract with six `core` types and a Protocol. An
8-line docs change (#92) converged in one round for ~7k tokens. **Length of the
artifact, not its file type, predicts the loop.**

Three findings shape the decision below.

**Every round is locally defensible.** From the agent that wrote ADR-0017,
unprompted: *"I had a local justification for each round and no view of the
aggregate."* Round 9 looks exactly like round 2 from inside. Its own commit
messages described fixing contradictions the previous commit had created, and it
could not read the signal it was emitting.

**In both cases the loop was broken from outside, by someone holding an
aggregate view. Neither terminated on its own.** One number — 801 next to 176 —
made two hours of drift legible instantly.

**Self-diagnosis is not available as a remedy.** At `80bb620` ADR-0017 had both
personas passing and was shippable. It then committed `05ca4fe`, a *good* commit
that cut scope as asked, which invalidated both records and forced another
round. Its own account: *"I treated [a green pair] as a checkpoint to build on
rather than a terminal state."* This is the same agent that had already written
the sharpest available description of the failure mode. Any remedy that depends
on the author noticing has been tested and has failed twice.

Two mechanisms are implicated. Adversarial review applies a code rubric to prose
and its findings about illustrative snippets are noise. And ADR-0015 §1 anchors a
review to an exact commit, so **any** commit forces a fresh round — including one
that leaves the reviewed content identical.

## Decision

### 1. Tell the reviewer what it is reading

`scripts/codex-review.sh` already writes a per-run preamble ("Change under
review") ahead of the rubric. The nature of the artifact is stated **there**, not
in `docs/review/guide.md` and not in the persona rubrics.

The preamble classifies the changed paths and, for prose files, states that
fenced snippets are illustrative for a human operator rather than executed code:
judge them for whether they would mislead a reader, not for runtime correctness,
error handling, or test coverage.

**The exemption does not extend to normative snippets.** A fenced block can *be*
the decision — ADR-0016 defines the `ToolRegistry` Protocol in one, and ADR-0015
§5 requires exactly that class of ADR to carry the architecture lens. Where a
snippet states a contract the repository will implement against, it is judged as
a contract: its internal validity is the subject of the review, not scenery
around it. The preamble distinguishes the two rather than exempting a file type
wholesale.

It goes in the invocation because the rubrics and the guide are *standing*
contracts — they are true of every change, and both reviewers and authors read
them as such. What this particular diff is, is per-run data, and belongs where
the per-run data already goes. A rubric edit would also apply the qualification
unconditionally, including to changes where it is false.

One statement is standing, and so does go in `docs/review/guide.md`: **findings
are hypotheses to verify, not facts to comply with.** Two `blocker`s in this
repository were stated with full confidence and specific-looking grounding and
were factually false — one claimed no-force-push protection covers feature
branches (it covers `main` only), one claimed the `ai-assistant-*` glob included
the primary clone (it does not). Both were correctly rejected with grounding.

### 2. Print the aggregate

`scripts/codex-review.sh` prints, on every run, without being asked:

- **round number** on this branch's SHA lineage — how many commits in the branch
  already carry a review artifact;
- **net diff size**, and where the change supersedes or amends another document,
  that document's size alongside it;
- **churn ratio** — cumulative lines touched across the branch's commits divided
  by net lines in the final diff. A ratio far above 1 means most of the work has
  been rework. This is the mechanical proxy for "consecutive commits fixing what
  the previous commit introduced": it needs no judgment and no model, only
  `git log --numstat`.

These numbers are recorded in the artifact's provenance line, so `just ship`
carries them to the PR and the human at merge sees the same aggregate the author
saw.

Nothing here blocks. **A round cap would forbid round 6 of #90, which found
`gh pr merge --match-head-commit` and closed a hole the author had wrongly called
unfixable.** Value at the tail is real; the defect is that the tail is invisible,
not that it exists. The failure mode this addresses is illegibility, so the
remedy is a number, not a gate.

Accompanying it, one rule in the living documents: **a green pair of records is a
terminal state, not a checkpoint.** When both personas pass, ship. This is prose,
and ADR-0015 is right that prose does not hold on its own — which is exactly why
it is paired with the printed aggregate rather than shipped alone.

### 3. Anchor the review to the reviewed content, not to the commit

`scripts/codex-review.sh` records the tree it reviewed (`git rev-parse
HEAD^{tree}`) alongside the `base_sha` it already records. `scripts/ship.sh`
accepts a review artifact when its recorded base **and** its recorded tree both
match the PR's current merge base and `HEAD`'s tree — regardless of which commit
the artifact is filed under.

The anchor's purpose is preserved exactly. A stale review is one taken against
different content or a different base; both still fail, mechanically, as before.
What is removed is the forced round on a commit that changes no reviewed byte: an
amended message, a squash, a rebase in place, a revert returning the tree to a
reviewed state, a reordering. The base is still compared, so a rebase onto moved
`origin/main` re-reviews — correctly, since the diff really did change.

`ship` still requires an adversarial record, and still requires the architecture
lens for a change touching `core/protocols.py` or `core/types.py`. Neither
requirement is relaxed.

**This does not cover the `05ca4fe` case.** A scope cut changes the tree, so it
genuinely produces a different diff and genuinely warrants a fresh review. The
remedy for that case is §2's terminal-state rule and the visible round count, not
this clause. Claiming otherwise would overstate what a content hash can know.

## Alternatives considered

**Skip adversarial review on docs-only changes (option A in #91). Withdrawn, not
narrowed.** It was tested directly on #92, an 8-line docs change: architecture
returned `APPROVE` with no findings, and adversarial on the same diff returned a
real `blocker` — the new text read as instructing the *reviewer* to fetch,
contradicting `docs/review/guide.md`'s requirement that a review never modify git
state. A would have skipped that review and shipped the defect. There is no
observed case of it helping. It also targets the wrong variable: short prose is
adversarial's best case, so A disables it precisely where it performs best, and
the length-scoped inversion — skip adversarial on *long* documents — would drop
the deepest review on the largest and most consequential ones. ADR-0017 governs
whether tool invocation may ever legally transmit a byte; that is the last place
to skip a review. Finally, `ship.sh` hard-blocks it: A was never a rubric-only
change, and required deciding what replaces the adversarial requirement for the
exempted class.

**A stop-rule the author applies to themselves** — "if a round's findings are all
about text the previous round introduced, stop." This was option C's original
form. Rejected: it asks for exactly the self-diagnosis that failed twice, the
second time in an agent that had already articulated the failure mode in writing.

**A hard round cap or diff-size threshold.** Rejected: see §2. It would have cost
#90 its most valuable finding.

**Dropping the freshness anchor entirely.** Rejected: it is the one mechanism
stopping a review of a stale commit from being posted as current, and ADR-0015
adopted it precisely because a self-attested paste needs that check to be
mechanical rather than a matter of care.

## Consequences

**Easier.** A commit that changes no reviewed content no longer costs a review
cycle, which removes the mechanical tax on squashing, amending, and reverting —
the operations an author performs while *reducing* a change. The author and the
merge reviewer both see the round count and the churn ratio, so the aggregate
that only an outside observer held is now on the record by default. Reviewer
noise on illustrative snippets falls without removing a reviewer.

**Harder.** The tree comparison is a second thing `ship` can refuse on, and its
failure message must distinguish "content moved" from "base moved" or it will be
misread as the old error. The aggregate is advisory, so an author can still
ignore it — deliberately; the alternative forbids findings worth having. §2's
terminal-state rule remains prose and carries prose's failure rate.

**Revisit if** the printed aggregate is observed being ignored across several
changes, which would argue for a soft gate — a confirmation at ship past some
round count — rather than the hard cap rejected here.

**Follow-on.** ADR-0015's status becomes "Accepted, partially superseded by
ADR-0020". Implementation is a separate PR: `scripts/codex-review.sh` (§1
preamble, §2 aggregate, §3 tree in the provenance line), `scripts/ship.sh` (§3
acceptance rule, and §2 — it currently strips the provenance line with
`tail -n +2` before posting, so the aggregate must be rendered into the comment
body explicitly or the merge reviewer never sees it), `docs/review/guide.md` (§1
standing statement), and the "exact commit" wording in `CLAUDE.md` and
`CONTRIBUTING.md` (§3).
