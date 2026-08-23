# 187. The band ordering stands against an outsider's supply, and precedence orders a band without excluding it

- Status: Proposed
- Date: 2026-08-23
- **This is the *second* revisit of ADR-0072 §5's band ordering, and the first one
  to weigh the adversarial input.** #663 records ADR-0072 §5's revisit trigger as
  fired and asks two questions.
  [ADR-0112](0112-currency-never-ranks-and-retrieval-orders-by-relevance.md) §4 and
  §5 already answered both, and its header says so: "Answers #663's fired revisit
  trigger … in both its halves". That answer stands and this ADR does not
  relitigate it on the ground it was given. What it does is put it against three
  things that postdate it — ADR-0098 §10's adversarial input as
  [ADR-0183](0183-the-adversary-writes-the-source-and-a-reader-derives-no-standing-from-what-it-reads.md)
  §7 strengthened it, #1447's volume argument, and the milestone-23 QA run on
  #1484 — and to rule the one question the record leaves genuinely open, which is
  not the ordering but the **budget**.
- **Decides no `core` surface.** No `core/protocols.py` change and no
  `core/types.py` change: §4's floor is a rule about
  `ai_assistant.orchestration.retrieval`'s composition over the `search` axes that
  already exist, and §4d routes it to a lane that adds none. The required review
  set is therefore **adversarial alone** (`CONTRIBUTING.md` → "Report the review,
  then mark it ready"), on the same reading ADR-0112's header records for itself.
- **Amends and supersedes nothing.** §9 applies ADR-0070 §1's test clause by clause
  to every ADR this decision touches — ADR-0072 §5 and §7, ADR-0112 §1–§5 and §7,
  ADR-0113 §5 and §6, ADR-0110 §8, ADR-0128 §1, ADR-0181 §2 and §6, ADR-0183 §3
  and §7, ADR-0098 §10 — and finds nothing owed. No ADR's `Status` line is edited
  and this branch touches no file but this one.
- **Marked under [ADR-0089](0089-a-ruling-is-marked-and-nothing-else-binds.md) §1.**
  Every obligation this ADR imposes is in a `> **Normative.**` block; unmarked
  prose here determines what a marked clause means and supplies no obligation of
  its own (ADR-0089 §3).
- **Refs:** #663 (the trigger, and the issue this answers), ADR-0072 §5 (the
  ordering and its own revisit clause), ADR-0092 §3 (`reported_at` is the source's
  clock and has no substitute), ADR-0098 §10 (the adversarial input, directed at
  this revisit), ADR-0112 §4 and §5 (the first revisit), ADR-0113 §6 (the budget
  left to the consumer's lane), ADR-0183 §1, §3 and §7 (the adversary, standing,
  and volume), ADR-0181 §2 and §6 (the origin fact and the line that discloses it),
  #1447 (the quantity, held for the owner and cited here, not decided),
  #1484 (the milestone-23 QA run), #789 (leg 7's measurement instrument).
- **Files** #1508 — the disclosure the milestone-23 run observed reading `True` on
  every send, which §5 rules is not this decision's.

## Context

### What #663 asked, and what the record has already done with it

ADR-0072 §5 ruled the assembler's band precedence — `ASSERTED`, then `ATTESTED`,
then `DERIVED` — and set its own revisit trigger on the half it was least sure of:

> The `ATTESTED`-above-`DERIVED` half of that ordering is the least-evidenced part
> of this decision … a connected source's record of the world is generally a
> better warrant than our generalisation over behaviour, but it can be stale in
> ways we cannot detect. It is ruled now because leg 6's sensors will otherwise
> force each consumer to guess, and it is revisited when the first real sensor
> exists (§10).

#663 recorded that trigger as fired and asked two questions: whether the ordering
survives a band whose staleness is undetectable by construction "or does the
ordering want a recency qualification", and what to do about §5's per-band
composition being "ruled and unimplemented".

**Both were answered on 2026-08-06, and the issue stayed open.** ADR-0112 §4 is a
marked clause affirming the ordering "as ruled, unqualified", and refusing the
recency qualification by name; ADR-0112 §5 diagnosed the composition gap as
structural rather than an oversight — neither read on the `MemoryStore` contract
served assembly — and filed **#790**. ADR-0113 then decided the band-scoped
relevance read, and the composition was built: `orchestration/retrieval.py` carries
`BAND_PRECEDENCE` and `assemble_by_band`, whose module docstring names itself as
"that consumer", and `orchestration/loop.py`'s retrieval stage calls it. The tree
answers #663's second question in code.

