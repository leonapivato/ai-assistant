# 135. A duration is honoured whole, and a poll's budget bounds its occupancy rather than an entry's eligibility

- Status: Proposed
- Date: 2026-08-11
- **No `core` surface changes** — no Protocol in `core/protocols.py`, no type or
  member in `core/types.py`, `PROTOCOL_VERSION` untouched, no signature and no
  error type moved — and **no implementation lands with it**: no `src/`, no
  `tests/`. What it decides is how two figures ADR-0131 §5a names and one
  argument ADR-0131 §4 declares behave at the top of their ranges.
- **Its required review set is both lenses.** `scripts/ship.sh` fires its
  architecture requirement on `core/protocols.py` or `core/types.py` alone and
  this ADR touches neither, so the requirement here is the dispatcher's rather
  than the script's. It is owed because a surface's *semantics* are part of its
  contract even where its shape is untouched: what this decides is what
  `next_notification`'s `budget` argument means on the `AssistantEngine` Protocol
  ADR-0085 §1 promoted, and the architecture lens is the one that raised all
  three of the findings the Context records. ADR-0134 took adversarial alone for
  a `Settings` default and said why; an argument's semantics on a promoted
  surface is the other case. `docs/adr/**` being in ADR-0027 §3's review floor
  bears on what a base move costs, not on which lens is required.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-11**,
  the durability form ADR-0100 established and ADR-0125, ADR-0126, ADR-0127 and
  ADR-0134 followed. This decision turns on the exact wording of ADR-0131 §2a,
  §3, §4 and §5a and on ADR-0089 §3's marked/unmarked split, so a citation
  meaning "whatever it says when you read it" would not be checkable.
- **This ADR is marked under ADR-0089.** Every obligation it imposes is a marked
  clause; unmarked text explains what a marked clause means and supplies no
  obligation of its own.
- **Nothing in ADR-0131 is replaced.** §4 below runs ADR-0070 §1's test on every
  clause this ADR reaches, clause by clause, and finds none a reader acts on
  differently. This is the stacked-addition category, so no `Status` edit is owed
  to ADR-0131 under ADR-0082 §1.

## Context

### One square inch, three architecture blocks, and no ratified sentence about it

ADR-0131 §5a makes `hub_notification_lease` and `hub_max_notification_budget`
`Settings` fields with the range `> 0`. Both are bounded **below and not above**,
so `timedelta.max` is a legal value for each, and §4 declares a `budget` argument
whose upper bound is `hub_max_notification_budget` — which is to say, no fixed
upper bound at all. Nowhere does ADR-0131 say what a hub does when a duration it
has accepted cannot be added to the hub's clock without leaving the range a
`datetime` holds.

PR #959, the lane implementing ADR-0131's delivery seam, met that corner and took
three architecture blocks on it — rounds 15, 17 and 18. Two forced real rework and
one did not, and the pattern across them is the reason this ADR exists rather than
another PR comment:

- **Round 15 refuted a refusal.** The lane refused an in-range `budget` it could
  not turn into a deadline. §4 is marked that `budget` is "honoured over the
  closed range from zero to `hub_max_notification_budget`" and reserves refusal
  for one "outside that range — negative, or above the bound", so refusing an
  in-range value invents a refusal mode the ADR does not have. Correct, and fixed.
- **Round 17 refuted saturation**, which round 15's fix had reached for: carry the
  instant to the last representable one. With `timedelta.max` configured that
  serves roughly eight thousand years where the caller asked for far more —
  accepting one duration and honouring a shorter one. Correct, and fixed. An
  integer-microsecond representation was tried on the way and fails too:
  `timedelta.max` is about 8.6e19 µs and overflows SQLite's `INTEGER`.
- **Round 18 was overruled on the merits.** It held that a poll whose budget had
  elapsed during a slow acknowledgement must not then select an entry. §4's marked
  zero-budget clause contradicts it outright, and the dispatcher verified both
  clauses and upheld the lane. The overrule is recorded on PR #959.

Three rounds is more than a ratified sentence costs. The first two were the corpus
working — a lane proposed, a reviewer checked it against the text, the text won.
The third was the corpus failing, because a reviewer reading §5a's figure bullet
without §4's zero-budget clause reaches a defensible-looking wrong answer, and
nothing in the document stops them.

### Why the corner was reachable three times over

