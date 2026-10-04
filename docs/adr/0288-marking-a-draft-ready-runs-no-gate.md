# 288. Marking a draft ready runs no gate

- Status: Accepted
- Date: 2026-10-04
- Authorization: the owner directed this on 2026-10-04 as one lane delivering one
  PR, the ADR and the `gate.yml` edit together. That departs deliberately from the
  usual split of an ADR and its implementation into two lanes. No Protocol and no
  `core/types.py` value is decided, so golden rule 5's separate merge does not
  apply. The dispatcher assigned 0288.
- **Amends** [ADR-0180](0180-the-closing-anchor-binds-the-tree-of-the-final-push-and-a-lane-does-not-wait-on-ci-to-flip-ready.md)
  in §4's first bullet, its trigger half, and in the third revisit trigger of its
  Consequences. **Amends**
  [ADR-0136](0136-the-full-gate-is-owed-at-two-anchors-and-between-them-the-fast-gate-suffices.md)
  in §4's first net, its list of trigger types, and in §6's first bullet as it reads
  that list. §4 below gives the test for each. Neither is a supersession: no marked
  clause of either moves.

## Context

### Why the trigger is there

`.github/workflows/gate.yml` lists four `pull_request` activity types, `opened`,
`synchronize`, `reopened` and `ready_for_review`. The first three are GitHub's
default set. The fourth was added in `a8658ff8` (2026-07-18, "ci(review): run Codex
review in CI, advisory and non-blocking"), and the comment above it says why:

```yaml
  # `ready_for_review` is explicit so marking a draft PR ready re-runs the gate —
  # which is what lets the codex-review workflow (ADR-0012) fire on that
  # transition via workflow_run. The other three are the default pull_request set.
```

ADR-0012 §1 had the adversarial review run automatically on the
`draft → ready for review` transition. It did that by listening for the gate's
completion through `workflow_run`, so the gate had to run on the flip. ADR-0012 is
`Superseded by ADR-0015`, which moved review back to the author's machine, and
`1f670715` deleted the codex-review workflow. `gate.yml` is now the only file under
`.github/workflows/`. Nothing listens for the run the flip starts. The reason given
in the comment no longer exists.

### What the flip's run tests

The gate job carries no condition on the pull request's draft state. A draft is
gated on `opened` and on every `synchronize` exactly as a ready pull request is,
which is what ADR-0136 §4's first net rests on. So by the time a lane flips ready,
its head SHA already has a gate run. Marking a draft ready changes no byte of the
branch.

The one input that can differ is the base. A `pull_request` run checks out
`refs/pull/N/merge`, the head merged into the base tip as it stands when the run
starts. Branch protection on `main` is `strict` (read on 2026-10-04: required
check `gate`, `strict: true`, linear history required), so a pull request merges
only when its head contains the current base tip. `main` only moves forward, so a
head that contains the current tip also contains every earlier tip, including the
one its own push was gated against. Merging such a head into that earlier tip
yields the head's own tree. The run the head's push triggered therefore tested
exactly the tree that lands, whenever the pull request is mergeable at all.

Where `main` has moved past the head, the pull request is `BEHIND` and cannot merge
until it is updated. The merger's guard in `.claude/skills/dispatch-agents/SKILL.md`
§5 checks for that before merging:

```bash
gh pr checks <n> --watch --fail-fast || exit 1
[ "$(gh pr view <n> --json mergeStateStatus --jq .mergeStateStatus)" = BEHIND ] && exit 1
```

The update is a push to the branch, and the push triggers `synchronize`. A run on
the flip in that state tests a merge of a head that will not land as it is. At
most it gives an early warning about the rebase.

### What it costs

ADR-0180's Context named this cost: a lane that waits for the `synchronize` run and
then flips ready "has bought a result that the flip immediately recomputes, on
identical content, at full price." ADR-0180 §2 stopped the wait. It did not stop
the second run, and it made the cancel-and-restart routine. A prompt flip starts
the `ready_for_review` run while the `synchronize` run is still going, and
`gate.yml`'s `concurrency` block (`group: gate-${{ github.ref }}`,
`cancel-in-progress: true`) cancels the older run. The merger's
`gh pr checks --watch` then waits for a run that started later, on the same
content.

