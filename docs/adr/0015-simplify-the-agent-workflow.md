# 15. Simplify the agent workflow: local review, clone per agent, issues over files

- Status: Accepted, partially superseded by ADR-0020 and ADR-0025; Consequences' every-commit gate clause amended by ADR-0136
- Date: 2026-07-19
- **Amended: 2026-08-11 by
  [ADR-0136](0136-the-full-gate-is-owed-at-two-anchors-and-between-them-the-fast-gate-suffices.md)
  (Consequences — its every-commit full gate no longer binds between a branch's
  two anchors, and the measurement it rests on has expired).** The Consequences
  clause *"The gate is ~33s locally (27s of it pytest, 5,777 tests), so the full
  gate stays mandatory on every commit — no test selection, no judgment call, no
  CI-only divergence"* states its own premise, and the premise no longer holds:
  measured at `d94637ca` the suite is 15,678 tests collected and the serial run
  355.64s, against 2.14s for `ruff format`, `ruff check`, `mypy` and
  `lint-imports` together. `CONTRIBUTING.md` carried the companion rule with the
  trigger written into it — *"Revisit if `pytest` ever crosses a couple of
  minutes"* — and ADR-0136's Context records that it has fired. ADR-0136 §1 keeps
  the full gate mandatory at two anchors on a branch (before the first review
  invocation, and before the final push preceding `gh pr ready`) and §2 leaves
  `pytest` to the author's discretion between them, the four static steps staying
  mandatory throughout. A reader holding only this ADR would run the whole suite
  before every commit and would read its refusal of "test selection" and of a
  "judgment call" as reaching the whole branch, which is ADR-0082 §1's test met on
  its second limb, so the record is owed.
  **This is an amendment and not a supersession** (ADR-0070 §1): none of §§1–5
  moves. The local review loop, the triage rule, issues-over-files and
  dispatcher-assigned ADR numbers all stand exactly as ratified, and ADR-0136
  depends on several of them — §1's author-owned loop is what its anchors are
  anchored to, and §5's ratify-after-review sequencing is the rule ADR-0136 itself
  was ratified under. Nothing in Consequences is rewritten: the clause above stays
  legible where it was written, beside this note. What ADR-0136 does *not* touch is
  ADR-0010's remote gate, which still runs the full five steps on the triggers
  `.github/workflows/gate.yml` declares — four `pull_request` types and `push` to
  `main`, so every push to an open PR but not a push to a branch with no PR, as
  ADR-0136 §4 states. ADR-0136 §4 depends on that being unchanged, so this ADR's
  "no CI-only divergence" survives as a statement about what CI runs, and is
  narrowed only as a statement about what the author runs before each commit.
- Superseded: 2026-07-20 by ADR-0020 — §1's freshness clause ("refuses unless
  one exists for the exact commit the PR head is on") is replaced by an anchor on
  the reviewed content rather than the commit. The rest of §1 and §§2–5 stand.
- Superseded: 2026-07-20 by ADR-0025 (the one-shot review model) — §1 ran each
  review round as an independent cold `codex exec` with no memory across rounds;
  ADR-0025 replaces it with one persistent session per review loop, resumed each
  round. Local-only execution, the `.review/` artifact, ship-not-push, and the
  author owning the loop all stand.
- Supersedes: ADR-0012 (Codex review in CI)
- Amends: ADR-0010 §"working on GitHub" (review reporting), ADR-0003
  ("Coordinating parallel work")

## Context

The workflow built across ADR-0003, ADR-0010 and ADR-0012 optimised for
multi-agent parallelism enforced by tooling. Roughly 200 commits in, the
measured cost of that machinery exceeds its measured benefit:

- **Process outweighs product.** 147 of 197 commits touch process files
  (docs, scripts, workflows, justfile); 52 touch `src/`. `fix(dev)` is the
  single largest commit category at 46 commits — 24% of all history — and is
  almost entirely tooling repairing itself: seven consecutive commits on
  ambiguous base-ref resolution in `claim-workspace.sh`, five on `pre-commit`
  path resolution, nine on the `find-parallel-work` skill's own freshness
  checks. Meanwhile `orchestration`, `planning`, `tools` and `permissions`
  remain one-module stubs.
- **The review budget is prose, so it does not hold.** CONTRIBUTING budgets
  "one CI review at ready, plus at most one or two more" and names
  fix-per-finding as the anti-pattern. Actual: PR #17 drew 20 CI reviews over
  23 commits, #19 drew 10 over 16, #26 and #14 drew 6 each. The rule was
  written *after* #17 and was violated by three PRs after it. Nothing checked
  draft status or counted rounds.
- **Hand-maintained coordination state decays exactly when it matters.**
  `WORKING.md` on `origin/main` currently claims the `ContextProvider` triad is
  in progress (PR #34 merged), `planning` is unclaimed (PR #33 open, ADR-0014
  in flight), and that no ADR numbers are in flight. The file whose only job is
  preventing lane and ADR-number collisions is wrong about both.

