# Contributing & development standards

This is the authoritative reference for how code is written, reviewed, and
committed in this project. It applies to human and AI contributors alike;
`CLAUDE.md` is the short operating agreement for agents and points here for
detail. Decisions recorded here are ratified in `docs/adr/0003-development-standards.md`.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
(the task runner behind every `just ...` command below, including workspace
claiming and the gate itself) — install both before continuing.

```bash
uv sync   # create/refresh the environment

# Install pre-commit as a standalone tool, pinned to the version uv.lock just
# resolved — once per machine, not per workspace (see below for why).
uv tool install "pre-commit==$(uv run python -c 'import importlib.metadata as m; print(m.version("pre-commit"))')"

"$(uv tool dir --bin)/pre-commit" install --install-hooks # pre-commit + commit-msg hooks
git config commit.template .gitmessage                    # scaffold commit messages
```

Step 3 calls the standalone tool by its resolved absolute path, not bare
`pre-commit` — if a workspace's own `.venv` is active (`source
.venv/bin/activate`), that puts a *second*, workspace-bound `pre-commit`
earlier on `PATH` (it's a project dev dependency too, for ad hoc `uv run
pre-commit run --all-files`); resolving explicitly is what stops that copy
from silently winning and re-introducing the exact bug this section exists to
avoid. (`just setup` runs all four steps for you, already using the resolved
path.) If step 2 warns that `uv`'s tool directory isn't on `PATH` at all, run
`uv tool update-shell` and open a new shell — needed for running `pre-commit`
directly afterward, not for setup itself, which never depends on `PATH` for
this step.

Install pre-commit as a standalone tool (`uv tool install`), not via
`uv run` inside a workspace. Git hooks live under the repo's shared
`.git/hooks` — one set for every worktree, not one per worktree — but
`pre-commit install` bakes the *installing* Python's absolute path into the
hook script. Run it with `uv run` from inside a claimed workspace and that
path points at that workspace's `.venv`; release or prune that workspace
later and every other worktree's commits start failing with `` `pre-commit`
not found ``. A standalone tool install lives outside any workspace, so the
hook keeps working no matter which workspaces come and go.

The version is pinned to whatever this workspace's `uv sync` just resolved
from `uv.lock` (`pre-commit>=4.6.0` in `pyproject.toml`), not left
unpinned — a bare `uv tool install pre-commit` would grab whatever is
latest on the machine at install time, letting the hook runner drift from
the locked dev dependency ADR-0003 requires. Re-run the command whenever the
project's pinned `pre-commit` version changes so the global tool stays in
sync. The tool install is machine-global, not per-worktree: if two worktrees
are on branches whose `uv.lock` resolves a different `pre-commit` version
(e.g. one is mid-upgrade), whichever ran setup most recently wins for every
worktree's hooks until the other reruns it — last-writer-wins, not
per-worktree isolation. In the ordinary case (`master`'s pin, followed
consistently) this never comes up.

Already set up from before this fix? Rerun the commands above — they
re-anchor the hook to the pinned tool install instead of whatever workspace
last ran `pre-commit install`. (An even earlier version of this command only
installed the `commit-msg` hook; rerunning also picks up the `pre-commit`
stage — ruff, mypy, import-linter — if you're that far behind. A stale
install fails silently rather than erroring.)

## The gate (Definition of Done)

A change is done only when all of these pass locally:

```bash
uv run ruff format .        # format
uv run ruff check .         # lint (--fix to autofix)
uv run mypy                 # strict type check
uv run lint-imports         # architecture boundary check
uv run pytest               # tests
```

`pre-commit` runs the fast subset on every commit; CI runs the full gate on
every pull request and push to `master` (`.github/workflows/gate.yml`, ADR-0010).
CI is the backstop now that more than one person commits — but run the gate
locally before you push. A red PR is a wasted round-trip, not a first line of
defence.

## Review (pre-merge)

The gate is mechanical; it cannot judge design or the adequacy of tests. Before
merging a slice branch — **after** the gate is green — put the change through
adversarial review. Claude writes the code; **Codex reviews it**, so every change
is judged by a model independent of the one that produced it.

Two reviewers, defined by shared rubrics in `docs/review/`:

- **architecture** — boundaries, contract discipline, ADR adherence, and drift
  from `VISION.md`.
- **adversarial** — tries to break the code: edge cases, error paths,
  concurrency, data integrity, and test gaps.

Run each against the base branch (read-only; this **sends the diff to OpenAI**,
so it is a deliberate pre-merge step, not per-commit):

```bash
just review-codex architecture      # or: scripts/codex-review.sh architecture
just review-codex adversarial       # base-ref defaults to origin/master (fetch first)
```

**Iterate locally, in draft — not against CI.** `just review-codex` runs the
identical engine and rubrics CI uses (below), so looping it first substantially
cuts the odds of meeting a finding for the first time in a CI comment — though
not to zero, since LLM review is not deterministic (ADR-0012): a clean local
run is a strong signal, not a guarantee. Loop it while the PR is still a
**draft**: fix, **commit** (a small follow-up commit is fine — it reviews
`HEAD` vs the base, i.e. the *committed* diff, not your working tree, so an
uncommitted fix is invisible to a re-run), re-run `just review-codex`, repeat,
until it comes back clean or only findings you're deliberately waiving remain.
A draft PR is never auto-reviewed, so this costs nothing in CI spend and
iterates faster than waiting on a hosted run each time.

Only mark the PR **ready for review** once the change is genuinely done —
that transition is the one deliberate checkpoint meant to trigger the
CI-hosted review that goes on the record (ADR-0012). If it still finds
something real, fix it, confirm with `just review-codex` locally, and push
once — don't push a fix per individual finding and let CI re-review after
every push (a ready PR is auto-reviewed on *every* push, same as the
ready-transition itself). Budget for **one CI review at ready, plus at most
one or two more** if genuine feedback needs incorporating; a PR that racks up
many CI review rounds after going ready is usually a sign the local loop above
got skipped, not that the code was unusually hard to get right.

Reviewers are advisory tooling, not a hard gate. Resolve `blocker`/`major`
findings before merging, or waive them with a written rationale in the PR/commit.
A reviewer that disagrees with a ratified decision files an ADR proposal — it
does not block on it (see the authority hierarchy in `docs/review/guide.md`).

### Review in CI (ADR-0012)

The same engine also runs in CI (`.github/workflows/codex-review.yml`) and posts
its findings as a **PR comment** — so the review is on the record, not just in
someone's terminal. It is **advisory and non-blocking**: the only required check
is `gate`; a review comment never blocks merge.

- **Automatic.** When you mark a PR **ready for review** (and on later pushes to
  a ready PR), the adversarial review runs — but only **after `gate` is green**
  for that commit. Draft PRs are never auto-reviewed. Each comment names the
  commit it covers; a new push supersedes the old comment. This fires on
  *every* push to a ready PR, not just the ready-transition — see "Iterate
  locally, in draft" above for why that means iterating locally first, not
  pushing fix-per-finding and letting each push spend another hosted review.
- **On demand.** Comment **`/review`** (or **`/review architecture`**) on any PR —
  **including a draft, and without waiting on `gate`** — to run a review; the
  architecture lens suits a `Proposed` ADR. Restricted to contributors with write
  access.

The **local** `just review-codex` above is unchanged — use it for fast iteration
before pushing. Local and CI run the *same* script and rubrics, so they cannot
drift.

CI review runs with full repo read access on the trust assumption of ADR-0012
§4, keyed by a **dedicated, spend-capped** `OPENAI_API_KEY` in the repository's
Actions secrets. No key → CI review is inert and the local path is the fallback.

### Architecture review of ADRs (at the Proposed stage)

The architecture reviewer's natural subject is a *decision*, not just a diff. A
**substantive contract ADR** — one that adds or changes a Protocol or a `core`
type that crosses subsystem boundaries — gets an architecture review **while it
is still `Proposed`, before ratification**, so a finding can still change the
decision (reviewing an already-Accepted ADR is too late to matter):

```bash
just review-codex architecture      # run on the branch holding the drafted ADR
```

Triage the findings, fold real ones into the draft, then flip the ADR to
`Accepted`. This is advisory like all review: the author still owns
ratification; the reviewer only surfaces blind spots (a missed alternative,
inconsistency with a prior ADR, a seam that will not extend). **Trivial ADRs**
(amendments, status changes, supersedes) skip this — not worth the round-trip.

## Git & commits

- **Trunk-based.** `master` is always green. Do each unit of work on a
  short-lived branch named `<area>/<slug>` (e.g. `models/provider-protocol`).
- **Linear history.** Rebase onto `master`; no merge commits. Condense a branch
  to one (or a few) logical commits before integrating.
- **One logical change per commit.**
- **Conventional Commits**, enforced by a `commit-msg` hook:

  ```
  <type>(<scope>): <subject>

  <body — explain WHY>

  Refs: ADR-NNNN
  ```

  - `type`: `feat` | `fix` | `docs` | `refactor` | `test` | `chore` | `perf` |
    `build` | `ci`. Breaking change: `feat(models)!: ...`.
  - `scope`: the subsystem (`core`, `models`, `memory`, ...).
  - Subject: imperative, ≤72 chars, no trailing period.
- **Trace commits to decisions.** When a commit implements or is governed by an
  ADR, add a `Refs: ADR-NNNN` trailer (multiple allowed:
  `Refs: ADR-0002, ADR-0003`). Retrieve a decision's implementation with
  `git log --grep 'ADR-0003'`.
- **Never commit** secrets or generated artifacts (`.gitignore` covers the
  common cases; `detect-private-key` guards commits).

### Working on GitHub (pull requests)

The repository is hosted on GitHub with more than one contributor, so `master`
is protected and integration happens through pull requests — not local merges
(ADR-0010).

- **Never push to `master`.** Push your `<area>/<slug>` branch and open a PR.
- **Open a draft PR early — always.** As soon as you have a branch and a first
  commit, open it as a **draft**, before the work is done. CI runs on every push
  so you get the gate continuously, and the other contributor can see your
  direction (and any contract change) before it lands. Mark it **ready for
  review** only when the change is complete: that flip is the signal that it
  wants a review — and the trigger the automated review acts on (see "Review",
  above). A change that is genuinely complete in one commit may open ready.
- **CI gates the PR.** The `gate` workflow runs the full Definition-of-Done gate
  on every PR and push; a PR cannot merge while it is red. This is enforced for
  everyone. Run the gate locally first anyway — CI is the backstop, not the
  substitute.
- **One approving review is required** before merge. Report the pre-merge Codex
  reviews (architecture / adversarial, above) in the PR description: the outcome,
  and any `blocker`/`major` finding you waived with its rationale.
- **Rebase and merge.** Rebase your branch onto `master` and merge via GitHub's
  *Rebase and merge* so linear history holds and each commit keeps its
  `Refs: ADR-NNNN` trailer. Delete the branch after merge.
- **Low-collision by design.** Work is split across low-overlap sections, so
  rebase conflicts should be rare; whoever merges second resolves them.
- Administrators retain a bypass for genuine emergencies — the gate still runs,
  but use the escape hatch sparingly and say why in the PR.

### Coordinating parallel work

**One workspace per unit of work.** Parallel agents must never share a working
tree — sharing one is how a stray `git add -A` can sweep another agent's
uncommitted files into the wrong commit. Each branch (each PR) gets its own
**linked worktree**, allocated by `just claim-workspace <area>/<slug>`, always —
there is no shared "first agent gets the bare checkout" slot to race for, so any
number of agents can claim in parallel with nothing to coordinate here. The
command creates the branch, bootstraps the environment (`uv sync` plus a copy of
git-ignored local config), and prints `WORKSPACE=<path>` — **work only there**.
Release it after the PR merges with `just release-workspace <area>/<slug>`.
Release removes the worktree but **deliberately leaves the branch name
claimed** — `require_new_branch` refuses to reuse it — until
`just prune-workspaces` confirms via GitHub that its PR actually merged or
closed and frees it. That is what lets `prune-workspaces` trust a
branch-name-to-PR match at all: reusing a name immediately on release would
let a brand-new claim collide with an old, already-merged PR of the same name.

Running several agents at once: `just claim-workspaces <area>/<slug> ...`
claims multiple branches concurrently in one command (each still runs its own
`uv sync`, which may serialise a little on uv's package-cache lock — this
parallelises the git side, not necessarily the bootstrap side). `just
workspaces` lists what's currently claimed (branch, clean/dirty, last commit,
path); `just prune-workspaces` reports worktrees whose PR has since merged or
closed (`FORCE=1` to actually remove them) so parallel claims don't
silently accumulate on disk.

- **Fetch before you claim.** Run `git fetch origin` first — *not*
  `git checkout master`, which would switch branches in the shared main checkout
  and stomp whatever the main checkout's `master` state is being used for
  elsewhere. `fetch` updates `origin/master` without touching any working tree,
  and the claim branches new work from `origin/master`, so your branch starts
  from the latest merged state.
- **Stacking one branch on another** (splitting a task into dependent PRs
  before the first has merged): `just claim-workspace <area>/<slug> <base>`
  takes an optional second argument — any branch, tag, or commit — as the new
  branch's start-point instead of `origin/master`. This is opt-in only: a
  claim never guesses at "wherever some other worktree happens to be" on its
  own, so omitting it always means the usual `origin/master` default.
- The main checkout is never claimed — it stays on `master` permanently, as a
  read-only integration copy. The `no-commit-to-branch` pre-commit hook refuses
  direct commits to it, so nothing can accidentally treat it as a workspace.
- A worktree shares the repo's object store and refs (not its working tree), so
  branches still integrate through the PR flow unchanged. Its `.venv` and
  git-ignored files are per-directory, which is why claiming re-bootstraps (uv's
  cache keeps this cheap; a shared venv is not an option — the editable install
  is path-specific).
- `git worktree add` for a fresh branch name is safe under concurrency on its
  own (git serialises its own worktree-administration writes), so claiming many
  workspaces at once needs no additional locking.

The subsystem split keeps most work in non-overlapping folders, but two places
are shared surfaces that the gate cannot referee — a collision there is a valid
diff that passes every check and only surfaces as a conflict on the second
rebase. Coordinate them by hand:

- **ADR numbers are a shared counter — claim yours up front.** The number is
  *provisional until merge*. Before drafting, record the number you are taking in
  the "ADR numbers in flight" list in [`WORKING.md`](WORKING.md) so a concurrent
  branch does not grab the same one. If two branches still land on the same
  number, **the second to merge renumbers** — it is a file rename plus its
  internal `ADR-NNNN` references and any `Refs:` trailers, no code change.
- **Changing `core/` is the one high-collision edit — flag it loudly.**
  `core/protocols.py` and `core/types.py` are touched by every subsystem, and a
  Protocol change is breaking (golden rule 5). Every branch is a draft PR early
  (above), so the shape is already visible — but for a `core/` change, push the
  contract *first* (ahead of the implementation) and say so in the PR title, so
  the other stream sees the new shape before building against the old one. The
  flag golden rule 5 asks for has to reach the *other contributor*, not just the
  reviewer.
- **Stay in your lane.** Who currently owns which subsystem is recorded in
  [`WORKING.md`](WORKING.md). Check it before starting, and update it when you
  pick up or hand off a subsystem, so two people do not converge on the same one.

## Typing & code style

- **mypy `strict`** is mandatory. No implicit `Any`.
- `# type: ignore[code]` must name the specific error code and carry a short
  reason comment. Blanket `# type: ignore` is banned (ruff `PGH003`).
