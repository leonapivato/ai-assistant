# 108. A write declares its intent at the store seam, and a cross-kind collision is refused at every door

- Status: Proposed
- Date: 2026-08-05
- **This is a contract change, of the semantics-only kind.** `MemoryStore.add`
  keeps its signature and keeps its upsert semantics; what it gains is one
  refusal clause (§4), and what changes around it is which verb each caller in
  `src/` uses to say what it means (§2, §3). **No signature changes, no Protocol
  is added, and `core/types.py` and `core/errors.py` are untouched** — the write
  modes this decision routes on are `MemoryWriteMode.UPSERT` and
  `MemoryWriteMode.INSERT_IF_ABSENT`, ratified and shipping since ADR-0046 §2.
  What changes is the documented meaning of two methods plus the shared
  conformance suite, which is the review concern `CONTRIBUTING.md` names when a
  Protocol's meaning changes without its shape. Golden rule 5 therefore applies:
  this ADR ships as **its own docs-only PR**, is reviewed while still `Proposed`
  so a finding can still change the decision, and is flipped to `Accepted` on
  merge (`CONTRIBUTING.md`, "Contract ADRs land before their implementation";
  ADR-0015 §5). **No code changes with it.**
- **Required review set: adversarial *and* architecture.** This ADR decides
  `core/protocols.py` surface without touching it, which is contract-surface
  under `CONTRIBUTING.md` → "Stop when the required reviews are green". A
  prose-only PR trips neither of `scripts/ship.sh`'s persona regexes, so both
  lenses are run deliberately rather than mechanically, in ADR-0106's shape.
- **This ADR partially supersedes three ratified ADRs** —
  [ADR-0022](0022-the-closed-learning-loop.md) §4's same-id collision clause,
  [ADR-0046](0046-a-memorystore-batch-commits-atomically.md)'s cross-kind `UPSERT`
  clause, and
  [ADR-0081](0081-no-write-consumes-the-evidence-its-own-proposal-cites.md) §8's
  first deferred item together with its assignment to the #104 lane. §6 applies
  ADR-0070 §1's test to each. Three findings, in the reviews this ADR ran while
  `Proposed`, moved two of these from "amendment" to "supersession"; the reasoning
  is in §6 rather than the classification being asserted. **No ratified body text
  is rewritten and all four files land in this one change**, so no Status line ever
  names an absent ADR.

## Context

`MemoryStore.add` is documented as an upsert keyed on the caller's id: "Adding a
record whose `id` already exists overwrites the previous one (an upsert), so `id`
is the caller's idempotency key. All backends share this behaviour; the shared
conformance suite enforces it."

Issue #630 is that this makes every minting producer's `uuid4` collision silently
destructive. `MemoryIngestor._apply`'s `ACCEPT` and `STORE_TEMPORARY` arms install
at `proposal.proposed.id` through `add`, with no absence check. A colliding id
replaces an unrelated live record, returns a healthy `record_id`, and raises
nothing. The destroyed record is not among the conflicts and never could be —
`_detect_conflicts` filters the proposal's own id (#110) — so **no ruling was made
about the record the write destroyed**. The defect was reproduced on `main` at
`a505d92`: one live belief gone, nothing raised.

Two prior attempts frame what is actually open.

**ADR-0081 §1** refuses a write that lands at an id the proposal *cites*. A record
that cites nothing — every `EXTERNAL` and `USER_ASSERTED` one — is untouched by it.
**ADR-0081 §8** deferred the neighbouring *cross-kind* horn to "the `MemoryStore`
write-semantics lane, the one that takes #104's compare-and-swap", on three stated
grounds. **PR #731** then tried the writer-side fix — an absence check inside
`MemoryIngestor` — and was withdrawn. Its withdrawal is the most useful thing in
the record, because one of its two grounds was itself wrong, and the other one is
the real problem:

- The ground that did **not** hold: ADR-0081 §8's "a rule at `add` covers every
  caller; a rule at `ingest` covers one", read as meaning episodic capture could
  arrive at a collision through `add`. It cannot. `ConversationCapture` writes a
  one-element `write_atomic` in `INSERT_IF_ABSENT` mode and says why:
  "`add` is refused for its own reason: it is a documented upsert keyed on the
  caller's id" (`orchestration/conversations.py`). The caller §8 named as the
  reason a writer-side rule would miss had already protected itself, for §8's own
  reason.
- The ground that **does** hold: **ADR-0022 §4 ratifies the upsert.** "Two
  proposals carrying the same record id resolve last-write-wins, because
  `MemoryStore.add` is an upsert keyed on id. The loop does not de-duplicate,
  because the id is documented as the caller's idempotency key — a processor
  re-proposing an id may well mean to supersede its own earlier proposal, and both
  outcomes report that id, so the collision is visible rather than hidden."

