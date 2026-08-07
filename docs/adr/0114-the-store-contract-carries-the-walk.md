# 114. The store contract carries the walk: a chunk in insertion order, and a named cursor that never leads its effects

- Status: Proposed
- Date: 2026-08-06
- **Durability clause.** Every reference below to ADR-NNNN is to its text as
  merged on 2026-08-06, not to its status on any later day. Where a later ADR
  changes one of them, this ADR is read against the text quoted here and the
  later ADR's own record says what moved.
- **This is the contract ADR-0111 §1 needs and did not know it needed.** ADR-0111
  placed a scheduled walk's cursor "in the store whose progress it records" and
  classified itself as touching no Protocol. That classification holds of
  ADR-0111's own diff and fails of the walk it decided: the component that
  selects a consolidation's inputs sits in `orchestration` (ADR-0106 §3, §6), and
  it reaches `memory` only through the `MemoryStore` Protocol. So the chunk read
  and the cursor advance cross a contract surface, and golden rule 5 applies after
  all. This ADR decides that surface and nothing else.
- **Surface.** This ADR decides **two methods** on the `MemoryStore` Protocol in
  `core/protocols.py` and **two types** in `core/types.py`. Golden rule 5 is
  therefore triggered: this ADR is ratified and merged as its own PR before
  anything implements against it (ADR-0015 §5), and the triad — the Protocol
  change, the extended `MemoryStoreContract`, and the canonical fake — lands
  together in the implementation lane behind it.
- **No implementation lands with it.** No `src/`, no `tests/`. The consolidation
  lane, the scheduler job, and every `Settings` field ADR-0111 §4 names are an
  implementation lane's act against this text once ratified, never this ADR's.
- **This ADR partially supersedes ADR-0111, in one narrow scope**: the Surface
  bullet's classification that this decision's cursor needs no Protocol surface.
  **Every ruling of ADR-0111 §§1–9 stays accepted and this ADR is built on them.**
  §10 applies ADR-0082 §1's and ADR-0070 §1's tests separately, states the scope and
  why it is drawn where it is, and states what is *not* owed elsewhere. Refs #632,
  #729, #785.

## Context

### The gap is not in ADR-0111's reasoning; it is in where the walk turned out to live

ADR-0111 decided how a scheduled job walks and resumes, and every ruling it made
stands. Its §1 sites the cursor in the walked store and gives the decisive reason
— only the component holding the store's connection can write the cursor in the
chunk's own transaction, which is ADR-0104 §2's guarantee. Its §2 fixes what a
cursor may be. Its §3 fixes the direction a cursor may lag. Its §7 fixes what a
build does with a cursor it cannot read. None of that is reopened here.

What ADR-0111 did not have in front of it was the *shape of the walker*. Its
Surface bullet says the cursor's mechanics "live in `service/` and, for the
cursor, below each subsystem's own façade", and on that reading a cursor is
private to `SqliteMemoryStore` and costs no contract. Two ratified clauses put the
walker somewhere else:

- **ADR-0106 §6** requires that "a consolidator reaches the store through the
  orchestration write stage, never through `MemoryWriter.ingest` directly", and
  the write stage is `orchestration`'s.
- **ADR-0106 §3** puts the taint computation on "the component that **selected the
  input set**", as the disjunction of `rests_on_recorded_external_content` over
  those inputs. Selection is therefore a step that holds the records, and it holds
  them where the write stage is.

So the chunk is read by a stage in `orchestration`, which under golden rule 1
knows `memory` only as the `MemoryStore` Protocol. A cursor "below the subsystem's
own façade" is unreachable from there: the stage cannot ask for the next chunk,
and cannot say that a chunk is done, without a method that exists.

**Nothing on `main` supplies one.** `MemoryStore` carries `add`, `write_atomic`,
`get`, `get_many`, `search`, `list_beliefs`, `delete`, `clear`, `export` and
`purge_expired`, and not one of them is resumable. `list_beliefs` is the near
miss and ADR-0111 §2 already refused it in terms: its paging "may skip or repeat a
record" over a mutating store, and "the *page number* is not the position". Its
own docstring puts the matter beyond argument from the other side as well — it
enumerates "newest revision first", an order keyed on a field every `REINFORCE`
moves, so it fails §2's "must not reorder rows under later writes" before the
offset question is even reached.

**The mechanism ADR-0111 §1 chose does exist, one layer down.**
`SqliteMemoryStore` creates `records` with an explicit `rowid INTEGER PRIMARY KEY`
beside a `meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)` table, which is exactly
the pair §1 pointed at. `Reembedder` in `memory/reembed.py` already runs a chunked
resumable walk over that shape, keyed on `_CURSOR_KEY` in `meta`, reading each
chunk with `WHERE rowid > ? ORDER BY rowid LIMIT ?` and writing the cursor inside
the same transaction as the chunk's rows. It is the working proof that the *shape*
is right — though not, as §1 below finds, that the bare declaration supplies the
key the shape needs — and it is not a precedent that can be reused, because
it is an offline tool holding a `sqlite3.Connection` it opened itself against a
`Path`. ADR-0104 §6 rules that "No part of the system runs this migration on its
own"; a scheduled job cannot open a database, because ADR-0083 §8 makes every job
"a public `Engine` call" holding "no concrete store, no subsystem import".

### What this decision has to be careful about

Three things, each with a wrong answer that looks reasonable.

1. **A resumption position that a caller can compose is a silent skip waiting to
   happen.** The failure mode ADR-0104 §2 names — a sentinel that "silently skips
   every row at or below it" — is reachable through the seam as easily as through
   a file, and it reports success while it happens.
2. **A read that both returns a chunk and advances the cursor is the one ordering
   ADR-0111 §3 forbids.** It is also the convenient shape, and it puts the cursor
   permanently ahead of the effects.
3. **A contract that carries a transaction across the seam would buy ADR-0111
   §3's stronger clause for no consumer**, and would be the largest thing in this
   contract.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. The walk is two operations on `MemoryStore`, and reading never advances anything

> **Normative.** `MemoryStore` gains exactly two operations: a **chunk read**
> that returns the next records of a named walk without changing any stored
> state, and a **cursor advance** that records a named walk's position. No third
> operation is added, and neither of the two performs the other's effect.

The shape, stated as ADR-0072 §2 stated `band_of`'s rather than left to the lane.
The semantics above and below are the contract; the spelling is the implementing
lane's, in ADR-0073 §1's form:

```python
async def walk_records(self, walk: NonBlankEncodableText, *, limit: int) -> RecordChunk: ...
async def advance_walk(
    self, walk: NonBlankEncodableText, *, position: WalkPosition
) -> None: ...
```

> **Normative.** The chunk read examines at most `limit` records, in the store's
> own insertion order, beginning strictly after the position recorded for `walk`,
> and returns the eligible ones among them together with the position of the last
> record it **examined**. Its work is bounded by `limit` whatever the eligibility of
> those records. It writes nothing: two consecutive reads with no intervening
> advance return the same records.

> **Normative.** The order a walk reads is keyed on a value the store issues once
> per stored record. Every key a store issues is **greater than every key it has
> already issued**, and no key is reissued after the record holding it is deleted,
> purged, retired or superseded, or after the store is emptied. An implementation
> whose key can be reissued does not satisfy this contract.

