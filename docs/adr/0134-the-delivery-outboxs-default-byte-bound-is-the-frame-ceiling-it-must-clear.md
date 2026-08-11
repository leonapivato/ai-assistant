# 134. The delivery outbox's default byte bound is the frame ceiling it must clear

- Status: Accepted
- Date: 2026-08-11
- **Note (2026-08-11, UTC): ratified.** `Proposed` → `Accepted` after the required
  review came back green on the content this ADR merged with — **adversarial
  APPROVE**, adversarial being the whole required set here for the reason the
  header records below. The outcome is taken from the review `just ship` posted to
  PR #968, which carries the round number and the ADR-0020 §2 aggregate; no
  figure from it is restated here, because a count of this change's own lines
  stated inside this change is falsified by stating it (adversarial review caught
  exactly that in an earlier draft of this note). This edit takes
  `CONTRIBUTING.md` → "Trivial ADR edits"' exemption for the ratification flip and
  ADR-0015 §5's trivial-ADR exemption; it records the review's outcome rather than
  replacing it.
- Partially supersedes: ADR-0131 — §5a's Default column for
  `hub_notification_outbox_bytes`, and nothing else. §5a's range for that field
  and its refusal at load are what this ADR defers to rather than what it
  replaces; the field's type and non-nullability, the other four rows of §5a's
  table, both relational validators and §5a's argument for naming its figures at
  all stand untouched, as does every other section of ADR-0131. §4 applies
  ADR-0070 §1's test and states what survives.
- **No `core` surface is decided** — no Protocol in `core/protocols.py`, no type or
  member in `core/types.py`, `PROTOCOL_VERSION` untouched — and **no
  implementation lands with it**: no `src/`, no `tests/`. What it decides is one
  `Settings` default.
- **Its required review set is adversarial alone.** No `core` path is touched, and
  `scripts/ship.sh` fires its architecture requirement on `core/protocols.py` or
  `core/types.py` alone. This is the reading ADR-0082, ADR-0088, ADR-0089,
  ADR-0090 and ADR-0127 each took for a corpus-form decision; `docs/adr/**` being
  in ADR-0027 §3's review floor bears on what a base move costs, not on which lens
  is required.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-11**,
  the durability form ADR-0100 established and ADR-0125, ADR-0126 and ADR-0127
  followed. This decision turns on the exact wording of ADR-0131 §5a, ADR-0070 §1
  and its 2026-07-31 amendment, and ADR-0089 §3 and §5, so a citation meaning
  "whatever it says when you read it" would not be checkable.
- **This ADR is marked under ADR-0089.** Every obligation it imposes is a marked
  clause; unmarked text explains what a marked clause means and supplies no
  obligation of its own.

## Context

### The document refuses the hub it ships

ADR-0131 §5a names five `Settings` figures and makes their ranges normative — "a
value outside a range is refused **at load**". Two of its columns disagree on one
row:

| Field | Type | Default | Range |
| --- | --- | --- | --- |
| `hub_notification_outbox_bytes` | integer | 1 MiB | `>= hub_max_frame_bytes` |

ADR-0084 §3's named default for `hub_max_frame_bytes` is 16 MiB. 1 MiB is below
that, so **a hub with no `.env` at all is refused at load by ADR-0131's own two
figures** — the failure `Settings` validation exists to surface, produced by the
document rather than by an operator, and precisely the "config typo" failure mode
§5a says it exists to prevent, arrived at from the other direction.

No implementation honours both columns. The three moves available to a lane are
each refused by something: ship 1 MiB and every unconfigured hub is dead; ship
16 MiB and the shipped default differs from the ratified figure; make the field
nullable or absent and §5a's non-nullability clause forbids it.

### How it was found, and why an issue and a code comment were not enough

