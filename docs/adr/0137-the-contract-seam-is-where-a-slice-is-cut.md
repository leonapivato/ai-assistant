# 137. The contract seam is where a slice is cut, and the triad rides with its primary implementation

- Status: Proposed
- Date: 2026-08-11
- **Durability clause.** Every reference below to ADR-NNNN is to its text as it
  stood at this ADR's base, `4bba371d`, not to its status on any later day. Every
  ADR this decision composes with reads `Accepted` there. References to
  `CLAUDE.md` and `CONTRIBUTING.md` are likewise to their text at that commit —
  which matters more here than usual, because §5 decides that two of those
  sentences change, and a reader arriving after the implementation lane has
  landed will find the amended text, not the text quoted here. Where a later ADR
  *changes* one of the ADRs cited, this ADR is read against the text quoted here
  and that ADR's own record says what moved. The `Date` line is this ADR's
  authoring date in this clone's frame, the convention ADR-0112, ADR-0113,
  ADR-0129 and ADR-0131 state for their own; the base named here is the anchor
  that does not move under either frame.

## Context

### A slice that spanned five subsystems cost twenty-four rounds

PR #959 delivered one dispatched lane. It landed +7,828 lines across 30 files
and took **24 review rounds**, with a worker handoff at round 9 when the
authoring agent's context was exhausted, two architecture-`BLOCK` overrules, and
finally an owner authorization to merge past a standing `BLOCK`. Nothing in that
sequence was a failure of the agent or of the reviewer. The lane was fenced
correctly, the findings were mostly true, and the change is one the roadmap
wanted.

What it was, was **too much machinery in one unit of review**. The slice put new
production machinery into several subsystems at once, and the cost did not
divide across them — it compounded. That is the observation this ADR turns into
a rule.

### Review does not decompose the way a diff does

A reviewer reads one diff and produces one finding list. Each subsystem's new
machinery draws its own findings, and they arrive in a single triage queue
against a single tree, every round re-reading all of it. Two subsystems do not
cost twice one subsystem; they cost more, because each round's fixes to one half
are re-reviewed alongside the other half, and a finding answered in round *n*
reappears against moved context in round *n+2*.

The second-order cost is worse and is what #959 actually hit: a lane deep enough
into that loop exhausts the context that made keeping the work together look
cheap in the first place, and the handoff spends it all again.

### A contract cannot stay soft for two consumers at once

There is also a sequencing reason, independent of volume.

Once the first consumer's implementation has been reviewed, changing the
contract to suit a second consumer invalidates reviewed bytes. Inside one lane
that is rework at full price, paid in the same loop that is already running.
Split across two lanes, the identical change is just the second lane's ordinary
brief, written against a merged contract.

So the question is not only *how much* rides in one lane, but *where the cut
falls*. A cut that separates a contract from every one of its consumers has its
own failure, which the ratified corpus already names — ADR-0015 §5:

> a contract ratified with no implementation contact is how a seam that does not
> survive first use gets blessed.

ADR-0015 §5 offers the throwaway spike branch as the remedy for that, discarded
before the ADR PR opens. The spike gives contact, but its lessons are never
reviewed alongside the contract — they survive only as whatever the ADR author
remembered to write down. This ADR keeps the spike and adds the stronger form:
the contract's **first real consumer** rides with it, in the tree, under review.

### Where the rule had no authority to stand on