So a repeated record id is **not uniformly a bug**. There is an accidental case (a
minting producer whose factory collides — a bug every time, blast radius one
unrelated record) and a deliberate case (a caller re-proposing an id it owns, using
it exactly as documented). A blanket insert-if-absent rule bans the deliberate case
to catch the accidental one; the withdrawn PR did precisely that. And the two cases
are **byte-identical at the seam by construction**: nothing on `MemoryUpdateProposal`
or `MemoryRecord` distinguishes them, and no store-side inference can recover the
intent from the bytes. Only the caller knows which it means.

Two facts about the tree make the resolution cheap, and both were verified against
`origin/main` before this ADR was written:

1. **The verb pair already exists and costs no read.** ADR-0046 §2 gave
   `write_atomic` a per-element `MemoryWriteMode`. A one-element batch in
   `INSERT_IF_ABSENT` mode buys the absence check with **no `get`** — the store
   enforces it inside the same transaction that writes, so the check adds no I/O
   and cannot be raced against the write it guards. In `SqliteMemoryStore`, `add`
   and `write_atomic` share `_persist_record` and embed through the same
   `_embed_one`; a single-element `UPSERT` batch differs from `add` in nothing.
   ADR-0046 §2 says so outright: "an `UPSERT` batch of one is equivalent to `add`".
2. **The destructive surface is six lines.** `MemoryStore.add` has six call sites
   in all of `src/`: three in `memory/ingest.py` (the `ACCEPT`, `STORE_TEMPORARY`
   and `REINFORCE` arms of `_apply`) and three in `testing/writer.py` mirroring
   them as contract. Every other write in the tree already goes through
   `write_atomic` with an explicit mode: `_apply_supersede`'s batch, its
   counterpart in the fake writer, and episodic capture.

Point 2 is the one that changes the shape of the answer. **Caller-declared intent
is not a new discipline being proposed here.** It is the pattern the one
non-ingestor writer in the tree already follows, with its reasoning written down.
This ADR generalises an existing precedent rather than arguing for a novelty.

## Decision

### 1. The seam is the verb, and the caller declares which one it means

> **Normative.** Every `MemoryStore` write in `src/ai_assistant/` states its
> collision intent **as a `MemoryWriteMode` at the call site**. A write that means
> to **install a new record** — one whose id was minted, derived, or received from
> a producer, and which is expected to name nothing stored — uses `write_atomic`
> with `MemoryWriteMode.INSERT_IF_ABSENT`. A write that means to **land at an id
> that already names a stored record** uses `MemoryWriteMode.UPSERT`. No write may
> rely on a default — neither `add`'s, nor `MemoryWrite.mode`'s — to resolve a
> collision it did not intend.

**`add` stays the upsert on the Protocol, and stops being how a caller here says
so.** The two are separable and this ADR separates them. `add`'s *semantics* are
unchanged and must be: ADR-0046 §2 defines `UPSERT` as "today's `add` semantics",
`MemoryStore` is a contract other implementations satisfy, and §4's refusal binds
`add` precisely because callers outside this repository exist. What changes is that
inside `src/ai_assistant/` the intent is carried by the mode argument rather than by
the method name — because `add` does not *say* what it does. A reader auditing which
writes can destroy a record can find `MemoryWriteMode.UPSERT`; they cannot find a
three-letter method name shared with every set, queue and task group in the tree,
which is also why this clause is enforced by §2 leaving no `add` callers rather than
by a structural check (§7 is explicit about that asymmetry).

This is the ruling, and everything below is either its routing, its backstop, or
an honest account of what it does not buy.

**Why declaration rather than inference.** The accidental and the deliberate case
are indistinguishable at the seam — that is established above and it is not a gap
in the current types that a field could close. A field that carried the
distinction would be `core/types.py` surface with exactly one consumer, which
ADR-0045 §1 and ADR-0028 §7 both decline. What is *not* indistinguishable is which
**verb the caller reached for**, and that is already expressible with ratified
machinery.

**Why this and not the cross-kind refusal alone.** Refusing only a cross-kind
collision leaves a same-kind `uuid4` collision destroying an unrelated belief,
returning healthy, invisible to conflict detection — which is the exact defect
#630 exists for — while presenting a shut door. That is the same "worse than the
open gap" property that sank the writer-side fix: a rule that reads as protection
without being one is worse than a documented absence, in ADR-0022 §4's own words
about the missing transaction.

**ADR-0022 §4's behaviour survives, as something a caller asks for.** §4 defended
the upsert on the ground that the collision is *visible* — "both outcomes report
that id". An explicit verb is the strongest available form of visible: after this,
a destructive write is a greppable claim (`MemoryWriteMode.UPSERT`) rather than the
silent default of every write. What §4 loses is not the deliberate re-proposal; it
is the deliberate re-proposal happening *by default* (§6).