> **Normative.** The guarantee above runs from the moment a store begins issuing
> keys under this contract, and the first key it issues then is **greater than
> every key present in the store at that moment**. Keys a store issued before it
> carried a walk surface are outside the guarantee, and an implementation is not
> obliged to know what they were.

**A key that is merely unique is not enough, and SQLite's default is exactly that
key.** `records` in `SqliteMemoryStore` declares `rowid INTEGER PRIMARY KEY`
without `AUTOINCREMENT`, and SQLite's ordinary rowid algorithm issues one more than
the **largest rowid currently in use** — so deleting the highest row releases its
number for the next insert. That is reachable through three paths the store already
has: a single `delete`, a `clear`, and `purge_expired`. Walk to the end, let the
newest record be forgotten, add another, and the new record is issued the position
the walk has already passed; `WHERE rowid > ?` never returns it, the walk reports
success, and nothing downstream knows the record existed. It is the silent skip
ADR-0111 §2 exists to prevent, arriving through the one axis §2 named as safe, and
adversarial review found it on round 1.

**So `rowid` is the right axis and the bare declaration is not the right key.**
The clause above states the property rather than the DDL, because the property is
what a second implementation has to satisfy and SQLite's `AUTOINCREMENT` is only
the mechanism that is to hand here — it keeps a high-water mark in `sqlite_sequence`
and never reissues, which is the clause exactly. One constraint bounds the lane
that takes it: existing rows keep their current values, because `vec_records` joins
`records` by `rowid` with no foreign key and `Reembedder` carries each original
forward explicitly. Seeding the high-water mark is then the ordinary thing —
`max(rowid)` as it stands, which is what adopting `AUTOINCREMENT` over an existing
table does anyway.

**The second clause is where an earlier draft asked for something no store can
supply, and the narrower rule is not a concession — it is the right rule.** That
draft required the mark to be seeded above the largest value the store had **ever**
held. A legacy database holding only rowid `1` is indistinguishable from one that
held `2` and deleted it: neither `records` nor `meta` retains the deleted maximum,
and there is no `sqlite_sequence` to consult, so the only ways to obey were to guess
or to seed at SQLite's ceiling and refuse every future insert. Adversarial review
found it on round 2.

**Pre-contract history cannot hurt a cursor, and that is why excluding it is
sound rather than merely necessary.** No walk position exists before the walk
surface does — this ADR is the contract that creates it — so there is no recorded
cursor naming a pre-adoption key. After adoption every issued key exceeds every key
then present, and thereafter every issued key exceeds every issued key, so a new
record's position is always **above the highest key ever issued** and therefore
above any position a walk can have recorded. A store that reissues a number some
long-deleted record once held is reissuing it into a range no cursor has ever named,
which is why the guarantee is about the keys a store issues under this contract and
not about its archaeology. `clear` is safe twice over on the same reasoning: the
high-water mark survives it in `sqlite_sequence`, and §4's clause discards the walk
positions along with the records regardless.

**ADR-0104 §2 is not falsified by this and its cursor is not at risk.** That
migration walks bare `rowid` too, and it is safe for a reason a recurring walk
cannot borrow: it holds a fingerprint of the source and "re-runs the whole
migration on any doubt", so a source that changed underneath it is detected and
restarted wholesale. A scheduled walk has no wholesale restart to fall back on —
that is the whole of why it has a cursor — so it needs the guarantee in the key
instead of in a check around it.

**Splitting the read from the advance is ADR-0111 §3 made expressible rather than
merely stated.** §3 rules that a cursor "may lag its effects and may never lead
them", and an operation that advanced as it read would make leading the effects
the only available behaviour — the caller could not put its writes between the two
halves because there would be no between. With the split, the ordering ADR-0111 §3
obliges is the ordinary sequence of two calls, and a lane that gets it wrong is
visible in the code rather than in the store six weeks later.

**The read takes no *caller* filter, and it honours the store's own lifecycle
predicate.** Those are two different things and an earlier draft ran them together,
saying the read "yields every record the store holds".

> **Normative.** The chunk read takes no filter from its caller. No band, kind or
> validity argument is offered, and any selection over a chunk is the caller's.

> **Normative.** The chunk read yields only records that are **retained and live**
> at the instant it reads — the same predicate `get` and `search` apply, on both
> ends of the validity window. It never yields an expired record and never yields
> one whose window is closed or not yet open. The instant is read once per chunk,
> so one chunk is judged against one reading of the clock.

> **Normative.** A chunk carries **no position exactly when there was nothing left
> to examine**, and that — never an empty record list — is how a caller learns the
> walk is exhausted. A chunk may carry a position and no records, meaning the range
> it examined held nothing eligible, and a caller advances on it exactly as on any
> other.

**A caller filter and the lifecycle predicate fail in opposite directions, which is
why one is refused and the other required.** A caller filter would make a walk's
position mean "the last record matching *this* filter", so two callers sharing a
name with different filters would advance each other past unexamined records — the
silent skip ADR-0111 §2 exists to prevent, arriving through the read. The lifecycle
predicate cannot do that: it is fixed, identical for every caller of every walk, and
not something two callers can disagree about.

**And omitting it would make this the one read in the store that breaches
retention.** ADR-0045 §6 is explicit that the two axes are orthogonal and that
"**`expires_at` is retention** (a privacy deadline; an expired record is gone from
*everything*, including `export`)", while a closed window is "off the read path but
present in `export`". A walk yielding either would hand expired content — or a
belief the user has already corrected — to a consolidator, which is a model-backed
producer that will write a *new* durable belief from it. That resurrects retired
content through the one door nobody was watching, and it would be this contract's
doing rather than the consolidator's. Architecture review found it on round 7.

**The walk sides with `get`/`search` and not with `export`**, and the choice is the
consumer's rather than a default: `export` keeps closed windows because a
data-rights snapshot must show what the store holds, whereas everything that
*derives* new content reads the live set. ADR-0110 §6's reconciliation wants the
same live set for the same reason. A later job that genuinely needs retired records
is asking for as-of retrieval, which ADR-0045 §1 defers and this ADR does not
supply.

**The bound is on records *examined*, not records returned, and that is forced by
ADR-0111 §4 rather than chosen.** §4's second clause makes a per-operation deadline
"a precondition of being chunked at all", and a read that scanned forward until it
had `limit` *eligible* records would have no bound at all: a store with a long run
of expired or closed-window rows makes one call walk arbitrarily many of them, and
`limit=1` over an all-ineligible tail scans to the end of the store. That is the
serial loop held for as long as the scan takes, with no figure in `Settings` that
would say so — exactly the hazard §4's second clause was added to close.
Adversarial review found it on round 9, in the fix that closed the retention hole
on round 7.

**Which is why exhaustion is signalled by the absent position and not by an empty
record list.** With the bound on examination, a chunk over a dead range legitimately
returns nothing, and a caller reading that as "exhausted" would stop short forever;
a caller that instead re-read without advancing would rescan the same range every
run and never progress. The position is the honest signal: it is absent only when
there was nothing left to look at, so a walk over an all-ineligible tail advances
through it a bounded chunk at a time and terminates.

