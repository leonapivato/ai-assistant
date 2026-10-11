# 310. CI's gate may split its test step across parallel jobs, and the triad evidence stays in one

- Status: Proposed
- Date: 2026-10-11
- Authorization: the owner directed on 2026-10-11 that CI's test run be split across
  parallel jobs, because CI's wall time is now the feedback loop every lane waits on.
  The dispatcher assigned 0310. The workflow change is a separate lane, briefed
  against this ADR's merged text.
- **Changes no `core` surface.** No Protocol, no type in `core/types.py` and no
  runtime behaviour is decided here. The local commands (`uv run pytest`,
  `just test-fast`) are untouched.
- **Partially supersedes**
  [ADR-0179](0179-the-triad-check-reads-a-distributed-runs-merged-record-so-both-gates-run-across-cores.md)
  (§3:1's refusal to split the test step across jobs, and its order across them),
  [ADR-0010](0010-remote-ci-and-github-workflow.md) (the "Remote gate" clause's one
  job `gate` running the five steps in order) and
  [ADR-0216](0216-the-page-is-executed-in-the-gate-by-a-browser-pytest-drives-and-the-text-layer-stays.md)
  (§3:4's one browser for the whole layer, as it reaches a split test step). §6 gives
  the test for each.

## Context

### What the gate costs, and where

`.github/workflows/gate.yml` is one job, `gate`, on a 4-vCPU `ubuntu-latest` runner.
The coordinator measured the last 23 green runs before this ADR at 620 s on average
(449–939 s). In run 38159008374 the steps took: `Tests` 315 s, the advisory citation
report 31 s, `mypy` 25 s, the browser install 20 s, `uv sync --locked` 16 s, the rest
a few seconds each. The suite is 38,788 tests. ADR-0179 measured 19,545 tests and a
113 s `Tests` step seven weeks earlier.

The tests' own times, summed over one whole run, are about 1,350 s. Four workers
cannot divide that much below 340 s, so a faster gate needs more runners.

### What stands in the way

Four ratified texts refuse or constrain a split.

- **ADR-0179 §3:1** says the test step stays whole and that "nothing is deselected,
  skipped or split across jobs", with ADR-0010's five steps "unchanged in number,
  kind and order".
- **The Protocol-triad check reads one session's record.** ADR-0179 §1:1 merges the
  workers' halves on the controller. §1:2 forbids carrying the evidence through a
  file "for a later invocation to read back". §2:1 makes an undecided check a
  failure. A job running a share of the suite holds a share of the record. Read as
  a whole run, it reports every Protocol whose binding ran elsewhere as unbound.
  Read as a narrowed run, it skips both checks, which is a silent pass.
- **The browser layer.** ADR-0216 §3:4 starts one browser per `pytest` run, shared
  by "every case in the layer", so `loadgroup` keeps the layer on one worker
  (`_ONLY_DISTRIBUTION` in `tests/conftest.py`). §6:1 lets the layer skip where no
  browser is installed, and §6:2's unconditional CI install keeps that skip out of
  the gate.
- **The required check.** ADR-0010's "Remote gate" clause has "job `gate`" run the
  five steps in the local order. ADR-0167 §1:1 requires the `gate` check on `main`,
  and branch protection names that context with no app restriction.

### Two ways to keep the triad whole

**Carry the evidence between jobs.** Each job would upload its half and a final job
would decide. That supersedes ADR-0179 §1:2 outright. It also brings back the hole
§1:2 closes: a decision read from an artifact that any step of the run can write,
made by a process that ran no tests. Rejected.

**Keep the evidence in one job.** ADR-0179 split the evidence at the process
boundary. What a class *could* bind is `static_candidacy(cls)` in
`tests/core/test_protocol_triad.py`, which is a property of the class alone. So a
partition can call it at collection time and send every class it names to one job.
On this tree it names 68 classes holding 4,782 items, 12% of the suite. The other
`Test…Contract` subclasses, about 10,500 items, are not candidates, so nothing they
report is evidence. This keeps §1:1, §1:2 and §2:1 exactly as ratified, at the cost of
one job carrying a known extra share. Chosen.

### The spike

A throwaway branch (draft PR #2817, closed unmerged) ran the split on real runners.
Every test job collects the whole suite and keeps its share. Triad-evidence items
and `tests/core/test_protocol_triad.py` go to job 0. Every other item goes by a hash
of its node id, or of its `xdist_group` name where it has one (run 2 below divides
the browser layer by node id). The cut points are
weighted so job 0's share, evidence included, is about equal to the others' by
count. In every layout the jobs' summary lines added up to 38,788 items, the whole
suite, with the same 100 skips as the single job, and job 0 passed both triad
checks.

**Run 1, with the browser layer kept in one job** (run 38160469111, one push):

| test jobs | slowest test job | its `Tests` step | browser layer, summed case time |
| --- | --- | --- | --- |
| 1 | 513 s | 460 s | 291 s |
| 2 | 372 s | 318 s | 255 s |
| 3 | 344 s | 291 s | 231 s |
| 4 | 325 s | 267 s | 206 s |

The static steps, as a job of their own, took 72 s. A test job's setup took 45–55 s:
checkout, `uv sync`, and 20–26 s of browser install.

The layer sets the floor. With 353 cases on one worker, it is 200–290 s of the
slowest job whatever the job count. Kept whole, a split gate bottoms out near five
and a half minutes.

**Run 2, with the browser layer divided among the jobs, one browser per job**
(run 38161287380):

| test jobs | slowest test job, first attempt | second attempt |
| --- | --- | --- |
| 2 | 322 s | 327 s |
| 3 | 247 s | 242 s |
| 4 | 216 s | 201 s |

The static job took 60 s and 76 s, and `gate` started 2–8 s after the last part
finished. The whole check is therefore about 3.5 minutes at four test jobs, a
little over 4 minutes at three, and 5.5 minutes at two. The single job it replaces
took 8.5 minutes on the same commit. Divided four ways, the layer's cases still sum
to 280 s, at 41–91 s per job.

## Decision

**We will let CI's `gate` workflow run its test step as several parallel jobs over
one partition of the suite. Every item that can be triad evidence stays in one of
those jobs, the browser layer may be divided with one browser per job, the static
steps run beside the tests, and `gate` stays the one job that passes only when
every part passed.**

### 1. One partition, and its union is the whole suite

> **Normative.** CI's `gate` workflow may run its `pytest` step as several parallel
> jobs, each a `pytest` session distributed across its runner's cores over its own
> share of one partition of the suite.

> **Normative.** Every test job collects the whole suite and keeps its share by an
> assignment every job computes identically. Each collected item is assigned to
> exactly one job index, and the assignment reads nothing that changes with the
> index of the job computing it.

> **Normative.** Every index the assignment can produce is a job the workflow runs.
> The partition is the only selection: apart from ADR-0179 §3:3's hand-over of the
> two triad checks to the controller, no job deselects anything or narrows its run
> by an option or environment variable.

> **Normative.** The number of test jobs is fixed in the workflow and chosen against
> measurement. Changing it owes no ADR while this decision's other clauses hold.

Taking each job's index and the job count from the matrix's own
`strategy.job-index` and `strategy.job-total` makes the third clause hold by
construction. An item whose node id differed between two collections of one tree
could still fall between shares, but not silently: every job is distributed, and
xdist refuses a session whose workers collected different items, so such an id
would fail the job that collects it.

### 2. The triad's evidence stays in one job

> **Normative.** Every item of a class for which `static_candidacy` in
> `tests/core/test_protocol_triad.py` names a Protocol, and every item of that
> module, is assigned to the partition's first index: the evidence job. The
> partition calls that function and does not restate its predicate.

> **Normative.** In the evidence job both evidence-dependent checks are decided over
> that session's record and never skipped. The partition kept every evidence item
> there, so the session is whole for the triad, and ADR-0179 §2:1 binds it as it
> binds an unfiltered session. Any other narrowing of that job fails both checks
> rather than skipping them.

> **Normative.** Every other test job is a narrowed run for the triad. It decides
> neither check, and ADR-0179 §2:1's clause about an unfiltered session handing no
> check over does not reach it.

> **Normative.** ADR-0179 §1:1 and §1:2 govern the evidence job's session unchanged.
> No job, artifact or step carries any part of the triad record from one job to
> another.

The evidence job is index 0, which exists at every job count, so it cannot be
dropped without breaking §1's third clause. A failed or skipped evidence job fails
`gate` under §5.

### 3. The browser layer may be divided, and every test job can run it

> **Normative.** The partition may divide the browser layer among test jobs. Each
> job runs its share in one `pytest` run, which starts one browser and shares it
> across every case of the layer in that share. ADR-0216 §3:4's first sentence
> binds each job's run unchanged.

> **Normative.** Every test job installs the browser build as an
> environment-preparation step, unconditionally. The layer's cases then run
> wherever the partition puts them, and none takes ADR-0216 §6:1's skip in CI.

ADR-0216 §3:4 exists for memory on one machine: one browser per worker would
multiply about 570 MB by the core count, on a VM that concurrent runs had already
taken down. Each test job is a separate runner, so dividing the layer among jobs
adds no browser to any machine. It gives up only the single shared start, about
0.9 s per extra job.

Whether another `xdist_group` is divided is the implementation's call. Dividing
one repeats its shared session setup in each job that holds a share. Within a job,
`loadgroup` keeps that job's share of any group on one worker, as before.

### 4. The static steps run beside the tests

> **Normative.** The four static steps (`ruff format --check`, `ruff check`, `mypy`,
> `lint-imports`) run in that order in one job of their own, concurrently with the
> test jobs.

The steps keep their number and kind. Their order now holds within each job and
not across jobs. In the local gate, order fails cheaply first on one machine. On
parallel runners the static job's verdict arrives first anyway (60–76 s in the spike),
and a static failure no longer withholds the test verdict. The advisory citation
report (ADR-0088 §3) is not a gate step. It can run in the static job after the
four steps, under the condition it has today.

### 5. `gate` passes only when every part passed

> **Normative.** The workflow has exactly one job whose check is named `gate`, and
> that check is the context ADR-0167 §1:1 requires. No other job's check carries
> that name.

> **Normative.** `gate` depends on every other job of the workflow, runs whatever
> their outcome, and succeeds only when each of them concluded `success`. A part
> that failed, was cancelled or was skipped fails it.

GitHub counts a skipped required check as passing. With an ordinary `needs`, `gate`
would be *skipped* when a test job failed, and the merge path would read that as
green. This is the one way a split gate can let red through, and the second clause
closes it. It also covers ADR-0288 §1:2 job by job: a part carrying a draft
condition would be skipped on a draft and fail `gate`.

The branch protection on `main`, ADR-0288 §1:1's trigger set and the workflow's
`concurrency` block are unchanged.

### 6. What this records against earlier ADRs

By ADR-0070 §1's test, a reader acting on each ADR below would refuse the workflow
§§1–5 allow. Each is therefore partially superseded, recorded on its `Status` line
and in a dated header note, with no ratified text rewritten.

- **ADR-0179 §3:1.** Replaced: "or split across jobs", and "nothing is deselected"
  as it reaches a partition's assignment of an item to another job. Also replaced:
  "order" across jobs. Kept: each job distributes across its runner's cores, the
  jobs' union is the whole suite, ADR-0010's five steps keep their number and kind,
  and nothing else is deselected or skipped. ADR-0179 §§1–2 and §3:2-4 are
  untouched.
- **ADR-0010's "Remote gate" clause.** Replaced: that job `gate` runs the five steps,
  and that their order mirrors the local gate across the workflow. Kept: the five
  steps, on every pull request and every push to `main`, against the locked
  environment, as the same gate on neutral ground. Its other clauses and
  ADR-0167's supersession are untouched.
- **ADR-0216 §3:4's second sentence**, "The browser is started once and shared by
  every case in the layer", as it reaches a test step split across jobs. There it is
  started once per job holding a share. Kept: §3:4's first sentence, and the whole
  clause for every single `pytest` run, local runs included. §3:3 is untouched. It
  is about the local anchors, and no case is left out of every job.

ADR-0166 §4:2, the serial-CI clause, was already superseded by ADR-0179 and takes
nothing. ADR-0136, ADR-0167, ADR-0180 and ADR-0288 are untouched.

## Consequences

**Easier.**

- **Every push gets its gate back sooner.** On the spike, three test jobs bring the
  check from about 8.5 minutes to about 4, and four bring it to about 3.5.
- **A static failure and a test failure are both reported on one push.** Today a
  formatting slip hides the test verdict until the next push.
- **The number of jobs is a tuning knob.** §1's last clause lets the implementation
  move it as the suite grows, with no ADR.

**Harder.**

- **More runner time per push.** Each test job pays 45–55 s of setup and about 10 s
  of collection. Minutes are free for a public repository on standard runners. The
  real limit is concurrency: the free plan runs about 20 jobs at once across the
  account. With *N* test jobs a push holds *N* + 1 runners while it tests, and
  `gate` follows briefly. At three test jobs, five lanes pushing at once fill the
  20. At four they would need 25, and a burst would queue. This ADR's measured recommendation is three test jobs to
  start with. Runner time per push rises from about 8.5 minutes to 12–13.
- **CI's verdict is no longer one summary line.** Each test job prints its own, and
  the shares add up to the suite. JUnit XML omits the two triad verdicts the
  controller reports (issue #2823), so it is not the place to check that sum.
- **The evidence job carries a known extra share.** The partition weights it out.
  If contract bindings grow faster than the rest, that job becomes the critical
  path, and its cut needs re-weighting.

**Follow-on.** One implementation lane writes the partition, as a `tests/` plugin
that calls `static_candidacy`, and the workflow. It also covers the tests that pin
§1's completeness and §2's no-skip rule in the evidence job, and it reports the
measured wall time. The browser layer is now 200–290 s of summed case time, against
ADR-0216 §3:5's 60-second budget. That is §3:5's own revisit condition, met; it is
filed as issue #2822 and is not decided here.

**Revisit if** the evidence job becomes the slowest job and re-weighting cannot fix
it; if a split gate is seen passing while one share of the suite did not run; if
GitHub's concurrency limit queues pushes routinely; or if the browser layer's cost
is cut enough that keeping it in one job no longer costs a minute or more.
