# 180. The closing anchor binds the tree of the final push, and a lane does not wait on CI to flip ready

- Status: Proposed
- Date: 2026-08-22
- **What this changes and what it does not.** It changes two things about the
  tail of a branch: ADR-0136 §1's closing anchor stops being an *ordering*
  against the final push and becomes a run on the **tree** of that push, and a
  lane stops waiting on the remote `gate` check before `just ready`. It changes
  nothing about what the gate is, what CI runs or when CI runs it, nothing about
  what a review record covers, and nothing about the merge bar: `gate` green on
  the merged content is still required, and the merger still watches it. No
  Protocol, no `core/types.py` value and no runtime behaviour is decided here.

## Context

### The tail of a lane is serial, and only one of its two waits is load-bearing

A dispatched lane finishes like this today:

1. the closing anchor — the four static steps plus a complete `pytest` run, about
   two minutes distributed (`just test-fast`) or eight to nine serial
   (ADR-0179's measurement on this machine; `CONTRIBUTING.md` says five to
   eight, and the owner's correction on issue #1378 says nine);
2. the final push;
3. the wait on the `gate` check — the last `gate` run before ADR-0179 took
   5m28s and the distributed job now takes about 2m45s, plus queueing;
4. `just ship`, then `just ready`.

Steps 1 and 3 are consecutive and independent. Nothing in step 3 can change what
step 1 concluded, because they are the same five commands over the same tree —
one on the author's machine, one on `ubuntu-latest` against the locked
environment. The lane is idle through both, and the cost is wall clock rather
than tokens: minutes per lane, paid once per final push and again after every
post-`ready` rebase, which under `strict` branch protection is every lane but the
first in an ordered batch.

### What the ordering clause forbids, and what nothing needs it to forbid

ADR-0136 §1 words the closing anchor as an ordering:

> immediately before the **final push preceding `gh pr ready`**

Read literally, that forbids running the anchor *after* the push — even on the
identical tree, even when the working tree is untouched while it runs. What the
clause is actually protecting is stated two clauses later, and it is about the
tree, not the order: "Each anchor is a run on the tree as it then stands, and a
full gate run on an earlier tree does not discharge it." The tree that matters is
the one that ships.

The ordering is in fact the *weaker* guarantee of the two. Before the push,
"the tree as it then stands" is checkable only by the author's discipline —
nothing stops a byte changing between the anchor and the push, and nothing
records which tree the anchor ran on. After the push, the tree the anchor ran on
is a pushed commit with a SHA, and its identity with the PR head is a fact anyone
can check. Binding the anchor to the tree therefore keeps everything the ordering
bought and makes it verifiable.

### What the CI wait buys, and who was already buying it

The wait's product is a statement about the `gate` check on the PR head. Three
facts about how that statement is used:

- **The merger re-checks it, and says so.** `.claude/skills/dispatch-agents/SKILL.md`
  runs `gh pr checks <n> --watch --fail-fast` before every merge, and it already
  tells the coordinator that "the worker's own `gh pr checks` paste" is
  *provenance* which "`gh pr checks` above supersedes". The lane's copy is a
  second reading of a check the merger reads again, later, authoritatively — and
  `--watch` exists precisely because a *pending* check must not be mistaken for
  an absent one. A lane reporting "pending" is the case that guard was written
  for.
- **Branch protection refuses the merge outright.** `gate` is the only required
  check (ADR-0167 §4), and nothing crosses it red (ADR-0167 §2). A red gate does
  not reach `main` whether or not the lane looked.
- **The wait is often spent on a head that will not merge.** `worker.md` →
  "You are probably not finished when you report" is explicit that a lane in an
  ordered batch should *expect* to come back `BEHIND` and rebase. That rebase
  re-pushes, CI runs again, and the run the lane waited for is discarded
  unmerged.

There is a fourth fact, and it is the sharpest: **flipping ready re-runs the
gate.** `.github/workflows/gate.yml` lists `ready_for_review` among its
`pull_request` types, deliberately. So the lane that waits for the `synchronize`
run to go green and *then* flips ready has bought a result that the flip
immediately recomputes, on identical content, at full price.

### The one thing the wait does buy, and how much of it is left

Local green and remote green can differ: CI checks out the commit into a locked
environment, so a file that was never committed, or a dependency present only
locally, shows up remotely and not on the author's machine. That gap is mostly
closed already — `scripts/codex-review.sh` and `just ship` both refuse to run on
a dirty tree, untracked files included, so a lane that has shipped a review has
proved its tree is complete. What is left is the environment, which is the class
ADR-0010 built CI to catch and which no local run can catch by construction.

So the wait's residual value is not zero: it puts a red environment-only failure
in front of the lane while its session is still live, where discovering it later
costs the coordinator a re-dispatch. That is a real cost and it is named in the
consequences below. It is a small probability against a certain few minutes on
every lane, and — decisively — it is a cost the coordinator can pay knowingly,
because the coordinator is the one who watches the check before merging.

### A superseded run does not surface as a failure

Flipping ready promptly means the `ready_for_review` run starts while the
`synchronize` run is still going, and `gate.yml`'s `concurrency` block cancels
the older one. Measured on this repository on 2026-08-22, on PR #1421 at head
`5648ba07`: run `32597948147` was cancelled at 20:52:39Z by run `32598060879`,
which started 20:54:59Z and passed in 3m13s. `gh pr checks 1421` reports **one**
`gate` row — the passing one. The checks listing reports the latest run per check
name, so the cancelled predecessor is not visible to the merger's `--fail-fast`
guard and does not block the merge. One observation, and it is the shape this
decision makes routine rather than occasional, so it is named as something to
watch rather than settled forever.

## Decision

**We will bind the closing anchor to the tree of the final push, and end the
lane's wait on CI.**

### 1. The closing anchor is a run on the tree of the final push

> **Normative.** The closing anchor of ADR-0136 §1 is a full Definition-of-Done
> gate run that passes on the **tree of the final push preceding `just ready`**,
> and it passes **before** `just ready`. It is not required to precede the push.

> **Normative.** Where the anchor runs after the push, the tree it runs on is
> byte-for-byte the tree of the pushed head, and the working tree is not modified
> while it runs. A run on any other tree does not discharge the anchor, exactly
> as ADR-0136 §1 already requires.

> **Normative.** If the anchor fails, the push it ran on was not the final push:
> the fix is committed and pushed, and the anchor is owed again on the new head's
> tree. `just ready` does not happen in between.

This replaces an ordering with the property the ordering was protecting, and it
is the whole of the change to ADR-0136. Both of ADR-0136 §1's rebase clauses are
untouched and bind exactly as written, including the one that binds on the push
for merge after `just ready` — that clause was already written to bind on a push
rather than on `gh pr ready`, and this decision makes the closing anchor read the
same way.

### 2. A lane does not wait on the `gate` check before `just ready`

> **Normative.** An author does not wait on the remote `gate` check before
> `just ship` or `just ready`. Once §1's anchor has passed on the pushed tree and
> the required reviews are terminal, the lane ships the review, flips the PR
> ready, and reports.

> **Normative.** A lane reports the `gate` check as it stands when it reports,
> **pending included**, and a pending check is not a reason to delay the report.

> **Normative.** The check that governs the merge is the merger's, not the
> lane's: `gh pr checks --watch --fail-fast` immediately before the merge, plus
> branch protection. Nothing in this decision permits merging on a red or absent
> `gate` (ADR-0010, ADR-0167 §2).

### 3. What still binds unchanged

> **Normative.** ADR-0136 §3 stands whole. A red push between the anchors is
> still acceptable, and a red **final** push is still the failure the closing
> anchor exists to prevent: a branch is not flipped out of draft on a tree whose
> full gate has not been run and passed locally. §1 is what makes that true, and
> §2 does not weaken it — what §2 removes is the wait on a second opinion about a
> tree the author has already proved, not the proof.

> **Normative.** ADR-0136 §1's first anchor, its two rebase clauses, its rule
> that each anchor is a run on the tree it names, and its refusal of a docs-only
> exemption all stand as ratified, as amended by ADR-0166 §1 and ADR-0179 §3.
> ADR-0136 §2's four static steps before every commit and its `pytest`
> discretion between the anchors stand.

> **Normative.** Nothing here alters ADR-0015, ADR-0020, ADR-0025, ADR-0027 or
> ADR-0165: which trees a recorded review covers, when a base move costs a round,
> what `ship` will accept, and the one exempt commit shape are decided there and
> are untouched.

### 4. What this does not decide

- **CI's gate and its triggers.** `.github/workflows/gate.yml` is unchanged: the
  same five steps, the same four `pull_request` types, the same `concurrency`
  block. §2 depends on `ready_for_review` continuing to trigger a run, because
  that run is the one the merger reads on a lane that never waited.
- **The merger's guard.** `.claude/skills/dispatch-agents/SKILL.md`'s pre-merge
  sequence — `gh pr checks --watch --fail-fast`, the `BEHIND` recheck,
  `--match-head-commit` — is relied on as written and is not changed by a byte.
  §2 makes it the operative check rather than the second of two, which is what
  that file already claimed it to be. The one clause this change edits there is
  the neighbouring prose about what a lane's own pytest line evidences, which §1
  makes stale.
- **The Definition of Done.** The five steps and their order are ADR-0002's and
  ADR-0010's; "done" still means all five pass on the shipping tree.
- **The first anchor.** Its ordering — before the first review invocation — is
  about a premise the reviewer is handed, not about a push, and nothing here
  touches it.
- **Whether a lane *may* wait.** §2 removes the obligation and the expectation,
  not the possibility. An author with a specific reason to watch a particular run
  may; no justification is owed either way, and no reviewer or coordinator may
  require one.

### 5. What this records against earlier ADRs

- **ADR-0136 — partially superseded, and the clause is named.** §1's first
  normative clause is replaced in its **ordering half only**: "immediately before
  the **final push preceding `gh pr ready`**" becomes §1 above. A reader holding
  only ADR-0136 would refuse to run the closing anchor after the push, which §1
  permits, so the requirement is replaced by a weaker one rather than reconciled
  with its own text — that is ADR-0070 §1's supersession test, and the record
  takes ADR-0070 §4's leading-token form on the `Status` line beside ADR-0166's,
  per the template's rule for a second partial supersession. **No ratified text
  of ADR-0136 is rewritten** (ADR-0070 §1): the clause stays legible where it was
  written, beside a dated note. Everything else in ADR-0136 stands, as §3 above
  states clause by clause.
- **ADR-0010 — nothing owed, and it is relied on more than before.** CI stays the
  backstop; §2 does not make it the substitute, because §1's anchor is the first
  line of defence and is unconditional. ADR-0010's remote gate, its triggers and
  its merge bar are untouched.
- **ADR-0167 — nothing owed.** `gate` as the only required check and "nothing
  crosses the gate red" are relied on as ratified and are what make §2 safe.
- **ADR-0166 and ADR-0179 — nothing owed.** They decide what discharges the
  anchor's `pytest` step; this decides which tree the closing anchor runs on and
  what the author does afterwards. ADR-0179 §5's clause that ADR-0136 §1 "stands
  exactly as ratified" is a statement about what *that* ADR changed, and it stays
  true: ADR-0179 changed nothing there. A reader arriving at ADR-0136 through it
  meets ADR-0136's own `Status` line, which now names this decision — which is
  the append-only mechanism doing its job rather than a second record being owed.
- **ADR-0138 — nothing owed.** The handoff arms count review rounds; this changes
  no round and no count.
- **Other ADRs' descriptions of the superseded clause — nothing owed.**
  ADR-0015's amendment note, ADR-0165's gate bullet, ADR-0166 §5 and ADR-0179 §5
  each restate or rely on ADR-0136 §1 in passing. None is made false: they record
  what *those* decisions did to ADR-0136, and each is a pointer to ADR-0136,
  whose `Status` line now names this decision. That is the append-only mechanism
  working rather than four further records being owed (ADR-0082 §1's test is
  about a reader held by a document, and every such reader is delivered to
  ADR-0136's header). ADR-0165's specific claim — that the closing anchor falls
  *after* the ratification flip, so the full gate runs on the flipped tree —
  stays true under §1, because the flip is part of the tree of the final push.
- **ADR-0089 — this ADR is marked**, and its normative clauses are the whole of
  what it imposes.
- **This ADR's `Status`.** It decides no Protocol and no `core/types.py` value,
  so the required review set is adversarial alone (ADR-0015 §1;
  `CONTRIBUTING.md` → "Stop when the required reviews are green"). It was drafted
  and revised as `Proposed`, with the status flipped only after the required
  review returned clean, per ADR-0165's exempt flip.

## Consequences

**Easier.**

- **The tail of a lane collapses from two serial waits to one.** The anchor's two
  to nine minutes may now overlap CI's, and CI's is no longer waited on at all.
  On a lane that rebases twice after reporting, that is three tails rather than
  one.
- **The anchor's tree becomes checkable.** Run after the push, the anchor's tree
  is a pushed SHA, so "the gate passed on the tree that shipped" stops being a
  claim only the author can make. A coordinator verifying a lane can compare the
  reported anchor to the PR head instead of taking the pytest line on trust.
- **One CI run instead of two, where the flip is prompt.** The
  `ready_for_review` run supersedes the in-flight `synchronize` one under
  `gate.yml`'s `concurrency` block, and only the survivor is what the merger
  reads. Waiting for the first and then triggering the second is the version that
  pays twice.
- **A pending check stops being a reason to hold a report.** The coordinator's
  own guard already covers pending; a lane that reports promptly hands over
  earlier, which is where wall clock is actually won in an ordered batch.

**Harder.**

- **An environment-only CI failure now lands on the coordinator.** A gate that is
  green locally and red remotely — a locked-environment difference, a runner
  timing sensitivity — is discovered after the lane has reported, possibly after
  its session has ended, and costs a re-dispatch rather than an in-session fix.
  This is the wait's one real product, and it is given up knowingly. It is
  bounded by the clean-tree refusals in `codex-review.sh` and `ship`, which
  already exclude the commonest local-only cause.
- **"The lane reported, so CI was green" stops being an available inference.**
  Nobody is entitled to it now, which is closer to the truth than before —
  `SKILL.md` already ranked the lane's paste below the coordinator's own check.
  What changes is that the coordinator must actually run the check rather than
  read it, which is the sequence that file already prescribes.
- **A cancelled predecessor run becomes routine on the PR page.** It is invisible
  to `gh pr checks` (Context, above) but visible in the Actions list, where it
  reads as a cancellation rather than as a supersession. Anyone reading run
  history rather than check status has one more thing to interpret.

**Follow-on.** `.claude/agents/worker.md` carries §1 and §2 operationally in this
same change, and `CONTRIBUTING.md` → "When the full gate is owed, and when it is
not" and `CLAUDE.md`'s gate paragraph take §1's restatement — both are ADR-0027
§3 floor paths, so each is edited to exactly the sentence that restates the
ordering. Neither of those two documents instructs a CI wait today, so §2 has no
stale sentence to correct there and gains no new one: its operational home is
`worker.md`, where the report field that produced the wait lives.
`.claude/skills/dispatch-agents/SKILL.md` takes the one-clause correction named
in §4. No lane is left behind this: everything the decision needs lands with it.

**Revisit if** a post-report red `gate` that the closing anchor could not have
caught is observed more than once in a wave (the wait was buying something, and
§2 is the clause to examine), or if the merger's `--fail-fast` guard is ever
observed tripping on a superseded, cancelled run (the Context measurement did not
generalise, and the prompt flip in §2's wake is what made it common), or if CI
ever stops running on `ready_for_review` (§2 assumes that run exists for the
merger to read).
