# 179. The Protocol-triad check reads a distributed run's merged record, so both gates run across cores

- Status: Proposed
- Date: 2026-08-22

## Context

### One check kept two gates serial

`tests/core/test_protocol_triad.py` is the mechanical enforcement of the
Protocol triad rule (`CONTRIBUTING.md` → "Adding a Protocol"): every Protocol in
`core/protocols.py` has a `<Protocol>Contract` conformance suite, a
`Fake<Protocol>` in `ai_assistant.testing`, and — the part no file-existence
check can make — a binding subclass that really ran the fake through the suite
and passed. It answers that last question by reading the record
`tests/conftest.py` builds from pytest's own call-phase reports.

Under `-n auto` that record is per process. Each xdist worker runs its own
session over a share of the items, so a contract subclass that passed on `gw3`
is simply absent from `gw0`'s record, and the check — which runs on exactly one
worker — reports **every** Protocol as missing its binding. Measured on this
tree before this change: `uv run pytest -n auto` gave `1 failed, 19451 passed`,
the one failure being the triad check reporting all thirty-odd Protocols.

Two decisions rest on that fact and only on that fact:

- `just test-fast` passes `--deselect tests/core/test_protocol_triad.py`, so the
  recipe ADR-0166 §1 admits at either ADR-0136 anchor is 31 tests short of the
  suite. ADR-0166 §3 states that gap as a **normative** accepted risk, and
  ADR-0166 §2 tells a lane to prefer the serial run when its diff touches a
  Protocol or a canonical fake.
- CI's gate stays serial. ADR-0166 §4 says so in as many words — "CI's gate
  stays the full five steps, serial" — and §3's first net, the one that makes
  the local deselection payable, is that CI runs the triad check on every push.

ADR-0166's own **Revisit if** names this exact escape: "the triad check is made
to run under `-n auto` (the deselection goes, §3's whole risk goes with it, and
§1 becomes unconditional in fact as well as in rule)".

### What it costs to leave serial

The last `gate` run before this change took 5m28s, of which **Tests were 273s**;
the type check was 31s and everything else seconds. `ubuntu-latest` gives this
public repository a 4-vCPU runner. That 273s is paid on every push to an open PR
and every push to `main`, and a lane merging late in an ordered batch under
`strict` branch protection pushes several times. Distributed, the same step on
the same runner is 113s and the whole job 2m45s.

Locally the same suite is 19,488 tests: about eight minutes serial against about
two distributed on this eight-core machine (ADR-0166 measured 497.33s against
88.97s on a smaller tree). ADR-0136 §1 obliges two full runs per branch and one
more per base-moving rebase.

### Why the check could not simply be distributed

The record is not only names. Deciding whether a class binds a Protocol's fake
means asking what its fixtures *produce* — `_binds_fake` evaluates them and
checks the object's type, because a name, an import or a lexical mention was a
way past every earlier draft of this check. That needs the live class object,
and a class object does not cross a process boundary.

Two shapes of fix were available.

- **Pin the distribution.** `--dist loadscope` puts every method of a class on
  one worker, so each worker's record is complete for the classes it ran and the
  controller could union a set of protocol names. It is much less code. It is
  also wrong under the default `--dist load`, which `just test-fast *args` still
  admits, and it is not free: 5,047 of the suite's 19,488 tests are in
  `Test…Contract` classes, so one worker would carry 26% of the suite and become
  the critical path on an eight-core machine.
- **Split the evidence at the seam the process boundary actually falls on.**
  What a class *could* bind is static and is computed where the class objects
  are; which obligations actually ran is names, and names travel. This holds
  under any distribution mode, and is what this ADR ratifies.

The second needs one further thing the first does not: somewhere to *decide*.
Under xdist the controller runs no tests, so the two evidence-dependent checks
cannot run on any worker and cannot run on the controller either — as tests. The
mechanism below reports them from the controller through the same hook every
worker's result already travels on.

## Decision

**We will make the Protocol-triad check read a distributed run's merged record,
and run both gates' `pytest` step across cores.**

### 1. The record is merged in the one process that outlives every worker

