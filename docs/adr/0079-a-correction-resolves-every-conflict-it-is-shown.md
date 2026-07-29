# 79. A correction resolves every conflict it is shown, or it does not land

- Status: Proposed
- Date: 2026-07-28
- **This ADR partially supersedes [ADR-0050](0050-resolving-the-full-contradiction-set.md)**,
  in the scope named in §5: **§1's over-limit surplus clause** (the paragraph
  headed *"Full" is bounded by conflict detection; the over-limit surplus is a
  filed residual*, the paragraph beginning *"The surplus does not self-heal by
  re-proposal"*, and the Consequences restatement *"a surplus beyond the cap
  stays live as a bounded, filed residual"*). Everything else ADR-0050 decided
  stands and is untouched: §1's full-set retirement ruling and its precise
  definition of the conflicting set, the `_SUPERSEDABLE` allow-list and the two
  sources deliberately held out of the widening, the applier-rather-than-
  `target_ids` reasoning, the single-atomic-batch property, **all of §2**
  (assertion-versus-assertion defers to the user), and §3's other deferrals.
  ADR-0050's Status line records the supersession per ADR-0070 §4; **no ratified
  body text of ADR-0050 is rewritten** (ADR-0070 §1). **Both files land in one
  change**, so ADR-0050's Status never points at an ADR that is absent — the
  hazard ADR-0070 §1 guards against is unreachable when the pair is atomic, and
  ADR-0005 already carries `Partially superseded by ADR-0075` and did so while
  ADR-0075 was still `Proposed` (ADR-0076's header records that precedent). The
  `Proposed` → `Accepted` flip is the ratifying edit at merge (ADR-0015 §5;
  `CONTRIBUTING.md`, "Trivial ADR edits").
- **This is a contract change** (golden rule 5), and a narrow one. It adds **no
  Protocol**, **no `core/types.py` type**, and **no `core/errors.py` class**. It
  changes one Protocol's *documented semantics* — `MemoryWriter.ingest` in
  `core/protocols.py` gains one obligation and one raise clause (§4) — and it
  promotes an obligation into the **shared `MemoryWriter` conformance suite and
  the canonical `FakeMemoryWriter`** (§3), which is the contract-surface change
  issue #314 names and ADR-0050 §3 reserved to its own lane. It therefore ships
  as **its own docs-only PR**, reviewed while still `Proposed` so a finding can
  still change the decision, and is flipped to `Accepted` on merge
  (`CONTRIBUTING.md`, "Contract ADRs land before their implementation"). **No
  code changes with it**; the detector, the applier, the suite and the fake are
  the next lane (§4).
- **Refs:** ADR-0050 (the law this ADR completes — §1's full-set retirement and
  its `conflict_limit` bound, §2's `ASK_USER` gate, §3's deferrals), ADR-0045 §4
  (window-closing supersession), §5 (clause 1 and the signal-strength floor), §6
  (read-time liveness; `export` keeps a closed window), §7 (#244/#245 unblocked),
  §8 (the atomicity floor), ADR-0046 §3 (`write_atomic` all-or-nothing, repeated
  id is a hard error), ADR-0040 §1 (a ruling names the relation), §5a/§5b (the
  differential writer obligations), ADR-0038 §2a/§3/§5 (the supersession
  asymmetry and the allow-list argument), ADR-0072 §2 (the three bands),
  ADR-0028 §4/§8 (the writer seam, the conformance suite, the canonical fake),
  ADR-0056 (the universal-obligation promotion it declined, "the shape of issue
  #314"), ADR-0065 (`core/protocols.py`'s input-observation clause), ADR-0005 §3
  (the model proposes, a deterministic policy disposes), ADR-0070 §1 (the
  amend-versus-supersede test applied in §5) and §4 (the status vocabulary),
  ADR-0073 §1 (the "semantics are the contract, spelling is the lane's" form),
  the roadmap's leg 4 (the exit test this ADR half-discharges); issues #313 and
  #314 (the two questions decided), #306, #423, #457 (the retrieval-side residual
  §1 names and declines to close), #411.

## Context

ADR-0050 closed the honesty gap #244 reported: a `SUPERSEDE` no longer retires
only the best-ranked conflicting inference, it retires the **full supersedable
conflict set**, in one atomic batch. It closed that gap only as far as detection
reaches, and said so plainly:

> The set is the full *detected* conflict set, which `_detect_conflicts` caps at
> the configured `conflict_limit` (default 5) … So when more than
> `conflict_limit` inferences match one correction, this supersession retires
> exactly `conflict_limit` of them and the surplus stays live.

and filed the remainder:

> The over-limit boundary and this residual are pinned by a regression test and
> **filed** as issue #313; they are not resolved here.

It filed a second question the same way — whether the full-set retirement should
become a **universal** `MemoryWriter` obligation, with the shared conformance
suite driving a multi-conflict `SUPERSEDE` and the canonical `FakeMemoryWriter`
matching (§3, issue #314) — because that is a contract-surface change and
ADR-0050 was fenced to the policy lane. ADR-0056 declined the same promotion for
its own case in the same words, calling it "the shape of issue #314".

This ADR decides both. Three things make now the moment.

**The residual is about to stop being exotic.** ADR-0050's cap-of-N behaviour is
a strict improvement on the pre-ADR one-of-N, and with today's producers — an
explicit `assistant learn` correction against a handful of records — six
above-threshold same-kind conflicts on one topic is rare. The observer (leg 3,
ADR-0077, in flight in a parallel lane) is a model-backed producer whose whole
job is to mass-produce `OBSERVED`/`INFERRED` beliefs from the episode stream.
Those are exactly the low-confidence, topically-clustered, mutually-reinforcing
records that make a single correction contradict dozens. The roadmap puts leg 4
— "epistemic soundness" — *before* the observer runs at volume for this reason,
and names its exit test in product terms: **"a conflicting or many-conflict
correction leaves the store consistent, and a deferred question reaches the user
instead of vanishing."** The second half is #423's, in flight as ADR-0078. The
first half is this ADR's.

**The residual does not drain.** ADR-0050 §1 already established this and it is
worth restating, because it is what rules out "leave it, it will heal":

> once the correction lands as a `USER_ASSERTED` record, a re-proposal of the
> same correction sees *it* as an asserted conflict and defers (`ASK_USER`, §2),
> so the surviving inferences are not swept on a second pass.

A surplus, once created, is permanent under every mechanism the system has today.
It is not a lagging indicator that a later write corrects; it is a monotone
accumulation of beliefs the user has explicitly denied. That is precisely the
dishonesty ADR-0050's own Context says "the moat cannot carry".

**The cap defeats more than the retirement set.** Reading ADR-0050 §1 and §2
together surfaces something neither issue records. `DefaultMemoryPolicy`'s
assertion gate is a predicate over the conflict set it is *handed*:

> if a user-asserted proposal conflicts with any existing `USER_ASSERTED` record,
> rule `ASK_USER`

Since the same `conflict_limit` truncates that set, a prior user assertion that
happens to rank *below* the cap is invisible to the gate. A user correcting
something they told us before, on a topic the observer has covered with six or
more higher-ranked inferences, is ruled `SUPERSEDE` rather than `ASK_USER` — and
the profile silently commits the self-contradiction ADR-0050 §2 exists to
prevent. The same truncation hides an asserted conflict from `DefaultMemoryPolicy`
rule 2 (an inference conflicting with an assertion), with the same effect. The
cap is therefore not only a bound on *how much* a correction cleans up; it is a
bound on *which ruling is reached at all*, and that is a soundness defect rather
than a bounded residual.

The forces. Against any widening, ADR-0050 §1's ratified reasoning stands and is
correct: `conflict_limit` is a safety knob (`_check_tuning` "refuses to disable
it"), and "an unbounded supersession sweep would be a denial-of-service surface
on a single ingest". Against leaving it, the three facts above. In favour of
being able to move at all: everything the widening would retire is **DERIVED**
band (ADR-0072 §2) — `OBSERVED`/`INFERRED`, the `_SUPERSEDABLE` set — where
retirement is a window close, non-destructive, and retained in `export`
(ADR-0045 §4/§6). Nothing in the user's own word is at risk; clause 1 stands
untouched, and ADR-0050 §1's exclusion of `USER_ASSERTED` and `EXTERNAL`
siblings from the widening is not reopened here.

## Decision

### 1. A ruling is made on every conflict retrieval surfaces, or the ingest refuses (#313)

**We will re-found `conflict_limit` as a ceiling rather than a truncation.**

Conflict detection reads the store once, as it does today, and can distinguish
"retrieval surfaced at most `conflict_limit` conflicts" from "it surfaced more".
Then:

- **At or below the limit**, the detected set is handed to the `MemoryPolicy`
  **whole** — nothing the detector holds is discarded — and a `SUPERSEDE` retires
  the whole supersedable part of it, exactly as ADR-0050 §1 already rules.
- **Above the limit**, the ingest **refuses**: it raises `MemoryStoreError`,
  writes nothing, closes no window, and asks the policy for no ruling.

The law this states, in one sentence: **a correction resolves every conflict it
is shown, or it does not land.** That phrasing is ADR-0050 §1's own — it fixed
the honest form of the claim as "a `SUPERSEDE` retires *every conflict it is
shown*, not 'every conflict that exists on the topic'" — and this ADR keeps it
verbatim while changing what "shown" means and removing the silent discard.

**What is closed, and what is not.** Two distinct things could leave a
contradicting belief live after a correction, and they have different owners:

- **The writer discarding evidence in hand.** Detection retrieves a set and the
  writer keeps the top `conflict_limit`, silently dropping the rest. This is
  #313's defect, and it is closed **completely**: the surplus is not made smaller,
  it is made unreachable, because the only state that produces one is the state
  the ingest now refuses.
- **Retrieval never surfacing the record at all.** `MemoryStore.search` is a
  bounded retrieval and this ADR does not make it exhaustive (below). A conflict
  retrieval does not return is a conflict nothing in this path can act on.

This ADR closes the first and is explicit that it does not close the second. The
second is a pre-existing property of retrieval that bounds ADR-0050's status quo
identically — its cap-of-five is subject to it too — and it is filed with its own
owner (§6).

**Why one knob and not two.** The obvious alternative is to keep
`conflict_limit` as the deliberation budget and add a second, larger
`retirement_limit` for the sweep. It is rejected because it does not close the
soundness half: a policy still shown only the top five still cannot see an
asserted conflict ranked sixth, so ADR-0050 §2's gate stays defeatable and the
fix would have to add band-aware truncation on top — three concepts where one
suffices. One ceiling means the policy always rules on the whole truth, and
`_check_tuning` keeps one number to validate.

**Deliberation cost is the policy's to bound, not the writer's.** The reason to
cap what a policy sees was never correctness; it was cost, for an injected
policy that might be model-backed (`ingest`'s docstring already warns that "a
policy that blocks on I/O therefore blocks other ingests"). But the writer cannot
know *which* conflict changes a ruling — that is the policy's own rule set, which
is exactly why `DefaultMemoryPolicy`'s gate broke when the writer truncated for
it. A policy that cannot afford the whole set may narrow its own view, because
only it knows which members are fungible. The writer's obligation is to hand over
everything it retrieved or to refuse; it is not to guess which part matters.

**Why refuse rather than truncate loudly.** The third option is to keep
truncating, land the correction, and report on `MemoryIngestResult` that the
retirement set was incomplete. It is rejected on this codebase's settled posture:
a write that loses data while reporting success is worse than one that stops
(`_refuse_unsafe_fold`'s stated reason), and `_check_tuning` exists precisely to
refuse a configuration that would "disable a stage while looking healthy" rather
than let it "surface as behaviour". A flag saying "I have committed your
correction and I am still holding beliefs that contradict it" is that shape: it
converts a correctness defect into a field, and it is honest only if something
reads it, which nothing today does. It also grows `core/types.py` for a state we
have decided should not exist.

**The refusal is a circuit breaker, and the ceiling must be set as one.** This is
the same instrument `_MAX_SUPERSEDE_ATTEMPTS` already is — "the bound exists to
make a *pathological* id factory fail loudly rather than spin". The default
`conflict_limit` of 5 was chosen as a truncation budget and is far too low to
serve as a ceiling; under this ADR the implementing lane raises it to **100**, an
order of magnitude past any ordinary correction and still a bounded batch. Above
100 same-kind records scoring at or above `conflict_threshold` (default 0.75)
against one proposal, the store is not holding a topic — it is holding a
runaway, and a correction is the wrong moment to discover that quietly.
`_check_tuning`'s floor of 1 and its refusal of non-integer and `bool` values
stand verbatim, and its ratified rationale survives unchanged: `conflict_limit=0`
still "hands the policy no conflicts, so every proposal is ruled on as though
nothing contradicted it".

**What this does not change.** ADR-0050 §1's ruling on *which* conflicts a
`SUPERSEDE` retires is untouched: the named `target` plus every other conflict
whose source is in `{OBSERVED, INFERRED}`, with `USER_ASSERTED` and `EXTERNAL`
siblings excluded for the standing reasons ADR-0050 gives. The retirement remains
**one atomic batch** — `[UPSERT(closed) for each retired] + [INSERT_IF_ABSENT(correction)]`
through `write_atomic` (ADR-0046, ADR-0045 §8) — so a failure part-way still
leaves every target live and unchanged. `MemoryIngestResult.record_id` is still
the correction's freshly-minted id. `MemoryDecision.target_id` still names one
primary and is still not grown to a list (ADR-0050 §1, §3).

**What the claim rests on, and the one thing it must not claim.**

- **It is a bound, not a loop.** The detector performs the same single
  `MemoryStore.search` it performs today, with a wider limit and an overflow
  probe. There is no iteration, so there is no termination argument to make and
  no dependence on the store's read clock — the objection that sinks
  "re-search until exhausted" (below). The existing over-fetch-by-one for the
  proposal's own record must be preserved *in addition to* the overflow probe;
  the arithmetic is the lane's, in ADR-0074 §9's form — the semantics here are
  the contract, the spelling is not.
- **It rests on `search` being ranked.** `MemoryStore.search` returns "the
  records most relevant to `query`, best first" (`core/protocols.py`), so among
  the rows it *does* return, one scoring below `conflict_threshold` proves no
  later returned row scores at or above it. This is the identical property
  `_detect_conflicts`'s existing over-fetch already assumes; this ADR names it as
  a dependency rather than leaving it implicit.
- **It must not claim that retrieval is exhaustive, because it is not.**
  `MemoryStore.search` bounds nothing about records it never returns, and the
  durable store is concretely bounded: `SqliteMemoryStore` applies the kind,
  expiry and window filters *after* a KNN of `limit * _RESULT_OVERFETCH` (8),
  clamped to sqlite-vec's `k` ceiling of 4096, and its own comment records the
  consequence — "a caller can still be under-served if more than this multiple of
  `limit` nearer neighbours are all filtered out". Retired records are filtered in
  exactly that pass, so a well-corrected topic accumulates precisely the
  filtered-out neighbours that consume the headroom. A `SUPERSEDE` therefore
  retires every conflict **retrieval surfaced**, at a ceiling two orders of
  magnitude above ADR-0050's cap and with no writer-side discard — and that is the
  whole of the guarantee. Making retrieval itself threshold-complete is a
  `MemoryStore` obligation and a sqlite-vec engineering problem, out of this ADR's
  lane and filed as issue #457. Stating the limit here is not a hedge: an ADR that promised
  absolute completeness would be promising something no store on this contract
  delivers, and the conformance suite — which drives `FakeMemoryStore` — could not
  detect the difference.
- **It adds no observation of the caller's proposal.** The detector's read is the
  one `ingest` already makes, against the single deep copy taken on the
  coroutine's first executed line (`core/protocols.py`'s input-observation
  clause, ADR-0065; the same discipline ADR-0056 fixed on the store's write
  paths). Widening a limit changes no observation point, so nothing here
  reintroduces the desync ADR-0065 closed: "beliefs retired over a statement that
  was never stored."

**The refusal precedes every ruling, deliberately.** It fires in detection, so an
over-ceiling proposal reaches no `MemoryPolicy` at all — it is not accepted, not
reinforced, not stored temporarily, and not deferred. The statement being made is
that the ingest's *inputs* cannot be trusted, which is a construction-time-shaped
claim, not an outcome the policy should be asked to weigh; `_check_tuning` refuses
bad tuning at construction for the same reason. One consequence is worth naming:
a secret-tier proposal, which rule 1 would otherwise defer, is refused instead.
That is accepted — both write nothing, and an error the operator sees is a better
outcome than a deferral raised against a store whose conflict set could not be
read soundly.

### 2. Completeness precedes the ruling; a deferral wins over the sweep

The ordering is fixed here, abstractly, because a many-conflict correction can
itself be one ADR-0050 §2 rules `ASK_USER`:

1. **Completeness.** Detection hands over everything retrieval surfaced, or the
   ingest refuses (§1). No ruling is ever made on a writer-truncated set.
2. **The ruling.** The policy rules on that whole set. ADR-0050 §2's gate
   therefore fires whenever *any* surfaced conflict is `USER_ASSERTED` —
   including one that would previously have ranked below the cap and been
   discarded before the policy saw it. A
   many-conflict correction that also contradicts a prior assertion is
   `ASK_USER`, **not** `SUPERSEDE`.
3. **Retirement.** Only a `SUPERSEDE` retires anything. `ASK_USER` writes nothing
   (existing applier behaviour, ADR-0050 §2), so no window is closed and no set is
   swept. A deferred many-conflict correction leaves the store exactly as it was.

**The deferral wins, and nothing is retired on its way.** This is the ordering,
not a tie-break: the applier acts only on the ruling the policy actually made, and
a policy that ruled `ASK_USER` authorised no retirement at all. Retiring "the
uncontroversial inferences anyway, while we ask about the assertion" is
specifically refused — it is ADR-0050 §2's rejected mixed case one layer down,
and it would commit part of a correction the user has not yet confirmed.

**What the resolution mechanism inherits, and what it does not get from here.**
Surfacing an `ASK_USER`, holding it durably, and applying the user's answer is
**ADR-0078's** (in flight in a parallel lane, closing #423). This ADR designs none
of it and names exactly one thing that binds it: **whatever commits an `ASK_USER`
resolution as a `SUPERSEDE` carries §1's obligation, at §1's own reach and not
beyond it.** Resolving a deferral may not land a correction that leaves live a
derived conflict its own conflict resolution surfaced, and it may not sidestep
the ceiling by writing through a path that skips conflict resolution altogether.
It is *not* held to more than §1 delivers: an above-threshold conflict retrieval
never surfaced is invisible to a resolver exactly as it is to an ingest (#457),
and no obligation stated here can be discharged against it. If ADR-0078 chooses
to resolve by re-ingesting the held proposal, it inherits §1 and its reach
together; if it chooses to commit directly, §1 is the constraint it must satisfy
by other means, and it owes the argument. Nothing else about the mechanism is
decided here.

### 3. The full-set retirement becomes a universal `MemoryWriter` obligation (#314)

**We will promote it.** A `SUPERSEDE` retiring every supersedable record in the
conflict set the policy ruled on — not only the named `target` — becomes an
obligation of the `MemoryWriter` contract, driven by the shared conformance suite
and matched by the canonical `FakeMemoryWriter`.

ADR-0050 §1's reason for leaving it alone was accurate and is now spent:

> The conformance suite pins that a `SUPERSEDE` *retires the target* and writes a
> new-id correction; it does not pin that the target is the *only* record
> retired.

True, and it made the widening legal without a contract lane — which is what
ADR-0050 needed. What it bought is a **silent divergence**: `MemoryIngestor`
retires the set, `FakeMemoryWriter._apply_supersede` retires one record, and both
pass the suite. That is the exact failure the canonical fake exists to prevent and
which its own docstring names — a consumer's test passing "on state the production
writer refuses" — with the sign reversed: here the consumer's test passes on state
the production writer would never *produce*. An `orchestration` test that corrects
a belief against the fake sees one retirement where production performs N, so the
subsystem that owns the pipeline cannot observe the property leg 4 is measured on.

Three further reasons the balance has moved:

- **§1 widens the divergence.** After this ADR the fake would also not refuse an
  over-ceiling ingest, so the two writers would disagree about whether a write is
  *possible*, not merely about how much it cleans up. A disagreement about
  refusal is not tuning under any reading.
- **It is a relation, not a mechanism.** ADR-0040 §1 fixed that a ruling "names
  the relation the policy asserts, never the write it causes", and §5a already
  promoted the differential *relation* obligations (`SUPERSEDE` carries nothing of
  the target; `REINFORCE` retains both evidences) to the contract. "Overturns the
  belief the conflict set holds" is the same kind of statement, and ADR-0050 §1
  derives the widening from precisely that sentence. Pinning it is completing
  §5a, not adding a new class of obligation.
- **The line the suite draws is unchanged.** The suite deliberately does not pin
  "the conflict threshold, the conflict limit, the constructor's tuning check, or
  — for `REINFORCE` — which content wins and how confidence combines". None of
  those moves. What is promoted is *which records a ruling reaches*, which is the
  same axis §5a already occupies, and — for §1 — that exceeding whatever limit a
  writer carries refuses rather than truncates. The **value** of the limit and its
  default stay tuning and stay unpinned; only the behaviour at the boundary
  becomes contract.

### 4. The contract surface owed

Stated at ADR-0074 §9's level of precision. No code is written here; the
semantics below are the contract, the spelling is the implementing lane's
(ADR-0073 §1's form).

**`core/protocols.py` — `MemoryWriter.ingest`, documented semantics only.** No
signature change, no member, no new Protocol, no `core` type. Two clauses:

- the `SUPERSEDE` obligation — a supersession retires **every** supersedable
  record among the conflicts the ruling was made on, not only the `target_id` the
  ruling names, in one atomic unit with the correction;
- the raise clause — `MemoryStoreError` when conflict resolution **surfaces** more
  conflicts than the writer will resolve in one ingest, with nothing written and
  no ruling sought. Stated on what the writer retrieved, not on what the store
  holds, because the writer can only observe the former (§1). This is flagged
  under golden rule 5 as a semantics widening rather than
  waved through as a no-op, the treatment ADR-0074 §9 gave `Planner.plan`'s
  `memories` parameter.

`MemoryStore`, `MemoryPolicy` and `MemoryDecision` are **untouched**. In
particular `MemoryPolicy.decide` gains no obligation: it may be handed a larger
`conflicts` sequence than before and it is free to narrow its own view (§1).

**`tests/memory/memory_writer_contract.py` — the shared suite gains obligations.**

1. **A multi-conflict `SUPERSEDE`.** A conflict set holding the ruling's named
   target plus at least two further supersedable conflicts, one `USER_ASSERTED`
   sibling and one `EXTERNAL` sibling. Pinned: every supersedable conflict is
   retired — window closed, absent from `get`/`search` read from a clock at or
   after the close (`_AFTER_CLOSE`, the existing device), present in `export`
   (ADR-0045 §6); the asserted and external siblings are **left live**
   (ADR-0050 §1's two held-out sources); `record_id` is the correction's fresh id
   and names none of the retired records.
2. **All-or-nothing across the whole set.** With an always-colliding id factory,
   **every** target is left live and unchanged — the existing single-target case
   generalised, pinning ADR-0045 §8's floor at N.
3. **The minted id may name no retired record.** The existing "re-mints when the
   minted id is the target itself" case generalised to the retirement set, since
   a repeated id in the batch is `write_atomic`'s hard error rather than the
   retryable conflict a re-mint handles (ADR-0046 §3).
4. **Resolve-or-refuse.** With the writer's limit driven low and more conflicts
   than that planted, `ingest` raises `MemoryStoreError`, nothing is written, no
   window is closed, and the policy is not asked. The obligation is stated
   relative to *the writer's own* limit, so no value is pinned. It is also stated
   on the conflicts the writer's own retrieval surfaced, which is all a suite
   running over `FakeMemoryStore` can observe — the durable store's retrieval
   headroom is a different obligation with a different owner (§1, §6).

**`WriterFactory` gains one optional, keyword-only seam: the conflict limit.**
Exactly the argument the suite already makes for `id_factory` — "most obligations
do not care …, but the four id-factory cases drive it deterministically, so the
factory must reach the writer's constructor". Obligation 4 is not observable
without it. `None` leaves the writer's own default, so existing subclasses need
no change beyond adopting the new parameter, and the suite's standing refusal to
pin the limit's *value* is preserved: it sets one to make a boundary observable,
it asserts nothing about what the value should be.

**`src/ai_assistant/testing/writer.py` — `FakeMemoryWriter` matches.** Its
supersession applier takes the retirement set rather than a single target, and
its conflict resolution carries the overflow probe and the refusal. Both are
**duplicated from `MemoryIngestor`, not imported** — the standing reason its
`_refuse_unsafe_fold`, `_close_window` and `_checked_id` are already duplicated:
the fake must not reach into the `memory` subsystem (golden rule 1) while owing
the same behaviour.

**`src/ai_assistant/memory/` — the production side.** `_detect_conflicts` widens
its read and refuses above the ceiling; the default limit rises to 100.
`_retirement_set` and `_apply_supersede` need **no change at all** — nothing is
discarded before them, so ADR-0050 §1's applier already retires the whole set it
is handed. `DefaultMemoryPolicy` is unchanged; its two asserted-conflict gates
simply stop being defeatable by the writer's own truncation. The existing
regression test
`test_a_correction_retires_at_most_the_conflict_limit_leaving_a_bounded_surplus`
is retargeted from "a bounded surplus stays live" to "the over-ceiling ingest
refuses and writes nothing" — the same boundary, the opposite ratified outcome.

**No new error class.** The refusal raises `MemoryStoreError`, which is what every
other writer-boundary refusal raises (`_refuse_unsafe_fold`, `_close_window`,
`_checked_id`) and what `MemoryWriter.ingest` already documents. A distinguishable
subclass — so an interface can render "this topic is too tangled to correct
safely" differently from a backend failure — is **not** decided here (§6); adding
one later is additive under `except MemoryStoreError` and needs no decision
reversed.

### 5. How this stands to ADR-0050 under ADR-0070 §1

ADR-0070 §1's test: "Any change to what was decided requires a new ADR that
supersedes the old one — wholly, or partially (§3). A change to what was decided
is anything a reader would act on differently." Applied honestly, the two halves
of this ADR fall on **opposite sides** of that line, and saying so is the
self-consistency check ADR-0070 invites.

**§1 (#313) is a partial supersession.** A reader of ADR-0050 §1 holding the
detector writes a truncating read and accepts a live surplus; a reader of this
ADR writes a refusing ceiling and accepts none. They act differently. More
decisively, two ratified sentences of ADR-0050 become **false** rather than
merely incomplete:

- §1: "when more than `conflict_limit` inferences match one correction, this
  supersession retires exactly `conflict_limit` of them and the surplus stays
  live" — after this ADR it refuses instead;
- Consequences: "a surplus beyond the cap stays live as a bounded, filed
  residual (§1)" — after this ADR no such state exists.

A false ratified sentence is not reconcilable by an appended note, which is what
ADR-0070 §1 reserves amendment for ("a reader acting on the ADR would act
**identically** before and after"). It is tempting to argue the clause was never
binding, since ADR-0050 says of the residual "they are not resolved here" and
even names "a larger `conflict_limit` (widening what one ingest sees)" as one of
the two routes out. That argument is rejected on ADR-0075's adjudication of the
same shape (#442): the test is applied as written, "regardless of how good the
reinterpretation's argument is". ADR-0050 anticipated the route; it did not
anticipate the refusal, and it described the interim behaviour as ratified fact.

The supersession is **narrow, and deliberately so**. ADR-0050 §1's ratified
rejection of "an unbounded re-search" is **not** superseded — it is honoured: §1
is a single bounded read with a refusing ceiling, not a sweep, so the
denial-of-service surface ADR-0050 names never opens. The `_SUPERSEDABLE`
allow-list, the two held-out sources, the applier-not-`target_ids` route, the
atomicity floor, and the whole of §2 are untouched and remain the operative law.

**§3 (#314) is a new decision, not a supersession.** ADR-0050 §3 names this exact
question and reserves it — "Filed as issue #314; it is a contract-surface change
in its own lane" — and §1's observation that "the suite and the canonical
`FakeMemoryWriter` are unchanged and both remain conforming" is stated as a
consequence of *not deciding it*, scoped to the suite as ADR-0050 left it. A
reader acting on ADR-0050 leaves the fake alone because ADR-0050 changed nothing
there, not because ADR-0050 ruled it must never change; the ADR points at the
lane that would. This is ADR-0073's shape — "settles what ADR-0072 left open and
changes no clause it closed" — and no ADR-0050 sentence becomes false. ADR-0056's
identical deferral is likewise settled, not superseded: it declined to
universalise its own snapshot obligation and named "the separate contract lane
(issue #314's shape)"; that lane now exists for the retirement obligation, and
ADR-0056's own snapshot question stays open (§6).

The status line ADR-0050 receives is ADR-0070 §4's leading-token form on one
physical line, with a scope that names a clause and carries no `ADR-NNNN` token:
`Partially superseded by ADR-0079 (§1's over-limit surplus clause)`.

### 6. What this ADR does not decide

- **Whether `MemoryStore` retrieval owes threshold-completeness** (issue #457).
  This ADR removes the *writer's* truncation and is explicit that it cannot make
  retrieval exhaustive (§1): `SqliteMemoryStore` post-filters after a bounded KNN
  and documents that it "can still be under-served", and no rule above the store
  can distinguish "there are no more" from "the nearer ones were filtered out".
  Closing that needs either a new `MemoryStore` obligation — a Protocol change,
  so its own ADR under golden rule 5 — or SQL-side pre-filtering, which is a
  sqlite-vec engineering question. Both are a store lane, not this one; #457
  carries the options and the regression it needs. Until then, an unsurfaced
  conflict can still leave a stale derived belief live *and* can still hide an
  asserted conflict from ADR-0050 §2's gate — a smaller residual than #313's, on
  a different axis, and one that bounds ADR-0050's status quo identically.
- **Retirement semantics for a producer-set bounded validity window** — clamp,
  refuse, or never-lived (issue #306, a **queued separate ADR**). Deliberately
  not absorbed. `_close_window`'s two ratified floors — never extend, never write
  an unrepresentable window — stand verbatim and now apply across N targets
  instead of one, which changes neither floor. #306 also owns the absolute,
  clock-coherence-independent hide guarantee; §1 leaves read-time-relative
  liveness exactly as ADR-0045 §6 has it.
- **The `ASK_USER` resolution mechanism** — surfacing a deferral, holding it
  durably, resuming it, and applying the user's answer (issue #423). **ADR-0078**
  owns it, in flight in a parallel lane; §2 states only the ordering and the one
  obligation any resolution inherits.
- **Observer volume, pacing and batching** — how often the observer proposes, and
  any batched or background retirement outside a single ingest. That is leg 5's
  hub and its internal scheduler; ADR-0077 owns what the observer proposes and
  ADR-0072 §3 already fixes the band and confidence obligations it produces under.
- **A distinguishable error subclass** for the refusal (§4). Deferred until an
  interface needs to render it differently, plausibly with ADR-0078's surface.
- **Whether the default policy adopts `EXTERNAL` supersession.** Untouched, as
  ADR-0050 §1 left it and ADR-0045 §5/§7 before it. `EXTERNAL` conflicts are still
  never swept in; they do, however, count toward §1's ceiling (Consequences).
- **Growing `MemoryDecision.target_id` to a list.** Still rejected, on ADR-0050
  §1's reasoning, which §1 leaves intact.
- **`MemoryStore` call-time-snapshot as a universal obligation** (ADR-0056's own
  deferral). A different obligation on a different Protocol; this ADR promotes
  only the retirement one.

## Consequences

- **The write path stops discarding contradictions it is holding.** Leg 4's exit
  test, first half, is discharged for the many-conflict case *to the reach of
  retrieval*: a correction retires every conflict detection surfaced or it does
  not land, and both outcomes leave the store consistent with what the ingest
  saw. What remains is not a writer-side surplus but a retrieval gap, filed as
  #457 with its own owner (§6). The second half — "a deferred question reaches
  the user instead of vanishing" — remains ADR-0078's.
- **Two existing gates stop being defeatable by truncation.** Because the policy
  now rules on everything detection surfaced, ADR-0050 §2's
  assertion-versus-assertion `ASK_USER` and `DefaultMemoryPolicy` rule 2's
  inference-versus-assertion `ASK_USER` fire on a surfaced asserted conflict
  wherever it ranks, instead of only when it ranks in the top five. This is a
  soundness fix neither #313 nor #314 records, and it is the strongest reason §1
  chose one ceiling over two budgets. It is not made *undefeatable*: an asserted
  conflict retrieval never surfaces is still invisible (#457).
- **Corrections read more of the store.** Every ingest's conflict search fetches
  up to the ceiling rather than six rows, and a policy may be handed up to 100
  conflicts. `DefaultMemoryPolicy` costs two linear scans over that, which is
  nothing; an injected model-backed policy may want to narrow its own view, and
  §1 says that is its call. The batch a `SUPERSEDE` writes is bounded by the same
  ceiling.
- **A pathological topic now fails a correction rather than half-applying it.**
  Above the ceiling the user's correction raises instead of landing. This is the
  chosen trade (§1) and it is loud, tunable, and recoverable — but it is a real
  user-visible failure mode, and the ceiling's default is what keeps it
  pathological rather than routine. It also fires **band-blind**: more than 100
  above-threshold same-kind `EXTERNAL` conflicts refuses a correction even though
  none of them would ever be retired. That is accepted for one number with one
  meaning, and it is the thing to revisit if the deferred `EXTERNAL` supersession
  choice (ADR-0045 §5/§7) is ever made.
- **`FakeMemoryWriter` and `MemoryIngestor` stop diverging on supersession.** A
  consumer's test — `orchestration`'s above all — sees the same retirement set
  the production writer produces, and the same refusal. The cost is the standing
  one ADR-0028 records: the fake carries a fourth duplicated helper set, kept
  honest by the suite rather than by import.
- **The `MemoryWriter` contract gains semantics without gaining surface.** No
  Protocol member, no `core` type, no error class. The reviewable unit is one
  docstring, four suite obligations, one optional factory parameter, and the
  fake.
- **ADR-0050 is partially superseded in one narrow clause** (§5), with its Status
  line edited and a dated note appended in this same change (ADR-0070 §1/§4). Its
  §1 widening ruling and all of §2 remain the operative law and are strengthened
  rather than replaced.
- **A retrieval-side residual is now named and owned.** Removing the writer's
  truncation makes the store's own bound the binding one, so the ADR states it
  rather than inheriting it silently: `SqliteMemoryStore.search` may under-serve a
  conflict query, and retired records are among the neighbours that consume its
  headroom, so the exposure grows with use. Filed as **#457** with the options and
  the regression it needs (§1, §6). This is a pre-existing property, not one this
  ADR introduces — it bounds ADR-0050's cap-of-five identically — but it is the
  next thing standing between leg 4's exit test and an unqualified claim.
- **Issues #313 and #314 are closed by this ADR** once its implementation lane
  lands; #306, #423, #457 and the observer's volume question stay open with named
  owners (§6).
- **Revisit if** a real contradiction signal lands (ADR-0050 §2/§3's standing
  deferral — a sharper signal would shrink the conflict set and make the ceiling
  bite less often), if the deferred `EXTERNAL` supersession choice is made (the
  band-blind ceiling above), or if the observer at volume makes over-ceiling
  topics routine rather than pathological, which would be evidence the ceiling is
  the wrong instrument rather than the wrong number.

## Alternatives considered

- **Iterate detection to exhaustion within one ingest.** Retire a page, re-search,
  repeat until a page comes back empty. Rejected on termination and on ADR-0050
  §1's ratified reasoning. Termination is the harder problem: a retired record is
  hidden from `search` only *read-time-relatively* (ADR-0045 §6), so a store whose
  read clock is behind the writer's close instant keeps returning what was just
  retired and the loop does not terminate — the exact clock-coherence gap issue
  #306 tracks. It is patchable, by carrying an in-process exclusion set so the
  loop never re-counts an id it already retired, but what remains is an unbounded
  sweep on a user-facing write path holding the ingest lock, which ADR-0050 §1
  rejected in terms ("a denial-of-service surface on a single ingest") this ADR
  has no grounds to overturn. It would also break the single-batch property: N
  pages are N `write_atomic` calls, so a crash mid-iteration leaves a partial
  retirement — the regression ADR-0045 §8 refused to ship.
- **Resolve the surplus lazily, on later contact.** Rejected on three counts.
  ADR-0050 §1 already established the surplus does not drain by re-proposal, so
  "later contact" would need a *new* mechanism, not an existing one. Retiring on
  the read path puts writes inside `search` and would retire on topical
  similarity with no ruling at all — bypassing the `MemoryPolicy` gate ADR-0005
  §3 makes every belief pass, an exemption only ADR-0075 has ever been granted and
  only for records that are evidence rather than beliefs. And a background sweep
  needs something awake to run it, which is leg 5's hub; leg 4 cannot depend on
  leg 5.
- **Keep truncating, land the correction, report the incompleteness on
  `MemoryIngestResult`.** Rejected in §1: it ratifies "I have committed your
  correction and I am still holding beliefs that contradict it" as a normal
  outcome, grows `core/types.py` for a state we have decided should not exist, and
  is honest only if a consumer reads the flag — none does. It is the shape
  `_check_tuning` refuses on principle: a healthy-looking result over a stage that
  did not do its job.
- **Refuse only the `SUPERSEDE` arm, in the applier, leaving detection
  truncating.** Rejected: it fixes the retirement half and leaves the soundness
  half open, since the ruling would still be reached on a truncated set (Context).
  It would also refuse *after* the policy had ruled, which is a worse place to
  discover that the inputs were untrustworthy.
- **Two budgets — keep `conflict_limit` for deliberation, add `retirement_limit`
  for the sweep.** Rejected in §1: it cannot close ADR-0050 §2's gate without
  band-aware truncation layered on top, it adds a knob and an invariant between
  the two, and it keeps the writer guessing which conflicts a policy needs — the
  guess that broke the gate in the first place.
- **Leave #314 filed and change only `MemoryIngestor`.** Rejected in §3: it
  preserves the silent divergence between the production writer and the canonical
  fake, and after §1 the two would disagree about whether a write is *possible*,
  not merely about how much it retires. The suite is where an obligation stops
  being one implementation's habit.
- **Make retrieval itself threshold-complete, so the conflict set is exhaustive
  rather than merely undiscarded.** This is the version of §1 that would justify
  an unqualified claim, and it is the right eventual answer — but it is a
  `MemoryStore` obligation, not a write-path one. It needs either a new Protocol
  method or a new guarantee on `search` (a contract change owing its own ADR under
  golden rule 5), *and* the sqlite-vec work to pre-filter kind, expiry and window
  inside the KNN rather than after it — the limitation `_RESULT_OVERFETCH` exists
  to paper over. Out of this ADR's lane and larger than it; filed as #457, with
  the `SqliteMemoryStore` regression it requires (planted filtered nearer
  neighbours hiding an above-threshold conflict), which the shared suite cannot
  reach because it runs over `FakeMemoryStore`. Deferring it does not weaken this
  ADR's decision — the writer's own discard is closed either way — it only bounds
  the claim, which §1 states rather than assumes.
- **Promote the obligation by pinning the ceiling's value in the suite.**
  Rejected: the suite deliberately does not pin the conflict limit, the threshold,
  or the tuning check, and a suite that fixed the number would stop being a
  contract and start being `MemoryIngestor`'s configuration. Obligation 4 is
  stated relative to whatever limit the writer carries, which is why the
  `WriterFactory` seam is needed and sufficient.
