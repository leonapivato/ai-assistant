# TODO — tracked debts and follow-ups

Cross-cutting work that is deliberately deferred, not forgotten. Each item is a
real gap surfaced during review; none blocks current functionality. Prefer
turning a substantial item into an ADR or a scoped slice when picked up.

## 1. Backfill shared Protocol conformance suites

**What:** `CONTRIBUTING.md` ("Protocol conformance suites") requires *each*
Protocol to have a shared test suite that every implementation must pass. Done
for `FeedbackProcessor` and `MemoryStore`; the rest still assert
`isinstance(impl, Protocol)` plus implementation-specific tests, which only
proves an attribute exists.

**Missing suites for:** `Embedder`, `MemoryPolicy`, `ContextProvider`.
(`MemoryStore` done — `tests/memory/memory_store_contract.py`, run against
`InMemoryMemoryStore`, `SqliteMemoryStore`, and the shared `FakeMemoryStore`.
`ModelProvider` done — `tests/models/model_provider_contract.py`, run against
`PydanticAIProvider` and the shared `FakeModelProvider`.)

**Pattern to follow:** `tests/memory/memory_store_contract.py` or
`tests/learning/feedback_processor_contract.py` — an abstract `…Contract` base
class (not `Test`-prefixed, so pytest does not collect it directly) with a
subject fixture overridden by a `Test…`-prefixed subclass per implementation.

**Origin:** adversarial review of the `learning` slice (ADR-0009).

## 2. Assertion-supersedes-conflict policy refinement

**What:** `DefaultMemoryPolicy` returns `ACCEPT` for a `USER_ASSERTED` proposal
*before* its merge rule (ADR-0005 §3). So an explicit correction that conflicts
with an existing **inferred** memory is stored as a *new* record rather than
superseding the stale one — the old (now-wrong) memory lingers.

**Impact:** the first learning loop ("learn a new preference, reuse it") is
unaffected, but "a correction supersedes a wrong belief" leaves a stale memory
behind.

**Direction:** refine the policy so a user assertion supersedes (merges over /
retires) a conflicting inference. This is a **memory-policy** decision — a
follow-up to ADR-0005, likely its own ADR.

**Origin:** recorded in ADR-0009 §5 ("Known interaction with the policy").

## 3. Canonical shared test doubles for every Protocol

**What:** canonical shared fakes so a subsystem depends on a *shared* stand-in
for its collaborators, never reaching into their internals or hand-rolling a
private mock that drifts from the contract. The home now exists —
`ai_assistant.testing` (test-only, enforced by `lint-imports`) — with the first
fake in place.

**Done:** `FakeMemoryStore` (`ai_assistant/testing/memory.py`) and
`FakeModelProvider` (`ai_assistant/testing/models.py`), each passing its
Protocol's shared conformance suite (item 1).

**Still needed:** `FakeContextProvider`, `FakeEmbedder`, `FakeMemoryPolicy` —
each paired with, and validated by, its Protocol's conformance suite so the fake
cannot drift. `orchestration` will need most of these; add them as it is built
(or ahead of it).

**Origin:** review of AI-agent scalability — the biggest cross-subsystem gap for
parallel development.

## 4. Single generated project-status view — DONE

**Done:** `just status` (`scripts/project_status.py`) derives packages
(built/stub), Protocols, and ADRs (status + numbering gaps) fresh from the repo
on each run, so it cannot go stale. It replaces stitching together the source
tree, `core/protocols.py`, and every ADR header. Human-declared state (lane
owners, ADR numbers in flight) intentionally stays in `WORKING.md`, which the
view points to rather than re-parsing.

**Origin:** review of AI-agent scalability — onboarding-context cost.

## 5. Formalize the "new Protocol" ritual in CONTRIBUTING

**What:** adding a Protocol today is documented as "edit `protocols.py` + write an
ADR." The machinery that keeps implementations honest — a conformance suite
(item 1) and a canonical fake (item 3) — is created *later, as debt* rather than
*with* the contract. That is precisely how items 1 and 3 became TODOs.

**Direction:** make the required unit of work for a new Protocol a *triad* —
Protocol definition + canonical fake + shared conformance suite — landing
together, and state this in `CONTRIBUTING.md` (Architecture boundaries / Testing).
Prevents the backfill debt from recurring for the remaining subsystems.

**Origin:** review of AI-agent scalability — process fix that closes the loop on
items 1 and 3.

## 6. `just setup` installs only the `commit-msg` hook, silently disabling the rest

**What:** `justfile` (`setup`) and `CONTRIBUTING.md` both run

```bash
uv run pre-commit install --install-hooks --hook-type commit-msg
```

`--hook-type` *replaces* the default rather than adding to it, so only
`.git/hooks/commit-msg` is written — there is no `.git/hooks/pre-commit`.
Everything in `.pre-commit-config.yaml` at the default `pre-commit` stage
(ruff check, ruff format, mypy, import-linter, and the file-hygiene hooks) is
therefore **never run on commit**. Only `conventional-pre-commit`, which
declares `stages: [commit-msg]`, actually fires.

**Impact:** the failure is silent and reads like success — committing prints
`ruff check ... (no files to check) Skipped` and `mypy (strict) ... Skipped`,
which looks like "nothing to do" rather than "not installed". A contributor
following `CONTRIBUTING.md` verbatim gets no local pre-commit safety net and
only discovers a lint/type failure from the remote `gate` workflow. Not
functionality-breaking — the full gate still catches everything — but it moves
feedback from seconds to a CI round-trip, and it undercuts the claim in
`CLAUDE.md` that "`pre-commit` runs the fast subset on commit".

**Direction: delete the flag — do not add a second one.**
`.pre-commit-config.yaml` line 4 *already* declares

```yaml
default_install_hook_types: [pre-commit, commit-msg]
```

which is exactly right, and the explicit `--hook-type commit-msg` is what
overrides it. So the config is not missing anything; the install command is
fighting it. Drop the flag:

```bash
uv run pre-commit install --install-hooks
```

Verified: that bare command installs **both** `.git/hooks/pre-commit` and
`.git/hooks/commit-msg`. Passing both hook types explicitly instead would also
work, but it re-states in two more places what the config already says and
leaves the same drift to happen again.

**Four** places carry the broken command and all four need the edit:

- `justfile:52` (`setup`)
- `CONTRIBUTING.md:12`
- `CLAUDE.md:81`
- `.pre-commit-config.yaml:1` — the header comment of the very file whose
  `default_install_hook_types` the command overrides

Anyone who already ran the old command must re-run it; the missing hook is not
repaired by `uv sync`.

**Origin:** found during environment setup — `.git/hooks/` contains only
`commit-msg`, and every commit on `models/error-taxonomy` shows the
`pre-commit`-stage hooks skipped.
