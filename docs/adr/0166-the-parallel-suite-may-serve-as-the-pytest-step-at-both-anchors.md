# 166. The parallel suite may serve as the `pytest` step at both anchors

- Status: Proposed
- Date: 2026-08-20
- **What this changes and what it does not.** It relaxes one step of one gate at
  two named moments — which `pytest` invocation discharges ADR-0136 §1's anchors.
  The two anchors themselves, the four static steps before every commit, the
  rebase clauses, and §1's refusal of a docs-only exemption are all untouched
  (§4). CI's gate is untouched (ADR-0010). No Protocol, no `core/types.py` value
  and no runtime behaviour is decided here; this is a rule about which command an
  author runs on their own machine.

## Context

### The rule as it stands

ADR-0136 §1 requires, at each of its two anchors, "the full Definition-of-Done
gate — `ruff format`, `ruff check`, `mypy`, `lint-imports` and the whole `pytest`
suite". §6 left the tooling open and said what an eventual parallel recipe would
be worth against that requirement:

> Where such a recipe exists, running it satisfies neither anchor unless it runs
> the whole suite — §1 requires the suite, not a command name.

The recipe arrived as `just test-fast` (batch #986 lane 1b), and it does **not**
run the whole suite: it is `uv run pytest -n auto --deselect
tests/core/test_protocol_triad.py`. So §6's conditional resolved against it, and
`CONTRIBUTING.md` → "When the full gate is owed, and when it is not" and
`CLAUDE.md`'s gate paragraph both state the conclusion flatly — "**It satisfies
neither anchor**".

### What the two runs cost

Measured on this branch, in the clone a dispatched lane actually runs in:

| run | wall clock | tests run |
| --- | --- | --- |
| `uv run pytest` (serial) | 497.33 s | 18,088 passed, 33 skipped |
| `just test-fast` (xdist, `-n auto`) | 88.97 s | 18,057 passed, 33 skipped |

A factor of 5.6, and the 31-test difference is the deselection §3 is about. The
serial figure ADR-0136 measured at `d94637ca` was 355.64s over 15,678 collected;
the suite has grown to 18,121 since, so the anchor has got more expensive, not
less. It is paid twice per branch and once more per base-moving rebase — and a
lane merging late in an ordered batch under `strict` branch protection rebases
more than once.

### What the deselection actually removes

This is the part the rule turned on, so it is stated precisely rather than as
"one check".

`tests/core/test_protocol_triad.py` is 31 tests, and it is the **mechanical
enforcement of the Protocol triad rule** — `CONTRIBUTING.md` → "Adding a
Protocol", golden rule 5's companion. It asserts that every Protocol in
`core/protocols.py` has a `<Protocol>Contract` conformance suite and a
`Fake<Protocol>` in `ai_assistant.testing`, and — the part no file-existence
check can make — that a binding subclass really ran the fake through the suite
and passed.

It cannot run distributed because of *how* it makes that assertion: it reads
`tests/conftest.py`'s record of which tests the session reported, and
`tests/conftest.py` defers it to the end of the run so the record is complete
when it reads it. Under `-n auto` each worker holds its own session and its own
partial record, so no worker sees the suite. The deselection is therefore a
property of the check's design, not a flake to be fixed by retrying it.

Two further facts bound how much that matters, and they point in opposite
directions:

- The check already **self-skips** its evidence-dependent parts on a narrowed
  run, with the message "the gate runs the full suite". That sentence is the
  premise this ADR changes.
- The check is **deterministic**. It does not depend on ordering, timing or a
  machine's load. So when it is skipped locally and run in CI, it either passes
  in both places or fails in CI every time — it is never silently lost, only
  learned about later.

### The ruling

The owner ruled on #1226 (amendment 2, 2026-08-20) that the parallel run is
allowed as the `pytest` step at both anchors, at the worker's discretion, on the
ground that it costs ~1 minute against the serial suite's several and the two
runs are equal in practically every case; that the worker may still choose the
serial run where the change warrants it (test-ordering sensitivity, shared-state
fixtures, timing); and that CI's full gate on every PR and push to `main` runs
regardless, so a serial-only divergence cannot reach `main` unseen. The accepted
risk was stated with it: a failure only the serial run would catch now surfaces
in PR CI *after* review, costing a fix commit and a fresh review round, judged
rare enough to pay for the savings across every lane.

This ADR records that ruling and names, in §3, the one concrete instance of that
risk the ruling did not enumerate.

## Decision

**We will let the parallel suite discharge the `pytest` step at both of
ADR-0136 §1's anchors, at the running agent's discretion.**

### 1. The parallel run satisfies either anchor

> **Normative.** At either of ADR-0136 §1's anchors — immediately before the
> first review invocation on a branch, and immediately before the final push
> preceding `gh pr ready` — the `pytest` step is discharged by **either** the
> full serial suite (`uv run pytest`, or `just check`, which runs it) **or** the
> parallel recipe `just test-fast`. The choice is the running agent's, no
> justification is owed for it, and no reviewer may require a particular one.

> **Normative.** ADR-0136 §6's clause "running it satisfies neither anchor unless
> it runs the whole suite" no longer governs `just test-fast`, whose one
> deselection is named and accepted in §3 below.

The permission is unconditional because the ruling is. It is stated as "either
anchor" rather than "both" to leave no reading on which the two anchors take
different runs: each anchor is discharged independently, and a branch may satisfy
one with `just test-fast` and the other with the serial suite in either order.

### 2. The serial run stays available, and is the one to choose when the change warrants it

> **Normative.** The full serial suite remains a valid discharge of either anchor
> and is never wrong. Nothing in §1 obliges an agent to run the parallel recipe.

The cases where the serial run earns its extra seven minutes are, non-normatively:
a diff whose tests are order-dependent or share state through a fixture; a
timing-sensitive test whose margins narrow under load from other workers; and —
the one this ADR adds to the ruling's list — **a diff that adds or changes a
Protocol in `core/protocols.py` or a canonical fake in `ai_assistant.testing`**,
which is exactly what §3's deselected check guards and exactly what
`just test-fast` will not tell you about.

That is guidance and not an obligation, deliberately. Making it normative would
narrow a discretion the ruling granted flat, and would put a lane in the position
of arguing about which diffs "touch a Protocol" at the moment it is trying to
finish.

### 3. What the parallel run does not cover, and the risk taken

> **Normative.** An anchor discharged by `just test-fast` leaves
> `tests/core/test_protocol_triad.py` — 31 tests, including the mechanical
> Protocol-triad enforcement — unrun locally. This is accepted, on the three nets
> below, and is not a defect in the agent's conduct.

This is the ruling's accepted risk made concrete. It is worth separating from the
risks the ruling named, because it is a different shape: order-dependence and
timing are *probabilistic* gaps that may or may not bite on any given branch,
while this one is **deterministic and permanent** — under `just test-fast` those
31 tests never run, on every branch, always.

Being deterministic is what makes it payable. The three nets under it are
ADR-0136 §4's, unchanged:

- **CI runs the full serial gate on every push to an open PR** (ADR-0010,
  `synchronize`). The triad check runs there, on every push, with no dependence
  on the agent's judgement — so a Protocol landing without its triad is caught,
  every time, on the first push after it appears.
- **Branch protection requires `gate` green to merge**, so it cannot reach `main`
  however the local loop was run.
- **The serial run is one command away** when §2's guidance applies.

What is genuinely given up is *when* the agent learns. Under the old rule a
missing triad failed at the first anchor, before the review was invoked; under
this one it can fail in CI after the review, which costs a fix commit and the
review round that commit buys. That is precisely the cost the ruling weighed and
accepted, and this ADR does not re-open it — it records which case it will most
often be.

### 4. Everything else about ADR-0136 is unchanged

> **Normative.** ADR-0136 §1's two anchors, its two rebase clauses, its rule that
> each anchor is a run on the tree as it then stands, and its refusal of a
> docs-only exemption at an anchor all stand exactly as ratified. ADR-0136 §2's
> four static steps before every commit stand. This ADR changes only which
> `pytest` invocation discharges the anchor's test step.

> **Normative.** Nothing here alters ADR-0010. CI's gate stays the full five
> steps, serial, on the triggers `.github/workflows/gate.yml` declares, and §3's
> first net depends on that being so.

> **Normative.** Nothing here alters ADR-0020, ADR-0025 or ADR-0027: which trees
> a recorded review covers, when a base move costs a round, and what `ship` will
> accept are decided there and are untouched.

The last is stated because the two loops run in the same window and are easy to
conflate, exactly as ADR-0136 §5 stated it. A commit made after a
`just test-fast` anchor costs a review round on identical terms to one made after
a serial anchor.

### 5. What this records against ADR-0136

**ADR-0136 is partially superseded, in two named clauses, and this change writes
the record.**

A reader holding only ADR-0136 would run the whole serial suite at both anchors
and would refuse `just test-fast` there — §1's "the whole `pytest` suite" read
against §6's "satisfies neither anchor unless it runs the whole suite", against a
recipe that demonstrably does not run the whole suite. Under §1 of this ADR they
would act differently. That is ADR-0070 §1's test met, so a record is owed
(ADR-0082 §1).

It is a **supersession and not an amendment**: ADR-0136 §1's requirement is not
being reconciled with its own text or with a fact that postdates it — it is being
*replaced*, at the anchors, by a weaker one. The premise it rested on has not
expired the way ADR-0015's did; the decision is simply revised. So the record
takes ADR-0070 §4's leading-token form.

- **`Status`** becomes `Partially superseded by ADR-0166 (§1's requirement of the
  whole `pytest` suite at the anchors, and §6's parallel-recipe clause)`. The
  supersession leads and `Accepted` is dropped (ADR-0070 §4).
- **An appended dated note** on ADR-0136 states the scope and this reasoning
  (ADR-0070 §1; ADR-0082 §1 makes the note the invariant half of the record).
- **No ratified text of ADR-0136 is rewritten.** Its §1 and §6 sentences stay
  legible where they were written, beside the pointer to this decision, per
  ADR-0070 §1's append-only mechanism.

The pair lands here rather than in a later lane, because a merged ADR-0166 beside
an unrecorded ADR-0136 is the window ADR-0082 exists to close (ADR-0082 §7).

**Nothing else is owed.** ADR-0015 is untouched — its every-commit clause was
already amended by ADR-0136 and this ADR does not read across it. ADR-0002's five
quality gates and their order are untouched; this decides a command, not a step.
ADR-0089: this ADR is marked, which is forward-only, so ADR-0136 continues to
bind as its own marks and prose.

**This ADR's `Status`.** It decides no Protocol and no `core/types.py` value — no
code surface at all — so the required review set is adversarial alone (ADR-0015
§1). ADR-0015 §5's ratify-after-review sequencing is taken as ADR-0136 itself
took it: drafted, reviewed and revised as `Proposed`, the status flipped only
once the required review returned clean, with the required review re-run on the
flipped tree.

## Consequences

**Easier.**

- **An anchor costs about a minute and a half instead of about eight.** A branch that never
  rebases pays two anchors; one that rebases twice pays four. The saving is
  ~7 minutes per anchor, and it lands hardest on exactly the lanes that pay the
  most anchors — the ones merging late in an ordered batch.
- **The closing anchor stops being the expensive one.** ADR-0136's post-`ready`
  rebase clause obliges a full gate on every landing tree, which is the anchor an
  agent under merge pressure is most tempted to skimp. Making it cheap makes it
  more likely to actually run, which is worth more than the coverage the serial
  run adds over it.
- **The rule now matches the tooling.** `just test-fast` existed as the
  between-anchors recipe and was forbidden at the two moments a full run is
  actually load-bearing, which is the inversion this removes.

**Harder.**

- **A missing Protocol triad now surfaces in CI rather than locally.** The cost
  is a fix commit and the review round it buys. §2's guidance is the mitigation
  and it is advisory, so it will sometimes not be taken.
- **"The gate runs the full suite" is now false in one place it is written.**
  `tests/core/test_protocol_triad.py`'s own skip message says it. The sentence is
  a *scoping* explanation to a reader of a narrowed run rather than a warranty,
  and correcting it touches a file outside this lane's fence, so it is filed as
  an issue rather than smuggled in here. Nothing in this ADR depends on that edit
  landing.
- **Two runs now discharge the same obligation**, so "did you gate?" no longer
  has one answer. §1 makes the choice explicitly unjustified and unreviewable to
  keep that from becoming a thing lanes argue about.

**Follow-on.** An issue carries the `tests/core/test_protocol_triad.py` skip-message
wording, and a second carries `.claude/agents/worker.md`'s copy of the repealed
"satisfies neither anchor" sentence — dispatch-infrastructure text outside this
lane's fence. Neither is a condition of this decision.

**Revisit if** the triad check is made to run under `-n auto` (the deselection
goes, §3's whole risk goes with it, and §1 becomes unconditional in fact as well
as in rule), or if a failure only the serial run would have caught is observed
costing review rounds more than occasionally (the ruling's rarity premise did not
hold), or if the serial suite's cost falls back near the parallel one (the
distinction stops being worth a decision).
