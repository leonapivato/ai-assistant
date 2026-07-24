# 50. Contradiction resolution retires the full conflict set, and defers assertion-vs-assertion

- Status: Accepted
- Date: 2026-07-23
- **Not a contract change.** This is a policy-lane decision. It changes
  `DefaultMemoryPolicy` (`memory/policy.py`) and the `MemoryIngestor` supersession
  applier (`memory/ingest.py`) only; it adds no member, no field, and no method to
  `core/types.py` or `core/protocols.py`, and it leaves the `MemoryWriter` and
  `MemoryPolicy` Protocols, their conformance suites, and their canonical fakes
  untouched. It is therefore **Accepted on merge**, not ratified ahead of an
  implementation.
- **Takes up the two questions [ADR-0045](0045-memory-records-carry-a-validity-window.md)
  §7/§10 deferred to "the policy lane" and "consciously does not answer":** #244
  (a correction retires only the best-ranked conflicting inference) and #245 (two
  contradictory user assertions both stay live). ADR-0045 unblocked both by giving
  the store a non-destructive validity window; it declined to *decide* how they
  resolve. This ADR decides.
- **Supersedes** [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md)
  §5's "accept beside" ruling for the assertion-versus-assertion case, and refines
  ADR-0038 §3's mixed-conflict handling (§2 below). It does **not** touch ADR-0045's
  writer floor: `_refuse_unsafe_fold` clause 1 (nothing may fold onto a
  `USER_ASSERTED` target, both rulings) stands verbatim.

## Context

Since [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md) a
user assertion supersedes a conflicting inference, and since
[ADR-0045](0045-memory-records-carry-a-validity-window.md) supersession is
non-destructive: the applier closes the stale record's validity window and writes
the correction as a fresh record, both retained on disk (`export`), one live. Two
honesty gaps in *which* records that resolution reaches survived ADR-0045 by its own
account, filed as issues and deferred:

- **#244 — a correction retires only the best-ranked conflicting inference.**
  `MemoryDecision.target_id` names one record, so when a correction contradicts
  several inferences on a topic, `DefaultMemoryPolicy` supersedes the top-ranked
  one and the rest stay live. The memory keeps believing things it was just
  corrected about. ADR-0038 §4 capped supersession at one target because a
  *destructive* overwrite is only safe to do once; ADR-0045 dissolved that reason —
  "closing N windows is now cheap and reversible in history" — and issue #244 notes
  the same: "superseding N records is closing N windows, which does not need
  `merge_into` to grow at all." ADR-0045 §7 left the choice open (emit N proposals,
  or a later `target_ids` widening).

