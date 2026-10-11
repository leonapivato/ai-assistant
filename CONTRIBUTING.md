# Contributing & development standards

This is the authoritative reference for how code is written, reviewed, and
committed in this project. **The code here is written by AI agents**, dispatched
into their own clones by an operator who assigns the work and owns the merge; a
human reads, decides, and adjudicates, but does not author. Read every rule below
as addressed to an agent — where one says "you," it means the agent doing the
work. `CLAUDE.md` is the short operating agreement and points here for detail.
Decisions recorded here are ratified in
`docs/adr/0003-development-standards.md`.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
(the task runner behind every `just ...` command below) — install both before
continuing. Then, once per clone:

```bash
just setup
```

which is:

```bash
uv sync                                # create/refresh the environment
uv run pre-commit install --install-hooks   # pre-commit + commit-msg hooks
git config commit.template .gitmessage      # scaffold commit messages
```

## The gate (Definition of Done)

A change is done only when all of these pass:

```bash
uv run ruff format .        # format
uv run ruff check .         # lint (--fix to autofix)
uv run mypy                 # strict type check
uv run lint-imports         # architecture boundary check
uv run pytest               # tests
```

`just check` runs the same five, with `ruff format --check` in place of the
rewrite. `pre-commit` runs the fast subset on every commit; CI runs the full gate
on every pull request and push to `main` (`.github/workflows/gate.yml`,
ADR-0010), and that run is the full gate a branch owes (ADR-0311).

### When the full gate is owed, and when it is not (ADR-0311)

**No local whole-suite run is owed** — not before review, not before `just
ready`, not after a rebase. The full gate is CI's `gate` on the pushed head
(ADR-0311 §1). The whole suite, serial or `just test-fast`, stays available and
is never wrong.

**Before the first review invocation, run the tests for what the change
touches** on the tree to be reviewed, and have them pass (ADR-0311 §2). Which
tests is your call; no justification is owed and no reviewer may require a
particular selection. It is owed once per branch: a later review or a rebase
does not re-open it. "What it touches" includes tests that read a changed file —
`tests/scripts/` for `scripts/`, `tests/scripts/test_adr_citations_corpus.py`
for `docs/adr/`.

**Before every commit, the four static steps run and pass** (ADR-0311 §3).
`pytest` at any other point is yours to choose: the whole suite,
`just test-fast`, a selection, or none.

**The PR leaves draft only on a green `gate` on its head** (ADR-0311 §4), and
`just ready` refuses otherwise. A red push on a draft is information, not a
defect. A push after the PR is ready, such as a rebase, owes no local run and no
wait on `gate`: the merger reads that run.

`just test-fast` is the suite across cores; it deselects nothing (ADR-0179).
It runs **at most three suites per user at once** (`TEST_FAST_SLOTS` changes the
number): a fourth waits for a slot rather than contending for memory — a run
holds 3–5 GB, and four at once has crashed the WSL VM. Prefer the serial run for
a change that is order-dependent, shares state through a fixture, or is
timing-sensitive.

**Run it against a current `main`.** A green run is evidence about the tree you
ran it on, so `git fetch origin && git rebase origin/main` comes first —
otherwise you have tested a base nobody will merge. This is about *freshness*,
and ADR-0311 leaves it standing (§7). A branch that predates a check added to
`main` runs tests that cannot fail on it. The same staleness misleads Codex, which
reads the working tree for context and will report other branches' merged work
as regressions in yours — so rebase before you *invoke* a review as well. The
reviewer itself stays read-only (`docs/review/guide.md`); freshening the tree is
the branch owner's job, not the reviewer's.

## Review (pre-merge)

The gate is mechanical; it cannot judge design or the adequacy of tests. Before
merging a slice branch — **after** the gate is green — put the change through
adversarial review. Claude writes the code; **Codex reviews it**, so every change
is judged by a model independent of the one that produced it. Review runs
**locally only** (ADR-0015).

Two reviewers, defined by shared rubrics in `docs/review/`:

- **architecture** — boundaries, contract discipline, ADR adherence, and drift
  from `VISION.md`.
- **adversarial** — tries to break the code: edge cases, error paths,
  concurrency, data integrity, and test gaps.

Run each against the base branch (read-only; this **sends the diff to OpenAI**,
so it is a deliberate pre-merge step, not per-commit):

