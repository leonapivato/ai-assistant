# 25. A persistent Codex review session, with independence guardrails

- Status: Accepted
- Date: 2026-07-20
- Supersedes: ADR-0015 §1's one-shot review model — each review round was an
  independent cold `codex exec` with no memory across rounds. §1 below replaces
  it with one persistent session per review loop, resumed each round. The rest
  of ADR-0015 §1 (local-only execution, the `.review/` artifact, ship-not-push,
  the author owning the whole loop) and §§2–5 stand. ADR-0020 already superseded
  §1's commit anchor.
- Amends: ADR-0020 §3 — its content anchor now pins the *terminal verdict* of a
  review conversation rather than the sole output of a one-shot. The acceptance
  rule (recorded base and tree both match) is unchanged.
- Resolves: #125 at its root — the *memoryless* re-raise, where the reviewer
  repeats a rejected finding because it never saw the rejection. A warm re-raise
  past a seen rejection is a different thing, left un-suppressed by design (§1).
- Refs: #124 (the base-anchor tax — related, out of scope)

## Context

The Codex review loop is expensive in a way that is partly structural. Every
round in `scripts/codex-review.sh` is a fresh `codex exec` (line 477): a cold
one-shot that re-reads the repository and rebuilds its model from zero each
round, and — the sharp edge — never sees the author's prior-round rejections. So
it re-raises findings that were already answered.

#125 is the clean case. On PR #122, Codex raised the *same* `blocker` in rounds
1, 2, 4, 5 and 6. It was rejected after round 1 with a specific structural
argument, and re-raised three more times without ever engaging it. Rounds 4 and
6 cost a full Codex run each and produced only the repeated objection. Beyond
#125, recent runaways: one ADR hit 21 rounds / 5.1× churn; another chased one
thread ~13 rounds. The cold-context waste and the re-raise share one root: the
reviewer has no memory across rounds.