> **Normative.** The Protocol-triad check's evidence is split at the process
> boundary: what a recorded class *could* bind is computed in the process that
> holds the class object, and what it actually honoured is carried as test
> names. In a distributed session each worker hands its half to the controller
> through xdist's own worker-to-controller channel, the controller unions the
> halves, and the evidence-dependent checks are decided there over the union.

> **Normative.** The evidence travels through pytest's and xdist's own channels
> — call-phase reports within a session, `workeroutput` between processes. It is
> never written to a file for a later invocation to read back, and no command-line
> argument may supply it.

The second clause is the first one's whole point rather than an implementation
note. This check exists because file-shaped evidence proves nothing: a
conformance suite bound by a class pytest never collects runs zero assertions,
and so does one whose tests are all collected and then skipped, and neither is
visible to anything that inspects artifacts rather than outcomes. A merged record
handed between two `pytest` invocations through a path on disk is exactly such an
artifact — satisfiable by a stale file from an earlier tree, or by a hand-written
one — so the mechanism that makes the check distributable must not reintroduce
the hole the check was built to close.

Union rather than intersection, and per test name: with the default distribution
one class's parametrized cases are split across workers, so no worker holds a
whole binding. For the same reason the satisfactory set is derived *after* the
union — a case that failed on one worker vetoes the same name reported
satisfactory on another.

### 2. A check no process decided is a failure, not a pass

> **Normative.** In a distributed session every item handed to the controller is
> decided, and every check the controller decides is reported under an item.
> Wherever that correspondence breaks — an item the controller has no evaluator
> for, a decision with no item to report it under, or an unfiltered session that
> hands no evidence-dependent check over at all — and wherever a worker leaves
> without handing its half of the record over, a failure is reported. None of them
> may be reported as passed or silently omitted.

> **Normative.** An evidence-dependent check is **unparametrized**, and that is
> part of the seam rather than an accident of it. The controller decides one
> outcome per test *function*, so a parametrized item requesting the evidence is
> refused under the clause above as an item nothing can decide — never reported
> under one of its cases, which would claim a verdict that was not computed for
> those arguments. `tests/core/test_protocol_triad.py` pins this, and the
> evaluator-coverage rule beside it, against **the collected items the seam
> itself selects** rather than against this module's function definitions — so
> both hold for a check written as a method on a `Test…` class, and for one
> parametrized by a `pytestmark` on its module or class, which are eligible here
> and invisible to a name-based guard. Caught where the check is written, in
> either run mode, rather than only where it is run.

This is the one place the arrangement can rot quietly. The items handed over are
identified by the fixture they request rather than by a list of test names, so a
check added later is handed over automatically — and would then be collected,
deselected on every worker, and decided by nobody. Failing loudly is the only
outcome that surfaces it; `tests/core/test_protocol_triad.py` also pins the
correspondence directly, so the failure is caught before a distributed run.

**Automatically, but not unconditionally**, which is why the restriction above is
stated where the promise is. Inheriting the arrangement by asking for the evidence
is what stops a new check going undecided; it is not a claim that every shape of
check fits through the seam. One does not: a parametrized check reaches the
controller as `…::test_x[one]`, and the merged record carries no per-case evidence
to decide it with. Making the evaluator address cases was considered and rejected —
it buys a shape nothing declares today, at the price of a case-aware payload on a
channel whose whole virtue is that it carries names. Refusing it, and saying so
where the check is authored, keeps the contract legible at the cost the seam is
already paying: an evidence-dependent check is a whole-suite verdict, and a
whole-suite verdict has one case.

The lost-worker clause is the same reasoning applied to an incomplete union: a
record missing a worker's share is not the suite's record, so an absent binding
class proves nothing, exactly as it proves nothing on a narrowed run.

The third clause covers the one silence the other two cannot, because it takes
their nodeids away with it. The checks are reported under the nodeids the workers
gave up, and those travel *inside* the halves — so where nothing arrives to name
them, there is nothing to report against and the checks simply vanish from a
green run. Two routes reach it and the clause is written to cover both: no half
arrives at all, and halves arrive whose record survived but whose item names did
not. The second is the more dangerous, because everything about that run looks
healthy.

The correspondence is stated as a correspondence, in both directions, because
each direction can be broken alone and one of them looks entirely healthy: a half
that arrives with the record whole but one item name short leaves the other check
reporting normally while the missing one's verdict — as likely a failing verdict as
a passing one — is simply dropped. So a decision nothing reports is a failure on
the same terms as an item nothing decides.