```bash
just review-codex architecture      # or: scripts/codex-review.sh architecture
just review-codex adversarial       # base-ref defaults to origin/main (fetch first)
```

**A round runs for minutes, so it can also be started and polled** — the same
round, same locks, same artifact, started detached rather than reimplemented.
Use this form when the caller cannot hold one process open that long:

```bash
just review-codex-start adversarial  # returns once the round is running
just review-codex-wait  adversarial  # 0 = artifact path + verdict; 3 = ask again
```

`-wait` blocks up to its timeout and then exits **0** with the artifact path and
the verdict, **3** for `still running` — the round is alive and nothing is lost,
so call it again — or **4** for no round in flight for `HEAD`'s tree, which is a
condition to read and act on rather than to retry. Never relaunch on a 3: a
second round is refused, and relaunching is how a paid round is thrown away.
Where `--start` cannot confirm its round, the message it prints says what to do.

A change that owes both lenses runs both in the same round —
`docs/review/guide.md` → "When a change owes both lenses".

`CODEX_REVIEW_NO_SANDBOX=1` (and `GITHUB_ACTIONS` exactly `true`) runs Codex with
no sandbox at all and no session, skipping ADR-0025 §4's read-only proof. It is
for CI-like environments where bubblewrap cannot set up its network namespace; do
not set it for an ordinary local review.

Loop: **fix, commit, re-run**. It reviews `HEAD` vs the base — the *committed*
diff, not your working tree — so an uncommitted fix is invisible to a re-run.
Each run records an artifact under `.review/`. Stop when it comes back clean or
only deliberately-waived findings remain.

### Triage every finding — do not let the PR grow to absorb them

A review finding is not automatically this PR's problem. For each one:

- **Fix it now** if it is `blocker` or `major` **and** concerns code in the
  current diff.
- **Otherwise open an issue** and leave the PR alone — a `minor`, a `nit`, or
  anything about code the PR merely sits next to.
- **Or acknowledge it, with no action warranted** — where you have **verified**
  the finding is true, can state its concrete consequence, and judge that
  consequence too small to justify any future work (ADR-0243 §7). Write the
  verdict and that one-line consequence in the PR, and the finding leaves the
  loop without a tracker row.

The trigger is the finding, not a size threshold; there is no "PR is too big"
rule to game.

Waiving a `blocker`/`major` is allowed — write the rationale in the PR or the
commit. A reviewer that disagrees with a ratified decision files an ADR
proposal; it does not block on it (authority hierarchy: `docs/review/guide.md`).
Review is advisory tooling, not a hard gate; the only required check is `gate`.

So there are five verdicts: *fix now*; *deferred to an issue*; *rejected as
false*, which asserts the finding is wrong; *waived with a rationale*, for a
`blocker`/`major` you will not fix; and *acknowledged, no action warranted*,
which asserts the finding is **right** and that nobody should ever act on it. A
finding whose consequence you cannot write down is one you have not verified,
and the last verdict is then unavailable. **It is never available at `blocker`
or `major`** (ADR-0243 §7): there the dispositions stay exactly the first, second
and fourth. It is also **prospective** — it disposes of a finding a review round
raised, and authorises no closure or relabelling sweep of issues already filed.

### Diagnose the loop at the fourth reviewed tree

As a **dispatched lane** (ADR-0243 §§1–6, §10 — an agent under a coordinator
who can brief a successor into its clone): once **four substantively reviewed
trees** have been recorded under you, and before you invoke a further round,
write a **diagnosis** as a comment on the PR. The count is **persona-agnostic** —
any lens's recorded artifact counts its tree, which is exactly what
`scripts/codex-review.sh` counts — less the figure recorded in the handoff comment
you took the lane under. A byte-identical rebase, a squash, a second lens on one
tree, an ADR-0165 ratification flip and a round that recorded no artifact each
count no tree. So it is the round number a *successful* round prints.

The diagnosis does two things:

- **Classifies** every finding still open, and every finding you fixed since your
  previous diagnosis, as exactly one of — a **new independent defect**; a
  **regression** from an earlier fix in this loop; a **specification dispute**
  (two readings of one clause, or a finding that contradicts a sentence of a
  ratified ADR); or **scope expansion**.