Each attempt was refuted by a *different* ratified sentence, and none of the three
sentences is about representability. §4's honour clause excludes refusing and
excludes clamping; §5a's ranges exclude an implementing lane inventing a ceiling;
§3's "the lease runs for `hub_notification_lease`… measured on the hub's clock"
excludes serving a shorter lease than the one configured. Every attempt satisfied
some of them. The lane's first overrule argued saturation was *entailed* by three
of those constraints and the following round found the fourth, which is precisely
the shape of a question that a document does not answer: reconstructible in
principle, and reconstructed wrongly twice in practice.

Issue **#971** parked exactly this as a documentary rider, on the reading that the
behaviour is unreachable in any shipped configuration — the defaults are 300 s and
120 s — so the gap was paper rather than product. That reading was right about the
product and wrong about the cost. The gap has now spent three review rounds on a
seam whose implementation is otherwise finished, and a fourth reviewer arriving at
this corner would start from the same blank page.

### What is genuinely undecided, and what only looks it

**Genuinely undecided:** what an accepted duration means at the top of its range,
and therefore which implementation shapes are available. ADR-0131 states honour,
refusal, ranges and a clock, and states no arithmetic — the lane's own `grep` over
it for `now +`, `+ budget`, `+ lease`, `deadline =` and `computed as` returned
nothing, which is why the shape was an implementing lane's to choose and why
choosing it wrongly twice broke nothing ratified.

**Only looks undecided:** whether an elapsed budget forbids selecting an entry.
§4 decides it, in a marked clause, in the one case where the question has a
forced answer — a `budget` of zero, which is elapsed the instant it starts. What
this ADR does for that question is state the general rule the special case already
entails, so the next reader does not have to derive it.

**Not in scope at all:** the same lower-bounded-only shape across the tree's other
duration settings, which #971 also records. Only this seam relates a configured
duration to the hub's clock, which is why only this seam meets the boundary. §5
below declines the general question deliberately.

## Decision

### 1. An accepted duration is honoured whole

> **Normative.** Where this seam accepts a duration, the hub honours it at its
> whole configured length. A `budget` argument inside ADR-0131 §4's closed range
> is waited out to its full span; a configured `hub_notification_lease`
> (ADR-0131 §5a) runs for its full span; and a configured
> `hub_max_notification_budget` (§5a) admits every `budget` up to and including
> it. In none of the three does the hub clamp, saturate, truncate, round or
> otherwise shorten the value, and in none does it refuse the value, on the
> ground that the hub cannot represent some quantity derived from it.
> Representability is the implementation's problem and is never part of the
> answer the caller or the operator gets.

**The ground is §4's marked honour clause, and being precise about which sentence
obligates is worth a paragraph.** ADR-0131 is a marked ADR, so under ADR-0089 §3
"the marked clauses are the whole of what it obligates" and "unmarked text is read
to determine what a marked clause *means*; it never supplies an obligation."
§4's celebrated sentence about clamping — "it is accepting-and-ignoring in a
second costume", with ADR-0084 §2's argument behind it — sits in a column-0
paragraph and is therefore *evidence of meaning*, not the obligation. The
obligation is the marked one: `budget` "is **honoured** over the closed range".
The unmarked paragraph is what tells a reader that "honoured" means honoured at
its stated length rather than honoured by acceptance, and §4's other marked
sentence — the hub "does not silently clamp it in either direction" — is scoped to
an out-of-range budget and so does not reach this case on its own. Getting that
attribution right matters because round 17's correction was argued from the
unmarked sentence, and an argument from unmarked text is persuasive rather than
binding. This clause makes the same rule marked, and extends it to the two
configured figures, which §4's honour clause never covered because they are not
arguments.

**The falsification is on the record and is why this is stated positively rather
than as a prohibition on clamping.** With `timedelta.max` configured, saturating
at the last representable instant does not merely shorten the budget: it shortens
*the lease too*, serving the roughly eight thousand years left to `datetime.max`
against a span of some 2.7 million that ADR-0131 §3 says "runs for
`hub_notification_lease`". A prohibition on the word "clamp" would have
been read as satisfied by an implementation that called it something else — the
integer-microsecond attempt is that shape, and it fails at a different boundary
for the same reason. Stating what the hub owes, rather than one technique it may
not use, is what makes the rule survive the next clever representation.

**What this clause does not do is admit an out-of-range value.** ADR-0131 §4
still refuses a negative `budget` and one above `hub_max_notification_budget`, and
§5a still refuses a non-positive figure at load. This clause is about a value the
seam has *accepted*; the refusals ahead of it are untouched, and §4 below records
that.

### 2. Elapsed time is measured against the span, and the span's far end is not materialized as an instant

