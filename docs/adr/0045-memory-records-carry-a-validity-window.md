# 45. Memory records carry a validity window: invalidate, don't delete

- Status: Accepted, §10's #248 conclusion narrowed by ADR-0046
- Date: 2026-07-22
- Amended: 2026-07-23 by ADR-0046 — §10's statement that '#104 closes [#248]
  alongside the atomicity primitive' is narrowed by ADR-0046: #104 delivers the
  atomic write-set §8 requires, but that primitive does not subsume #248's
  read-modify-write race — in-process across two `MemoryIngestor` instances or
  across processes — which needs a compare-and-swap ADR-0046 §5 defers for want of
  a consumer that runs two writers on one store. #248 is therefore re-scoped, not
  closed; #262's per-ingestor lock covers the single-ingestor case. ADR-0045 §8
  (its two consumer requirements and #104-as-hard-prerequisite) and every other
  ADR-0045 ruling stand unchanged.
- **Contract change.** This adds a `Validity` value object and a `validity` field
  to `MemoryBase` in `core/types.py` (both cross subsystem boundaries), changes
  the read-time contract of three `MemoryStore` methods (`get`, `search`,
  `export`) in `core/protocols.py`, and rewrites two clauses of the
  `MemoryWriter` conformance suite. It therefore ships as its **own PR** and is
  ratified before anything implements against it (golden rule 5, ADR-0015 §5,
  `CONTRIBUTING.md` → "Contract ADRs land before their implementation"). **No code
  changes with it.** The triad (Protocol/type + conformance suite + canonical
  fakes) and the store/ingest work are separate later lanes.
- **Follow-up to** [ADR-0040](0040-reinforcement-and-supersession-are-different-rulings.md)
  §6, which teed this up precisely: it named the two `MemoryWriter` obligations
  #112 must rewrite (§5a's id clause, §5b's `EXTERNAL` clause) and ruled that
  `SUPERSEDE` already names the *relation*, so a validity window changes only how
  the applier *executes* it — the members, `MemoryDecision`, `DefaultMemoryPolicy`
  and the `MemoryPolicy` conformance suite survive untouched. This ADR takes up
  that frontier. It is also the answer to
  [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md) §6's
  four deferred compromises, and to issue #112.
- **Amends on ratification:** [ADR-0007](0007-memory-data-rights.md) §3 (the
  meaning of `export`); [ADR-0040](0040-reinforcement-and-supersession-are-different-rulings.md)
  §5a and §5b (the two `MemoryWriter` conformance clauses) **and §3** (whose
  `_refuse_unsafe_fold` `EXTERNAL` arm, and whose "keyed on the records, not the
  relation" shape, both narrow: the `EXTERNAL` refusal becomes `REINFORCE`-only,
  which §5b itself named as "the second clause a validity window revisits" — it is
  *narrowed*, not deleted, because `REINFORCE` still inherits the target's id);
  and [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md)
  §2a's **ingestor-enforced** `EXTERNAL` refusal (the `_refuse_unsafe_fold` arm the
  §2a "enforced at the ingestor" clause installs — which ADR-0038 §6 anticipated a
  window would lift *for supersession*, "would let §2a supersede an `EXTERNAL`
  record without inheriting its key"). [ADR-0028](0028-the-memory-write-path-is-a-contract.md)
  §8's conformance list is touched a second time, for the two `MemoryWriter`
  clauses. **`DefaultMemoryPolicy` is not amended, and ADR-0040 §6 and §4 stand
  verbatim:** this ADR lifts only the *writer/ingestor* floor that refused an
  `EXTERNAL` supersession, leaving the shipped policy's `_SUPERSEDABLE` set
  (`{OBSERVED, INFERRED}`) untouched — so the members, `MemoryDecision`,
  `DefaultMemoryPolicy` and the `MemoryPolicy` suite all survive untouched, exactly
  as ADR-0040 §6 promised. Whether the default policy *opts in* to superseding
  `EXTERNAL` is a policy-lane choice this ADR only makes *safe*, not one it makes
  (§7). None of these edits is made by this change — ADR-0001 keeps ADRs
  append-only, so each travels with the implementation PR it describes; their exact
  form is in §Consequences.

## Context

The product thesis is an accumulated user model that improves through continuous
learning. [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md)
gave the system the ability to *unlearn* — a user correction supersedes a
conflicting inference — but it did so destructively: supersession writes the
correction **at the stale record's id**, overwriting it in place, because there
is no representation for "a belief that has stopped being true." ADR-0038 §6 named
this and four other compromises as things a validity window would give back, and
[ADR-0040](0040-reinforcement-and-supersession-are-different-rulings.md) §6 drew
the boundary exactly: ADR-0040 settled *what the policy can say*
(`REINFORCE` vs `SUPERSEDE`, naming the relation and not the mechanism), leaving
this ADR *what the store does to a record that stops being true*.

Zep's Graphiti is the prior art issue #112 cites: every fact carries a validity
window, and **when new information contradicts an existing fact, the old fact's
window is closed rather than the fact deleted.** History is preserved; reads
simply stop returning it. This is the read-time-enforcement shape ADR-0007
already uses for `expires_at`, applied to a different, orthogonal axis.

Five forces make this a decision worth recording rather than an implementation
detail.

1. **`SUPERSEDE`'s mechanism is the last destructive write in the memory model.**
   ADR-0040 §5a pins, as a temporary `MemoryWriter` obligation, that a `SUPERSEDE`
   is "written at the target's id, which is returned," and marks it as the clause
   #112 rewrites. ADR-0038 §1a discards the overturned belief's evidence outright
   "because there is nowhere honest to keep it" — and calls it "the first thing
   #112 should give back."

2. **Four neighbouring defects are all one shape — "the record is gone or wrong"
   — and all wait on this.** ADR-0040 §6 is explicit that they dissolve into #112:
   - **#254** — a user correction cannot supersede an `EXTERNAL` record, because
     supersession inherits the target's id, which is the integrating system's
     idempotency key, so the next routine sync overwrites the correction. ADR-0040
     §5b's `EXTERNAL` refusal exists solely to hold this hazard shut until a window
     revisits it (§5 narrows the refusal to `REINFORCE`, which still inherits the
     id).
   - **#244** — a correction supersedes only the best-ranked conflicting
     inference; the rest stay live, because a *destructive* overwrite is only safe
     to do once (ADR-0038 §4).
   - **#245** — two contradictory user assertions both stay live, because no
     conflict heuristic is confident enough to *destroy* one the user gave us
     (ADR-0038 §5).
   - and the audit-trail loss of ADR-0038 §1a.

3. **`Provenance.last_updated` conflates two clocks.** It is described as "when
   this belief was last revised," which is *transaction time* — when the system
   changed its mind — and says nothing about *when the belief holds*. There is no
   field for the latter.

4. **`export` is a data-rights obligation, and today it hides history.** ADR-0007
   §3 defines `export` as "all live (non-expired) records." Once a superseded
   belief is retained rather than overwritten, the user is entitled to it in an
   export — it is data we hold — but the current definition would exclude it.

5. **The write becomes two writes, and `MemoryStore` cannot make two writes
   atomic.** Today's supersession is a single upsert. Closing a window *and*
   writing a new record is two store writes; a failure between them retires a live
   belief and never replaces it. `MemoryStore` has no batch or transaction (issue
   #104). Whether #112 may proceed without #104 is a decision this ADR must make
   rather than assume (§8).

The forces against are real. `MemoryRecord` is a `core` type with construction
sites across `memory`, `learning`, `orchestration`, the two canonical fakes, and
every test; adding an envelope field reaches all of them. Full bi-temporality —
two independent axes plus as-of queries on each — is a large surface, and #112's
own open questions flag most of it as deferrable. This ADR adopts the minimum
that discharges the five forces and stages the rest.

## Decision

### 1. One enforced validity window now; full bi-temporality is staged

Snodgrass's two axes are **valid time** (when the fact is true in the modelled
world) and **transaction time** (when the system held the belief; a
transaction-time store is append-only and "deletes" only by closing the
transaction end — which *is* "invalidate, don't delete"). Every in-scope
defect — #254, #244, #245, #256's residue, ADR-0038 §1a — needs exactly one
thing: a non-destructive way to take a belief off the read path while keeping it
on disk. That is **one** window, not two.

We will therefore adopt a **single validity window** on the record, enforced at
read time, and **defer** the second axis and as-of retrieval:

- The window is **valid-time-shaped**: it answers "is this the live belief now?",
  which is what a reader means by live and what Graphiti closes on contradiction.
- **Transaction time as a second, independent axis** (a `recorded_at`/`retired_at`
  pair distinct from the valid window, enabling "what did I believe on date X")
  is **not** added here. `Provenance.last_updated` continues to serve as the
  coarse transaction-time stamp (§3), and the full second axis is filed for when
  a consumer needs bi-axis history (§10).
- **As-of queries** (issue #112 OQ1) are **deferred** (§10): reads answer "true
  now," not "true as of T". Adding an `as_of` parameter to `get`/`search` is a
  `MemoryStore` surface increase with no in-scope consumer.

Naming this "bi-temporal" and shipping one axis is deliberate and honest: the
*mechanism* "invalidate, don't delete" is a single-axis capability, and building
the second axis before a query needs it is surface without a consumer — the same
discipline ADR-0028 §7 applied to batch ingestion and ADR-0040 §4 to rule 5.

### 2. A `Validity` window on `MemoryBase`, defaulting to open

`core/types.py` gains a small value object and a field on the shared envelope:

```python
class Validity(BaseModel):
    """The interval during which a record is the system's live belief.

    ``valid_from``/``valid_until`` are half-open [from, until). ``None`` at either
    end means unbounded: a record with a fully-open window (the default) is live
    forever until something retires it.
    """

    valid_from: UtcInstant | None = None
    valid_until: UtcInstant | None = None
    # validator: if both set, valid_until > valid_from.
```

`MemoryBase` gains `validity: Validity = Field(default_factory=Validity)`.

**A record is *live at* an instant `now`** iff
`(validity.valid_from is None or validity.valid_from <= now)` **and**
`(validity.valid_until is None or now < validity.valid_until)`.

Two properties make this the low-blast-radius choice:

- **The default is open, so nothing existing changes.** Every record constructed
  today, and every `ACCEPT`, gets `Validity()` — live forever — so present
  behaviour is preserved and the SQLite migration backfills the absent column as
  "open" (§9). Retirement is the only thing that ever sets `valid_until`.
- **It mirrors `expires_at` exactly.** Both are read-time lifecycle filters the
  store enforces; the read predicate `valid_until IS NULL OR valid_until > now`
  is the same shape as ADR-0007's expiry predicate, which is why §6's read changes
  are small.

**On the envelope, not on `Provenance`** (issue #112 OQ5). The window is a
lifecycle property of *the record's life in the store*, set operationally by the
applier, and it belongs beside `expires_at` — the other read-time filter — so all
read predicates live in one place and the SQLite column sits next to
`expires_at`. `Provenance` stays about *trust and source*; `last_updated` stays
there as the belief-revision stamp (§3). Putting a store-set lifecycle field on
`Provenance`, whose every other field is set by the *producer* of the belief,
would mix two authorships.

`SemanticMemory.valid_until` already exists (ADR-0005 §1) as a *per-kind,
content-declared* world-expiry — "the author says this fact self-expires on date
X". That is a different thing from the envelope window, which is *uniform* and set
*operationally* by supersession. This ADR does not merge them; reconciling the two
`valid_until` notions is filed (§10) so the overlap is acknowledged rather than
left to surprise an implementer.

### 3. `last_updated` is clarified as transaction time; it is not split

`Provenance.last_updated`'s docstring is clarified to read as *transaction time* —
when the system last revised this belief — explicitly **not** the valid window.
No field is added or split: the full transaction-time axis (§1) is deferred, and
`last_updated` already carries the coarse "when we last touched it" signal. This
is a docstring change on a `core` type, called out because the type crosses
boundaries, but it renames nothing and changes no value.

### 4. `SUPERSEDE` closes a window and writes a new record; `REINFORCE` is untouched

This is the mechanism change ADR-0040 §6 named. It lives entirely in the
*applier* (`MemoryIngestor._apply` and `_supersede`, and the canonical
`FakeMemoryWriter`); the `SUPERSEDE` member, `MemoryDecision`, the policy and the
`MemoryPolicy` suite do not move, exactly as ADR-0040 §6 promised.

Applying `SUPERSEDE(target_id=T)` for a proposed record `P`:

1. **Close `T`'s window.** Write `T` back with `validity.valid_until = now`,
   where `now` is the ingestor's injected clock (ADR-0026). `T` stays on disk with
   a closed window — retained, off the read path.
2. **Write `P` as a *new* record, at a freshly-minted unique id**, with a fresh
   open window. `P` carries nothing of `T` (ADR-0038 §1a is unchanged — a
   correction does not inherit the overturned belief's evidence), and it no
   longer borrows `T`'s id. The id is also **not sourced from** `P.id`:
   `MemoryRecord.id` is caller-supplied and `MemoryStore.add` is a caller-id upsert
   (a record whose id already exists is overwritten), so writing at `P.id` could
   silently clobber an unrelated live record that happens to share it. The applier
   therefore mints its own id from an **injected id factory** (mirroring the
   injected clock and ADR-0022 §5's goal-id factory — deterministic in tests) and
   discards `P.id`, exactly as today's supersession discards it when it rehomes
   `P` onto `T`'s id.
   **The one id requirement is "names no existing record," enforced not assumed.**
   The record that must not be clobbered is any *stored* one — the retained target
   `T` included, and any unrelated `U` — so the sole obligation is that the minted
   id is **absent from the store**. (Whether it happens to equal the discarded,
   *unstored* `P.id` is immaterial: no record lives there to overwrite. There is
   no separate "must differ from `P.id`" rule — the earlier hazard was `P.id`
   naming an *existing* record, which the absence check already covers.) A
   probabilistic generator (`uuid4`) makes a collision unlikely, not impossible,
   so the new record is written with **insert-if-absent** semantics under the
   atomic primitive (§8), *not* a blind upsert: a minted id that already exists is
   rejected and the applier mints again, rather than overwriting the colliding
   record. **Retry is bounded.** After a small fixed number of attempts the
   applier raises `MemoryStoreError`; because the whole `SUPERSEDE` is atomic
   (§8), that abort rolls back the window-close too, so a pathological id factory
   fails loudly with the **target left live and unchanged** rather than hanging or
   half-applying. The injected factory is **guarded at its
   output**, exactly as ADR-0026's `checked_clock` guards the injected clock: its
   result is validated to be a non-empty `str` and its raising is caught, both
   re-raised as `MemoryStoreError` **before** the atomic write. This is
   load-bearing for the same reason ADR-0026 §2 gives for the clock — the applier
   installs the id via `model_copy(update=...)`, which skips validators, so a
   `None` or non-`str` reading would otherwise reach the store unchecked and the
   two writers would diverge (the in-memory fake storing under a bad key while
   SQLite rejects it, the exact "consumer test passes on state the production
   writer refuses" trap `FakeMemoryWriter` names). Which factory mints the id is
   `memory`'s own semantics (like the fold rule, ADR-0028 §8); the *obligation*
   the contract pins is only that the id is absent-and-fresh, or the write fails
   as `MemoryStoreError` with no state change (§5).
3. **Return the new record's id.** `MemoryIngestResult.record_id` is the id of the
   **live** record, which is now `P`'s new id, not `T`'s — "MemoryIngestResult
   carries a different id than it does today" (ADR-0040 §6).

`REINFORCE` is **unchanged**: reinforcement means the two records agree, so it
keeps folding into one live record at the target's id, evidence unioned (ADR-0040
§5a). No window is closed, no second record is written. Only `SUPERSEDE` gains the
close-and-write shape, which bounds the blast radius of this ADR to one arm — and,
because `REINFORCE` still inherits the *target's* id, is exactly why the
`EXTERNAL` refusal can only be lifted for `SUPERSEDE` and must stay for
`REINFORCE` (§5).

Steps 1 and 2 are two writes and **must be atomic** (§8).

### 5. The two `MemoryWriter` conformance rewrites, stated precisely; clause 1 stays

ADR-0040 §6 named exactly two clauses a validity window rewrites, both in the
`MemoryWriter` conformance suite. This ADR makes them.

**§5a's id clause is rewritten.** Its current obligation:

> After a `SUPERSEDE`, the live record is the proposed record ... borrowing from
> the target only the id it is written at.

becomes:

> After a `SUPERSEDE`, the target is **retained with a closed validity window**
> (`valid_until` set, live-at-now false) and the live record is the proposed
> record written **at an id absent from the store** (so it overwrites no existing
> record — the retained target included), carrying nothing of the target.
> `MemoryIngestResult.record_id` is the **live record's** id, not the target's.
> The target remains fetchable by `export` and, being window-closed, is absent
> from `get`/`search`.

The conformance suite adds four cases, all driving the injected id factory
deterministically and asserting the `SUPERSEDE` overwrites **no** existing record
and returns a live-record id equal to neither the target nor any collided-with
record: (a) the proposal's own `id` already names a **live, non-target** record;
(b) the **minted** id collides with an existing record on the first attempt —
the applier mints again (insert-if-absent, not upsert) and succeeds; (c) an
**always-colliding** factory — the applier raises `MemoryStoreError` after its
bounded retries, and by §8's atomicity the target is left **live and unchanged**;
and (d) a factory that **raises** or returns a **non-`str`/empty** id — the
applier raises `MemoryStoreError` (not the factory's own exception) with no state
change, so the two writers cannot diverge on a malformed factory. The absent-id
obligation is what forbids the collisions; the bound forbids the hang; the output
guard forbids the divergence.

The differential ADR-0040 §5a ratified — **`SUPERSEDE` carries nothing of the
target onto the surviving record** — is unchanged and still complete; only "at
the target's id" becomes "at a new id, target retained". `REINFORCE`'s
"retains both records' evidence" obligation is untouched.

**§5b's `EXTERNAL` clause narrows to `REINFORCE`-only; it is not removed.** Its
current obligation refuses a `USER_ASSERTED` proposal folded onto an `EXTERNAL`
target, for **either** ruling, because ADR-0040 §3 keyed the refusal on the
records — every fold overwrote the target's id, so the relation did not matter.
§4 breaks exactly that premise: **only `SUPERSEDE` gets the new id;** `REINFORCE`
still folds at the *target's* id (§4). So the refusal must split by relation:

- For **`SUPERSEDE`**, the refusal is **lifted** — §4 gives the correction a new
  id, the idempotency-key hazard (ADR-0038 §2a, ADR-0040 §5b: "it rests entirely
  on the target's id being inherited") is gone, and an `EXTERNAL` supersession
  becomes safe and permitted at the writer boundary (§7).
- For **`REINFORCE`**, the refusal **stays** — a `USER_ASSERTED` proposal
  reinforcing an `EXTERNAL` target still folds at the external id, still inherits
  the integrating system's idempotency key, and is still overwritten by the next
  routine sync. This is the exact data-loss ADR-0038 §2a and ADR-0040 §5b exist to
  prevent, and the window does nothing for it, so removing the refusal here would
  reopen it.

Concretely, `_refuse_unsafe_fold`'s `EXTERNAL` arm in `memory/ingest.py` and the
`EXTERNAL` obligation in the `MemoryWriter` conformance suite become **gated on the
ruling**: refuse a `USER_ASSERTED`→`EXTERNAL` `REINFORCE`, permit the same
`SUPERSEDE`. This makes *that clause* relation-aware, which is a deliberate
amendment to ADR-0040 §3's "keyed on the records, not the relation" shape — sound
now precisely because §4 makes the two folds do different things to the id, which
was not true when §3 was written. Clause 1 (below) stays record-keyed.

**The shipped policy's `_SUPERSEDABLE` set is deliberately *not* widened here.**
`DefaultMemoryPolicy` keeps `{OBSERVED, INFERRED}` in `memory/policy.py`, so it
continues to `ACCEPT` a correction *beside* an `EXTERNAL` conflict rather than rule
`SUPERSEDE` over it — `DefaultMemoryPolicy` is untouched, and ADR-0040 §6's "the
policy survives untouched" holds verbatim. What this ADR changes is only the
*floor*: the writer boundary no longer forbids an `EXTERNAL` supersession, so a
policy that chooses to rule one is now safe (the correction gets a new id, §4).
Adopting that in the default policy is a policy-lane decision, filed with #244 and
#245 as the third "unblocked, not taken here" (§7). These amend two ratified
decisions — ADR-0040 §3 and §5b (the ingestor refusal and its conformance clause,
narrowed to `REINFORCE`-only, not deleted) and ADR-0038 §2a's ingestor-enforced
half — each of which its own author named a validity window as revisiting; their
append-only amendment forms are in the header and §Consequences.

**Clause 1 stays.** `_refuse_unsafe_fold`'s *first* refusal — **no fold of any
kind onto a `USER_ASSERTED` target** — is **not** rewritten by this ADR, and this
is a deliberate departure from a naive reading of "the window makes supersession
safe". The refusal had two justifications, and the window dissolves only one:

- *Destructiveness* — "the write replaces what the user told us". The window
  dissolves this: a window-closing `SUPERSEDE` keeps the target on disk.
- *Signal strength* — ADR-0038 §5 / §2: the conflict signal is topical
  similarity (a 0.75 lexical or embedding score), **not** contradiction, and is
  too weak to authorise retiring a record the user gave us. This survives the
  window entirely: non-destructive is not the same as *warranted*.

Because the second justification stands, clause 1 remains an obligation on every
writer for **both** rulings, and this ADR does **not** let a heuristic retire an
assertion. ADR-0040 §6 named two `MemoryWriter` clauses a window revisits, and this
ADR touches exactly those two: §5a's id clause is rewritten, and §5b's `EXTERNAL`
clause is narrowed to `REINFORCE`-only (lifted for `SUPERSEDE`). Clause 1 is left
in force, record-keyed, for both rulings. What the window unblocks for assertions
is filed as policy-lane work, not taken here (§7, #245).

### 6. Read semantics: `get`/`search` hide closed windows; `export` keeps them

The `MemoryStore` Protocol contract and its conformance suite change as follows.

- **`get`** returns `None` for a record that is absent, expired, **or not live at
  now** — where "not live" is the *full* §2 predicate, **both** ends: a closed
  `valid_until` (`valid_until <= now`) **and** a not-yet-open `valid_from`
  (`valid_from > now`).
- **`search`** never returns a non-live record, exactly as it never returns an
  expired one, again on both ends of the window. The over-fetch-and-post-filter
  caveat ADR-0007 §Consequences records for expiry applies identically.
- **The `valid_from` end is enforced, not assumed away.** This ADR's own
  mechanisms never set `valid_from` to the future (retirement sets `valid_until`;
  new records get an open window), but a producer *may*, and the store must honour
  the contract regardless. `valid_from` is therefore filtered like `kinds` already
  are — in the post-filter step, not the SQL pre-filter (§9) — and the conformance
  suite carries before/at/after-boundary cases for **each** end of the window, not
  only "closed" and "fully open".
- **`export`** returns **every retained (non-expired) record, whether its window
  is open or closed.** This is the amendment to ADR-0007 §3 (issue #112 OQ3): a
  superseded belief is data the store holds, so a data-rights export must include
  it. Only *expired* records (past `expires_at`, a retention/privacy deadline) are
  excluded — retention still wins over history, because a record the system
  promised to forget must not resurface through export.

The two axes are orthogonal and both are honoured: **`expires_at` is retention**
(a privacy deadline; an expired record is gone from *everything*, including
`export`), **the validity window is truth** (a closed-window record is off the
read path but present in `export`). A record can be retained-but-retired, or
still-live-but-expired; the store treats each axis on its own terms.

The `MemoryStore` class docstring gains the window rule beside the expiry rule.
The shared `MemoryStoreContract` suite gains obligations: a window-closed record
is absent from `get`/`search` and present in `export`; a fully-open record behaves
as today. No new *method* is added to the Protocol — retirement is performed by
the writer via `add` (upsert) under an atomic primitive (§8), not by a new store
verb, and as-of retrieval is deferred (§1).

### 7. How #254, #244, #245 resolve under the window

- **#254 (correction vs `EXTERNAL`) — its blocker dissolved here; adoption
  deferred, like #244/#245.** #254 was not "the default policy should supersede
  `EXTERNAL`"; it was "it *cannot*, because superseding inherits the target's
  idempotency key and the next re-sync overwrites the correction — so `EXTERNAL`
  had to be excluded." §4 removes the ground: a superseding correction is written
  at a **fresh id**, so the re-sync's upsert of the external id can no longer touch
  it, and §5 lifts the writer-boundary refusal that held the exclusion shut. An
  `EXTERNAL` supersession is therefore now **safe and permitted**, and a policy
  that rules one leaves the correction surviving unconditionally — which
  `tests/memory/test_ingest.py::test_a_correction_survives_the_next_external_re_sync`
  is retargeted to assert (from "the exclusion holds" to "the new id survives the
  re-sync").

  Two honest limits keep this from being "#254 closed". First, **the shipped
  default policy does not yet adopt it** (§5): with `_SUPERSEDABLE` unchanged it
  still `ACCEPT`s the correction *beside* the `EXTERNAL` record, so both stay live —
  the #38 "stale belief stays live" shape, not the silent-destruction #254 is
  about. Whether the default policy should now rule `SUPERSEDE` over an `EXTERNAL`
  conflict is a policy-lane choice this ADR makes safe, filed alongside #244 and
  #245. Second, even for a policy that adopts it, **the re-synced external record
  is not guaranteed to stay retired**: conflict detection is similarity, not
  identity (ADR-0038 §2), and the score is asymmetric — a correction shorter than
  the record it corrected can be *found* when superseding yet *missed* on the
  reverse query, so the re-sync may see no conflict, `ACCEPT`, and make the stale
  external belief live again **alongside** the surviving correction. That is again
  the two-live-records shape, not destruction — no user data is lost — and closing
  it needs an identity-/tombstone-aware re-sync rule (a superseded external id must
  not silently resurrect), a property of conflict detection, not of the window.
  This ADR removes the destruction hazard and **files both residuals** (§10)
  rather than claiming #254 closed.

- **#244 (only the best-ranked inference superseded) — unblocked, downgraded out
  of `core`.** ADR-0038 §4 limited supersession to one target because a
  destructive overwrite is only safe to do once. A window close is
  non-destructive and idempotent, so that safety reason dissolves. This ADR does
  **not** grow `target_id` to a list: closing N windows is now cheap and reversible
  in history, so whether a correction retires several conflicting inferences
  becomes a *policy-lane* choice (emit N proposals, or a later, safe `target_ids`
  widening), no longer a `core` blocker. #244 stops needing `target_id` to grow —
  exactly ADR-0040 §6's phrasing — and moves to the policy lane.

- **#245 (two contradictory assertions both live) — unblocked, still deferred.**
  The window supplies the missing piece: a later assertion *could* close the
  earlier contradictory assertion's window, keeping the earlier one on disk and in
  `export`, so the "unrecoverable loss" objection of ADR-0038 §5 is gone. But two
  things remain, and both are out of this ADR's scope: the *signal-strength*
  objection (§5, clause 1) survives the window — topical similarity still cannot
  authorise retiring an assertion — and doing it would require narrowing clause 1
  for the assertion-supersedes-assertion case, which is a policy-and-refusal change
  gated on a real contradiction signal (or explicit user confirmation), not on
  this ADR's mechanism. #245 therefore moves from "architecturally blocked" to "a
  decidable policy-lane question", and this ADR consciously does not answer it.

The line ADR-0040 §6 drew holds: all three are about *what happens to the record*,
and the window is what lets them be answered — one here, two unblocked for the
policy lane.

### 8. Ruling: #104 is a hard prerequisite for the supersession applier

§4 makes `SUPERSEDE` two writes — close the target's window, write the new
record — where today it is one upsert. A failure between them leaves the target
retired and no live replacement: the belief vanishes from reads, a **regression**
from today's atomic single-upsert supersession. `MemoryIngestor`'s lock (issue
#248) serialises ingests *within one process* but does not make two `store.add`
calls atomic against a store failure or crash between them; that needs an atomic
multi-write primitive **on the store**, which is exactly issue #104's scope
(ADR-0028 §7: "atomicity has to come from the store").

We rule, rather than assume: **the window-closing `SUPERSEDE` applier requires
#104 first.** Splitting the dependency by what actually needs it:

- The **type and read-filtering** work (the `Validity` field, `get`/`search`/`export`
  filtering, the SQLite migration) is independent of #104 and may land first — it
  changes no write to two writes.
- The **`SUPERSEDE` applier** (§4) may **not** land until `MemoryStore` can apply
  the window-close and the new-record write atomically. Doing it as two bare
  `add`s would ship the regression above under the cover of a feature.

So the implementation sequence is: #104 gives `MemoryStore` an atomic batch/
transaction; then #112's applier uses it. Two properties the applier needs from
that primitive, stated as consumer requirements rather than as its design: it must
apply the window-close and the new-record write **atomically** (a failure between
them must not commit the retirement), and it must support an **insert-if-absent**
write for the new record (§4) — a blind upsert cannot honour the fresh-id
obligation, since a minted id that collided would silently clobber the colliding
record. This ADR does **not** design the primitive — it belongs to #104's lane and
Protocol change — it only fixes what #112's applier consumes and that it must not
precede it. Stated so a later lane cannot silently implement the applier over a
non-atomic pair of blind upserts.

### 9. Schema migration is needed and is mechanical (OQ4)

`SqliteMemoryStore` stores each record as a JSON `data` blob plus an `expires_at
REAL` column, and already carries a `_migrate_records` that `ALTER TABLE ADD
COLUMN`s and backfills within the setup commit (the `expires_at` migration is the
template). The window migration mirrors it: add a `valid_until REAL` column,
default `NULL` (= open = live), which correctly leaves every existing row live.
`valid_until` is the **hot** end — retirement is the common operation, so it earns
a column and a SQL pre-filter: the predicate becomes
`(expires_at IS NULL OR expires_at > now) AND (valid_until IS NULL OR valid_until > now)`.
`valid_from` rides in the JSON blob and is applied in the **post-filter**, in the
same pass that already drops kind- and expiry-filtered rows (`_search_sync`), and
in the `get` decode path — because future-dated `valid_from` is rare (no in-scope
writer produces it) and does not justify a second indexed column. What is **not**
optional is that both ends are enforced somewhere on every read (§6); the split is
only *where*. Issue #112 OQ4 is answered: yes, a migration is required, and the
existing `expires_at` pattern covers it with no new machinery.

### 10. What this ADR does not decide

- **As-of queries** (OQ1). Reads answer "live now". An `as_of` parameter on
  `get`/`search` is a Protocol surface increase with no in-scope consumer; filed
  for when temporal retrieval ("what did I believe on date X") has a caller.
- **The full transaction-time axis** (§1). A `recorded_at`/`retired_at` pair
  independent of the valid window, enabling bi-axis as-of history, is the second
  half of true bi-temporality and is deferred with as-of, since no in-scope defect
  needs it.
- **Reconciling `SemanticMemory.valid_until` with the envelope window** (§2). The
  per-kind content-declared world-expiry and the uniform operational window
  overlap in name; whether they merge is filed, not answered.
- **#245's policy behaviour and any narrowing of `_refuse_unsafe_fold` clause 1**
  (§5, §7). Unblocked by the window, decided in the policy lane on a contradiction
  signal, not here.
- **#244's multi-target supersession** (§7). Unblocked, a policy-lane choice, no
  `core` growth.
- **Whether `DefaultMemoryPolicy` adopts `EXTERNAL` supersession** (§5, §7). The
  writer floor is lifted so it is safe; the shipped policy's `_SUPERSEDABLE` is
  untouched (ADR-0040 §6), and opting in is a policy-lane choice filed with #254.
- **Identity-aware re-sync so a superseded `EXTERNAL` record does not resurrect**
  (§7, #254 residual). The window stops the correction being destroyed but does
  not, on its own, keep a re-synced external record retired when similarity misses
  the correction. Filed as a conflict-detection / tombstone question, distinct
  from the destruction bug this ADR closes.
- **`MemoryStore`'s atomic primitive** (§8). Issue #104's lane designs it.
- **The lost-update window** in `MemoryIngestor.ingest` (issue #248). Orthogonal;
  #104 closes it alongside the atomicity primitive this ADR depends on.

## Consequences

- **The memory model stops overwriting.** ADR-0038 §1a's discarded evidence, the
  overturned belief's text, and both sides of a contradiction are now kept on disk
  with exactly one live — "the first thing #112 should give back" (ADR-0038 §6),
  given back.
- **This is a breaking `core` change**, flagged per golden rule 5. `MemoryBase`
  gains a field (additive, defaulted, so no construction site breaks) but
  `MemoryStore.export`'s *behaviour* changes — it now returns window-closed
  records — which breaks any caller assuming `export` is the live-belief set. The
  read-time filter on `get`/`search` also changes what they return.
- **The implementation owes**, across the lanes §Contract-change and §8 separate:
  - `core/types.py` — a new `Validity` model (`valid_from`, `valid_until`,
    `valid_until > valid_from` validator); `MemoryBase.validity: Validity` with an
    open default; `Provenance.last_updated`'s docstring clarified as transaction
    time; `MemoryIngestResult.record_id`'s docstring updated (SUPERSEDE returns
    the new live id). `MemoryDecisionKind`, `MemoryDecision`, `MemoryUpdateProposal`
    are **untouched** (ADR-0040 §6).
  - `core/protocols.py` — `MemoryStore.get`/`search`/`export` docstrings and the
    class docstring updated for the window; **no new method**; `MemoryWriter.ingest`
    unchanged in signature.
  - `memory/store.py`, `memory/sqlite_store.py` — read-time window filtering;
    `export` returns closed-window records; the SQLite `valid_until` migration (§9).
  - `memory/ingest.py` — `_supersede`/`_apply` rewritten to close the target's
    window and write a new-id record via an **injected id factory**, using the
    insert-if-absent primitive (§4); `_refuse_unsafe_fold`'s `EXTERNAL` arm gated on
    the **ruling** — refuse `USER_ASSERTED`→`EXTERNAL` under `REINFORCE`, permit it
    under `SUPERSEDE` (the arm receives the decision kind; clause 1 stays
    record-keyed for both); **clause 1 kept** (§5). `MemoryIngestor` gains the id
    factory alongside its existing injected clock. Requires #104 (§8).
  - `memory/policy.py` — **unchanged.** `DefaultMemoryPolicy`'s `_SUPERSEDABLE`
    stays `{OBSERVED, INFERRED}` (ADR-0040 §6); adopting `EXTERNAL` supersession is
    a policy-lane follow-up (§5, §7), not this ADR's change.
  - `testing/writer.py`, `testing/store.py` — `FakeMemoryWriter` grows the new
    supersession shape; the fake store grows window filtering.
  - conformance suites — `MemoryStoreContract` gains the window read obligations
    (§6); `MemoryWriterContract` rewrites §5a's id clause and **narrows** §5b's
    `EXTERNAL` clause to `REINFORCE` (a `USER_ASSERTED`→`EXTERNAL` `REINFORCE` still
    raises; the same `SUPERSEDE` is now permitted and asserted to write a new-id
    correction) (§5).
- **`export` amendment (ADR-0007 §3).** On ratification, ADR-0007 §3's "live
  (non-expired)" is annotated: `export` returns every *retained* record regardless
  of validity window; only expired records are excluded. ADR-0007's other rulings
  stand.
- **`MemoryWriter` amendment (ADR-0040 §5a, §5b; ADR-0028 §8).** On ratification,
  ADR-0040 §5a's id clause is annotated rewritten (target retained + closed
  window, new live id returned) and §5b's `EXTERNAL` clause annotated **narrowed to
  `REINFORCE`** (a `USER_ASSERTED`→`EXTERNAL` `REINFORCE` still refuses; the same
  `SUPERSEDE` is permitted); ADR-0028 §8's conformance list records both. ADR-0040's
  members, `MemoryDecision` and the `MemoryPolicy` suite are confirmed untouched —
  if any of them had to move, ADR-0040 §1's naming rule was wrong; it was not.
- **`EXTERNAL`-refusal amendment (ADR-0040 §3; ADR-0038 §2a) — the writer floor
  only, and only for `SUPERSEDE`.** On ratification, ADR-0040 §3 is annotated on two
  points: "refusals do not move" narrows to **clause 1** (no fold onto a
  `USER_ASSERTED` target, which stays put for both rulings), and "keyed on the
  records, not the relation" gains an exception for the `EXTERNAL` arm, which
  becomes **`REINFORCE`-only** — sound now because §4 makes `SUPERSEDE` and
  `REINFORCE` do different things to the target's id, which was not true when §3 was
  written. ADR-0038 §2a's **ingestor-enforced** `EXTERNAL` refusal is annotated
  lifted **for `SUPERSEDE` only** — `_refuse_unsafe_fold`'s `EXTERNAL` arm receives
  the ruling and permits an `EXTERNAL` `SUPERSEDE` while still refusing an
  `EXTERNAL` `REINFORCE` — because only supersession stops inheriting the target's
  id (§4), the *sole* ground ADR-0038 §2a gave for the refusal and the one ADR-0038
  §6 foresaw a window removing. **`DefaultMemoryPolicy`'s own `_SUPERSEDABLE` is not
  touched** (ADR-0040 §6 stands), so §2a's *policy-side* exclusion persists until a
  policy lane adopts it; §2a's `USER_ASSERTED`-target refusal (clause 1) and every
  other ADR-0038 and ADR-0040 ruling stand unchanged.
- **Issue #112's open questions close**: OQ2 was already ADR-0040's; OQ3 (export)
  §6; OQ4 (migration) §9; OQ5 (placement) §2. OQ1 (as-of) is deferred (§10).
- **#254's blocker dissolves** with the implementation (the writer floor is lifted
  and a superseding correction is no longer overwritable, §4–§5); its default-policy
  *adoption* and its resurrection residual are re-filed to the policy and
  conflict-detection lanes (§7, §10). **#244 and #245** are likewise retargeted to
  the policy lane (§7); **#104** becomes a hard predecessor of the applier lane (§8).
- **Two `valid_until` notions coexist** until the reconciliation (§10) — a known,
  filed overlap, the cost of not conflating a content-declared expiry with an
  operational window in one change.
- **Revisit if** a consumer needs as-of retrieval or the full transaction-time
  axis (§1, §10), if the two `valid_until` fields prove confusing in practice
  (§2), or if #104's atomic primitive lands in a shape the applier cannot use
  as §8 assumes.

## Alternatives considered

- **Full bi-temporality now — two independent axes plus as-of queries.** Rejected
  in §1. Every in-scope defect needs one non-destructive window; the second axis
  and as-of retrieval are surface with no consumer, and #112's own open questions
  flag them as deferrable. Building both would be the over-reach ADR-0028 §7 and
  ADR-0040 §4 each declined in their own lane.
- **Keep destructive `SUPERSEDE`, add a separate invalidation `MemoryDecisionKind`.**
  Rejected: ADR-0040 already settled the ruling layer — `SUPERSEDE` names the
  relation, and #112 changes only how the applier executes it (ADR-0040 §6). A new
  kind would re-open a question ADR-0040 closed and split one relation across two
  members.
- **The window on `Provenance` rather than `MemoryBase`** (OQ5's other horn).
  Rejected in §2: the window is a store-set lifecycle filter, kin to `expires_at`,
  and mixing it into `Provenance` — every other field of which the *producer*
  sets — would blur two authorships and scatter the read predicates.
- **Reuse `SemanticMemory.valid_until` instead of a uniform envelope window.**
  Rejected in §2: it is per-kind (only semantic records have it) and
  content-declared (the author asserts a self-expiry), whereas invalidation is
  uniform across kinds and set operationally by supersession. It cannot carry the
  window for episodic, preference, or procedural records at all.
- **Lift `_refuse_unsafe_fold` clause 1 because the window makes supersession
  non-destructive.** Rejected in §5: the refusal has a second, independent
  justification — the conflict signal is topical similarity, not contradiction,
  too weak to retire a record the user gave us — which the window does not touch.
  Non-destructive is not warranted. This would also exceed the two clauses ADR-0040
  §6 scoped to #112.
- **Grow `MemoryDecision.target_id` to a list to resolve #244 here.** Rejected in
  §7: a `core` widening for a case the window downgrades to a non-destructive,
  policy-lane choice. Closing N windows needs no contract growth.
- **Implement the applier over two bare `add`s and accept partial failure.**
  Rejected in §8: it ships a regression from today's atomic single-upsert
  supersession — a retired belief with no live replacement — under the cover of a
  feature. Atomicity has to come from the store (ADR-0028 §7); #104 is the
  prerequisite, not an optimisation.
- **Widen `DefaultMemoryPolicy`'s `_SUPERSEDABLE` to include `EXTERNAL` here,
  amending ADR-0040 §6.** Rejected in §5, §7. It would resolve #254 in the shipped
  policy in one move, but it changes `DefaultMemoryPolicy`'s *behaviour* — a
  policy-lane decision — inside a temporal-model contract ADR, and it would force
  an amendment to ADR-0040 §6's "the policy survives untouched", which this ADR
  otherwise honours verbatim. Lifting only the *writer floor* (the ingestor refusal
  and its conformance clause, which ADR-0040 §5b/§3 and ADR-0038 §2a's ingestor
  half all named a window as revisiting) makes an `EXTERNAL` supersession *safe*
  without deciding that the default policy *takes* it — the same "unblock the
  mechanism, defer the policy" treatment #244 and #245 get. The default policy's
  adoption is then one uniform policy-lane question, not a behavioural change
  smuggled in here.
- **Mint the new supersession id with a bare `uuid4` and a blind `add` upsert.**
  Rejected in §4: `uuid4` makes a collision unlikely, not impossible, and `add` is
  an unconditional upsert, so the fresh-id obligation — distinct from *every*
  existing id — would be probabilistic rather than enforced, and a collision would
  silently clobber an unrelated record. An injected id factory plus insert-if-absent
  under the atomic primitive makes the obligation exact and testable, at no extra
  Protocol surface beyond the atomicity #104 already owes (§8).
- **Redefine `expires_at` to double as the validity window.** Rejected in §6 and
  per issue #112 explicitly: `expires_at` is a retention/privacy deadline (an
  expired record is gone from *everything*, including `export`), the window is a
  truth axis (a retired record stays in `export`). Conflating them would either
  leak forgotten data into reads or drop retained history from a data-rights
  export.
