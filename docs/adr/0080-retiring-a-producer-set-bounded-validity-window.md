# 80. Retiring a producer-set bounded validity window clamps, and refuses only what it cannot represent

- Status: Proposed
- Date: 2026-07-28
- **This ADR partially supersedes [ADR-0045](0045-memory-records-carry-a-validity-window.md)**,
  in the scope named in §8: **§4 step 1's window-close instruction** (the
  numbered step headed *Close `T`'s window*, whose sentence is "Write `T` back
  with `validity.valid_until = now`, where `now` is the ingestor's injected clock
  (ADR-0026)"). Everything else ADR-0045 decided stands and is untouched: §1's
  single-axis staging, §2's `Validity` value object, its liveness predicate and
  its placement on `MemoryBase`, §3, §4's steps 2 and 3 (the fresh-id correction
  with a fresh open window, and the returned live id), §5 in whole (both
  conformance rewrites and the standing clause 1), **all of §6** (the read-time
  semantics, including that `valid_from` is enforced and that a producer *may*
  set it), §7, §8's atomicity floor, §9's migration, and §10's deferrals.
  ADR-0045's Status line records the supersession per ADR-0070 §4 and a dated
  note is appended; **no ratified body text of ADR-0045 is rewritten** (ADR-0070
  §1). **Both files land in one change**, so ADR-0045's Status never points at an
  ADR that is absent — the hazard ADR-0070 §1 guards against is unreachable when
  the pair is atomic, and `main` already carries the precedent three times over
  (ADR-0005 carried `Partially superseded by ADR-0075` while ADR-0075 was still
  `Proposed`, which ADR-0076's header records; ADR-0074/ADR-0076 and
  ADR-0050/ADR-0079 are the same pair shape). The `Proposed` → `Accepted` flip is
  the ratifying edit at merge (ADR-0015 §5; `CONTRIBUTING.md`, "Trivial ADR
  edits").
- **This is a contract change** (golden rule 5), and a narrow one. It adds **no
  Protocol**, **no `core/types.py` type**, **no `core/errors.py` class**, and no
  method or parameter anywhere. It changes one Protocol's *documented semantics*
  — `MemoryWriter.ingest` in `core/protocols.py` gains one clause on the
  `SUPERSEDE` obligation and one raise clause (§7) — and it promotes two
  behaviours from applier internals into the **shared `MemoryWriter` conformance
  suite and the canonical `FakeMemoryWriter`** (§7). It therefore ships as **its
  own docs-only PR**, reviewed while still `Proposed` so a finding can still
  change the decision, and is flipped to `Accepted` on merge (`CONTRIBUTING.md`,
  "Contract ADRs land before their implementation"). **No code changes with it**;
  the docstring, the three suite obligations and the fake are the next lane (§7).
- **Refs:** issue #306 (the question decided, minus the half split out as #460);
  ADR-0045 §2 (the `Validity` window and the liveness predicate), §4 (the
  window-closing supersession this ADR completes), §5 (clause 1 and the
  `EXTERNAL` narrowing), §6 (read-time liveness; `valid_from` enforced, not
  assumed away; `export` keeps a closed window), §8 (the atomicity floor), §9
  (`valid_until` is the SQL pre-filter column, `valid_from` rides the JSON blob),
  §10 (the deferrals this ADR leaves standing); ADR-0079 §1 (the resolve-or-refuse
  law and its ceiling refusal), §2 (the ordering and what ADR-0078 inherits), §3
  (full-set retirement as a universal `MemoryWriter` obligation), §4 (the surface
  form and the suite obligations), §6 (this ADR's own deferral, and #460's half);
  ADR-0050 §1 (the retirement set and the two held-out sources); ADR-0046 §3
  (`INSERT_IF_ABSENT` tests physical presence; a repeated id in a batch is a hard
  error); ADR-0040 §1 (a ruling names the relation), §5a/§5b (the differential
  writer obligations); ADR-0038 §2a/§5 (the supersession asymmetry and the
  signal-strength floor); ADR-0072 §2 (the three bands); ADR-0026 (the guarded
  injected clock); ADR-0065 (`core/protocols.py`'s input-observation clause) and
  ADR-0056 (the same discipline on the store's write paths); ADR-0007 §2/§3
  (retention and `export`); ADR-0028 §4/§8 (the writer seam and the conformance
  suite) and its 2026-07-23 note (the absolute-hide deferral, now #460);
  ADR-0074 §9 and ADR-0073 §1 (the level of precision this ADR states its surface
  at); ADR-0070 §1/§3/§4 (the amend-versus-supersede test, partial supersession,
  the status vocabulary); ADR-0075 (its adjudication of a reinterpretation,
  applied in §8); ADR-0015 §5 (contract ADRs land before their implementation);
  **ADR-0077** (merged Accepted — the observer, its third documented clause on
  `MemoryWriter.ingest`, and `UnresolvedEvidenceError`), whose §11 defers #306 to
  this lane in terms. In flight in a parallel lane and designed by neither this
  ADR nor it: **ADR-0078** (`ASK_USER` resolution, #423).

## Context

ADR-0045 §4 made supersession non-destructive: the stale record is retained with
its validity window closed rather than overwritten. Step 1 of that mechanism is
one sentence — "Write `T` back with `validity.valid_until = now`" — and it is
unqualified. It is exactly right for the only targets the applier has ever had to
retire, because ADR-0045 §2 frames the envelope window as set *operationally*, no
in-scope producer constructs a bounded-window record, and a supersession fires
only on a record its own conflict search returned as **live**.

Issue #306 records what that sentence does not decide: what a retirement means
when the target's window was **already bounded by its producer**. Two shapes
break the literal instruction.

- **A target whose window already ends before the writer's clock.** Writing
  `valid_until = now` would push the end *out*, making a self-closed belief live
  again over `[existing_end, now)`. Retirement would have resurrected something.
- **A target whose window has not opened at the writer's clock**
  (`valid_from >= now`). Closing at `now` forms an empty or inverted interval,
  which `Validity`'s `valid_until > valid_from` validator rejects — and
  `SqliteMemoryStore`'s decode re-runs that validator on load, so persisting one
  would make the retained record un-loadable. There is no *representable* "retire
  as of now" for such a target at all.

**Three parts of #306's body are stale, and the ratified records win.** #306 was
filed against PR #304 and says the hardening that handled these two shapes "was
reverted to the ADR-literal form; the edge cases are deferred here." That is no
longer the state of `main`. `MemoryIngestor._close_window` — and, duplicated
rather than imported, `FakeMemoryWriter`'s copy — today take the **min** and
**refuse** the unrepresentable case, each pinned by a per-writer regression test
(`test_superseding_a_target_never_extends_its_existing_window`,
`test_superseding_a_future_dated_target_refuses_without_corrupting`, and their
`test_fake_writer.py` counterparts). #306 also predates ADR-0050 and ADR-0079, so
its framing of a supersession as retiring *one* target is superseded twice over:
a `SUPERSEDE` retires the named target plus every supersedable conflict in the
ruled-on set (ADR-0050 §1, promoted to the contract by ADR-0079 §3). And its
third paragraph — the read-time visibility residual under injected clock skew —
is a different question on a different Protocol; it is split out as **#460** and
is not decided here (§9).

What has *not* changed is that those two behaviours are **unratified**. No ADR
before this one states them. `_close_window`'s own docstring is careful about it,
calling them "correctness floors, not a retirement policy" and deferring
"whether the envelope window should be producer-settable at all, and any richer
retirement of a bounded window" to this ADR. ADR-0079 §6 holds them constant
while explicitly declining to absorb the question — "`_close_window`'s two
ratified floors — never extend, never write an unrepresentable window — stand
verbatim and now apply across N targets instead of one, which changes neither
floor" — and files the choice between **clamp, refuse, or never-lived** as a
queued separate ADR. Their authority up to now has been an applier docstring and
two per-writer tests. This ADR supplies the clause, and raises it from applier
internals to the `MemoryWriter` contract.

**Three things make now the moment.**

**Retirement is now total, and it is now at N.** ADR-0079 §1 ratified that "a
correction resolves every conflict it is shown, or it does not land," and §3
promoted full-set retirement into the `MemoryWriter` contract. A rule about one
awkward target is no longer about one target: a single member of a retirement set
that cannot be closed decides the fate of the whole correction. Whatever this ADR
rules has to be stated over the *set*, or it reintroduces exactly the partial
retirement ADR-0079 closed.

**The producer population is about to grow.** Every record in the store today
comes from a small, known set of producers, none of which stamps an envelope
window. The observer (leg 3, **ADR-0077**, merged Accepted) is a model-backed
producer of `DERIVED`-band beliefs, and it sets no bounded window — ADR-0077 §11
says so and files #306 here, "Leg 4", rather than deciding it. That is the right
split and it is also the reason not to wait: the producer population stops being
small and known with the observer, and a rule that is unratified while its
trigger is unreachable becomes a bug the first time a producer stamps
`valid_from` or `valid_until` because the belief it recorded genuinely has a
shape.

**ADR-0045 §6 already ruled the read side and left the write side open.** §6 is
explicit that a producer-set `valid_from` is a real case the contract must
honour — "This ADR's own mechanisms never set `valid_from` to the future
(retirement sets `valid_until`; new records get an open window), but a producer
*may*, and the store must honour the contract regardless" — and §9 gives it a
post-filter home rather than a column. So the store already owes correct reads of
a producer-set window. The asymmetry left over is that the *writer* owes nothing.

**The forces.** Against clamping: `valid_until` is producer testimony where the
producer set it, and a retirement that rewrites it is the system amending someone
else's claim about when a fact held. Against refusing: ADR-0079 just made the
supersession law total, and a refusal is a user's correction failing. Against
never-lived: `Validity` makes an empty window unrepresentable *on purpose*, and
its validator says why — "a window that is never live … making it unrepresentable
here is better than storing a record that is silently invisible forever." In
favour of being able to move at all: retirement is a window close, non-destructive
and retained in `export` (ADR-0045 §4/§6), and the band where rewriting testimony
would be least defensible is already unreachable (§2).

## Decision

### 1. Retirement clamps: the close is the earlier of the writer's instant and the record's own end

**We will ratify the clamp.** Applying a `SUPERSEDE` at close instant `now`, for
each record the ruling retires (the named `target` and every supersedable
conflict in the ruled-on set, ADR-0050 §1 as promoted by ADR-0079 §3), the
retirement's end is

> `end = now` when the record's `valid_until` is unset, otherwise
> `end = min(now, valid_until)`

and the record is written back with `validity.valid_until = end`. **Every other
field is preserved, `valid_from` included.** A retirement never widens a window,
never moves its start, and never touches its content.

That single formula is the whole rule, and it splits into three cases worth
naming because they read differently:

- **The window is unbounded at the end** (`valid_until is None`) — the ordinary
  case, including the fully-open default ADR-0045 §2 gives every record. The end
  becomes `now`. This is ADR-0045 §4 step 1 unchanged, and it is what the applier
  does today for every target it has ever retired.
- **The window is still open at `now` but self-closes later**
  (`valid_until > now`). The end becomes `now`: the producer said the belief held
  until a later instant, and the system has learned it stopped holding sooner.
  The window shortens.
- **The window has already ended at or before `now`** (`valid_until <= now`). The
  end stays the producer's, which makes the write back a no-op on the window. The
  record is already retired by its own terms and the retirement adds nothing.
  Writing `now` here would push a self-closed belief back onto the read path for
  `[valid_until, now)` — retirement takes a belief *off* the read path and never
  puts one back.

**Why clamping is honest about testimony rather than destructive of it.** The
objection to clamping is that it rewrites what the producer said. Three things
bound that cost, and together they are why it is the right rule:

- **It rewrites one field of the envelope, and only downward.** The record's
  content, `provenance`, `evidence` and `expires_at` are untouched, and the
  clamped record stays in `export` — ADR-0045 §6's "the validity window is truth
  … a closed-window record is off the read path but present in `export`". Nothing
  is destroyed; a shorter window is exactly the claim the system now holds.
- **Content-declared testimony lives elsewhere and is not touched.** ADR-0045 §2
  keeps `SemanticMemory.valid_until` (ADR-0005 §1) distinct from the envelope
  window — "*per-kind, content-declared* world-expiry … a different thing from the
  envelope window, which is *uniform* and set *operationally*". Where a producer
  records a world-expiry as part of what it is asserting, that field carries it
  and this ADR does not reach it. The envelope end a retirement clamps is the
  lifecycle field, kin to `expires_at`.
- **Retirement is the ruling; deferring to the older end would refuse the
  ruling.** The policy has ruled that this belief is overturned. Leaving a later
  `valid_until` intact would leave the record live and contradicting the
  correction, which is the state ADR-0079 §1 exists to make unreachable.

**The close instant is sampled once per ingest, for the whole set.** `now` is one
guarded reading of the writer's injected clock (ADR-0026), taken before any write
and shared by every member of the retirement set. It is not re-sampled per
target. This is the same discipline `core/protocols.py`'s input-observation
clause fixes for a call's inputs (ADR-0065) and ADR-0056 fixes for the store's
write paths, applied to the one mutable input this rule reads: a per-target
sample would let one atomic batch record two different instants for one ruling,
so a reader could not say when the correction took effect. The clamp is otherwise
a pure function of the record and that instant, and it reads nothing of the
caller's proposal, so nothing here adds an observation point.

### 2. The rule does not split by band, because the band where it would is already unreachable

ADR-0072 §2 puts every record in exactly one band, and a bounded window is
producer testimony, so the natural question is whether clamping means something
different per band. It does not — and the reason is that the two bands where
clamping would be contentious are governed by rules that already stand:

- **ASSERTED** (`USER_ASSERTED`). **Never clamped.** Clause 1 of
  `_refuse_unsafe_fold` — no fold of any kind onto a `USER_ASSERTED` target, for
  either ruling — is left in force by ADR-0045 §5 on the signal-strength ground
  ADR-0038 §5 gives, and ADR-0050 §1 excludes `USER_ASSERTED` conflicts from the
  swept set for the same reason. A supersession therefore never reaches an
  asserted record's window, so the band in which "the system rewrote the user's
  own statement about when their preference held" would be the objection is
  unreachable by construction. This ADR does not narrow clause 1 and does not
  depend on it being narrowed.
- **ATTESTED** (`EXTERNAL`). **Clamped only where a policy names it explicitly.**
  ADR-0050 §1 holds `EXTERNAL` *siblings* out of the widening, so an attested
  record is never swept into a retirement set; ADR-0045 §5b permits a `SUPERSEDE`
  onto an `EXTERNAL` target and ADR-0079 §3 makes retiring a named `EXTERNAL`
  target a contract obligation. So clamping an attested record's window happens
  only as the deliberate act of a policy that named it, which is precisely the
  case where the system is asserting that the third party's report has stopped
  being true. The report itself is retained in `export`, and the integrating
  system's own record is unaffected — this is our envelope, not theirs.
- **DERIVED** (`OBSERVED`/`INFERRED`). **Clamped freely**, as the `_SUPERSEDABLE`
  allow-list already allows. ADR-0072 §2 calls a derived belief "provisional and
  re-derivable"; the same authority that produced the window revises it, and
  ADR-0079's Context makes the same observation about the widening — "everything
  the widening would retire is **DERIVED** band … where retirement is a window
  close, non-destructive, and retained in `export`."

So one rule, stated once, applies to every record a supersession can reach. This
is deliberately *not* a per-band retirement policy: inventing one would add a
third axis to a mechanism ADR-0045 §2 made uniform across kinds, and it would
have to be justified by a case the standing exclusions leave open. There is none.

### 3. An unrepresentable close refuses the whole ingest

**We will ratify the refusal, for exactly one case.** Where the record's
`valid_from` is set and the end §1 chooses is **at or before** it — `end <=
valid_from`, so the window would be empty or inverted — the applier raises
`MemoryStoreError` **before** the atomic batch. Nothing is written, no window is
closed, the correction does not land, and **every** record in the retirement set
is left **unchanged** (§6).

**"Unchanged", not "left live", and the distinction is load-bearing here.** The
guarantee is about **stored state**: the refusal writes nothing, so every record
in the set is byte-identical afterwards to what was stored before the ingest, and
no window is closed. It is deliberately **not** a claim about liveness, because
liveness is not a property of a record at all — ADR-0045 §2's predicate evaluates
the record's window against the *reader's* clock, so what a reader sees can change
with no write whatever. A target whose producer bounded it at `valid_until = E`
was retrieved as a live conflict from a store clock before `E` and is invisible to
one at or after it, refusal or no refusal. So the promise §7 states is that the
records and their windows are unchanged; what any subsequent read returns is
whatever ADR-0045 §6's predicate says at that reader's own clock. ADR-0079 §4's
obligation 2 phrases the same all-or-nothing property as "every target is left
live and unchanged" because its targets are ordinary open-window records, for
which liveness cannot lapse on its own; under this ADR it can, so the exact form
is used.

This is not a second retirement rule. It is the acknowledgement that for such a
record there is no representable retirement at all: `Validity`'s validator
rejects the interval, `SqliteMemoryStore`'s decode re-runs that validator on
load, and a store that accepted the write would hold a record it could not read
back. Failing closed, with the record left exactly as it was, is the only outcome
that leaves the store consistent.

**Two edges, named so the lane cannot get them wrong.**

- **The tie refuses.** `end == valid_from` gives the half-open interval
  `[valid_from, valid_from)`, which is empty — the record would be live at no
  instant. There is no honest end to write, so the tie falls on the refusing
  side, not on a "close it at its own start" fallback.
- **It follows from the clamp, not from a second comparison against `now`.** The
  test is on the end §1 chose. A record whose `valid_until` is earlier than its
  `valid_from` cannot exist (`Validity` forbids it), so in practice the case
  arises only from a `valid_from` at or after the writer's close instant.

**This refusal is a circuit breaker, and it fires on an incoherent composition
rather than on a hard belief.** A record with `valid_from > now` is, by ADR-0045
§2's own liveness predicate, **not live at the writer's clock** — and conflict
detection surfaces only records the *store* read as live (ADR-0045 §6). Since the
detector's read precedes the applier's clock sample within one ingest, a
composition whose store and writer clocks advance forward together gives
`valid_from <= now_read <= now_write`, and the case cannot arise. What produces it
is a store read clock **ahead** of the writer's close — an injected test clock, or
genuinely disagreeing clocks — which is the same clock-coherence gap #460 now
carries. So the refusal is the instrument ADR-0079 §1 describes for its ceiling
and `_MAX_SUPERSEDE_ATTEMPTS` before it: it exists to make a pathological state
fail loudly rather than corrupt something, not to bound an ordinary one.

**It therefore does not blunt the law ADR-0079 made total.** ADR-0079 §1's law is
over the conflicts retrieval *surfaced*, and it already states its own reach
rather than claiming exhaustiveness. This refusal removes nothing from that
reach: under a coherent composition it never fires, and where it does fire the
inputs to the ingest are already mutually inconsistent — the same class of
statement ADR-0079 §1 makes when it refuses above the ceiling ("the ingest's
*inputs* cannot be trusted"). An error the operator sees is the better outcome
than a persisted window the store will refuse to decode.

### 4. Never-lived is rejected, and `Validity`'s invariant is not relaxed

The third horn #306 names — mark the record as having never been live, rather
than clamping or refusing — is rejected, and with it any relaxation of
`Validity`'s `valid_until > valid_from` validator.

- **It is not representable, and making it so has a cost the type deliberately
  refuses.** `Validity`'s validator exists to keep an empty window out of the
  system, in its own words because "a window that is never live — never what a
  producer means — so making it unrepresentable here is better than storing a
  record that is silently invisible forever." Relaxing it would be a
  `core/types.py` change under golden rule 5, and every read predicate, the
  SQLite `valid_until` pre-filter (ADR-0045 §9) and the decode path would have to
  carry a third state.
- **It asserts something false.** The system *did* hold the belief: it is stored,
  and conflict detection surfaced it as a live contradiction of the correction.
  A never-lived marker records that it was never believed, which erases the very
  history ADR-0045 exists to keep — "invalidate, don't delete" would become
  "invalidate by denying it was ever there."
- **A separate never-lived flag is the same claim with more surface.** Encoding it
  outside `Validity` (a boolean, or a sentinel) adds a `core` field, a fourth
  read-time state and a migration, to represent an outcome §3 shows arises only
  from clocks that already disagree.

### 5. The envelope window stays producer-settable; no write-time refusal is added

#306's second question — "whether envelope `valid_from` should ever be
producer-settable at all, given §2 frames the window as operational-only" — is
answered **yes, it stays settable**, and no store or writer obligation to reject a
bounded envelope window on the way in is created.

- **ADR-0045 §6 already decided the posture and this ADR honours it.** §6 rules
  that the `valid_from` end is "enforced, not assumed away … a producer *may* [set
  it], and the store must honour the contract regardless," and requires
  before/at/after-boundary conformance cases for *each* end. A write-time refusal
  would make a ratified sentence false, for no capability.
- **§2's "set operationally" is a description of this system's own mechanisms,
  not a prohibition on producers.** The two coexist precisely because §6 spelled
  out the producer case. This ADR completes the *write* side §4 left literal; it
  does not reopen either.
- **The refusal would have to live on `MemoryStore`, which nothing asks for.**
  `add` and `write_atomic` are the general store writes; forbidding a bounded
  envelope window there is a `MemoryStore` semantics widening owing its own ADR
  under golden rule 5, and it would not remove the need for this one — a record
  can already have been stored bounded by any conforming store, and by every
  test that plants one today.
- **It would also break a real case rather than a hypothetical one.** A producer
  that records a belief it knows to be time-bounded is doing the honest thing; the
  read path handles it, and after this ADR the write path does too.

### 6. How this composes with ADR-0079's total retirement law, with no partial-retirement hole

ADR-0079 §3 makes a `SUPERSEDE` retire the named target plus every supersedable
conflict in the ruled-on set, in one atomic batch. This ADR is stated over that
set, and four clauses keep it from opening the hole ADR-0079 closed.

**Every member is subjected to the same rule, evaluated before any write.** The
close instant is sampled once (§1), §1's end is computed for **every** member, and
§3's representability test is applied to **every** member — all of it before the
batch is built. A single unrepresentable member therefore refuses the whole
ingest.

**There is no "skip the awkward one and retire the rest".** That shape is
specifically forbidden. It would commit a correction while knowingly leaving live
a conflict the policy ruled on — the exact state ADR-0079 §1 rules out, one
member deep. So is the variant ADR-0079 §1 already rejected in general: landing
the correction and reporting the incompleteness on `MemoryIngestResult`, which
"converts a correctness defect into a field" and is honest only if something
reads it.

**A clamp that changes nothing still counts as resolved, and the member stays in
the batch.** For §1's third case (`valid_until <= now`) the write back leaves the
window as the producer set it. That discharges ADR-0079 §1's obligation rather
than dodging it: at every read clock at or after the writer's close the record is
off the read path, which is the same read-time-relative guarantee every other
retirement carries (ADR-0045 §6; ADR-0028's 2026-07-23 note; the absolute form is
#460's). The member is written back as part of the atomic batch rather than
skipped, so the applier branches on nothing and the batch remains the record of
which records the ruling reached; the batch still repeats no id, which
`write_atomic` would reject (ADR-0046 §3).

**Two refusals, two places, and this ADR moves neither.** ADR-0079 §1's ceiling
refusal fires in **detection**, before any ruling is sought — "the ingest's
*inputs* cannot be trusted". §3's refusal fires in the **applier**, after a
`SUPERSEDE` ruling and before the batch. The order within one ingest is:
completeness (ADR-0079 §1), then the ruling (ADR-0079 §2), then §3's
representability check, then the write. Both raise `MemoryStoreError`. §3's is
deliberately *not* hoisted into detection: a window that cannot be closed is a
problem only for a record a ruling actually retires, so refusing at detection
would fail `ACCEPT` and `REINFORCE` ingests that touch no window — a strictly
larger refusal buying nothing. And it never fires on a deferral: ADR-0079 §2's
`ASK_USER` writes nothing and closes no window.

**Whoever commits an `ASK_USER` resolution inherits this rule with §1's.**
ADR-0079 §2 binds any resolution mechanism to §1's obligation "at §1's own reach
and not beyond it"; a resolution that commits a `SUPERSEDE` is a supersession and
carries this ADR's clamp and refusal identically. ADR-0078 owns that mechanism,
in flight in a parallel lane; nothing about it is decided here.

**The refusal is band-blind, and that is accepted.** Like ADR-0079 §1's ceiling,
§3's refusal does not ask which band the offending member is in: one derived
sibling with a `valid_from` ahead of the writer's clock fails a user's
correction. That is the cost of one rule with one meaning, it is loud and
recoverable, and §3 shows the trigger is a clock disagreement rather than a
property of the belief.

### 7. The contract surface owed

Stated at ADR-0074 §9's level of precision. No code is written here; the
semantics below are the contract and the spelling is the implementing lane's
(ADR-0073 §1's form).

**`core/protocols.py` — `MemoryWriter.ingest`, documented semantics only.** No
signature change, no member, no new Protocol, no `core` type, no new error class.
Two clauses, **stacked on** what that docstring already carries and touching none
of it: ADR-0079 §4's `SUPERSEDE` obligation and its over-ceiling raise clause,
and ADR-0077 §5's refusal of a `DERIVED` proposal whose evidence names no record
the store holds. The clauses below narrow *how a retirement writes a window*;
ADR-0079's decide *which records a ruling reaches*, and ADR-0077's decides *which
proposals are admissible*, so the three do not overlap.

- **the clamp**, attached to the `SUPERSEDE` obligation ADR-0079 §4 states: each
  record a supersession retires is written back with its window closed at the
  **earlier** of the writer's close instant and the record's own `valid_until`,
  every other field preserved — so a retirement never extends a window and never
  moves `valid_from`. One close instant serves the whole retirement set;
- **the raise clause**: `MemoryStoreError` when a record the ruling would retire
  carries a `valid_from` at or after that end, so the closed window would be
  empty or inverted — with nothing written, no window closed, and every record in
  the set left **unchanged** — the stored records and their windows, not a claim
  about what a later read returns (§3). This is flagged under golden rule 5 as a
  semantics widening rather than waved through as a no-op, the treatment ADR-0074
  §9 gave `Planner.plan`'s `memories` parameter and ADR-0079 §4 its own raise
  clause.

`MemoryStore`, `MemoryPolicy`, `MemoryDecision` and `Validity` are **untouched**
(§4, §5).

**`tests/memory/memory_writer_contract.py` — the shared suite gains three
obligations.** ADR-0079 §3's argument for promotion applies unchanged: both
writers already carry the behaviour, `FakeMemoryWriter`'s copy is duplicated
rather than imported, and nothing but a per-writer test keeps them in step — so
the two could drift into disagreeing about whether a write is *possible*, which
"is not tuning under any reading."

1. **A retirement never extends a window.** A `SUPERSEDE` over a target planted
   with `valid_until = E`, read from a store clock before `E` so it is a live
   conflict. Pinned: the retained target's `valid_until` is set and **not later
   than `E`**; it is absent from `get`/`search` read at or after `E` and present
   in `export` (ADR-0045 §6); the correction lands at a fresh id with a fresh open
   window and `record_id` names it.
2. **An unrepresentable close refuses, and writes nothing.** A `SUPERSEDE` over a
   retirement set holding a target planted with `valid_from = F` **and** at least
   one ordinary open-window sibling, read from a store clock at or after `F` so
   both are live conflicts. Pinned as the exhaustive disjunction below: either
   the ingest raised and nothing in the set moved, or it succeeded and did so
   lawfully. There is no third outcome, and in particular no outcome in which a
   record is stored carrying an unrepresentable window.
3. **All-or-nothing across the set, and one close instant for it.** On the
   refusal branch of obligation 2, **every** record in the set is left
   byte-identical to what was planted — no window closed, no correction written,
   no id minted — which is the §6 clause and the generalisation of ADR-0079 §4's
   obligation 2 from the id-factory failure to this one. On the success branch,
   two things: every retired record's window is **well-formed** — `valid_until`
   strictly greater than `valid_from` wherever `valid_from` is set — and every
   retired record **that §1's clamp leaves at the writer's own end** carries the
   *same* `valid_until`. That qualifier is not a hedge: §1 requires a record whose
   own `valid_until` is earlier than the close to keep *its* end, so those records
   are outside the equality by the rule's own terms, and obligation 1 is what pins
   them. Since every member of obligation 2's planted set is such a record — a
   `valid_from`-only target and an open-window sibling, neither carrying an end —
   the equality holds over the whole set there. It pins §1's *outcome*, one close
   instant recorded across the set; it does not prove the writer took only one
   clock **reading**, which the shared suite cannot see (below).

**No writer clock is pinned, and `WriterFactory` gains nothing.** This is the
constraint that shapes the obligations: the suite "deliberately does not pin
clock handling (a writer with no clock at all conforms)", which is why the
bounded-window tests have lived per-writer until now. Obligation 1 needs no clock
because "never extend" is an **inequality** against the planted end, which every
conforming writer satisfies whatever its clock reads. Obligations 2 and 3 are
stated as a **disjunction** the suite can observe:

- **either** `ingest` raised `MemoryStoreError` and no record in the set changed
  and no correction was written — the branch a writer whose close instant is at
  or before `F` owes;
- **or** `ingest` succeeded, **and** both planted records — neither of which
  carries a `valid_until` of its own, so §1 leaves both at the writer's end —
  were retired with the same `valid_until`, **and** that instant is strictly
  after `F`. Which is exactly the case where the window *was* representable, so
  the close was lawful and no refusal was owed.

**The success branch's two conjuncts are what make the disjunction airtight, and
neither is decorative.** A weaker form — asserting only that the *sibling's*
stamped close is at or after `F` — is satisfiable by a writer that violates both
§1 and §3: sample the clock once per target, close the future-dated target at an
instant before `F` (persisting the inverted window `[F, earlier)`, which
`model_copy(update=...)` constructs without re-running `Validity`'s validator),
then sample again past `F` for the sibling. Requiring the two retired records to
share one `valid_until` rules out the per-target sampling that makes the
divergence possible, and requiring each retired window to be well-formed rules
out the persisted inversion directly rather than by inference. Both must be
asserted in the suite rather than left to the store: the shared suite runs over
`FakeMemoryStore`, so `SqliteMemoryStore`'s decode re-validation — which would
reject such a row on read — is not there to catch it.

**What the shared suite cannot reach, stated rather than implied.** It fixes no
writer clock, so it cannot observe that a stamped close instant *is* the writer's
own reading of one. A writer that returns a constant close instant **conforms** —
that is what "a writer with no clock at all conforms" means — so an assertion
that the end is clock-derived would contradict the suite's standing exclusion
rather than strengthen the contract. Two consequences follow, and both are
accepted:

- **The suite cannot force the refusal branch.** A writer whose close instant
  always falls after the planted `F` lawfully takes the success branch every
  time. The obligations prove the disjunction holds, not that both of its
  branches are reachable.
- **Obligation 1 bounds the close from above and not from below.** "Never
  extend" does not catch a *premature* close — which this ADR does not make a
  violation: §1 fixes the end as a function of the writer's own clock, and the
  clock is exactly what the suite declines to pin.
- **Obligation 3's equality pins the outcome, not the number of clock reads.**
  A writer whose clock is constant — which every writer the suite drives today
  effectively is — satisfies it even if it samples once per target, because both
  samples return the same instant. So the assertion is necessary and not
  sufficient for §1's one-*reading* rule.

**The third gap is closed by a per-writer regression, and the lane owes it.**
Each writer's own tests already inject a clock, so each gets a multi-target
`SUPERSEDE` driven by an **advancing** clock — one that returns a later instant
on each call — asserting that every retired record in the set carries the *same*
`valid_until`. A writer re-sampling per target fails it; a writer sampling once
passes whatever the clock does next. That is the deterministic form the shared
suite cannot express without a clock seam it has ruled out, and it belongs beside
the clamp and refusal regressions that are already there.

Driving the exact clamp and the exact refusal against an **injected** clock is
therefore the per-writer tests' job and stays there (`test_ingest.py`,
`test_fake_writer.py`, which already do the first two). The shared obligations
exist to stop the two writers **diverging** — the thing ADR-0079 §3 promoted an
obligation for — not to re-derive each writer's clock discipline. Naming that
bound is the same move ADR-0079 §1 makes about its own reach: not a hedge,
because a suite claiming more than `FakeMemoryStore` and an unpinned clock can
observe would be claiming something no conforming writer is held to.

So no clock seam is added, and the suite's standing refusal to pin the limit's
value, the threshold, the tuning check and the clock all survive (ADR-0079 §4
needed a seam for its obligation; this one does not). The `WriterFactory`
docstring's line that "the bounded-window close tests live with each concrete
writer, not here" is what the lane updates.

**`src/ai_assistant/testing/writer.py` — `FakeMemoryWriter` matches**, by the
standing rule that it duplicates `_close_window` rather than importing it: the
fake must not reach into the `memory` subsystem (golden rule 1) while owing the
same behaviour. The suite is what keeps the two honest.

**`src/ai_assistant/memory/` — the production side needs no behaviour change.**
`_close_window` already computes `min(now, valid_until)` and refuses
`end <= valid_from`, and `_apply_supersede` already closes every target up front,
before any write. What the lane owes is the *record*: the `MemoryWriter.ingest`
docstring, the three suite obligations, the advancing-clock regression each
writer owes (above), and re-homing the `#306` citations in `_close_window` and
`testing/writer.py` to this ADR (the `#306` citations that refer to the
read-time-relative hide move to **#460** instead). The existing per-writer
regression tests stay where they are; the suite obligations do not replace them,
they stop the two writers drifting apart.

**No new error class, and deliberately not the one ADR-0077 just added.** §3's
refusal raises plain `MemoryStoreError`, which is what every other
writer-boundary refusal raises. ADR-0077 §5 has since taken the distinguishable
subclass ADR-0079 §4 left open — `UnresolvedEvidenceError(MemoryStoreError)`,
carrying the unresolved evidence ids — and it is emphatically **not** the class
for this refusal: it names a proposal whose *evidence* does not resolve, whereas
§3 refuses over a *target's* window, and the observer stage discriminates it
precisely to tell a retention race from a producer bug. §3's refusal has no such
consumer: nothing distinguishes it from a backend failure today, and ADR-0077's
own reasoning — the subclass is "taken by the lane that has the consumer" — is
the reason to leave it plain. If an interface ever needs to render "this target's
window cannot be closed" differently, a subclass is additive under `except
MemoryStoreError` and reverses nothing here.

### 8. How this stands to ADR-0045 and ADR-0028 under ADR-0070 §1

ADR-0070 §1's test: "Any change to what was decided requires a new ADR that
supersedes the old one — wholly, or partially (§3). A change to what was decided
is anything a reader would act on differently."

**ADR-0045 §4 step 1 is partially superseded.** A reader of ADR-0045 §4 holding a
target and asked to retire it writes `validity.valid_until = now`,
unconditionally. A reader of this ADR writes the **earlier** of `now` and the
record's own end, and refuses where `valid_from` would make the interval
unrepresentable. **They act differently** — and for a target that self-closes
before the writer's clock, ADR-0045's ratified sentence becomes **false**, not
merely incomplete: the retirement writes the producer's end, not `now`.

It is tempting to argue this is a *new decision* rather than a supersession,
because §4's instruction was written for a population in which the case cannot
arise, ADR-0045 §2 frames the window as operational, and `_close_window`'s own
docstring reads §4 as scoped to open-window targets. That argument is rejected on
ADR-0075's adjudication of the identical shape (#442): the test is applied as
written, and a change to what was decided is owed a supersession "regardless of
how good the reinterpretation's argument is." §4 carries no such qualifier in its
ratified text; the qualifier is the implementation's gloss. The scoping argument
is not defeated by being insufficient to avoid a supersession — it is the
justification for one, and it is §1's.

The supersession is **narrow, and deliberately so**. Step 1's *shape* — the
target is retained on disk with a closed window, off the read path, rather than
overwritten — is ADR-0045's decision and is honoured rather than replaced; what
this ADR replaces is only which instant the end takes and what happens when no
end is representable. Steps 2 and 3, the whole of §5 and §6, the atomicity floor
of §8 and the migration of §9 are untouched and remain the operative law. In
particular §6's ruling that a producer-set `valid_from` is enforced at read time
is not merely left standing — §5 depends on it.

The status line ADR-0045 receives is ADR-0070 §4's leading-token form on one
physical line, with a scope that names a clause and carries no `ADR-NNNN` token:
`Partially superseded by ADR-0080 (§4's window-close instruction for a target
carrying a producer-set bounded window)`. That **replaces** the grandfathered
`Accepted, §10's #248 conclusion narrowed by ADR-0046` value, because ADR-0070 §4
requires the supersession to lead and forbids an `ADR-NNNN` token inside a scope
— and the ADR-0046 narrowing loses nothing by it, since it is an *amendment*,
which §4 says "is not a status token and never bears on this read," and it is
recorded in full in ADR-0045's own `Amended: 2026-07-23 by ADR-0046` header note
directly below. The appended dated note this ADR adds says so explicitly, so the
reformat is legible as a reformat rather than a deletion.

**ADR-0028 is not edited.** Two clauses of it are in the neighbourhood and
neither moves. §8's conformance list grows a third time in spirit — but ADR-0079
added four suite obligations to the same suite and left ADR-0028 alone, which is
the post-ADR-0070 precedent directly on point, and it is the right one: a reader
of ADR-0028 §8 implements a `MemoryWriter` and runs the shared suite, and acts
identically before and after, because each obligation's authority is the ADR that
states it. ADR-0028's 2026-07-23 note defers the *absolute, clock-coherence-
independent* hide guarantee to #306; this ADR does not decide that, and §9 names
**#460** as where it now lives, so the note's substance is undisturbed and its
pointer is re-homed by the tracker rather than by rewriting ratified text
(ADR-0070 §1).

**ADR-0079 is not superseded.** §6's bullet defers this exact question and holds
the two floors constant while doing so; this ADR ratifies them as the answer and
changes neither, so no ADR-0079 sentence becomes false. This is ADR-0073's shape
— it settles what ADR-0079 left open and changes no clause it closed. §6's
sibling deferral of #306's absolute-hide half is likewise honoured, not absorbed.

### 9. What this ADR does not decide

- **An absolute, clock-coherence-independent retirement hide guarantee** — issue
  **#460**, split out of #306 in this lane and carrying the third paragraph of
  #306's body. A retired record leaves the read path when the *store's* read
  clock reaches the *writer's* close instant, and this ADR leaves that
  read-time-relative semantics exactly as ADR-0045 §6, ADR-0028's 2026-07-23 note
  and ADR-0079 §6 have it. Closing it needs either a store-authoritative
  retirement instant — a `MemoryStore` contract change owing its own ADR under
  golden rule 5 — or a coherent shared read-write clock invariant at the
  composition root. A store lane, not a write-path one.
- **Whether `MemoryStore` should refuse a producer-set bounded envelope window at
  write time.** Answered "no" in §5 rather than deferred, on ADR-0045 §6's
  ratified posture. Revisiting it would be a `MemoryStore` semantics change with
  its own ADR.
- **Any relaxation of `Validity`'s ordering invariant, or a never-lived
  representation** (§4). Rejected outright, not filed.
- **As-of queries and the full transaction-time axis** (ADR-0045 §1/§10). A
  clamped window is still one axis; nothing here creates a consumer for the
  second, and this ADR adds no way to ask "what did I believe on date X".
- **Reconciling `SemanticMemory.valid_until` with the envelope window**
  (ADR-0045 §10). §1 leans on the distinction and does not close the overlap;
  the content-declared field is not touched by a retirement.
- **Whether `MemoryStore` retrieval owes threshold-completeness** (issue #457).
  ADR-0079 §6's, unchanged. A conflict retrieval never surfaced is invisible to
  this rule exactly as it is to ADR-0079 §1.
- **The `ASK_USER` resolution mechanism** (issue #423). **ADR-0078**'s, in flight
  in a parallel lane; §6 states only what any resolution committing a
  `SUPERSEDE` inherits.
- **What the observer produces, and at what volume.** **ADR-0077**'s, merged
  Accepted, with ADR-0072 §3 fixing the band and confidence obligations it
  produces under and ADR-0077 §11 deferring #306 here in terms — "the observer
  sets no bounded window today, and it is deliberately not the lane that decides
  what retiring one means." This ADR is the reciprocal: it makes the write path
  ready for a producer that stamps windows without deciding that any producer
  should.
- **A distinguishable error subclass for §3's refusal.** Not taken (§7). ADR-0079
  §6's deferral was closed for a *different* refusal by ADR-0077 §5's
  `UnresolvedEvidenceError`; this one has no consumer that discriminates it, so it
  stays plain `MemoryStoreError` until one exists.
- **Narrowing `_refuse_unsafe_fold` clause 1**, so a supersession could reach an
  `USER_ASSERTED` target's window. Untouched (ADR-0045 §5, ADR-0050 §2); §2
  depends on it standing but does not argue about it.

## Consequences

- **The write path's retirement semantics are complete for every window a
  producer can construct.** Before this ADR the applier's behaviour for a bounded
  target rested on a docstring and two per-writer tests; after it, the rule is a
  `MemoryWriter` clause, the boundary is in the shared suite, and the canonical
  fake is held to it. #306's first two questions are answered and the third is
  #460's.
- **A supersession cannot resurrect a belief.** The clamp makes "retirement takes
  a belief off the read path and never puts one back" a contract property rather
  than an implementation habit — the one thing a naive reading of ADR-0045 §4
  step 1 gets wrong.
- **A correction can now fail on a clock disagreement.** §3's refusal is a real
  user-visible failure mode: an ingest raises and the user's correction does not
  land. It is bounded to a state a coherent composition cannot produce (§3), it
  is loud rather than silent, and it leaves every record in the set exactly as it
  was — but it is a second
  way for a correction to refuse, alongside ADR-0079 §1's ceiling, and both are
  `MemoryStoreError` today.
- **The suite gains three obligations and no seam.** The reviewable unit is one
  docstring, three suite obligations, and the fake matching. `WriterFactory` is
  unchanged, so no existing subclass needs to move, and the suite still pins no
  writer clock — the constraint that shaped how the obligations are stated (§7).
- **`FakeMemoryWriter` and `MemoryIngestor` stop being able to drift on the
  window.** They agree today; nothing but two independent tests kept them there,
  and after this ADR the shared suite does — the same cure ADR-0079 §3 applied to
  the retirement set.
- **ADR-0045 is partially superseded in one clause** (§8), with its Status line
  edited to ADR-0070 §4's leading-token form and a dated note appended in this
  same change (ADR-0070 §1/§4). Everything else it decided remains the operative
  law, and §6 in particular is load-bearing for §5 rather than weakened.
- **ADR-0028 keeps its `#306` pointer and gains no edit**, on ADR-0079's
  precedent; the absolute-hide question it defers now lives at #460 (§8, §9).
- **Issue #306 closes with this ADR's implementation lane**; **#460** stays open
  with a named owner. #457, #423 and the observer's volume question are
  unaffected.
- **Revisit if** a producer lands that stamps envelope windows routinely (the
  refusal's trigger would stop being exotic and the clamp's cost would become
  visible in `export`), if #460 gives the store an authoritative retirement
  instant (§3's refusal would become genuinely unreachable rather than
  practically so), or if a consumer ever needs to read *when* a belief was
  retired independently of when it stopped being true — which is the
  transaction-time axis ADR-0045 §1 staged, not a change to this rule.

## Alternatives considered

- **Refuse every retirement of a producer-set bounded window.** The simplest
  rule: if the producer bounded it, the applier will not touch it. Rejected —
  it makes the supersession law ADR-0079 §1 just ratified defeatable by data. One
  bounded record in a retirement set would fail every correction on the topic,
  permanently, and the surplus ADR-0079 refused to leave live would come back as
  a correction that can never land at all. It also refuses the case where
  clamping is unambiguous (a window still open at the close), for no gain.
- **Never-lived: mark the record as having never been live.** Rejected in §4. It
  is unrepresentable without relaxing `Validity`'s ordering invariant — which
  exists precisely to keep a permanently-invisible record out of the store — or
  adding a `core` field and a fourth read-time state; and it asserts something
  false, since the system did hold the belief and detection surfaced it.
  "Invalidate, don't delete" would become "invalidate by denying it was ever
  there," which is the audit-trail loss ADR-0045 was written to end.
- **Take `max(now, valid_until)` — always retire "as of now", extending where
  needed.** Rejected in §1. It reads as consistency ("the retirement instant is
  always the ruling's instant") and it resurrects: a belief that self-closed in
  March is live again from March to the June correction. Retirement is a
  one-directional operation and the `min` is the only end that keeps it one.
- **For a not-yet-begun target, skip it and retire the rest of the set.**
  Rejected in §6. It commits a correction while leaving live a conflict the
  policy ruled on — ADR-0079 §1's defect, one member deep — and it is the
  partial-retirement hole this ADR is required not to open.
- **For a not-yet-begun target, close it at its own `valid_from` (or a hair
  after).** Rejected in §3. `[valid_from, valid_from)` is empty and the validator
  rejects it; adding an epsilon fabricates an interval of arbitrary width in
  which the system claims the belief held. An invented window is worse than a
  refusal, because it is indistinguishable in `export` from one the producer set.
- **Delete the record instead of closing its window when no close is
  representable.** Rejected: it is the destructive write ADR-0045 exists to
  remove, and deletion is a retention decision governed by `expires_at` and
  ADR-0007 §3, on an axis ADR-0045 §6 deliberately keeps orthogonal to truth.
- **Hoist §3's check into detection, so an unclosable record never reaches a
  ruling.** Rejected in §6. It would refuse `ACCEPT` and `REINFORCE` ingests that
  close no window at all, which is a strictly larger refusal for no benefit; a
  window that cannot be closed is only a problem for a record a ruling retires.
  ADR-0079 §1's ceiling belongs in detection for the opposite reason — it is a
  statement about the *inputs* to any ruling.
- **Forbid producers from setting the envelope window, so the whole question
  disappears.** Rejected in §5. It contradicts ADR-0045 §6's ratified "a producer
  *may*, and the store must honour the contract regardless", it needs a
  `MemoryStore` refusal that is its own contract lane, and it would not even
  discharge this ADR: records stored bounded before such a rule, and by any
  conforming store, still have to be retirable.
- **Split the rule by band — clamp DERIVED, refuse ATTESTED.** Rejected in §2.
  The band where rewriting testimony would be least defensible (ASSERTED) is
  already unreachable through clause 1, and an ATTESTED record is clamped only
  where a policy names it explicitly, which is a deliberate act rather than a
  sweep. A per-band retirement policy would add an axis to a mechanism ADR-0045
  §2 made uniform across kinds, justified by no case the standing exclusions
  leave open.
- **Add a clock seam to `WriterFactory` so the suite can pin the refusal
  directly.** Rejected in §7. The suite's refusal to pin clock handling is
  deliberate — "a writer with no clock at all conforms" — and a seam a clockless
  writer could only pass by skipping the obligation is not a contract. Stating
  obligation 1 as an inequality and obligations 2–3 as an observable disjunction
  gets the same coverage with no seam, which is why ADR-0079 §4 needed one for
  its ceiling and this ADR does not.
- **Leave the two floors as applier internals and close #306 as "already
  handled".** Rejected: it is the reinterpretation ADR-0075's adjudication rules
  out (§8), it leaves two writers agreeing by coincidence rather than by
  contract, and it would leave ADR-0045 §4's ratified sentence standing while the
  code does something else — which is the state that produced #306 in the first
  place.