- **Ruff at maximum** (see `pyproject.toml` for the full rule set): security
  (`S`), complexity (`C90`, max 10), pylint subset (`PL`), no commented-out code
  (`ERA`), no relative imports (`TID`), async pitfalls (`ASYNC`), timezone-aware
  datetimes (`DTZ`), and more.
- **Line length 100.** Absolute imports only.
- **Design types:** `typing.Protocol` for cross-subsystem seams; pydantic models
  for data that crosses boundaries (defined in `core/types.py`); frozen
  dataclasses / `Final` for internal immutable values.
- `from __future__ import annotations` at the top of every module.
- **Async for all I/O.** No blocking calls on async code paths.
- **Errors:** raise only from the `AssistantError` hierarchy (`core/errors.py`).
  No bare `except`; never silently swallow an exception.
- **Logging:** `structlog` only. No `print` except deliberate CLI rendering
  (Rich). Never log secrets or PII.
- **Config:** read everything through `core.config.Settings`; never touch
  `os.environ` directly.
- **Determinism:** inject the clock and randomness; never call `datetime.now()`
  or `random` directly in library code.

## Architecture boundaries (mechanically enforced)

`uv run lint-imports` fails the build if any of these are violated:

1. `core` imports nothing else in `ai_assistant`.
2. Subsystems (`models`, `memory`, `context`, `planning`, `tools`,
   `permissions`, `learning`) never import one another.
