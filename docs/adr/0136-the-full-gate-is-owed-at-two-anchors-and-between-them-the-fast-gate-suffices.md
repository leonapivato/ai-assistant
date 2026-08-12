# 136. The full gate is owed at two anchors on a branch, and between them the fast gate suffices

- Status: Proposed
- Date: 2026-08-11
- **What this changes and what it does not.** It moves one sentence of ADR-0015's
  `Consequences` — the every-commit full gate — and nothing else. CI's gate is
  untouched (§6), the Definition of Done is untouched, and no Protocol, no
  `core/types.py` value and no runtime behaviour is decided here. This is a rule
  about when an author runs a command on their own machine.

## Context

### The rule as it stands, and the measurement it rests on

ADR-0015's `Consequences` says, under **Easier**:

> The gate is ~33s locally (27s of it pytest, 5,777 tests), so the full gate
> stays mandatory on every commit — no test selection, no judgment call, no
> CI-only divergence.

`CONTRIBUTING.md` → "The gate (Definition of Done)" carries the same rule
operationally, and — this is the part that matters — it names its own expiry:

> **Run the whole suite, always.** Selecting "the tests that matter for this
> change" trades a shorter wait for a judgment call whose failure mode — a
> cross-subsystem regression `lint-imports` cannot see — surfaces in CI after you
> have moved on. **Revisit if `pytest` ever crosses a couple of minutes.**

Both sentences are conditioned on a cost. The rule was never "run everything
because breadth is sacred"; it was "run everything *because it is free*, so no
judgment call is worth its risk". The condition has expired.

### What it costs now

Measured in a clone at `d94637ca`, on the machine a dispatched lane actually runs
on:

| step | wall clock |
| --- | --- |
| `uv run ruff format .` | 0.12 s |
| `uv run ruff check .` | 0.12 s |
| `uv run mypy` | 1.54 s |
| `uv run lint-imports` | 0.36 s |
| `uv run pytest` | 355.64 s — 15,645 passed, 33 skipped |

The four static steps together cost **2.14 seconds**. `pytest` costs just under
**six minutes** — batch #986 records ~4 min for the same suite on a less loaded
machine, so four to six is the honest range and the low end is the one to argue
against. Either figure is an order of magnitude past ADR-0015's *whole*-gate
number, against a suite that has grown 2.7× since (5,777 → 15,678 collected).

The gate is no longer one thing with one price. It is two things whose prices
differ by a factor of about 165, and ADR-0015's sentence was written when it was
one thing. That is the whole of what has changed.

### What the every-commit rule costs a dispatched lane

