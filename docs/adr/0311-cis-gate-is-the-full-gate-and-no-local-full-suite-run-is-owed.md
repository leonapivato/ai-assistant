# 311. CI's `gate` is the full gate, and no local full-suite run is owed

- Status: Proposed
- Date: 2026-10-11
- Authorization: the owner decided this on 2026-10-11, in conversation with the
  dispatcher, as owner-directed maintenance under no milestone. The dispatcher
  assigned 0311. This PR records the decision and the rulings it replaces; the
  standards, recipes and agent instructions are a separate implementation lane
  (§6).
- **Partially supersedes**
  [ADR-0136](0136-the-full-gate-is-owed-at-two-anchors-and-between-them-the-fast-gate-suffices.md),
  [ADR-0166](0166-the-parallel-suite-may-serve-as-the-pytest-step-at-both-anchors.md)
  and
  [ADR-0180](0180-the-closing-anchor-binds-the-tree-of-the-final-push-and-a-lane-does-not-wait-on-ci-to-flip-ready.md).
  §5 names each clause and applies ADR-0070 §1's test to it.

## Context

### What a branch owes locally today

ADR-0136 §1:1 requires the full gate, the whole `pytest` suite included, at two
anchors: before the first review invocation and on the final push before
`just ready`. §1:3 and §1:4 require it again after every rebase that moves the
base, before the next review and before the rebased head is pushed for merge.
ADR-0166 §1 lets `just test-fast` discharge either anchor, ADR-0180 §1 binds the
closing anchor to the tree of the final push, and ADR-0180 §2:1 lets a lane flip
ready without waiting on CI, because the closing anchor has already proved the
tree locally.

### What CI already does on the same tree

`.github/workflows/gate.yml` runs ADR-0010's five steps on every push to an open
pull request, drafts included (ADR-0288 §1:1, §1:2), and its `pytest` step is the
whole suite (ADR-0179 §3:1). `gate` is a required check on `main` under `strict`
up-to-date enforcement (ADR-0167 §1:1), and nothing crosses it red (ADR-0167
§2:2). Under `strict`, a head that may merge contains the current base tip, so the
run its own push started tested the tree that lands (ADR-0288's Context works
this through).

