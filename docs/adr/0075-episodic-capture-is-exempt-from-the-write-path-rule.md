# 75. Deterministic episodic capture is exempt from the proposal → policy write path

- Status: Proposed
- Date: 2026-07-28
- **This ADR partially supersedes ADR-0005**, in the scope named in §1: its
  proposal → policy write path, insofar as that path covers the deterministic
  capture of an episode recording a turn that happened. Everything else ADR-0005
  decided — the four typed kinds, the shared envelope, `Provenance`, the
  profile-versus-model reading, the `MemoryPolicy` seam, and the write path for
  **every other** write — stays accepted and is untouched. ADR-0005's Status line
  records the supersession per ADR-0070 §4; **no ratified body text of ADR-0005 is
  rewritten** (ADR-0070 §1). **Both files land in one change**, so ADR-0005's
  Status never points at an ADR that is absent — ADR-0070 §1's condition on
  recording a supersession is that the superseding ADR *exists*, and the failure it
  forbids ("with no such ADR") is unreachable when the pair is atomic. The
  `Proposed` → `Accepted` flip is the ratifying edit at merge (ADR-0015 §5;
  `CONTRIBUTING.md`, "Trivial ADR edits"), and ADR-0070 §1 keeps the repair path
  open besides: a marked supersession that never landed is restored by correcting
  the Status line, which changes no decision.
- **Changes no contract.** No Protocol, no `core` type, no code. It removes an
  obligation from one producer rather than adding surface, so there is no triad
  and nothing to implement against it beyond what ADR-0074 already ruled.
- **Refs:** ADR-0070 §1 (the amend-versus-supersede test this ADR is filed
  under), §3 (partial supersession is the sanctioned form), §4 (the status
  vocabulary); ADR-0005 §3 and its Consequences (the scope replaced), §2
  (`evidence` as "references, e.g. episode ids"); ADR-0074 §3 (what capture does
  and the safeguards it carries), §4 (what capture stamps), §7 (retention), §8
  (deletion); ADR-0072 §3 (evidence is not the belief); ADR-0004 §6 (the deletion
  right); ADR-0038 §1a; the roadmap's leg 3 (the observer, which this exemption
  does **not** reach); #442 (the question this ADR answers), #443 (ADR-0074, which
  is held until this merges).

## Context

ADR-0074 ratifies leg 2's capture: every turn the engine hands back is recorded as
an `EpisodicMemory`, written **directly** to the store — a one-element
`write_atomic` in `INSERT_IF_ABSENT` — rather than through
`MemoryWriter.ingest` → `MemoryPolicy` (ADR-0074 §3).

ADR-0005 says otherwise, and says it twice. Its §3 splits responsibilities so that
"`learning` turns feedback/observations into `MemoryUpdateProposal`s", whose
`proposed` field is any `MemoryRecord` — `EpisodicMemory` included. Its
Consequences state, without qualification: "**Every write goes through a
reviewable proposal → policy path**, and false or oversensitive memories can be
rejected, expired, or bounced to the user."

ADR-0074 §3 argued that the rule's *subject* is a belief and that an episode is
the evidence a belief cites, so the two never met. Both Codex personas rejected
that reading across five review rounds, and **#442 was adjudicated against it**.
The adjudication applies ADR-0070 §1's test as written:

> **Any change to what was decided requires a new ADR that supersedes the old one**
> — wholly, or partially (§3). A change to what was decided is anything a reader
> would act on differently.

That is decisive on the facts, whatever one thinks of the belief-versus-evidence
distinction. A reader of ADR-0005's Consequences, holding an `EpisodicMemory` and
asking "how do I write this?", routes it through the policy path. A reader of
ADR-0074 §3 writes it directly. **The two readers act differently**, so this is a
change to what was decided, and it is owed a supersession rather than a
reinterpretation — regardless of how good the reinterpretation's argument is.

**The argument survives the ruling; it just moves.** The distinction ADR-0074 §3
drew is not defeated by being insufficient to avoid a supersession — it is the
*justification* for one, and it belongs here:

- ADR-0072 §3 states the line in its own words: "an observation is *evidence for* a
  belief and never the belief itself". What `learning` proposes is the belief read
  *off* an observation; the observation is what that belief will cite.
