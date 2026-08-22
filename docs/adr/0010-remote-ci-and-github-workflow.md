# 10. Remote CI and the GitHub collaboration workflow

- Status: Partially superseded by ADR-0167 (the "Branch protection (pragmatic)" clause's administrator-bypass and approving-review bullets, and the settings-change route to tightening)
- Date: 2026-07-18
- Amended: 2026-08-22 (the gate's `pytest` step is distributed — see the
  dated section at the end). It is still the same five steps over the whole
  suite; nothing decided here changes.
- Partially superseded: 2026-08-20 by ADR-0167 — **the branch protection named
  below is not the branch protection this repository runs, and the configuration
  is now the decision; everything this ADR decided about the remote gate, PR
  integration and the merge method stands.**
  [ADR-0167](0167-the-gate-binds-the-merge-path-the-admin-bypass-is-deliberate-and-no-approval-is-required.md)
  records what `gh api repos/{owner}/{repo}/branches/main/protection` returns:
  `enforce_admins` is **false**, which exempts repository administrators from
  every protection above it — the required `gate` check included — and
  `required_approving_review_count` is **0**, not one.

  **Replaced — the "Branch protection (pragmatic)" clause's administrator-bypass
  and approving-review bullets.** Its first bullet's "enforced for **everyone,
  with no bypass**", as a claim about the mechanism: ADR-0167 §2 keeps the
  conduct half of it word for word — nothing crosses the gate red, whatever the
  flag mechanically reaches — and replaces the claim that nothing can. Its
  "Require **one approving review**" bullet, retired by the owner's 2026-07-29
  ruling that the Codex review and the `gate` are the whole pre-merge bar
  (ADR-0167 §4). And its fourth bullet's exemption of administrators from "the
  review/up-to-date restrictions" alone, which is not the exemption that exists:
  the toggle is all-or-nothing, which is **why** the split this clause specified
  was never configurable (ADR-0167 §3).

  **Replaced — the settings-change route to tightening.** The Alternatives
  sentence "We chose the pragmatic variant … and can tighten to strict if the
  team or the blast radius grows — a settings change, not a new ADR", and the
  Revisit bullet in Consequences that names the same tightening. ADR-0167 §5
  ratifies `enforce_admins: false` as a decision, so enabling it now takes an ADR
  superseding ADR-0167; §6 states the fact that re-opens the question — a second
  person able to merge.

  **What stands.** The up-to-date and linear-history bullet is configured exactly
  as ratified here, and ADR-0167 §1 re-states it rather than re-deciding it. The
  "Remote gate", "Pull-request integration" and "Merge method" clauses are
  untouched, as is the 2026-07-19 amendment except where its settings list
  restates the bullets above, which is read through them. Nothing in this ADR's
  text is rewritten (ADR-0070 §1), and the record sits in this note rather than
  as a `Status` qualifier because the line now leads with the supersession token
  (ADR-0082 §2).

## Context

ADR-0002 deferred remote CI: *"Remote CI (e.g. GitHub Actions) is deferred;
revisit in a future ADR when hosting is chosen."* That was correct for a
single-committer repository where the author ran the gate locally before every
integration — the `pre-commit` hook plus the local gate were a sufficient safety
net because one machine gated everything.

Two things have now changed:

1. The repository is hosted on **GitHub** for remote version control.
2. A **second contributor** has joined, working in a low-collision section.

The safety model breaks under the second change. The local gate only protects
what runs on the author's machine; a collaborator's "it passed" is invisible and
unverifiable, and the current integration path (a local branch merged straight
into `master`) has no point where a neutral party re-runs the gate. This is the
"hosting is chosen" trigger ADR-0002 named. This ADR supersedes **only** the CI
deferral in ADR-0002; the rest of ADR-0002 stands.

## Decision

**We will run the gate in CI and integrate through protected pull requests.**

**Remote gate.** A GitHub Actions workflow (`.github/workflows/gate.yml`, job
`gate`) runs the five Definition-of-Done steps — `ruff format --check`,
`ruff check`, `mypy`, `lint-imports`, `pytest` — on every pull request and every
push to `master`, against the locked environment (`uv sync --locked`). The steps
and their order mirror the local gate exactly, so CI is the same gate on neutral
ground, not a second, divergent one.

**Pull-request integration.** `master` is no longer pushed to directly.
Each unit of work lands through a PR from an `<area>/<slug>` branch. This makes
the existing pre-merge Codex reviews (CONTRIBUTING, "Review") reportable in the
PR rather than performed privately before a local merge.

**Branch protection (pragmatic).** On `master`:

- Require the `gate` status check to pass before merging — enforced for
  **everyone, with no bypass**. The gate is the safety net; nothing crosses it
  red.
- Require **one approving review**.
- Require the branch to be **up to date** before merging, and require
  **linear history** — matching the rebase-only history ADR-0003 already
  mandates.
- **Do not** include administrators in the review/up-to-date restrictions,
  leaving an escape hatch for a genuine solo emergency.

**Merge method.** *Rebase and merge* only (squash and plain merge commits
disabled). This keeps the linear history of ADR-0003 while preserving each
logical commit and its `Refs: ADR-NNNN` trailer — which a squash would collapse.

The mechanics for contributors live in CONTRIBUTING ("Working on GitHub"); this
ADR records the decision and its rationale.

## Alternatives considered

- **Keep local-only gating (status quo).** Rejected: it cannot verify a second
  contributor's work. The whole point of hosting was to make integration safe
  across machines.
- **Strict protection — administrators included, no bypass.** Safer on paper,
  but with two contributors it also blocks the author from a legitimate hotfix
  and adds round-trips with no real adversary to protect against yet. We chose
  the pragmatic variant (CI required for all; review + up-to-date not enforced
  on admins) and can tighten to strict if the team or the blast radius grows —
  a settings change, not a new ADR.
- **Squash-and-merge.** The common GitHub default and it yields linear history,
  but it collapses a branch's several logical commits into one, destroying the
  one-logical-change-per-commit granularity and the per-commit `Refs: ADR-NNNN`
  trailers that `git log --grep ADR-NNNN` relies on. Rejected in favour of
  rebase-and-merge.
- **Merge commits (`--no-ff`).** Matches the local practice the repo had drifted
  into, but contradicts the linear-history rule ratified in ADR-0003. Rejected;
  we align to the ratified standard instead of the drift.
- **A heavier gate in CI (add `pip-audit`, coverage, matrix builds).**
  Deferred. `pip-audit` stays advisory/pre-release (CONTRIBUTING), there is no
  coverage gate (ADR-0003), and a single-version build matches the pinned-Python
  stack. CI should be the existing gate, not a new set of rules smuggled in.

## Consequences

- A collaborator's change is verified by the same gate as the author's, on
  neutral infrastructure, before it can reach `master`.
- The pre-merge architecture/adversarial Codex reviews now have a natural home
  (the PR) and an audit trail.
- Integration costs a PR round-trip and a green CI run instead of a local
  `git merge` — the intended trade for multi-contributor safety.
- Branch protection is repo configuration, not code; it is set once in the
  GitHub UI (or via `gh api`) and cannot be enforced by this repository's
  tooling. The settings are documented in CONTRIBUTING so the intent is
  reviewable even though the switch is external.
- Revisit if the team grows or an incident shows the pragmatic bypass was
  abused: tighten to strict protection (include administrators), or add required
  reviewers / CODEOWNERS.

## Amendment (2026-07-19): the integration branch is now `main`

The integration branch was renamed `master` → `main`. Everything above still
holds as ratified — read every `master` in this ADR as the branch now called
`main`. The text is left as written because ADRs are append-only (ADR-0001);
only the name of the branch changed, not the decision.

The rename went through GitHub's branch-rename, which moved the default branch
and carried the protection rules over unchanged: required `gate` check, strict
up-to-date, one approving review, linear history, no force-pushes, no deletions
— exactly the settings listed under "Branch protection (pragmatic)" above.

## Amendment (2026-08-22): the gate's `pytest` step runs across the runner's cores

The `Tests` step of `.github/workflows/gate.yml` is now `uv run pytest -n auto`
rather than `uv run pytest`. Everything above still holds as ratified: it is the
same five Definition-of-Done steps, in the same order, on the same triggers, over
the whole suite, and a green `gate` means exactly what it meant before.

Only the invocation changed, and only because the one thing that could not run
distributed no longer exists. `tests/core/test_protocol_triad.py` reads the run
record `tests/conftest.py` accumulates, and under `-n auto` each worker
accumulated only its own; [ADR-0179](0179-the-triad-check-reads-a-distributed-runs-merged-record-so-both-gates-run-across-cores.md)
merges the workers' halves on the controller, so nothing is deselected, skipped
or split across jobs. On the 4-vCPU `ubuntu-latest` runner this public
repository gets, the step went from 273s to 113s and the whole job from 5m28s to
2m45s.

Recorded as an amendment rather than a supersession because a reader acting on
this ADR acts identically before and after (ADR-0070 §1): what it decided is that
a remote gate runs those five steps and binds the merge path, not which process
count `pytest` uses. ADR-0166 §4's *restatement* — "CI's gate stays the full five
steps, serial" — did decide serialism, and ADR-0179 supersedes that clause there.
