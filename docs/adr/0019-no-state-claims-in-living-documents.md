# 19. No state claims in living documents

- Status: Accepted
- Date: 2026-07-19
- Complements: ADR-0003 §"Documentation". It adds a rule about what the living
  documents may contain; it does not change, narrow, or reverse any clause
  ADR-0003 ratified. See "Relationship to ADR-0003".

## Context

`CLAUDE.md` and `CONTRIBUTING.md` are the project's standing law. They are
undated, they are read as currently-true by every agent dispatched into the
repository, and nothing verifies them. An ADR is the opposite: dated, numbered,
append-only, and read as history.

The migration ADR-0015 performed made that difference matter. `TODO.md` and
`WORKING.md` were deleted and their live content moved out; a substantial body
of workflow prose moved from ADR-0015 into `CONTRIBUTING.md` at the same time
(commit `e59beab`, 2026-07-19). Sentences that were true and legitimate in a
dated record arrived in an undated one, where they had lost the timestamp that
made them true and had acquired the authority of standing law.

Two of them were measurably wrong within the same day:

- **The test count.** `CONTRIBUTING.md` described the gate as "~33 seconds end
  to end (27s of it pytest, 5,777 tests)". By the time #69 was written the
  actual count was 5,803 — drift of 26 tests, on the same date the claim was
  written. The normative content of that sentence is *run the whole suite*; the
  precision was decoration that guaranteed future wrongness.

- **The triad backfill.** `CONTRIBUTING.md` asserted "Every Protocol that exists
  today has its triad; the backfill is complete", and admitted in the following
  sentence that nothing verified it. It was false: `FeedbackProcessor` had no
  canonical fake. That was found **mechanically**, by the triad check built in
  #39 and landed in #51 (`tests/core/test_protocol_triad.py`, commit `bdf801e`),
  not by review. Review had asserted the opposite into the contributing guide
  and it went unchallenged, because there was nothing to challenge it with.

The repository had already diagnosed this failure and then reproduced it.
ADR-0015 §"Hand-maintained coordination state decays exactly when it matters"
argued precisely this point, with `WORKING.md` as its evidence — a file whose
only job was preventing lane and ADR-number collisions and which was wrong about
both. That is why `WORKING.md` was deleted. The migration then planted
hand-maintained state claims in the document that replaced it. ADR-0015's
general lesson — **invariants enforced by prose rather than mechanism do not
hold** — had been applied to the code and not to the documents describing it.

The rule was adopted by the repo owner in #69, implemented in #77 (commit
`7b6bbd1`), and is ratified here. The adversarial reviewer on #77 raised the
absence of an ADR as a `blocker` in three rounds; it was waived there for
process reasons — an agent may not self-assign an ADR number
(`CONTRIBUTING.md`), and the dispatch for #77 assigned none — and the finding
was filed as #81 rather than dropped. The reviewer's argument was correct, and
this ADR is the record it asked for.

## Decision

**We will keep state claims out of the living documents.** A living document
carries **rules and the reasoning behind them** — both durable — and never
**snapshots**. If a fact about the repository matters, either a check asserts it
or a dated ADR records it.

**0. What makes a document "living".** Two properties together, not a fixed
list of filenames:

- **Undated and continuously revised in place**, so a sentence in it carries no
  timestamp and no indication of when it was last true.
- **Read as currently authoritative** — a contributor follows it to decide what
  to do now, rather than consulting it as history.

`CLAUDE.md` and `CONTRIBUTING.md` are the clearest cases and the ones that
motivated this ADR, but the rule follows the properties: `README.md`,
`VISION.md`, and the rubrics in `docs/review/` are living documents too, and any
future undated standing document is governed on arrival without amending this
ADR. `docs/adr/` fails the first property by construction, which is clause 4.
`CHANGELOG.md` fails the second: its entries are dated releases read as history.

**1. What counts as a snapshot.** Anything **measured or observed** rather than
**decided**: a test count, a wall-clock timing, a "currently"/"today"/"so far",
or a claim that some piece of work is finished. The test is provenance — did
this sentence come from an argument, or from a measurement? Written into an
undated document a measurement loses the timestamp that made it true, becomes an
assertion no one owns, and decays from that moment while still reading as law.
The durable form is to name the rule and point at whatever actually holds the
state.

