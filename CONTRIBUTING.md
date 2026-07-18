# Contributing & development standards

This is the authoritative reference for how code is written, reviewed, and
committed in this project. It applies to human and AI contributors alike;
`CLAUDE.md` is the short operating agreement for agents and points here for
detail. Decisions recorded here are ratified in `docs/adr/0003-development-standards.md`.

## Setup

```bash
uv sync                                   # create/refresh the environment
uv run pre-commit install --install-hooks --hook-type commit-msg
git config commit.template .gitmessage    # scaffold commit messages
```

## The gate (Definition of Done)

A change is done only when all of these pass locally:

```bash
uv run ruff format .        # format
uv run ruff check .         # lint (--fix to autofix)
uv run mypy                 # strict type check
uv run lint-imports         # architecture boundary check
uv run pytest               # tests
```

`pre-commit` runs the fast subset on every commit. There is no remote CI yet
(see ADR-0002), so the local gate is the only automated safety net — run it.

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
just review-codex architecture      # or: scripts/codex-review.sh architecture master
just review-codex adversarial
```

Reviewers are advisory tooling, not a hard gate. Resolve `blocker`/`major`
findings before merging, or waive them with a written rationale in the PR/commit.
A reviewer that disagrees with a ratified decision files an ADR proposal — it
does not block on it (see the authority hierarchy in `docs/review/guide.md`).

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

- **Trunk-based.** `main` is always green. Do each unit of work on a short-lived
  branch named `<area>/<slug>` (e.g. `models/provider-protocol`).
- **Linear history.** Rebase onto `main`; no merge commits. Condense a branch to
  one (or a few) logical commits before integrating.
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
  every implementation must pass.
- **Fakes over mocks.** A test never imports another subsystem's internals; use
  the Protocol and a fake.
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