Measured on 2026-10-04 over the 100 most recent `pull_request` runs of `gate`
(2026-10-01 16:57Z to 2026-10-04 04:40Z): 71 distinct head SHAs, 29 of which ran
more than once. 18 of those 29 were a cancelled run followed by a fresh one on the
same SHA, and 8 were two full successful runs. The median successful run took 658
seconds. The Actions API does not record which activity type started a run, so
these counts bound the flip's share from above. A second run on one SHA cannot come
from a push, though. A manual re-run is a new attempt of the same run, not a new
run. That leaves `ready_for_review` and `reopened`, and reopening is rare here. One
case read end to end: PR #2668 at `1bc8dcf8`. Run `37177147021` started at
04:29:31Z and passed at 04:39:18Z. The PR's timeline records `ready_for_review` at
04:40:07Z, and run `37177666790` started on the same SHA at 04:40:09Z and passed
at 04:48:53Z.

## Decision

**We will stop running the gate when a draft is marked ready.** The runs a
pull request's pushes trigger are the whole of CI's coverage of it, and they
already are the runs that cover what lands.

### 1. The flip triggers no gate run

> **Normative.** `.github/workflows/gate.yml` runs its `pull_request` job on the
> `opened`, `synchronize` and `reopened` activity types and on no other, so marking
> a draft pull request ready for review triggers no gate run.

> **Normative.** The gate job carries no condition on a pull request's draft state:
> a draft pull request is gated on every push exactly as a ready one is.

The second clause states what the first depends on. Dropping the flip's run is safe
only because the run the merger reads already exists while the pull request is
still a draft. A later edit that skipped drafts, to save CI minutes on work in
progress, would leave a newly ready pull request with no run on its head at all.
That edit has to answer to this clause first.

The comment above the `types` list says why the set is what it is, and points
here.

### 2. ADR-0180 §2 does not depend on the flip's run

ADR-0180 names this change as a reason to revisit it: "if CI ever stops running on
`ready_for_review` (§2 assumes that run exists for the merger to read)". This
section is that revisit. Its finding is that §2 stands entire.

ADR-0180 §2:1 has a lane ship, flip ready and report without waiting on `gate`.
§2:2 has the lane report the check as it stands, pending included. §2:3 makes the
merger's `gh pr checks --watch --fail-fast` and branch protection the check that
governs the merge. None of the three names the run the flip starts. What §2:3
needs is a `gate` result on the head SHA, and §1:2 above guarantees one, from the
push that made it the head. Under `strict` protection that run tested the tree
that lands (Context). ADR-0180 §4 read §2 as resting on the flip's run because,
when it was written, the flip's run was the latest run on a lane that flipped
promptly. It was never the only run. The same head's `synchronize` run was always
there, and it is what the guard reads once nothing supersedes it.

So ADR-0180 §§1 to 3 bind as ratified. The lane still does not wait, and the merger
still waits, now on a run that started at the push rather than a later one.

### 3. What this does not decide

- **The other triggers.** `opened`, `synchronize`, `reopened` and `push` to `main`
  are unchanged. `reopened` is open to the same argument on a branch that has not
  moved, but it is part of GitHub's default set, it is rare here, and nothing in
  this lane measured it.
- **The `concurrency` block and the job's steps.** Both are unchanged. ADR-0010's
  five steps and ADR-0216 §5's browser install stand as they are.
- **The merger's guard.** `.claude/skills/dispatch-agents/SKILL.md` §5 is relied on
  as written and is not changed.
- **What `just ready` does.** It still runs ADR-0165 §5's refusal and then
  `gh pr ready`. Only the CI side effect of the flip goes.

### 4. What this records against earlier ADRs

- **ADR-0180, amended in two places.** §4's first bullet says `gate.yml` keeps "the
  same four `pull_request` types", and that "§2 depends on `ready_for_review`
  continuing to trigger a run, because that run is the one the merger reads on a
  lane that never waited". After §1 the types are three. §2 above shows that the
  merger reads the head's own push run, so the dependency sentence is false as well.
  The Consequences' revisit trigger "if CI ever stops running on
  `ready_for_review`" has fired, and §2 above is the revisit it asks for. Neither
  sentence is a marked clause. ADR-0180 is a marked ADR, so they impose nothing
  (ADR-0089 §3). Every marked clause, §1:1 to §3:3, binds unchanged, and a reader
  holding only ADR-0180 acts identically before and after. That makes this an
  amendment that reconciles the ADR with a later fact, not a supersession
  (ADR-0070 §1). ADR-0180's `Status` line has no leading supersession token, so the
  record takes a qualifier there and a dated header note (ADR-0082 §1). The
  Context's fourth fact and the Consequences bullets "One CI run instead of two,
  where the flip is prompt" and "A cancelled predecessor run becomes routine on the
  PR page" describe the workflow as it stood on 2026-08-22. They stay legible as
  written, and the note says they no longer describe it.