The last clause is judged against the run's **own options**, not against the
halves, since
with nothing arriving there is nothing to read a verdict from. An unfiltered
session collects the whole suite and therefore collects both checks — `--deselect`
and every other way of not collecting them is itself a filtering option — so on
an unfiltered run their absence is the failure, and on a narrowed one it is the
ordinary case and nothing is said. The same options question separates the two
readings of a missing item: `-k` on a name matching one check and not the other
produces, legitimately, exactly the shape that on an unfiltered run is a fault. It is reported under a nodeid of its own rather
than under a test's, since no test was ever named.

### 3. Both gates' `pytest` step is distributed, and it is still the whole suite

> **Normative.** CI's `gate` workflow runs its test step distributed across the
> runner's cores. It remains the whole suite and ADR-0010's five steps are
> unchanged in number, kind and order; nothing is deselected, skipped or split
> across jobs.

> **Normative.** `just test-fast` deselects nothing on its command line. Every
> test the tree declares is collected and answered, so ADR-0166 §1's carve-out for
> "the one file `just test-fast` deselects" no longer describes it and no longer
> applies. ADR-0166 §1's collection clause is otherwise untouched: a run narrowed,
> stopped early or never executed is a scoped selection under ADR-0136 §2, however
> it was narrowed and wherever that came from.

> **Normative.** In a distributed session the two evidence-dependent checks are
> collected on every worker, deselected there, and their assertions evaluated on
> the controller over the merged record, with the outcome reported under their own
> nodeids. Their test *functions* execute in no process, and a run is not on that
> ground short of the whole suite. ADR-0166 §1's requirement that every test the
> tree declares be "actually run" is superseded exactly here and nowhere else: for
> these two items, being **answered** — by the same predicates their bodies call,
> over strictly more evidence than any one process holds — is what that clause
> now asks. Every other test it names must still execute, and every other way of
> falling short of the clause is untouched.

That last is stated rather than left to be noticed, because it is the one place
where what runs is not what the file appears to say. It turns on the difference
between a check that is *not answered* and one that is *answered elsewhere*.
ADR-0166 §3's deselection was the first kind: the checks left the run and nothing
decided them, which is exactly why §3 had to ratify an accepted risk. These are
the second: `_binding_gaps` and `_stale_exemptions` — the functions the test
bodies call — are given a record no worker could assemble alone, and the serial
run, where the bodies do execute, remains a valid discharge of either anchor and
reaches the identical verdict from the identical predicates.

Two things stop that drifting. `evaluate_for_controller` is keyed by the test
functions' own `__name__`, and an item handed over with no entry there is reported
**failed** (§2); and a test in the same file asserts that every check requesting
the evidence fixture has an entry, so a third one cannot be added without one.

> **Normative.** ADR-0166 §3's accepted risk is discharged rather than
> transferred. An anchor discharged by `just test-fast` no longer leaves the
> Protocol-triad check unrun, and ADR-0166 §2's guidance to prefer the serial run
> "when your diff adds or changes a Protocol in `core/protocols.py` or a canonical
> fake in `ai_assistant.testing`" no longer has a coverage difference behind it.
> §2's other cases — order-dependence, shared fixture state, timing sensitivity —
> are untouched, and the serial run remains a valid discharge of either anchor.

**One CI job, not two.** A serial re-run in CI, as a second job or a manual
`workflow_dispatch` input, was considered and rejected: `uv run pytest` is the
serial suite on any machine, ADR-0136 §1 lets a lane discharge either anchor with
it, and a lane that wants to know whether a failure is distribution-related can
answer that in one command on its own tree. A second job would double the gate's
cost on every push to buy a diagnosis that is already one command away.

**What distribution changes about what CI catches** is worth stating plainly,
because it is not symmetric. A test that quietly depends on running after another
is *more* likely to be caught distributed than serially, since the order changes;
a test whose timing margins are narrow is more likely to fail under load, which
is a flake rather than a find. The first is a gain, the second is the cost, and
it is observable — a `gate` that starts failing on timing rather than on
assertions is this decision's Revisit condition.

### 4. What this records against ADR-0166 and ADR-0010