> **Normative.** An implementation of this seam measures **elapsed time against
> the configured span**. It does not compute, persist or compare an instant
> obtained by adding an accepted duration to the hub's clock. This binds both
> measurements the seam makes: a poll's remaining wait is its `budget` less the
> time elapsed since that poll began, and an entry's lease is judged by comparing
> the time elapsed since the lease was **taken** against `hub_notification_lease`
> (ADR-0131 §3). Neither measurement is the other's, and satisfying one does not
> discharge the other.

> **Normative.** A representation that cannot hold the sum of the hub's clock and
> an accepted duration is not a ground on which any figure of ADR-0131 §5a gains
> an upper bound. No implementing lane may narrow a §5a range to make an
> arithmetic fit.

**Both halves are named because the seam discharges this in two places with
different mechanics, and a clause written around one word — "deadline" — would
have covered only the poll.** The poll's budget lives in memory for the length of
one request; the lease is a column in a durable store, read back by a later
process. They fail differently: adding `timedelta.max` to `datetime.now()`
overflows `datetime` outright, while a lease *expiry* stored as integer
microseconds overflows SQLite's `INTEGER` at about 8.6e19. Both were reached on
PR #959 and both are recorded under Alternatives considered. A single clause that
named only a deadline would leave the lease side open for the next round to
relitigate, which is the specific failure this ADR is paying three rounds to
close.

**Stating a mechanism rather than only an outcome is deliberate, and it is the one
place this ADR spends more than it strictly must.** §1 alone is enough to judge
any implementation correct or incorrect: an implementation that shortens a
duration violates it, whatever shape produced the shortening. But §1 alone is what
the corpus already effectively had, and two lanes derived two failing shapes from
it. The value of naming the shape is that a lane no longer has to rediscover which
representations survive `timedelta.max`; the cost is that a hub built on a wider
clock type, where materializing the instant would be perfectly correct, is
foreclosed from the simpler implementation anyway. That cost is real, it is
accepted, and it is bounded — this clause binds this seam, not the tree.

**Why the lease is anchored at its start rather than at its end.** ADR-0131 §3
gives the lease a *source and a clock* — it "runs for `hub_notification_lease`
(§5a). It starts in the indivisible step §2a fixes, measured on the hub's clock"
— and says nothing about what is stored. Storing the instant the lease was taken
and comparing elapsed time against the configured span keeps every word of that
true for any legal figure: the duration is the configured one, the clock is the
hub's, the start is §2a's indivisible step. Storing the expiry instead makes the
stored value a function of a figure that may not fit, and it also silently
freezes the span at the moment the lease was taken, so an operator's change to
`hub_notification_lease` would apply to leases granted after the change and not
to those outstanding. That second effect is not what §3 describes either, and it
is reachable on ordinary figures rather than only at the extreme.

**What the first clause does not reach is an instant the hub was handed.** It
binds an instant *derived* by adding an accepted duration to the hub's clock, and
nothing else. A candidate's own expiry is a field ADR-0130 §2 puts on the
candidate, and ADR-0131 §3's departing rule compares it against the hub's clock
directly; no duration of this seam's is added to anything to obtain it, so that
comparison is untouched here. The distinction is worth drawing because both
comparisons look alike at a call site and only one of them can overflow.

**And the second clause forecloses the tempting fourth attempt.** After crashing,
refusing and saturating were each excluded, the shape still available to a lane
under pressure is to bound `hub_notification_lease` above, so the arithmetic fits
by construction. ADR-0134's precedent forbids it in terms: a figure ADR-0131 §5a
states is ratified-decision ground, and correcting one takes an ADR rather than a
lane's judgement. Saying so here means the next lane does not have to reason from
a precedent about a different field.

### 3. `hub_max_notification_budget` bounds a poll's occupancy of its connection, not an entry's eligibility for selection

> **Normative.** A poll's `budget` bounds how long the hub may hold that request
> before answering. It is **not** a deadline after which an outbox entry becomes
> ineligible for selection. A `next_notification` request performs its first
> selection unconditionally — after applying any acknowledgement, and whatever the
> state of its budget — and where that selection succeeds the hub answers with the
> delivery it made, including where the budget has already elapsed, whether
> because the budget was zero or because an earlier step of the same request
> consumed it.

> **Normative.** An elapsed budget is what ends a poll's **waiting**, not what
> forbids its selecting. A poll whose selection found nothing and whose budget has
> elapsed ends without an answer; it does not wait beyond its budget, and it does
> not decline an entry it has already found.