**What the predicate cannot do is revisit a record whose eligibility changes below
the cursor**, and no mechanism is offered for it. A window that opens after the
walk has examined its record is never reached, which is precisely the limit ADR-0111
§2 names — "a row updated in place below the cursor keeps its position and is not
revisited" — and its ruling stands: "A job whose correctness requires reconsidering
changed rows cannot express its selection as a high-water mark alone, and this ADR
gives it no other mechanism." **This is the one place the bounded scan costs
something real**, and it is named rather than buried: a record whose `valid_from` is
in the future can be examined, found not yet live, and passed. ADR-0045 §6 records
that this ADR's own mechanisms "never set `valid_from` to the future" while a
producer may, so the case is possible rather than produced; an unbounded scan is a
starvation risk on every run. The bounded scan is the better trade and ADR-0111 §4
does not leave it open anyway.

The remaining cost is that a consolidator reading only beliefs still pays for the
episodes in between, which is the same trade `list_beliefs` already takes when it
decides the band, the `valid_from` end of the window and its sort key on decoded
records rather than in SQL, "which this read does not need at a personal store's
scale".

### 2. A position is opaque to its caller, and is never a value a caller composes

> **Normative.** A walk position is opaque: no caller may parse, order, compare,
> arithmetically derive, persist or synthesise one. The only admissible source of a
> position is the chunk read that returned it, and the only admissible use is
> passing it to the cursor advance for the walk it came from.

> **Normative.** A position is **bound to the walk it was issued for**. The cursor
> advance refuses a position bound to a **different** walk, as a defined refusal on
> every backend rather than a silent no-op. An implementation satisfies this
> statelessly by making the bound walk recoverable from the token it hands out.

> **Normative.** The clause above is the whole of what the store detects. A
> position that names the right walk but was never issued by it is a breach of §2's
> first clause by the caller, and no implementation is obliged to detect one.

> **Normative.** `core/types.py` gains two frozen models: a `WalkPosition`
> carrying one opaque token typed `NonBlankEncodableText`, and a `RecordChunk`
> carrying the eligible records of one chunk and the position of the last record
> the chunk examined. The position is absent exactly when the chunk examined
> nothing, and a chunk may carry a position with no records.

Two facts force opacity rather than recommend it. The position is the *store's*
order key — `rowid` in `SqliteMemoryStore`, an insertion index elsewhere — and
nothing about that key is on a `MemoryRecord`, so a caller deriving a position
from a record it read would be inventing one. And a caller that could compose a
position could compose a wrong one, which is the class of failure ADR-0104 §2
records in its own domain: the obvious sentinel "silently skips every row at or
below it", and the symptom was "a verification complaint about counts rather than
anything an operator could act on".

**Binding the position to its walk is what makes §5's independence structural
rather than merely stated.** §2's opacity clause already told a caller to pass a
position only "to the cursor advance for the walk it came from", and an obligation
is not a mechanism: with a bare order key as the token, a caller holding walk `A`'s
legitimate position for row 50 can hand it to walk `B`'s advance, and a conforming
implementation records `B` at 50 and never processes rows 1–50. Every record before
that point is skipped, `B` reports healthy progress, and nothing distinguishes the
call from a correct one. **This is unlike §3's ordering precondition, which the
store genuinely cannot referee** — there the effects live outside the store, whereas
here the store issued the position itself and holds the walk name in the same call,
so refusing the mismatch costs it nothing. Where a check is available, an obligation
is the wrong instrument. Adversarial review found it on round 12.

**What the walk binding does *not* do is authenticate issuance, and the clause is
written to what the mechanism delivers rather than past it.** An earlier draft said
the advance refuses a position "the named walk did not issue", which requires
distinguishing an unissued token from an issued one and so promised precisely the
mechanism the paragraphs below decline — a clause and its own justification pulling
against each other, which adversarial review caught on round 14 after proposing the
mechanism on round 13. The rule is therefore stated as a **mismatch** refusal,
which walk-recoverable tokens deliver exactly, and the fabricated same-walk token
stays where §2's first clause already put it: a caller that synthesises a position
has broken the contract, and the store is not obliged to notice.

That mechanism — an unforgeable token — is declined for three reasons, recorded
here because a refused direction that lives only in a pull request is a judgement a
later reader cannot check.

- **It defends a boundary that does not exist.** The caller is an `orchestration`
  stage in the same process, holding the same `MemoryStore` handle, which already
  offers `delete`, `clear` and `write_atomic`. A component willing to fabricate a
  cursor can empty the store outright; there is nothing a forged position buys it.
  ADR-0094 §5's "a claim carried in a submission is not evidence of the standing it
  claims" is a rule about a **spoke**, across a seam this system actually draws, and
  ADR-0098's threat model is ingested content rather than the hub's own components.
- **It does not solve the realistic failure.** The plausible bug is not a
  fabricated token but a **stale legitimate** one — a caller reusing a position it
  should not have kept, which §2's first clause already forbids. A stale token is
  authentic, so a MAC or a signature accepts it and the forward jump happens
  anyway. Only recorded issuance state with expiry would catch it, and that is the
  unbounded "set of processed identifiers" ADR-0111 §2 refuses for the cursor
  itself, reintroduced as its guard.
- **The cost is not notional.** Authentication means a secret in a local store: a
  key to generate, persist beside the data it protects, and rotate — inside the
  component whose job is a personal SQLite file (ADR-0004 §3 puts secrets in the OS
  keyring, not here).

The round-12 binding is kept because it was the opposite case: the store already
held both the name and the position it issued, so the check cost nothing. This one
would cost a key to buy a guarantee that misses the failure it is aimed at.

**Frozen models rather than a string alias**, for the reason `MemoryWrite` is
frozen: a value that governs whether records are skipped must not be
reconstructible by accident from something that happens to be a string. A record
id and a position are both text and mean entirely different things, and a seam
that accepts either accepts the wrong one silently.

**A position is a bound, not a reference, which is why deletion does not disturb
it — given §1's never-reissued key, and only given it.** `delete`, `purge_expired`
and a retirement all remove or rewrite rows below a recorded position, and none of
them invalidates it: the position says *where the walk has reached*, and the next
chunk is whatever the store now holds after it. That reasoning is sound exactly
because a deleted record's key is not handed to a later one; without §1's clause
the same sentence would be false in the one case that matters, which is why the
clause is there and not left as an implementation detail. This is also the property
ADR-0111 §2 names as the limit of a high-water mark — "a row updated in place below
the cursor keeps its position and is not revisited" — and it is stated here as the
reason the contract needs no repair operation.

### 3. The cursor advances behind the effects, never backwards, and never by itself

> **Normative.** The cursor advance records the given position durably before it
> returns, so a walk that has advanced has advanced whatever follows.

> **Normative.** A caller advances a walk only to a position from a chunk whose
> effects are already durable. No clause of this ADR may be implemented in a way
> that lets a cursor record a chunk whose effects are not.

> **Normative.** The clause above is a **caller-ordering precondition that no
> store can enforce**, and every lane that ships a walking job ships a test for it:
> a failure or a cancellation arriving after the chunk's work has begun and before
> its effects are durable leaves the walk's recorded position **unchanged**, so the
> chunk is re-processed on the next run. A job tested only on its success path
> satisfies no clause of this ADR.