**ADR-0166 is partially superseded, in three named clauses, and this change
writes the record.**

A reader holding only ADR-0166 would run `just test-fast` expecting 31 tests to
be missing from it, would refuse an `-n auto` run at an anchor once they noticed
two declared tests had not executed, would choose `just check` for a diff touching
a Protocol, and would hold CI's gate to be serial — ADR-0166 §1's "less the one
file `just test-fast` deselects, actually run", §3's normative "leaves
`tests/core/test_protocol_triad.py` … unrun locally", and §4's "CI's gate stays
the full five steps, serial". Under §3 of this ADR they act differently in all
four. That is
ADR-0070 §1's test met, so a record is owed (ADR-0082 §1).

It is a **supersession and not an amendment**, and the distinction is not
cosmetic here. It would be tempting to call this an amendment on the ground that
ADR-0166's clauses rested on a fact — "no worker sees the suite" — that has since
changed. But that fact did not expire; it was *removed by this change*, and
ADR-0166 §3 did not merely observe it, it ratified an accepted risk on the
strength of it. Withdrawing a ratified acceptance of a risk is a change to what
was decided, so it takes ADR-0070 §4's leading-token form.

- **`Status`** becomes `Partially superseded by ADR-0179 (§1's carve-out for the
  file `just test-fast` deselects and its per-test execution clause, §3's accepted
  risk, and §4's serial-CI clause)`.
  The supersession leads and `Accepted` is dropped (ADR-0070 §4).
- **An appended dated note** on ADR-0166 states the scope and this reasoning
  (ADR-0070 §1; ADR-0082 §1 makes the note the invariant half of the record).
- **No ratified text of ADR-0166 is rewritten.** Its §§1–4 stay legible where
  they were written, beside the pointer to this decision.

