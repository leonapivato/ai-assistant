# ai-assistant

> A model-agnostic AI operating system that orchestrates language models,
> long-term memory, and real-world tools to become a trusted, deeply
> personalized everyday assistant.

Instead of being another interface to a single model, `ai-assistant` is an
**intelligent orchestration layer** that understands the user, manages long-term
context, plans tasks, coordinates tools, and continuously learns from
interactions. The underlying language model is interchangeable — the value lies
in the personalization and orchestration surrounding it.

## Status

Pre-alpha. The project skeleton, tooling, and the `models` and `memory`
subsystems have landed. See [`VISION.md`](VISION.md) for what we are building and
why, `docs/roadmap.md` for the build sequence and status, and `docs/adr/` for
ratified decisions.

## Requirements

- Python **3.14+**
- [uv](https://docs.astral.sh/uv/) for environment and dependency management
- [just](https://github.com/casey/just) for the task runner (`just check`,
  `just review-codex`, `just ship` — see `CONTRIBUTING.md`)

## Getting started

```bash
# Create the virtual environment and install all dependencies (incl. dev tools)
uv sync

# Run the test suite
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .

# Type-check
uv run mypy

# Check architecture boundaries
uv run lint-imports
```

See `CONTRIBUTING.md` for the full development standards.

## Project layout

```bash
ai-assistant/
├── src/ai_assistant/     # application package
├── tests/                # test suite
├── pyproject.toml        # project metadata + tooling config (ruff, mypy, pytest)
├── .python-version       # pinned Python version (3.14)
└── uv.lock               # fully resolved, reproducible dependency lock
```

## Tooling

| Concern             | Tool                         |
| ------------------- | ---------------------------- |
| Packaging / env     | uv + `uv_build`              |
| Task runner         | just                         |
| Lint + format       | ruff (maximum rule set)      |
| Static typing       | mypy (strict)                |
| Architecture rules  | import-linter                |
| Testing             | pytest + pytest-asyncio      |
| Commit hygiene      | pre-commit + Conventional Commits |