So the premise a reader coming fresh to #663 would take from it — that neither
question is decided anywhere — is false of the corpus and false of the tree. What
is true is that **nobody closed the issue**, which is the same defect #663 itself
was filed about, one level up: a question answered by a document nothing pointed
back at.

### What the first revisit did not weigh

ADR-0112 §4's argument for the ordering is entirely about staleness mechanisms. It
observes that the `ATTESTED` band has three ways for a belief to stop being live
without the user (ADR-0080 §1's clamp, ADR-0092 §4's user assertion, ADR-0110 §3's
absence under a declared coverage) while ADR-0110 §8 gives `DERIVED` none, and
concludes that "the band #663 worried was undetectably stale is now the only one of
the two whose staleness the system has a mechanism to detect at all".

The words *adversary*, *outsider*, *hostile* and *attacker* do not occur in
ADR-0112's decision text, and neither does ADR-0098. That is checkable and it is
the gap this ADR fills, because ADR-0098 §10 had already written the input and
addressed it to this revisit:

> It adds one input that #663 does not record and that neither ADR-0072 §5 nor
> ADR-0092 §10 could have: **`ATTESTED` is the band an outsider can write into,
> and ordering it above `DERIVED` gives that outsider budget priority over the
> system's own inferences.** … The revisit should weigh it.

ADR-0112 §4 is the revisit and it does not weigh it. No fault attaches: §4's
subject was the question #663 asked, in #663's own terms, and the input sat in a
different ADR's deferral list. But it means the ordering has been affirmed twice on
staleness grounds and never tested against the one that was flagged for it.

### Three things have happened since 2026-08-06 that bear on it

**ADR-0183 §7 supplied the volume argument the input lacked.** ADR-0098 §10 said
the outsider gets budget priority; ADR-0183 §7 adds that "the outsider's budget
priority is not over a fixed quantity of attested material, because the quantity is
theirs to choose", and is explicit that this "strengthens #663's input and does not
decide it". The mechanism is on #1447: re-reading is idempotent (ADR-0161 §1's
`_re_reported` fold), so the growth is not a loop — it is a **supply**, and an
adversary who can place *distinct* material in a source adds durable records on
every read, within every cap, with each read refusing nothing.

**The adversary is no longer a person the user chose.** ADR-0183 §1 rules the class
as anyone who can cause bytes to appear in a source, and gives the reason the top
rung is occupied by default now: a calendar file implies a channel the user
established, "a mailbox has no such implication, so its writers are everyone". The
second reader exists (`readers/email.py`).