**§4's zero-budget clause is the decisive ground, and it is marked.** ADR-0131 §4
states, normatively: "A `budget` of zero is an **immediate poll**: the hub answers
at once with whatever is available, which may be nothing." A zero budget is
elapsed at the instant it starts. If an elapsed budget forbade selection, the
immediate poll could answer with nothing else *ever* — and §4 says it answers "at
once with whatever is available", which is an obligation to select. So the ADR
already requires selection at the budget's own boundary, and a rule forbidding
selection past that boundary contradicts a marked clause rather than extending it.
Round 18's finding conceded the point in its own remedy, which asked for a
deadline-aware selection "while preserving the required zero-budget immediate-read
behavior" — the exception it carves out *is* the unconditional first read it
objected to.

**§5a's figure bullet says the same thing and is not what decides it.** The bullet
reads: "**`hub_max_notification_budget` at 300 s.** The ceiling on how long one
poll may occupy a connection." Occupancy, in terms, and nothing in it makes the
figure a selection deadline. But it sits in §5a's unmarked "Where each figure comes
from" prose, and under ADR-0089 §3 that supplies no obligation — §5a's marked
clause is about the fields, their defaults, their ranges and their refusal at load.
So the bullet is read here to determine what §4's marked clauses *mean*, which is
exactly the use ADR-0089 §3 sanctions, and the obligation is taken from §4.
Naming which sentence carries the weight is not pedantry: a reader who takes the
bullet as the rule has taken an obligation from unmarked text, and a reader who
notices it is unmarked and stops there loses the reading entirely. Neither is
necessary once §4 is the ground.

**The remedy inverts the clause it invokes, and that is the substantive argument
rather than the textual one.** Where a slow acknowledgement has already overrun
the budget, that occupancy is spent — the connection has been held for that long
whatever the hub does next. Returning nothing shortens the occupancy by exactly
zero, discards a notification the hub is holding, and costs the owner a round trip
to ask for it again. The clause exists to bound how long a delivery connection is
unreclaimable, and refusing to answer does not reclaim it a microsecond sooner. A
rule that spends a notification to buy nothing is not a strict reading of the
bound; it is a misreading with a cost.

**What is not licensed here is an unbounded poll.** The second clause is what
keeps this section from swallowing the bound it is reading: a poll gets *one*
unconditional selection, and thereafter the budget governs how long it may wait
for another chance — not whether it may take what a wait has brought it. A poll
that has waited out its budget with nothing to show ends, and does not extend its
occupancy to look again. So the bound still does the whole job §5a's bullet
describes; what it does not do is reach backwards into a selection the hub has
already made.

**This section is written to be argued with.** `docs/review/guide.md` makes a
finding a hypothesis to check against the text rather than a fact to comply with,
and that cuts both ways: the reading here is now a text a later reviewer can
quote and attack, instead of an overrule they have to find in a comment thread
and take on trust. That is the whole of what ratifying this square inch buys.

### 4. Classification under ADR-0070 §1 and ADR-0082 §1: a stacked addition, clause by clause

ADR-0082 §1 requires the judgement in this ADR's text, naming the clauses reached
and applying ADR-0070 §1's test: would a reader holding only the earlier ADR now
act differently, or read one of its clauses more widely than it now holds?

**Every ADR-0131 clause this ADR reaches, and what happens to it:**

- **§4's honour clause** — "`budget` is honoured over the closed range from zero
  to `hub_max_notification_budget`". Unchanged and strengthened. §1 above states
  what "honoured" costs at the top of the range and extends the same rule to two
  figures the clause never covered. A reader holding only §4 honours every
  in-range budget; under §1 they do the same and know one more thing about how.
- **§4's anti-clamp clause** — the hub "does not silently clamp it in either
  direction". Unchanged and untouched in scope: it is about an out-of-range
  budget, §1 above is about an accepted one, and neither reads the other wider.
- **§4's zero-budget clause.** Unchanged. §3 above generalises it and replaces
  none of it; the immediate poll behaves identically before and after.
- **§4's argument-validation clause** — a refused request "retires nothing, leases
  nothing and mints nothing". Untouched. Nothing here moves validation relative to
  effects, and §3 above is explicit that selection follows the acknowledgement,
  which is the order §4 already fixes.
