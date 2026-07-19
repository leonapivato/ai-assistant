# CLAUDE.md — working agreement for agents

This project is intended to be built largely by AI agents. This file is the
contract you (an agent) work under. Read it fully before changing code.

## What this is

A model-agnostic AI operating system: an orchestration layer that understands
the user, manages long-term memory, plans tasks, coordinates tools, and learns
over time. The underlying LLM is interchangeable — the value is the
orchestration and personalization around it. See `README.md` for the vision and
`docs/adr/` for the decisions already made (do not relitigate them; propose a
new ADR if you think one should change).

**`CONTRIBUTING.md` is the full standards reference** (git, typing, docs,
testing, dependencies). This file is the short version — when in doubt, defer to
`CONTRIBUTING.md` and the ADRs.

## Golden rules

1. **Depend on contracts, not implementations.** Subsystems talk to each other
   only through the Protocols in `src/ai_assistant/core/protocols.py`. Never
   import one subsystem's concrete module from another subsystem. The
   `orchestration` engine receives implementations by injection.
2. **`core` depends on nothing else** in `ai_assistant`. Everything may depend
   on `core`.
3. **Interface adapters are thin.** No business logic in `interfaces/`.
4. **No provider SDK outside `models/`.** `anthropic`, `openai`, etc. are
   imported only there. Everyone else uses the `ModelProvider` Protocol.
5. **A Protocol change is a breaking change.** Flag it in your summary and add
   an ADR before implementing against it.

These boundaries (rules 1, 2, 4) are enforced mechanically by
`uv run lint-imports` — a violation fails the gate, it is not just a convention.

## Architecture map

```text
core/           contracts (Protocols), shared types, config, errors
models/         model-agnostic LLM layer (wraps pydantic-ai)   → ModelProvider
memory/         persistent user model + long-term memory        → MemoryStore
context/        situational context assembly (time, calendar, tasks)
planning/       request → executable plan, progress tracking
tools/          tool registry + external integrations
permissions/    policy/permission checks + audit trail
learning/       feedback capture → memory updates
orchestration/  the engine wiring the pipeline together (consumes contracts)
interfaces/     adapters (cli now; api/ui later)
```

Request pipeline (owned by `orchestration`): intent → context assembly →
memory retrieval → planning → tool selection → permission check → execute →
learn/update memory.

## How to work (make changes reviewable)

- **Claim a workspace first — before editing anything.** Run `git fetch origin`
  (which updates `origin/master` without touching any working tree — never
  `git checkout master`, which would move the shared main checkout off `master`),
  then `just claim-workspace <area>/<slug>` as the first action of any task. The
  claim branches your new work from `origin/master`, so the fetch keeps you
  current — give it a second argument (`just claim-workspace <area>/<slug>
  <base>`) to stack it on another branch instead, for a task split into
  dependent PRs; omitted, it always defaults to `origin/master`, never
  "wherever some other worktree happens to be." It puts you on a fresh branch
  in its own linked worktree — always, so any number of agents can run in
  parallel with none sharing a working tree — and prints `WORKSPACE=<path>`.
  **Work only in that path**, and never commit to `master`. Running several
  agents at once: `just claim-workspaces <area>/<slug> ...` claims multiple
  branches concurrently; `just workspaces` lists what's claimed; `just
  prune-workspaces` reports worktrees whose PR has merged or closed. Release a
  workspace after its PR merges with `just release-workspace <area>/<slug>`.
  (Details: `CONTRIBUTING.md` → "Coordinating parallel work".)
- **Stage explicit paths, never `git add -A`/`git add .`.** Add the specific
  files your change touches, so a stray sweep can't pick up unrelated work.
- **One subsystem per change.** Scope a change to a single package plus its
  tests. Small diffs review faster and fail more clearly.
- **Contract first.** If a subsystem needs a new capability from another, add or
  extend a Protocol in `core/protocols.py` first, get it reviewed, then
  implement against it.
- **Tests are the guardrail.** Add tests under `tests/` mirroring the package
  path. Test implementations against their Protocol. Use fakes/mocks for other
  subsystems — never reach into their internals.
- **Type everything.** `mypy` runs in `strict` mode; only specific, justified
  `# type: ignore[code]` — no blanket ignores.
- **Leave a paper trail.** Any non-obvious design decision goes in an ADR.

## The gate (must all pass before a change is done)

```bash
uv run ruff format .    # format
uv run ruff check .     # lint (add --fix to autofix)
uv run mypy             # strict type check
uv run lint-imports     # architecture boundary check
uv run pytest           # tests
```

CI runs this same gate on every PR and push to `master` (ADR-0010) — it is the
backstop, not the first line of defence; run it locally before pushing.
`pre-commit` runs the fast subset on commit; enable it once per machine with
`uv tool install pre-commit && pre-commit install --install-hooks` (a
standalone tool install, not `uv run` inside a workspace — see
`CONTRIBUTING.md` → "Setup" for why that distinction matters).

**Iterate against `just review-codex`, not against CI.** It runs the same
adversarial-review engine CI does (`CONTRIBUTING.md` → "Review (pre-merge)"),
against `origin/master` by default (fetch first). Loop locally while the PR
is a **draft** — fix, **commit** (it reviews `HEAD`, the committed diff, not
your working tree — an uncommitted fix is invisible to a re-run), re-run,
repeat — until it's clean or only deliberately-waived findings remain; a
draft is never auto-reviewed, so this costs nothing in CI spend. Flip to
**ready for review** only once, as the one deliberate checkpoint that
triggers the CI-hosted review that goes on the record — every push to an
*already-ready* PR triggers another one, so pushing a fix per finding and
letting CI re-review each time is the anti-pattern this exists to avoid.
Budget one CI review at ready, plus at most one or two more for genuine
feedback — more than that usually means the local loop got skipped (though a
clean local run is a strong signal, not a guarantee: LLM review isn't
deterministic).

## Conventions

- Python **3.14+**, `src/` layout, package `ai_assistant`.
- Public data that crosses subsystem boundaries is a pydantic model in
  `core/types.py`.
- I/O-bound methods are `async`. The system composes on one event loop.
- Read config through `core.config.Settings`; never touch `os.environ` directly.
- **Google-style docstrings** on public API (enforced by ruff).
- **Conventional Commits** (`type(scope): subject`), one logical change per
  commit, with a `Refs: ADR-NNNN` trailer when it implements a decision
  (e.g. `feat(memory): add sqlite-vec backed MemoryStore`).