The rule below was ruled by the owner on 2026-08-11 and first written as
dispatcher-side process prose in PR #990. Adversarial review of that PR raised,
across two rounds, that the prose asserted an exception the standards do not
grant. The lane verified the finding rather than complying with it, and it held
(issue #992). Two sentences are in the way, both quoted from this ADR's base:

`CLAUDE.md`, under "One subsystem per change":

> The one exception is a Protocol triad (below): contract, conformance suite,
> and canonical fake are one unit of work, not three changes.

`CONTRIBUTING.md`, under "Adding a Protocol: land the triad together":

> It stays a small diff because it is a contract and its guardrails, with no
> *production* implementation attached (the canonical fake is an
> implementation, but a test-only one).

Two supports were offered for the prose and neither carries it. `worker.md`
does admit "a Protocol triad, or an explicitly-sanctioned cross-cutting
change" — but it is an agent definition, not a ratified standard, and cannot
widen `CLAUDE.md`. And ADR-0015 §5's implementation-contact clause, quoted
above, justifies the **spike**; reading it as authority for attaching production
code to the triad reads it wider than it holds.

That is why this is an ADR and not a documentation edit. The exception list is a
real decision, and widening it is a decision change.

### Neither sentence was ever ratified

Worth stating plainly, because it decides §6. Neither clause has an ADR behind
it. `CLAUDE.md`'s "One subsystem per change" bullet entered the tree in
`796c0d53`, the initial scaffold commit, with no `Refs:` trailer.
`CONTRIBUTING.md`'s triad section entered in `70903847`, whose trailer is
`Refs: #30` — an issue, not an ADR. ADR-0003 records the development standards
and names `CONTRIBUTING.md` as "the operational reference", but its Decision
states neither sentence, and the triad section postdates it.

So this ADR is not overturning an earlier ruling. It is the **first ratified
authority** for the exception list, and it ratifies a wider one than the prose
had.

## Decision

### 1. New machinery in more than one subsystem is more than one lane

> **Normative.** A slice is one lane only if its implementation puts substantial
> **new machinery** into at most one subsystem. Where it would put new machinery
> into two or more, it is decomposed into more than one lane before it is
> dispatched, and §2 governs where the cut falls when the subsystems are
> separated by a contract.

The distinction the clause turns on is **new machinery** against **adaptation**,
and it is a distinction about what is being built, not about line count.

New machinery is the thing that did not exist: a store, a loop, a codec, a
producer, a policy engine. Adaptation is everything that merely follows from it —
a call site updated, an argument threaded through, a method added to a class that
already had the rest of them, an implementation of a Protocol method a subsystem
already almost satisfied.

> **Normative.** Adaptation does not count against the bound in this section. A
> lane may carry adaptation across any number of subsystems.

That asymmetry is deliberate and is what keeps the rule from fragmenting
ordinary work. A contract change that ripples a new argument through six call
sites is one lane, because six adaptations draw one class of finding. Two new
machines draw two, and they compound.

### 2. The sanctioned cut is the contract seam

> **Normative.** Where a slice fails §1 and its subsystems are separated by a
> contract, the cut falls at that contract, and the **contract triad together
> with its primary production implementation is one unit of work** — one lane,
> one PR. Primary means the consumer whose demands shape the contract, not the
> one that is cheapest to write. This clause widens the exception to "one
> subsystem per change" from the triad alone to the triad with its primary
> implementation; it does not create a general licence for cross-subsystem
> lanes, and any other cross-subsystem pairing remains outside the exception.

The pairing is the whole point of cutting here rather than one seam further out.
The contract stays **soft while its hardest consumer stress-tests it**: its
shape is still open in the tree, in the same review, when the first real caller
discovers what it got wrong. A contract whose only exercise is its own
conformance suite hardens before anything has tried to use it in anger, and the
first real consumer must then either bend around a shape that is already
ratified or reopen a settled decision.

> **Normative.** The sequence ahead of the paired lane is unchanged. A
> substantive contract ADR still ships as its own PR and is ratified before the
> implementation PR that depends on it (ADR-0015 §5, `CLAUDE.md` golden rule 5),
> and the paired lane is that implementation PR.

What pairs is the triad's **code** with its first real caller. What does not
change is which document is ratified first.

### 3. The triad itself is never split

> **Normative.** Nothing in §1 or §2 permits splitting a Protocol triad. The
> Protocol, its shared conformance suite, and its canonical fake with the
> concrete `Test…Contract` subclass land in the same change, as
> `CONTRIBUTING.md` → "Adding a Protocol: land the triad together" requires.

This section adds no obligation; it forecloses a misreading. §1 is a rule about
splitting work, and the triad is the one unit that a splitting rule must not
reach. §2 says what rides **with** the triad, never what may be taken out of it.

### 4. Each further consumer group is a follow-on lane

> **Normative.** Every consumer of the contract other than the primary
> implementation is a separate lane, briefed only after the paired lane has
> merged. The merged contract text is that brief's authority.

This is the same sequencing golden rule 5 applies to an ADR and its
implementation, applied one step later: a brief written against an unmerged
contract is written against a draft in its author's head.

A consumer group may hold more than one consumer where they draw one class of
finding — three call sites adapting to the same new method are one lane under
§1, because they are adaptation.

### 5. What this decides in the standards, and what lands where

> **Normative.** This ADR decides that `CLAUDE.md`'s "One subsystem per change"
> exception and `CONTRIBUTING.md`'s "no *production* implementation attached"
> clause are amended to admit the paired lane of §2. The wording of those two
> edits is this ADR's **implementation** and is out of the lane that authors
> this ADR; it lands in a separate PR after this ADR merges, under golden rule
> 5's ordinary sequencing.

Naming this explicitly matters because the two files are ADR-0027 §3 floor paths
and one of them was held by a concurrent lane while this ADR was written.
Deciding the amendment and writing it are separable, and separating them is what
let this decision be reviewed on its own merits rather than racing a file.

> **Normative.** Until those edits land, the standards read as they do at this
> ADR's base. An agent that finds its brief in conflict with the unamended
> sentences resolves the conflict in favour of this ADR, which outranks both
> documents, and says so rather than narrowing its lane.

That clause exists because the window is real and an agent in it would otherwise
be correct to flag its own brief.

### 6. What this records against earlier ADRs

- **No record is owed on any earlier ADR, and none is written.** ADR-0082 §1
  asks whether a reader holding only the earlier ADR would now act differently or
  read one of its clauses more widely than it now holds. The two sentences this
  ADR amends are not clauses of any ADR: `CLAUDE.md`'s entered the tree in the
  initial scaffold commit with no `Refs:` trailer, and `CONTRIBUTING.md`'s
  entered under `Refs: #30`, an issue. There is no earlier ruling to make false.
  This is the **stacked addition** ADR-0082 §1 describes — recorded in the ADR
  that makes it, and nowhere else.
- **ADR-0003 — nothing owed.** It records the development standards and names
  `CONTRIBUTING.md` as "the operational reference" in its Context, but its
  Decision states neither amended sentence, and the triad section postdates it.
  No clause of ADR-0003 becomes false or over-wide. ADR-0082 §1 forecloses the
  book-keeping objection that would otherwise be raised here: a record may not be
  demanded because a document "should mention" a change, only by naming a
  sentence the change falsifies.
- **ADR-0015 — nothing owed, and its §5 is applied rather than narrowed.** §2
  above keeps ADR-0015 §5's sequencing verbatim: the contract ADR ships as its
  own PR, ratified before the implementation PR that depends on it. The spike
  permission stands untouched and unused by this decision; §2 adds a second,
  stronger form of implementation contact beside it, which is an addition to
  ADR-0015 §5's remedy and not a contradiction of it.
- **ADR-0065 — nothing owed.** Its §4 cites "one subsystem per change" as the
  reason `planning` conformance cases were deferred out of a `memory` lane. That
  reasoning is unaffected: the two subsystems there are not separated by a
  contract this decision pairs across, so §1 splits that work exactly as it was
  split.
- **This ADR's `Status`.** It decides no Protocol and no `core/types.py` value —
  it decides how work is cut into lanes and what two standards documents will
  say — so the required review set is adversarial alone (ADR-0015 §1,
  `CONTRIBUTING.md` → "Stop when the required reviews are green"), and the
  architecture lens ADR-0130 §12 owed is not owed here. This follows ADR-0132's
  note for the same reason it gave. The ratification sequence is the one
  `CONTRIBUTING.md` → "Finishing an ADR PR" writes down, and this ADR took it
  rather than re-arguing it: drafted, reviewed and revised as `Proposed`, with
  the status flipped only once the required review returned clean on one tree,
  and that review re-run on the flipped tree. The PR carries the round record;
  nothing implements against this ADR until it has merged.

## Consequences

**Easier.**

- **A lane can finish.** The bound in §1 is set where the compounding starts, so
  a dispatched lane has a review loop it can converge rather than one that
  outruns its context. That is the cost #959 paid and the one this rule exists
  to stop paying.
- **A contract meets a real consumer before it hardens.** §2 puts the first
  caller in the tree while the contract is still open, which is the contact
  ADR-0015 §5 asks for, in a form that is reviewed rather than remembered.
- **A follow-on lane's brief has a merged authority to cite.** §4 removes the
  case where two lanes negotiate a contract that neither has landed.
- **The exception list is ratified.** Until now the rule that decides whether a
  cross-subsystem PR is legitimate lived in two unratified sentences, and a lane
  that needed to argue about it had nothing to cite. §5 fixes the citation as
  much as it fixes the rule.

**Harder, and accepted.**

- **Consumer lanes serialize.** §4 makes every consumer group wait for the
  paired lane's merge rather than running beside it. For a contract with several
  consumers this is straightforwardly slower in wall-clock terms, and it is
  accepted: the alternative is the compounding loop of §1, which is slower in
  the end and unpredictably so.
- **Each additional PR pays its own floor rounds.** Splitting one lane into
  three means three review loops drawing on the same finite Codex quota, and the
  rebases between them may land in ADR-0027 §3's floor. Accepted on the same
  ground — the rounds a decomposed batch spends are bounded and predictable,
  where #959's were neither.
- **"Substantial new machinery" is a judgement.** §1 gives the distinction and
  worked categories but no threshold, deliberately: a line count would be gamed
  and would misclassify the cases that matter. The judgement sits with the
  dispatcher at slice time, where it is cheap, rather than with the reviewer at
  round 9, where it is not.

**Revisit when.** This rule is on trial. The measure is the next implementation
batch's aggregates — the per-lane round counts and churn ratios that
`just review-codex` already prints (ADR-0020 §2) — read against #959's baseline.
If decomposed lanes do not converge in materially fewer rounds each, the
compounding argument in Context is wrong and §1's bound is in the wrong place.
If they converge but the serialization in §4 dominates the batch's wall-clock
time, the cut in §2 is right and the sequencing in §4 is the part to reopen.