### 2. The routing table

This is the complete `MemoryStore` write surface in `src/ai_assistant/`, and its
mode after this ADR. It is enumerated rather than described because the enumeration
is short enough to be checkable, and because a routing rule stated only in prose is
how a later caller silently picks the wrong default.

> **Normative.** The write paths route as follows. `MemoryIngestor._apply` and its
> contract mirror `FakeMemoryWriter._apply`: `ACCEPT` and `STORE_TEMPORARY`
> install with `INSERT_IF_ABSENT`; `REINFORCE` folds at the ruling's target id
> with `UPSERT`; `SUPERSEDE` is unchanged (ADR-0045 §8's batch already declares
> both modes). `ConversationCapture` is unchanged: it already writes
> `INSERT_IF_ABSENT`.

| caller | mode | why |
| --- | --- | --- |
| `_apply` → `ACCEPT` | `INSERT_IF_ABSENT` | The ruling says this proposal contradicts nothing retrieved. Landing on a stored id is therefore an accident in every case. |
| `_apply` → `STORE_TEMPORARY` | `INSERT_IF_ABSENT` | Same ruling shape, plus an `expires_at`. |
| `_apply` → `REINFORCE` | `UPSERT` | `_merge` keeps the *target's* id (ADR-0040 §3). The ruling names the record being landed on, so the overwrite is the decision, not a collision. |
| `_apply_supersede` | unchanged | Already `[UPSERT(T_closed)…] + [INSERT_IF_ABSENT(P_new)]` (ADR-0045 §8, ADR-0046 §2). |
| `ConversationCapture.record` | unchanged | Already `INSERT_IF_ABSENT`, with its reasoning in its docstring. |

**`REINFORCE` is the deliberate case, and it is the whole of it.** It is worth
being precise that this ADR does not abolish the upsert: it locates it. The one
write in the tree that means to land on an existing record is the fold, its target
is named by a ruling a policy made, and after this it says so at the call. That is
ADR-0022 §4's "a processor re-proposing an id may well mean to supersede its own
earlier proposal" — routed through the seam that actually rules on it, rather than
through a default that cannot tell it from a bug.

**`REINFORCE` moves to `write_atomic` rather than staying on `add`**, even though
`add` *is* the upsert verb, because a mode named in the call is a declaration and a
method name is not. The cost is one list wrapper and one `[0]`; the benefit is that
`src/` afterwards contains **no `MemoryStore.add` call at all**, so "which writes in
this tree can destroy a record" is answerable by grepping for one enum member. This
is the property §1 is for, and it is not obtained by leaving one caller on the
default.