A lane requiring both review lenses can run up to roughly **20 rounds** before the
required set is terminal (owner's ruling, 2026-08-11, batch #986). Each round is
commit → review → triage → fix → commit, and Codex reviews the *committed* diff,
so each round has at least one commit in it. Under the every-commit rule that is
~20 × 4–6 min ≈ **one and a half to two hours of pytest per lane**, nearly all of
it re-running the
same tests against trees that differ by a paragraph of prose or a renamed local.

What those mid-loop runs buy is close to nothing, and the reason is structural
rather than empirical: **the intermediate trees are not shipped.** Nobody merges
round 7. The only tree whose full-suite result anyone acts on is the tree at the
end, and that tree is gated twice over — once by the author before `gh pr ready`,
and once by CI on every push and PR (ADR-0010), where a red `gate` blocks the
merge outright.

### The breadth argument is right about the wrong tree

`CONTRIBUTING.md`'s reasoning above is sound: a cross-subsystem regression is
exactly what a selected test run misses and `lint-imports` cannot see. But that is
an argument about *some* tree being fully tested, and it is satisfied by testing
the tree that ships. Running the full suite on the eighteen intermediate trees as
well does not make the final tree any more tested; it only makes the regression
visible earlier, and "earlier" here means "eleven minutes earlier in a loop that
will run for another hour".

There is one place where earlier genuinely matters, and it is not the merge. It is
the **review**: Codex reads the working tree for context, so an invocation on a
tree that does not build or does not pass is a wasted round — the review reports
the breakage instead of the design, and the round is spent. That is a real anchor,
and it is the first of the two below.

### Why the answer is anchors rather than "use judgement"

Two failure modes bound the design.

- **A rule with no mandatory point degrades to nothing.** "Run the suite when it
  seems worth it" is what the every-commit rule was written to refuse, and the
  refusal was right about the failure mode even where it is now wrong about the
  price. An author under review pressure is the worst-placed person to judge when
  the next run matters.
- **A rule mandatory everywhere is paid everywhere.** That is the two hours.

Naming the two points where a full run is *load-bearing* keeps the first property
and drops the cost of the second: the discretion is bounded by two mandatory
anchors rather than resting on the author's sense of risk.

## Decision

**We will require the full gate at two anchors on a branch, and a fast gate
between them.**

### 1. The two anchors

> **Normative.** The full Definition-of-Done gate — `ruff format`, `ruff check`,
> `mypy`, `lint-imports` and the whole `pytest` suite — is run, and passes, on the
> tree at two anchors on a branch: immediately before the **first review
> invocation** on that branch, and immediately before the **final push preceding
> `gh pr ready`**. Both are mandatory and neither is at the author's discretion.

> **Normative.** Each anchor is a run on the tree as it then stands. A full gate
> run on an earlier tree does not discharge either anchor, and a rebase between
> the closing anchor and the final push re-opens it (`CONTRIBUTING.md` → "Run it
> against a current `main`": a green gate is evidence about the tree it ran on).

The first anchor is owed once per branch, not once per review invocation: it
protects the reviewer from a tree that cannot be read, and a tree that has been
fully gated once and has since only had review findings folded into it is not that
tree. The closing anchor is what makes the intervening discretion safe, and it is
the one that must not be skipped.

### 2. Between the anchors, the fast gate

> **Normative.** Between the anchors, `ruff format`, `ruff check`, `mypy` and
> `lint-imports` are mandatory before every commit, exactly as they are today.

> **Normative.** Between the anchors, `pytest` is at the author's discretion: the
> whole suite, a scoped selection, `--lf`, or no run at all. No justification is
> owed for the choice, and no reviewer may require a particular one.

> **Normative.** A diff touching no file under `src/` or `tests/` owes no `pytest`
> run between the anchors.

The static four stay mandatory because they are the cheap half — two seconds — and
because `mypy` and `lint-imports` catch precisely the class of cross-subsystem
breakage that a *selected* test run would miss. Dropping them would trade the
argument this ADR accepts for the one it rejects.

### 3. A red push between the anchors is acceptable

> **Normative.** Pushing a branch whose tests fail is permitted between the
> anchors. A red `gate` check on a draft PR mid-loop is information, not a defect
> in conduct, and is not on its own grounds for a finding, a report or an
> escalation.

> **Normative.** A red **final** push is the failure the closing anchor exists to
> prevent. A branch is not flipped out of draft on a tree whose full gate has not
> been run and passed locally.

This is the one behaviour change visible from outside the author's machine, and it
is deliberate: opening the draft PR early is already required so that CI gates
every push (`CONTRIBUTING.md`), and a rule that a push must never be red is in
tension with a rule that pushes should be frequent and early. CI is the backstop
(ADR-0010) — which is what a backstop is for. What it is not is a *substitute*:
§1's closing anchor is unconditional precisely so that "CI will catch it" never
becomes the plan.

### 4. Why the discretion is safe

Three nets sit under §2, none of which depends on the author's judgement:

- **CI runs the full serial gate on every push and every PR** (ADR-0010), against
  the locked environment. Nothing about that changes here (§6).
- **The closing anchor** re-runs everything locally on the tree that ships.
- **Branch protection** requires `gate` green to merge (`CONTRIBUTING.md` →
  "`gate` is the only required check"), so a suite that fails on the merged tree
  cannot reach `main` however the local loop was run.

The regression `CONTRIBUTING.md` warns about therefore has three chances to be
caught before it lands, and the every-commit rule was buying only the fourth.

### 5. This does not change what a review round costs

> **Normative.** Nothing in this ADR alters ADR-0020, ADR-0025 or ADR-0027: which
> trees a recorded review covers, when a base move costs a round, and what `ship`
> will accept are decided there and are untouched. A commit made under §2's
> discretion costs a review round on exactly the same terms as one made under the
> old rule.

Stated because the two loops run in the same window and are easy to conflate. This
ADR changes what an author runs before committing; it changes nothing about what
the record of a review covers.

### 6. What this does not decide

- **CI's gate.** It stays the full five steps, serial, on every push and PR. This
  ADR is about the *local* cadence only, and §4 depends on CI's being unchanged.
- **The Definition of Done itself.** The five steps and their order are ADR-0002's
  and ADR-0010's; "done" still means all five pass on the shipping tree.
- **The tooling.** A parallel test recipe (`just test-fast`, `pytest-xdist`) is
  briefed as a **follow-on implementation lane** after this ADR merges (batch
  #986, lane 1b). It is a consequence of this decision, not part of it: this ADR
  is correct with or without it, and nothing here presumes any particular runner.
  Where such a recipe exists, running it satisfies neither anchor unless it runs
  the whole suite — §1 requires the suite, not a command name.
- **`pre-commit`.** Its fast subset is unchanged and is not what §2 means by the
  fast gate; §2 binds the author, and a hook is not an author.
- **Which review lenses a change requires.** ADR-0015 §1 and `CONTRIBUTING.md` →
  "Stop when the required reviews are green" own that, unchanged.
- **The rebase rules.** Rebasing before gating and before invoking a review is
  about *freshness*, not breadth (`CONTRIBUTING.md` states them as distinct
  judgements), and both stand. §1's second clause leans on them.

### 7. What this records against earlier ADRs

- **ADR-0015 — amended, and the clause is named.** Its `Consequences` sentence
  *"the full gate stays mandatory on every commit — no test selection, no judgment
  call, no CI-only divergence"* becomes over-wide: a reader holding only ADR-0015
  would run the whole suite before every commit, which §2 no longer requires. That
  is ADR-0070 §1's test failing on a named clause, so ADR-0082 §1 owes a record on
  ADR-0015 — a qualifier on its `Status` line, which is a grandfathered
  `Accepted, partially superseded …` line and so takes one (ADR-0082 §2), and an
  appended dated note. **No ratified text of ADR-0015 is rewritten**; its sentence
  stays legible beside the pointer to this decision, per ADR-0070 §1's append-only
  mechanism.
  The change is an **amendment and not a supersession**, on ADR-0111's precedent
  against ADR-0083 §7: there, a ratified acceptance rested on a stated condition,
  the condition's revisit trigger fired, and the narrowing was recorded as an
  amendment. Here the clause's own premise — *"The gate is ~33s locally"* — is the
  condition, and `CONTRIBUTING.md`'s companion sentence names the trigger
  explicitly (*"Revisit if `pytest` ever crosses a couple of minutes"*). None of
  ADR-0015's five numbered decisions moves: the local review loop, the triage
  rule, issues-over-files and dispatcher-assigned ADR numbers all stand exactly as
  ratified.
- **ADR-0010 — nothing owed.** Its remote gate is relied on as ratified and relied
  on *more* than before; no sentence of it becomes false or over-wide, and §6
  keeps it whole. That CI is "the backstop, not the first line of defence"
  survives: §1's closing anchor is the first line, and it is unconditional.
- **ADR-0002 — nothing owed.** Its toolchain and its five quality gates are
  untouched; this ADR decides a cadence for running them, which ADR-0002 does not
  decide.
- **ADR-0020, ADR-0025, ADR-0027 — nothing owed and nothing read across.** §5
  states this: the review-round accounting is theirs and is not touched.
- **ADR-0089 — this ADR is marked.** Marking is forward-only (§5 of that ADR), so
  ADR-0015 remains unmarked and binds as prose; the clause named above is read as
  the prose obligation it is.
- **This ADR's `Status`.** It decides no Protocol and no `core/types.py` value —
  it decides no code surface at all — so the required review set is adversarial
  alone (ADR-0015 §1, `CONTRIBUTING.md` → "Stop when the required reviews are
  green"), and the architecture lens is not owed. ADR-0015 §5's
  ratify-after-review sequencing is taken as ADR-0130 §12 and ADR-0132 took it: it
  was drafted, reviewed and revised as `Proposed`, and the status flipped only
  once the required review returned clean on one tree, with the required review
  re-run on the flipped tree. The PR carries the round record; the follow-on lane
  named in §6 is briefed only after this has merged.

## Consequences

**Easier.**

- **A lane's local cost stops scaling with its round count.** Two full runs per
  branch instead of one per commit; on a 20-round lane that is ~10 minutes of
  pytest where there were ~110. The saving is largest exactly where it hurts most —
  a long review loop is already the expensive case.
- **A docs-only lane pays nothing.** An ADR PR that touches no code no longer runs
  15,678 tests per commit to prove that prose did not break them. The anchors
  still catch a tree that will not build.
- **The early draft PR stops being a liability.** `CONTRIBUTING.md` asks for the
  draft to open before the work is done so CI gates every push; §3 makes that
  honest rather than something an author avoids to keep the check green.
- **The rule now says what it means.** The old rule's stated ground was that the
  gate was free. Written down as anchors, the ground is what a full run is *for* —
  a readable tree for the reviewer, and a shipping tree that is proven — which is
  a reason that does not expire the next time the suite grows.

**Harder.**

- **A regression can now surface later in a loop.** A cross-subsystem break
  introduced at round 3 and not caught by `mypy` or `lint-imports` may not be seen
  locally until the closing anchor — or by CI on the next push, which is the more
  likely case in practice. The cost is a longer bisect over the branch's own
  commits; the change never reaches `main` either way.
- **A red check is now ambiguous at a glance.** A dispatcher glancing at a draft
  PR's `gate` can no longer read red as "this lane is broken". It has to be read
  against where the lane is in its loop, which is a judgement that did not exist
  before. §3 says explicitly that mid-loop red is not on its own grounds for a
  report, so the ambiguity is resolved by not acting on it.
- **The closing anchor is a single point of failure, and it is procedural.**
  Nothing mechanical fires before `gh pr ready` to check that a full gate ran.
  Branch protection catches the consequence — a red `gate` cannot merge — but the
  wasted round-trip lands on whoever verifies the lane.

**Follow-on.** Batch #986 lane 1b — a parallel test recipe and the
`CONTRIBUTING.md` edit that states this cadence where an author reads it — is
briefed after this merges (§6). `CONTRIBUTING.md` and `CLAUDE.md` continue to
state the every-commit rule until that lane lands; where they and this ADR
disagree in that window, this ADR governs, since a ratified ADR outranks
`CONTRIBUTING.md`.

**Revisit if** the suite's serial cost falls back under a minute (the anchors stop
being worth naming — restore the simpler rule), or if a regression that the
every-commit rule would have caught locally reaches `main` through this cadence
(the three nets in §4 did not hold, and the closing anchor is the one to examine
first), or if the discretion in §2 is observed collapsing to "never run pytest"
across lanes whose diffs are substantial (the bounded judgement call is being
taken as a blanket exemption, which is the failure mode ADR-0015 named).