**The store cannot referee this and the contract says so rather than implying
otherwise.** The advance is a call like any other; a job that makes it before its
effects are durable has committed a cursor ahead of its work, and the store sees
the same two calls in the same order either way. That is the cost of §3's refusal
to carry the effects, it is the reason the obligation is stated twice — once on the
caller, once as a test each job owes — and it is why the Consequences below say the
ordering is made *visible* rather than impossible. ADR-0111 §3's own asymmetry is
what bounds the damage when a lane gets it wrong: the failure is a skipped chunk,
which is why the test is required rather than recommended.

> **Normative.** The cursor never moves backwards. An advance to a position at or
> behind the one recorded for that walk leaves the recorded position unchanged and
> is not an error.

**The monotonicity clause is the caller's mistakes made harmless in the safe
direction.** ADR-0111 §3 makes a scheduled walk at-least-once, so a chunk is
re-processed after a crash and a stale position is a thing a resumed run can hold;
under this clause the worst outcome is repeated work, which ADR-0077 §8 already
priced ("re-observation is safe by construction… the gate folds each into a
`REINFORCE` on the existing record rather than writing a duplicate"). Without it,
the worst outcome is a walk rewound past records that will now be skipped forever
by the *next* advance. Those two costs are not comparable, which is ADR-0111 §3's
own asymmetry applied one layer down. Note that only the store can honour this
clause, because only the store can compare two positions — which is the same fact
that makes §2's opacity cost the caller nothing.

**This contract carries ADR-0111 §3's second clause and not its first, and the
reason is that no job can use the first.** §3's stronger form commits "a chunk's
effects and the cursor recording that chunk … in one transaction where they live
in one store". Every producer the corpus has reaches memory through the
orchestration write stage — ADR-0078 §3 rules that the stage "already holds the
`MemoryWriter` by injection and now also holds the `DeferralStore`", and ADR-0106
§6 obliges a consolidator to use it — so a walker's effects are committed by
`MemoryWriter.ingest` inside a transaction the walker does not hold, and a tainted
proposal additionally lands in a second database as a `DeferredProposal`. A
`writes=` parameter on the advance, or a transaction handle crossing the Protocol,
would therefore be surface with no consumer, which ADR-0045 §1 and ADR-0028 §7 both
refuse and ADR-0106 §2 refused one field over.

> **Normative.** This ADR adds no transaction handle to any Protocol and no
> parameter carrying record writes to the cursor advance. A job whose walker
> commits its own effects and wants ADR-0111 §3's one-transaction form is a later
> lane's, and that lane decides the primitive.

**What is lost by taking the weaker clause is exactly one repeated chunk**, on a
crash between a chunk's effects and its advance — which ADR-0111 §3 ratifies as
at-least-once and names as the designed cost. What is gained is that this contract
stays two methods.

### 4. An absent, unreadable or unsupported cursor restarts the walk and never raises

> **Normative.** A walk with no recorded position begins at the first record of
> the order. No implementation initialises a position to a sentinel.

ADR-0104 §2's reason transfers unchanged and is the reason this is a clause rather
than an obvious default: "There is no integer to use as one. `rowid` is an
explicit `INTEGER PRIMARY KEY` here, so it starts at `-2**63` and SQLite has
nothing below that to compare against — which makes the obvious sentinel, `0`,
silently skip every row at or below it."

> **Normative.** A recorded position that is unreadable, malformed, written in a
> form this build does not understand, or not supported by the store's current
> contents is discarded, and the walk restarts from the first record of its order.
> The store does not raise, does not refuse to open, and does not report a state
> fault for any of these.

This is ADR-0111 §7 stated at the seam that has to honour it, and it comes out the
way §7 came out for §7's own reason: a cursor "holds no evidence and answers no
query", so discarding one "returns nothing wrong to any client" and costs only the
repeated walk §3 already accepted. `IncompatibleStateError` is not its class, and a
store that refused to open over one would take a resident process down over
scaffolding.

> **Normative.** `clear` discards every recorded walk position along with the
> records, in the same operation. No walk resumes from a position naming rows a
> `clear` removed.

Without this clause `clear` produces exactly the state ADR-0111 §7's second clause
describes — a cursor and a store that disagree — and while the clause above
already disposes of it correctly, leaving it to be detected is worse than not
creating it. It is also the shape #738 reports in the migration's own domain, where
a store with "rows present, cursor absent" sticks instead of being discarded.

**`clear` discards the positions and must not reset the key sequence, and the two
halves are what make an in-flight walk safe across one.** §1's clause already
forbids the reset — "or after the store is emptied" is that case — and this is
where the reason shows. A walker can be holding a chunk's position when another
caller empties the store, and it will then advance to a position §4 has already
discarded; the advance is the first for that walk, so nothing compares against it
and the store records it. That is harmless **only** because the key sequence did
not reset: every record added after the `clear` is issued a key above every key
issued before it, so a cursor sitting at a stale position names a point below all of
them and the next chunk returns every one. Reset the sequence and the same sequence
skips them silently — the walker's own stale position now sits *above* live records
that will never be read again. So no special disposition is needed for a stale
advance, and the invariant is doing the work; adversarial review found on round 3
that nothing in §8 made an implementation prove it, which is the gap that mattered
rather than a missing refusal.

### 5. A walk is named, and two names never share a position

> **Normative.** A position is recorded per walk name. The store treats the name
> as opaque, never interprets it, never normalises it, and never shares a position
> between two names.

> **Normative.** A walk name is declared `NonBlankEncodableText` on both
> operations, and **every implementation validates it on entry** — before it
> reaches a query, a key, or any stored state — so that an empty, whitespace-only
> or unencodable name is refused identically on every backend. The annotation
> states the intent; the entry check is what enforces it.

This is ADR-0111 §1's "A cursor is per walked order and per job. Two jobs walking
the same store do not share a position, and one job walking two orders holds one
position in each", discharged with one parameter rather than a matrix: the name
identifies the (job, order) pair, and a store that maintains a second order gives
it a second set of names.

**The name is checked because it becomes store state, and the backends disagree
about what a `str` is.** `walk_records("\ud800", …)` is an ordinary Python call:
SQLite cannot UTF-8 encode a lone surrogate when binding it as a `meta` key, so one
backend raises a `UnicodeEncodeError` out of the driver while an in-memory one
accepts it happily — backend-dependent behaviour on a value the contract had said
nothing about. `EncodableText`'s validator exists for exactly this class and names
`"\ud800"` itself; `NonBlankEncodableText` adds the empty and whitespace-only cases
a `""` check alone misses.

**The check has to be an obligation on the implementation, and an earlier draft
made it a property of the annotation.** That draft said the name was "refused by
the type before any implementation sees it", which is false: these aliases are
pydantic `Annotated` validators, and Python runs nothing for a plain method call —
they bind on a model field or through an explicit adapter and nowhere else. The
corpus already knows this and already has the remedy at precisely this kind of
seam: `wire/codec.py` and `orchestration/grants.py` each hold a module-level
`TypeAdapter[str](NonBlankEncodableText)` and validate what arrives. The clause
above asks these operations for the same thing, so the uniformity it promises is
bought by the check rather than asserted of the notation. Adversarial review found
the bare `str` on round 5 and the false claim about it on round 6.

**Not normalised**, which §5's first clause states: two names differing only in
case or spacing are two walks, because a store that quietly merged them would merge
two jobs' positions and skip records for one of them.

> **Normative.** A walk position is operational state, never user content. It is
> absent from `export`, and nothing about it is Tier 1.

ADR-0111 §9 already settled the classification — "A cursor position is a row
position, not content, and a chunk count is a number; both are Tier 2" — and the
clause exists because `export` is ADR-0007's data-rights surface and a lane
extending it would have no reason to know that.

### 6. The chunk bound is `scheduler_chunk_size`'s, and zero is refused

> **Normative.** The chunk read refuses a `limit` that is not **exactly an `int`**
> — `bool` included, and every non-integer with it — and refuses one outside
> `1 <= limit < 2**63`, raising rather than clamping. Zero is refused with the rest.
> Every implementation checks this on entry, before the value reaches a query or a
> slice, so the refusal is the same refusal on every backend, and none substitutes a
> different bound.

The over-wide end is `list_beliefs`' own reason, quoted rather than re-derived:
"Python's `int` is unbounded and SQLite's parameter binding is not, so an over-wide
value raises `OverflowError` out of the driver while an in-memory store answers with
an empty page". Two reads on one Protocol disagreeing about what an over-wide limit
does is a difference nobody would look for, and this one does not.

**The zero end deliberately does *not* follow `list_beliefs`, and an earlier draft
copied it without noticing what it collided with.** That read accepts `0` and
answers with an empty page, which is harmless there because a page carries no
exhaustion semantics. Here it is not harmless and not merely useless: a chunk read
that examines nothing has no position to carry, and §1 makes an absent position mean
**nothing remains to examine**. So `limit=0` over a store full of unwalked records
would answer with the exact shape that tells a caller the walk is finished, and a
job configured to a zero chunk would report a completed walk having read nothing at
all. Adversarial review found it on round 10.

**Refusing zero closes that by construction rather than by adding a signal**, which
is the cheaper of the two repairs and the one that leaves the contract smaller: the
alternative — an explicit exhaustion flag beside the position — adds a field to
`RecordChunk` for a case no caller wants, and leaves the ambiguous call
constructible. Zero is not a bounded request for work; it is a request for no work,
and it can make no progress by definition.

**"Exactly an `int`" is the other half, and it is the same lesson §5 learned about
the walk name one section earlier.** An annotation validates nothing on an ordinary
method call, so `limit=True` satisfies `1 <= limit < 2**63` — `bool` is an `int`
subclass and `True == 1` — and quietly becomes a one-record chunk, while `limit=1.5`
passes the same comparison without being a count at all and then meets whatever the
backend does with it. `core/config.py` already refuses exactly this for exactly this
reason, in the words ADR-0111 §4 quotes when it pins `scheduler_chunk_size`: `bool`
"is an `int` subclass, so `True` would otherwise load as a chunk size of one", which
is why those fields are `_IntegerSetting` rather than bare `int`. The entry check
here is that rule at the seam the setting is handed to. Adversarial review found the
gap on round 11, having found its twin on the walk name on round 6; an ADR that
required the check for one argument and not the other was inconsistent with itself
rather than merely incomplete.

**The bound now matches the setting that feeds it exactly.** ADR-0111 §4 pins
`scheduler_chunk_size` to an `int` in `[1, 2**63)` and refuses a bad value at load,
so a configured chunk size is always an admissible `limit` here and the two figures
cannot disagree — which is a stronger alignment than the one with `list_beliefs`
that the earlier draft reached for, because the setting is what actually calls this
read.

### 6a. Every refusal in this contract is a `ValueError`

> **Normative.** All three refusals these operations state — a walk name that is
> not `NonBlankEncodableText`, a `limit` that is not exactly an `int` or is outside
> `[1, 2**63)`, and a position bound to a different walk — are raised as
> **`ValueError`** by every implementation. A failure of the store itself is a
> `MemoryStoreError` as everywhere else, and no implementation reports a caller's
> bad argument as one.

**Naming the class is what makes "the same refusal on every backend" mean
anything.** Without it a SQLite implementation can surface its binding failure as a
`MemoryStoreError` while an in-memory one raises `ValueError`; both refuse, both
satisfy every clause of §8 as an earlier draft wrote it, and a caller cannot handle
one invalid call uniformly — which is the backend divergence §5 and §6 exist to
close, surviving in the one place neither of them looked. Adversarial review found
it on round 15.

**`ValueError` because `list_beliefs` already says so**, one method over on this
same Protocol and for this same argument: it raises `ValueError` "If `limit` or
`offset` falls outside `0 <= value < 2**63`", and `Observer.observe` raises one for
a batch that breaks its bound. A second convention for the neighbouring read would
be a difference nobody would look for, which is the argument §6 already makes about
the over-wide end. The position mismatch joins them rather than taking a store
error, because it is decided from the arguments alone — the store has not been
touched when it is refused, and a caller passing another walk's position has a bug
of exactly the kind a bad `limit` is.

### 7. Serialisation: the cursor needs none, and the job may still owe one

> **Normative.** This ADR requires no serialisation primitive for the cursor
> itself, and adds none. The scheduler runs one job at a time (ADR-0111 §8), so one
> walk's position has one writer.

> **Normative.** Nothing in this ADR relaxes ADR-0110 §5a. A walking job whose own
> work is a read-modify-write across the store owes that section's serialisation
> requirement, and this contract neither supplies it nor exempts anyone from it.

The second clause is stated because the first invites the wrong generalisation. A
walk read followed by a cursor advance is not a read-modify-write over the records
— the position is written, the records are not — so nothing here engages ADR-0046
§5's residual. A reconciliation that reads a chunk and then writes closes over the
records in it is a different thing entirely, and ADR-0110 §5a already refuses it
"over an unserialised read-modify-write". A lane reading this section as a
statement about its whole job rather than about the cursor would take the wrong
half of that disjunct.

### 8. What the implementing lane owes

> **Normative.** The lane landing this contract lands the whole triad in one
> change: the two Protocol operations with the two `core/types.py` models, the
> clauses below added to `MemoryStoreContract`, and `FakeMemoryStore` conforming to
> them. It updates `SqliteMemoryStore` and the in-memory store in the same change.

> **Normative.** The conformance suite asserts, over every implementation: that a
> walk with no recorded position starts at the first record; that a chunk read
> twice with no advance returns the same records; that a walk advanced to a chunk's
> position returns the *following* records and never repeats one; that an advance to
> a position at or behind the recorded one leaves the walk where it was; that two
> walk names hold independent positions; that a chunk carries no position exactly
> when it examined nothing; and that `clear` leaves no walk resumable.

> **Normative.** The suite asserts the cross-walk refusal over a walk that
> **already holds a position**, and asserts it as *no observable change at all*:
> walk `A` forward, advance `B` to a position of its own, read `B`'s next chunk and
> keep it, then present `A`'s position to `B`'s advance and require both the
> `ValueError` and that `B`'s next chunk is **exactly** the chunk kept before the
> call. Nothing weaker suffices, and the two weaker forms each pass a real defect:
> run against a fresh `B` the case cannot fail at all, because `B` has no position
> to lose; and asserting only that `B` resumes *after* its prior position passes an
> implementation that writes `A`'s position and then raises, since a cursor dragged
> forward from 20 to 50 is still strictly after 20 while positions 21–50 are gone.

> **Normative.** The suite additionally asserts the two dispositions a wrong
> implementation passes every other clause on: that a walk whose recorded position
> the store cannot use restarts from the first record **rather than raising**, and
> that a record inserted during a walk is reached by a later chunk rather than
> shifting a position already recorded. The first fails an implementation that
> treats an unusable cursor as a fault; the second fails one that records an offset
> and calls it a position.

> **Normative.** The suite asserts §1's never-reissued key directly, over the
> sequence that breaks a merely-unique one: walk to the end of the store, delete
> the record holding the highest position, add a new record, and assert the walk
> reaches it. The case runs for `delete`, and for a `purge_expired` that reclaims
> the highest-positioned record.

> **Normative.** The suite asserts the lifecycle predicate on both axes: an
> expired record is never yielded; a record whose validity window is closed is
> never yielded, nor is one whose window has not yet opened; and a walk over a
> stretch of records that are **all** ineligible returns an empty chunk **carrying
> a position**, and that advancing on it and reading again returns the eligible
> records beyond the stretch. The last case fails an implementation that returns no
> position for a dead range, which stalls the walk there for good.

> **Normative.** The suite asserts that the chunk read's work is bounded by
> `limit` records examined and not by `limit` records returned, over a store whose
> ineligible run is longer than `limit`: the read returns having examined `limit`
> records, and a walk over an all-ineligible tail reaches the end in a bounded
> number of chunks rather than in one long scan. An implementation that scans until
> it has filled the chunk passes every other clause here and breaches ADR-0111 §4.

> **Normative.** The suite asserts that `clear` does not reset the key sequence:
> after a `clear`, a newly added record's position is greater than every position
> the store issued before it, and a walk holding a position from before the `clear`
> that advances to it afterwards still reaches every record added since. An
> implementation that resets its high-water mark in `clear` passes every other
> clause here and fails this one.

> **Normative.** The lane migrating an existing store ships a test over a store
> **populated before the walk surface existed** and carrying a gap at its top — its
> highest-positioned record deleted before the migration ran — asserting that the
> first record added afterwards is reached by a walk that has already run to
> exhaustion. A test over a store created fresh under the new schema cannot fail on
> this and does not satisfy the clause.

> **Normative.** The suite asserts the refusals §5 and §6 state, since a clause
> nothing exercises is an obligation nobody meets: **both** operations refuse a
> walk name that is empty, whitespace-only, or a lone surrogate, and the chunk read
> refuses a `limit` of `-1`, of `0`, and of `2**63` — the zero case run against a
> **non-empty, unexhausted** walk, where a wrong implementation answers with the
> positionless chunk that means exhaustion — and refuses `True`, `1.5`, a `str` and
> `None`, none of which is exactly an `int`. `True` is the case that matters most,
> because it satisfies every range comparison and is the one a reader would not
> think to write. Every one of these refusals is asserted to be the same refusal
> on
> every implementation, and each case is exercised by **calling the operation
> directly** — the way every caller reaches it — rather than by constructing a
> validated model around the argument first.

The last clause is there because the negative case is not symmetric with the
over-wide one and only one of them looks dangerous. SQLite reads `LIMIT -1` as *no
limit*, so an implementation forwarding the argument returns the whole store where
the contract says it must refuse — an unbounded read inside a job whose entire
purpose is to be bounded, and one every positive-path case above passes.

Each clause names the case that can fail, because each has a wrong implementation
the neighbouring test waves through. A suite that only walks a store nobody writes
to passes an offset masquerading as a position, which is the single defect ADR-0111
§2 spends its longest paragraph on. A suite that never hands the store an unusable
position passes an implementation that raises, which under ADR-0111 §7 would take
the hub down over scaffolding.

**An in-memory implementation satisfies these clauses without persisting
anything**, and the suite must be writable against one. The obligations above are
about *semantics* — where a walk starts, what an advance means, what an unusable
position does — and "durably before it returns" (§3) is satisfied by a store whose
durability is its process lifetime, exactly as `add` is. Stating this keeps the
suite from being written against SQLite and then failing the in-memory store for
conforming.

### 9. What this ADR does not decide

- **What a consolidation concludes.** ADR-0106 owns the taint marker, the band, the
  gate's ceiling, the routing through the write stage and the retention of refused
  work. Not one of them is touched, narrowed or widened here. This ADR decides how a
  walker asks for records and says it is done, and nothing about what it may make of
  them.
- **How the walk is scheduled, bounded, or halted.** ADR-0111 §§4–8 decide the run
  budget, the chunk count, halting at the first chunk that cannot be recorded, the
  absence of backoff and the serial loop. This contract is what those clauses were
  missing, not a revision of them.
- **The `Engine` operation a consolidation job calls, which needs no
  `core/protocols.py` change.** ADR-0083 §8 already ruled that the Engine's
  maintenance operations are "new *concrete* surface on a class in `orchestration`,
  not `core` contract surface", and ADR-0085 §1 fixes the promoted `AssistantEngine`
  Protocol at fifteen request methods with lifecycle deliberately off it, noting
  that "the concrete `Engine` keeps both methods and stays substitutable, because a
  Protocol constrains what an implementation must have, not what it may not".
  `Engine.purge_expired` and `Engine.ingest` are the standing proof. This is
  recorded as a non-decision so the implementation lane does not relitigate it.
- **Any authentication of a walk position.** §2 binds a position to its walk and
  stops there: this contract adds no MAC, no signature and no issuance ledger, and
  a lane may not read §2's binding as promising unforgeability. The argument is in
  §2 and the shape it would take belongs to whichever ADR first draws a trust
  boundary inside the hub, which none does today.
- **A compare-and-swap, an `IF_UNCHANGED` write mode, or a concurrency token on
  `MemoryRecord`.** ADR-0110 §5a scopes all three to ADR-0046 §5's own lane and
  #248, in terms, and this ADR takes nothing of that ground.
- **`list_beliefs`' paging.** ADR-0111 §2 filed improving it with the scheduler
  lane and then declined to use it; this ADR declines it a second time and changes
  nothing about that read. Its offset paging keeps exactly the behaviour its
  docstring and ADR-0110 §6 describe.
- **A walk over any store but `MemoryStore`.** The observation job's cursor-driven
  selector (#785) walks the conversation index, and `ConversationStore` already
  carries keyset reads — `stamped_conversation_ids` and `episodes_to_purge` both
  take an `after_id`. Whether that store gains a recorded position, and in what
  shape, is that lane's decision. **The shape above is offered as the precedent and
  is not imposed**, and no shared walk Protocol is created here (see Alternatives).
- **The chunk size and run budget values.** ADR-0111 §4 sets both and this ADR
  reads them rather than revisiting them.

### 10. Records under ADR-0082 §1

ADR-0082 §1 puts the judgement in the later ADR's text — the test is whether "a
reader holding only the earlier ADR [would] now act differently, or read one of its
clauses more widely than it now holds".

**One record is owed, and this change writes it.**

**ADR-0111, its Surface bullet.** That bullet says "This ADR adds two `Settings`
fields (§4). It touches **no** Protocol in `core/protocols.py` and **no** type in
`core/types.py`, so golden rule 5 is not triggered and no triad is owed", and
locates the cursor's mechanics "below each subsystem's own façade". Both halves are
true of ADR-0111's own change and the second is not true of the walk it decided: a
`MemoryStore` walk is reached from `orchestration`, so its cursor sits *on* the
subsystem's façade rather than below it, and golden rule 5 is triggered for the lane
that builds it. A reader holding only ADR-0111 dispatches the consolidation lane as
non-contract-surface, which is the reading that produced this ADR. The test is met
on both limbs and the record is owed. ADR-0111's `Status` carries no leading token,
so under ADR-0082 §2 the qualifier belongs on that line beside the appended dated
note.

**This is a partial supersession scoped to the Surface bullet, and the scope is
where the whole of the judgement sits.** Two tests run, and they answer different
questions:

- **ADR-0082 §1 decides whether a *record* is owed** — would a reader "act
  differently, or read one of its clauses more widely than it now holds". Met, on
  both limbs.
- **ADR-0070 §1 decides whether that record is an amendment or a supersession** —
  whether the change "alters no decision", amendment being the disposition for
  "reconciling an ADR with its own text or with a fact that postdates it".

**On the second test this ADR changed its own answer, and the reasoning is recorded
because the first answer was defensible and wrong.** An earlier draft classified the
record as an amendment, on the ground that ADR-0089 §3 makes a marked ADR's unmarked
text supply no obligation and a Surface bullet is the classification of a change,
which ADR-0089 §1 names as the paradigm of what is not normative. Architecture
review refused that twice, and its second refusal carried the fact that settles it:
**ADR-0089 is itself `Proposed`.** An amendment resting on an unratified governance
ADR is a supersession-avoidance bought with a rule that is not yet ratified, and the
right disposition is the one that holds under *either* reading of ADR-0111's text —
read as prose, the Surface bullet says the cursor's mechanics need no contract
surface, and this ADR replaces that, so a supersession is owed; read under the
marking regime, scoping a supersession to an unmarked bullet costs nothing. The
scoped form is correct on both readings, and choosing it means this contract does
not depend on how that governance question lands.

**The scope is one bullet's classification and nothing else, which is what keeps the
record true.** `docs/adr/template.md` provides exactly this instrument — "the
parenthesis names exactly what was replaced. The remainder stays accepted" — and
what is replaced is the claim that this decision's cursor needs no Protocol surface
and that its mechanics sit below each subsystem's own façade. **ADR-0111 §1's marked
clause is satisfied by this ADR clause by clause and is deliberately outside the
scope**: a resumption position is still "durable state of the subsystem whose store
the job walks" — state of `memory`, in the same database as the records; still
"reached only through the same public `Engine` operation the scheduler already
calls" — the scheduler calls one Engine operation and the cursor is reached inside
it; and still one the scheduler "neither reads, writes, nor passes" — it holds an
`Engine` and nothing else, as ADR-0083 §8 requires. A supersession written any wider
would record that a placement rule this ADR is *built on* is dead, and the
implementation lane would have none to build against.

**Under ADR-0082 §2 the record therefore lives in ADR-0111's dated note**, because
its `Status` line now leads with the supersession token; the amendment qualifier an
earlier draft wrote on that line moves into the note, which is §2's own operation
and loses nothing, since §1 requires the note either way.

**No record is owed on:**

- **ADR-0083 §7.** Its "No job gets new store surface. Every one of them calls an
  operation that already exists" is a constraint on the *job* — the scheduler's
  call — and the job is untouched: it remains one public `Engine` call taking no
  arguments, with the cursor below that façade exactly as ADR-0111 §1 placed it and
  as the amendment note ADR-0111 already wrote on ADR-0083 records. The new surface
  is between `orchestration` and `memory`, where no job reaches. §7's own gloss
  confirms the reading — the sentence exists as "the reason the confirmation reclaim
  is absent above rather than listed hopefully", that is, as a refusal to invent a
  store operation for a job with no first caller. Here the first caller is decided
  (ADR-0106 §3, §6) and the contract lands ahead of it, which is the sequence golden
  rule 5 asks for. ADR-0093's calendar job is the corpus precedent: it added a new
  `core` Protocol for a scheduled job and no §7 record was owed or written.
- **ADR-0083 §8 and §13.** §8's "every scheduler job is a public `Engine` call"
  and its ruling that the Engine grows *concrete* maintenance surface are relied on
  as written (§9 above). §13's deferral of the cursor was discharged by ADR-0111,
  which ADR-0083 §15 classifies as "a stacked addition, not an amendment"; this ADR
  supplies the contract that discharge needs, which is the same shape one step on.
- **ADR-0104 §2.** Quoted as the model for a chunked resumable walk and restated at
  a different seam. Every sentence of it stays true, and §6's keeping of the
  migration outside the scheduler is untouched — this ADR obligates nothing of the
  migration and does not reach #738's instance.
- **ADR-0106.** §3 and §6 are relied on as the facts that site the walker in
  `orchestration`; no ruling of that ADR is read more widely. Its §12 defers "how a
  consolidator retains and retries refused work" to ADR-0111's lane, which answered
  it; nothing here revisits either.
- **ADR-0110 §5a and §6.** §5a is quoted and left standing, with §7 above stating
  in terms that nothing here relaxes it. §6's account of `list_beliefs`' paging is
  relied on and its filing of that paging's improvement is declined a second time,
  which changes nothing it decided.
- **ADR-0073 §1 and ADR-0086.** `list_beliefs`' contract and the evidence tuple's
  elision rules are untouched; this ADR adds a read beside them and changes neither.
- **ADR-0046 §2 and ADR-0108.** `write_atomic`, `MemoryWrite` and the declared
  write intent are untouched: the cursor advance carries no writes (§3), so no
  collision mode is engaged and the write-intent rule reaches nothing new.
- **ADR-0085 §1.** Applied and found to permit the concrete `Engine` operation (§9
  above). ADR-0083 §15's rule covers this shape: "Examining a revisit condition and
  finding it unmet changes nothing." The fifteen-method surface is neither widened
  nor narrowed.
- **ADR-0112.** It rules what *orders* a retrieval and refuses currency any part
  in it. The chunk read of §1 ranks nothing: it yields records in the store's own
  insertion order, which is a position rather than a judgement of relevance, and
  §2's opacity keeps it from being read as one. No clause about ordering is
  engaged, widened or narrowed, and this ADR grants the walk no retrieval role —
  the position ADR-0106 §8 took for the taint marker, for the same reason.
- **ADR-0113.** It adds one keyword-only `bands` parameter to `MemoryStore.search`;
  this ADR adds two operations beside that method and changes neither `search` nor
  its parameters. The two decisions are disjoint in substance and collide only in
  the file they land in, which the Consequences below dispose of as a sequencing
  matter under ADR-0068 §2. Nothing of ADR-0113 is read more widely, and §1's
  refusal of filters on the *walk* takes no view on filters elsewhere: a relevance
  read and a resumable enumeration want opposite things, which is ADR-0072 §7's own
  ground for splitting the two branches in the first place.

**The record is well-formed from the moment it is written**, on ADR-0083 §15's
ground: "The existence condition is that the naming ADR ships in the same change,
not that it has ratified." The note names ADR-0114 and ships in this change; if this
ADR does not land, neither does the note.

## Consequences

**The consolidation lane becomes buildable, and it becomes a lane with a fence
that fits.** It was blocked on exactly this: a walk that satisfies ADR-0111 §2
cannot be expressed through `MemoryStore` as it stands, and the lane that
discovered it could only stop. With this ratified, the implementation is
`core/protocols.py` and `core/types.py` for the triad, then `memory/`,
`orchestration/`, `app/` and `service/` for the job.

**`MemoryStore` grows from ten operations to twelve, and three implementations
pay.** `SqliteMemoryStore`, the in-memory store and `FakeMemoryStore` all
implement the pair, and `MemoryStoreContract` grows the clauses of §8. That is the
cost of putting the walk on the store contract rather than beside it, and it is
paid once for every store that will ever be walked by a scheduled job.

**The SQLite store additionally owes a one-time migration**, because §1's key is a
property its current `records` declaration does not have. That is the largest piece
of work this ADR creates and it is bounded: it changes how new positions are
issued, not what any existing row's position is, and it must leave every current
`rowid` where it is so the `vec_records` join keeps working. A deployment that has
never run a scheduled walk loses nothing by it, which is every deployment today.

**Two contract ADRs now want `MemoryStore`, and their implementations sequence
rather than race.** ADR-0113 decides one keyword-only `bands` parameter on
`MemoryStore.search`; this ADR decides two operations beside it. The two are
disjoint in substance — a filter on a relevance read, and a resumable enumeration
— and neither needs the other, so the order between them is a scheduling choice.
What they are not disjoint in is the *file*: both land in `core/protocols.py`,
which `CONTRIBUTING.md` names as "the one high-collision edit" and which nothing
mechanical referees. Their implementation lanes therefore sequence as separate
`core` PRs, which is ADR-0068 §2's rule and the disposition ADR-0106's
Consequences reached for this same shape one type over, when it and ADR-0103's
lane both wanted `Provenance`. Whichever lands second rebases onto the first; this
ADR takes no view on which that is, and neither lane's ratification is a
precondition on the other's.

**A second walked store will want the same shape and does not inherit it.** #785's
conversation-index walk is the next one, and §9 leaves it its own decision. If a
third arrives, promoting the pair into a shared Protocol becomes the right move —
which is ADR-0028 §7's discipline, and the trigger is stated here so the third lane
recognises it rather than adding a fourth copy.

**Repeated work stays a designed cost, and the ordering that protects it becomes
visible rather than enforced.** Splitting the read from the advance is what lets a
caller put its effects between them, and it is not what makes it do so: a job that
advances and *then* fails to make its effects durable — through a raise, a
cancellation at shutdown, or a deferral the queue never admitted — has committed a
cursor ahead of its work, and the store cannot tell that sequence from the correct
one, because §3 deliberately carries neither the effects nor a transaction. So
ADR-0111 §3's guarantee still rests on each walking job's lane getting the ordering
right; what this contract changes is that the ordering is now two calls in one
function, where a reviewer and a test can see it, rather than an invariant spread
across a store and a scheduler. §3's last clause is the obligation and its test,
and adversarial review found on round 4 that an earlier draft of this paragraph
claimed the stronger thing.

**What would trigger revisiting this.** A job whose walker commits its own effects
and can therefore use ADR-0111 §3's one-transaction clause — it would want the
advance to carry writes, and that is the parameter §3 above refuses today for want
of a consumer. A store that cannot supply a total non-reordering insertion order. A
walked store whose scale makes an unfiltered chunk read the wrong trade, which
would reopen §1's refusal of filters on measurement rather than on principle. Or a
third walked store, which reopens the shared-Protocol question above.

## Alternatives considered

**A separate walk Protocol — `WalkableRecords`, injected beside `MemoryStore`.**
The tidier-looking option, and the one that keeps `MemoryStore` at ten methods.
Rejected on three grounds, the first decisive. **It makes "the same store" a
composition-root obligation no type expresses** — the walk handle and the store the
writer persists to must be one object, or the walk yields records the write path
cannot cite and every proposal is refused for unresolved evidence. That is
precisely the class ADR-0052 §1 describes as "a composition-root single-instance
obligation… no type expresses it", and ADR-0028 §4 has already had to state one by
hand; buying a second one to avoid two methods is a bad trade, and the failure it
buys is silent. **It also contradicts ADR-0111 §1's siting**: the cursor is durable
state "of the subsystem whose store the job walks", and the object that *is* that
store is `MemoryStore`. **And it is a generic seam with one implementation**, which
ADR-0028 §7's promotion discipline refuses until a third consumer exists — the
position §9 takes explicitly, so a shared Protocol stays available on evidence
rather than on speculation.

**Keying the walk off `list_beliefs` with an offset.** The shape a reader reaches
for first, since the read exists. Rejected by ADR-0111 §2 in terms — an offset "is
a count into a result set, so a row inserted or deleted below it moves every later
row's number" — and independently by that read's own ordering, which is newest
revision first and therefore moves under every `REINFORCE`.

**A cursor the caller holds and passes in, with no stored position.** It removes
the advance operation entirely and makes the read a pure keyset page. Rejected
because ADR-0111 §1 rules the position is durable state of the walked store and
that the scheduler "neither reads it, writes it, nor passes it"; a caller-held
position has to be persisted by somebody, and every candidate is further from the
data it describes than the store is.

**A position that is a record id rather than an opaque token.** Ids are already on
the record, so the seam would need no new type. Rejected because the id order is not
the insertion order — ids are minted by an injected factory and nothing makes them
monotone — so a walk keyed on them would satisfy §2's letter and fail its
substance, and the failure would be a silent skip.

**Keeping bare `rowid` and accepting the reuse window.** The cheapest option: no
migration, no `sqlite_sequence`, and the defect only fires when the
highest-positioned record is removed and another is added behind an exhausted
walk. Rejected because that sequence is ordinary rather than exotic — capture a
record and forget it, or let `purge_expired` reclaim the newest expiring one — and
because of *how* it fails. A skipped record is never read, never proposed, and
never mentioned; the run logs a completion, the cursor looks healthy, and nothing
in the system holds a fact that would let anyone notice. §1's clause buys a
one-time migration to remove a permanent, silent and unbounded coverage hole, which
is the same trade ADR-0104 §2 made when it spent a fingerprint rather than accept a
stale resume.

**Advancing the cursor inside the read.** One operation, no ordering for a lane to
get wrong. Rejected in §1: it makes a cursor that leads its effects the only
available behaviour, which is exactly the direction ADR-0111 §3 forbids, and it
loses the crash window in the unsafe direction rather than the safe one.

**Carrying record writes on the advance, so a chunk's effects and its cursor commit
together.** ADR-0111 §3's stronger clause, and the one ADR-0104 §2 restructured a
migration around. Rejected in §3 for want of a consumer: every producer the corpus
has writes through the orchestration write stage (ADR-0078 §3, ADR-0106 §6), so no
walker holds the transaction its effects land in, and a parameter no caller can use
is surface ADR-0045 §1 and ADR-0028 §7 both refuse. It is named as the revisit
trigger rather than built on speculation.

**Refusing to start on an unusable cursor, by analogy with ADR-0083 §6.** The
nearest ratified precedent and the wrong one, for the reason ADR-0111 §7 already
gave: §6's test is whether serving would be silently wrong, and a cursor answers no
query, so discarding one returns nothing wrong to anybody.
