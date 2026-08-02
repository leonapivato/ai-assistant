# 86. A belief's evidence is bounded, the elision is on the record, and the batch read lands

- Status: Partially superseded by ADR-0091 (§4's clause that two renderings of an elision and a tombstone must both exist)
- Date: 2026-07-31
- **This is a contract change.** §1–§4 bound `Provenance.evidence` and add one
  field to it — a `core` type both `memory` and `planning` construct (ADR-0068
  §2) — and §3 adds an obligation to the `MemoryWriter` conformance suite. §6
  adds `get_many` to the `MemoryStore` Protocol. Golden rule 5 therefore applies:
  this ADR ships as **its own docs-only PR**, is reviewed while still `Proposed`
  so a finding can still change the decision, and is ratified before anything
  implements against it (ADR-0015 §5; `CONTRIBUTING.md`, "Contract ADRs land
  before their implementation"). **No code changes with it.**
- **Records owed on earlier ADRs (ADR-0082 §1), declared here and written
  elsewhere.** §11 names each clause, quotes it, and applies ADR-0070 §1's test.
  Two records are owed — on ADR-0040 and on ADR-0074 — and five commonly-assumed
  others are argued *not* owed, ADR-0085 and ADR-0087 among them. They are
  declared in this text, which is where ADR-0082 §1 says the judgement is made and
  reviewed, and the edits themselves are sequenced into a following change — the
  split ADR-0084 §12 made, deferring its ADR-0077 record "to its own lane (#536)",
  and whose records landed after `ratify ADR-0084`. Each goes in a *different*
  file (`docs/adr/0040-*.md`, `docs/adr/0074-*.md`), so neither could have landed
  in this change's fence in any case.
- **Closes #473.** Its two questions are decided together, in §1–§5 and in §6,
  because each turns on the other: the bound decides whether the batch read is
  buying anything, and the batch read decides how expensive the bound is allowed
  to be.
- **Ratified against a base that moved under it.** ADR-0085, ADR-0087 and #566
  landed while this ADR was `Proposed`. §2 answers #566's element-level validators
  on this very field, §7 re-grounds its arithmetic on ADR-0085 §8c's number and
  ADR-0087 §2b's bytes rather than on ADR-0084 §3, and §7's second gate is closed
  by ADR-0085 §4a — which came out of **#552**, filed from this lane. No decision
  of this ADR moved; what moved is which authority each claim rests on.
- Partially superseded: 2026-08-02 by ADR-0091 — **§4 requires two renderings to
  exist while §4 and §10 both rule that no surface this ADR owns renders either.**
  §4's paragraph on why an elision is not a tombstone closes "The renderings must
  differ, and both must exist, because conflating them would tell the user their
  data was lost when it was not." Two sentences of this ADR say the opposite: §4's
  third surfaces bullet ratifies that the count "does not reach the inspection
  DTOs at all" and that a surface silent about it "is silent about a quantity it
  does not hold, which is a gap in reach, not a false statement"; and §10 puts
  the rendering outside this ADR entirely, "filed as **#568**". Reported as #606
  item 1 and flagged independently by two readers.

  **Replaced**, one clause of §4: the requirement that two renderings exist.
  ADR-0091 §1 rules that nothing is obliged to render `evidence_elided` — that
  stays #568's, as §10 already left it — and keeps the constraint as a
  conditional one: a surface that renders both an ADR-0077 §6 tombstone and an
  elision count renders them so a reader can tell the two apart. The rest of §4
  stands whole: the field, its recurrence over every install, the record-level
  obligation, the floor-plus-ceiling shape of a count that *is* rendered, the
  confidence-neutrality rule, and `export`'s carriage of the stored number.

  **Amended**, four items, recorded here and not rewritten (ADR-0070 §1; the
  record is this note alone, because the `Status` line now carries a leading
  supersession token — ADR-0082 §2). ADR-0091 §2 through §5 apply ADR-0070 §1's
  test to each and none of them moves a decision:

  1. **§2's pointer to §3** (#606 item 2). §2's "it installs the retained subset
     §3 specifies" points at §3 entire, including "**Where there is no fold there
     is no accumulation order** … the retained subset is a suffix of an order that
     carries nothing". §3's heading names the case §3 principally argues; it does
     not bound what §3 rules, and §8 item 3 already pins the non-fold subset in
     the conformance suite as "the retained suffix". The rule for an oversized
     `ACCEPT`, `STORE_TEMPORARY` or `SUPERSEDE` install is unchanged.
  2. **§8 item 6's named symbol** (#586 item 1). The presentation-path migration
     lands at `Engine._resolved_citations`, which both `Engine._project` and
     `Engine._summarise` call. `Engine._project` alone is the single-belief view
     and cannot deliver §6's 3,200-to-50 reduction, which is a claim about the
     listing page. Item 6's own next clause names both ADR-0085 §4a DTOs —
     "**neither** of which can carry `evidence_elided`" — and only
     `Engine._summarise` builds the second, so the sentence's scope was never one
     method. **"That is the whole of what this lane owes there" is untouched and
     still bounds the *rendering*** — its own colon-clause reads "so this lane
     renders no elision and changes no field" — which is why this is an
     amendment: the instruction is spent (PR #582 migrated the right site,
     closing #575), and Consequences' "**The listing's worst case drops from
     3,200 store reads to 50**" already decided the outcome.
  3. **§6's `ConversationService`** (#586 item 2). The class is
     `ConversationLifecycle`, in the module §6 names correctly and under the name
     §8 item 7 uses. Nothing about the two-callers argument or the resume path's
     obligations changes.
  4. **Nothing is owed for §4's elided `description=`** (#606 item 3), and it is
     recorded so a later reader need not re-derive it. The description's content
     is the block quote directly beneath that sketch, ratified and complete, and
     §8 item 1 assigns where it goes; what is absent is a literal `Field` string,
     which no ADR in this corpus fixes for any field. ADR-0091 §5.

  Refs #586, #606, ADR-0091 §1–§5.

## Context

### What #473 found, and the half the review that raised it did not

`Provenance.evidence` carries no `max_length` — it is a `tuple[EncodableText,
...]` since #566, an element-level rule about a string's *wire form* and not a
bound on the tuple — and `FeedbackEvent.evidence` is the same (`Provenance` and
`FeedbackEvent`, `core/types.py`). `MemoryIngestor._merge` **unions** both records'
evidence on every `REINFORCE`:

```python
evidence=tuple(dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence])),
```

(`MemoryIngestor._merge`, `memory/ingest.py`). A belief reinforced repeatedly therefore accumulates
one citation per distinct supporting episode, without bound. Nothing caps it and
nothing prunes it.

That is not a defect in the fold. It is exactly what ADR-0040 §1 says the ruling
means — "the surviving record carries **both** records' `evidence`" — and
exactly the accumulation ADR-0077's observer now makes routine. The growth is
the design working.

### The premise that does not hold

ADR-0077 §6 accepted the resulting read amplification on a stated premise:

> The cost is a `get` per citation per presented belief, bounded by the page
> (ADR-0073 §2's default of 50) and by evidence tuples that are **small by
> construction** (§5's floor is a minimum, not a target). It is accepted for now
> and it gives ADR-0074 §5's declined `get_many` its second consumer — revisited
> with the hub, where a resume already crosses a transport (§11).

"Small by construction" holds **per proposal** and fails **over time**. Per
proposal it is true and enforced: the observer cites at most
`observation_batch_size` episodes (default 20, refused at load outside
`[1, 2**63)`, `Settings.observation_batch_size`, `core/config.py`),
`RuleBasedFeedbackProcessor` copies
`FeedbackEvent.evidence` straight through, and `assistant learn` constructs a
`FeedbackEvent` with no evidence at all. No shipped surface can author a large
tuple in one act. But the union has no such bound, and a belief that is
reinforced is a belief the system is working correctly on.

### Why the deferral expires now

ADR-0084 §4 does not treat this as background. It rules that the size limit is
part of the promoted engine Protocol's declared contract and that *every*
implementation enforces it — so a client is never silently less capable than the
engine it stands in for — and then records the residual honestly:

> a belief whose evidence grew past the limit becomes unreadable through *any*
> implementation, which is a memory-contract problem and not a transport one. So
> #473 is a prerequisite of the client lane, not merely context for it (§11).
> Until its bound lands, §3's ceiling is set so that state is unreachable for any
> belief this system currently produces — the observer cites at most
> `observation_batch_size` episodes, default 20 — rather than *provably*
> unreachable.

**This ADR is what turns "unreachable in practice" into "unreachable by
contract" — for the citation *count*, which is the factor that grows.** §7 states
exactly how far that goes and where it stops, because "unreachable" is a claim
about an arithmetic and the arithmetic has a second factor this ADR does not own.
ADR-0084 §4's prerequisite therefore has two gates. This ADR closes the first;
ADR-0085 §4a closed the second while this one was `Proposed`, out of #552 filed
from this lane (§7).

### The read amplification is contract-mandated, not an implementation choice

Worth stating before §6 decides anything, because it is easy to read the N+1 as
something an implementation could simply stop doing. It cannot. ADR-0073 §4
requires the inspection surface to convey "how many citations stand behind it"
and forbids presenting "a derived belief as carrying a warrant it cannot show";
ADR-0077 §6 discharges that gate by ruling that "the listing resolves *existence*
and renders the count, the lost count, and the adjusted confidence". Rendering a
lost count requires knowing which citations still resolve, which requires reading
each one. `Engine._project` does precisely that, in a sequential loop, for every
record on the page (`Engine._project`, `orchestration/engine.py`).

And each of those reads is not free. `SqliteMemoryStore.get` takes the store's
`asyncio.Lock` and dispatches to a worker thread through `_run_to_completion`
(`SqliteMemoryStore.get`, `memory/sqlite_store.py`), so the cost is a lock
acquisition and a
thread hop per citation — serialised against every other operation on the memory
store. In a one-shot CLI that is invisible. In ADR-0083's resident process,
serving up to `hub_max_connections` clients (ADR-0084 §3, default 64), it is a
single listing holding the memory store's lock several thousand times.

## Decision

### 1. `Provenance.evidence` gains a cardinality bound, and it is a fixed `core` constant

`core/types.py` gains

```python
MAX_EVIDENCE_CITATIONS = 64
```

and no **`MemoryRecord`** this system **installs** carries more than that many
citations in `provenance.evidence` — "install" in ADR-0081 §1's sense, which §2
defines the scope with and which exempts a write that only retires an existing
record.

**`Goal` carries a `Provenance` too, and this bound does not reach it.** The
scope is stated on the record type rather than on the field, because §2 puts
enforcement at the `MemoryWriter` seam and `PlanStore.save_goal` does not cross
it — a caller can persist a `Goal` with 65 citations and nothing here stops it.
That is deliberate on both halves:

- **Nothing accumulates on the goal path.** The bound exists because `REINFORCE`
  unions evidence without limit (Context); there is no fold on a `Goal`, so the
  growth this ADR is about cannot happen there. A bound whose motivating
  mechanism is absent would be a rule imported for symmetry.
- **The goal path already has a ratified owner, and it is not this ADR.**
  ADR-0077 §11 defers "**the evidence obligation on `Goal`** (§7, #432), and any
  enforcement seam on the goal write path" to "the lane that adds an
  inferred-goal producer". No such producer exists, which is why that lane is
  where the seam is decided rather than guessed at here — the same reasoning
  ADR-0072 §3 used to decline a validator until a producer could violate it.

**`FeedbackEvent.evidence` is not bounded either, and it needs no rule of its
own.** An earlier draft said the bound "governs" it; after §2 puts enforcement at
the install that is simply false, and the correction is worth stating rather than
deleting. A `FeedbackEvent` carrying 65 ids is constructible, and
`RuleBasedFeedbackProcessor` copies all 65 into the record it proposes
(`RuleBasedFeedbackProcessor._to_record`, `learning/processor.py`). Nothing there
is stored: the proposal crosses `MemoryWriter`, which installs the retained
subset and records the elision like any other. Adding a second enforcement point
at the feedback boundary would put one rule in two places to drift — the defect
ADR-0077 §5 names when it explains why the emptiness rule lives at the policy and
the resolvability rule at the writer, and not both at each.

**A figure is named rather than left to the implementation**, following ADR-0083
§7 and ADR-0074 §9.3's reason: "a 'bounded default' with no figure is two
conforming stores handing the same continuation different history." A bound with
no number is not a bound.

**Why 64:**

- It is comfortably above `observation_batch_size`'s default of 20 — more than
  three whole batches — so a belief accumulates across several disjoint
  observations before the bound bites. A bound at or near the per-proposal cap
  would make every fold displace, turning reinforcement into churn and
  contradicting ADR-0077 §5's ratified property that confidence is
  "non-decreasing in the number of supporting episodes, **under a ceiling**".
  Accumulation must be real up to the ceiling, or the ceiling is the whole
  behaviour.
- It is small enough that the contract-mandated resolution cost stays legible:
  §6's batch read turns a listing page's worst case from 50 × 64 = 3,200 store
  round trips into 50.
- It is far past what a person reads. §5's floor is "a minimum, not a target",
  and this is the same sentence from the other end: 64 is a ceiling nobody should
  reach, not a quota to fill.

**It is a constant and deliberately not a `Settings` field.** Three reasons, and
the third is decisive:

- A contract bound a deployment can raise is not a bound. #473's exposure is
  unbounded growth; a knob that raises the ceiling is a knob that re-opens it.
- §7's frame arithmetic must be derivable from the contract. ADR-0084 §3 already
  had to solve the two-configurations problem for `hub_max_frame_bytes` by making
  the server's value authoritative and publishing it in the handshake, because
  "a limit that each side configured independently would not be one limit at
  all". A constant has no such problem to solve.
- **`export` crosses deployments and a configured bound would not.** A record
  exported from a deployment at 512 and imported into one at 64 would be a
  record the receiving system's own contract refuses, for a reason the user
  cannot see and did not cause. The bound is a property of the record graph, and
  the record graph is shared (ADR-0068 §2).

### 2. The bound is a writer obligation, not a `Provenance` validator

This is the load-bearing half of §1 and the obvious implementation is wrong.

A `max_length=MAX_EVIDENCE_CITATIONS` on `Provenance.evidence` looks like the
cheapest possible enforcement — one line, mechanical, applied everywhere the type
appears. **It would manufacture, on the read path, exactly the failure this ADR
exists to make unreachable.**

A pydantic validator runs on *deserialisation* as well as on construction.
`SqliteMemoryStore` stores records as JSON and reconstructs them through the
model on every read (`_decode`). A deployment that has been running since
ADR-0077's observer shipped may already hold a belief above 64 — four disjoint
batches of 20 is 80, and nothing has stopped that. On the day the validator
landed, every such belief would stop being reconstructible: `get` would raise
rather than return, `list_beliefs` would fail the page it appeared on, and
`export` — the surface ADR-0007 §3 gives the user for their own data — would
fail with it. "A belief that becomes unreadable through any implementation" is
the sentence ADR-0084 §4 asked this ADR to make false; a type-level bound would
make it true on the read path for the exact records the bound is about.

So:

> **No `MemoryWriter` *installs* a record whose `provenance.evidence` exceeds
> `MAX_EVIDENCE_CITATIONS`.** Where the record it would install does, it installs
> the retained subset §3 specifies and records the count of what it did not, as §4
> specifies. `Provenance` itself admits a longer tuple, and a record already
> stored with one stays readable.
>
> **A write that merely *retires* is not an install and carries the record as it
> stands.** Storing an existing record back with only its validity window narrowed
> (ADR-0080 §1) changes no citation and asserts nothing new about the warrant, so
> it is exempt — a legacy over-bound target is retired intact, not truncated.

**The install/retire line is ADR-0081 §1's, taken as given rather than invented
here.** That ADR already needed exactly this distinction for a different rule and
defined it in `MemoryIngestor._installed_at`: a write *installs* when "it stores
the proposal's content at an id", and *retires* when "it stores an **existing**
record back with only its validity window narrowed (ADR-0080 §1) — the record is
retained, `export` still carries it, and nothing of the proposal lands at its id."
Reusing it costs nothing and keeps one concept from acquiring two definitions.

**Without the exemption the rule would contradict this section's own reasoning.**
`SUPERSEDE` retires its targets through `_close_window`, which preserves
"`valid_from` and every other field" and writes the record back inside the atomic
batch. A universal "no writer stores" rule would therefore be violated by
*retiring* a legacy 80-citation belief — and the only way to satisfy it would be
to truncate a record on its way off the read path, which is the eager rewrite
ADR-0077 §6 refused and which §2 has just spent four paragraphs refusing for the
same reason. A rule that can only be obeyed by breaking the rule above it is
mis-scoped, not strict.

**#566 put element-level validators on this very field, and that is the sharpest
objection to this section — so it is answered rather than left standing.**
`Provenance.evidence` is `tuple[EncodableText, ...]` today: a `core` validator,
added to a shared frozen type, applied to data a running deployment already
holds. If that was safe, why is a `max_length` not?

**Because the two refuse different things, and only one of them refuses a record
that reads today.** `EncodableText` refuses a string with **no wire form at all**
— ADR-0087 §2b: "A string with no UTF-8 encoding has no wire form and the encoder
raises." A record carrying one was already unreadable *through the transport*;
the validator moves an existing failure earlier, to a place that has a name and a
field. It cannot take a record that round-trips today and make it fail tomorrow,
because a value with no encoding never round-tripped.

A cardinality bound is the opposite. A belief with 65 citations encodes
perfectly, transports perfectly, and reads perfectly — it is merely *large*. A
`max_length` would take a record that is readable in every sense and make it
unreadable, which is a strictly new failure invented on the read path. **The test
is not "is it a validator on a `core` type"; it is "does it refuse something that
already worked".** #566 does not; a `max_length` would.

This is the shape ADR-0077 §5 already chose for the closely related
resolvability floor, and for a related reason: "what a deployment's own policy
permits is that deployment's floor to set; what it cannot escape is the
resolvability check, because that one cannot live at the policy at all." Here the
same seam is chosen because the check cannot live on the *type* at all — not
without making the type refuse data it is the only reader of.

**The population converges rather than being migrated.** Every *install*
conforms from the day the implementing lane lands, so an over-long tuple can only
shrink: the next `REINFORCE` on that belief brings it under the bound and records
the elision. A legacy record that is only ever retired keeps its tuple, readable,
in the history `export` carries — which is the right outcome, since retirement is
where a belief stops being asserted rather than where its warrant is restated. No migration, no backfill, no read-path repair, and nothing that
rewrites a record because of something that happened to another one — which
ADR-0077 §6 refused in as many words.

**It applies to every *install*, not only to a fold.** An `ACCEPT` of a proposal
citing more than 64 episodes is bounded by the same rule — it installs the
proposal's content at an id, which is the thing the bound is about. That is unreachable
with `observation_batch_size` at its default, and it is written anyway so the
rule is not one configuration change away from being untrue: the setting's upper
bound is `2**63`, and a deployment that raises it is not thereby permitted to
author an unbounded record.

### 3. What a `REINFORCE` whose union would exceed the bound does

> **The surviving record retains the most recently accumulated
> `MAX_EVIDENCE_CITATIONS` citations of the union, and nothing else about the
> fold changes.**

Concretely, and this is one line of change to `_merge`: form today's union —
`dict.fromkeys([*target.provenance.evidence, *incoming.provenance.evidence])`,
which deduplicates while preserving order — and keep its **last**
`MAX_EVIDENCE_CITATIONS` entries. The oldest are displaced.

**This ratifies the tuple's order as accumulation order.** `Provenance.evidence`
is ordered oldest-accumulated first, which is already precisely what `_merge`
produces and what every store already returns (nothing in `MemoryStore.add`'s
contract licenses reordering a field, and no implementation does). The ADR
promotes it from an implementation property to a stated one, because §3's rule
reads position as age and a rule that reads a property nobody guaranteed is not a
rule.

**Why "most recent" and not "most reinforcing."** #473 offers both. Only one is
available:

- **"Most reinforcing" does not exist to be selected.** The union deduplicates by
  id, so every citation in an evidence tuple has weight exactly one — a second
  observation of the same episode is the same support, which is the rule
  ADR-0077 §5 already states from the input side ("two labels resolving to one
  episode are one support"). Ranking citations by how much they reinforced would
  require a per-citation counter that does not exist and that this ADR would have
  to store — which is more payload, in the field it is trying to bound.
- **Recency is available and is right on merits.** Episodes carry a finite
  retention horizon (ADR-0074 §7) enforced at read time (ADR-0007 §2), so the
  oldest citations are precisely the ones most likely to be tombstones already
  (ADR-0077 §6). Retaining the oldest would fill a bounded tuple with citations
  that no longer resolve and leave "why do you believe that?" unanswerable at
  exactly the moment the bound bit — spending the whole budget on the residue and
  none of it on the warrant.

**Where there is no fold there is no accumulation order**, and the rule
degenerates gracefully: a single proposal above the bound has only the order its
producer wrote, so the retained subset is a suffix of an order that carries
nothing. That is acceptable because §4 records the count either way and because
every citation in a single proposal is equally warranted — and because it is
unreachable at any default configuration.

**`SUPERSEDE` is untouched.** ADR-0040 §5a's asymmetry stands exactly as written:
a `SUPERSEDE` "carries nothing of the target onto the surviving record", so
there is no union to bound and no elision to carry across. The surviving record's
elision count is the proposal's own, which is zero for every producer that
exists.

### 4. The elision is recorded on the record: `Provenance.evidence_elided`

Silent truncation is not available. ADR-0073 §4's floor — "a citation the surface
cannot render as evidence is never rendered *as* evidence — not as a reassuring
id, not silently dropped" — is the rule #473 names as closing this off, and
ADR-0084 §4 relies on it again when it refuses to shorten a payload quietly. A
displaced citation that leaves no trace would make a belief report a narrower
warrant than it has, which is a *false* answer to the one question the provenance
display exists to answer.

So `Provenance` gains one field:

```python
evidence_elided: int = Field(default=0, ge=0, description=...)
```

> **The number of displacements this record's history has performed**, and
> therefore an **upper bound** on the number of distinct citations it no longer
> carries. It is a count and never an id: keeping the ids would defeat the
> bound, since the ids are the payload.
>
> **One recurrence, over every install.** The installed record's
> `evidence_elided` is the **sum of the counts on every record the install draws
> content from, plus the citations this install displaces.** It instantiates
> three ways and no install is outside it:
>
> - a **`REINFORCE`** draws from two — `target.evidence_elided +
>   incoming.evidence_elided + displaced`;
> - an **`ACCEPT`** or **`STORE_TEMPORARY`** draws from one, the proposal —
>   `proposal.evidence_elided + displaced`;
> - a **`SUPERSEDE`** draws from one, also the proposal, because ADR-0040 §5a has
>   it carry nothing of the target across — so the target's count is **not**
>   inherited even though the target's id survives.
>
> Stating it as a sum over sources rather than as three rules is what stops the
> non-fold cases quietly resetting a history: a proposal that already carries
> `evidence_elided=3` and 65 citations installs at `3 + 1`, never at `1`, and
> `export` never understates what a record has displaced.

**It is a bound and not an equality, and that is a decision rather than an
oversight.** Two cases make an exact count unobtainable, and both are reachable:

- **A displaced citation is re-cited.** A record that displaced episode *x*
  counts one elision; a later proposal citing *x* re-admits it to the retained
  tuple, and the record now both carries *x* and counts it as elided. Reachable
  today with no producer doing anything unusual.
- **Two independently elided histories are folded.** Each side counted the same
  displaced episode, and the sum counts it twice.

Making the count exact requires knowing *which* ids were displaced — which is the
payload §1 exists to stop carrying, and it would grow without bound in the field
whose growth is the whole problem. So the count is defined as what can be
recorded honestly. This is the same trade ADR-0077 §6 made when it ruled that the
tombstone "deliberately does not say what it was": where an exact answer costs
the thing the mechanism is for, the mechanism says less rather than saying
something false.

**The corpus now has a second elision marker, and the two agree on the
principle.** ADR-0085 §9 gives `AssistantError` a `details_elided: bool` so "a
client whose reconstruction lost an exception's structured state can say so,
instead of presenting an empty list as an empty answer" — the same rule as §4's,
that an elision is declared rather than silent. The shapes differ for a stated
reason: `details_elided` marks a loss whose size the *client* cannot know, so a
boolean is all that is honest there; this field marks a capacity decision the
*writer* made and can count, up to the collisions above. A flag here would discard
a magnitude the writer holds.

**It is additive with a default**, so a stored record written before this ADR
deserialises with `evidence_elided=0` and nothing migrates. Every `Goal` carries
a `Provenance` too (ADR-0068 §2); its value is always zero — §1 scopes the bound
to `MemoryRecord` installs, so nothing on the goal path ever elides — which is the same
harmless breadth ADR-0077 §7's validator already accepted on that type.

**It is an elision, not a tombstone, and the two are different facts.** ADR-0077
§6's tombstone says an evidence item stood here and *went away* — deleted or
expired, the read cannot tell. An elision says an evidence item stood here and
**we stopped carrying it**: the episode may be perfectly intact. The renderings
must differ, and both must exist, because conflating them would tell the user
their data was lost when it was not.

**What follows for the surfaces**, decided here rather than left to be
discovered:

- **The record carries it, and `export` carries it out.** This is the obligation
  this ADR sets, and it is deliberately set on the *record* rather than on the
  inspection DTOs. `MemoryStore.export` returns `MemoryRecord`s whole (ADR-0007
  §3), so a user's own data as held includes how many citations the bound
  displaced. That is what makes the truncation non-silent, which is all
  ADR-0073 §4 and ADR-0084 §4 require of it.
- **Where a count *is* rendered, the honest shape is a floor plus a ceiling** —
  `len(evidence)` citations shown, and *up to* `evidence_elided` further episodes
  supported this belief and are no longer carried. Reporting only the retained
  tuple's length understates the support; reporting `len(evidence) +
  evidence_elided` as an exact *total* overstates it in the two collision cases
  above. Neither end is available, so the shape is a floor with an explicit
  ceiling.
- **And as the promoted surface stands, that count does not reach the inspection
  DTOs at all — stated rather than assumed away.** ADR-0085 §4a ratified
  `BeliefSummary` with `evidence_count` and `lost_evidence` as fields and `Belief`
  "unchanged … its counts stay derived" from the resolved tuple. Neither type has
  anywhere to put an elision, so a renderer holding either cannot distinguish 64
  citations with nothing displaced from 64 with a thousand displaced. **Whether
  they should grow a field is ADR-0085's to decide, not this ADR's** — the DTOs
  are its contract surface, and reaching into them from here is the widening §7
  already declined once. It is filed as **#568**, and the precedent is good: #552
  was filed from this lane on exactly this boundary and ADR-0085 §4a is the answer
  that came back. Until it is taken, the disclosure lives on the record and in `export`, and
  no surface misreports — it is silent about a quantity it does not hold, which is
  a gap in reach, not a false statement.
- **Presented confidence does not move.** ADR-0077 §6's degradation is a function
  of the stored confidence and how many citations still *resolve*; an elided
  citation is not unresolved, and the belief did not lose support — the record
  lost the reference. Feeding elisions into that function would lower a belief's
  presented confidence because the system worked, which inverts the signal.
- **`export` carries `evidence_elided` as stored**, with the retained ids, for
  ADR-0007 §3's reason that "an export is the user's data as held, not a
  rendering of it" (ADR-0077 §6). An export that showed 64 citations with no
  note that 900 were displaced would misdescribe the record it is exporting. It
  carries the stored number, not a rendering of it, so the bound's imprecision
  travels with the field rather than being resolved in the artifact.
- **`MemoryStore.search` and `list_beliefs` stay confidence-neutral and
  order-neutral.** Nothing here is a ranking input, for the same reason ADR-0077
  §6 gives: "a number computed at presentation cannot reorder a store it never
  touches", and a count on the record must not start doing so either.

### 5. The proposal fingerprint is unaffected, and ADR-0078 §7 is not narrowed

Two questions a reader will reasonably raise, both answered against the text.

**Does `evidence_elided` change `MemoryUpdateProposal.proposal_fingerprint`?**
It joins the projection like any other `provenance` field, and changes no key. The
projection digests `proposal.proposed` — a record that has not yet been written,
let alone folded — so `evidence_elided` is `0` on every proposal any producer in
this system authors, and a constant contributes nothing to a digest. It is
deliberately *not* added to `_FINGERPRINT_EXCLUDED_RECORD_FIELDS`: excluding it
would be a change to ADR-0078 §7's projection bought for no observable
difference, and where a producer does set it, it is a statement about the
warrant being offered and belongs in the digest.

**Does §3's accumulation order contradict ADR-0078 §7's canonicalisation of
`evidence`?** No, and the scope is the answer. §7 rules that "collections that are
*sets in meaning* are sorted and deduplicated" and classifies `evidence` as one,
for a reason it states in terms of proposals: "conflict detection ranks by score,
so two equal-scored gatherings come back in either order; digesting the raw
sequence would mint two keys for one question." That is a rule about the
**fingerprint's projection**, and its justification is about a **proposal**, where
no fold has happened and order carries nothing. §3's order is a property of a
**stored, folded** record. A reader acting on ADR-0078 §7 canonicalises the
projection, and that stays exactly correct after this ADR. No sentence of §7
becomes false and no record is owed against it (§11).

### 6. `MemoryStore.get_many` lands

> ```python
> async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
>     ...
> ```
>
> Returns the readable records among `record_ids`, keyed by id. An id that is
> absent, expired, or not live at now is **simply missing from the mapping** —
> the identical predicate `get` applies, applied id by id with no exception.

**ADR-0074 §5's stated trigger did not fire, and saying so is what makes this
decision honest.** §5 declined the batch read and named where to revisit it:
"the honest place to revisit it is the hub, where a resume crosses a transport."
That condition has not arrived and will not. ADR-0083 §1 makes the hub the
resident process that owns the databases exclusively, so the resume's *k* reads
run *inside* the hub and never touch the socket; ADR-0084 §1 puts one loopback
connection in front of the whole façade, and a `beliefs()` call is one request
frame and one response frame however many store reads it made. The transport
argument is dissolved, not met.

**It lands anyway, on the argument the deferral actually turned on.** ADR-0074 §5
declined it as "a contract change bought for one caller at a scale where it buys
nothing measurable." Both halves have changed, and the scale is now a figure
rather than an intuition:

- **Two callers, both contract-mandated.** Conversation resume fetches *k* turn
  ids (`ConversationService`'s history tail, `orchestration/conversations.py`);
  belief presentation resolves every
  citation of every belief on the page, which ADR-0073 §4 and ADR-0077 §6 make
  obligatory, not optional (Context, above).
- **The scale is 50 × 64.** A listing page is ADR-0073 §2's default of 50
  beliefs, each with up to §1's 64 citations: **3,200** reads for one screen. Each
  is an `asyncio.Lock` acquisition and a worker-thread hop on the shipped store
  (`SqliteMemoryStore.get`). `get_many` makes it 50.
- **`BeliefSummary` did not make this go away, and it is worth saying so.**
  ADR-0085 §4a now has `beliefs()` return a type with no `evidence` field, which
  removes the listing's *payload*. It removes none of its *reads*: §4a says in as
  many words that "this does not change what the listing computes, only what it
  ships", because the adjusted confidence and the lost count are still functions
  of how many citations resolved. So the 50 × 64 figure above is unchanged by the
  one ADR that might have been expected to change it, and ADR-0085 §4a names this
  section's `get_many` as what makes that resolution cheap.
- **The process it runs in changed.** This is the half ADR-0074 §5 could not
  weigh, because ADR-0083 did not exist. A one-shot CLI absorbs 3,200 serialised
  reads; a resident process serving up to 64 concurrent connections holds one
  store's lock 3,200 times while every other request waits behind it. The cost
  stopped being one caller's latency and became a shared resource the hub holds.

**Bounding the tuple is what makes this a decision rather than a guess.** Before
§1, "how expensive is a listing page" had no answer — the citation count was a
function of how long the system had run. After §1 it is at most 3,200 and the
trade is arithmetic. This is why #473 asked for the two together.

**The obligations, which the conformance suite pins:**

- **It never disagrees with `get`.** For every id, `get_many` returns the record
  `get` would return, or omits it exactly where `get` would return `None`. Both
  read-time axes are honoured identically — expired, closed `valid_until`,
  not-yet-open `valid_from`, both ends enforced (ADR-0007, ADR-0045 §6). A second
  read that answered differently about a record's liveness is the failure
  `MemoryStore`'s own docstring already forbids between `search` and
  `list_beliefs`; a third read gets the same rule.
- **One read-time snapshot for the whole batch.** Every id in a call is judged
  against **one instant**: the result is exactly what the store would return for
  those ids at some single point in time, so no two entries can disagree about
  when "now" was. This is a real guarantee and not book-keeping — resolving 64
  citations through 64 `get`s judges them against 64 instants, so a citation can
  expire mid-resolution and a belief's rendered count can disagree with its own
  tombstones. A batch is internally consistent; a loop of singles is not.

  **The guarantee is the snapshot, not any mechanism for obtaining one.** A lock
  plus one clock reading is how the shipped SQLite store will meet it (§8), and
  that is an implementation note there rather than an obligation here: a
  transactional, remote or lock-free store can satisfy the same observable
  property with no lock at all, and a Protocol that named one would put a
  concrete store's synchronisation into a contract every consumer depends on
  (golden rule 1). Stated as a snapshot, the clause is also testable at the
  boundary, which a clause about a private lock is not.
- **A mapping, not a sequence.** The caller's question is *which* ids resolved —
  that is the lost count and the tombstone placement — so a positional result
  would force every caller to re-derive the correspondence. Duplicate ids
  collapse; the mapping never has more entries than the argument has distinct
  ids.
- **An empty argument returns an empty mapping** and requires no round trip.
  Asking for nothing is a question with an answer, in the same words
  `list_beliefs`'s `limit=0` and `write_atomic`'s empty batch already use.
- **Records are detached snapshots**, like every other `MemoryStore` read.
- Cancellation is governed by `core/protocols.py`'s cancellation clause
  (ADR-0060) and the observation of `record_ids` by its input-observation clause
  (ADR-0065), exactly as `write_atomic`'s `Sequence` argument is.

**It carries no size cap of its own, and that is not an unbounded read.**
ADR-0021 §4's concern is a read with no natural bound — one that can ask for
*everything*. `get_many` cannot: every record it returns had to be named, so its
result is bounded by an argument the caller enumerated. Adding a ceiling would
mean picking a number that both shipped callers' own bounds must stay under,
which couples `MAX_EVIDENCE_CITATIONS` and the conversation history tail to a
third figure and creates a load-time-undetectable conflict the day either moves.
A backend with a per-statement limit of its own — SQLite's bound-parameter cap is
the one in hand — meets this by chunking behind the single snapshot §8 requires,
not by refusing: an implementation limit is not a contract limit, and this
Protocol does not let one become one.

**It does not replace `get`.** A single read stays a single read; a caller with
one id does not build a one-element sequence to unwrap a one-element mapping.

### 7. Coherence with ADR-0084 §3's frame ceiling — checked, and where it stops

The brief asks whether §1's bound and ADR-0084 §3's frame ceiling are coherent,
"a bound that still permits an unframeable belief has not closed the gap." The
honest answer has two parts.

**What is now closed.** ADR-0084 §4's residual is a belief that "grew past the
limit". After §1 no belief grows past anything: the citation *count* is capped at
64 regardless of how long the system runs or how often a belief is reinforced. The
state ADR-0084 §4 could only call "unreachable for any belief this system
currently produces" is now unreachable for any belief any conforming writer can
ever produce, which is what the section asked for. **Accumulation is no longer a
path to an unreadable belief.**

**The other factor, and where the arithmetic now stands.** A frame carries
*rendered* evidence, not ids: `Evidence.content` is the cited episode's own text
(`Evidence.content`, `orchestration/engine.py`), and no contract bounds an
episode's content. So the payload is `beliefs × citations × content`, and §1
bounds the middle factor only.

**Both the number and the bytes are ratified now, which makes this exact rather
than approximate.** An earlier draft worked against "ADR-0084 §3's 16 MiB
default", which was the wrong authority on both halves:

- **The number is ADR-0085 §8c's**: the contract limit is `hub_max_frame_bytes -
  512`, applied to the **whole payload** rather than to any one value, on
  arguments, results and errors alike. ADR-0084 §3's `hub_max_frame_bytes` is the
  setting the reserve is subtracted from, not the limit itself.
- **The bytes are ADR-0087's**, which replaced ADR-0084 §3's "serialised through
  pydantic's JSON mode" outright. §2b pins them: UTF-8 unescaped wherever JSON
  permits, `/` unescaped, nothing at or above U+007F escaped, and only the
  two-character escapes plus `\u00XX` below U+0020. A citation's byte cost is
  therefore a *computable* function of its text rather than an estimate — which is
  what makes the check below decidable at all.

| Response | Citation contents in one payload |
| --- | --- |
| `belief()` — one belief | ≤ 64 (§1) |
| `beliefs()` — `BeliefSummary` (ADR-0085 §4a) | **zero — no field to hold one** |

**No per-citation budget is quoted, and an earlier draft was wrong to quote one.**
Dividing `hub_max_frame_bytes - 512` by 64 looks like a threshold and is not one:
§8c bounds the **whole payload**, so the same frame also carries the `Belief`'s
own fields, each `Evidence` object's braces and member name, and the array's
commas and brackets. A belief whose 64 contents sum to just under the limit is
still refused, because the structure around them has not been counted. The
divided figure is an upper bound that is never attained, and quoting it as a
budget would misstate ADR-0085 §8c's rule in the one place this ADR leans on it.

**So the coherence statement, as strongly as it can honestly be put:** the
largest evidence payload any frame can carry is **one belief's citations**, that
count is **fixed at 64 and no longer a function of time**, and whether a given
belief fits is decided by ADR-0085 §8c against the whole encoded payload — a
question about the size of some episodes, answerable by measurement, and not a
question about how long the assistant has been running. That last clause is the
whole of what §1 buys here.

**ADR-0084 §4's prerequisite had two gates, and both are now closed — one by
each of two ADRs that do not depend on each other.** An earlier draft of this
section left the second open and handed it to the surface ADR; that lane took it,
and the hand-off is recorded from both sides.

1. **Growth — closed here.** No belief's citation count can exceed 64, whatever
   the system does or how long it runs. §1 through §4.
2. **The page multiplier — closed by ADR-0085 §4a**, which came out of #552,
   filed from this lane. `beliefs()` returns `BeliefSummary`, which carries
   `evidence_count` and `lost_evidence` as fields and **has no `evidence` field at
   all**, so a listing has nowhere to put a citation's content. §4a's own reason
   is the better one: the over-delivery is now *unrepresentable* rather than
   merely forbidden, where ADR-0073 §4 and ADR-0077 §6 had only forbidden it.

**Neither ADR leans on the other**, and ADR-0085 §8f says so from its side —
"each removes one factor of the same product". That independence is what makes the
pair sound: this ADR was ratified after ADR-0085 and could have leaned on it;
ADR-0085 was written while this one was `Proposed` and correctly refused to lean
on an unratified ADR. Both stand alone.

**What that does *not* mean, and the over-claim is worth refusing explicitly:
`content` is still unbounded, and the two gates do not add up to a bounded
payload.** Of the product `beliefs × citations × content`, ADR-0085 §4a removed
the first factor and §1 bounds the second. **The third has no contract bound and
this ADR does not give it one.** A belief citing a single 20 MiB episode carries
one citation, satisfies §1 with 63 to spare, and still produces a `Belief` that
ADR-0085 §8c refuses. Nothing in §1 constrains an episode's size, and §7 quotes
no figure that could be mistaken for such a constraint.

**What is eliminated is *growth*, which is the whole of what #473 and ADR-0084 §4
asked for.** The failure mode they name is a belief that becomes unreadable
because the system worked correctly on it for long enough; that is now impossible,
because the only factor that grew with time is capped. A belief that is oversized
because one cited episode is enormous is a different fact: it is not monotone in
time, it does not arrive by accumulation, and it already has a declared answer —
ADR-0085 §8e's `OversizedValueError` naming `Belief.evidence`, "a sentence a user
can read and act on". That residual is retained here, not closed.

### 8. What the implementing lane owes

The triad and its consumers, in the order golden rule 5 fixes.

1. **`core/types.py`** — `MAX_EVIDENCE_CITATIONS`; `Provenance.evidence_elided`
   with its `ge=0` bound and a docstring stating §4's elision-is-not-a-tombstone
   distinction. No `max_length` on either evidence field (§2).
2. **`core/protocols.py`** — `MemoryStore.get_many`, with §6's obligations in its
   docstring, and `MemoryWriter`'s docstring carrying §2's bound as a stated
   obligation.
3. **The shared conformance suites and the canonical fakes**, in the same change
   (`CONTRIBUTING.md`, "Adding a Protocol"):
   - `MemoryStore`: `get_many` never disagrees with `get` on any id, on all three
     read-time outcomes; duplicates collapse; an empty argument returns an empty
     mapping; a missing id is an omission and not an error; **the batch is one
     snapshot** — of the clock *and* of the stored state — tested only through
     what the Protocol exposes: a controlled clock, and results that never
     disagree with a `get` taken at the same instant. **The shared suite stops
     there, deliberately.** A conforming store may answer in one remote request,
     one statement or one in-memory snapshot, so it has no per-chunk boundary a
     portable test could inject a mutation at, and a suite that raced a writer
     against an in-flight call would be nondeterministic where it was not simply
     testing SQLite. Demanding that boundary would also make one store's chunking
     a universal obligation — the mechanism §6 says the contract is *not*. **And it observes
     `record_ids` before its first await** — the ADR-0065 clause §6 binds it to,
     which needs its own suspended-call case because none of the clauses above
     mutates the sequence mid-call and an implementation that took its lock first
     and materialised the argument afterwards would pass every one of them while
     answering a later version of the caller's input. This is the case
     `write_atomic`'s `Sequence` argument already carries; a second `Sequence`
     argument on the same Protocol gets it too, or the clause is declared and
     unenforced.
   - `MemoryWriter`: no **installed** record exceeds `MAX_EVIDENCE_CITATIONS`,
     **and a retirement write is exempt** — a `SUPERSEDE` whose *target* is a
     legacy over-bound record retires it with its tuple and its
     `evidence_elided` untouched, which is a distinct case from the oversized
     *proposal* below and is reachable on any store that predates this ADR; a
     `REINFORCE` whose union would exceed it retains the **last**
     `MAX_EVIDENCE_CITATIONS` of the deduplicated union and increments
     `evidence_elided` by exactly the number displaced; a `REINFORCE` whose union
     **fits** retains both records' evidence unchanged and still applies §4's
     recurrence with **zero** displacement — so it stores
     `target.evidence_elided + incoming.evidence_elided`, which is not the
     target's value whenever the incoming record carries one of its own; a
     `SUPERSEDE` carries neither the target's evidence nor its elision count. **Both collision cases §4 names are exercised** — folding two records
     that each already elided the same episode, and re-citing an episode a record
     previously displaced — pinning the recurrence as stated, so the suite
     asserts the count it defines rather than an exactness the field does not
     claim. **And the bound is exercised on the rulings that are not folds**:
     §2 applies it to *every* install, so an oversized `ACCEPT`,
     `STORE_TEMPORARY` and `SUPERSEDE` proposal each assert the retained suffix
     **and** §4's recurrence in its one-source form — `proposal.evidence_elided
     + displaced`, exercised with a proposal whose count is already **non-zero**,
     since a writer that stored the displacement alone would pass every
     zero-valued case while discarding a history `export` is supposed to carry.
     A writer that truncated these without incrementing at all would satisfy "no
     installed record exceeds the bound" and every `REINFORCE` clause above while
     silently dropping provenance, which is the one outcome §4 exists to prevent.
     For `SUPERSEDE` the case asserts both halves of §3's ruling: the proposal's
     own count is carried, and the *target's* is not inherited.
   - `FakeMemoryStore` and `FakeMemoryWriter` grow the behaviour, not a stub.
4. **`memory/ingest.py`** — `_merge` truncates before constructing `Provenance`,
   so the constructor's validators still run on the value that is stored
   (ADR-0026 §2's hazard: the surrounding `model_copy(update=...)` skips them).
5. **`memory/sqlite_store.py`** — `get_many` under **one lock acquisition, one
   clock reading, and one read transaction**, not a loop over `_get_sync`. That
   is this store's way of meeting §6's snapshot guarantee, not the guarantee
   itself; a loop of singles would pass a clock-consistency test and buy none of
   the thing the method exists for. It is equally **not a single SQL statement**:
   SQLite caps bound parameters per statement (`SQLITE_MAX_VARIABLE_NUMBER`,
   32,766 on current builds and 999 on older ones), so an `IN` clause must be
   chunked to that limit — inside the one lock, against the one clock reading, so
   the chunking is invisible in the result. Mandating one statement would put a
   caller-reachable "too many SQL variables" failure inside a method §6 promises
   never refuses on size.

   **The read transaction is what makes chunking safe, and the `asyncio.Lock` is
   not.** The lock serialises coroutines on *this* store instance; it does nothing
   about the file. This module's own header is explicit that the discipline which
   makes a sequence atomic "against a second *process* on the same file" is the
   transaction, not the lock — which is why #562 gave every mutation a
   `BEGIN IMMEDIATE`. Chunked without one, `get_many` reads chunk 1, another
   process retires `a` and installs `b`, chunk 2 reads `b`, and the result pairs
   an old `a` with a new `b` — two values that never coexisted. That is §6's
   snapshot violated by the very mechanism introduced to satisfy its no-size-cap
   promise. ADR-0083 §12 notes exclusivity makes a second writer absent in the
   reference deployment and names its relaxation as the condition that makes this
   urgent again; the transaction costs nothing and does not depend on that
   holding.

   **The interleaving test belongs here too, not in the shared suite.** Only this
   store has chunks to interleave between, and `tests/memory/test_sqlite_store.py`
   already constructs the second-process case deliberately for #562's forked
   cases — so the test is written where both the chunk boundary and the writer can
   be controlled, and it is deterministic. The shared suite tests the observable
   snapshot and stops (item 3).
6. **The presentation path** — `Engine._project` calls `get_many` once per belief
   instead of `get` per citation. **That is the whole of what this lane owes
   there**, and the limit is deliberate: `Engine._project` builds the DTOs
   ADR-0085 §4a ratified, neither of which can carry `evidence_elided` (§4), so
   this lane renders no elision and changes no field. It resolves the same
   citations against the same predicate and answers in one call instead of *n*.
   Whether the DTOs grow a field is **#568**, and this obligation is written so
   that a lane taking it cannot mistake a rendering it has nowhere to put for
   work it was assigned. The listing's payload — §7's other factor — needs
   nothing here at all: ADR-0085 §4a settled it, and **#552** with it.
7. **The conversation resume path** — `ConversationLifecycle.history()`
   (`orchestration/conversations.py`) takes `get_many` too. It is the *other*
   consumer §6 counts, and leaving it on `await self._memory.get(turn.episode_id)`
   once per turn would land an ADR that cites two callers and converts one. Two
   behaviours it must preserve exactly, because a mapping loses both and the loop
   has them for ratified reasons: **turn order**, which is the conversation's
   ordinal sequence and not the mapping's, so the batch is read back by iterating
   `turns` and looking each id up; and **skip-not-fail** for an id that does not
   resolve, which ADR-0074 §5 ratified as "skipped, not an error — whether it was
   deleted, expired, or is an intent whose episode write never landed". The tests
   pin both against the current loop's behaviour, and the store's own docstring
   (`conversations.py`, the `get_many` note §6 supersedes) is corrected with it.

### 9. Explicitly declined

- **A `max_length` on `Provenance.evidence`.** §2 — it would make an
  already-stored over-long belief unreadable on the read path, which is the
  failure this ADR exists to prevent.
- **A `Settings` field for the bound.** §1 — a bound a deployment can raise is
  not a bound, and `export` crosses deployments.
- **Refusing the fold when the union would exceed the bound.** A `REINFORCE` is
  a legitimate, correct act; turning it into a `MemoryStoreError` would make
  accumulation fail for the beliefs the system knows most about, and the
  observation stage propagates every writer refusal but
  `UnresolvedEvidenceError` (ADR-0077 §5), so one heavily-reinforced belief would
  abort a batch that was working.
- **Storing the displaced ids anywhere.** A side table of elided citations is the
  reverse index ADR-0077 §6 already refused, re-created to hold the payload §1
  exists to stop carrying.
- **Feeding elisions into ADR-0077 §6's presented-confidence degradation.** §4 —
  it would lower a belief's presented confidence because the system worked.
- **A per-citation reinforcement counter**, which "retain the most reinforcing"
  would need. §3 — it does not exist, and inventing it is more payload in the
  field being bounded.
- **A size cap on `get_many`'s argument.** §6 — it is bounded by an enumerated
  argument, and a third figure would couple two unrelated bounds.
- **Bounding `observation_batch_size` by `MAX_EVIDENCE_CITATIONS`.** Unnecessary
  once §2 puts the bound at the writer: a large batch yields a large proposal,
  which the writer bounds and counts like any other. ADR-0077 §1's stated range
  is untouched, and no record is owed against it (§11).

### 10. What this ADR does not decide

- **How a listing conveys citation counts without carrying citations.** Filed
  from this lane as **#552** and **decided elsewhere**: ADR-0085 §4a gives
  `beliefs()` its own return type, `BeliefSummary`, with `evidence_count` and
  `lost_evidence` as fields and no `evidence` field at all. Recorded here because
  §7's arithmetic depends on it and a reader should not have to rediscover which
  ADR closed which factor.
- **Whether the inspection DTOs grow a field for the elision**, and its
  rendering. §4, filed as **#568**. `Belief` and `BeliefSummary` are ADR-0085's
  contract surface and neither can carry the count today; the disclosure lives on
  the record and in `export` until that lane rules. §4 fixes what would be
  conveyed — the showable count, the ceiling on what is not, and that the
  difference is capacity rather than loss
  — and leaves the words to the surface, exactly as ADR-0077 §6 left the
  tombstone's.
- **Any bound or elision on `Goal.provenance.evidence`, or an enforcement seam
  on the goal write path.** §1. ADR-0077 §11 already owns it and assigns it to the
  lane that adds an inferred-goal producer; none exists, and this ADR does not
  pre-empt that lane by bounding a field on a path with no accumulation on it.
- **Whether an evidence tuple should be *pruned* by relevance or age rather than
  displaced by arrival.** That is consolidation, and consolidation is leg 7
  (ADR-0072 §10, ADR-0077 §11, unchanged). §3 decides only what the fold does at
  the boundary.
- **Anything about `hub_max_frame_bytes`' lower bound.** ADR-0084 §3 defers the
  exact floor to the surface ADR, "which is the change that knows it". §7 hands
  that ADR one input and decides nothing for it.
- **A batch *write* keyed by id.** `write_atomic` already exists (ADR-0046) and
  nothing here touches it.
- **Whether `Provenance` should record *which* connected source attested a
  belief** — ADR-0073 §4's other open gate, on leg 6's first `EXTERNAL` producer.
  Untouched: this ADR adds one field for a different reason and does not open the
  type to that lane's question.

### 11. Records owed on earlier ADRs, under ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this ADR's text, clause by
clause, against ADR-0070 §1's test: *would a reader holding only the earlier ADR
now act differently, or read one of its clauses more widely than it now holds?*

**Owed — ADR-0040 §1 and §5a.** §5a's ratified obligation reads:

> **`REINFORCE` retains both records' `evidence`.** Everything else about the
> fold — which content wins, how confidence combines, `last_updated` — is
> unasserted.

and §1 states the same in the member's definition: "The applier folds the two,
and the surviving record carries **both** records' `evidence`." §3 above makes
both false at the boundary — a conforming writer now retains both records'
evidence *up to `MAX_EVIDENCE_CITATIONS`*, and displaces the oldest beyond it. A
reader holding only ADR-0040 would build a writer that fails the widened
conformance suite. This is a change to what was decided, so under ADR-0070 §1 it
is a **partial supersession** of ADR-0040 §1 and §5a, in the shape ADR-0084 §5
used for ADR-0042 §1. Everything else in §5a is untouched, and the asymmetry it
insists on survives intact: `SUPERSEDE` still carries nothing across (§3).

**Owed — ADR-0074 §5 and its §10 entry.** §5 reads: "**A batch read on
`MemoryStore` is declined.** Fetching *k* episodes is *k* calls to `get`. A
`get_many` would be a contract change bought for one caller at a scale where it
buys nothing measurable, and the honest place to revisit it is the hub, where a
resume crosses a transport." §10 repeats it in the declined list. §6 above lands
the method, so both sentences become false and a reader holding only ADR-0074
would believe the contract has no batch read. A **partial supersession** of
ADR-0074 §5 and its §10 entry, again following ADR-0042/ADR-0084. Note that §6
does *not* claim §5's stated trigger fired — it did not, and §6 says so — which
is why this is a supersession of the decision and not a deferral being collected.

**Not owed — ADR-0077 §6.** Its sentence "evidence tuples that are **small by
construction**" is a *premise of a cost estimate*, and #473 shows it was already
false when written; §1 makes it true. Nothing §6 decided — lazy resolution, the
tombstone, no rewrite, the confidence split — changes, and a reader acting on §6
acts identically. §6 also scheduled the `get_many` revisit "with the hub", and
§6 above performs it: performing a revisit an earlier ADR asked for is a stacked
addition to *that* ADR, which is the treatment ADR-0082 §1 classifies as correct
on `main` for ADR-0072 §3 → ADR-0077 §7. The supersession is owed to ADR-0074,
which held the *decision*, not to ADR-0077, which held the *schedule*.

**Not owed — ADR-0078 §7.** Argued in §5 above: its canonicalisation rule and its
justification are both scoped to the fingerprint's projection over a *proposal*,
and both stay exactly correct.

**Not owed — ADR-0077 §1, ADR-0077 §5, ADR-0068, ADR-0073 §4, ADR-0084 §3/§4.**
`observation_batch_size`'s range is untouched (§9). §5's floors are minima and
this is a maximum; the two cannot conflict, since 64 is above every floor §5
sets. ADR-0068 froze the graph and did not close it, and §4's field is additive.
ADR-0073 §4's floor is *satisfied* here, not narrowed — §4 above is what keeps
the drop from being silent. ADR-0084 §4 named this ADR as its prerequisite and §7
above discharges the memory-contract half of it; §3's ceiling and its settings are
untouched, and §3's encoding clause was replaced by ADR-0087 before this ADR was
ratified, which this ADR reads rather than moves.

**Not owed — ADR-0085, and it is recorded from both sides.** ADR-0085 §12 already
rules "no record, and no dependency in either direction" against this ADR, and the
test comes out the same way from here. Two clauses are worth naming because they
look like candidates:

- **§8e — "`evidence` carries no `max_length`."** This ADR does not add one; §2
  declines it, and for a reason §8e would recognise. The sentence stays true.
- **§8e — "until its bound lands the bad state is unreachable rather than
  provably unreachable."** A conditional the earlier ADR wrote in anticipation of
  this one, discharged by the ADR it was anticipating. That is a stacked addition,
  the same treatment ADR-0082 §1 blesses on `main` for ADR-0072 §3 → ADR-0077 §7.

**Not owed — ADR-0087.** This ADR cites it for what the bytes are (§7) and takes
no position on them. Nothing about a cardinality bound bears on an encoding, and
ADR-0087 §2b's rules are used exactly as written.

**The edits themselves are sequenced into their own change, and this is the
corpus's own practice rather than a convenience.** ADR-0084 §12 made exactly this
split days ago: it declared every record it owed, wrote one of them in its own
change, and **deferred the rest** — its ADR-0077 record explicitly "to its own
lane (#536)". The records on ADR-0077 §10, ADR-0052 §3, ADR-0022 §2 and ADR-0074
§9 all landed in separate commits *after* `docs(adr): ratify ADR-0084`. Declaring
in the text and writing in a following change is a ratified, exercised shape.

**Two reasons it is the right one here.** ADR-0070 §1 permits "recording a
supersession **that has landed**", and a `Proposed` ADR's decision has not: this
ADR is reviewed while `Proposed` precisely "so a finding can still change the
decision" (ADR-0015 §5), and this review already changed §4, §6 and §7. A
`Partially superseded by ADR-0086` line written now would assert on two live
ADRs' `Status` lines that they had been superseded by a decision not yet made,
and would have to be revised or withdrawn if a later round moved §3's fold rule
or §6's ruling. And two lanes are writing under `docs/adr/` this wave, so the
edits need ordering that this lane does not own.

**What is *not* being deferred is the judgement.** ADR-0082 §1 puts the
substantive work in the later ADR's text — "the author names the clause and
applies §1's test to it; a reviewer checks that showing against the quoted
clause" — and it is all above, quoted and argued, where this review can reach it.
The following change transcribes a decision made here; it is not where the scope
is chosen, and it is emphatically **not** the `Proposed` → `Accepted` flip, which
ADR-0070 §1 permits only as an edit that "finalises the current decision rather
than changing a past one" and which must stay trivial for exactly that reason.

## Consequences

- **The unreadable-by-accumulation belief becomes unreachable by contract.** A
  belief's citation count can no longer grow, at all, however long the system
  runs.
- **ADR-0084 §4's prerequisite — a belief made unreadable by *growth* — is
  discharged, by this ADR and ADR-0085 §4a together.** Its second gate, a
  `beliefs()` page carrying the content of every citation of every belief on it,
  closed when ADR-0085 §4a gave the listing `BeliefSummary`, out of **#552** filed
  from this lane. Neither ADR leans on the other (ADR-0085 §8f); each removed one
  factor of `beliefs × citations × content`.
- **`content` stays unbounded, and the residual is retained rather than closed.**
  One enormous cited episode still produces an oversized result, refused by
  ADR-0085 §8c as §8e's `OversizedValueError`. That failure is not reached by
  accumulation and is not what #473 was about, but a reader should not take §7 for
  a proof that every `Belief` fits.
- **A belief's warrant stops being a function of how long the system has run.**
  Sixty-four citations is what any belief can show, and the count of what it
  cannot show is on the record.
- **The listing's worst case drops from 3,200 store reads to 50**, and stops
  holding a resident process's memory-store lock several thousand times per
  screen.
- **`Provenance` grows a field**, which every `MemoryRecord` and every `Goal`
  carries and `export` serialises. Additive with a default; nothing migrates.
- **`MemoryStore` grows a method**, so every implementation and every fake grows
  with it. There is one real store and one canonical fake.
- **Two partial supersessions are owed** (§11) and are sequenced behind
  ratification.
- **A residue is accepted and named:** a deployment that has already accumulated
  a belief above 64 keeps it, readable, until its next reinforcement brings it
  under the bound. That is the price of §2's refusal to make a stored record
  unreadable, and it is the right price — the alternative fails the read for
  exactly the beliefs the system knows most about.

## Alternatives considered

- **Bound the type with `max_length` and migrate.** Rejected in §2. Beyond the
  read-path hazard, a migration that rewrites beliefs because of a contract
  change is precisely the "edit a belief because of something that happened to
  another record" that ADR-0077 §6 refused, and it would run inside a store the
  user may hold thousands of records in.
- **Make the bound configurable.** Rejected in §1. It re-opens the exposure by
  configuration, and it makes `export` deployment-dependent.
- **Paginate the citations instead of bounding them** — a `Belief` carrying a
  page of evidence with a continuation. Genuinely arguable, and it is the shape
  ADR-0073 §2 uses elsewhere. Rejected because it answers the *transport*
  question and leaves the *semantic* one open: a belief with 40,000 citations is
  not a belief with a paging problem, it is a belief whose warrant nobody can
  read. #473 asks for the semantic bound, and ADR-0084 §4 asks for a type that is
  "sensible", not a type that is merely deliverable in slices. Paging would also
  add a continuation to a `core` DTO whose whole point (ADR-0084 §4) is that it
  is small and frozen.
- **Retain the oldest citations rather than the newest.** Rejected in §3 — it
  spends the bounded budget on the citations most likely to have expired.
- **Retain a sample across the history** (first *n*, last *n*). Rejected: it is
  two rules where one will do, it has no epistemic justification either half of
  recency lacks, and the elision count already tells the user what the retained
  set omits.
- **Land the bound and defer `get_many` again.** Rejected. The bound is what
  makes the cost a figure rather than an unknown, and deferring the batch read
  with the figure in hand would be deferring a decision that is now fully
  determined — with a third revisit trigger that, on ADR-0074 §5's record, would
  again name a condition that does not fire.
- **Land `get_many` and defer the bound.** Rejected outright. It converts a
  round-trip problem into a payload problem, which is #473's own framing, and
  ADR-0084 §4 is explicit that a bounded transport and an unbounded contract are
  reconcilable only by a contract-visible failure. Making the failure cheaper to
  reach is not closing it.
