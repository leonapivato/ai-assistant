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

Each clone owns its own `.git/hooks` and its own `.venv`, so the hook path
`pre-commit install` bakes in stays valid for the life of the clone. (This was
not true under the linked-worktree model ADR-0015 removed, where one shared
hooks directory pointed at whichever worktree installed last.)

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
every pull request and push to `main` (`.github/workflows/gate.yml`, ADR-0010).
CI is the backstop — but run the gate locally before you push. A red PR is a
wasted round-trip, not a first line of defence.

**Run the whole suite, always.** Selecting "the tests that matter for this
change" trades a shorter wait for a judgment call whose failure mode — a
cross-subsystem regression `lint-imports` cannot see — surfaces in CI after you
have moved on. Revisit if `pytest` ever crosses a couple of minutes.

**Run it against a current `main`.** A green gate is evidence about the tree you
ran it on, so `git fetch origin && git rebase origin/main` comes first —
otherwise you have tested a base nobody will merge. This is not the same
judgment call as the one above: running everything is about *breadth*, and this
is about *freshness*. A branch that predates a check added to `main` runs a full
suite that cannot fail on it, which is how a change has been reported green
while CI had it red. The same staleness misleads Codex, which reads the working
tree for context and will report other branches' merged work as regressions in
yours — so rebase before you *invoke* a review as well. The reviewer itself
stays read-only (`docs/review/guide.md`); freshening the tree is the branch
owner's job, not the reviewer's.

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
just review-codex adversarial       # base-ref defaults to origin/main (fetch first)
```

Review runs **locally only** (ADR-0015). It used to also run in CI and post its
findings as a PR comment; that produced far more rounds than it produced value —
PR #17 drew 20 hosted reviews across 23 commits — so the hosted path is gone.
The reviewer is unchanged: Codex still judges every change, independently of the
model that wrote it.

Each run records itself to
`.review/<loop_id-or-noloop>-<persona>-<base_sha>-<tree>.md`, named by the
anchor `ship` selects it by rather than by the commit it was filed under
(ADR-0027 §6). The first field is the ADR-0025 loop identity where the run has
one. The bypass path — `CODEX_REVIEW_NO_SANDBOX=1`, or `GITHUB_ACTIONS` exactly
`true` — keeps no session and so has no loop identity; there the sentinel
`noloop` stands in, so the field is never empty and the segments never collapse.

Loop: **fix, commit, re-run**. It reviews `HEAD` vs the base — the *committed*
diff, not your working tree — so an uncommitted fix is invisible to a re-run.
Stop when it comes back clean or only deliberately-waived findings remain.

### Triage every finding — do not let the PR grow to absorb them

A review finding is not automatically this PR's problem. For each one:

- **Fix it now** if it is `blocker` or `major` **and** concerns code in the
  current diff.
- **Otherwise open an issue** and leave the PR alone — a `minor`, a `nit`, or
  anything about code the PR merely sits next to.

The trigger is the finding, not a size threshold. The PRs that got out of hand
did not start large; they grew under review, one finding-fix commit at a time.
Deciding at the finding is what stops that, and it is why there is no "PR is too
big" rule to game.

Waiving a `blocker`/`major` is allowed — write the rationale in the PR or the
commit. A reviewer that disagrees with a ratified decision files an ADR
proposal; it does not block on it (authority hierarchy: `docs/review/guide.md`).
Review is advisory tooling, not a hard gate; the only required check is `gate`.

### Report the review, then mark it ready — on your own judgement

Finishing a change is one continuous motion, and it belongs to whoever is doing
the work:

```bash
just ship        # posts the recorded review(s) to the PR
gh pr ready      # flip it out of draft
```

**An agent does not ask permission for any of this** — not to run the review,
not for the OpenAI spend it incurs, not to flip the PR ready. Deciding a change
is done is the job; stopping to ask just adds a round-trip to something already
authorized. Say what you concluded and why in the PR, and let the review and the
gate speak for the rest.

What still warrants stopping is unchanged and narrow: an irreversible or
destructive action, or discovering the task itself was wrong. "Is this ready?"
is not on that list.

`ship` refuses unless an adversarial review exists for **the content the PR head
carries**, so the record cannot be a review of different code. Two paths are
accepted (ADR-0027 §2):

- **The base has not moved** — the review's recorded base equals the PR's merge
  base *and* its recorded tree equals `HEAD`'s tree. This is ADR-0020 §3 exactly
  as written, and it is unchanged.
- **The base has moved** — the recorded base is a *proper* ancestor of the merge
  base, the reviewed patch identity is unchanged, and the base move clears the
  floor below. `ship` then publishes the drift — both bases and the whole file
  set the move touched — in the comment it posts.

It also refuses on a dirty tree, on `main`, and when the PR head is behind local
`HEAD`.

**Before pushing a rebase, ask `ship` which path applies rather than working it
out** — `scripts/ship.sh --drill` (`just drill`) runs this same acceptance rule
and posts nothing, so a round that is owed is discovered while it is still cheap.
(It fetches the PR's base, as `ship` does; what it does not do is write to
GitHub.) It reports the inputs it judged, not just a verdict: the base move's
file set with floor paths marked, and where it made no floor claim, which of its
three reasons applies — none of which is a clear. **Rebase first**: on a `HEAD`
that does not contain the fetched tip it refuses, rather than testing the floor
over the range to the *old* merge base — a different base move from the one
being asked about, and where nothing else has moved, an empty one (issue #751).

**A base move costs a review round when it lands in ADR-0027 §3's floor:**
`src/ai_assistant/core/protocols.py` and `src/ai_assistant/core/types.py` — the
contract surface — plus `docs/review/**`, `CLAUDE.md`, `CONTRIBUTING.md`,
`scripts/codex-review.sh` and `docs/adr/**`, the standing contracts the review
was conducted under. The floor is read rename-aware on **both** endpoints: a
floor path is breached when it appears as the source or the destination of a
rename, and when it is deleted. Clearing the floor is necessary but not
sufficient — the moved-base path above carries the rest of the conditions, and
a base move that edits the reviewed hunks costs its round whatever the floor
says. Merging to `main`, meanwhile, does not move a PR's merge base at all;
rebasing onto it does.

Anchoring on content rather than the commit SHA is what makes squashing,
amending, and reverting free: a commit that changes no reviewed byte does not
cost a review round. Content the review did not read still fails mechanically —
a scope cut is a real content change, so it genuinely re-reviews. On the
moved-base path, so does a diverged history, a patch identity with nothing to
hash (a rename-only or mode-only entry), or a drift record too large to publish
whole: each makes that path unavailable, leaving the unmoved-base test to judge
the artifact, which a moved base fails.

### Stop when the required reviews are green

**Every review the change requires coming back green is a terminal state, not a
checkpoint.** The required set follows the shape of the diff, and this is the
sentence that owns it: **adversarial alone for most changes; adversarial *and*
architecture for a contract-surface one** (ADR-0015 §1). A change is
contract-surface when it touches `core/protocols.py` or `core/types.py` — **or
when it is the ADR deciding that surface**, even though such a PR is prose only
(see "Contract ADRs land before their implementation"). Adversarial is in every
required set, which is why `ship` can demand it unconditionally. When the
required set is green, ship —
do not commit again to improve wording, because that destroys the records and
starts a fresh round.

Each review run prints an aggregate, unasked: the round number on this branch,
the net diff size, and the **churn ratio** (cumulative lines touched ÷ net lines
in the final diff). A ratio far above 1 means most of the work has been rework.
Nothing in it blocks — a cap would forbid rounds that produce findings worth
having — but it is on the record, and `just ship` carries it to the PR so the
reviewer at merge sees the same numbers you did.

A long review loop is locally defensible at every step: a late round looks like
an early one from inside, and the author cannot read the signal they are
emitting.
That is why the aggregate is printed rather than left to judgement — the view
that ends such a loop has historically been held from outside it. Several rounds
in with a high churn ratio is the signal that the loop is reworking itself rather
than converging. ADR-0020 records the cases this rule comes from.

This is deliberately not a pre-push hook: review is a pre-merge step, and gating
every push would force a full Codex run per WIP commit — the per-push cost
pattern ADR-0015 exists to remove.

A pasted review is self-attested where the CI-posted one was not. The content
anchor covers the failure that actually happens (reviewing stale content); it is
not tamper-proof and does not try to be.

### Contract ADRs land before their implementation

The architecture reviewer's natural subject is a *decision*, not just a diff. A
**substantive contract ADR** — one that adds or changes a Protocol or a `core`
type that crosses subsystem boundaries — ships as **its own PR, ratified before
the implementation PR that depends on it** (ADR-0015 §5). Review it while it is
still `Proposed`, so a finding can still change the decision:

```bash
just review-codex architecture      # on the branch holding the drafted ADR
just review-codex adversarial       # both — see below
```

**Run both on an ADR PR.** Architecture is the review that earns its keep on a
decision; adversarial is required as well, and not only because `ship` enforces
it (above). A contract ADR is where the edge cases get decided — what happens on
conflict, on cancellation, on an empty or oversized input — and those are
answerable from the prose, before an implementation has committed to an answer.
A finding there costs a paragraph; the same finding after the triad lands costs a
supersession.

Triage the findings, fold real ones into the draft, flip the ADR to `Accepted`,
merge that PR, then build against it. This is advisory like all review: the
author still owns ratification; the reviewer only surfaces blind spots (a missed
alternative, inconsistency with a prior ADR, a seam that will not extend).

**Trivial ADR edits** — an in-place amendment, the `Proposed` → `Accepted`
ratification flip, or recording on an ADR's status that a superseding ADR has
landed — are cheap and skip a separate review *of the edit itself*, not worth the
round-trip. This is about *review cost*, and nothing else: it is not licence to
rewrite a ratified decision in place, and it does not lift any review the ADR's
substance requires. A substantive contract ADR is still reviewed while `Proposed`
and ratified only after (see "Contract ADRs land before their implementation",
ADR-0015 §5); the trivial edit is recording that ratification, not the decision
to grant it. Recording a supersession likewise presupposes the superseding ADR
exists; flipping a live decision to `Superseded` without one is not a status
change but an unrecorded decision change, and is not permitted.
ADR-0070 fixes the line: **amend in place only when the change alters no
decision** — reconciling an ADR with its own text or with a fact that postdates
it — always as an appended dated note that never overwrites ratified text.
**Any change to what was decided needs a new ADR that supersedes the old one:**
wholly, or **partially** with a scoped, supersession-leading status
(`docs/adr/template.md`). ADR-0001 holds the append-only rule; ADR-0070 holds
the amend-vs-supersede test and the partial-supersession form. Being small, or
cheap to review, does not bear on which side of that line a change is.

**Spike first if you need to.** A contract ratified with no implementation
contact is how a seam that does not survive first use gets blessed. Run a
throwaway branch to learn the shape, then discard it before opening the ADR PR —
what must not happen is the implementation landing *with* the ADR that justifies
it.

**ADR numbers are assigned at dispatch,** by whoever hands out the work, not
computed by the agent doing it. That removes the shared-counter race the old
in-flight ledger tried and failed to arbitrate. If two branches still collide on
a number, the second to merge renumbers — a file rename plus its internal
`ADR-NNNN` references and `Refs:` trailers, no code change.

### Finishing an ADR PR: `Proposed` through the reviews, `Accepted` on the way out

An ADR PR ends in a fixed order, and each step is what makes the next one mean
something. It is written down once here so a lane does not re-derive it:

1. **Draft, review and revise it while it stands `Proposed`.** That is the state
   in which a finding can still change the decision, and in which the ADR's own
   text is *corrected* rather than annotated — ADR-0070 §1's append-only
   protection is scoped by its own words to **ratified** decision text, and
   ADR-0095 §7 works that adjudication through ("A `Proposed` ADR is by
   definition still in the state where review changes its text"). Run the whole
   required set here: adversarial for most ADRs, adversarial *and* architecture
   for one deciding a contract surface ("Stop when the required reviews are
   green").
2. **Flip `Proposed` → `Accepted` only once that whole set is green on one
   tree.** Two lenses that came back clean on trees the ADR has since moved off
   have not agreed with each other about the thing being ratified. Ratifying
   ahead of them ratifies a decision the reviewer was still entitled to change.
   The flip itself is a permitted in-place header edit (ADR-0070 §1).
3. **Then re-run the required reviews on the flipped tree.** This is not a
   judgement call and not a symptom of anything: the flip edits a reviewed byte,
   so the recorded tree no longer equals `HEAD`'s and the unmoved-base path
   refuses — "(a) — ADR-0020 §3 exactly as written. The tree is the whole test
   here.", in `scripts/ship.sh`'s artifact-selection loop. The moved-base path
   does not rescue it either, since the flip changes the reviewed patch identity
   as well. "Trivial ADR edits" above says the flip earns no review *of the edit
   itself*, and it does not — nothing in the re-run triages a status line. What
   the re-run buys is **coverage**, which is mechanical, and no exemption in this
   document lifts it. The round is cheap by construction: the flipped tree
   differs from the one already judged by a status line.

   **This does not turn a green set into a checkpoint.** What "Stop when the
   required reviews are green" forbids is committing *again to improve* content a
   reviewer has already judged. The flip improves nothing and reworks nothing —
   it is the ratifying act the PR exists to perform, and without it nothing may
   implement against the ADR at all (ADR-0015 §5). And a finding that does arrive
   on that round is not stranded by the flip having happened: **return the ADR to
   `Proposed` and re-enter at step 1.** This is a **pre-merge** move and only
   that. Every step here runs on the open PR, so an `Accepted` flip sitting on the
   branch has landed nowhere and binds no reader; restoring `Proposed` is then
   ADR-0070 §1's *third* permitted in-place header edit — "correcting a `Status`
   line to match what actually landed" — which is the clause ADR-0127 §3 invokes
   for exactly this restoration, and the route ADR-0127 and ADR-0133 each took on
   their own PRs. After the merge the route is gone and a change to the decision
   is a new ADR that supersedes it (ADR-0070 §1), which is the whole reason the
   flip waits for step 2's green set. ADR-0070 §1's no-rewrite rule protects
   *ratified* decision text, and an ADR returned to `Proposed` before merge is not
   that — so the correction stays an in-place edit rather than becoming a dated
   note appended to a document one commit old. What the return does **not** buy is a
   shortcut back to step 3: §1 is explicit that its permitted edit forms "bound
   the append-only *form* of an edit, not the review a decision needs. A
   substantive contract ADR is still reviewed while `Proposed` and ratified only
   after". So the corrected decision earns the whole required set green on the
   corrected `Proposed` tree before it is flipped a second time — which is why an
   ADR taking this route records itself as ratified *on its second flip*.
4. **`just ship`, then `gh pr ready`, then merge** — on your own judgement, like
   any other change ("Report the review, then mark it ready").
5. **Nothing implements against the ADR until that merge** (ADR-0015 §5, golden
   rule 5).

**Point at this block rather than re-arguing it.** ADR-0130 §12's status bullet
is the worked precedent: drafted, reviewed and revised as `Proposed`, "its status
flipped only once both required reviews returned clean on one tree", "Findings
raised after the flip were folded the same way and both reviews re-run", and
"nothing implements against §9 until this has merged". An ADR recording its own
ratification owes a line naming the set it ran and the outcome it got, plus a
pointer here — not a paragraph reasoning the sequencing out from first
principles.

## The dispatcher

ADR-0015 replaced the shared coordination files with a person: the **dispatcher**
is whoever hands work to agents. ADR-0015 §§2 and 5 give the role its powers, and
the rest of this document assumes it exists without naming it.

The dispatcher:

- **assigns ADR numbers** at dispatch (above);
- **prevents lane collisions**, since nothing mechanical detects two agents
  working the same subsystem — ADR-0015 traded that check away deliberately;
- **places each agent in its own clone** (ADR-0015 §2), never two in one, and
  never in a linked worktree;
- **decides merge order** where a contract ADR must land before the
  implementation depending on it (golden rule 5).

Two things follow for **you, the agent**. Your lane's boundaries and your ADR
number come from your brief, not from your own reading of the repo — where the
brief conflicts with an issue the brief is newer, and where it conflicts with a
ratified ADR, stop and say so rather than choosing. And the report you send back
is evidence: say what you actually verified and at which commit, because a gate
run before a rebase is not a gate run against `main`.

The mechanics of the role — clone inventory, brief contents, what to re-check
before believing a report, merge sequencing — live in the `dispatch-agents`
skill, alongside `pre-dispatch-survey`, which establishes the state its briefs
are written against. Neither decides *what* the work is: `docs/roadmap.md` owns
scope, and its legs are ordered.

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
merges (ADR-0010). The protection is not about arbitrating between contributors;
it is what makes every merge carry evidence: a green `gate` on the merged
content, and a linear history where each commit keeps its `Refs:` trailer.

- **Never push to `main`.** Push your `<area>/<slug>` branch and open a PR.
- **Open a draft PR early — always.** As soon as you have a branch and a first
  commit, open it as a **draft**, before the work is done. CI runs on every push
  so you get the gate continuously, and the dispatcher can see your direction
  (and any contract change) while redirecting is still cheap. Mark it **ready for
  review** when the change is complete — your call, made without asking (see
  "Report the review, then mark it ready"). Nothing automated fires on that
  transition (ADR-0015); it is the signal to the dispatcher that the lane is done
  and ready to be verified and merged.
- **CI gates the PR.** The `gate` workflow runs the full Definition-of-Done gate
  on every PR and push; a PR cannot merge while it is red. This is enforced for
  everyone. Run the gate locally first anyway — CI is the backstop, not the
  substitute.
- **`gate` is the only required check; no approving review is required.** Branch
  protection asks for zero approvals, because there is no second author to ask —
  so the Codex review reported by `just ship` (see "Review") is the entire
  independent judgement on the change, and the dispatcher's verification is the
  entire human one. Note in the PR description any `blocker`/`major` finding you
  waived, with its rationale, and link the issues you filed for findings you
  deferred. **A merge therefore needs no `--admin`:** reach for the bypass only
  to override a genuinely red or stale gate, and say why in the PR.
- **Rebase and merge.** Rebase your branch onto `main` and merge via GitHub's
  *Rebase and merge* so linear history holds and each commit keeps its
  `Refs: ADR-NNNN` trailer. Delete the branch after merge.
- **Low-collision by design.** Work is split across low-overlap sections, so
  rebase conflicts should be rare; whoever merges second resolves them.
- Administrators retain a bypass, and what it now bypasses is **evidence**, not
  an approval queue: `--admin` merges past a red `gate` and past the
  `strict`-protection check that a branch is current. Both of those are the
  reason to trust the merge, so the bypass is for a genuine emergency and the
  reason goes in the PR.

### Coordinating parallel work

**One clone per agent** (ADR-0015). An agent is dispatched by hand into a
pre-existing local clone and may assume it is the only worker there. Isolation
comes from the clone; there is no claiming protocol, no lock, and no code to
maintain. Nothing in the repo tracks who is working where — that is the
dispatcher's job, deliberately.

In your clone, each unit of work still starts the same way:

```bash
git fetch origin
git switch -c <area>/<slug> origin/main
```

Branch from `origin/main`, not from whatever the clone happens to have checked
out, so your work starts from the latest merged state. To stack a dependent PR,
branch from `origin/<other-branch>` — fetch first; the base must be a ref you
actually have.

Never work directly on `main` in a clone: it is the integration ref, and the
`no-commit-to-branch` pre-commit hook refuses commits to it.

The subsystem split keeps most work in non-overlapping folders, but `core/` is a
shared surface the gate cannot referee — a collision there is a valid diff that
passes every check and only surfaces as a conflict on the second rebase:

- **Changing `core/` is the one high-collision edit — flag it loudly.**
  `core/protocols.py` and `core/types.py` are touched by every subsystem, and a
  Protocol change is breaking (golden rule 5). The contract lands as its own
  ratified ADR *and its own PR*, ahead of anything built on it (see "Contract
  ADRs land before their implementation"), so the new shape is visible before
  another stream builds against the old one.
- **Two agents needing `core/` at once are not independent.** Sequence them:
  the second stacks on the first once the first's contract PR has merged.
  Whoever dispatches decides this; an agent that discovers it mid-task should
  say so rather than racing.

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

**These four are the headline, not the register.** They restate `CLAUDE.md`'s
golden rules 1, 2 and 4. The register is `pyproject.toml`'s
`[[tool.importlinter.contracts]]`, where each contract carries its reasoning in
place — **check a change against `uv run lint-imports`, never against this
list.** Restating the enforced set here would be a state claim in a living
document, and the check owns that fact (ADR-0019, "No state claims in living
documents" below).

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
exists to prevent, not a way to satisfy the scoping rule. It stays a small diff
because it is a contract and its guardrails, with no *production* implementation
attached (the canonical fake is an implementation, but a test-only one).

Not "Protocol now, tests when someone implements it." Deferring 2 and 3 is how
the original backfill debt came to exist: contracts landed, the machinery that
keeps implementations honest did not, and the backfill fell to whoever came
later. A fake with no suite drifts from the contract silently; a suite with no
fake leaves every consumer hand-rolling a private mock.

The triad is what a Protocol *change* is measured against too — extend the suite
in the same change, so the new obligation is enforced rather than assumed.

**The triad itself is mechanically enforced.**
`tests/core/test_protocol_triad.py` maps every Protocol in `core/protocols.py`
to its suite, its canonical fake, and a `Test…Contract` subclass whose contract
tests pytest actually *ran and passed*. The last part is the one that matters:
an abstract suite is only worth anything once something runs it against a real
subject, so the check demands evidence of execution rather than the existence
of files. It lives in pytest rather than in a script because only pytest can
answer "did these assertions run?", and `uv run pytest` is already in the gate
and in CI. Add a Protocol without its triad and the gate goes red, naming what
is missing.

Because the check wants evidence that the contract *ran*, a contract test that
skips itself does not count — a `pytest.skip("not implemented")` in a suite is
an obligation nobody met. Where an obligation genuinely does not apply to every
implementation, the **suite** says so by marking that test
`@pytest.mark.optional_obligation`; only then may an implementation's run skip
it. See `ContextProviderContract.test_each_assembly_recomputes_from_the_clock`,
which a provider deliberately serving a fixed instant opts out of.

What the check enforces is that the three artifacts exist and run — **not that
a suite covers every method of its Protocol.** Add a method to an existing
Protocol and leave its suite alone and the gate stays green. Keeping the suite
abreast of the contract is a review concern, like the adequacy of any other
test (ADR-0003).

The check carries an `EXEMPTIONS` list for Protocols whose backfill was still
outstanding when it landed. That list is a backlog, not an escape hatch: each
entry names the missing parts and the issue tracking them, an entry that
outlives its gap fails the check, and only the Protocols that predate the check
may be named at all — so a new Protocol cannot buy itself an exemption, and the
list can only shrink. **The hatch is closed rather than merely unused:** the
list is empty and no Protocol remains that an exemption could name, both of
which `tests/core/test_protocol_triad.py` enforces on every run. Read it for
what the list holds.

This does not loosen contract-first. The sequence is two stages, not one:

- **Stage 1 — ratify, in its own PR.** The ADR proposing the Protocol goes
  through architecture review, is ratified (golden rule 5), and **merges** —
  a substantive contract ADR is its own PR (ADR-0015 §5). Nothing implements
  against the new shape yet, the canonical fake included: a fake is an
  implementation, bound by that rule like any other.
- **Stage 2 — land the triad.** Once the contract has merged, all three
  artifacts ship together in the implementation PR.

So "contract-first" governs the ADR *preceding* the triad, not the ordering of
files inside it. The triad is about what ships together, not about writing tests
before you know the contract.

## Documentation

- **Google-style docstrings**, enforced by ruff (`D`, `convention = "google"`).
- Required on public modules, classes, and functions/methods; optional on
  private helpers.
- Do **not** repeat types in docstrings — they live in annotations.
- Comments explain **why**, not what. No commented-out code.
- Record every non-obvious decision as an ADR (`docs/adr/`, see the template).

### Cite in form, and mark what binds

Two decisions govern ADR *text* — ADR-0088 and ADR-0089, which hold the
evidence and the rejected alternatives. Both are **forward-only**: nothing
ratified is rewritten to satisfy either, so an older ADR that does not follow
them is a record, not a defect to fix.

**Cite in one of ADR-0088 §1's three forms** — a decision, a code, or a tracker
citation. §1 defines each and §2 says what each must resolve to; read them there
rather than from memory, because a reference not written in one of those forms
is prose, and nothing resolves it. **A code citation carries no line number**
(§5): name the enclosing symbol, and quote the line where the position matters.
That one is worth remembering for its reason — a line number stays well-formed
after the edit that invalidates it, so it fails *silently*, where a symbol name
either resolves or does not.

What the corpus actually cites is owned by a check, not by this document:
`tests/scripts/test_adr_citations_corpus.py` runs ADR-0088 §6's Tier 1 inside
`pytest`, so a citation naming an ADR file that does not exist fails the gate
like any other test. One case is exempt: a number in a **gap** the issued set
encloses was assigned and never written, so an ADR cites it correctly and it is
neither failed nor reported. **ADR-0090 §1 defines which numbers those are —
read it there rather than inferring the boundary**, because the enclosure is
bounded on both sides and a number outside it is one nobody has issued. That
residual is where the check keeps its value: a typo and a stale forward
reference both land outside far more often than inside a gap, and both still
fail. Tier 1's tracker half needs `gh` to answer GitHub; where it cannot, the
citation is unevaluable and passes silently rather than failing, which is §6's
rule that a miss is benign and a false report is not.
`just citations` prints the whole report; its Tier 2 half is advisory and never
fails, because an append-only corpus correctly cites what the tree no longer
contains (ADR-0088 §3).

**Mark every normative clause**, in the form `docs/adr/template.md` carries
(ADR-0089 §2). A clause is normative when **a reader could disobey it** — it
constrains what an implementation, a lane, or a later ADR may do. A measurement,
an argument, a worked example, or a classification of the change being made is
not, however load-bearing it is: the test is conduct, not weight, and a refusal
to allow something is a rule like any other (ADR-0089 §1).

**In a marked ADR the marked clauses are the whole of what it obligates** (§3).
Unmarked text is read to determine what a marked clause *means*; it never
supplies an obligation. So a rule stated only in the prose beside a mark binds
nothing, and a clause has to carry its own scope, conditions and exceptions —
where the surrounding argument is what establishes that an obligation exists, or
how far it reaches, the marking is not finished.

Which regime an ADR is in is mechanical, not a judgement: it is marked when it
carries at least one well-formed clause and unmarked otherwise, and an unmarked
ADR binds as prose exactly as the corpus always has (§4). Mechanical is not a
bare search for the token — one that is indented, not preceded by a blank line,
or sitting inside a fence is not a mark and does not switch the regime (§2).
That default is deliberate: a near-mark and a marked-nothing ADR both degrade to
the status quo rather than to a defect, which moves the risk onto review.
**Reviewing a marked ADR, check that every obligation the document intends sits
inside a mark.** Nothing mechanical finds an under-marked ADR, and under §3
whatever was left outside the marks is simply discarded.

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
- **A fact a check owns is not a snapshot.** Say which check owns it, so a
  reader can tell the two apart.
- **A decision does not become a snapshot by describing a situation.** "You are
  the only agent in this clone" is a premise these documents *set* (ADR-0015),
  not a count someone took.
- **ADRs are exempt**, and that is why the rule works: an ADR is dated, so "at
  the time of writing, X" belongs there and stays correct as history. Do not
  scrub snapshots out of `docs/adr/`.

Enforced the way style is — by reviewers, reading the diff. There is
deliberately no linter for it (ADR-0019 §5).

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