The delivery lane implementing §5a (PR #959, open at this ADR's date) hit this and
resolved it the only loadable way, recording the choice in a code comment, its
commit message, its PR body and issue #965. Architecture review blocked it twice
and was right both times, the second time in terms this ADR exists to answer: "The
shipped default for `hub_notification_outbox_bytes` is 16 MiB, while ratified
ADR-0131 §5a specifies 1 MiB; **a code comment and issue cannot amend an ADR.**
Resolve the contradictory ADR through the decision process, then implement the
ratified default."

### Why this is an ADR and not a dated note on ADR-0131

The first attempt at this correction was an appended dated amendment under
ADR-0070 §1, on the reading that §1 enumerates "an internal contradiction" among
the reconciliations an amendment may perform. Adversarial review blocked that
across four rounds, from three directions, and the objection that survives is the
one §4 below accepts: **§5a decided both columns.** §1's enumeration covers a
contradiction where one side is not itself a decision — a stale phrase, a broken
pointer, a sentence that went out of date — and its own 2026-07-31 amendment keeps
the limit explicit: "Membership in it does not license an in-place edit; the
decision test still runs on the specific correction." Here both sides are decided
figures, so *whichever* gives way, something decided moves. That is a supersession
however narrow the scope, and ADR-0082 §1's rule applies: "**The test controls, not
the label**."

Two further attempts at staying inside the amendment mechanism failed for reasons
worth recording, because each looks workable until it is checked:

- **Reading the correction as unmarked text that merely supplies meaning.**
  ADR-0131 is marked, so under ADR-0089 §5 no mark may be added to it — "No mark
  is added to a ratified ADR, by a dated note or otherwise" — and under ADR-0089
  §3 unmarked text "never supplies an obligation". A dated note is therefore
  either illegal or inert, and there is no third state. (§5a's table is itself
  unmarked, which makes the pincer arguable rather than airtight; but "arguable"
  is not the standard for putting a figure an implementation must obey into text
  the marking rules say does not obligate.)
- **Choosing a formulation that changes no observable figure.** A default keyed to
  ADR-0084 §3's *named* default rather than to the configured field would have
  been a static figure of the same kind §5a's table holds — and it moves the
  number on a configuration where §5a was never contradictory at all, since with
  `hub_max_frame_bytes` at 512 KiB both columns are satisfied by 1 MiB. That is a
  plain decision change with none of the excuse the shipped configuration offers.

So the mechanism is the one ADR-0070 §3 calls "the sanctioned tool when a later
ADR replaces part of an earlier one", at the narrowest scope that fixes the
defect: one cell of one table.

## Decision

### 1. The default is the frame ceiling, floored at the figure §5a named

> **Normative.** `hub_notification_outbox_bytes` defaults to the greater of 1 MiB
> and this hub's `hub_max_frame_bytes` — the configured value, not ADR-0084 §3's
> named default for that field. This replaces ADR-0131 §5a's Default column for
> this field and nothing else in that table.

> **Normative.** ADR-0131 §5a's range for this field is unchanged and is what this
> default satisfies: a value below `hub_max_frame_bytes` is still refused at load,
> whether it came from an operator or from this default.

**Only one column can give way, and it is not the range.** §5a argues the floor at
length and what it protects is a safety property: an outbox smaller than one frame
"could hold no entry a device could receive, and would evict every notification the
instant it arrived — a hub that silently delivers nothing, which is this leg's
whole failure produced by a config typo". Relaxing it would ship exactly the
failure it exists to prevent. The default is the weaker of the two claims — it is
the figure an operator overrides, and §5a's supporting bullet argues the byte
bound's *purpose* ("what stops a few large notifications defeating the count
bound") and its *floor*, never the number 1 MiB itself.

**The 1 MiB survives as the floor of the expression, and that is not a courtesy.**
`hub_max_frame_bytes` is bounded below by ADR-0085 §8d at 1024 bytes, so an
operator may legitimately configure a frame ceiling far below 1 MiB. On such a hub
the smallest value satisfying the range would be a few kilobytes, and §5a's
reasoning for a byte bound at all — that it "stops a few large notifications
defeating the count bound" — argues for the larger figure it named rather than the
smallest legal one. Keeping 1 MiB as the floor means the ratified figure still
governs everywhere it is legal, and the rule departs from §5a only where §5a
cannot be obeyed.

**The rule names the field, not ADR-0084 §3's default for it, and the durability
convention is why that distinction matters.** A default keyed to "ADR-0084 §3's
named default" would be pinned by this ADR's own durability clause to 16 MiB
forever, while reading in plain English as though it tracked a later change to
that ADR — two incompatible readings the day the frame ceiling's default moves,
which is the same species of defect this ADR exists to close. Keyed to the field,
the rule resolves against whatever that hub holds and stays on the legal side of
§5a's range under any later ADR.

**What it costs.** The figure is no longer readable off one setting: an operator
reading `hub_notification_outbox_bytes`'s default has to read
`hub_max_frame_bytes` too. §5a's naming discipline is satisfied all the same,
because the hazard it inherited from ADR-0074 §9.3 is a figure left to a lane's
discretion — "a 'bounded default' with no figure is two conforming stores handing
the same continuation different history" — and two hubs with the same
configuration compute the same number here. Nothing is left to a lane.

### 2. What an implementation may not do with it

> **Normative.** The field stays non-nullable and keeps the type ADR-0131 §5a gives
> it. An implementation resolves the default from the configured frame ceiling; it
> does not expose "unset" as a value a deployment can hold, and `None` remains
> unavailable.

**This is stated because the obvious implementation reaches for a sentinel.** A
computed default has to distinguish "absent" from "set to this number", and the
shapes nearest to hand — a nullable field, or an out-of-range marker like `0` or
`-1` — would each put a value in the settings surface that §5a ruled out when it
said "'off' is not an available value". Filling an absent value before validation
keeps the public field a non-nullable integer and needs no such marker, which is
why the clause constrains the observable surface rather than the mechanism.

### 3. A `hub_max_connections` of 1 is unexpressible on a hub serving delivery, and that is ADR-0131 §5a's decision rather than this one's

ADR-0131 §5a requires `hub_max_delivery_connections` to be `>= 1` and strictly
below `hub_max_connections`, so two connection slots is the minimum for a hub
serving delivery — one for a poller and one for the owner's CLI. That is the
sub-bound's whole purpose; §5a calls the strict inequality "the load-bearing half:
it is what guarantees a slot for the owner's CLI, so a hub saturated with pollers
is still a hub the owner can talk to". A single-slot hub cannot serve delivery and
stay reachable at the same time.

**Nothing here is decided; it is recorded**, because §5a states the bound and never
states the narrowing, and a previously legal deployment stops being expressible.
This ADR replaces no part of that clause and adds no obligation to it — §5a's
marked clause already binds, and this section is unmarked. The narrowing has a
measured cost rather than a theoretical one: in PR #959, the open lane
implementing §5a, two pre-existing cases in `tests/service/test_transport.py` move
from a ceiling of one to two rather than being exempted from the rule, which is
the right way round.

**No supersession record is owed to ADR-0084 §3 for it, and the route to that
answer is ADR-0131 §9's own.** ADR-0084 §3 admits `hub_max_connections >= 1` and is
silent about delivery connections, which did not exist when it was written. §5a
*adds* a relation between its field and a new one, exactly as ADR-0131 §7 adds a
condition to a seam ADR-0124 §4 left open: a reader holding only ADR-0084 "was not
led to act *contrary* to anything; they were led to act incompletely". That is the
stacked-addition category ADR-0083 §15 established and ADR-0084 §12 applied, and
ADR-0084 §3 already carries a relational bound of the same shape
(`hub_max_pending_handshakes` against `hub_max_connections`). Treating it as a
supersession would make every later ADR that constrains an unaddressed corner a
supersession of the ADR that did not address it.

### 4. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in this ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?

**ADR-0131 §5a's Default column for `hub_notification_outbox_bytes` is partially
superseded.** A reader holding only §5a computes 1 MiB; under §1 above they
compute the greater of 1 MiB and the configured frame ceiling. On the
configuration ADR-0131 ships those differ, and an implementation obeying §5a's two
columns together produces a hub that refuses to start where this ADR produces one
that runs. That is ADR-0070 §1's first limb on its face, and the scope is the one
cell: the range beside it is not replaced, it is the clause §1 above defers to.

**The `Accepted` prefix is dropped from ADR-0131's Status line and the record is
its own scope-bearing state.** ADR-0070 §4 makes that load-bearing — "a filter that
prefix-matches `Accepted` cannot silently read a partially-superseded ADR as fully
current" — and the scope names a clause and carries no `ADR-NNNN` token, which is
§4's one authoring constraint on target extraction.

**The record landed with this ADR in the same change, written while it still stood
`Proposed`.** ADR-0070 §1's condition for a Status edit is that the superseding ADR
*exists*, not that it is ratified. ADR-0082 §7 names the contrary reading as "#458 — the recurring
misreading of ADR-0070 §1's 'a supersession that has landed' clause", calls it "not
a governance gap but a reviewer failure mode", and states the condition — "§1's
condition is that the superseding ADR **exists**, not that it is ratified".
`CONTRIBUTING.md` carries the same sentence, and ADR-0131 §9 applied it to
ADR-0084 and ADR-0124 in ADR-0131's own change. So ADR-0131's Status line and a
dated header note carry the record, and not one word of §5a's Decision text is
edited.

**No record is owed to ADR-0084 §3.** Its figures are read here, not moved: §1
above cites its named default only to show what §5a's two columns do to each other,
and the rule §1 states does not reference it. §3 above says why the connection
narrowing owes it nothing either.

**No record is owed to ADR-0089.** §5's prohibition on adding a mark to a ratified
ADR is obeyed rather than narrowed — this ADR adds no mark to ADR-0131, and the
route it takes is the one §5 names in its own text: "A later ADR may restate an
earlier ADR's rule as its own marked clause and partially supersede the earlier one
for that scope."

## Consequences

**What gets easier.** The delivery lane can implement a default that loads. #965
is discharged: a reader holding the corpus computes the same figure the tree
should, and the reasoning for it is in a decision rather than in a code comment.

**What gets harder, and it is a real cost.** ADR-0131 §5a's table is no longer
self-contained — one of its five rows has to be read against this ADR, and a
reader who stops at the table gets a figure that is wrong on the shipped
configuration. ADR-0131's Status line and dated header note are what make that
reachable, and they are the whole mitigation available under an append-only
corpus.

**What is owed next.** `core/config.py` holds no `hub_notification_outbox_bytes`
field on `main` at this ADR's date; the lane that lands it is PR #959, which
resolves §5a's contradiction with a static default equal to ADR-0084 §3's named
frame ceiling. That is correct on every configuration leaving the frame ceiling
alone and short of §1 above exactly where an operator lowers it below 1 MiB.
**#967** carries the difference, against whichever lane lands the field.

**What this does not decide.** Nothing about the other four figures, nothing about
the outbox's count bound, nothing about how the default is expressed in code
beyond §2's constraint on the observable surface, and nothing about
`hub_max_connections`' own range — §3 records a consequence of a clause ADR-0131
already ratified and replaces none of it.