3. Subsystems never import `orchestration` or `interfaces` (dependencies point
   inward).
4. Provider SDKs (`pydantic_ai`, `anthropic`, `openai`, ...) are imported only
   inside `models/`.

Subsystems communicate only through the Protocols in `core/protocols.py`. A
Protocol change is a breaking change: call it out and add an ADR first.

## Documentation

- **Google-style docstrings**, enforced by ruff (`D`, `convention = "google"`).
- Required on public modules, classes, and functions/methods; optional on
  private helpers.
- Do **not** repeat types in docstrings — they live in annotations.
- Comments explain **why**, not what. No commented-out code.
- Record every non-obvious decision as an ADR (`docs/adr/`, see the template).

## Testing

- `pytest`; tests mirror the package path (`tests/<pkg>/test_*.py`); name tests
  `test_<unit>_<behavior>`; structure them Arrange–Act–Assert.
- **Protocol conformance suites:** each Protocol gets a shared test suite that
  every implementation must pass — an abstract `…Contract` base (not
  `Test`-prefixed) with a subject fixture overridden per implementation. See
  `tests/memory/memory_store_contract.py` and
  `tests/learning/feedback_processor_contract.py`.
- **Fakes over mocks.** A test never imports another subsystem's internals; use
  the Protocol and a fake. Canonical shared fakes live in `ai_assistant.testing`
  (e.g. `FakeMemoryStore`) — import those rather than hand-rolling a mock, and
  make each fake pass its Protocol's conformance suite. `ai_assistant.testing` is
  test-only; production code importing it fails `lint-imports`.
- No network or filesystem in unit tests. Anything that needs them is marked
  `@pytest.mark.integration`.
- Tests are deterministic — inject clock/randomness.
- No coverage gate (ADR-0003); adequacy of tests is a review concern.

## Dependencies & security

- **uv only.** The lockfile is committed; `uv sync` is reproducible.
- Adding a runtime dependency needs a one-line justification in the change; a
  foundational dependency needs an ADR.
- `uv run pip-audit` reports known vulnerabilities (advisory; run before
  releases).
- Secrets come from the environment via `Settings`; `.env` is never committed.

## Versioning

- **SemVer.** Pre-1.0 (`0.x`): anything may change between minors.
- The version lives once in `pyproject.toml`; `ai_assistant.__version__` reads it
  from installed metadata. Do not hardcode it elsewhere.
- User-facing changes are noted in `CHANGELOG.md` (Keep a Changelog format).