This is a cost problem as much as a quality one, and Codex quota is a live
operator concern. Every cold round pays twice — to re-read the repository it read
last round, and to re-argue a finding already answered — and a round that
re-raises a rejected finding and nothing else (#122's rounds 4 and 6) is pure
spend for no review. Cutting per-round cost is a first-class motivation, alongside
convergence.

Worse, ADR-0020's aggregate cannot see the re-raise. §2's numbers all measure
the *author's* churn, and a re-raise the author correctly rejects produces none
— nothing is edited. So the round count climbs against a flat diff, which reads
identically to "the author is thinking hard." The mode is invisible by
construction (#125).

The operator's proposal, which this ADR ratifies: keep **one persistent Codex
conversation across rounds** — one that retains context, that the author can
feed facts to and ask questions of, and that can offer potential solutions, not
only a verdict. Three capabilities, each chosen deliberately with a guardrail:
(1) persistent session, (2) author dialogue / context-feeding, (3)
Codex-proposed solutions.

### The governing tension

**Codex is worth having only because it is independent of the model that wrote
the code** (`CONTRIBUTING.md` → Review; `docs/review/guide.md`). Every capability
here trades against that independence: a conversation the author can talk to,
and that proposes fixes, is a step toward the reviewer becoming a collaborator
on the code it reviews — the self-review that ADR-0020 exists to prevent. So each
capability below carries a guardrail that is a real rule, checkable after the
fact, not an aspiration.

### Spike: the mechanism exists natively

The hard unknown was whether the Codex CLI supports a resumable, read-only,
context-retaining session. It does, natively (codex-cli 0.144.5). A throwaway
spike established it end to end:

- `codex exec --json` emits a `thread.started` event carrying a `thread_id`.
- `codex exec resume <thread_id> <prompt>` resumes that thread in a *fresh
  process* and retains the full conversation: a token stated in round 1 was
  recalled verbatim in a resumed round 2 without being re-supplied.
- Resume takes no fresh `-s`, but that alone does not pin read-only: it still
  honours `--dangerously-bypass-approvals-and-sandbox` and `-c sandbox_mode=…`
  overrides. So read-only is a **driver invariant the driver must actively
  hold** by passing none of those on a resumed round — see §1.
- Sessions persist to `$CODEX_HOME/sessions/` by default (`--ephemeral` opts
  out). The reviewer still reads the current working tree each round, so the
  warm conversation is combined with a *fresh* view of the committed code.

So mechanism (a), native resume, is available; its one dependency, recorded
honestly, is the same `$CODEX_HOME` across rounds, which the local per-clone loop
(ADR-0015 §1) provides. Where it is unavailable — a pruned session, an ephemeral
host — the fallback is (b) transcript injection: prior rounds' recorded findings
and rejections fed into a cold prompt, suppressing re-raises at a token cost. The
decision below is written on the *mechanism*, so either satisfies it.

### `codex-plugin-cc` was evaluated and is not adopted

OpenAI's `codex-plugin-cc` (a Claude Code plugin: `/codex:review`,
`/codex:adversarial-review`, `/codex:transfer`, `/codex:rescue`) was evaluated at
source, not on its README, and is **not adopted**. `/codex:review` is verbatim
"native-review only … does not support … extra focus text," and
`/codex:adversarial-review` runs Codex's own fixed rubric with our input reduced
to a `{{USER_FOCUS}}` slot — neither can be handed `docs/review/guide.md`, the
exact limitation for which `codex-review.sh` drives `codex exec` directly (line
6). Adopting it would discard our rubric, the persona provenance (#99), the
verdict-line contract (#126), and the ADR-0020 §1 preamble; it emits no
tree-anchored `.review/` artifact; and it imports a Stop-hook gate that blocks on
findings (the model ADR-0020 rejected). Its one genuine add — a resumable thread
— is `codex exec resume`, which we already have. **We adopt the primitive the
plugin wraps, not the plugin.**

## Decision

We keep **one persistent Codex review conversation per review loop** — one per
persona, keyed on a durable per-loop identity (§1 below; the branch name is the
round-1 handle, not that identity) — resumed across rounds via `codex exec resume` instead
of started cold each round, driven from `scripts/codex-review.sh` so the rubric,
preamble, verdict contract, and tree-anchored artifact are all preserved. Three
guardrails and an anchoring reconciliation govern what the session enables.

### 1. Persistent / warm session

Round 1 starts the session read-only and records its `thread_id` in `.review/`.
Each later round resumes that thread with the new diff, so the reviewer carries
what it already said and what the author already answered. This is the pure-win
part — context retention at the least risk to independence: it is the same
independent model, merely remembering. It reaches #125 at its root. #125's
pathology is a *memoryless* re-raise — the reviewer repeats a rejected finding
because a cold round never saw the rejection. Now the finding is visible *as*
already-rejected, with its grounding, so that blind repetition cannot happen.

A re-raise *past* that visibility is a different thing, and the ADR **does not
suppress it, by design.** A reviewer that has read the rejection and insists
anyway is making a deliberate, informed act — a signal worth the author's
attention, since often the finding is important and the rejection was wrong.
Structurally gating it would risk discarding exactly the re-raise worth listening
to; the residual warm re-raise is left visible for the author to weigh, not
silenced.

Every persistent round runs under **enforced read-only**, and holding that is
the driver's job. Resume takes no `-s`, but it still honours the sandbox-bypass
flag and `-c sandbox_mode=…` overrides, so the driver must pass none of them and
reject any sandbox- or permission-widening override on a resumed round. The
review loop is local (ADR-0015 §1), so the CI sandbox-bypass the current script
carries does not reach it — a persistent review session never widens its
sandbox. Where native resume is unavailable, the loop falls back to transcript
injection (mechanism b) with no change to the contract.

**A review loop needs a durable identity, and persistent sessions raise the
stakes of getting it wrong.** `codex-review.sh` (its lines 108–125) already
documents that a branch name is the only handle on a loop, so reusing a name
inherits the old branch's artifacts and renaming orphans them — accepted today
because it only skews an advisory counter. With a persistent *session* the same
collision stops being cosmetic: resuming under a reused name would carry another
PR's findings, rejections, and proposed solutions into a fresh verdict. So the
implementation must bind the session (and its fallback transcript, and the
recorded dispositions) to a durable per-loop identity with explicit reset on
reuse and re-validation when the base moves — the durable-identifier question
#97 already raised for the counter, now load-bearing rather than advisory. The
requirement is the decision; the mechanism is deferred to the implementation.

**Re-raise suppression degrades gracefully, because the memory is not the
guarantee.** A context window is finite: over enough rounds or a large enough
diff, early rejections in the live session get compacted or truncated, and a
resume can fail outright. The durable backstop is the record of dispositions —
each finding's rejection and its grounding — persisted in `.review/`, which is
exactly the transcript mechanism (b) injects. Session memory is the optimization
that avoids re-sending it; the recorded dispositions are what must be re-injected
when the window overflows or resume is unavailable. When even `diff + injected
dispositions` will not fit, the floor is an explicit drop to a **plain cold
review of the diff** — today's behaviour exactly — rather than a failed or
silently truncated injection. So the worst case is a re-raise that costs a round,
never worse than the cold loop and never a silently lost rejection. (Bounded
retrieval or compaction above that floor is implementation.)

### 2. Author dialogue / context-feeding — the line

The author may supply the session facts and missing context: what a symbol
means, why a seam is shaped as it is, which constraint a finding overlooked. That
is legitimate and is the point. What is not legitimate is arguing a reviewer out
of a finding it still believes.

The rule: **a finding is retired only by Codex's own updated assessment,
recorded in the review artifact — never by author assertion.** The author
supplies facts; Codex decides whether they change its finding. Every
author-supplied context and every rejection is part of the session transcript
and is recorded, so the negotiation is auditable and the reviewer's independence
can be checked after the fact.

This keeps the author's existing recourse against a finding they believe is
simply wrong: reject it with grounding on the PR (the `guide.md` authority
hierarchy), waive it, and ship. §2 draws the line between *informing* the
reviewer and *overruling* it: independence is not "the author cannot speak to
the reviewer" — it is "the author cannot author the verdict."

### 3. Codex-proposed solutions — the load-bearing guardrail

Codex may propose a fix, not only name a defect. The risk is precise: if the
author takes Codex's patch, the next round reviews code Codex effectively wrote —
the self-review loop ADR-0020 exists to prevent. The warm session can propose a
patch in prose (as `/codex:rescue` does frictionlessly), so the guardrail is on
the *capability*, not any one tool.

The line: a suggestion the author **independently evaluates and authors
themselves** is fine — because the author is a *different model* from Codex, that
authorship carries the same model-level independence ADR-0015 relies on, and the
fix is judged next round like any other code the author wrote. A wholesale paste
is not: then the code is Codex's, and Codex reviewing it is reviewing itself.

But a review record from the proposing session cannot *by itself* tell the two
apart — a disposition line reads the same either way — so the independence check
does not live inside that session. Two rules place it outside:

- **The exact proposal is recorded and published alongside the change**, bounded
  (below) because a proposal is one patch, so the **human at merge** can compare
  what Codex proposed against what was committed. An adapted or rewritten fix is
  the author's own work, judged by a different model.
- **Codex cannot clear code Codex authored**, so this ADR adopts only Codex
  *suggestions the author implements*. A byte-for-byte paste — or any
  **materially proposal-derived** change, since a rename or reformat does not
  launder authorship — is Codex's output: no Codex session may certify it (not
  the proposing session, not another persona, not a cold `codex exec`), so it is
  treated as Codex-authored and routed to a human or genuinely different model
  unless independently certified. The routine path stays author-written code the
  unchanged ship gate reviews as always. Codex *authoring* shippable code
  (rescue) is **not adopted** — it would need its own ADR, since `ship` requires
  a Codex adversarial record a Codex-authored change cannot supply. That boundary
  is the independence ADR-0015 §1 keeps.

Publishing the *proposal* (not the transcript) is what makes this auditable, and
why §4 leaves the raw transcript unpublished without contradiction. The proposal
is published **in full**, hence **size-bounded** — one patch, bounded to fit the
published record rather than stranded in git-ignored `.review/`. A proposal that
cannot be published **exactly and safely** — too large, or carrying a secret
Codex read from an ignored file like `.env` — is **excluded from the
persistent-session path and takes ordinary independent review**, fail-closed, so
publishing is never a new exposure class and the authorship comparison holds for
every published proposal. (The size bound and secret-detection are
implementation; that an unpublishable proposal is excluded, not redacted, is the
decision.) Enforcement in v1 is the author's discipline plus that human
comparison at merge — prose, like ADR-0020 §2's terminal-state rule, carrying its
failure rate. The named upgrade, if it is observed ignored, is a machine-readable
provenance field the next round's prompt surfaces and `ship` refuses a terminal
verdict without: the ADR sets the rule and the published evidence now, and defers
that mechanism to the implementation. This is the guardrail most likely to be
wrong — see
Consequences.

### 4. Anchoring reconciliation (amends ADR-0020 §3)

`just ship` gates on a review artifact whose recorded `(base_sha, tree)` match
the PR's merge base and HEAD tree (ADR-0020 §3). A conversation is a stream; the
gate needs a point. These reconcile: **the dialogue is *how* the reviewer reached
its verdict; the shippable artifact is still the terminal verdict, pinned to the
final `(base, tree)`.** Each round's resume ends by writing that anchored artifact
exactly as today — §3 is amended only to say it is a conversation's terminal turn
rather than a one-shot's whole output; the acceptance rule (base and tree both
match) is untouched, so the ship gate survives intact.

What `ship` posts is unchanged: the terminal verdict artifact, within the size
limit it already enforces. The durable audit record §2 and §3 rely on is the
**disposition record** — per finding, its id, disposition, grounding, and (§3)
any Codex proposal — not the raw conversation, which stays unpublished. Two
decisions bound it so it never breaks the existing ship path; the rest is
deferred to the implementation:

- **Complete record stored, published rendering bounded — but a §3 proposal
  appears in full.** The full record lives in `.review/` (local, unbounded); for
  accumulated context and grounding `ship` posts a bounded rendering plus a
  reference, so a long loop cannot exceed `ship`'s limit. The §3 proposal is the
  exception: a local-only reference defeats its audit value, so §3 size-bounds it
  to appear in full.
- **The published rendering matches the terminal artifact's tree.** Because the
  record is loop-wide and mutable while the verdict is tree-anchored, `ship`
  renders the snapshot of dispositions belonging to the terminal artifact's
  tree — not the current live record — so a re-accepted earlier tree cannot be
  posted next to a later round's dispositions.

The decision is the two invariants above and that the auditable unit is the
per-finding disposition, not the conversation. **What this ADR does not decide —
the implementation PR owns it, as fail-closed obligations it may not quietly
skip:** the record's schema and finding-identifier uniqueness/stability, a
cumulative published-byte budget, and the ship-gate binding — plus three required
end-states the mechanism must reach:

- **read-only proven, not assumed** — the driver pins read-only on every resume
  against a widening `config.toml` and fails closed if it cannot show the
  effective sandbox is read-only;
- **verdict-changing evidence reaches the merge reviewer** — context or a
  disposition that changed a finding's outcome lives in the record the human at
  merge can read, not only in git-ignored `.review/`; a dialogue whose deciding
  context cannot be published does not retire the finding;
- **snapshots selected by the full anchor** — `(loop identity, persona,
  base_sha, tree, terminal turn)`, not the tree alone, failing closed on
  ambiguity.

Fixing a byte budget or ID scheme would over-reach; those are mechanism, and the
obligations above are the states it must satisfy.

### Scope: this targets churn, not a genuine held BLOCK

Honest limit. This addresses the **churn** failure modes: cold-context re-work,
and the re-raise (#125). It does **not** address the author grinding a genuine
structural BLOCK — the 21-round case was a real finding Codex was right to hold,
and shared memory cannot shorten a loop where the reviewer is correct and the
change is not yet right. That mode needs a human reading the aggregate, which
ADR-0020 §2 already provides (the printed round count and churn ratio, carried to
the PR). Nothing here is a substitute for it; no one should expect this to end
all long reviews.

#124 (the base-anchor tax — a base move invalidating a review unconditionally) is
related and out of scope: it concerns *when* an anchor is stale, orthogonal to
the conversation this ADR adds. Referenced, not resolved.

## Alternatives considered

**Adopt `codex-plugin-cc` wholesale.** Rejected (see Context) — it cannot carry
our rubric, emits no tree-anchored artifact, and imports a blocking review-gate.
We take the resume primitive it wraps and keep our own driver.

**Persistent session, read-only to the author too** — the reviewer remembers but
cannot be fed context. Rejected: it keeps §1's win but discards the operator's
goal, and the independence risk is handled by §2's line, not by muting the
author.

**A hard round cap now that context is shared.** Rejected for ADR-0020 §2's
reason: a late round can carry the finding that mattered. The aggregate stays
advisory.

## Consequences

**Easier.** #125's memoryless re-raise is gone at the root — the reviewer sees
what it already said, so it cannot repeat a rejection blindly; a warm re-raise
past that is left visible as a deliberate signal, not silenced (§1). Cold-context
re-reading falls, cutting tokens and latency per round. The reviewer can offer
solutions, and the author can correct a finding built on a missing fact without
spending a whole round to do it.

**Harder.** New things to record and honour: the per-loop session identity, the
disposition record, and the published proposal behind a Codex-suggested fix.
Independence stops being automatic — every round used to be a cold independent
read; now it is preserved by rules (§2, §3) and made checkable by the published
record, a reduction accepted deliberately for the churn cut. Guardrail #3 is the
fragile one: v1 leans on author discipline and the human comparison at merge —
prose, like ADR-0020 §2's terminal-state rule, which has failed here before. If
ignored, the remedy is the mechanical provenance field §3 names, not removing the
capability.

**Revisit if** guardrail #3's provenance is observed ignored across several
changes (make it mechanical), or if the warm session converges *less* than the
cold one on some class of change — its memory anchoring it to an early wrong
reading — for which a periodic fresh-context round is the remedy.

**Follow-on.** ADR-0015 and ADR-0020 gain the status lines added here.
Implementation is a separate PR — a review-contract decision ratified before code
builds on it (the ratify-before-build principle, not golden rule 5, which governs
Protocol/`core` ADRs): `scripts/codex-review.sh` records and resumes the
`thread_id` and records dispositions, context, and proposals in `.review/` under a
durable per-loop identity, falling back to transcript injection when resume is
unavailable; `scripts/ship.sh` keeps the anchor and confirms the terminal
artifact matches; and the §2 retire-only-by-Codex and §3 provenance rules go into
`docs/review/guide.md`.
