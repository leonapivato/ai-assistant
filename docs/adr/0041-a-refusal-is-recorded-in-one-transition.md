# 41. A refusal is recorded in one transition, whether or not anyone was asked

- Status: Accepted
- Date: 2026-07-22

## Context

ADR-0014 §4's transition table permits `SkipReason.APPROVAL_DENIED` from
exactly one status, `AWAITING_APPROVAL`. `planning/execution.py` encodes that in
`_LEGAL_SKIP_REASONS`, under a comment restating the rationale:

> A step that was never queued for approval cannot have been denied one, so
> allowing `APPROVAL_DENIED` from `PENDING` would manufacture a permission
> record for a decision nobody made — worse than no record at all.

That reasoning holds against the case it was written for: a caller inventing a
denial for a step no permission layer ever looked at. It does not hold against
the case ADR-0021 §3 actually produces. An `ActionPolicy` returning
`PermissionOutcome.DENY` refuses the step outright, on its own authority, with
nobody asked and nothing shown. The step is still `PENDING` when that ruling is
recorded, and it never becomes anything a human could answer.

The ratified graph offers no move that records this. So `StepRunner` commits two
(ADR-0037 §5, which documents the workaround and argues for it): `PENDING →
AWAITING_APPROVAL` carrying `bound_tool`, purely to reach a status from which
`APPROVAL_DENIED` is legal, then `AWAITING_APPROVAL → SKIPPED` carrying the
`approval_ref`. ADR-0037 §5 is explicit that this is a recorded disagreement
rather than a settled one, names the widening as the better end state, and
points at this issue for it (#260).

**ADR-0037, `orchestration/runner.py` and `StepRunner` are in flight on PR #249
and are not on `main` at the time of writing** — this ADR is deliberately
sequenced ahead of them, because #249 is held behind the stranding window
described below. A reader checking the premise against merged history will not
find them yet; they are on that PR's branch, and #249 rebases onto this change
once it lands. Nothing here depends on ADR-0037 being ratified: the decision
rests on ADR-0014 §4's own text and on `planning`'s `_LEGAL_SKIP_REASONS`, both
of which are merged. ADR-0037 §5 is cited as the record of *why the workaround
exists and who disagreed with it*, which is the honest attribution — the
objection this ADR settles was raised by review of that PR, not invented here.
Should #249 be abandoned, this decision stands unchanged: the edge it makes
legal is the one any caller of a denying `ActionPolicy` needs.

Two costs, and the second is the one that forces the decision.

**The record says something untrue.** §4's trigger column defines `PENDING →
AWAITING_APPROVAL` as the case where the "permission check requires
confirmation", and §4 makes `AWAITING_APPROVAL` durable "precisely so a restart
preserves it" — that is, as a state a human is expected to come back and answer.
A step parked there for a `DENY` was never a question. A reader of the durable
state, or of the version history, sees an approval sought that was not.

**It is a two-commit window, and the intermediate state is unrecoverable.** The
two transitions are two separate compare-and-swaps; `PlanStore` offers no
multi-transition commit (#257 names this as one of three such windows, and as
the only one where the intermediate state is a dead end). If the second commit
fails, or the task is cancelled between them, the step is durably
`AWAITING_APPROVAL` for a ruling that is a `DENY` — and there is no way out.
`StepRunner.resume` refuses it, correctly, because the recorded decision is not
a `CONFIRM` and an answer to a question nobody was shown authorises nothing.
`StepRunner.run` refuses it, correctly, because the step is no longer `PENDING`
(ADR-0037 §6). Nothing has acted — no tool was reached — so unlike a stranded
`RUNNING` there is no side effect in doubt; the step is simply stuck, and the
plan with it.

The window exists *only because* the disposition needs two commits. A denial
that is one transition has no window at all.

## Decision

**We will permit `PENDING → SKIPPED` with `skip_reason=APPROVAL_DENIED`, when
and only when an `approval_ref` is supplied.** This widens ADR-0014 §4's table
by one row. It moves nothing and removes nothing.

### 1. What the "never queued" rule was protecting, stated precisely

ADR-0014 §4's rationale conflates two things that turn out to be separable:
*whether a human was asked*, and *whether a decision exists to point at*. Only
the second is load-bearing.

The harm the rule guards against is a fabricated permission record — a step
recorded as refused with nothing behind the refusal. What prevents that is not
the step having passed through `AWAITING_APPROVAL`; passing through it proves
only that a `bound_tool` was known. What prevents it is the `approval_ref`: a
foreign key into `permissions/`'s audit trail (ADR-0004 §7, ADR-0014 §3), which
either resolves to a stored `PermissionDecision` or does not. The narrow rule is
therefore:

> **A denial must name the decision that refused it.** Whether anybody was asked
> is not what makes the record truthful; the `approval_ref` is.

Be exact about what "name" buys, because the two halves are enforced in
different places. `planning` enforces that a denial *carries* an identifier —
present and non-blank, which `Identifier` already validates. That the identifier
*resolves* to a stored decision is `permissions/`'s to guarantee and is #107's
open gap, which this ADR neither closes nor relies on being closed. The
widening's claim is therefore the narrower one: a denial is never recorded
without something to look up.

This is the same rule ADR-0014 §4 already applies in the mirror-image case, and
it applies it there for a reason that reads as an argument for this widening.
Every transition into `RUNNING` must carry an `approval_ref` — *including* the
common automatic clearance where no prompt was shown — because otherwise
"precisely the silent, automatic actions ... would be the ones that could not be
correlated with their authorisation". An automatic refusal is the same event
with the sign flipped. A table that spends a paragraph insisting the silent
*grant* be recorded cannot coherently make the silent *refusal* unrecordable.

So: **a refusal recorded without a question having been asked is still a
refusal.** `AWAITING_APPROVAL` stops being a waypoint on the way to
`APPROVAL_DENIED` and means only what §4 says it means — a human is being asked,
which is what makes its durability worth having.

### 2. `approval_ref` is required on the new edge

Not merely conventional, not defaulted, not inferable: a `PENDING → SKIPPED`
with `APPROVAL_DENIED` and no `approval_ref` is rejected as an illegal
transition. Present and non-blank is the whole of what `PlanExecution` can
check, and per §1 it is the whole of what this ADR claims.

This is the whole of what §1 keeps from the rule being widened. Dropping it
would leave `APPROVAL_DENIED` assertable from the initial status of every step
with nothing behind it — which is precisely the fabricated record the original
rationale feared, and would make the widening the mistake ADR-0014 was right to
refuse. #107 exists because nothing yet forces a decision *id* to resolve to a
stored record; the least this change can do is not widen the set of places an
id can be absent altogether. ADR-0014 §4's own precedent is the `→ RUNNING`
rule, which is unconditional for exactly this reason.

The requirement is symmetric with the existing `AWAITING_APPROVAL` edge and is
already enforced there by a check that is not conditioned on the origin status,
so the rule is one rule rather than two.

### 3. `AWAITING_APPROVAL → SKIPPED` with `APPROVAL_DENIED` remains legal

Unchanged, and it must be: it is the genuine path — a human was shown a
confirmation and said no. `StepRunner.resume` commits exactly that. Removing it
in favour of the new edge would be a *move*, and would delete the one case the
original row was written for.

This is a widening. After it, `APPROVAL_DENIED` is legal from `PENDING` and from
`AWAITING_APPROVAL`, and from nowhere else. The two rows differ in who refused,
not in what is recorded: both carry an `approval_ref`, and the difference — was a
human asked — is answerable from the referenced decision, which is where
ADR-0014 §3 deliberately puts the ruling rather than copying it into execution
state.

Nothing else in the table changes. `PENDING`'s other skip reasons —
`UNMET_DEPENDENCY`, `NO_CAPABLE_TOOL`, `SUPERSEDED` — keep exactly the statuses
they had, and `AWAITING_APPROVAL` keeps refusing the planning reasons (a step
already queued for approval has, by construction, a capable tool).

### 4. Alternatives considered

**Keep the two-commit path (ADR-0037 §5's position).** Rejected. Its own text
concedes the widening is the better end state and defers it only because the
change belongs to a different lane's fence. That fence is this ADR's lane. The
stranding window is the decisive difference: a false-but-recoverable record is a
documentation problem, and an unrecoverable one is a correctness problem.

**A distinct `SkipReason` for a policy refusal — `POLICY_DENIED` alongside
`APPROVAL_DENIED`.** Rejected, and this is the closest alternative. It would let
the durable state say directly whether a human refused or a policy did, without
resolving the `approval_ref`. Three reasons against:

- It is a `core` type change — a new `SkipReason` member crossing subsystem
  boundaries — which under golden rule 5 makes this a contract ADR that must
  merge alone, ahead of its implementation. That is a real cost and it buys a
  distinction already available: the referenced `PermissionDecision` records
  which outcome was ruled and whether a confirmation resolved it.
- It puts the ruling's *content* in execution state. ADR-0014 §3 is deliberate
  that `approval_ref` is a foreign key and not a copy, because duplicating the
  ruling "would create a second authority that can drift from it". A skip reason
  that encodes *how* the refusal was reached is exactly that second authority,
  in miniature.
- Every consumer that today asks "was this step denied" would have to learn to
  ask about two members, and each one that forgets is a bug. One reason for one
  disposition — the step will not run, and here is the decision that says so —
  is the distinction execution state actually needs.

The counter-argument is real and worth recording: an operator reading raw
execution state cannot, without a join, tell an automatic refusal from a human
one. We accept that, because the join is to the trail that ADR-0004 §7 makes
authoritative anyway, and reading the disposition without reading the decision
it names was never going to be sound.

**Record nothing and leave the step `PENDING`.** Rejected. It discards the
durable fact that the step was refused and makes a denied step
indistinguishable from an unattempted one, which ADR-0004 §7 likes least of all.
ADR-0037 §5 rejects it on the same ground.

**Skip from `PENDING` as `SUPERSEDED`.** Rejected. It records a false reason and
carries no `approval_ref` at all — strictly worse than the two-commit path on
both counts.

**Make the two commits atomic instead.** Rejected here, not on its merits but on
scope: it needs `PlanStore` to accept more than one transition per commit, a
Protocol change with a much wider blast radius (#257), and it would leave the
untruthful intermediate record in place even once it worked. Closing the window
by removing the second commit is strictly cheaper. #257's other two windows are
untouched by this change and remain open.

### 5. What ratification does to ADR-0014

ADR-0017 §7 requires the operation performed on another ADR to be recorded
rather than inferred. This ADR merges `Accepted` with its implementation — no
Protocol and no `core` type moves (§6), so golden rule 5's separate-PR
requirement is not triggered — so the edit is applied by this change rather than
deferred, on ADR-0034 §4's reasoning: leaving ADR-0014 unmarked while code runs
against the widened rule is the defect with the sign flipped, and ADR-0014 is
where a reader will look.

**ADR-0014 is partially superseded, and its `Status` line says so.** This is the
ruling the amendment convention asks for and it is worth being exact about,
because it goes the *other* way from every previous note on ADR-0014's header.

ADR-0029 §9 and ADR-0034 §4 each widened §4's **trigger column** and each
declined a status line, on a stated test: "No legal move is added or removed —
`PlanExecution` validates the move and not the trigger, so an implementation
built from that table needs no change." That test is exactly what this ADR
fails. §4's `PENDING → SKIPPED` row does not describe a trigger; it *enumerates*
the legal skip reasons, `_LEGAL_SKIP_REASONS` is that enumeration transcribed,
and this decision adds a fourth member. A transition ADR-0014 makes illegal
becomes legal, and the implementation built from that table does change. Under
ADR-0001 that is changing a past decision, not applying one to a new
circumstance, and it takes a status line — the same way ADR-0018 earned one
against ADR-0016 by changing its rules.

The tempting narrower reading is that only the *rationale* moves: that ADR-0014
§4's real decision is "a denial must name the decision that refused it" (§1
above), that "never queued for approval" was the reasoning offered for it on an
assumption a policy `DENY` falsifies, and that the rule survives intact. That
reading is true as far as it goes and it is why §1 is written the way it is —
but it does not settle the status question, because ADR-0001's trigger is what a
later ADR does to the earlier one's *text*, and the text here is a set with a
member added. Recording it as a supersession costs nothing and leaves a reader
of §4's table unable to act on it without meeting this ADR first; recording it
as a mere note would leave that table silently wrong about what is legal. So:

- **ADR-0014's `Status` line becomes `Accepted, partially superseded by
  ADR-0041`**, and a dated `Partially superseded:` entry is added to its header
  in the form ADR-0016 uses for ADR-0018 — naming the one row affected, stating
  that a legal move is added (which is why this one takes a status line where
  the header's other notes did not), and listing what in §4 stands unchanged:
  the `AWAITING_APPROVAL` denial row, `PENDING`'s other skip reasons, the
  `approval_ref` requirement on every entry into `RUNNING`, and
  `AWAITING_APPROVAL`'s durability.
- **The supersession is partial and narrow.** It reaches one row of one table.
  Nothing else in ADR-0014 — §3's types, §5's `PlanStore` and its CAS, §6's
  `Planner`, or the rest of §4's graph — is touched or called into question.
- **ADR-0014's own text is not rewritten**, per ADR-0001's append-only rule. §4's
  table stands in the document as ratified, with the header entry above it
  recording what a reader must know before relying on it.
- **No other ADR is edited.** ADR-0037 §5 named this change as the better end
  state and pointed at #260 for it, so its ratification is that section working
  as designed rather than a contradiction of it — nothing in ADR-0037's text
  reads as false once this lands, and its §5 stays accurate as the record of why
  the workaround existed. The workaround itself is `orchestration`'s to remove,
  in the change that owns `runner.py`. ADR-0021 and ADR-0004 are *read* here and
  not widened. The line is ADR-0029 §9's: whether a sentence in the other ADR
  would now read as false.

### 6. This changes no contract surface

Stated because it is what makes the one-PR shape legitimate, and it is checkable
rather than asserted:

- **`SkipReason` gains no member.** `APPROVAL_DENIED` already exists
  (`core/types.py`), and this ADR deliberately does not add a second reason
  (§4).
- **`StepTransition` already carries `approval_ref`** and already accepts it
  alongside `to_status=SKIPPED`; its `_fields_match_target_status` validator
  constrains `skip_reason`, `error` and `output` by target status and says
  nothing about `approval_ref`.
- **`PlanStore`'s Protocol is unchanged.** Transition legality was never on the
  Protocol's signature; it is behaviour the conformance suite asserts.

So the surface that moves is `planning`'s own `_LEGAL_SKIP_REASONS`, the
`PlanStore` conformance suite's statement of the obligation, and the canonical
fake that must keep passing it.

### 7. What the implementation owes

- **The new edge is pinned**: `PENDING → SKIPPED` with `APPROVAL_DENIED` and an
  `approval_ref` succeeds, and the resulting step durably carries the reason and
  the reference.
- **The widening is pinned as a widening, not a hole.** `PENDING`'s other skip
  reasons are unchanged; `AWAITING_APPROVAL → SKIPPED / APPROVAL_DENIED` still
  works; `AWAITING_APPROVAL` still refuses the planning reasons.
- **The `approval_ref` requirement is pinned on the new edge specifically** — a
  `PENDING → SKIPPED` / `APPROVAL_DENIED` without one is refused. Asserting it
  only on the old edge would leave §2, the load-bearing half of this decision,
  untested.
- **The `PlanStore` conformance suite states the obligation**, because
  transition legality is already part of that contract — the suite asserts the
  denial rule today, in the negative — and a suite *is* the contract (#40). The
  existing negative case is not merely deleted; it is replaced by the positive
  edge plus the `approval_ref` refusal that now carries the same protection.
  The canonical `FakePlanStore` mirrors the graph independently and moves with
  it.

## Consequences

**A denial can be one commit, which is what #257's third window needs.** This
change makes the single compare-and-swap *available*; it does not perform it.
The window closes when `StepRunner`'s `run` + `DENY` path is rewritten to take
the new edge — a change to `runner.py`, in flight on PR #249 (Context) and one
this change deliberately does not touch (below). Until then that path still commits twice and is still
interruptible, exactly as #257 describes. What is settled here is that the
one-commit disposition is now legal, which is the part #257 said was missing.
The other two windows in #257 — both on the `resume` path, where a recorded
resolution precedes a commit that can fail — are not addressed by this edge at
all; that issue stays open on all three counts until the orchestration change
lands, and on two counts after it.

**`AWAITING_APPROVAL` means one thing.** Its durability is now justified by its
only remaining occupant: a step a human is being asked about, which a restart
must preserve because the answer is still coming.

**`orchestration` removes its workaround, in its own change.** This ADR makes
the legal edge exist; it does not touch `runner.py`. The synthetic `PENDING →
AWAITING_APPROVAL` commit and the comment explaining it are removed by PR #249,
which owns that file and rebases onto this one. Until it does, that path still
commits twice — legally, since neither edge is removed here. That the
workaround is left working rather than broken is what lets the two changes land
in either order without a red `main`.

**A reader of raw execution state cannot tell an automatic refusal from a human
one** without resolving the `approval_ref` (§4). Accepted deliberately. If that
join proves to be one consumers cannot make — if something needs the
distinction without access to the trail — the answer is to revisit §4's rejected
alternative, and it would then be a `core` type change with its own ADR under
golden rule 5.

**The widening is only as good as the `approval_ref`.** `PlanExecution` can
check that an id is present; it cannot check that it resolves to a stored
decision, which is #107 and is unchanged by this. This change does not weaken
that position — it requires the id in one more place — but it does put slightly
more weight on it, since the id is now the *only* thing distinguishing a
legitimate automatic denial from an asserted one.