- **#245 — two contradictory user assertions both stay live.** ADR-0038 §5 left
  assertion-versus-assertion alone: both sit at confidence 1.0, nothing ranks them,
  and the conflict signal is topical similarity, not contradiction — too weak to
  destroy a record the user gave us. It rejected `ASK_USER` as too noisy for the
  common benign restatement and accepted the resulting gap (both live). ADR-0045 §5
  confirmed the signal-strength objection *survives* the window ("non-destructive is
  not the same as warranted") and §7 named the only two acceptable gates for
  resolving it: **a real contradiction signal, or explicit user confirmation.**

The forces: the product thesis is an *honest* accumulated user model. Two live,
contradictory profile records — whether two stale inferences or two things the user
said — is precisely the dishonesty the moat cannot carry. Against that: ADR-0045's
signal-strength floor is ratified and correct — topical similarity is not
contradiction, so nothing here may destroy a user's assertion on a lexical
near-match; and the fix must not grow the `core` contract (both issues were
explicitly downgraded *out* of `core` once the window existed).

## Decision

### 1. A `SUPERSEDE` retires the full supersedable conflict set (#244)

`SUPERSEDE` names a **relation** — the proposal overturns the belief the conflict
set holds — not a single record (ADR-0040 §1). Every entry in the conflict set the
detector surfaced is a same-kind, at-or-above-threshold contradiction of the
proposal; they are all the belief being corrected, restated. The applier therefore
closes the window of the policy's named `target_id` **and** of every other conflict
it is *warranted* to retire, in one atomic `write_atomic` batch.

**The conflicting set is defined precisely as:** the named `target`, plus every
other detected conflict whose `provenance.source` is in `{OBSERVED, INFERRED}` (the
`_SUPERSEDABLE` allow-list). Two sources are held out of the widening, each for a
standing reason:

- **`USER_ASSERTED` conflicts are never swept in.** Clause 1 of `_refuse_unsafe_fold`
  stands, record-keyed, for both rulings (ADR-0045 §5): topical similarity may not
  retire a record the user gave us. (Under `DefaultMemoryPolicy` this set never even
  arises with an asserted conflict present — §2 rules `ASK_USER` first — but the
  applier excludes them regardless, since it takes rulings from any injected policy.)
- **`EXTERNAL` conflicts are not auto-retired**, even though ADR-0045 §5b now permits
  an `EXTERNAL` supersession at the writer floor. Whether the *default policy* adopts
  `EXTERNAL` supersession is a separate, still-deferred choice (ADR-0045 §5/§7); the
  widening stays inside the `{OBSERVED, INFERRED}` class the policy already
  supersedes. An `EXTERNAL` target a custom policy *names explicitly* is still
  retired — it is the `target` — but sibling `EXTERNAL` conflicts are left live.

**"Full" is bounded by conflict detection; the over-limit surplus is a filed
residual.** The set is the full *detected* conflict set, which `_detect_conflicts`
caps at the configured `conflict_limit` (default 5) — the same pre-existing bound that
governs how many conflicts the policy considers at all. So when more than
`conflict_limit` inferences match one correction, this supersession retires exactly
`conflict_limit` of them and the surplus stays live. This is deliberately *not* an
unbounded re-search: `conflict_limit` is a safety knob (`_check_tuning` refuses to
disable it), and an unbounded supersession sweep would be a denial-of-service surface
on a single ingest. The honesty claim is therefore the precise one — a `SUPERSEDE`
retires *every conflict it is shown*, not "every conflict that exists on the topic" —
the same read-time-relative, bounded honesty the rest of the memory model states
(ADR-0045 §6). This is still a strict improvement over the pre-ADR behaviour (which
retired *one* of N); the residual leak shrinks from N−1 to N−`conflict_limit`.

**The surplus does not self-heal by re-proposal**, and this ADR does not claim it
does: once the correction lands as a `USER_ASSERTED` record, a re-proposal of the same
correction sees *it* as an asserted conflict and defers (`ASK_USER`, §2), so the
surviving inferences are not swept on a second pass. Retiring them needs either a
larger `conflict_limit` (widening what one ingest sees) or the confirmation-driven
flow §2 defers. The over-limit boundary and this residual are pinned by a regression
test and **filed** as issue #313; they are not resolved here.

This lives in the applier because the policy cannot express it: `target_id` is
singular and this ADR deliberately does not grow it (below). The `target` remains the
**primary** the policy names and `MemoryDecision` audits; `MemoryIngestResult.record_id`
is still the correction's fresh id (ADR-0045 §4). Retiring N is one atomic batch —
`[UPSERT(closed) for each retired] + [INSERT_IF_ABSENT(correction)]` — so a failure
part-way leaves *every* target live and unchanged, exactly as the single-target
applier did (ADR-0045 §8). The minted id must be absent from the store *and* name no
retired target (a repeated id in the batch is `write_atomic`'s hard error, ADR-0046
§3); the bounded re-mint loop already enforces this, widened from one target id to
the set.

**Why the applier, not a `target_ids` widening or N proposals.** ADR-0045 §7 offered
three routes. A `core` `target_ids` widening is rejected here: closing N windows needs
no contract growth (issue #244's own closing observation), and a `core` change would
be a separate contract lane. "Emit N proposals" is rejected: it splits one logical
correction across N ingests, N conflict searches, and N policy calls, and cannot be
made atomic. Deriving the set in the applier from the conflicts it already holds is
the minimal, atomic, contract-free route.

**Why this is within the `MemoryWriter` contract's latitude.** The conformance suite
pins that a `SUPERSEDE` *retires the target* and writes a new-id correction; it does
not pin that the target is the *only* record retired. An applier that retires the
target plus other supersedable conflicts still satisfies every pinned obligation, so
the suite and the canonical `FakeMemoryWriter` are unchanged and both remain
conforming — the fake simply exercises the single-conflict case. Whether this
widening should be *promoted* to a universal `MemoryWriter` obligation (with the
conformance suite driving a multi-conflict `SUPERSEDE` and the fake matching) is a
follow-up filed as an issue, not decided here; that would be a contract-surface change
in its own lane.

### 2. A user assertion contradicting a prior assertion defers to the user (#245)

`DefaultMemoryPolicy` gains a rule, ahead of its supersession rule: **if a
user-asserted proposal conflicts with any existing `USER_ASSERTED` record, rule
`ASK_USER`.** The user is contradicting something they earlier told us; the memory
may not silently keep both (the #245 gap) and may not destroy either on a
topical-similarity signal (ADR-0045 §5, clause 1). It defers to the one authority
that can resolve a contradiction between two things the user said — the user — which
is the **explicit user confirmation** gate ADR-0045 §7 named as acceptable.

The check comes **first**, ahead of the inference-supersession rule, and this refines
ADR-0038 §3's mixed case. When the conflict set holds *both* a prior assertion and a
supersedable inference, superseding the inference (ADR-0038 §3's behaviour) would
still *commit the contradicting assertion* beside the prior one — the #245 gap,
merely reached by a different path. Deferring the whole proposal is the only outcome
that does not leave two live contradictory assertions. The inference is not lost — it
stays live and correctable — but note it is **not** cleaned up by a plain re-proposal
of the correction: once any correction on the topic is deferred, and more so once one
lands as a `USER_ASSERTED` record, a re-proposal conflicts with *that* assertion and
defers again. Retiring the inference in the mixed case therefore waits on the
confirmation-driven flow this ADR defers (below), not on a normal re-ingest.

**The precedence rule, once a contradiction is confirmed, is recency** — the later
assertion supersedes the earlier, closing its window and keeping it in `export`, as
issue #245 and ADR-0045 §7 both describe. This ADR does **not** implement that
confirmation-driven supersession (it spans the interface/permission layers, outside
the memory lane); it decides that the ingest-time policy is `ASK_USER`, so the
profile never *silently* commits a self-contradiction. `ASK_USER` writes nothing
(existing applier behaviour), so the earlier assertion stays live and the incoming
one is held pending the user's answer, not dropped.

**Why this supersedes ADR-0038 §5's `ASK_USER` rejection.** ADR-0038 §5 rejected
`ASK_USER` because "both live" was an acceptable fallback and interrogation seemed
worse than the gap, *and* because a confirmation then had no non-destructive outcome
to offer. Two things changed. Issue #245 establishes that "both live" is **not**
acceptable for an honest user model — it is a correctness defect, not a benign
restatement to be tolerated. And ADR-0045's window makes the *outcome* of a
confirmation non-destructive: the superseded assertion is retained in `export`, so
confirming "the new one holds" costs the user nothing. The cost/benefit ADR-0038 §5
weighed has flipped. The prompt is also **targeted** — it fires only when an incoming
assertion topically conflicts with an *existing assertion*, not with an inference and
not with an external record — so it is rare and high-value, not the blanket
interrogation §5 feared.

### 3. What this ADR does not decide

- **Growing `MemoryDecision.target_id` to a list.** Rejected in §1; closing N windows
  needs no contract growth. Filed against a possible future `MemoryWriter` promotion.
- **Promoting the full-set retirement to a universal `MemoryWriter` obligation** (the
  conformance suite + `FakeMemoryWriter`). Filed as issue #314; it is a contract-surface
  change in its own lane. Here it is `MemoryIngestor`'s behaviour within the contract's
  existing latitude (§1).
- **A real contradiction signal** to distinguish a genuine assertion contradiction
  from a benign restatement or a coexisting preference. ADR-0045's finding stands:
  topical similarity is not that signal. Until one exists, §2's gate is user
  confirmation. Filed.
- **The confirmation-driven supersession flow** for #245 (surfacing the `ASK_USER`,
  applying recency on the answer). Spans interfaces/permissions; out of the memory
  lane.
- **Whether the default policy adopts `EXTERNAL` supersession.** Untouched (§1);
  still the deferred choice ADR-0045 §5/§7 left open.

## Consequences

- **The memory stops holding beliefs it was just corrected about.** A correction
  retires every stale inference it is *shown* — the full detected conflict set, up to
  `conflict_limit` — in one atomic supersession, not only the best-ranked (#244); a
  surplus beyond the cap stays live as a bounded, filed residual (§1). The store gains
  no record it did not before — the extra retirements are window-closes, all retained
  in `export`.
- **The profile never silently holds two contradictory assertions.** An assertion
  that contradicts a prior assertion defers to the user rather than landing beside it
  (#245). No assertion is destroyed on a weak signal; clause 1 stands.
- **No `core` change, no Protocol change, no conformance/fake change.** The
  `MemoryWriter` and `MemoryPolicy` contracts, their suites, and their canonical
  fakes are untouched; both writers remain conforming (§1). Flagged per golden rule 5
  as *not* a contract change.
- **`DefaultMemoryPolicy` rule count grows by one** (the assertion-vs-assertion
  `ASK_USER`, ahead of supersession). `ASK_USER` was already a policy outcome
  (secret-tier, rule 1), so no new decision kind is used.
- **Filed follow-ups:** promoting the full-set retirement to a universal writer
  obligation (with fake parity); a real contradiction signal for #245; the
  confirmation-driven recency supersession; the **over-`conflict_limit` surplus**
  (issue #313) — a correction contradicting more inferences than the detection cap
  leaves the surplus live (§1), a bounded residual not self-healed by re-proposal. The
  universal-obligation promotion is issue #314.
- **Revisit if** a contradiction signal lands (§2's gate could tighten from "any
  asserted conflict" to "a *contradicting* asserted conflict", sparing benign
  restatements the prompt), or if a consumer needs finer per-record supersession
  control than the full-set rule gives (the `target_ids` widening, §3).

## Alternatives considered

- **Grow `MemoryDecision.target_id` to `target_ids` to resolve #244.** Rejected (§1):
  a `core` contract widening for something the validity window makes free — closing N
  windows is N atomic upserts. It would be a separate contract lane for no capability
  the applier does not already have.
- **Emit N supersession proposals, one per stale inference.** Rejected (§1): splits
  one correction across N ingests and conflict searches, and cannot be atomic. The
  applier holds the whole conflict set already.
- **Auto-retire `EXTERNAL` conflicts in the full set too.** Rejected (§1): ADR-0045
  §5/§7 deliberately left `EXTERNAL` supersession as a deferred policy choice; sweeping
  external records into the set would adopt it silently. A named external target is
  retired; siblings are not.
- **Resolve #245 by recency-superseding the earlier assertion on topical similarity.**
  Rejected: this is exactly what ADR-0045 §5 forbids — topical similarity is not a
  contradiction signal, and retiring a user's assertion on a lexical near-match is the
  destruction clause 1 exists to prevent. Recency is the right *precedence once a
  contradiction is confirmed*, not a licence to auto-retire on the conflict signal.
- **Keep ADR-0038 §5's "accept beside" for #245.** Rejected (§2): it is the very gap
  issue #245 reports — two live contradictory profile records — which an honest user
  model cannot carry.
- **`ASK_USER` on *every* asserted conflict, including inferences.** Rejected: an
  inference is a derived belief a user correction is *entitled* to overturn without
  asking (ADR-0038's whole point). The prompt is reserved for the one case with no
  ranking between the records — assertion versus assertion.