So the closing anchor and both rebase re-runs test, on the author's machine, the
exact tree CI tests on the pushed head. What the local copy adds is earlier
knowledge. The local copy is also expensive in a parallel wave. On 2026-09-09 one
run took about three minutes across cores and about twenty-six serially, and two
concurrent runs took 411 seconds each (#2162). Lanes waited for `TEST_FAST_SLOTS`,
the WSL VM has crashed out of memory under concurrent suites, and shell settings
have produced test failures unrelated to any diff.

### Where #2162 stood

#2162 asked whether the gate obligations should change. Its 2026-09-09
measurement recommended retaining every obligation and spending the effort on
slow tests instead. **The owner has overruled that recommendation.** The cost is
not only one run's wall clock. It is concurrent lanes contending for one machine,
and only removing the runs removes that.

### What changes about waiting on CI

ADR-0180 §3:1 states why a lane need not wait on CI: "what §2 removes is the wait
on a second opinion about a tree the author has already proved, not the proof".
Once no local run proves the tree, CI's run is the only proof. The wait returns,
at the one point where it matters, the flip to ready.

## Decision

**We will treat CI's required `gate` as the full gate. A branch owes no local
whole-suite run. Before the first review it owes the tests for what it touches,
and it is marked ready only on a green `gate`.**

### 1. No local whole-suite run is owed

> **Normative.** No local run of the whole `pytest` suite is owed at any point on a
> branch: not on the final push, not before `just ready`, and not after a rebase,
> whether or not the rebase moved the base. The full-suite run a branch owes is
> CI's `gate` on its pushed head.

The whole suite, serial or `just test-fast`, stays available to an author who
wants it, and is never wrong.

### 2. Before the first review, the tests for what the change touches

> **Normative.** Before the first review invocation on a branch, the author runs
> the tests for what the change touches, on the tree to be reviewed, and they pass.
> Which tests those are is the author's call. No justification is owed for the
> selection, and no reviewer may require a particular one.

> **Normative.** That run is owed once per branch. A later review invocation does
> not re-open it, and neither does a rebase.

"What the change touches" includes tests that read a changed file, not only the
tests under the mirrored path. A diff confined to `docs/adr/` is read by
`tests/scripts/test_adr_citations_corpus.py`, and a diff under `scripts/` is
driven by `tests/scripts/` (#2194). That is guidance, not an obligation: the
selection stays the author's.

**The accepted cost.** A cross-package break that the selection misses surfaces in
CI after the review has run. The fix is a new commit, and the commit costs a
review round. The owner accepted that cost against the local full suite's cost in
parallel waves.

### 3. The four static steps stay before every commit

> **Normative.** `ruff format`, `ruff check`, `mypy` and `lint-imports` are run and
> pass before every commit on a branch.

This is ADR-0136 §2:1, unchanged in substance. With no closing anchor to end
"between the anchors", it runs to the merge. ADR-0136 §2:2's `pytest` discretion
likewise covers every point except §2 above.

### 4. `just ready` refuses unless `gate` is green on the PR head

> **Normative.** A pull request is marked ready only while the `gate` check is
> green on its current head commit. `just ready` refuses while that check is
> pending, failing, cancelled or absent for that commit, and the refusal names the
> state it saw.

> **Normative.** A dispatched lane makes its finishing report after `just ready`
> has succeeded, and reports `gate` green. A report of a stop, a handoff or a
> request for a ruling is not a finishing report and waits on nothing.

> **Normative.** `just ship` is not held for the `gate` check.

> **Normative.** A push made after the pull request is marked ready, such as a
> rebase onto a moved base, owes the lane no local test run and no wait on `gate`
> before it reports the push. The merger's check under ADR-0180 §2:3 reads that
> push's run.

The refusal sits in the recipe ADR-0165 §5:1 already makes the only way out of
draft, beside its refusal on an ADR still `Proposed`. Whether the recipe also
waits for a pending run, and how it reads the check, are the implementation's
choice. It never flips on a pending check.

The merge is governed as before. ADR-0180 §2:3 stands: the merger runs
`gh pr checks --watch --fail-fast` immediately before merging, and branch
protection refuses a red or stale `gate`.

### 5. What this supersedes, and what it leaves standing

Each clause below fails ADR-0070 §1's test: a reader holding only the earlier ADR
would run a local whole suite, or flip ready without a green `gate`, where this
decision directs otherwise. Each is replaced by a different rule, not reconciled
with its own text or with a later fact, so each is a **partial supersession**.
The record is a `Status` pair and a dated header note on each earlier ADR, and no
ratified text is rewritten.

- **ADR-0136.** Superseded: §1:1 in two scopes, its closing anchor and its
  requirement of the whole suite at the first anchor, which §2 above replaces;
  §1:3 and §1:4, the rebase clauses; and §3:2, which refused the flip to ready
  without a local full run and which §4 replaces. Standing: §1:2, which now
  governs §2's run; §1:5, whose proviso naming the rebase clauses now has nothing
  to bind; §2, whose first clause §3 restates; §3:1, so a red push on a draft is still
  information, not a defect; and §5:1. ADR-0136's later partial supersession by
  ADR-0180 overlaps on the closing anchor, and this decision, the later one,
  governs the overlap (ADR-0070 §4).
- **ADR-0166.** Superseded: §1 whole. Its three clauses say what discharges an
  anchor that requires the whole suite, and none is left. §1:2 also refuses a
  narrowed run at an anchor, which §2 above permits. Standing: §2:1, that the
  serial suite is never wrong, and §4.
- **ADR-0180.** Superseded: §1 whole, the closing anchor; §2:1 and §2:2, which
  held neither `just ready` nor the report for CI; and §3:1, which restated
  ADR-0136 §3:2. Standing: §2:3, the merger's check, which §4 relies on; §3:2; and
  §3:3. Its `Status` line takes the leading token, and the qualifier for ADR-0288
  moves off it into the existing 2026-10-04 note (ADR-0082 §2).

**Nothing is owed on ADR-0179.** §3:2 to §3:4 describe `just test-fast` and the
distributed triad check CI still runs on. Where they speak of anchors, they say
what discharges one, which is now vacuous, not false.

**Clauses that say ADR-0136 §1 "stands" are not superseded.** These are ADR-0166
§4:1, ADR-0179 §5:1 and ADR-0180 §3:2. Each states what that ADR left untouched,
which stays true, and a reader following one reaches ADR-0136, whose `Status`
line names this decision. That is how ADR-0180 §5 read ADR-0179 §5, and this
decision reads all three the same way.

**Nothing is owed on ADR-0216, ADR-0165, ADR-0010, ADR-0167 or ADR-0288.** ADR-0216
§3:3's obligation is that no recipe deselects the browser layer, and it stands;
its "runs at both of ADR-0136 §1's anchors" was a consequence of that and is now
vacuous. ADR-0165's gate bullet is unmarked prose in a marked ADR (ADR-0089 §3),
and its substance holds: CI gates the flipped head and §4 waits for it. The other
three are relied on as ratified.

### 6. What the implementation lane changes

Nothing here edits these; the lane is briefed against this ADR once it has
merged.

- `CLAUDE.md` → "The gate (Definition of Done)".
- `CONTRIBUTING.md` → "The gate (Definition of Done)", "When the full gate is
  owed, and when it is not", the "After the gate is green" paragraph under
  "Review (pre-merge)", the "CI gates the PR" bullet, and "Report the review,
  then mark it ready".
- `.claude/agents/worker.md`: the rebase-and-gate bullet, "Finishing", "You are
  probably not finished when you report", and the report's pytest and
  `gh pr checks` line.
- `.claude/skills/dispatch-agents/SKILL.md` §3: the paragraph reading the
  worker's pytest line as evidence of the closing anchor.
- The `ready` recipe in `justfile`, to carry §4's refusal; and the comments in
  `justfile`, `.github/workflows/gate.yml` and `tests/conftest.py` that describe
  anchors.

Issues the implementation lane closes or answers:

- **#2162**, whose recommendation to retain every obligation is overruled here.
  Its #1752 test speed-up thread is separate and continues.
- **#2194**, which is moot. The clause it disputes, ADR-0136 §2:3, was safe only
  because a whole-suite anchor followed it. Now no local run is owed anywhere,
  and §4 refuses ready on the red `gate` that a docs-only diff can produce.
- **#1243**, which is moot. No anchor run is left for `PYTEST_ADDOPTS` to narrow.
- **#2174**, which is partly addressed. A ready lane's refresh cycle loses its
  local re-gate, but the rebase, drill and ship steps remain.

`docs/review/guide.md`'s "Assume the gate is already green" does not change. It
is a scoping instruction, as ADR-0136 §6 argued: the reviewer runs no tests and
reports nothing `pytest` catches, whatever the tree. #994's proposed wording names
ADR-0136's two anchors, so whoever takes it up rewords it against this decision.

### 7. What this does not decide

- **What CI runs**, its triggers and its jobs: ADR-0010, ADR-0179 §3:1 and
  ADR-0288.
- **Review coverage**, and when a base move costs a round: ADR-0020, ADR-0025,
  ADR-0027, ADR-0209 and ADR-0165. A rebase still costs a round where those say
  so, and never because a local test run is owed.
- **Freshness.** Rebasing before the first review and before invoking a review
  remains `CONTRIBUTING.md` → "Run it against a current `main`".
- **Branch protection**: ADR-0167.

**This ADR's own branch.** It decides no Protocol and no `core/types.py` value, so
the required review set is adversarial alone (ADR-0015 §1). Until it merges, the
rules it replaces still govern, so this PR was gated at ADR-0136's anchors as
they stand.

## Consequences

**Easier.**

- **Parallel waves stop contending for one machine.** No lane holds a slot for a
  whole-suite run, so there are no slot waits and no out-of-memory crashes from
  concurrent suites.
- **A rebase costs a push, not a run.** This matters most for the lanes that
  rebase repeatedly, late in an ordered batch.
- **One authority for the suite.** A failure that only the local environment
  produced no longer blocks a lane, and a failure that only CI's environment
  produces is caught while the lane is still live. ADR-0180 gave up that catch
  knowingly, and this decision gets it back.

**Harder.**

- **A cross-package break is found after the review**, at the price of a fix
  commit and a round (§2).
- **A lane waits on CI before it flips ready.** The median successful `gate` run
  was 658 seconds on 2026-10-04 (ADR-0288's measurement). The wait is idle wall
  clock, not contention, and it is paid once per lane.
- **A CI flake or outage now holds the flip as well as the merge.** A flaky run
  is re-run, and an outage was already a merge block.

**Revisit if** CI finds a break after review often enough that the extra rounds
cost more than the local runs did, or if the wait before ready grows to dominate
a lane's wall clock.