- **§3's lease clauses** — "The lease runs for `hub_notification_lease` (§5a). It
  starts in the indivisible step §2a fixes, measured on the hub's clock." All
  three facts survive §2 above exactly: the span is the configured one, the start
  is §2a's step, the clock is the hub's. This is the clause the round-17
  correction showed saturation *did* falsify, and the shape §2 ratifies is the one
  that restores it.
- **§2a's indivisible-step clause.** Untouched. §3 above says a poll's first
  selection is unconditional; it says nothing about how selection, minting and
  leasing relate to each other, which stays one indivisible step.
- **§5a's marked clause and its table.** Untouched, and §2's second clause above
  defends them: no range is narrowed, no upper bound is added, no default moves.
- **§5a's occupancy bullet.** Read, not moved. §3 above takes it as evidence of
  §4's meaning under ADR-0089 §3 and states its own obligation from §4.

**So no sentence of ADR-0131 becomes false under this ADR, and no reader acts
contrary to one.** ADR-0131 §9 puts the distinction in its own words, judging its
own relation to ADR-0084: a reader holding only the earlier ADR "was not led to
act *contrary* to anything; they were led to act incompletely." That is the
stacked-addition category ADR-0083 §15 established, and ADR-0134 §3 is its most
recent application — to this same target document, for a corner ADR-0131 likewise
did not address. No `Status` edit is owed to ADR-0131 and none is made.

**The counter-argument deserves stating, because §3 is where it bites.** It runs:
a reader holding only §5a's occupancy bullet could have concluded that an elapsed
budget forbids selection, and after §3 above they cannot — so a reader *does* act
differently, and §3 narrows §5a. The answer is ADR-0070 §1's own: the test is
whether the earlier ADR **decided** the thing being changed, and "anything a
reader would act on differently" is its 2026-07-31 amendment's gloss on *what was
decided*, not a wider standalone test. §5a decided a field, a default and a range;
the bullet explains why the figure is 300 s. The selection reading was never
available to a reader of ADR-0131 read whole, because §4's marked zero-budget
clause forecloses it — which is why round 18's finding had to carve that case out
by hand to state itself at all. A reading that a document's own marked clause
already excludes is not a decision the document made, and correcting it is not a
supersession. **The test controls, not the label** (ADR-0082 §1), and run honestly
it lands on this side.

**No record is owed to ADR-0089.** §3's marked/unmarked rule is applied here, not
narrowed: this ADR adds no mark to ADR-0131, and reads its unmarked text for
meaning exactly as §3 sanctions. **No record is owed to ADR-0084 or ADR-0085**
either — the promoted surface's shape is unchanged, and this ADR alters no
signature, no error type and no `PROTOCOL_VERSION`.

### 5. What this ADR does not decide

- **Nothing about the tree's other duration settings.** #971 records that most
  `core/config.py` durations are bounded below and not above, and that a future
  setting relating one to a clock would face the same question. This ADR binds
  the delivery seam ADR-0131 defines and takes no view on any other setting. The
  general rule would be a better ADR written after a second seam needs it, not
  before.
- **Nothing about ADR-0131's figures, ranges, defaults or refusals.** No range
  gains a bound in either direction, no default moves, and every refusal §4 and
  §5a state is untouched.
- **Nothing about how a poll waits.** Whether the wait is an event, a timeout or a
  poll loop is an implementation's, so long as §2's measurement holds and §3's
  bound on waiting holds.
- **Nothing about clock monotonicity.** ADR-0131 §3 says the hub's clock and this
  ADR does not reopen it; how an implementation defends a clock that steps
  backwards is its own, and no clause here requires or forbids a monotonic source.
- **Nothing about the storage format of a lease anchor.** §2 requires that the
  anchor be the lease's start and that comparison be against the configured span;
  the column type, unit and precision are the implementing lane's.

## Alternatives considered

**Crash with a raw `OverflowError`.** Refused, and this was round 11's adversarial
finding on PR #959. `next_notification` declares `NotificationBudgetError` and
`NotificationOutboxError`; the wire dispatcher maps this project's error types and
nothing else, so an overflow crossing that seam costs a valid request its
connection rather than an answer.

**Refuse the in-range value.** Refused by ADR-0131 §4's honour clause, and this
was round 15's architecture finding. §4 honours every budget in the closed range
and reserves refusal for one outside it, so a hub refusing an in-range duration
has invented a refusal mode the ADR does not have — and a client has no way to
tell it from a bug.

