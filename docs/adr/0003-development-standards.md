# 3. Development standards and policies

- Status: Accepted
- Date: 2026-07-16

## Context

This repository is intended to be built largely by AI agents working in small,
reviewable increments. Standards that a machine can enforce are followed far more
reliably than standards that live only in prose, so we fixed the development
policies — git, typing/style, documentation, testing, dependencies, versioning —
before feature work began. `CONTRIBUTING.md` is the operational reference; this
ADR records the decisions and their rationale.

## Decision

**Git.** Trunk-based development; `main` always green; short-lived
`<area>/<slug>` branches; linear history (rebase, no merge commits); one logical
change per commit.

**Commit messages.** Conventional Commits (`type(scope): subject`) with the
subsystem as scope, enforced by a `commit-msg` hook. Commits link to decisions
via a `Refs: ADR-NNNN` git trailer, chosen over alternatives (scope encoding,
free-text body references) because trailers are the idiomatic, machine-parseable
footer mechanism in git, compose with other trailers (e.g. `Co-Authored-By`),
and are queryable with `git log --grep`.

**Typing & style.** mypy `strict`; specific, justified `# type: ignore[code]`
only. Ruff configured at "maximum": in addition to the baseline, security (`S`),
complexity (`C90`, max 10), pylint subset (`PL`), no commented-out code (`ERA`),
no relative imports (`TID`), async and datetime-safety families, and Google-style
docstrings (`D`).

**Architecture enforcement.** `import-linter` contracts mechanically enforce the
dependency rules from ADR-0002 (core imports nothing; subsystems are mutually
independent and never import orchestration/interfaces; provider SDKs confined to
`models/`). Added to the local gate.

**Documentation.** Google-style docstrings on public API; comments explain why;
decisions recorded as ADRs from `docs/adr/template.md`; `CHANGELOG.md` in Keep a
Changelog format.

**Testing.** pytest; tests mirror package paths; Protocol conformance suites;
fakes over mocks; no network/filesystem in unit tests (`integration` marker
otherwise); deterministic (injected clock/randomness). No coverage gate —
coverage tracking was deliberately omitted; test adequacy is a review concern.

**Dependencies.** uv only, lockfile committed; new runtime deps justified in the
change, foundational ones via ADR; `pip-audit` advisory; secrets via `Settings`.

**Versioning.** SemVer; single version source in `pyproject.toml`, exposed via
`importlib.metadata`.

## Consequences

- The local gate grows to five commands (format, lint, mypy, import-linter,
  pytest). With no remote CI yet (ADR-0002), running it is mandatory.
- Boundary and style violations fail fast and mechanically, which is the main
  lever for keeping agent-authored diffs correct and reviewable.
- Maximum ruff strictness will occasionally require refactoring otherwise-fine
  code (e.g. complexity limits); accepted as a deliberate trade-off.
- Omitting coverage avoids gaming a metric but places more weight on reviewers to
  judge whether tests are sufficient.
- Choosing not to auto-manage versions/changelog from commits keeps tooling
  simple now; Conventional Commits leave that door open later.