**The milestone-23 QA run drove it live** (#1484). After ten ingestion and
consolidation cycles against a hostile source the store held 22 attested records
against 36 derived ones, and the run's item-2 observation records that with any
attested record in the store the turn's selection contains one. Its item 13 also
discharges the honest bound ADR-0112 §4 stated for itself — "no reader on `main`
satisfies its four conditions" — because `CalendarReader` now declares a coverage
(ADR-0115 §4, ADR-0117 §5) and the run observed 38 attested records window-closed
by an absence. The structural argument §4 made has become an observed one.

### What the budget actually is, and who ruled it

ADR-0113 §6 is a marked clause and it is careful:

> **Normative.** This ADR decides no budget, no per-band share, no number of calls
> and no assembly order. ADR-0072 §5's precedence … is affirmed as ruled and as
> ADR-0112 §4 reaffirmed it, and how a consumer divides a budget across bands is
> that consumer's lane's decision.

Its prose names the open question exactly: "this ADR does not rule … that a band
whose page comes back short donates its remainder to the next band — both are real
questions and both belong to the lane that holds the prompt."

The lane that holds the prompt took it, in code, and recorded its reasoning in
`assemble_by_band`'s docstring: "There is one budget, not a share per band, and
each call asks for whatever remains." That choice is defensible on ADR-0072 §5's
own sentence and it degrades well on an empty band. It was made on 2026-08-07,
against a store whose bands nobody supposed an outsider could size. **No ADR rules
it**, and the input that bears on it postdates it by sixteen days.

The budget in the composition root is `RETRIEVAL_LIMIT = 30`
(`app/composition.py`), the first band asks for all of it, and `MemoryStore.search`
applies no relevance threshold — ADR-0128 §1 moved every eligibility predicate
before the ranking cut and added no floor, so a band's read is cut by `limit` and
by nothing else. Thirty distinct entries in a source is therefore the whole of what
it takes to reduce the derived band's share of a turn's context to zero, and
nothing bounds that number (#1447).

## Decision

### 1. The ordering stands, and now against the input that was flagged for it

> **Normative.** ADR-0072 §5's band precedence — `ASSERTED`, then `ATTESTED`, then
> `DERIVED` — is affirmed as ruled, and is affirmed against ADR-0098 §10's
> adversarial input as ADR-0183 §7 strengthens it. That an outsider chooses the
> quantity of `ATTESTED` material is **not** a ground to reorder the bands, and no
> lane may read #663, #1447 or #1484 as licensing a reordering.

**What the outsider can displace, and what they cannot.** The ordering's protective
half does exactly what it was ruled to do under the adversarial input, and this is
the first thing to state because it is the part at risk of being lost in the
argument. `ASSERTED` is read first. A source that supplies thirty thousand entries
does not displace one word the user said, because the user's band is filled before
the outsider's is read at all. The band an outsider can write into sits **below**
the band the supersession law protects, and every mechanism that keeps it there —
ADR-0072 §2's refusal to fold `EXTERNAL` into `ASSERTED`, ADR-0183 §3's refusal to
let content buy a band — holds under supply as well as under content.

What the outsider can displace is `DERIVED`: the system's own inferences about the
user. That is precisely what ADR-0098 §10 said, and it is real. §4 is where it is
answered.

**Reversing the two lower bands is refused, on three grounds.**

*It asserts something false.* Ranking `DERIVED` above `ATTESTED` says our
generalisation over behaviour is a better warrant than a connected source's report
of the world. ADR-0072 §2 rejected that claim in both directions when it refused to
fold `EXTERNAL` into either neighbour, and nothing about an outsider's volume makes
the claim true — it makes the *material* less trustworthy in bulk, not our
inferences better.

*It bounds the outsider only by a quantity the system does not control, and it
fails worst where it is needed most.* Under a reversal the outsider takes whatever
the derived band leaves. At cold start the derived band is empty — which is exactly
when a connected source is the only thing the assistant knows, and exactly when
ADR-0072 §1's argument for observing rather than interrogating is strongest — so
the reversal returns the whole budget to the outsider in the case it was adopted
for. A bound that is a side effect of how much the system happens to have inferred
is not a bound.

*It trades away the band with a staleness mechanism for the band with none.*
ADR-0112 §4's asymmetry has strengthened rather than decayed: `ATTESTED` has three
routes to stop being live and one of them is now live in the tree and observed
under a hostile source (#1484, item 13); ADR-0110 §8 rules that for a `DERIVED`
belief "nothing is asked and nothing is closed". Reversing would put the
unfalsifiable band above the falsifiable one.

**The honest cost of affirming.** A turn's context can be filled with material an
outsider chose, up to whatever the budget leaves after `ASSERTED`. This ADR does
not claim otherwise and does not treat ADR-0098 §2's labelling as making it
harmless: §2 makes the material arrive as data rather than instruction, which is a
different property from how much of the prompt it occupies. §4 bounds the
occupation at one end and names what it does not bound.

### 2. No recency qualification — refused a second time, on a ground the first refusal did not have

> **Normative.** No recency, currency, report-time or staleness qualification
> attaches to band precedence or to the composition that applies it. In
> particular, neither `Attestation.reported_at` nor `SourceReading.as_of` is a term
> in any ordering, score, cut, reservation or eligibility test applied to retrieved
> records. ADR-0112 §1's prohibition is affirmed and is not narrowed by anything
> here.

#663's question 1 asks whether the ordering "wants a recency qualification".
ADR-0112 §1 and §4 already answer no, on the ground that a clock acting on rank is
a mechanism the corpus has refused twice (ADR-0103 §4, ADR-0110 §1) and that
ADR-0103 §9's unknown currency has no place in a total order. Those grounds stand
and are not restated here.

**The adversarial input supplies an independent and, for the `ATTESTED` band,
decisive one: there is no recency value that the adversary does not write.** An
attested record's report time is `Attestation.reported_at`, and ADR-0092 §3 rules
it "the instant the reporting source asserts the fact was current, on that source's
own clock" and forbids every substitute — not our clock, not the ingest instant,
and "in particular **not** the file's mtime". `SourceReading.as_of` is `None` for
the calendar by construction and is refused for email by ADR-0140 §7. So the only
recency a qualification could rank on is a field inside the source's bytes, which
ADR-0183 §1 places in the adversary's gift.

A recency qualification would therefore hand the ranking dial to the party it is
meant to bound: a hostile entry stamped with a fresh `DTSTAMP` outranks an honest
one that has not changed since Monday. ADR-0183 §3's first clause already names the
outcome in its list of standings that content may not set — "the band, the
confidence, the sensitivity, the record identity, the reporting identity, **the
retrieval precedence**, or the grant that a proposal drawn from it carries". That
clause binds the reader; a qualification imposed by the assembler would reach the
same outcome by a route outside the reader, and this clause closes that route
rather than assuming §3 already had.

**So #663's question 1 is answered no, twice, and the reason has inverted.** It is
not that the `ATTESTED` band's staleness turned out to be bounded. It is that under
an adversary the staleness signal *itself* is supply, and a rule that consumed it
would be a rule the source could drive.

### 3. #663's second question is discharged by the record, and nothing is owed for it

> **Normative.** ADR-0072 §5's per-band composition is **built**, not owed. No lane
> owes its implementation, and a later ADR or brief may not carry it as an open
> item. What is owed against the assembler is §4's floor and nothing else.

The chain is: ADR-0112 §5 diagnosed why no lane had built it and filed #790;
ADR-0113 ruled the band-scoped relevance read; the assembler landed as
`ai_assistant.orchestration.retrieval.assemble_by_band`, is wired into the turn by
`orchestration/loop.py`'s retrieval stage, and holds the cross-call obligation
ADR-0113 §5 placed on it — deduplication by record id, keeping the
higher-precedence copy. `BAND_PRECEDENCE` is a module constant rather than a
parameter, for the reason its own comment gives: a caller that could reorder it
could reorder precedence.

ADR-0112 §5's sentence "ADR-0072 §5's per-band composition remains owed and unbuilt"
was true when written and has been discharged by the lane it routed to. That is a
deferral discharged rather than a clause superseded, on the reading ADR-0112 §11
itself used for ADR-0103 §8 and ADR-0110 §9 (§9 below).

**#663 can close on this ADR.** Both of its questions have answers — question 1 in
ADR-0112 §4 and again in §2 above, question 2 in the tree — and what it asked for
that was still missing is §4.

### 4. Precedence orders a band; it does not exclude one

> **Normative.** Band precedence orders the assembler's budget and does not remove
> a band from it. Where the budget admits at least as many records as there are
> bands in `BAND_PRECEDENCE`, every band that has an eligible record for the turn's
> query is represented in the composed context by **at least one** record, and no
> other band's supply may reduce it below that. Precedence governs every other slot
> and every within-band order exactly as ADR-0072 §5 rules it.

> **Normative.** Where a reservation must be taken from a band that would otherwise
> have held the slot, it is taken from the **lowest-precedence band holding more
> than its own floor**, and within that band from its least relevant record. A band
> with no eligible record reserves nothing, and no slot is left empty in order to
> hold a reservation open.

> **Normative.** This ADR rules the floor and **no share beyond it**. A proportional
> split, a per-band quota, a cap on any band's take, or any other reservation
> larger than the one above is a bet on a frequency and waits for the measurement
> ADR-0112 §7's first clause gates and #789 owns. A lane may not adopt one on the
> strength of this section.

> **Normative.** This is a rule about the **consumer's budget**. It grants
> `MemoryStore.search` no weighting authority over any quantity, adds and relaxes
> no read-time axis, and is not the confidence-weighted retrieval whose price
> ADR-0072's Consequences and ADR-0112 §2 both quote as a supersession. ADR-0112
> §1, §2 and §3 are untouched: nothing here orders by currency, within a band or
> across them.

**Why this is the clause the adversarial input actually reaches.** ADR-0098 §10's
input is about *budget priority*, and ADR-0183 §7's strengthening is about
*quantity*. Neither is a claim about which band deserves to be higher; both are
claims about how much of a finite budget one band may take when something outside
the system chooses how much material it holds. The ordering is the wrong instrument
for that and §1 keeps it; the budget is the right one and no ADR had ruled it.

**Per-band composition traded a risk of displacement for a guarantee of it, in the
other direction.** ADR-0072 §5 adopted per-band reads because a band-neutral top-k
lets "a flood of low-confidence inferences … displace an assertion *below the cut*,
where no amount of downstream ordering recovers it". That fix works. What it also
does, unremarked, is remove the lower band's ability to compete at all: under a
band-neutral cut a derived belief of high relevance beat an attested one of low
relevance, and under strict precedence it cannot, however relevant it is and
however irrelevant the thirty attested records above it are. The failure ADR-0072
§5 named as intolerable in one direction became certain in the other, and the
outsider chooses when.

**The floor is ADR-0112 §1's own reasoning applied to the mechanism ADR-0112 did
not examine.** §1 refused to demote a lapsed derived belief because "a stale derived
belief is precisely the record the user most needs to be shown, because being shown
is the whole of its correction affordance", and because "an ordering that hides it
is an ordering that makes the model wrong for longer and quieter". A derived band
displaced to zero by an outsider's supply is that outcome, reached without a clock
and without any lane deciding it. Refusing the currency demotion and accepting the
supply displacement is not a coherent pair.

**What the floor buys, stated exactly, because it is small.** It stops an outsider
making the assistant's own beliefs *absent* from a turn. It does not stop them
making them few, it does not restore personalization at volume, and it is not a
defence of the prompt's composition against a determined supply. One slot is the
boundary between representation and exclusion, and it is the only reservation
derivable without a number nobody has measured — which is why the third clause
gates every larger one behind #789 rather than picking a proportion here. ADR-0103
§5's standing objection is the reason: "a number invented here would arrive with
the authority of a ratified decision and the evidence of a guess."

**The objection this section has to meet, and its honest answer.** A reader may say
the correction affordance does not run through the prompt at all: the user inspects
beliefs through `MemoryStore.list_beliefs`, which is band-scoped (ADR-0073 §1) and
which no other band's supply can starve, so a displaced derived belief is still
visible where it matters. That is true and it is why the harm is not total. What
the floor defends is the other half — the personalization the derived band exists
for, which has no channel but the turn's context, and the *trigger* for a
correction, which ADR-0072 §6 places in what the assistant says back. The
inspection surface answers "what do you believe about me"; it does not stop the
assistant behaving, for thirty turns, as though it had inferred nothing.

**The rule is general, and that is deliberate.** Nothing in it is conditioned on a
band being the outsider's. A user with a very large asserted band can exclude the
calendar from every prompt today, by the same mechanism and with no adversary
involved; under this clause they cannot. The adversarial input is what made the
question urgent, not what makes the answer right.

#### 4d. What the follow-on lane owes

> **Normative.** The floor is implemented in
> `ai_assistant.orchestration.retrieval` by a lane of its own, with no
> `core/protocols.py` or `core/types.py` change and no new `MemoryStore` member: it
> is a composition over the `bands` filter ADR-0113 ruled and the budget the
> consumer already owns. That lane owns the shape — reserving before the first read
> and returning the unused reserve upward, or filling in precedence order and
> repairing a starved band afterwards — and ADR-0113 §6's leave to choose the
> number of calls covers either.

> **Normative.** That lane's obligation is discharged by tests in the assembler's
> own suite. No conformance clause is added to any store's suite: the floor is a
> property of the composition and is invisible to every single call, exactly as
> ADR-0113 §7 says of the deduplication rule beside it.

Naming both shapes and choosing neither is ADR-0072 §7's discipline applied to a
smaller question: what the corpus needs fixed is the property, and the lane holding
the code is better placed than this ADR to say which shape costs less. What is
foreclosed is only the wrong answer — a floor obtained by over-requesting against an
estimate of how many records to expect from each band, which is the headroom bet
ADR-0113 §8 declines and ADR-0112 §7 gates.

### 5. The milestone-23 observation is evidence about the selection, not about the ordering

> **Normative.** No lane, ADR or QA run may cite #1484's item-2 observation — that
> a send's `planned_with_external_content` reads `True` whenever the store holds an
> attested record — as evidence about band precedence or about §4's floor. It is a
> property of the turn's selection, and neither the ordering nor the composition
> changes it in either direction.

ADR-0181 §2 defines the fact as a disjunction over the turn's selection. One
attested record anywhere in that selection sets it, `MemoryStore.search` applies no
relevance threshold (ADR-0128 §1 added none), and `assemble_by_band` reads the
`ATTESTED` band on every turn. So the value would read `True` under a reversed
ordering, under a per-band share, and under §4's floor alike — the floor changes how
*few* derived records a turn can hold, and nothing about whether an attested one is
present.

Saying this plainly matters because the observation is the most vivid thing in the
record and it is about a neighbouring seam. What it is evidence *for* is ADR-0181's
own revisit trigger, which its Consequences state as "the first evidence that users
approve egress confirmations without reading them", and which nothing on GitHub
owned. It is filed as **#1508** rather than folded here: it would be decided by a
similarity floor on retrieval, by a change to what the line says, or by neither, and
each of those is a different lane's.

### 6. The quantity is #1447's, and this ADR bounds the composition rather than the supply

> **Normative.** Nothing here bounds what a source may cause this system to store.
> §4's floor bounds one band's share of one turn's context and no more; it is not a
> retention rule, not a quota, not an eviction rule, and it may not be cited as
> mitigating #1447.

#1447 is held for the owner and its shapes are a store's — retention by count, a
per-source quota, an eviction rule over the `ATTESTED` band. It is cited here for
the one thing it supplies to this decision, which is that the outsider chooses the
quantity, and it is not decided here. The two decisions are genuinely separable: a
retention bound would reduce how much attested material exists, and §4 holds
whether or not it does.

### 7. What this ADR pre-registers for milestone 24: no live arm, and why

> **Normative.** This lane pre-registers **no live QA arm** for milestone 24. The
> milestone's exit as ruled on `docs/roadmap.md` is that "every read of a source
> and every egress is reconstructible from the audit trail alone, origin included",
> and no clause of this ADR bears on it. §4's floor is pinned by the assembler's
> own tests (§4d), and a run that reported the milestone's exit met or unmet on the
> strength of band precedence would be reporting against a criterion the roadmap
> does not state.

ADR-0185 §11 leaves the band-precedence half of milestone 24 "pre-registered by
their own lanes", which obliges this lane to say what it pre-registers rather than
to leave a gap someone later reads as an omission. The honest answer is nothing:
the roadmap lists #663 under milestone 24 because that is where the decision was
scheduled, not because the exit test measures it.

### 8. What this ADR does not decide

- **Whether `MemoryStore.search` gains a relevance threshold.** It is what would
  change the disclosure #1508 records, and it is a `core/protocols.py` decision
  under golden rule 5, gated by ADR-0112 §7 if its case is a frequency.
- **Any share larger than §4's floor** — a proportion, a quota, a cap. §4's third
  clause and #789.
- **What bounds the supply** (#1447, §6).
- **Anything about what a lapse does to standing.** ADR-0110 owns it in full and
  §2 consumes it unchanged.
- **The presentation of a band or an origin in the prompt.** ADR-0072 §6, ADR-0103
  §9 and ADR-0181 §6 own it; nothing here changes what is conveyed, only how many
  records of each band there are to convey.
- **Consolidation's taint ceiling** (ADR-0106 §6) and the scheduler gap #1487
  records against it.
- **Whether the `DERIVED` band's lapse gap is costing retrieval quality.**
  ADR-0112 §6 carries it to leg 8's memory-precision measure, unchanged.
- **The episodic supplement's budget** (ADR-0158), which is a separate budget by
  that ADR's own ruling and which §4's floor does not reach.

### 9. What this records against earlier ADRs: nothing

ADR-0082 §1 requires the judgement in the later ADR's text. It is made here by
applying ADR-0070 §1's test to each earlier ADR: would a reader holding only that
ADR now act differently, or read one of its clauses more widely than it holds?

**ADR-0072 §5 — nothing owed, and this is the load-bearing one.** §1 above affirms
its ordering; §4 rules a floor on the assembler's budget. The question is whether
§5's sentence — "The assembler fills its budget `ASSERTED` first, then `ATTESTED`,
then `DERIVED`" — already ruled the share, in which case §4 would be a partial
supersession rather than an addition. **It did not, and the corpus's own later
reading is what settles it**: ADR-0113 §6 is a marked clause stating that "how a
consumer divides a budget across bands is that consumer's lane's decision", and it
could not lawfully have left to a lane something ADR-0072 §5 had already ruled. §5's
sentence fixes the **order** in which the budget is filled, which §4 leaves exactly
as it is, and is silent on whether a band may take the last slot a lower band with
eligible records could have used. A reader holding only ADR-0072 §5 builds the same
assembler in the same order; what they now also owe is one slot they were never
told they could keep. **Stacked addition over ground §5 left open; no record owed.**

**ADR-0072 §7 — nothing owed.** Its obligation was a band-scoped read and its
deferral was between two signatures. Both are discharged (ADR-0073 for the
enumeration, ADR-0113 for the filter), and §4 adds no read.

**ADR-0112 §1, §2 and §3 — nothing owed.** §1's prohibition on currency ordering is
affirmed in §2 and relied on in §4's fourth clause; §2's citation discipline is
respected — §4 is a consumer-side budget rule, not the store weighting whose only
door is ADR-0072's Consequences, and this ADR does not open that door; §3's refusal
of within-band currency ordering is untouched, because §4 reserves a slot without
ordering anything by currency. **Affirmed; no record owed.**

**ADR-0112 §4 — nothing owed, and it is not narrowed.** Its normative clause says
the ordering is affirmed "unqualified. No recency, currency or staleness
qualification attaches to it". §1 above affirms the same ordering and §2 affirms
the same refusal. §4's floor is none of those three things: it attaches no
qualification to the ordering, it consults no instant, and the ordering it applies
is unchanged. A reader holding only ADR-0112 §4 acts identically on every question
§4 answers. **Addition beside it; no record owed.**

**ADR-0112 §5 — a deferral discharged, not a clause superseded.** Its normative
clause states that the per-band composition "remains owed and unbuilt, and closing
it is not this ADR's and not this lane's", and routes it. The lane it routed to
closed it. Recording that a routed deferral has been taken is what ADR-0112 §11
itself did for ADR-0103 §8 and ADR-0110 §9, by reference to ADR-0045's 2026-08-02
note. §3 above records it and changes no obligation: a reader holding only ADR-0112
§5 looks for the composition, finds it, and owes nothing further. **Discharge; no
record owed.**

**ADR-0112 §7 — nothing owed, and it is applied rather than narrowed.** Its first
clause gates headroom changes on the measurement. §4's third clause routes every
share beyond the floor to exactly that gate, and §4d forecloses the over-request
shape that would be a headroom bet. The floor itself is not a bet on a frequency:
its case is that a band with eligible records should not be absent, which is true
at every frequency and is the same species of claim §7's third clause admits when
it distinguishes a correctness remedy from a headroom one. **Applied; no record
owed.**

**ADR-0113 §5 and §6 — nothing owed.** §5's cross-call deduplication rule is
untouched and §4's floor composes with it unchanged: a record already held is still
skipped, and a band whose only eligible record was deduplicated has no eligible
record left to reserve for. §6 is a routing clause that decides no budget and
assigns the decision to the consumer's lane; this ADR makes that decision for one
of its aspects and leaves the rest — the number of calls, the assembly order, the
donation of a short band's remainder — exactly where §6 put it. A reader holding
only ADR-0113 §6 is told ADR-0113 decides no budget, which stays true. **Deferral
partly discharged; no record owed.**

**ADR-0110 §8 — nothing owed.** Its band-by-band enumeration of what a lapse
warrants is cited in §1 as the asymmetry it states and is neither widened nor
appended to. §4 adds no consequence to a lapse; it adds a floor that is indifferent
to whether a record has lapsed.

**ADR-0128 §1 — nothing owed.** It is cited for what it did and did not do: it moved
every eligibility predicate before the cut and added no threshold. §4 adds no
predicate and no axis, and §5's observation about the selection rests on §1's
silence about a threshold rather than on any obligation of it.

**ADR-0181 §2 and §6 — nothing owed.** §2's disjunction and §6's disclosure line are
described exactly as ruled, and §5 above rules only that a lane may not cite the
run's observation as evidence about band precedence — a statement about what the
observation is evidence *for*, not about what ADR-0181 obliges. Nothing here
changes the fact, its computation, or the line.

**ADR-0183 §3 and §7 — nothing owed.** §3's first clause is cited for the list it
already carries, and §2 above closes a route outside the reader rather than reading
§3 as having closed it; §7's volume argument is used as the input it says it is —
"That strengthens #663's input and does not decide it" — and is decided here, which
is that clause used as written. **Input consumed as offered; no record owed.**

**ADR-0098 §10 — a directed input, taken.** It says the revisit "should weigh it".
This ADR is where it is weighed. Nothing in §10 becomes false and nothing is read
more widely.

**ADR-0092 §3, ADR-0093, ADR-0106, ADR-0140 §7, ADR-0158, ADR-0161 §1, ADR-0073 §1
— nothing owed.** Each is cited as a mechanism or a reason and read no more widely
than it holds; none acquires an exception and none loses one.

## Consequences

- **#663 closes, seventeen days after its questions were last answered and twenty
  days after they were asked.** Both halves have answers on the record
  — one in ADR-0112 §4 and again in §2, one in the tree — and the thing it asked
  for that was still missing is §4's floor.
- **The ordering has now been affirmed against every input the corpus has
  raised against it**: staleness (ADR-0112 §4), adversarial write access
  (ADR-0098 §10, §1 above), and adversary-chosen volume (ADR-0183 §7, §1 above). A
  future proposal to reorder the bands arrives against three refusals rather than
  one, and needs a supersession of §1 rather than a citation of #663.
- **The assembler acquires an obligation and a follow-on lane** (§4, §4d). It is
  small, it needs no contract surface, and it is the first bound the system has on
  what an outsider's supply can do to the composition of a turn.
- **A ratified decision now exists where a docstring was carrying one.**
  `assemble_by_band`'s one-budget policy was the consumer lane's to take under
  ADR-0113 §6 and it was taken well; §4 ratifies its shape and adds the one
  constraint the lane had no input to consider. The next lane that touches the
  budget reads an ADR rather than reconstructing an argument from a comment.
- **The disclosure-noise observation gets an owner** (#1508) instead of living in a
  closed QA issue, and gets it without being mistaken for a retrieval-ordering
  defect (§5).
- **What does not get better.** A turn's context can still be dominated by material
  an outsider chose; §4 bounds the derived band's exclusion and bounds nothing else.
  The supply itself is #1447's, and this ADR deliberately does not let the floor be
  cited as mitigating it (§6).
- **Revisit if** leg 8's memory-precision measure or #789's instrument shows the
  one-record floor to be the wrong size — which is the measured warrant §4's third
  clause is waiting for, in either direction; if a source appears whose report time
  is not adversary-influenceable, which is the only fact that would reopen §2's
  second ground (ADR-0112 §1's grounds would still stand); if #1447 is decided in a
  way that bounds the attested band's size, which would make §4's floor cheaper
  without making it wrong; or if a consumer other than the turn's prompt composes
  by band, since §4 is written for a budget filled once per turn.

## Alternatives considered

- **Reverse the two lower bands — `ASSERTED`, `DERIVED`, `ATTESTED`.** Rejected in
  §1 on three grounds: it asserts that our generalisation outranks a connected
  source's report, which ADR-0072 §2 refused in both directions; it bounds the
  outsider only by the size of a band the system does not control, and returns the
  whole budget to them at cold start; and it promotes the band ADR-0110 §8 leaves
  with no staleness mechanism above the band that now has three, one of them
  observed working under a hostile source.
- **Qualify the ordering by recency — demote an attested record whose report time
  is old.** Rejected in §2. Beyond ADR-0112 §1's standing refusal of a clock acting
  on rank, the field it would rank on is written by the adversary (ADR-0092 §3
  forbids every local substitute, ADR-0183 §1 places the source's bytes in the
  adversary's gift), so the qualification would be a dial the attacker turns and
  would penalise exactly the honest source that has not changed.
- **A per-band proportional share — a third of the budget each, or a fixed
  percentage.** Rejected in §4's third clause. It is a number with no measurement
  behind it, which ADR-0103 §5 and ADR-0112 §7 both refuse in terms, and it
  degrades badly in the ordinary case: on a store holding almost nothing but
  assertions it would return a third of a budget it could have filled, which is the
  failure `assemble_by_band`'s docstring already identifies in its own reasoning
  for one budget.
- **Cap the `ATTESTED` band's take specifically, since it is the outsider's band.**
  Rejected as the same number without the generality. It would need a share to be
  chosen, it would leave the symmetric case — a large asserted band excluding the
  calendar — unfixed, and it would write the adversary into a rule that reads better
  as a property of what precedence means (§4's last paragraph).
- **Leave the budget alone and rely on the inspection surface.** Rejected in §4's
  objection paragraph. It answers the correction affordance and not the
  personalization, and it accepts by supply exactly the outcome ADR-0112 §1 refused
  to reach by clock.
- **Rule the floor as a further deferral, routed to the assembler's lane with a
  trigger.** Rejected. ADR-0113 §6 already routed the budget to that lane, the lane
  took it, and the result is the policy this ADR is examining; routing it a second
  time would be recording a question rather than answering it, and #663's own
  history is the argument against that.
- **Fold #1447's supply bound into this ADR**, since the floor and a retention
  bound answer the same worry. Rejected in §6. #1447 is a `memory/` lifecycle
  decision held for the owner, its shapes are a store's, and ADR-0183 §7 is explicit
  that the reader's threat model may not decide it. The two are separable and each
  holds without the other.
- **Add a relevance threshold to `search` so that irrelevant attested records stop
  reaching the selection.** Rejected as not this ADR's (§8). It is `core` surface
  under golden rule 5, it would change ADR-0181's disclosure as a side effect
  (#1508), and its case — how often a low-relevance record is selected — is a
  frequency, which is ADR-0112 §7's gate.
- **Say nothing, on the ground that ADR-0112 §4 already answered #663.** Rejected in
  the header and the Context. §4 answered the question #663 asked, in #663's terms,
  and does not weigh the input ADR-0098 §10 addressed to the revisit — a fact
  checkable by reading ADR-0112's decision text for the word *outsider*. An
  affirmation that has never met the strongest argument against it is not a closed
  question, and the corpus has since produced two facts (ADR-0183 §7, #1484) that
  bear on it directly.