- ADR-0005 §2 already put episodes on the far side of that line, documenting
  `Provenance.evidence` as "references (e.g. episode ids)" — episodes were, in
  ADR-0005's own design, the thing pointed *at* by records travelling the gate.
- ADR-0038 §1a's shape applies: a record whose warrant is that it happened has
  nothing for a policy to weigh.

So the question this ADR settles is not whether episodes are beliefs. It is
whether the write path ADR-0005 ratified for beliefs should also carry the
records those beliefs cite — and, §4 shows, the answer is that it cannot carry
them without destroying them.

## Decision

### 1. The scope replaced, stated exactly

**ADR-0005's proposal → policy write path does not govern the deterministic
capture of an episode that records a turn.** Precisely:

- ADR-0005's Consequences, "Every write goes through a reviewable proposal →
  policy path", is replaced by: **every write of a belief** goes through that
  path. A deterministic recording of an interaction does not.
- ADR-0005 §3's assignment of "feedback/observations" to `learning`, for turning
  into `MemoryUpdateProposal`s, is narrowed to the beliefs an observation
  supports. It no longer reaches the recording of the observation itself.

Nothing else in ADR-0005 is touched — not §1's typed kinds, not §2's provenance
model, not §3's `MemoryPolicy` seam or its five outcomes, not §4's contract
surface, and not the write path for every other producer. ADR-0005's rule that
"memory is never written directly by the model" is **not** in the replaced scope
and stands as written: capture writes no model output as fact.

### 2. The exemption is one producer wide

It covers **only** the capture path ADR-0074 §3 ratifies: a deterministic,
non-inferring recording of a turn the engine has already answered, written by
`orchestration`, at **at most one insert attempt per outcome**.

"At most one" is exact, and the exemption is not a licence to make it more. A
store failure leaves the turn recorded with **no** episode, reported on the
outcome and not retried (ADR-0074 §3): the guarantee there is a durable turn and a
best-effort episode, and nothing in this ADR asks an implementer to reach a
cardinality of exactly one — which they could only do by retrying, recording the
exchange twice, or swallowing the failure.

It does **not** cover, and this list is exhaustive rather than illustrative:

- **Any belief write, in any band.** `ASSERTED`, `DERIVED` and `ATTESTED` records
  all go through the gate exactly as before.
- **Leg 3's observer.** The roadmap defines it as "a model-backed producer that
  reads episodes and proposes `OBSERVED`/`INFERRED` memories **through the
  existing `MemoryPolicy` gate**", and this ADR leaves that untouched. The
  observer is the paradigm case the gate exists for: a model's inference about a
  person, which must be rejectable. That capture and the observer both carry
  `OBSERVED` provenance (ADR-0074 §4) is exactly why the boundary is drawn on
  *what the producer does* — record, or infer — and not on the source enum.
- **Any future capture source** — a sensor (leg 6), or the buffered ambient
  capture #441 sketches. Each may argue for the same exemption on the same
  grounds when it exists; none inherits it here, because none is deterministic
  recording of an exchange this system itself conducted and can vouch for.
- **Any write that asserts something about the user.** This is the boundary, and
  it is worth stating carefully, because a captured turn *does* contain
  model-generated text — the assistant's own reply is half of the exchange. The
  distinction is not whether a model produced the words but **what the record
  claims**:

  - Recording **that the assistant said X, at this time, in this conversation** is
    an event. It is true because it happened, a policy has nothing to weigh, and
    it is exempt.
  - Recording **that X is true of the user** is an assertion. It is a belief
    whatever produced it, it is exactly what "false or oversensitive" (ADR-0005 §3)
    is about, and it goes through the gate.

  So the exemption follows the record's *claim*, not the provenance of its
  characters. The same model output crosses both sides: quoted inside an episode it
  is exempt; distilled by leg 3 into "the user prefers…" it is a proposal like any
  other. That is the same line ADR-0072 §3 draws between evidence and the belief
  read off it, applied to the one case where the evidence happens to contain
  machine-written words.

### 3. What replaces the gate for this class

The exemption is not "no safeguards"; it is a different set, all of them already
ratified by ADR-0074 and cited here rather than restated:

- **The write cannot clobber.** `INSERT_IF_ABSENT`, never `add`'s upsert, with a
  store-derived id that cannot collide with another turn by construction, and a
  conflict that fails loudly instead of retrying (ADR-0074 §3).
- **No episode is ever folded.** Nothing merges, retires or supersedes a captured
  episode: two things that both happened do not contradict each other, and
  ADR-0074 §4 keeps an episode's validity window open because supersession is a
  law about beliefs. The gate's conflict machinery has no work to do here, which
  §4 shows is not a coincidence.
- **Capture judges nothing.** No importance, no participants, no evidence, and a
  documented sub-1.0 confidence that is standing rather than certainty
  (ADR-0074 §4).
- **Retention is bounded and explicit.** A finite default horizon set at capture
  (ADR-0074 §7) — which is what ADR-0005's `STORE_TEMPORARY` outcome would
  otherwise have been reached for, and does better, because it is a decision about
  episodes rather than a fallback for weak evidence (§4).
- **Deletion is unconditional.** ADR-0004 §6's right reaches every episode
  individually and by conversation, with the protocol ADR-0074 §8 ratifies.
- **The write is bounded in volume by construction**: one insert attempt per turn
  the engine answered, and none for anything else, which is the "unbounded,
  unreviewable side effect" ADR-0005 §Context feared, closed by arithmetic rather
  than by review.

### 4. The gate is not merely unnecessary here — it is destructive

This is the part that makes the exemption a correction rather than a convenience,
and it is verified against the code at the time of writing rather than argued from
first principles. Trace an `EpisodicMemory` proposal carrying `OBSERVED`
provenance through `MemoryIngestor` and `DefaultMemoryPolicy`:

1. **Conflict detection is kind-scoped.** `MemoryIngestor._detect_conflicts`
   searches `kinds=[MemoryKind(record.kind)]`, so an episode's candidate conflicts
   are **other episodes** — every turn topically similar to this one, above the
   conflict threshold. (This scoping is also why a *correction* can never
   accidentally retire an episode: an assertion's conflict search is scoped to its
   own kind. The hazard runs turn-against-turn, and only there.)
2. **The shipped policy rules `REINFORCE` on the first of them.**
   `DefaultMemoryPolicy.decide` reaches, for a non-asserted proposal with no
   user-asserted conflict, `if conflicts: return MemoryDecision(kind=REINFORCE,
   target_id=conflicts[0].id, reason="updates an existing memory")`.
3. **The fold is not refused, and it overwrites.** `_refuse_unsafe_fold` declines
   only folds onto a `USER_ASSERTED` target, and a `USER_ASSERTED` proposal onto
   an `EXTERNAL` one; two `OBSERVED` episodes are neither. So `_apply` runs
   `store.add(_merge(target, proposed))`, and `_merge` returns
   `incoming.model_copy(update={"id": target.id, ...})` — the **new turn stored at
   the older turn's id**, through an upsert. Two turns went in; one record comes
   out, holding the later turn's content under the earlier turn's identity.

`_merge`'s own docstring names the precondition being violated: it "assume[s] the
two records *agree*", unioning evidence and taking the maximum confidence. Two
different turns do not agree or disagree — they are different events, and the
machinery has no concept for that.

**A second, quieter failure sits beside it.** A conflict-free episode whose
confidence falls below the policy's `min_confidence` (0.3 by default) is ruled
`STORE_TEMPORARY` and given the policy's `temporary_ttl` (7 days). Retention would
then be set from a number that does not mean, for an episode, what the policy
reads it as: ADR-0074 §4 makes an episode's confidence a statement of *standing*
below the user's word, not an estimate of how likely the exchange was to have
happened. The gate would silently override ADR-0074 §7's retention decision with a
fallback meant for weak evidence.

So the gate does not fail to help; it actively corrupts. The propose/dispose path
exists to let a deterministic policy **reject false or oversensitive beliefs**
(ADR-0005 §3, Consequences). A record of what happened is not a candidate belief:
there is nothing to reject — it happened — and a `REJECT` would silently discard
an interaction the user had. Routing capture through it would mean building an
episode-safe policy whose entire content is "never fold, never reject, never
re-time an `EPISODIC` record" — a gate configured to do nothing, on every turn, at
the cost of a similarity search whose answer is meaningless.

