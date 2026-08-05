# 105. An install enforces the absence of the id it lands at

- Status: Proposed
- Date: 2026-08-05
- **This is not a substantive contract ADR, and the test was applied rather than
  assumed.** `CONTRIBUTING.md` → "Contract ADRs land before their implementation"
  defines one as an ADR "that adds or changes a Protocol or a `core` type that
  crosses subsystem boundaries", and golden rule 5 names a Protocol change. This
  ADR does neither: it changes which **already-ratified** `MemoryStore` verb
  `MemoryIngestor` calls on two of its four write-producing rulings.
  `MemoryStore.write_atomic`, `MemoryWrite` and `MemoryWriteMode` are consumed
  exactly as [ADR-0046](0046-a-memorystore-batch-commits-atomically.md) ratified
  them, `MemoryStore.add` keeps every word of its own contract (§3), and no
  signature, field or documented promise in `core` changes. It therefore ships
  **with** its implementation in one PR rather than ahead of it, and `just ship`
  agrees independently: its architecture trigger is keyed on
  `src/ai_assistant/core/protocols.py` and `src/ai_assistant/core/types.py`, and
  fires on neither.
- **It adds a `MemoryWriter` conformance obligation**, which
  [ADR-0079](0079-a-correction-resolves-every-conflict-it-is-shown.md) §3 made
  contract rather than one implementation's habit. That is why the decision is
  recorded at all instead of landing as a defect fix: the shared conformance
  suite and `FakeMemoryWriter` move with `MemoryIngestor`, and the behaviour at
  the boundary is what a later reader will read as the rule.

  **It is not why the ADR would ship separately, and `main` settles that rather
  than the reasoning above.** The obvious objection is that every neighbouring
  writer obligation — ADR-0079 §3's retirement set, ADR-0080 §1's clamp,
  ADR-0081 §1's self-consuming write, ADR-0086 §2's bound — is also *stated* on
  `MemoryWriter.ingest`'s docstring in `core/protocols.py`, so this one owes a
  line there too, and that would be a contract change. **Checked against the
  tree, and it does not hold:**
  [ADR-0078](0078-a-deferred-memory-decision-is-a-durable-question.md) §5b's
  check 0 — a write-producing ruling on `DataTier.SECRET` is refused at the
  writer boundary — is pinned in `memory_writer_contract.py` for all four
  write-producing rulings by
  `test_no_write_producing_ruling_persists_secret_tier_data`, and
  `MemoryWriter.ingest`'s docstring says **nothing** about it: the whole
  `MemoryWriter` block mentions neither `DataTier` nor secrecy. So a
  *refusal* at the writer boundary, ratified by its own ADR and pinned by the
  shared suite with no `core/protocols.py` text behind it, is the established
  shape on `main` and not an exception being carved here. §1 is the same
  category, and takes the same treatment.

  What that leaves genuinely open is whether the Protocol docstring *ought* to
  enumerate its refusals as well as its positive obligations — a question about
  ADR-0078 §5b's entry as much as this one, with a whole-docstring answer.
  Deliberately not decided here: it is a `core/protocols.py` edit affecting a
  ratified clause that is not this ADR's, and doing it under this ADR would
  reclassify a fix as a contract change to tidy something the fix did not cause.
  Filed rather than dropped (§9).
- **It discharges two named deferrals rather than superseding anything.**
  [ADR-0092](0092-an-attested-belief-names-its-source-and-a-user-assertion-retires-it.md)
  §10 deferred "whether `ACCEPT` should install insert-if-absent for a producer
  that mints its id", filed as issue #630; §1 answers it. §5 states why
  [ADR-0081](0081-no-write-consumes-the-evidence-its-own-proposal-cites.md) §8's
  neighbouring deferral keeps its owner, its trigger and its scope. Applying
  [ADR-0082](0082-recording-an-amendment-on-an-earlier-adrs-status-line.md) §1's
  test edit by edit, **no record is owed on any earlier ADR's `Status` line**:
  no named clause of ADR-0092, ADR-0081, ADR-0045 or ADR-0046 acquires, loses or
  alters an obligation. §6 works that through.

## Context

