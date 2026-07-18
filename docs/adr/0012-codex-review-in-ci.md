# 12. Codex review in CI: triggered, advisory, non-blocking

- Status: Accepted
- Date: 2026-07-18
- Amended: 2026-07-18 (§4 — CI cannot run Codex's own sandbox; see the amendment)

## Context

Adversarial and architecture review by **Codex** — a model independent of the
Claude that writes the code — is a core quality mechanism (CONTRIBUTING,
"Review"; `docs/review/`). Today it runs only locally, by hand, via
`scripts/codex-review.sh`, which sends the branch diff to OpenAI as a deliberate
pre-merge step.

That was right for one committer working locally. With two contributors
integrating through pull requests (ADR-0010), the local-only model has gaps:

1. **It relies on memory.** Nothing ensures the review actually ran before a
   PR is approved; "did you review it?" is a manual, forgettable step.
2. **It leaves no trace.** Findings live in someone's terminal, not on the PR,
   even though the workflow asks contributors to *report* the review outcome in
   the PR description.
3. **It is invisible across contributors.** In parallel work, one person cannot
   see that the other's change was reviewed or what was found.

The pull-request workflow already gives us the missing seam: a PR has a
lifecycle (`draft → ready`) and a comment channel. The question this ADR settles
is *how* to run the existing review through CI without turning an advisory,
non-deterministic reviewer into a brittle merge gate — and without making egress
to OpenAI happen thoughtlessly.

This changes the review *process*, not any Protocol or `core` type; it is a
non-obvious workflow decision, so it is recorded here and it revises the review
story of ADR-0010.

## Decision

We will run the **existing** Codex review through GitHub Actions, triggered by
PR lifecycle events, as an **advisory, non-blocking** step that posts its
findings to the PR.

### 1. One engine, two triggers

`scripts/codex-review.sh` and the rubrics in `docs/review/` remain the single
review engine: CI runs that **same script**, rather than reimplementing review
logic in YAML. So local and CI cannot drift, and the reviewer can read across the
tree to confirm a finding (the trust this rests on is §4). The local run confines
that access with Codex's read-only sandbox; the CI runner cannot initialize that
sandbox and drops it — see the §4 amendment. The local invocation (`just review-codex …`) is
**kept** for fast, zero-latency iteration with no remote round-trip.

Triggers:

- **`draft → ready for review`** automatically runs the **adversarial** persona
  — the universal pre-merge code review. This ties review to the moment a change
  claims to be complete (the draft-PR convention), not to every commit.
- **A push to an already-ready PR** re-runs it, so the reviewed diff tracks the
  diff that will actually merge (§5). Draft PRs are still exempt — the point of a
  draft is to iterate without review.
- **A `/review [persona]` PR comment** runs a review on demand (default
  `adversarial`; `/review architecture` for the architecture lens). This covers
  the architecture-review-at-`Proposed` norm for ADRs and any re-review after
  changes. The comment trigger runs only for an **authorized actor** (§4).

The two automatic triggers fire **only after `gate` is green for the same head
SHA** — reviewers are the judgment layer above an assumed-green gate
(`docs/review/guide.md`), so there is nothing to gain from reviewing a
mechanically-broken change. The explicit `/review` trigger does not wait on the
gate: a `Proposed` ADR is docs-only, so the gate has nothing to catch and the
architecture review should not be held hostage to it.

Review does **not** run per commit: most commits are incomplete, so per-commit
review spends OpenAI calls to critique half-built code and buries signal in
noise.

### 2. Advisory and non-blocking — never a required check

The review posts its ranked findings and verdict (`docs/review/guide.md`) as a
**PR comment**. It is **not** a required status check. The only check that blocks
merge remains the mechanical `gate` (ADR-0010). This preserves two properties the
reviewer is designed around:

- It is advisory by contract — it may disagree with a ratified ADR only as a
  note, never as a block (`docs/review/guide.md`).
- Its output is **non-deterministic**. A required LLM check would flake and block
  merges on a coin-flip. A comment tolerates variance; a gate does not.

Resolving or waiving `blocker`/`major` findings stays a human judgment recorded
in the PR, enforced socially by the one required approving review — not by CI.

### 3. A single Codex reviewer — no dual panel

The independence that matters is *reviewer ≠ author*. Claude authors the code, so
Codex-as-reviewer already satisfies it. We will **not** run a second Claude
reviewer alongside Codex: a same-family reviewer shares the author's blind spots,
so it roughly doubles cost and egress for little independent signal. One
independent reviewer, always Codex.

**Revisit if authorship changes.** If a contributor's agent is itself
Codex-based, Codex-reviewing-Codex loses independence for that code; the reviewer
should then be the model the author is *not*. That is a re-trigger for this
decision, not something to build now.

### 4. Egress and the trust posture

The review sends the **code diff** (not user data) to OpenAI — consistent with
the existing deliberate-egress design and with ADR-0004 (which governs *user*
data; this is developer code review). It is gated to `ready` and `/review`, not
per commit, so the volume is bounded.

CI runs the review with **full read-only repo access**, the same as the local
run. That rests on an explicit assumption: **every contributor with write access
is trusted.** Two residual risks come with it, and we accept both for the current
team:

- *A modified review script.* Same-repo branches receive the secret, so a PR
  could in principle edit `scripts/codex-review.sh` to leak the key. Trusting
  write-access contributors is what makes this acceptable.
- *Prompt injection through the diff.* The diff is untrusted input to a
  tool-capable, credentialed reviewer. Because this is an AI-assistant project, a
  PR may *legitimately* add adversarial fixtures (injection payloads, jailbreak
  strings) that could induce the reviewer to read and emit the key. The author's
  good faith does not remove this — the payload is *meant* to be in the diff.

Because the stake is bounded — an OpenAI key is spend on one account, rotatable,
not user data — we match the mitigation to it rather than engineering isolation:

- **A dedicated, spend-capped review key.** CI uses its own `OPENAI_API_KEY`
  (review-only, a low monthly cap), never a shared or primary key. A leak by
  *either* path above then costs a capped key we rotate in minutes, not our main
  credential.
- **`/review` runs only for an authorized actor** (write access), so a drive-by
  comment cannot burn the capped budget.

**Revisit trigger — escalate to forks at scale.** This posture is right for a
small, mutually-trusted team. When the assumption weakens — more contributors, or
any external/untrusted one — move to **fork-based contribution**: GitHub withholds
secrets from fork PRs by default, so an untrusted fork's diff cannot reach the key
(a maintainer re-runs the review, or it runs only post-merge). That is the scaling
answer. Building an isolated reviewer (tool-less, or a sandboxed/scoped-retrieval
harness) before then would defend against a contributor we do not have, at the
cost of real work and a shallower reviewer.

**Amendment (2026-07-18): Codex's own sandbox does not run in CI.** The local
run executes Codex with its read-only sandbox (`-s read-only`), which confines
the reviewer to reading the repo and — critically — **blocks network egress**.
On GitHub-hosted runners that sandbox cannot initialize: bubblewrap fails to
bring up the loopback interface in its network namespace
(`bwrap: loopback: Failed RTM_NEWADDR`), and under read-only mode that failure
breaks every file read, degrading the review to an apology instead of a verdict.
No Codex mode keeps the filesystem read-only *and* blocks the network without
that namespace, so in CI we run Codex **without its sandbox**
(`--dangerously-bypass-approvals-and-sandbox`, the case its own help documents
for "environments that are externally sandboxed" — the ephemeral runner is
exactly that). `scripts/codex-review.sh` selects this only when
`GITHUB_ACTIONS == "true"` (or `CODEX_REVIEW_NO_SANDBOX=1`) and keeps
`-s read-only` locally, where the sandbox works and is a real layer.

- *Threat-model consequence.* Dropping the sandbox removes the network-egress
  block. A successful prompt injection through the diff (above) could therefore
  now exfiltrate the review key **silently over the network**, not only by
  emitting it into the visible PR comment. We accept this for the current team:
  the *channel* widens, but the *stake* and the *risk owner* do not — the key is
  dedicated, spend-capped, and rotatable; the runner is ephemeral; and both
  review paths are gated to write-access actors we already trust. A leak still
  costs a capped key we rotate in minutes, not user data or a primary credential.
- *The job's GitHub token is kept out of the review's reach.* The OpenAI key is
  not the only credential present: `actions/checkout` persists the job
  `GITHUB_TOKEN` (scope `pull-requests: write`) into `.git/config` by default,
  where the bypassed-sandbox reviewer could read and abuse or exfiltrate it. We
  set **`persist-credentials: false`** on both checkouts, so no git credential is
  left in the workspace the reviewer runs in. `gh` uses the token from the step
  *environment* (never in scope during the Codex run), and the repo is public so
  history fetches need no credential. The token is also job-scoped and expires
  with the run. If the repo ever goes private, restore credentials for the fetch
  by other means — not by re-persisting them into the reviewed workspace.
- *Alternatives rejected.* Making bubblewrap's namespace work on the runner is
  fragile — pinned to the runner image's kernel/AppArmor and to Codex's sandbox
  internals (both change without notice), and against Codex's documented CI
  guidance; when it breaks it degrades silently to no review. An egress allowlist
  (permit only OpenAI) needs recurring DNS/IP maintenance GitHub gives no native
  support for. Neither is worth it to protect a capped, rotatable key.
- *Revisit trigger unchanged — and it also resolves this.* Moving to fork-based
  contribution when the trust assumption weakens withholds the key from untrusted
  diffs entirely, at which point the widened exfil channel is moot.

### 5. Freshness: a result binds to the commit it reviewed

A review is only honest about the commit it saw. Every posted result **names the
head SHA it reviewed**, and a push to a ready PR re-runs the review (§1), so a
later commit does not hide behind an earlier clean verdict. A result whose SHA is
no longer the PR head is, by definition, stale — the re-run supersedes it. This
keeps the audit trail (§ Context, gap 2) truthful rather than merely present.

## Alternatives considered

- **Per-commit review in CI.** Rejected: reviews incomplete WIP, multiplies
  OpenAI cost and latency, and floods the PR with findings about code that is not
  done. The review's value is on the complete diff.
- **A required, blocking review check.** Rejected: contradicts the reviewer's
  advisory role and would make merges hostage to a non-deterministic model.
- **Reimplement the review as a bespoke Action (logic in YAML).** Rejected: it
  would fork the review logic from the local script and the two would drift.
  CI runs the script instead.
- **Move fully to CI and delete the local script.** Rejected: the local loop is
  faster, incurs no round-trip, and defers egress until wanted. Keeping both
  costs nothing since they share one engine.
- **A dual Claude + Codex review panel.** Rejected (§3): independence is already
  met by Codex; a same-family second reviewer doubles cost for correlated
  findings.
- **Strict isolation now — a tool-less reviewer, or a sandboxed/scoped-retrieval
  harness that keeps the credential unreachable from the diff.** Rejected *for the
  current team* (§4): it defends against an adversarial contributor we do not
  have, costs real implementation work, and (tool-less) yields a shallower
  reviewer that cannot read across the tree to confirm a finding. Adopted instead
  as the **fork-based escalation path** once the trust assumption weakens.
- **Status quo (local, manual only).** Rejected: no assurance it ran, no audit
  trail, invisible in parallel work — the gaps that motivated this ADR.

## Consequences

- Review findings live on the PR, on the record, and consistently — closing the
  "did it run / what did it find" gap for parallel work.
- The review costs OpenAI calls at `ready` time and on `/review`, bounded and
  predictable rather than per commit.
- A maintainer must provision a **dedicated, spend-capped** OpenAI key as the
  `OPENAI_API_KEY` Actions secret; until then CI review is inert and the local
  path is the fallback.
- Because the review is non-blocking, a careless author can ignore its findings;
  the required human approval and the "report the outcome in the PR" norm are the
  backstop, not CI.
- **Full repo access rests on trust (§4).** The CI reviewer reads the whole tree,
  so its findings are as deep as a local run — the price is the two residual risks
  in §4, bounded by the capped key. When the team grows, the fork escalation is
  the answer, and this ADR is where that trigger is written down.
- **Simpler to build than an isolated design.** CI runs the existing script as-is
  with the key — no tool-less client or sandbox harness to engineer. The follow-up
  slice is just the workflow (`.github/workflows/codex-review.yml`), the
  gate-green + push + `/review` triggers, and the CONTRIBUTING update.
- This ADR decides the shape; the implementation lands as a follow-up slice.
- Revisit when a contributor's authoring model changes (§3), when the trust
  assumption weakens (§4 — move to forks), or if OpenAI egress policy tightens
  under a future ADR-0004 revision.