- **Names one next activity**, and only one: an executable probe, a smaller
  decision (splitting the PR, cutting its scope), an adjudication request to the
  coordinator written on the PR, a grounded waiver, or continued review with the
  reason stated.

**A specification dispute does not get another round.** Where the diagnosis
classifies any finding as one, the chosen activity is the adjudication request —
quote the clause, state both readings — or the grounded waiver (issue #1684).

**Nothing turns on it mechanically.** The checkpoint authorises no merge, forbids
no round, caps nothing, makes no lens terminal, and is **not** a second handoff
trigger — ADR-0138 §1's seven-rounds and churn-1.5 arms are untouched, and a
handoff is never delayed or excused by a missing diagnosis. Where your count
never reaches four, no diagnosis is owed — say that in the handoff comment.
Carry your most recent diagnosis, and the count of trees actually recorded (never
the figure a failed launch printed), into the handoff comment when one is owed
(ADR-0243 §6).

### Report the review, then mark it ready — on your own judgement

Finishing a change is one continuous motion, and it belongs to whoever is doing
the work:

```bash
just ship        # posts the recorded review(s) to the PR
just ready       # flip it out of draft — refuses on an unratified ADR or a non-green gate
```

**An agent does not ask permission for any of this** — not to run the review,
not for the OpenAI spend it incurs, not to flip the PR ready. Deciding a change
is done is the job; stopping to ask just adds a round-trip to something already
authorized. What still warrants stopping is narrow: an irreversible or
destructive action, or discovering the task itself was wrong.

**Your triage verdicts go in the PR text** — every waived `blocker`/`major` with
its rationale, every *acknowledged, no action warranted* with its one-line
consequence (ADR-0243 §8), links to the issues you filed, and any diagnosis the
checkpoint above owed. The disposition list in the ship comment is the
**reviewer's** ledger, written from whether Codex re-raised a finding, never from
what you decided about it.

`ship` refuses unless an adversarial review exists for **the content the PR head
carries**. Two paths are accepted (ADR-0027 §2):

- **The base has not moved** — the review's recorded base equals the PR's merge
  base *and* its recorded tree equals `HEAD`'s tree (ADR-0020 §3).
- **The base has moved** — the recorded base is a *proper* ancestor of the merge
  base, the reviewed patch identity is unchanged, and the base move clears the
  floor. `ship` then publishes the drift in the comment it posts.

Anchoring on content rather than the commit SHA is what makes squashing,
amending, and reverting to a reviewed tree free; changing a reviewed byte costs a
round. `ship` also refuses on a dirty tree, on `main`, and when the PR head is
behind local `HEAD`. The one exempt commit shape, the ratification flip, is
"Finishing an ADR PR"'s step 3.

**The floor** is ADR-0027 §3's, as ADR-0209 narrows it. The standing review
contracts — `docs/review/**`, `CLAUDE.md`, `CONTRIBUTING.md`,
`scripts/codex-review.sh` — bind outright (§1). `docs/adr/**`,
`src/ai_assistant/core/protocols.py` and `src/ai_assistant/core/types.py` bind
only where the moved text and the PR name each other (§§2–4), and anything
undecidable binds (§6). The PR description is part of the PR's text, so a
citation there binds like one in the diff, and `ship` reads every recorded
description with the live one (§5).

**Before pushing a rebase, ask `ship` which path applies rather than working it
out** — `just drill` (`scripts/ship.sh --drill`) runs the same acceptance rule
and posts nothing. **Rebase onto the fetched base first**; the drill refuses a
`HEAD` that does not contain it. Its report prints the base move's file set with
the test that bound or cleared each floor path, and says when it makes no floor
claim and why; report its figures, not your reconstruction of them.

**`just ready`, not bare `gh pr ready`.** It refuses to leave draft while an ADR
this PR adds or modifies still reads `- Status: Proposed`, naming the file
(ADR-0165 §5), and unless `gate` is green on the PR head, waiting up to nine
minutes on a pending run (ADR-0311 §4). `just ship` is not held for `gate`.

### Stop when the required reviews are green

**Every review the change requires coming back green is a terminal state, not a
checkpoint.** The required set follows the shape of the diff, and this is the
sentence that owns it: **adversarial alone for most changes; adversarial *and*
architecture for a contract-surface one** (ADR-0015 §1). A change is
contract-surface when it touches `core/protocols.py` or `core/types.py` — **or
when it is the ADR deciding that surface**, even though such a PR is prose only
(see "Contract ADRs land before their implementation"). Adversarial is in every
required set, which is why `ship` can demand it unconditionally. When the
required set is green, ship — do not commit again to improve wording, because
that destroys the records and starts a fresh round.

**"Green" is about the findings, not the verdict word** (ADR-0138 §3): a lens is
terminal when its latest run leaves no finding the triage rule above requires
this PR to fix. A run whose remaining findings are all deferred to issues, all
waived with a rationale on the record, or all disposed of as *acknowledged, no
action warranted* (ADR-0243 §7) is terminal. A run carrying a `blocker`/`major`
about code in your diff is not, whatever line it printed.

Each review run prints an aggregate, unasked: the round number on this branch,
the net diff size, and the **churn ratio** (cumulative lines touched ÷ net lines
in the final diff). Nothing in it blocks, and `just ship` carries it to the PR.
Several rounds in with a ratio far above 1 is the signal that the loop is
reworking itself rather than converging (ADR-0020).

### Contract ADRs land before their implementation

A **substantive contract ADR** — one that adds or changes a Protocol or a `core`
type that crosses subsystem boundaries — ships as **its own PR, ratified before
the implementation PR that depends on it** (ADR-0015 §5). Review it while it is
still `Proposed`, so a finding can still change the decision, and **run both
lenses on it**: a contract ADR is where the edge cases get decided, and a finding
there costs a paragraph where the same finding after the triad lands costs a
supersession.

Triage the findings, fold real ones into the draft, flip the ADR to `Accepted`,
merge that PR, then build against it. This is advisory like all review: the
author still owns ratification; the reviewer only surfaces blind spots.

**Trivial ADR edits** — an in-place amendment, the `Proposed` → `Accepted`
ratification flip, or recording on an ADR's status that a superseding ADR has
landed — are cheap and skip a separate review *of the edit itself*. This is about
*review cost*, and nothing else: it is not licence to rewrite a ratified decision
in place, and it does not lift any review the ADR's substance requires. A
substantive contract ADR is still reviewed while `Proposed` and ratified only
after; the trivial edit records that ratification, not the decision to grant it.
Recording a supersession presupposes the superseding ADR exists; flipping a live
decision to `Superseded` without one is an unrecorded decision change, and is not
permitted. **Amend in place only when the change alters no decision** —
reconciling an ADR with its own text or with a fact that postdates it — always as
an appended dated note that never overwrites ratified text. **Any change to what
was decided needs a new ADR that supersedes the old one:** wholly, or
**partially** with a scoped, supersession-leading status (`docs/adr/template.md`).
ADR-0001 holds the append-only rule and ADR-0070 the amend-vs-supersede test.
Being small, or cheap to review, does not bear on which side of that line a
change is.

**Spike first if you need to.** A contract ratified with no implementation
contact is how a seam that does not survive first use gets blessed. Run a
throwaway branch to learn the shape, then discard it before opening the ADR PR —
what must not happen is the implementation landing *with* the ADR that justifies
it.

**ADR numbers are assigned at dispatch,** by whoever hands out the work, not
computed by the agent doing it. If two branches still collide on a number, the
second to merge renumbers — a file rename plus its internal `ADR-NNNN`
references and `Refs:` trailers, no code change.

### Finishing an ADR PR: `Proposed` through the reviews, `Accepted` on the way out

An ADR PR ends in this order:

1. **Draft, review and revise it while it stands `Proposed`** — the state in
   which a finding can still change the decision and the ADR's text is
   *corrected* rather than annotated (ADR-0070 §1 protects only **ratified**
   text; ADR-0095 §7). Run the whole required set here ("Stop when the required
   reviews are green").
2. **Flip `Proposed` → `Accepted` only once that whole set is green on one
   tree**, and make the flip with **`just adr-ratify`** — a permitted in-place
   header edit (ADR-0070 §1).
3. **Then re-run the required reviews on the flipped tree — unless the flip
   commit is the one exempt shape** (ADR-0165 §2): **one ADR file, the header's
   single `- Status: Proposed` becoming `- Status: Accepted`, and no other byte —
   the `- Date:` line included.** `just adr-ratify` makes exactly that commit;
   `ship` recognises it, judges coverage against `HEAD`'s parent, and says so in
   its comment (ADR-0165 §§3–4). Anything larger — a ratification note, an
   amendment record, a restamped date, a typo fix, a second ADR — costs the
   round; write the note and pay, or keep the flip bare. The flip is the
   ratifying act, not a commit "to improve", so "Stop when the required reviews
   are green" does not forbid it. **A finding on that round returns the ADR to
   `Proposed` and re-enters step 1** — before merge only, as ADR-0070 §1's
   correction of a `Status` line (ADR-0127 §3) — and the corrected decision
   earns the whole set green before it is flipped a second time, so such an ADR
  records itself as ratified *on its second flip*.
4. **`just ship`, then `just ready`, then merge** ("Report the review, then mark
   it ready"). `just ready` refuses while any ADR this PR adds or modifies still
   reads `- Status: Proposed` (ADR-0165 §5).
5. **Nothing implements against the ADR until that merge** (ADR-0015 §5, golden
   rule 5).

An ADR recording its own ratification owes a line naming the set it ran and the
outcome it got, plus a pointer here — not a paragraph reasoning the sequencing
out from first principles.

## The dispatcher

The **dispatcher** is whoever hands work to agents (ADR-0015 §§2 and 5): it
assigns ADR numbers, prevents lane collisions, places each agent in its own
clone, and decides merge order. The `dispatch-agents` skill carries the role.

Two things follow for **you, the agent**. Your lane's boundaries and your ADR
number come from your brief, not from your own reading of the repo — where the
brief conflicts with an issue the brief is newer, and where it conflicts with a
ratified ADR, stop and say so rather than choosing. And the report you send back
is evidence: say what you actually verified and at which commit.

## The tracker

GitHub issues and native GitHub milestones are the delivery tracker. Keep no
in-repo coordination ledger (ADR-0015). Milestones and their linked acceptance
issues hold delivery scope (`CLAUDE.md` → "Delivery planning", #2518); how scope
is taken, accepted, retired and swept out of `docs/roadmap.md` is the dispatcher
skills' (`pre-dispatch-survey`, `qa-milestone`, `status-report`).

**Track labels — at most one per issue.** A track identifies an area of work,
not a milestone board or a schedule. The live set is the tracker's own; read it
whole with

```bash
gh api --paginate repos/{owner}/{repo}/labels --jq '.[].name'
```

rather than with `gh label list`, whose `--limit` defaults to 30. An issue that
would carry two tracks is a finding in a subsystem another track has a lane open
in: file it to the track that holds that subsystem, not to both
(`docs/roadmap.md` → "Concurrency").

**The backlog is a severity family, not a track.** An issue triaged onto *no*
program of work carries exactly one of `backlog:blocker`, `backlog:major`,
`backlog:minor` or `backlog:unknown`, *instead of* a `track:*` label and never
alongside one (#1232 is the conventions record).

- The three named severities are **`docs/review/guide.md`'s words** — `blocker`
  (must fix before merge), `major` (should fix), `minor` (worth noting) — read
  against the issue rather than against a review finding.
- **`unknown` is "not yet sized"**, the honest default for an issue filed in
  passing, re-sized lazily when the issue is next touched.
- **`backlog:blocker` makes selection urgent, not implicit.** Surface it for the
  next work-selection decision; it does not create a batch, revive a retired plan
  or bypass the owner's milestone/scope decision.

**Kind labels**, orthogonal to the track: `ruling` — needs the owner, and the
return brief is `gh issue list -l ruling`, whole; `batch` — a dispatch record;
`qa` — a QA-run record (`.claude/skills/qa-milestone`). Add another label on
evidence, not in advance.

**Label lazily, as you touch an issue** — no sweep is owed — except `ruling`,
which is applied the moment the issue is filed.

## Git & commits

- **Trunk-based.** `main` is always green. Do each unit of work on a
  short-lived branch named `<area>/<slug>` (e.g. `models/provider-protocol`).
- **Linear history.** Rebase onto `main`; no merge commits. Condense a branch
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

`main` is protected and integration happens through pull requests — not local
merges (ADR-0010) — so every merge carries a green `gate` on the merged content
and a linear history where each commit keeps its `Refs:` trailer.

- **Never push to `main`.** Push your `<area>/<slug>` branch and open a PR.
- **Open a draft PR early — always.** As soon as you have a branch and a first
  commit, open it as a **draft**, so CI gates every push and the dispatcher can
  see your direction (and any contract change) while redirecting is still cheap.
  Mark it ready with `just ready` when the change is complete — your call, made
  without asking ("Report the review, then mark it ready"). The transition is the
  signal to the dispatcher that the lane is done and ready to be verified and
  merged.
- **CI gates the PR.** The `gate` workflow runs the full gate on every PR and
  push; a PR cannot merge while it is red.
- **`gate` is the only required check; no approving review is required**
  (ADR-0167 §4). The Codex review `just ship` reports is the entire independent
  judgement on the change, and the dispatcher's verification the entire human
  one. When the administrator bypass may be used is ADR-0167 §§2–3's.
- **Rebase and merge.** Rebase your branch onto `main` and merge via GitHub's
  *Rebase and merge* so linear history holds and each commit keeps its
  `Refs: ADR-NNNN` trailer. Delete the branch after merge.
- **Low-collision by design.** Work is split across low-overlap sections, so
  rebase conflicts should be rare; whoever merges second resolves them.

### Coordinating parallel work

**One clone per agent** (ADR-0015). An agent is dispatched by hand into a
pre-existing local clone and may assume it is the only worker there; nothing in
the repo tracks who is working where. Each unit of work starts on a fresh branch
from `origin/main` (`CLAUDE.md` → "How to work"), or from `origin/<other-branch>`
to stack a dependent PR — fetch first. The `no-commit-to-branch` pre-commit hook
refuses commits to `main`.

`core/` is a shared surface the gate cannot referee — a collision there is a
valid diff that passes every check and only surfaces as a conflict on the second
rebase:

- **Changing `core/` is the one high-collision edit — flag it loudly.** A
  Protocol change is breaking (golden rule 5), and the contract lands as its own
  ratified ADR *and its own PR*, ahead of anything built on it (see "Contract
  ADRs land before their implementation").
- **Two agents needing `core/` at once are not independent.** The second stacks
  on the first once the first's contract PR has merged. Whoever dispatches
  decides this; an agent that discovers it mid-task should say so rather than
  racing.

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

**These four are the headline, not the register.** The register is
`pyproject.toml`'s `[[tool.importlinter.contracts]]`, where each contract carries
its reasoning in place — **check a change against `uv run lint-imports`, never
against this list** (ADR-0019).

Subsystems communicate only through the Protocols in `core/protocols.py`. A
Protocol change is a breaking change: call it out and add an ADR first.

### Adding a Protocol: land the triad together

A Protocol on its own is an unenforced promise. The required unit of work for a
**new** Protocol is a triad, landing in the same change:

1. **The Protocol** in `core/protocols.py`, plus any types it exchanges in
   `core/types.py`.
2. **A shared conformance suite** — the abstract `…Contract` base described
   under [Testing](#testing), encoding what every implementation must do.
3. **A canonical fake** in `ai_assistant.testing`, *plus* the concrete
   `Test…Contract` subclass that runs it through the suite. The abstract base
   collects nothing on its own — without that subclass the fake is unverified,
   however many files exist. See `tests/memory/test_fake_store.py`.

A triad spans `core/`, `ai_assistant/testing/`, and `tests/`, and that is
deliberate: it is **one** unit of work, the standing exception to "one subsystem
per change" (`CLAUDE.md`). Splitting it across PRs is the failure mode this rule
exists to prevent. On its own it stays a small diff, because it is then a
contract and its guardrails with no *production* implementation attached (the
canonical fake is an implementation, but a test-only one).

**It does not always travel alone.** Where a slice was cut at this contract seam
— because its implementation would otherwise put new machinery into two
subsystems — the triad rides with its **primary production implementation**, the
consumer whose demands shape the contract, as one lane and one PR (ADR-0137 §2).
That is a widening of the same exception, not a second one: any other
cross-subsystem pairing stays outside it, the triad itself is still never split
(ADR-0137 §3), the sequence below is unchanged, and every further consumer group
is a follow-on lane briefed against the merged contract (ADR-0137 §4).

Not "Protocol now, tests when someone implements it": a fake with no suite drifts
from the contract silently; a suite with no fake leaves every consumer
hand-rolling a private mock.

The triad is what a Protocol *change* is measured against too — extend the suite
in the same change, so the new obligation is enforced rather than assumed.

**The triad itself is mechanically enforced.**
`tests/core/test_protocol_triad.py` maps every Protocol in `core/protocols.py`
to its suite, its canonical fake, and a `Test…Contract` subclass whose contract
tests pytest actually *ran and passed*. Add a Protocol without its triad and the
gate goes red, naming what is missing.

Because the check wants evidence that the contract *ran*, a contract test that
skips itself does not count. Where an obligation genuinely does not apply to every
implementation, the **suite** says so by marking that test
`@pytest.mark.optional_obligation`; only then may an implementation's run skip
it. See `ContextProviderContract.test_each_assembly_recomputes_from_the_clock`.

What the check enforces is that the three artifacts exist and run — **not that
a suite covers every method of its Protocol.** Keeping the suite abreast of the
contract is a review concern, like the adequacy of any other test (ADR-0003).

This does not loosen contract-first. The sequence is two stages, not one:

- **Stage 1 — ratify, in its own PR.** The ADR proposing the Protocol goes
  through architecture review, is ratified (golden rule 5), and **merges** —
  a substantive contract ADR is its own PR (ADR-0015 §5). Nothing implements
  against the new shape yet, the canonical fake included: a fake is an
  implementation, bound by that rule like any other.
- **Stage 2 — land the triad.** Once the contract has merged, all three
  artifacts ship together in the implementation PR.

So "contract-first" governs the ADR *preceding* the triad, not the ordering of
files inside it.

## Documentation

- **Google-style docstrings**, enforced by ruff (`D`, `convention = "google"`).
- Required on public modules, classes, and functions/methods; optional on
  private helpers.
- Do **not** repeat types in docstrings — they live in annotations.
- Comments explain **why**, not what. No commented-out code.
- Record every non-obvious decision as an ADR (`docs/adr/`, see the template).
- A design that is not yet decided is a **proposal**: a draft PR carrying one
  file under `docs/proposals/`, which becomes its ADR on acceptance (below).

### A proposal is a draft PR that becomes its ADR

A **proposal** is a design under discussion before the owner has decided it. It
is one Markdown file under `docs/proposals/` on a `proposal/<slug>` branch,
opened as a **draft pull request**, and it never merges as a proposal.
`docs/proposals/README.md` is the working guide — what the file carries, how
it is discussed, why it is a PR, and the three ways it ends.

- **The wiki is the baseline, not the venue.** The wiki describes the system's
  design at a high level and is not wired into dispatch; ADRs bind the code, and
  a page never amends one. A proposal cites the wiki pages and ADR clauses it
  would alter and does not live among them. Nothing under `docs/proposals/` on
  `main` is a proposal.
- **The pull request is the medium.** The file is rewritten in place and
  pushed; review threads on the diff are the discussion. An issue, where one
  exists, holds the ruling and the link.
- **An open proposal authorizes nothing.** It claims no scope, blocks no lane,
  amends no ADR, and no implementation cites it.
- **Accepted means converted, on the same branch.** The file moves to
  `docs/adr/NNNN-<title>.md` and is rewritten into the ADR form with `- Status:
  Proposed`; the number is assigned at conversion (`CLAUDE.md` → golden rule
  5). From that commit the branch is an ADR PR and "Finishing an ADR PR"
  applies unchanged. The proposal file does not survive the conversion.
- **Declined or parked means closed unmerged**, with the ruling in the closing
  comment and, for a parked one, the issue that holds it.
- **Nothing the gate owes arrives while it is a draft proposal.** No review is
  invoked on it and it is never flipped out of draft as a proposal, so no review
  round and no ADR-0311 §2 run is owed until conversion.

### Cite in form, and mark what binds

ADR-0088 and ADR-0089 govern ADR *text*, and both are **forward-only**: an
older ADR that does not follow them is a record, not a defect to fix.
`docs/adr/template.md` carries the authoring forms.

- **Cite in one of ADR-0088 §1's three forms** — a decision, a code, or a tracker
  citation; §2 says what each must resolve to. **A code citation carries no line
  number** (§5): name the enclosing symbol, and quote the line where the position
  matters — a line number stays well-formed after the edit that invalidates it.
- **Mark every normative clause** (ADR-0089 §2). A clause is normative when **a
  reader could disobey it**; a measurement, an argument, a worked example or a
  classification is not, however load-bearing (§1). **In a marked ADR the marked
  clauses are the whole of what it obligates** (§3): prose beside a mark binds
  nothing, so a clause carries its own scope, conditions and exceptions. An ADR
  with no well-formed mark is unmarked and binds as prose (§4). **Reviewing a
  marked ADR, check that every obligation it intends sits inside a mark** —
  nothing mechanical finds an under-marked ADR.
- **Name one ruling by its clause identifier**, `ADR-NNNN §S:k` — the *k*-th
  marked clause within section *S* (ADR-0277 §1); the template defines *S*,
  ranges and shared prefixes. It is an additional form of the decision citation
  and replaces none, and no lane rewrites an existing citation into it. **Do not
  count by hand** — `just adr-rules NNNN` prints an ADR's `Status` line and every
  marked clause under its identifier, and says nothing about whether a clause is
  still in force; that reading stays with the `Status` line (ADR-0277 §4). An
  identifier is stable once its ADR is `Accepted`.
- **Two authoring rules keep the record from drifting** (ADR-0277 §3). A header
  note written onto an earlier ADR does not state the writing ADR's status — it
  may say the change takes effect on that ADR's ratification, and nothing
  further. A quotation of another ADR's marked clause carries no `**Normative.**`
  token: fence it, or block-quote it without the token.

`tests/scripts/test_adr_citations_corpus.py` runs ADR-0088 §6's Tier 1 in the
gate and `just citations` prints the whole report; which numbers are exempt gaps
is ADR-0090 §1's. Two checks are ADR-0278's: a marked clause equal to another
ADR's fails where it stands outside its own ADR's `## Decision` section and is no
finding inside it (§1), and a header note saying an ADR "remains Proposed" after
it was ratified is reported until a later dated item of the same header writes
`ADR-NNNN was ratified` (§2). The check is narrower than the rule: a marked
quotation inside a Decision section passes it, and the second authoring rule
above still forbids it (§3).

### No state claims in living documents

Ratified in ADR-0019, which holds the evidence and the rejected alternative.

A **living document** is one that is undated and revised in place, and read as
currently authoritative — `CONTRIBUTING.md`, `CLAUDE.md`, `README.md`,
`VISION.md`, the rubrics in `docs/review/`. They carry **rules and the reasoning
behind them, never snapshots.** If a fact about the repository matters, either a
check asserts it or a dated ADR records it.

- **A snapshot is anything measured or observed rather than decided** — a test
  count, a wall-clock timing, a "currently"/"today"/"so far", a claim that some
  piece of work is finished. The test is where the sentence came from: an
  argument, or a measurement. Prefer the durable form — name the rule, and point
  at whatever actually holds the state.
- **A fact a check owns is not a snapshot.** Say which check owns it.
- **A decision does not become a snapshot by describing a situation.** "You are
  the only agent in this clone" is a premise these documents *set* (ADR-0015).
- **ADRs are exempt**: an ADR is dated, so "at the time of writing, X" belongs
  there. Do not scrub snapshots out of `docs/adr/`.

Enforced by reviewers reading the diff; there is deliberately no linter for it
(ADR-0019 §5).

## Testing

- `pytest`; tests mirror the package path (`tests/<pkg>/test_*.py`); name tests
  `test_<unit>_<behavior>`; structure them Arrange–Act–Assert.
- **Protocol conformance suites:** each Protocol gets a shared test suite that
  every implementation must pass — an abstract `…Contract` base (not
  `Test`-prefixed) with a subject fixture overridden per implementation. See
  `tests/memory/memory_store_contract.py` and
  `tests/learning/feedback_processor_contract.py`. For a *new* Protocol the
  suite is not optional and not deferrable — it ships with the contract and its
  fake, as [one triad](#adding-a-protocol-land-the-triad-together).
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
- **There is no changelog** (ADR-0067). What a change was and why is carried by
  its commit message, by its ADR where it records a decision, and by its PR.
  Release notes, when there is a release to write them for, are assembled from
  that record rather than maintained continuously between releases.