**2. A fact a check owns is not a snapshot.** It is a description of something
mechanically true, and the check is what keeps it that way. "Every Protocol has
its triad" is an unowned assertion on its own; with a gate-failing check behind
it, it is a statement about an enforced invariant. Name the check, so a reader
can tell the two apart, and prefer a claim that can only stay true — a list that
can only shrink, having reached empty, does not decay the way a count does.

**3. A decision does not become a snapshot by describing a situation.** "You are
the only agent in this clone" is a premise these documents *set* (ADR-0015), not
a count someone took. If it stops holding, the workflow has been broken — a
different problem from a fact going stale.

**4. ADRs are exempt, and that exemption is what makes the rule workable.** An
ADR is a dated, point-in-time record; "at the time of writing, X" is exactly
what belongs there and stays correct as history. Snapshots are not to be
scrubbed out of `docs/adr/`, including ADR-0015's own copies of the numbers this
ADR cites as having drifted — they were correct when written and remain correct
as history. The rule does not ask anyone to stop recording facts; it asks them
to record facts where facts are dated.

**5. Deliberately no mechanical check.** This is enforced by reviewers reading
the diff, the way style is. We considered and rejected a linter that hunts state
claims in prose, for three reasons:

- It cannot do the job. Clauses 1–3 turn on provenance and on whether a check
  owns the fact — distinctions a text matcher cannot draw. It would flag rules
  and premises alongside measurements, and the false positives would be routed
  around rather than fixed.
- The cost pattern is the one ADR-0015 exists to remove. A checker for a
  documentation convention is `fix(dev)` work: tooling that maintains itself,
  which ADR-0015 found had come to dominate the commit history at the expense of
  the subsystems the project is actually for.
- The failure mode does not warrant it. A stale sentence in a guide is slow and
  cosmetic. It misleads a reader; it does not break a build. Mechanism is worth
  its cost where the invariant is load-bearing and the violation is silent —
  which is the case for `lint-imports` and the triad check, and is not the case
  here.

This is a deliberate limit on "mechanism over prose", not an exception smuggled
past it: that principle argues for mechanism where mechanism can decide, and
here it cannot.

## Relationship to ADR-0003

**This ADR complements ADR-0003; it does not amend it.** ADR-0003 §"Documentation"
ratified docstring convention, the "comments explain why" rule, recording
decisions as ADRs, and `CHANGELOG.md` format. None of those clauses is changed,
narrowed, or contradicted here — every one of them remains true in exactly the
form ADR-0003 states it.

The distinction matters because ADR-0001 makes ADRs append-only: an amendment or
supersession is how a *past decision* is changed, and it obliges updating the
older ADR's status. This decision governs a subject ADR-0003 never addressed —
what the living documents themselves may assert — so there is nothing in
ADR-0003 to revise and its status is unchanged. The two sit side by side in the
same domain, which is why this ADR is filed adjacent to ADR-0003 rather than
folded into it.

The reference runs one way, from here to ADR-0003. ADR-0003 is not edited to
point back: it is `Accepted`, ADR-0001 makes accepted ADRs append-only, and a
complementary decision is not one of the grounds (amendment, supersession) for
touching one. A reader arriving at ADR-0003 finds this ADR the way any later
decision is found — by reading forward through `docs/adr/`.

## Consequences

- `CONTRIBUTING.md` states the rule in summary and points here for the evidence
  and the rejected alternative, so the rationale lives in one place rather than
  two. That is itself an instance of the rule: the durable statement is the
  rule, and the dated record holds the observations that motivated it.
- Reviewers gain a specific thing to look for in a documentation diff, with
  clauses 1–3 as the test. Some judgement calls will be wrong in both
  directions; that is the accepted cost of not having a checker.
- Removing counts and timings makes some sentences vaguer. "Run the whole suite"
  carries the instruction without carrying an expiry date; a reader wanting the
  current number runs the gate, which is authoritative and never stale.
- Claims that a body of work is complete now require either a check that fails
  when it stops being true, or an ADR that dates the claim. Writing one is
  strictly more work than asserting it in prose. That is the intended price.
- **What would trigger revisiting.** Evidence that reviewer enforcement is not
  holding — state claims landing in the living documents repeatedly and being
  found later by drift rather than by review. The response would first be to
  ask whether the fact wants a check that owns it (clause 2), which is the
  durable fix, before reconsidering a prose linter, which clause 5 rejects on
  grounds a higher violation rate would not change.