**Not in this table, and why.** `memory/reembed.py` writes records with raw SQL into
a *fresh* database it is building (ADR-0104's build-and-swap). It is not a
`MemoryStore` caller, it never passes through this contract, and it copies each
row's `id` and `kind` together into an empty table — so it cannot produce a
collision of either sort and gains nothing from a rule stated here.

### 3. The insert-if-absent collision propagates; nothing is re-minted

> **Normative.** When an `INSERT_IF_ABSENT` install refuses, `MemoryIngestor`
> propagates the `MemoryStoreConflictError` unchanged. It does not re-mint the
> proposal's id, does not retry, and does not fabricate a ruling. Nothing is
> written.

`_apply_supersede` re-mints on collision, under a bounded retry (ADR-0045 §4,
ADR-0081 §4) — and that is not a precedent for this, because the id it re-mints is
one **the ingestor itself minted** for the correction. An installing arm's id is the
*producer's*. Re-minting it would edit a record the producer made, which the writer
does not do (ADR-0068's frozen graph; ADR-0081 §9 declines exactly this as
"repairing the proposal instead of refusing it"), and it would return an id the
caller never proposed.

The refusal is already the right error and needs no new class:
`MemoryStoreConflictError`'s documented meaning is "the caller minted a colliding
id and should re-mint and retry" (ADR-0046 §4, ADR-0045 §4). That is precisely the
producer's situation, and it is a `MemoryStoreError` subclass, so ADR-0028 §5's
"`MemoryStoreError` is what crosses this seam" stays true as written and every
existing `except MemoryStoreError` still catches it.

### 4. The backstop: a cross-kind collision is refused at every upsert-capable door

> **Normative.** A `MemoryStore` write whose id names a stored record of a
> different `kind` is refused with `MemoryStoreError`, and **nothing is written**.
> This binds every upsert-capable door on every implementation — `add` and
> `write_atomic`'s `UPSERT` mode alike. "Names a stored record" is physical
> presence in ADR-0046 §3's sense: an expired or window-closed row still collides.

This is ADR-0081 §8's deferred cross-kind horn, taken here (§6). It is **defence in
depth, not a rival ruling**: §1 is what closes #630, and this is what a caller that
*wrongly* claims upsert runs into. By ADR-0081 §8's own logic a cross-kind
collision can never be a deliberate supersession — the trigger §8 names for it
becoming a design is a producer deriving ids from content, and even then the
derivation is per-kind — so the refusal breaks nothing ratified. Concretely: a
caller that wrongly claims `UPSERT` still cannot vaporise a belief with an episode.

**Every door, not just `add`.** ADR-0081 §8 argued the rule belongs at `add`
because "a rule at `add` covers every caller". That is not true of this tree:
`write_atomic` is a second door into the store, capture uses it, and after §2 every
ingestor write uses it too. A rule stated only on `add` would be the same
false-shelter shape one layer up — which is the mistake this decision exists to
avoid repeating. Stating it on both doors is what makes it a floor rather than a
suggestion.

**It raises `MemoryStoreError`, and earns no new error class**, on ADR-0081 §3's
reasoning applied unchanged. `MemoryStoreConflictError` is specifically wrong here:
its documented remedy is "re-mint and retry", and a cross-kind collision is a
producer fault that a retry does not answer — the caller asked to overwrite, and
what it asked to overwrite was not the kind of thing it thought. There is no second
branch for a caller to take, and a subclass with one caller and one branch is
surface with no consumer. The message names the id, the stored kind and the
incoming kind, so the fault is diagnosable from the error alone.

**It costs no read on the shipped store.** `SqliteMemoryStore._persist_record`
already executes `SELECT rowid FROM records WHERE id = ?` to decide insert-versus-
update; the check widens that one statement to read `kind` as well. Because
`_persist_record` is shared by `add` and `write_atomic`, one refusal there covers
both doors by construction rather than by two implementers remembering. In
`INSERT_IF_ABSENT` mode the presence check has already refused any collision before
`_persist_record` runs, so the two rules cannot interact.

### 5. What the implementing lane owes

> **Normative.** The implementing lane lands, in one change: the routing of §2; the
> §4 refusal in **all three** `MemoryStore` implementations — `SqliteMemoryStore`,
> `InMemoryMemoryStore` and the canonical `FakeMemoryStore`; the amended contract
> docstrings on `MemoryStore.add`, `MemoryStore.write_atomic` and
> `MemoryWriter.ingest`; and cases in `MemoryStoreContract` pinning both verbs'
> collision behaviour, plus cases in `MemoryWriterContract` pinning the routing.

> **Normative.** §1 is enforced mechanically, not left to review: a test asserts
> that **every `MemoryWrite` construction under `src/ai_assistant/` names its
> `mode` explicitly**, over the parsed source rather than by grep. `MemoryWrite`'s
> field carries `MemoryWriteMode.UPSERT` as its default (ADR-0046 §2), so
> `MemoryWrite(record=r)` *is* a destructive write with no word in it for a reader
> to find — the second silent default, beside `add`, and the one that reaches the
> door §2 routes every ingestor write through. The default itself stays: it is
> ADR-0046's, `core/types.py` is not this ADR's to change, and removing it would
> break every construction outside this repository's own callers for a benefit a
> check on those callers already delivers.

Three backends, not two: `MemoryStoreContract` runs against `InMemoryMemoryStore`,
`FakeMemoryStore` and `SqliteMemoryStore`, and ADR-0081 §8 anticipated "the same
conformance-suite rewrite across all three backends". A refusal landed in two of
three is exactly the "consumer test passes on state the production writer refuses"
trap ADR-0045 §4 names, run in reverse.

**`MemoryWriter.ingest`'s docstring gains this refusal by name.** #734 records that
`ingest`'s Protocol docstring states the writer's obligations but not its refusals
— ADR-0078 §5b's secret-tier refusal is pinned only by the conformance suite. This
ADR does not fix that generally, but it does not add to it: the refusal §3 defines
is stated on `ingest` when it lands.

**The conformance suite pins behaviour, not mechanism.** `MemoryStoreContract` gets
cases for: an `UPSERT` at a same-kind stored id still fully replaces it (ADR-0022
§4's mechanism, unchanged and now pinned as *a mode's* behaviour); an `UPSERT` at a
different-kind stored id refuses with `MemoryStoreError` and leaves the stored
record intact; `add` behaves as `UPSERT` on both; and an `INSERT_IF_ABSENT` at a
different-kind stored id still refuses with `MemoryStoreConflictError` — the
existing rule wins there, because it refuses *earlier* and its remedy is the
narrower one.

> **Normative.** Two further conformance cases are required, because §4's two
> qualifiers are each independently satisfiable by a wrong implementation that
> passes every case above. **(a) Physical presence, on both doors**: a cross-kind
> `add` *and* a cross-kind `UPSERT` at an id held by an **expired or window-closed**
> record are each refused, and that record is still returned by `export`
> afterwards. **(b) Rollback**: a multi-element `write_atomic` whose *later* element
> is a cross-kind `UPSERT` commits **nothing**, including the valid element ordered
> before it.

> **Normative.** Every cross-kind case asserts the refusal is **not** a
> `MemoryStoreConflictError`, not merely that it is a `MemoryStoreError`. The
> conflict class subclasses the base one, so a bare `pytest.raises(MemoryStoreError)`
> passes on the very disposition §4 rules out and certifies nothing.

Neither of the two cases above is decoration, and neither is implied by the cases
before them:

- **A store can judge the collision on read-visibility** and pass every
  single-collision case, because those all use a live record. It would then let a
  preference silently replace a *retired* belief — retained history, which is the
  least recoverable thing in the store and precisely what ADR-0046 §3 made
  `INSERT_IF_ABSENT` physical to protect. §4 says "physical presence, in ADR-0046
  §3's sense" and a rule that is not tested at the only place the two senses differ
  is not a rule.
- **A store can refuse the cross-kind element and keep the earlier ones.** ADR-0046
  §4's all-or-nothing already governs this — the refusal is an element failure like
  any other — but the shipped implementation raises it from *inside* the write body
  rather than from a pre-pass, so "nothing is written" depends on a rollback that no
  single-element case exercises. This is exactly the divergence ADR-0046 §3 forbids
  between a sequential SQLite apply and a stage-then-swap fake, arriving through a
  new door.
- **A store can raise the wrong subclass and pass a base-class assertion.** §4's
  choice of `MemoryStoreError` over `MemoryStoreConflictError` is the whole of what
  it says about *remedy* — "re-mint and retry" is right for a minted-id collision
  and wrong for a caller that asked to overwrite something of a kind it did not
  expect — and it is invisible to `pytest.raises(MemoryStoreError)`. The exclusion
  is stated as "not the conflict class" rather than "exactly the base class",
  matching the two on-`main` precedents (`assert not isinstance(refusal,
  UnresolvedEvidenceError)` in `MemoryWriterContract`): it forbids the disposition
  §4 rules out, and does not forbid a future subclass some later ADR introduces
  with reasons of its own.

### 6. What this changes in ADR-0022 §4, in ADR-0046, and in ADR-0081 §8

The three get different treatments because ADR-0070 §1's test gives different
answers, and the difference is worth stating rather than assuming.

**ADR-0022 §4 — partial supersession.** §4's clause reads: "two proposals carrying
the same record id resolve **last-write-wins**, because `MemoryStore.add` is an
upsert keyed on id. The loop does not de-duplicate…". After §2, two proposals both
ruled `ACCEPT` at the same id do **not** resolve last-write-wins: the second is
refused and nothing is written. A reader acting on ADR-0022 §4 would act
differently, which is ADR-0070 §1's definition of a decision change — "any change
to what was decided requires a new ADR that supersedes the old one". It is
**partial**: only §4's same-id collision clause is replaced. Everything else §4
decides — which rulings write, what "nothing was written" means, the absent
cross-call transaction and its deferral to #104 — stands untouched, as does the
rest of ADR-0022.

The replacement is not a reversal of §4's *reasoning*. §4 wanted the collision
visible rather than hidden; this makes it visible as a refusal instead of as two
reported ids, and preserves the deliberate re-proposal §4 protected by giving it a
verb (§2's `REINFORCE` row). What is withdrawn is only that the deliberate outcome
was the **default** for a caller that intended the other one.

**ADR-0046 — partial supersession, and it is the sharper of the two.** §4's
refusal is an *addition* to what `UPSERT` does, and the repository has ruled twice
that adding a refusal is an amendment rather than a supersession (ADR-0081 §5, on
ADR-0079 §4 and ADR-0077 §5 each adding one to `MemoryWriter.ingest`). That
precedent does **not** carry here, and the reason is specific: ADR-0046 did not
merely leave the cross-kind case unmentioned, it **required the opposite outcome by
name**, in the conformance obligations its Consequences hand to the implementing
lane —

> an `UPSERT` on a **present** id **overwrites** it, exactly as a bare `add` upsert
> does — verified with an *open* replacement so `get` can see it: upsert a full,
> different-kind replacement at an existing id and assert `get` returns the
> replacement, not the prior record.

An implementation could satisfy that sentence only by breaching §4. There is no
reading on which a reader acts identically before and after, so ADR-0070 §1 makes
it a supersession, and §3 makes it a partial one: only that clause and §2's
unconditional phrasing of the same rule are replaced. Everything else ADR-0046
decides stands, and §3's physical-presence definition is not merely preserved but
**adopted** — §4's refusal uses ADR-0046 §3's sense of "names a stored record"
rather than inventing a second one, which is why an expired or window-closed row
collides on both rules alike.

The property that clause was pinning survives; only its instrument changes. It was
proving an upsert is a *full replacement rather than a merge* — every column
rewritten, not only the payload — and it reached for a kind change as the most
visible way to show it. §5 pins the same property same-kind, through the lifecycle
columns, which is if anything the sharper instrument: a store that rewrote only the
JSON blob would keep the old retention deadline and closed window, and `get` would
then answer `None` for a record that is fully open.

**ADR-0081 §8 — partial supersession, and the classification was corrected under
review.** §8's cross-kind bullet is a *deferral with an owner*, and the first draft
of this section recorded taking it as an amendment, on the reasoning that
"discharging a deferral changes no decision — §8 decided to defer, and the deferral
has now been taken, which is what a deferral is for." **That reasoning does not
survive ADR-0070 §1's test and is withdrawn.** Two clauses of §8 are things a reader
acts on and both change:

- The **deferral** itself. A reader of §8 treats the cross-kind question as open and
  does not rule it; after §4 it is ruled. "A deferral that is taken has been
  honoured" describes the *spirit* correctly and is not the test ADR-0070 §1 sets,
  which is whether the reader acts identically.
- **The owner**, which is the sharper of the two. §8 does not merely defer, it
  assigns: "Owner: the `MemoryStore` write-semantics lane, the one that takes #104's
  compare-and-swap." This ADR lands the ruling in a lane that leaves #104 untouched.
  §8's stated reason for pairing them is that the cross-kind rule "wants the same
  conformance-suite rewrite across all three backends that #104's CAS wants" — and
  that rewrite happens here anyway, for §1's sake, so pairing them again would mean
  doing it twice. That is a good reason to reassign; it is still a reassignment, and
  §5's obligations are what discharge §8's stated concern rather than what excuse
  it.

So the record on ADR-0081 is a leading-token partial supersession naming both
clauses, and #104 stays open and unclaimed by this lane.

**§8's *reasoning* is separately assessed, and where it needs correcting that part
is an amendment** — ADR-0070 §1's "reconciles the ADR … with a fact that postdates
it". Of the three grounds §8 gave, **one is stale and two stand** — which is fewer
than #630's thread concluded, and the difference is worth recording because getting
it wrong was easy:

1. **The cost ground stands, and §4 honours it rather than retiring it.** §8 wrote
   that a writer "could only enforce [it] by paying a `get(proposed.id)` on every
   ingest to see something the store sees for free while it replaces the row —
   giving up §1's no-I/O, cannot-be-raced property". That is still exactly true, and
   it is *why* §4 puts the cross-kind refusal in the store: a writer cannot learn
   the stored record's **kind** without reading it, and `INSERT_IF_ABSENT` does not
   supply it — that mode refuses *every* collision without ever reporting what it
   collided with, so it answers §1's routing question and not §8's.

   **#630's thread argued this ground had expired, and it had not.** The argument
   holds for the absence check §1 needs, which genuinely costs no read, and was
   carried across to a different rule one line away. The two are easy to conflate
   and neither buys the other: **§1's insert-if-absent costs no read at the writer;
   §4's cross-kind check costs no read at the store** — the `SELECT` that already
   chooses insert-versus-update. §8 predicted the second in the phrase "something
   the store sees for free"; §4 is that prediction taken up.
2. **The coverage ground is stale, in both halves.** §8 wrote that "a cross-kind
   collision arriving from capture would pass a writer-side rule untouched. A rule
   at `add` covers every caller; a rule at `ingest` covers one." Capture does not
   call `add` at all — it writes `INSERT_IF_ABSENT` and refuses `add` explicitly,
   for §8's own reason — so the unprotected caller §8 named had already protected
   itself. And `add` is not "every caller": `write_atomic` is a second door, which
   is why §4 binds both.
3. **The residue ground stands unchanged**, and is why this is a low-priority
   defect properly fixed rather than an incident: with ADR-0081 §1 closed, what
   remained was a silent replacement of an *unrelated* record with no fabricated
   warrant behind it.

§8's named **trigger** also fired before this lane started, which is recorded
because it means the deferral's own terms were met rather than merely outrun: #735
finds `FakeBeliefObserver` deriving record ids from a content hash, verbatim the
class §8 named as the thing that would make the question urgent, and which its
"until then no producer can collide" therefore no longer covers.

### 7. The residual, stated rather than papered over

**Caller-declared intent trusts the declaration.** A buggy caller that claims
`UPSERT` and carries a colliding minted id of the same kind still destroys a
record. Same-kind, same-id, deliberately-claimed is indistinguishable from correct
use by construction — that is what §1 establishes, and it does not stop being true
because the declaration is now explicit. This is irreducible under any
non-inferential design, and the goal is correspondingly narrower and honest:
**destruction requires an explicit, greppable claim rather than being the default
of every write.**

**There are two silent defaults, not one, and only one of them is checkable.**

The first is `add` itself: a caller added later can still reach for it and get the
old upsert. This is the real cost of ruling as §1 does rather than flipping `add`'s
default (§8), and it is the property that makes a rule read as protection while not
being one. Three things bound it, none of which abolishes it: §4's refusal binds
`add` too, so the worst outcome — an episode overwriting a belief — is closed for
every caller regardless of diligence; `add`'s own docstring, after §5, states that
its upsert is a claim and that a minted id must not use it; and `src/` contains no
`add` call after §2, so a new one is a visible addition in review rather than a line
lost among others.

The second is subtler and was nearly missed: **`MemoryWrite.mode` defaults to
`UPSERT`** (ADR-0046 §2), so `write_atomic([MemoryWrite(record=r)])` is a
destructive write containing no word a reader can grep for — and it arrives at the
very door §2 routes every ingestor write through, which is where a reader would
least expect to find the old default hiding. It differs from the first in one
respect that matters: it is **mechanically checkable**, because the construction
site names a unique type in a parseable expression. §5 therefore requires that
check rather than leaving this to the same "visible in review" argument, and this
residual is closed for this repository's own callers even though the default
remains in `core`.

**The asymmetry between the two is deliberate and is worth naming, because it looks
like an oversight.** `add` gets no equivalent structural check, and not because it
matters less. It is that "is this call `MemoryStore.add`?" is not decidable from the
source in a duck-typed tree: `add` is the name every `set`, every `TaskGroup` and
several of this repository's own collections use, and `self._store` is typed by a
Protocol at some call sites and by nothing at others. A check would either be a
name heuristic with false positives on unrelated code, or a type-directed one that
fails open exactly where a new caller is most likely to be careless. `MemoryWrite`
has no such problem — the construction names the class. So §1 is enforced by a check
where a check can be sound, and by §2 having left zero callers where it cannot: a
new `store.add(...)` line is a *visible addition* in review precisely because there
are no existing ones for it to hide among, which is a weaker guarantee than a gate
and is stated as one.

What is **not** closed by either bound is the same irreducible thing stated above: a
caller writing `mode=MemoryWriteMode.UPSERT` deliberately, at a same-kind colliding
minted id, still destroys. The check makes the claim explicit; it cannot make it
true.

**Nothing here closes the lost update.** Two concurrent ingests can still both
resolve conflicts before either writes. ADR-0046 §5 ruled that `write_atomic` does
not close it and ADR-0022 §4 says the same; #104 remains open and this ADR neither
advances nor blocks it.

### 8. Explicitly declined

- **Flipping `add`'s default to insert-if-absent**, with upsert as the explicit
  ask. It is attractive — it makes the safe case the free one and would retire §7's
  second residual — but it *silently* changes the meaning of a documented method
  for every caller outside this repository's fence and every test written against
  it, and the guarantee ADR-0022 §4 gave would become unavailable through `add` at
  all. Declining it costs one residual, honestly named; taking it would put a
  reversal of a documented contract behind an unchanged signature. It also buys
  little that §2 does not: after §2 there are no `add` callers left to protect.
- **Requiring the mode argument on `add`, with no default.** This is the strongest
  form and the most faithful to §1 — it makes ADR-0022 §4's guarantee something a
  caller *states* — but it is a Protocol **signature** change, so golden rule 5
  puts it behind its own ratified ADR. It is also exactly the shape #104's
  compare-and-swap will want, since a CAS is a third mode. Filed rather than taken
  here, so this ADR stays semantics-only and does not front-run the CAS lane's
  surface.
- **The writer-side absence check** (PR #731's shape). Rejected on ADR-0022 §4's
  ground: it bans the deliberate case to catch the accidental one, and it states a
  rule at a layer that does not own the semantics. Recorded here so it is not
  re-derived.
- **A field on `MemoryUpdateProposal` or `MemoryRecord` carrying the mint-versus-
  assert distinction.** Surface with one consumer (ADR-0045 §1, ADR-0028 §7), and
  it would put a producer's self-report where a caller's verb already says the same
  thing more strongly.
- **Refusing a same-kind collision on the upsert verb.** That is not defence in
  depth, it is §1 abolished: it removes the deliberate case ADR-0022 §4 ratified,
  which is the failure this ADR exists to avoid.

### 9. What this ADR does not decide

- **#104's compare-and-swap**, and the lost update it closes. Untouched (§7).
- **Whether `MemoryWriter.ingest`'s docstring should state its refusals
  generally** (#734). This ADR states *its own* refusal there and leaves the
  general question filed.
- **What `FakeBeliefObserver` should do about deriving ids from a content hash**
  (#735, #736). §4 makes its cross-kind case a refusal rather than a silent
  overwrite; whether a derived id is the right design for that fake is the
  observer lane's.
- **Anything about `add`'s signature.** §8 files that; it is not decided here.

## Consequences

- **The defect #630 filed is closed**, for the case it was filed about: a minting
  producer whose id collides now gets a refusal and a `MemoryStoreConflictError`
  it can act on, instead of a healthy record id and a destroyed belief.
- **`MemoryStore.add` acquires no callers in `src/` and one new refusal.** It
  remains contract surface, remains the upsert, and remains exercised by the
  conformance suite against all three backends.
- **Three ratified ADRs get Status-line edits in this change**, each a leading
  partial-supersession token with a dated note beneath it: ADR-0022 (§4's collision
  clause), ADR-0046 (the cross-kind `UPSERT` clause), ADR-0081 (§8's first deferred
  item and its owner). ADR-0081's note additionally records the two corrected
  grounds, which is an amendment riding in the same note. All are the append-only
  forms ADR-0070 §1 permits; no Decision or Consequences text is rewritten in any
  of them, and ADR-0081's leading token replaces an `Accepted` under ADR-0082 §2 —
  no prior amendment qualifier stood on that line to be moved.
- **This ADR touches more of the record than a change of its size usually does**,
  and that is the finding rather than an aside: a rule about *what a write means*
  reaches every ADR that ever described a write's collision behaviour, and three
  had. Two of the three classifications above started as amendments and became
  supersessions under review. A later ADR in this area should expect the same and
  budget for it.
- **A round trip is added to the `REINFORCE` path in name only.** `write_atomic`
  with one element embeds through the same `_embed_one` and writes through the same
  `_persist_record` as `add`; ADR-0046 §2 already ruled the degenerate batch legal
  and equivalent.
- **An ingest that would have silently overwritten now raises**, and the raise is
  a `MemoryStoreConflictError` — a `MemoryStoreError`, so ADR-0028 §5's "that is
  what crosses this seam" stays true and no existing handler is bypassed. Two
  consumers see the difference and they see it differently, which is worth stating
  because it is not uniform: `LearningLoop.learn` **propagates**, leaving earlier
  proposals applied, which is ADR-0022 §4's own documented behaviour for a store
  failure and is unchanged here; the observation stage's `_ingest` likewise
  propagates anything that is not the citation race it discriminates (ADR-0077 §5).
  So the trade is a *loud* failure where there was previously a silent data loss —
  not a degraded turn. That is the right direction for a write whose whole defect
  was that it reported success, and it is a real behaviour change for a caller that
  today gets a healthy result.
- **A producer that derives its record ids from content now collides loudly on
  re-proposal.** `FakeBeliefObserver` is exactly that producer (#735, #736) and is
  the only one in the tree; the shipped `learning/observer.py` mints. What it was
  doing before was silently replacing its own earlier records — the fold its
  docstring promises never fires, because conflict detection filters the proposal's
  own id (#110). This ADR does not decide what that fake should do instead (§9);
  it makes the existing gap audible rather than creating one.
- **The next lane that adds a `MemoryStore` caller has a table to consult**, and a
  conformance suite that will fail it if it picks the wrong verb for a cross-kind
  write. It will not fail it for picking the wrong verb for a same-kind one — §7's
  residual, which is the price of not inferring intent.

## Alternatives considered

**Do nothing, on the priority argument.** #630 files itself as low priority: the
probability is a `uuid4` collision and the blast radius is one unrelated record.
The counter is #735 — a producer deriving ids from a content hash already exists,
which is the trigger ADR-0081 §8 named for the question becoming urgent — and the
fact that the fix is now six call sites and one widened `SELECT`, because ADR-0046
already paid for the machinery. A defect this cheap to close does not stay open on
a probability argument.

**Rule the cross-kind refusal only, and leave §1 for later.** This is ADR-0081 §8's
literal deferral and the smaller change. Rejected in §1: it leaves the same-kind
case — the one #630 reproduced — silently destructive behind a door that now looks
shut. It also does not avoid the work, since the conformance rewrite is the same.

**Rule §1 only, and leave the cross-kind horn deferred.** Tempting, because §1 alone
closes #630 and the backstop protects against a caller bug rather than a design gap.
Rejected because §4 is nearly free once §5's conformance rewrite is happening
anyway, because it is the one part of this that holds against a caller that gets §1
wrong, and because leaving ADR-0081 §8's deferral standing with its coverage ground
known-stale would leave a stale argument in the record — which is the same failure
#630's own thread corrected, and which §6 shows this ADR then committed once itself
about §8's *cost* ground before review caught it.