`MemoryIngestor._apply` dispatches four write-producing rulings. Two of them —
`ACCEPT` and `STORE_TEMPORARY` — install the proposal at `proposed.id` through
`MemoryStore.add`, whose semantics are documented on the Protocol in as many
words: "Adding a record whose `id` already exists overwrites the previous one (an
upsert), so `id` is the caller's idempotency key." There is no absence check on
that path.

So a producer that **mints** its ids silently replaces an unrelated live record
whenever its factory collides. Reproduced against `origin/main` at `a505d92`
before this ADR was drafted, with `FakeMemoryStore` holding one belief and an
unrelated proposal minted at the same id:

```text
ruling: accept written: collide
what stands at 'collide' now: quarterly revenue was up 4 percent
the cat belief is gone: True
```

One live belief destroyed, no error raised, and `MemoryIngestResult` handed back
a healthy `record_id`. Every minting producer in the tree is exposed:
`learning/observer.py` and `learning/processor.py` mint a `uuid4`, and
`readers/calendar.py` mints `calendar-<uuid4 hex>` per proposal per sync — the id
discipline ADR-0092 §6 requires of an `EXTERNAL` producer.

**The neighbouring rulings do not cover it, and each declined for a reason worth
keeping.**

- **ADR-0045 §4** settled the same question the other way *for `SUPERSEDE`
  alone*: a minted id "names no existing record, **enforced not assumed**",
  written insert-if-absent under the atomic primitive with a bounded retry,
  precisely because `uuid4` "makes a collision unlikely, not impossible".
  `ACCEPT` got no such treatment, and nothing on the record says why beyond
  ADR-0045's lane being about supersession.
- **ADR-0081 §1** (`_refuse_self_consuming_write`) refuses a write landing at an
  id the proposal *cites*. A record that cites nothing — every `EXTERNAL` and
  `USER_ASSERTED` one — is untouched by it.
- **ADR-0081 §8** defers the **cross-kind** horn to a named owner, the
  `MemoryStore` write-semantics lane taking issue #104's compare-and-swap. Its
  central objection is that a writer "could only enforce a cross-kind rule by
  paying a `get(proposed.id)` on every ingest to see something the store sees for
  free while it replaces the row — giving up §1's no-I/O, cannot-be-raced
  property for a weaker version of a rule that belongs one layer down."
- **ADR-0092 §6** states the residual exactly and declines to rule it: "The
  `ACCEPT` path has no such enforcement — it is a blind `store.add` upsert … The
  residual is not import-specific … so it is a pre-existing property this ADR
  neither creates nor closes, and §10 files it rather than half-ruling a contract
  for one caller."

**What has changed since is the reason this is decidable now.** ADR-0092 §10
declined because ruling it "would decide a contract for one caller" — the
`EXTERNAL` producer then in hand. The consolidation lane of leg 7 is a second and
much worse caller: a scheduled job that mints ids and writes in bulk, on a merge
path where a collision destroys an unrelated belief and reports success. That is
no longer one caller's contract, and a bulk writer is the trigger a residual of
this shape was waiting for. Issue #729 states the sequencing plainly — this is a
prerequisite for consolidation, not a passenger.

And **the writer-side objection has an answer that did not exist when it was
first made in the abstract**: ADR-0046 gave `MemoryStore` an explicit
insert-vs-upsert verb, and `MemoryIngestor._apply_supersede` already uses it. A
one-element `write_atomic` batch in `INSERT_IF_ABSENT` mode buys the absence
check with **no read at all** — the store enforces it while it writes, which is
exactly the thing ADR-0081 §8 said the store sees for free.

## Decision

### 1. `ACCEPT` and `STORE_TEMPORARY` install insert-if-absent

> **Normative.** `MemoryWriter.ingest` applying an `ACCEPT` or a
> `STORE_TEMPORARY` ruling installs the proposal through `MemoryStore` in
> `INSERT_IF_ABSENT` mode, never through `MemoryStore.add`. Where a stored record
> already occupies the id, nothing is written and the ingest raises
> `MemoryStoreConflictError`.

This is ADR-0045 §4's rule — "names no existing record, **enforced not
assumed**" — applied to the other two installing rulings. One rule, three
evaluation points, matching the shape ADR-0081 §2 gave its own refusal.