### 5. What this ADR does not decide

- **The sensitivity or tiering of captured content.** Whether some exchanges must
  not be captured, or must be captured differently, is the leg 3 observer ADR's
  problem (its brief already carries "the scope of observation and what justifies
  retention"), together with #441's retention-trigger provenance. Nothing here
  licenses capturing more than ADR-0074 §3 ruled.
- **Any change to the gate for any other write.** The path is untouched for every
  producer except the one §2 names.
- **Whether `DefaultMemoryPolicy` should refuse to fold an `EPISODIC` record
  anyway.** §4's trace is the *reason* capture does not use the path, not a defect
  report against the policy; whether that policy should be hardened for a producer
  that no longer reaches it is a question for whoever owns it, and it is not a
  precondition of ADR-0074 shipping. ADR-0074 §4 already binds leg 3's policy rule
  not to require evidence of an episode, which is the constraint that matters if
  an episode ever does reach the gate again.
- **Anything ADR-0074 decided.** This ADR removes an obligation; it adds no design
  and changes none of ADR-0074's rulings, whose own header stays accurate — it
  amends and supersedes nothing, because the supersession is here.

## Consequences

- **ADR-0074's capture path is ratified law rather than a contested reading.** The
  implementation lane builds against ADR-0074 §3 without inheriting a live
  disagreement with ADR-0005, which is what #442 was blocking.
- **The exemption is legible from ADR-0005 itself.** Its Status line names this
  ADR and the scope, so a reader arriving at ADR-0005 to learn how to write a
  memory is told, in the one place they will look, that one class of write is
  decided elsewhere.
- **The boundary is behavioural, not provenance-keyed** (§2). A producer is exempt
  because it *records* rather than *infers*, so `OBSERVED` alone never buys the
  exemption — which is what keeps leg 3's observer, whose records carry the same
  source, firmly inside the gate.
- **A future producer that wants the same exemption must argue for it.** Sensors
  and ambient capture are named as not covered (§2), so the next such lane writes
  its own ADR rather than reading this one as a precedent for "recording is
  exempt".
- **The cost is a real one, stated plainly:** episodic writes are no longer
  reviewable at a policy seam, so a capture bug writes straight to a Tier 1 store.
  What bounds it is volume (one record per answered turn), the inspection surface
  ADR-0073 shipped, and ADR-0004 §6's deletion — not a gate.
- **Revisit if** a policy is written that is safe for episodes *and* has something
  to decide about them — the two together, since §4's objection is that the second
  half is empty.

## Alternatives considered

- **Leave ADR-0074 §3's reinterpretation standing and close #442 as "no change
  needed".** Rejected by ADR-0070 §1's test, applied in Context: two readers act
  differently, so it is a decision change. The reinterpretation's argument is
  preserved here as justification rather than discarded.
- **Route capture through the gate after all, with an episode-safe
  `MemoryPolicy`.** Rejected in §4. It requires a policy whose whole content is a
  list of things not to do, pays a similarity search per turn for an answer that
  is meaningless, and leaves the destructive default one injected policy away.
- **Supersede ADR-0005's write-path rule wholly, and re-ratify it for beliefs
  only.** Rejected: the rule is correct for everything except one producer, and a
  whole supersession would drag §3's `MemoryPolicy` seam and its five outcomes —
  live, load-bearing, and uncontested — through a re-ratification that changes
  none of them. Partial supersession is the sanctioned tool for exactly this
  (ADR-0070 §3).
- **Split ADR-0005's write-path clause into its own ADR so it can be superseded
  wholly.** Rejected by ADR-0070 §3, which considered and refused this
  (retroactively it "would rewrite and relocate ratified text — the append-only
  violation §1 exists to prevent").
- **Key the exemption on `MemorySource.OBSERVED`.** Rejected in §2. It is the one
  formulation that would be easy to enforce and would exempt precisely the wrong
  thing: leg 3's observer proposes `OBSERVED` records, and it is the producer the
  gate most needs to hold.
