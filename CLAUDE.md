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
5. **A Protocol change is a breaking change.** Flag it in your summary. Its ADR
   is ratified and **merged as its own PR** before anything implements against
   it (ADR-0015). Your ADR number is assigned when the work is handed to you —
   don't pick one yourself.

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
interfaces/     thin adapters (cli, api, ui) — list the package for what exists
```

Request pipeline (owned by `orchestration`): intent → context assembly →
memory retrieval → planning → tool selection → permission check → execute →
learn/update memory.

## How to work (make changes reviewable)

- **Branch first, before editing anything.** You are the only agent in this
  clone, so there is nothing to claim — but never work on `main`:

  ```bash
  git fetch origin
  git switch -c <area>/<slug> origin/main
  ```

  Branch from `origin/main` (or `origin/<branch>` to stack a dependent PR), not
  from whatever is checked out.
- **Stage explicit paths, never `git add -A`/`git add .`.** Add the specific
  files your change touches, so a stray sweep can't pick up unrelated work.
- **One subsystem per change.** Scope a change to a single package plus its
  tests. Small diffs review faster and fail more clearly. The one exception is a
  Protocol triad (below): contract, conformance suite, and canonical fake are
  one unit of work, not three changes.
- **Contract first, and land the triad.** If a subsystem needs a new capability
  from another, the Protocol goes in `core/protocols.py` first — its ADR merged
  ahead of the implementation (golden rule 5). Then the *new* Protocol ships as
  a triad — Protocol + shared conformance suite + canonical fake in
  `ai_assistant.testing` — in one change, never deferred (`CONTRIBUTING.md` →
  "Adding a Protocol").
- **Park what isn't this change.** Anything you notice but shouldn't fix here —
  a deferred review finding, a debt, a follow-up — becomes a **GitHub issue**.
  There is no tracked TODO file; a file would just conflict (ADR-0015).
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

Run **all** of it, every time. CI runs the same gate on every PR and push to
`main` (ADR-0010) as the backstop, not the first line of defence. `pre-commit` runs the fast subset on commit; `just setup`
enables it once per clone.

## Review (local only, ADR-0015)

**This loop is yours to run and yours to finish. Don't ask permission for any
of it** — not to run the review, not to spend on it, not to flip the PR ready.
Judge that the change is done, then:

```bash
just review-codex adversarial   # architecture too, for a contract change
# ...triage, fix, commit, re-run until clean...
just ship                       # posts the review to the PR
gh pr ready                     # you decide when; don't wait to be told
```

Codex reviews every change — a model independent of the one that wrote it. It
reviews `HEAD` vs the base, i.e. the **committed** diff, so commit a fix before
re-running or it is invisible. Each run records `.review/<sha>-<persona>.md`;
`just ship` refuses to post unless one exists for the commit the PR head is on.

Running the review sends the diff to OpenAI. That is a normal, expected step of
finishing a change, already authorized — not a decision to escalate.

**Triage each finding — do not let the PR grow to absorb them.**

- `blocker`/`major` **and** about code in your diff → fix it now.
- Anything else → **open a GitHub issue** and leave the PR alone.

This is the rule that keeps PRs small. There is no size threshold to watch;
decide at each finding.

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