"Absent" is ADR-0046 §3's sense, unchanged and inherited rather than restated:
**physical presence**, not read-visibility. A stored row blocks the insert even
when expired or window-closed. That is the reading this decision needs and not
merely the one it gets for free — a retired target carrying a user's correction
is exactly the record whose window closure ADR-0092 §Context traces being erased,
and it is invisible to `get` and `search` alike (ADR-0045 §6). An absence check
keyed on readability would step past it and destroy the very thing the retirement
preserved.

`REINFORCE` is untouched. Its fold lands at the **target's** id, drawn from the
conflicts this ingest resolved and therefore known to be stored (ADR-0081 §6);
an upsert is what a fold *is*, and an absence check there would refuse every
correct fold.

`SUPERSEDE` is untouched. It already installs insert-if-absent, and its retirement
writes are `UPSERT` because a window-close overwrites a record that exists by
construction.

### 2. The writer raises rather than re-minting, because the id is not its own

> **Normative.** On the collision in §1 the writer neither re-mints the id nor
> rewrites the proposal. Nothing is written, no window is closed, and no decision
> is returned.

`SUPERSEDE` re-mints because **the id is the writer's to choose**: ADR-0045 §4
made the correction's id freshly minted inside `_apply_supersede`, so a re-mint is
free and always available, and the caller never named it. An `ACCEPT`'s id is the
**proposal's**. Three things follow, and each on its own settles it:

- **It is the producer's idempotency key**, in `MemoryStore.add`'s own words. A
  writer that quietly relocated it would return a `record_id` naming a record the
  producer did not ask for, and the producer's next reference to the id it minted
  would resolve to nothing.
- **ADR-0081 §1's refusal is quantified over `proposed.id`.** `_installed_at`
  returns exactly that for these two rulings, and the self-citation check runs
  *before* the write dispatch. A writer that moved the destination afterwards
  would have run §1's rule against an id it then abandoned — a refusal computed
  for one write and applied to another.
- **A collision is a producer bug, and the honest thing is to say so.** For a
  minting producer a collision of any kind is a defect in its factory, never a use
  of the documented key. Silently repairing it hides a broken factory behind a
  healthy result, which is the failure mode this whole decision exists to remove.

`MemoryStoreConflictError` already subclasses `MemoryStoreError`, so this earns no
new error class and widens no documented `Raises` clause on `ingest` beyond naming
the case — the same economy ADR-0081 §3 applied.

### 3. `MemoryStore.add` keeps its upsert, and that is what keeps this out of `core`

> **Normative.** `MemoryStore.add`'s upsert semantics and its idempotency-key
> promise are unchanged by this ADR. No `MemoryStore` method gains, loses or
> alters a documented behaviour.

This decision is about **which verb the writer calls**, not about what the store
promises. The distinction is the whole of why the fix is small:

- **Episodic capture keeps working.** ADR-0075 §1 exempts it from the write-path
  rule entirely, so it reaches `add` directly. ADR-0081 §8's second objection —
  "stating it at the writer would leave the callers who need it outside it" — is
  a correct objection to a rule *at the writer* pretending to be a rule at the
  store. §1 does not pretend: it binds `MemoryWriter` and says nothing about any
  other caller of `add`.
- **The store lane's ground is untouched.** #104's compare-and-swap and the
  cross-kind refusal still want a rule at `add` across all three backends, and
  still want the same conformance-suite rewrite. Nothing here forecloses it and
  nothing here does it.
- **No `core` change means no core hold.** The lane implementing this needs
  neither `core/protocols.py` nor `core/types.py`, so it does not contend for the
  contract surface with any concurrent lane.

The one-element `write_atomic` batch is not a workaround for a missing verb; it is
the verb. `SqliteMemoryStore.add` and `SqliteMemoryStore.write_atomic` share
`_persist_record` and embed through the same `_embed_one`, so a single-element
batch is `add` plus the absence check and differs in nothing else.

### 4. What it costs: re-proposing at a stored id stops being an update

> **Normative.** A producer may no longer refresh a stored record by re-proposing
> it at that record's id under an `ACCEPT` ruling. The supported way to update a
> stored belief is a fold — `REINFORCE` at the target's id, or `SUPERSEDE`.