**ADR-0010 takes a dated amendment note, not a supersession.** What ADR-0010
decided is that a remote `gate` runs "the five Definition-of-Done steps — `ruff
format --check`, `ruff check`, `mypy`, `lint-imports`, `pytest` — on every pull
request and every push", and that it binds the merge path. It is five steps and
`pytest` is still `pytest` over the whole suite; nothing about which steps run,
what they are, or what a green `gate` means has changed, so a reader acting on
ADR-0010 acts identically before and after (ADR-0070 §1). The note records that
the step is distributed and points here. ADR-0166 §4's *restatement* of CI's
serialism is a different matter and is superseded above, because that clause
decided serialism where ADR-0010 only assumed it.

**ADR-0136 takes nothing.** Its own dated supersession note quotes ADR-0166's
reasoning and, with it, the recipe as it stood on 2026-08-20 — "`just test-fast`
is `uv run pytest -n auto --deselect tests/core/test_protocol_triad.py`, so it
does not run the whole suite". That sentence is part of ADR-0166's record, dated
to it, and a reader following it reaches ADR-0166, which now leads with the
pointer here — so the chain is complete without rewriting a dated note about a
decision this ADR does not touch. What ADR-0136 itself decided is untouched,
which §5 states directly.

### 5. Everything else is unchanged

> **Normative.** ADR-0136 §1's two anchors, its rebase clauses, its rule that each
> anchor is a run on the tree as it then stands, its refusal of a docs-only
> exemption, and §2's four static steps before every commit all stand exactly as
> ratified — as amended by ADR-0166 §1, which this ADR leaves in force except for
> the carve-out named in §3.

> **Normative.** Nothing here alters ADR-0015, ADR-0020, ADR-0025 or ADR-0027:
> which trees a recorded review covers, when a base move costs a round, and what
> `ship` will accept are decided there and are untouched.

**No record is owed on ADR-0136 for §3's execution clause, and it is worth saying
which ADR that clause belongs to.** ADR-0136 §1 requires "the whole `pytest` suite
— is run, and passes"; it says nothing about individual declared tests. The
per-test wording — "every test the tree declares, less the one file
`just test-fast` deselects, actually run" — is **ADR-0166 §1's**, added when that
ADR admitted the parallel recipe at an anchor, and it is superseded above, in the
one sentence that also carries the carve-out §4 records. A reader holding only
ADR-0136 runs the suite at each anchor, reads the summary line, and gets a
complete pass-or-fail answer for every declared test before and after this change,
so ADR-0070 §1's test is not met against it and there is nothing to record
(ADR-0082 §1). Against ADR-0166 the test *is* met, which is why §4 records it
there.

The last is stated because the two loops run in the same window and are easy to
conflate, as ADR-0136 §5 and ADR-0166 §4 both stated it. A commit made after a
distributed anchor costs a review round on identical terms to one made after a
serial anchor.

**This ADR's `Status`.** It decides no Protocol and no `core/types.py` value.
It does change a contract *surface* in the sense that matters for the review set
— the rules two gates run under — so it takes the adversarial and architecture
lenses both, and ADR-0015 §5's ratify-after-review sequencing: drafted, reviewed
and revised as `Proposed`, flipped only once the required reviews returned clean.

## Consequences

**Easier.**

- **Every push to an open PR gets its gate back sooner.** Measured on this
  branch's own runs: the `Tests` step went from **273s to 113s** and the whole
  `gate` job from **5m28s to 2m45s**, on the same 4-vCPU runner. The saving lands
  on every push by every lane, not once per branch.
- **`just test-fast` is now literally what ADR-0136 §1's anchor wording asks
  for** — a run that "collected the whole suite and executed it to a passing
  result" — rather than that minus a named file. The two-sentence caveat that
  followed the recipe everywhere it was documented goes away with it.
- **A missing Protocol triad is caught locally again, at the first anchor.**
  ADR-0166 §3 gave that up knowingly and paid for it with a fix commit and the
  review round that commit buys, in exactly the case — a diff that touches a
  Protocol — where rounds are most expensive.
- **"The gate runs the full suite" is true again** where the check's own skip
  message says it (issue #1241).

**Harder.**

- **The check now has a distributed code path, and it is the more subtle one.**
  Two processes, a serialised payload, and a result reported by a process that
  ran no tests. It is pinned by tests of the merge itself — a binding split
  across two halves, a failing case vetoing a passing one, and the
  correspondence between the checks that read the evidence and the controller's
  evaluators — but it is machinery where there was none.
- **CI can now fail for a reason that is not the code.** Four workers on a
  4-vCPU runner is real contention, and a timing-sensitive test that passed
  serially can fail under it. That is the cost §3 names, and the run to compare
  against is `uv run pytest` on the same tree.
- **The controller's report is a synthesised one.** It lands in the counts, the
  failure list and the short summary through the same hook xdist puts every
  worker's result through, so it reads as an ordinary test outcome — but a reader
  debugging the harness itself should know it was not produced by running the
  test function.
- **Two lines on a distributed run disagree by exactly two, and the summary line
  is the one that is whole.** xdist's header reports what it *scheduled* to
  workers, and the two controller-answered items are deselected there by
  construction, so it reads `8 workers [19543 items]` where the serial run reads
  `collected 19545 items`. The summary line is unaffected: both modes finish
  `19509 passed, 36 skipped`, accounting for all 19,545. So a distributed run
  reports *more* outcomes than the header scheduled rather than fewer, which is
  the safe direction — a check going missing would show up as a count that fell,
  and nothing here can make one fall silently (§2). The summary line stays the
  contract, exactly as `CONTRIBUTING.md` → "Read your own summary line" says.

**Follow-on.** `.claude/agents/worker.md` carries its own copy of ADR-0166 §2's
"prefer the serial run when your diff touches a Protocol or a canonical fake",
which §3 above leaves without a ground; it is dispatch infrastructure outside this
change's fence and is filed as issue #1423. Issue #1243 — that a filtering
`PYTEST_ADDOPTS` narrows either anchor's run silently — is untouched and still
open; this decision neither widens nor closes it. Issue #1419, the kept temp trees
that fill this machine's tmpfs, rides in the same change as tooling: it bounds how
many kept trees can stand at once and decides nothing this ADR needs to state.

**Revisit if** the distributed `gate` is observed failing on contention rather
than on assertions more than occasionally (the flake cost above was
underestimated, and a serial CI job earns its price after all), or if the merge
is found to certify a binding no single process could have certified (the union's
semantics are wrong, and the deselection was the safer answer), or if xdist's
`workeroutput`/`pytest_testnodedown` contract changes under the project (the
channel this rests on is a plugin's, not pytest's core).