The common cause: **invariants enforced by prose rather than mechanism.** Where
this project used mechanism — `lint-imports`, the `commit-msg` hook, generated
`just status` — the invariant held without exception. Where it used
documentation — the review budget, the lane ledger, "stay in your lane" — it has
already failed in recorded history.

The parallelism the machinery served is also not what actually happens: agents
are dispatched by hand, one task at a time, by a single operator.

## Decision

We will trade automated multi-agent coordination for a smaller surface that a
manually-dispatched agent can follow correctly.

**1. Review runs locally only; the artifact is SHA-anchored.**
`.github/workflows/codex-review.yml` and `scripts/codex_review_decision.py` are
removed. `scripts/codex-review.sh` is unchanged in what it does — Codex, a model
independent of the one writing the code, still reviews every change — but now
also writes its output to `.review/<sha>-<persona>.md`, keyed to the commit it
actually reviewed. The reviewer's independence is preserved; only the hosted
execution is dropped.

The review reaches the PR through `just ship` (`scripts/ship.sh`), which posts
the recorded review(s) and **refuses unless one exists for the exact commit the
PR head is on** — also refusing on a dirty tree, on `main`, and when the PR head
is behind local `HEAD`. A change touching `core/protocols.py` or `core/types.py`
must additionally carry the architecture lens.

This check sits at ship, not in a `pre-push` hook. Review is a pre-merge step;
gating every push would force a full Codex run per WIP commit — the per-push
cost pattern this ADR exists to remove — while ship is the one point where the
review actually has to be current.

We accept that a pasted review is self-attested where a CI-posted one was not.
The SHA anchor makes the common failure — a review of a stale commit — mechanical
rather than a matter of care. It is not tamper-proof, and does not try to be.

**The whole loop is the author's to run and to finish, agent or human.** Running
the review, incurring its spend, and marking the PR ready are steps of doing the
work, not decisions to escalate. An agent that pauses to ask "shall I review?" or
"is this ready?" reintroduces by hand the round-trip this ADR removes from CI.
Approval belongs at merge, where a human already reviews.

**2. One clone per agent, not one worktree per branch.**
`claim-workspace.sh`, `claim-workspaces.sh`, `release-workspace.sh`,
`prune-workspaces.sh` and `list-workspaces.sh` are removed (~856 lines of shell,
~1,770 lines of tests). Agents are dispatched by hand into a pre-existing local
clone and may assume they are the sole worker there. Isolation comes from the
clone, which needs no code to maintain.

**3. Review findings are triaged; PRs do not grow to absorb them.**
For each finding: fix it now if it is `blocker` or `major` *and* concerns code
in the current diff. Otherwise open a GitHub issue and leave the PR alone. The
trigger is the finding, not a PR size threshold — the history shows PRs did not
start large, they grew under review.

**4. Cross-change tracking lives in GitHub issues.**
`TODO.md` and `WORKING.md` are deleted, their live content migrated to issues.
Both were shared mutable files in git: a merge-conflict surface that duplicated
state GitHub already holds authoritatively. Under decisions 2 and 5, neither
retains a job — lane collisions are prevented by the dispatcher, ADR numbers are
assigned by the dispatcher.

**5. ADR numbers are assigned at dispatch; substantive contract ADRs land
before their implementation.**
The operator dispatching an agent assigns its ADR number, removing the race the
in-flight ledger failed to arbitrate. A substantive contract ADR — one adding or
changing a Protocol or a `core/` type crossing subsystem boundaries — ships as
its own PR, ratified before the implementation PR that depends on it. Trivial
ADRs (amendments, status changes, supersessions) are exempt, as they already
were from architecture review. An agent may run a throwaway spike branch to
inform the ADR, discarded before the ADR PR opens; a contract ratified with no
implementation contact is how a seam that does not survive first use gets
blessed.

## Consequences

**Easier.** The gate is ~33s locally (27s of it pytest, 5,777 tests), so the
full gate stays mandatory on every commit — no test selection, no judgment call,
no CI-only divergence. Review iterates at local speed with no hosted spend and
no draft/ready choreography. Roughly 2,600 lines of shell and shell-testing code
leave the repo, along with the class of `fix(dev)` commit that dominated the
history. Separate clones each own their `.git/hooks`, so plain
`uv run pre-commit install` is correct again and the absolute-path workaround in
CONTRIBUTING's Setup section is deleted.

**Harder.** Review is no longer on the record independently of the author.
Concurrent agents are limited by how many clones the operator maintains, and
nothing detects two agents colliding on a subsystem — that is now the operator's
job, deliberately. `prune-workspaces`' branch-name-reuse guard is gone; branch
hygiene is manual.

**Revisit if** more than one human contributor integrates regularly (self-attested
review stops being adequate when the author and the reader differ), or if agents
are dispatched programmatically rather than by hand — either restores the
conditions ADR-0012 and the claiming machinery were built for.

**Follow-on.** ADR-0012 is marked superseded. ADR-0010 remains append-only; its
review-reporting expectation is amended by this ADR rather than edited in place.