**Saturate at the last representable instant.** Refused by §4's honour clause too,
and this was round 17's architecture finding. It is the shape issue #971 itself
proposed — "honoured to the last representable instant" — and it is the one this
ADR most directly rejects, so closing #971 with this decision closes it against
its own suggestion rather than with it. The falsification is arithmetic: with
`timedelta.max` configured, saturation serves roughly eight thousand years against
a span the caller asked to run for far longer, on *both* the budget and the lease.
That is §4's "accepting-and-ignoring in a second costume" and §3's lease running
for something other than `hub_notification_lease`. It looked entailed at the time —
the first overrule on PR #959 argued exactly that, from three constraints — and the
missing fourth constraint is why an entailment argument is worth less than a
ratified sentence.

**Store durations as integer microseconds.** Refused as a representation rather
than as a policy, and tried on PR #959 between rounds 17 and 18. It moves the
boundary without removing it: `timedelta.max` is about 8.6e19 µs, which overflows
SQLite's `INTEGER`, so a lease expiry stored that way fails on the durable side
after the in-memory side was fixed. Recorded because it is the obvious next idea
after `datetime` overflows, and it costs a round to learn.

**Bound `hub_notification_lease` and `hub_max_notification_budget` above.** Not
adopted, and §2's second clause forbids an implementing lane reaching for it. It
would make every arithmetic fit and it is a change to a ratified figure, which
ADR-0134 establishes takes an ADR of its own. It is also unnecessary: §2's shape
honours every legal value, so the ceiling would buy nothing that is not already
had. A future ADR may still choose to bound them for a reason of its own; what is
excluded is a lane bounding them to avoid an overflow.

**Make selection deadline-aware after the acknowledgement.** Not adopted, and this
was round 18's architecture finding, overruled on the merits by the dispatcher and
ratified against by §3. §4's zero-budget clause requires selection at the budget's
own boundary, and the remedy shortens no occupancy while costing a held
notification and a round trip.

**A dated amendment on ADR-0131 rather than a new ADR.** Not available. ADR-0131
is marked, so under ADR-0089 §5 "No mark is added to a ratified ADR, by a dated
note or otherwise", and under ADR-0089 §3 unmarked text "never supplies an
obligation" — a dated note would be either illegal or inert. ADR-0134 §"Why this
is an ADR and not a dated note on ADR-0131" reasons this out at length for the
same target document and reached the same wall; the difference is that ADR-0134
had to supersede a figure and this ADR replaces nothing, so it takes the stacked
addition rather than the partial supersession.

**Say nothing and leave the overrule comments as the record.** Not adopted, and it
is the alternative with the best short-term economics — the behaviour is
unreachable on shipped defaults, and #971 was parked on exactly that reasoning.
What defeats it is that the record is not where a reader looks. A fourth reviewer
reads the ADRs, finds no sentence about this corner, and reconstructs it from §5a's
figure bullet — which is how round 18 happened after rounds 15 and 17 had already
been argued in comments on the same PR. Three rounds of a required lens is more
than this document cost.

## Consequences

**What gets easier.** PR #959's shape has a text behind it: the poll's
elapsed-against-budget measurement and the outbox's `leased_at` anchor are what
§2 requires rather than what a lane chose, and its unconditional first selection
is what §3 requires rather than an overrule a reader has to find in a comment
thread. A future reviewer of this corner now argues against a clause instead of
against a lane, which is the exchange `docs/review/guide.md` is built on. #971 is
closed — against its own proposal, which §"Alternatives considered" records.

**What gets harder, and it is a real cost.** §2 binds a mechanism, not only an
outcome, so an implementation of this seam is no longer free to compute an expiry
instant even where its clock could hold one. That is a narrowing of implementation
freedom bought to stop a rediscovery, and it is the one place this ADR chose the
more expensive rule.

**A second cost, smaller and worth naming.** ADR-0131's §4 and §5a are now read
against this ADR for one question each. A reader who stops at §5a's occupancy
bullet gets the right answer and the wrong authority for it; a reader who stops at
§4 gets honour-in-range without knowing what honour costs at the top. Under an
append-only corpus that is unavoidable, and §4 above is the whole mitigation
available — ADR-0131's text stands untouched and this ADR carries the map of what
it reaches.

**What is owed next.** Nothing to a lane. PR #959 already implements every clause
here at its head as of this ADR's date; no follow-up issue is filed against it,
because there is no gap between what this decides and what that lane built — which
is the intended relationship between a ratifying ADR and the lane whose review
rounds paid for it. Should a second seam relate a configured duration to a clock,
§5 above names the general question this ADR declined, and it should be asked then
rather than assumed answered by this one.

Refs #971, #959, #943.