This is the real cost and it is stated rather than argued away. It is reachable
today: `_detect_conflicts` filters the proposal's own id out of the conflict set
(`match.id != record.id`, issue #110), so a re-proposal at a stored id sees no
conflict, is ruled `ACCEPT`, and upserts in place. After §1 it raises.

Three reasons that is the right trade:

- **No *production* producer in the tree does it.** Every one mints per proposal —
  `readers/calendar.py` per sync per ADR-0092 §6, `learning/observer.py` at
  `self._id_factory()`, and `learning/processor.py` — so none has an id to
  re-propose at. **One shipped producer does, and it is a fake**; see §8, which is
  why this ADR is `Proposed` rather than `Accepted`.
- **It is not the intended update path, and ADR-0092 §6 already said so.**
  "Idempotency does not vanish; it moves": an unchanged re-sync proposes identical
  content, detection scores the existing record at the top of its ranking, and the
  policy rules `REINFORCE`, folding at the target's id. One record, updated in
  place. The `ACCEPT` upsert is a *second*, undocumented update path that only a
  producer re-using an id can reach.
- **`ACCEPT` means "nothing here contradicts this; store it as new".** Landing on
  top of a record the policy never saw is not that ruling. Insert-if-absent is
  `ACCEPT` saying out loud what it already claims.

A producer that genuinely wants to address a stored record is the trigger
ADR-0081 §8 names — "a producer that *derives* a record id from content rather
than minting one … which is the only way a cross-kind collision stops being a bug
and starts being a design". **That trigger is fired**, by a fake rather than a
production producer, and §8 records what it costs this decision.

### 5. ADR-0081 §8's deferral keeps its owner, its trigger and its scope

> **Normative.** This ADR does not decide whether a proposal arriving at the id of
> a stored record **of a different kind** should be refused at `MemoryStore.add`.
> That question, its owner — the `MemoryStore` write-semantics lane taking issue
> #104's compare-and-swap — and its trigger are unchanged.

The two questions look adjacent and are not the same. ADR-0081 §8 asks what `add`
should promise **every** caller about a foreign-kind collision. §1 asks what
`MemoryWriter` should do about a **same-kind** collision against an id its
producer minted, where a collision is a bug by construction. #630 states the
distinction and it holds: "for a minting producer a collision of any kind is a
bug, not a use of the documented key."

§8's own trigger confirms the boundary rather than merely permitting it: "Until
then no producer can collide" is a statement about the class of producer that may
collide *by design*. A minting producer is not in that class, which is why §8's
residue is described as "a silent replacement of an *unrelated* record — the
ordinary hazard of a documented idempotency key". §1 removes the case where that
hazard is reached by a caller who never used the key as a key.

And §8's cost objection does not reach §1. It priced a writer-side `get`; §1 pays
no read.

### 6. ADR-0082 §1 applied edit by edit, and no earlier `Status` line is touched

ADR-0082 §1 requires a record on an earlier ADR "exactly when the later ADR amends
a named clause", judged by ADR-0070 §1's test and made in the later ADR's text,
which is where it is reviewed. Each candidate, and the verdict:

- **ADR-0092 §10.** A deferral is discharged, not amended. §10 names the question,
  files it as #630, and declines to answer; §1 answers it. ADR-0092's own header
  states the precedent in its own voice — "It discharges two named deferrals rather
  than superseding them" — for ADR-0073 §4 and ADR-0045 §5/§7/§10. **No record
  owed.**
- **ADR-0092 §6.** Its ruling is the negative one: an `EXTERNAL` producer mints, and
  may not adopt the source's key. Untouched and still required — §1 in fact depends
  on it, since insert-if-absent under a source-keyed id would turn the §Context
  resurrection into a hard refusal on every re-sync rather than a correct write. §6's
  sentence about the blind upsert is a description of a residual it declines to
  close, in a section that says so; ADR-0089 §3 governs — a clause is normative
  when a reader could disobey it, and nobody can disobey a statement of what the
  code does. **No record owed.**
- **ADR-0081 §1's table.** It records `ACCEPT | store.add(proposed) | proposed.id`
  and the row is now stale. It sits in ADR-0081's **Context**, above its Decision,
  introduced as "the shape, verified against `src/ai_assistant/memory/ingest.py` at
  `origin/main` rather than taken from the report" — a dated observation of the
  tree, not a ruling. §1's actual obligation is quantified over the *destination*,
  which `_installed_at` still computes as `proposed.id` for both rulings and which
  §2 above keeps that way deliberately. **No record owed.**
- **ADR-0081 §8.** Untouched, per §5. **No record owed.**
- **ADR-0045 §4.** Extended by analogy to two further rulings; its own ruling about
  `SUPERSEDE` is unchanged, and an extension elsewhere is not an amendment of it.
  **No record owed.**
- **ADR-0046 §2, §3.** `MemoryWriteMode` and `write_atomic` are consumed exactly as
  ratified. §2's remark that the two modes "are exactly the two the supersession
  applier needs and no more" describes the modes' provenance, not a restriction on
  who may use them. **No record owed.**
- **ADR-0079 §3.** The conformance obligation moves with the implementation, which
  is what §3 requires of any change to writer behaviour. Obeyed, not amended.
  **No record owed.**

### 7. Explicitly declined

- **Ruling it at `MemoryStore.add` instead.** That is ADR-0081 §8's question with
  §8's owner, it needs the conformance-suite rewrite across all three backends that
  #104's CAS wants, and it would decide for episodic capture (ADR-0075 §1) a rule
  no evidence has been gathered about. §1 covers every producer #630 names and
  leaves the wider rule to the lane that can state it once.
- **Distinguishing a minting producer from an asserting one.** Nothing on
  `MemoryUpdateProposal` or `MemoryRecord` carries that fact, and a field
  distinguishing them would be surface with one consumer (ADR-0045 §1, ADR-0028
  §7). §4 shows the distinction is not needed: no producer asserts an id today, and
  the fold is the update path for one that ever wants to.
- **A `get(proposed.id)` in the writer before the install.** ADR-0081 §8's
  objection stands verbatim against it — an I/O-paying, raceable version of a check
  the store performs atomically while writing.
- **Re-minting on collision, as `SUPERSEDE` does.** §2.
- **Making `_detect_conflicts` stop filtering the proposal's own id.** It would
  route a re-proposal into the policy as a self-conflict and reintroduce issue
  #110's slot starvation at a small `conflict_limit`, to reach a case §1 refuses
  directly.

### 8. Unresolved: ADR-0081 §8's trigger is already fired, by a fake

**This section is why the `Status` above is `Proposed`.** It was found by running
the full suite against the implementation, not by reading, and it is stated here
rather than worked around because it bears on whether §1 is this lane's to make.

`FakeBeliefObserver` — `ai_assistant/testing/observation.py`, the canonical
`Observer` fake — does **not** mint. `_identify` derives the record id from a
`sha256` over the belief's content, kind, step and citations, and says why in as
many words:

> Derived from what is being believed and what supports it rather than from a
> counter, so it is deterministic without depending on execution order and
> identical across instances — two fakes writing into one store cannot silently
> overwrite each other, and re-observing one batch proposes the *same* record id
> twice, which is what a consumer testing a `REINFORCE` fold needs.

That is exactly the producer class ADR-0081 §8 named as its trigger, and §8's
"until then no producer can collide" is therefore already false on `main`. Three
consequences, none of them comfortable:

- **§1 breaks three tests outside `memory`**, each encoding another subsystem's
  ratified behaviour: `test_learn_resolves_a_repeated_record_id_last_write_wins`
  and `test_learn_leaves_earlier_proposals_applied_when_a_later_write_fails`
  (ADR-0022 §4's visible collision and partial application) and
  `test_two_unscoped_runs_select_the_same_conversation` (ADR-0077 §8's
  cursor-free re-observation).
- **The fake's stated purpose is not achieved today, which §1 exposes.**
  Re-observing one batch does *not* reach a `REINFORCE`: `_detect_conflicts`
  filters the proposal's own id out of the conflict set (issue #110), so the
  prior record is never a conflict, the policy rules `ACCEPT`, and the write is
  an upsert. The fold the docstring promises has never happened; what happened is
  the silent replacement §1 refuses.
- **So the fake diverges from production in the axis that matters here.**
  `learning/observer.py` mints at `self._id_factory()`. A fake whose ids collide
  where the real producer's cannot is the shape ADR-0026 §7 warns about, one
  direction over: it lets a consumer's test pass on an idempotency the production
  observer never provides.

**What this ADR does not do is resolve it**, because the two candidate
resolutions belong to other ground. Either `FakeBeliefObserver` mints like the
producer it doubles — a `testing` change whose fallout lands in
`tests/orchestration/**` and turns on ADR-0077 §8's re-observation ruling — or
the collision rule waits for the `MemoryStore` write-semantics lane, which
ADR-0081 §8 already owns and whose trigger this discovery fires. The first is the
better answer on the merits, and it is still not this lane's to take alone.

### 9. What this ADR does not decide

- **Issue #631** — an imported record's identity being re-established by
  similarity, so a materially rewritten source entry duplicates instead of folding.
  It is the *other* half of ADR-0092's residual and this ADR does not touch it. Its
  fix needs a third `Attestation` field carrying the source's own key and a
  `MemoryStore` read surface resolving `(reported_by, source_key)` to a live
  record — a `core/types.py` change and a Protocol addition, owing their own
  ratified ADR under golden rule 5, with the trigger ADR-0092 §10 records still
  unfired. **The two issues share a heading and not a fix**, and the difference is
  worth naming: #630 is destruction and #631 is duplication, #630 is reached by
  every minting producer and #631 only by a re-syncing one, and a consolidator —
  which mints and does not re-sync — meets #630 and never #631.
- **Whether `MemoryWriter.ingest`'s Protocol docstring should enumerate the
  writer's *refusals* as well as its positive obligations.** It states ADR-0079
  §3's, ADR-0080 §1's, ADR-0081 §1's and ADR-0086 §2's obligations and says
  nothing about ADR-0078 §5b check 0's secret-tier refusal, which the shared
  suite has pinned since that ADR landed. §1 joins the second group by the
  precedent, so this ADR neither needs nor makes that call — but the asymmetry is
  real, it is older than this change, and a `core/protocols.py` edit answering it
  belongs to whoever takes the docstring as a whole. Filed as issue #734.
- **The re-proposal path an asserting producer would want**, beyond noting in §4
  that the fold is it.
- **Anything about `confidence`.** Issue #646 and ADR-0103's split are a separate
  lane; `_merge`'s fold rule is untouched here.

## Consequences

**Easier.**

- A minting producer can no longer destroy an unrelated live belief through the
  write path. The bulk writer leg 7's consolidation lane introduces meets a hard
  refusal where it would have met a silent overwrite, which is the whole reason
  #729 sequences this ahead of it.
- The three installing rulings now state one rule between them, so a reader who
  learns ADR-0045 §4's "enforced not assumed" learns all of it. The asymmetry that
  made `SUPERSEDE` careful and `ACCEPT` blind is gone, and with it the reasoning
  needed to explain why.
- A broken id factory surfaces as a raise at the write rather than as a belief
  quietly going missing — the failure ADR-0092 §6 could only describe.

**Harder.**

- A producer that re-proposes at a stored id now fails where it used to update
  (§4). Nothing in the tree does, and the fold is the supported path, but a future
  producer written against `add`'s idempotency-key promise will meet the refusal
  rather than the promise.
- One more place where `MemoryIngestor` and `FakeMemoryWriter` must stay in step.
  The conformance suite is what keeps them there, and it is where the new case is
  pinned.
- `ACCEPT` now costs a `write_atomic` rather than an `add`. Same embedding, same
  transaction, one extra list allocation — but `MemoryWriter` implementations that
  wrap a store lacking `write_atomic` no longer exist as a possibility, since it
  has been on the Protocol since ADR-0046.

**Revisit when** a producer arrives that derives its record ids from content — a
content hash, or an external system's key adopted as the id. That is ADR-0081 §8's
trigger, and it is the same event that would make §4's cost real rather than
theoretical: such a producer both *may* legitimately address a stored record and
*may* legitimately collide across kinds, and the two questions should then be
settled together by the lane §5 leaves them with.