- **ADR-0136, amended in one place.** §4's first net says `gate.yml` "triggers on
  four `pull_request` types — `opened`, `synchronize`, `reopened`,
  `ready_for_review`". After §1 it triggers on three. §6's first bullet says §4
  "depends on CI's being unchanged — including on the trigger set". The net does not
  rest on the type this change removes: §4 names `synchronize` as "the one that
  carries this net", and that type, the net's reliance on the draft PR being open,
  and its one gap are all unchanged. §1:2 above keeps the run free of any draft
  condition, which the net needs. A reader holding only ADR-0136 acts identically,
  so this is an amendment and not a supersession (ADR-0070 §1). ADR-0136's `Status`
  line leads with `Partially superseded by`, so the record is the dated header note
  alone, and the line is not edited (ADR-0082 §2).
- **ADR-0015, nothing owed.** The header note ADR-0136 wrote on it says the remote
  gate runs "on the triggers `.github/workflows/gate.yml` declares — four
  `pull_request` types and `push` to `main` … as ADR-0136 §4 states", and that
  "ADR-0136 §4 depends on that being unchanged". The note restates ADR-0136 §4 and
  sends its reader there, and ADR-0136's header now carries the record. That is the
  append-only mechanism doing its job, as ADR-0180 §5 ruled for the notes that
  restated ADR-0136 §1. What the note relies on, "every push to an open PR but not
  a push to a branch with no PR", stays true.
- **ADR-0012, nothing owed.** It is superseded whole. Its §1 transition review is
  what the trigger served, and that review has not existed since ADR-0015.
- **ADR-0010, nothing owed.** "on every pull request and every push to `main`"
  stays true. Its 2026-08-22 amendment's "on the same triggers" was true on its
  date, and it compares that change with what came before it.
- **ADR-0167, nothing owed.** `gate` stays the only required check, and nothing
  crosses it red.
- **Operational text.** `.claude/agents/worker.md`'s finishing bullet gave "flipping
  ready starts a fresh `gate` run over the same content anyway" as a reason not to
  wait. That sentence becomes false, and it is corrected in this change.
  `CONTRIBUTING.md`'s "Nothing automated fires on the transition itself
  (ADR-0015)" was written about review. It is now true of CI as well, and it needs
  no edit.
- **This ADR's `Status`.** It decides no Protocol and no `core/types.py` value, so
  the required review set is adversarial alone (ADR-0015 §1; `CONTRIBUTING.md` →
  "Stop when the required reviews are green"). It is drafted as `Proposed` and
  flipped by ADR-0165's exempt commit once that review is terminal.

## Consequences

**Easier.**

- **One gate run per pushed head.** The flip's run on identical content is gone,
  and with it the run `concurrency` cancelled when a lane flipped promptly. In the
  last 100 runs that was at most 26: 18 cancelled and 8 complete re-runs.
- **The merger's signal arrives sooner.** `gh pr checks --watch` waits on the
  run the push started. It no longer waits on a restart that began at the flip.
- **The Actions list stops showing a routine cancellation** on almost every lane,
  the cost ADR-0180's Consequences named.

**Harder.**

- **Flipping ready no longer re-tests against a moved base.** Where `main` moved
  between the last push and the flip, the old run would have tested the head merged
  into the newer tip, an early warning about the rebase. That warning is given up.
  The merge itself is unaffected: `strict` protection and the merger's `BEHIND`
  check force the update, and the update's push is gated.
- **A failed run is no longer retried by the flip.** A flaky or runner-side failure
  on the last push's run now stays red until someone re-runs it (`gh run rerun`, or
  the Actions page) or pushes again. Toggling a pull request back to draft and ready
  does nothing.

**Revisit if** branch protection on `main` stops being `strict` (Context's argument
that the push's run tested the tree that lands rests on it), if a pull request ever
reaches the merger's guard with no `gate` run on its head SHA, or if anything is
added that needs to fire on the `ready_for_review` transition itself.
