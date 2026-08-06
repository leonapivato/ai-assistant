---
name: dispatch-agents
description: Dispatch scoped work to parallel agents in sibling clones, then verify what comes back and sequence the merges. Use when handing issues to multiple agents, briefing an agent on a lane, checking an agent's reported result, or deciding merge order across in-flight PRs.
---

# dispatch-agents

Runs the loop that begins where `pre-dispatch-survey` stops. That skill
establishes *state* — what has merged, what open work already claims, where the
slices would collide; this one dispatches the lanes, checks what returns, and
merges in an order that respects contract-first. Scope itself comes from
`docs/roadmap.md`, not from either skill.

The commands here are illustrations for an operator, not an implementation —
see §6. The judgement calls are yours, and §4 says why encoding them is a
mistake.

## 1. Preflight

**Inventory the clones.** One agent per clone (ADR-0015 §2), never a linked
worktree, never the user's primary clone, and never the clone you are yourself
working in — the glob will list that one if it has a suffix:

```bash
for d in ~/projects/ai-assistant-*; do
  printf '%s: %s %s dirty\n' "$d" "$(git -C "$d" branch --show-current)" \
    "$(git -C "$d" status --porcelain | wc -l)"
done
```

A clone is free only if it is on `main` **and** clean. Uncommitted work in a
clone sitting on `main` is someone's in-progress change; dispatching there
sweeps it into the agent's branch or loses it. A clone with no `.venv` needs
`just setup` first — say so in the brief rather than letting the agent find out.

**Assign ADR numbers yourself.** ADR-0015 §5 makes this the dispatcher's job, to
remove the race a shared ledger could not arbitrate. A number is claimed when a
lane starts, not when it merges, so `main` alone is never enough:

```bash
git fetch origin --prune
git ls-tree origin/main docs/adr/ --name-only                    # merged
for r in $(git for-each-ref --format='%(refname)' refs/remotes/origin); do
  git ls-tree "$r" docs/adr/ --name-only                         # unmerged
done | sort -u
```

Assign **one above the highest number any source mentions**, and never fill a
gap — an absent number below the maximum is a live claim whose file is not
written yet. Branch names need not contain the number
(`tools/tooldefinition-registry` carried ADR-0016), so your own record of what
you handed out is the primary source; the scan only catches what predates you.

## 2. Write the brief

An under-specified brief is the largest source of rework. Each one carries:

- **The clone path**, and that other clones are off-limits.
- **A scope fence** — which directories this lane may touch and which it may
  not, naming the lane that owns each excluded one. `core/protocols.py` and
  `core/types.py` are the highest-collision surface; one lane holds them at a
  time. **Fence the ground, not the technique.** The worker owns method and will
  substitute a better approach inside the fence and flag it (`worker.md`), so a
  brief that prescribes *how* either gets overridden or, worse, is followed
  against the worker's better judgement. Say what the lane delivers and what it
  may touch; leave the rest to the agent you picked for its judgement.
- **Corrections to stale issue text.** An issue written before a decision landed
  will instruct against it. Read it before dispatching and say which parts no
  longer apply — an agent that follows a stale issue faithfully has still done
  the wrong work.
- **The ADR number, or that none is needed.** Never let an agent pick one.
- **A lane delivers exactly one PR.** If the work needs two — a contract ADR
  and its implementation is the standing case — that is two lanes, briefed
  separately, the second only after the first has merged. A lane carrying a
  stack overloads its context, and an implementation written in the same
  context as the ADR is built against the draft in its author's head rather
  than the ratified text; the merged PR is the second brief's authority.
  Golden rule 5 already sequences the *PRs* — this sequences the *lanes* the
  same way. The Protocol triad is one PR and so still one lane
  (`CONTRIBUTING.md` → "Adding a Protocol"); it is the ADR that ships alone.
  The rule also has a mechanical ground, not just a context one: a PR stacked
  on another PR's branch records that branch as its review base, and a
  rebase-merge of the parent rewrites the SHA out of history. The parent's
  merge itself moves nothing — a merge to `main` never moves a merge base
  (ADR-0027) — but it deletes the base branch, forcing the child to retarget
  and rebase onto `main`, and *that* is where §2(b)'s proper-ancestor clause
  becomes unsatisfiable and a fresh round is owed *even when not one reviewed
  byte moved*. Stacking buys a round at review time and forfeits one at the
  retarget its parent's merge makes inevitable.
- **Cross-lane interactions** in both directions: what this lane will see if
  another merges first, and what it must not assume. Say **where in the merge
  order it sits and why** (§5). A lane told it merges last plans for the rebase
  instead of reporting as though it were finished; a lane told it holds a floor
  path knows its own merge is the expensive one.
- **The finishing loop** — full gate, `just review-codex`, triage, `just ship`,
  `gh pr ready` — and that the agent owns all of it without asking.
- **Fetch and rebase before gating *and* before reviewing.** A gate against a
  stale tree is not evidence, and Codex reads the working tree for context, so a
  stale branch makes it report other lanes' merged work as regressions.

**Say that the brief's factual claims are hypotheses.** Every file, symbol and
line you name is something you believed when you wrote it, and a brief has
already been wrong about exactly that — one named a symbol and a line the
committed text did not contain, and the lane found out only because the brief
separately asked for an unrelated sweep. A brief is more dangerous than a review
finding: it arrives with your authority and is read before any skepticism exists,
so a lane that treats "fix this citation" as an instruction rather than as a
claim edits the wrong thing and reports success. `docs/review/guide.md` already
tells a worker to treat findings as hypotheses; nothing says it of the brief, so
write it in — **verify the brief's factual claims against the tree before acting
on them, and report the ones that do not hold.**

The report contract itself lives in `worker.md` — do not restate it in the brief.
What the brief owes it is **completeness**: a worker treats a missing fence, or a
missing ADR number where the change needs one, as a STOP rather than as
permission, because it cannot tell an omission from a deliberate blank. That is
the cheapest place an under-specified brief gets caught, and it only works if you
write every section rather than leaving the obvious ones implied.

## 3. Verify every report — assume nothing

Reports are written from the agent's belief, which can be stale or wrong.
Reported status has been contradicted by CI. Check the thing, not the claim:

```bash
sha=$(gh pr view <n> --json headRefOid --jq .headRefOid)
gh pr checks <n>                      # not the reported gate result
gh pr view <n> --json isDraft,mergeable,mergeStateStatus,reviewDecision
gh pr diff <n> --name-only            # scope claims: did it touch what it said?
gh pr view <n> --json comments --jq '.comments[].body' | grep -c "ship:$sha"
```

`mergeStateStatus: BEHIND` means it was never gated against current `main`.
The last line is the one nothing else covers: green CI and a clean diff say
nothing about whether `just review-codex` and `just ship` ever ran, and a report
claiming both is not evidence that either did. `ship.sh` tags its comment with the
SHA it reviewed, so no tag for the current head means no review of the current
head.

**Check scope as a list against a list, not by eye.** `worker.md` requires the
report to paste `git diff --name-only origin/main...HEAD`, so compare that against
the fence you wrote and against `gh pr diff <n> --name-only`. Reading the diff and
judging whether it "looks in scope" is the version of this check that has been
wrong; two lists disagreeing is not.

**Spend your attention on the right fields.** The gate's pytest line and the
worker's own `gh pr checks` paste are provenance — `gh pr checks` above supersedes
them, and the pytest line matters only as evidence the gate ran locally *before*
the push, which CI cannot show. The fields that carry weight are the file list,
the `ship:$sha` tag, the artifact verdict, the issue numbers, and what the worker
says it did not do.

**Before merging, diff the open PRs against each other** — two lanes editing one
file is invisible in either PR alone:

```bash
for p in $(gh pr list --state open --json number --jq '.[].number'); do
  gh pr diff "$p" --name-only | sed "s|^|$p |"
done | sort -k2 | uniq -f1 -D
```

## 4. Adjudicate escalations — do not encode the answers

When an agent stops on a conflict between authorities, resolve it from the
texts. Read the actual lines before ruling; agents cite these from memory and
misquote them.

Authority runs: **ADRs and `CLAUDE.md`'s golden rules > `CONTRIBUTING.md` > a
reviewer's opinion.** `CONTRIBUTING.md` is ratified by ADR-0003, so an ADR
outranks it. A brief outranks neither — if yours conflicts with one, that is
your error to fix, not the agent's to follow.

Deliberately not encoded: the rulings themselves. Two waivers that look alike
resolve opposite ways when the governing authority differs — one structural
finding against `CONTRIBUTING.md` was correctly overruled and the next correctly
upheld. A skill that pre-decided them would be wrong half the time with full
confidence.

A STOP report carries the resolution the worker would take (`worker.md`), so most
adjudications are a yes or a no rather than a re-brief. Rule on *that* — and where
you overrule it, say which authority overrules it, because the worker read the
same texts and will otherwise reach the same conclusion again.

**Two tiers arrive differently.** A **STOP** halts the lane and needs a ruling
before anything continues. A **FLAG** does not: the worker was entitled to decide
it, did, and recorded it in the PR description and the report — so it needs your
attention only if you disagree, and it costs nothing to arrive late. Method
choices, and a brief that contradicted an ADR without reshaping the lane, come
back as FLAGs. **Read them as feedback on your brief.** A lane that flags three
method substitutions is telling you the brief was prescribing technique it should
have left alone; a lane that flags an ADR conflict is telling you the brief was
written against something the ADRs had already settled. Neither is the worker
misbehaving.

### Resume the lane; do not restart it

A subagent has no channel to ask mid-run, so a STOP ends the run — but it does not
end the *lane*. The clone still holds the branch, the commits, and the draft PR
with the pre-flight in its description.

The same applies to a lane that finished and reported: **the most common resume is
not an adjudication at all, it is "rebase, you went `BEHIND`"** (§5). Everything
below holds for it unchanged.

- **Prefer `SendMessage` to the same agent.** Its context is intact: it knows its
  clone, its fence, what it has already built, and why it stopped. A ruling plus
  "continue" is a few hundred tokens.
- **A fresh worker re-pays everything** — both standards documents, the issue, the
  ADRs, its own pre-flight — before it writes a line. That is the expensive path,
  so take it only when you must.
- **You must, once the agent is unreachable** (a session restart loses its id). Then
  the brief has to say it is *continuing, not starting*: the clone, the existing
  branch and its HEAD, what is already committed and pushed, the PR number, and
  the ruling. Without that, a worker following its own instructions branches from
  `origin/main` in a clone that is neither on `main` nor clean, and either trips
  the freshness test in §1 or quietly builds on the wrong base.

An aborted lane that will not be resumed still needs releasing — §5's last step
applies, except `git cherry` will show its commits as unmerged, which is the
signal to close the PR and decide deliberately whether the work is discarded or
becomes an issue. Then reset the clone so §1 sees it as free.

## 5. Merge

**Decide the order when you dispatch, not when the PRs arrive.** It follows from
one asymmetry, and it is cheap to get right in advance and expensive to discover
late.

`CONTRIBUTING.md` → "Report the review, then mark it ready" holds the floor and
every condition — read it there rather than from memory. What the *order* turns
on is this: a base move that clears the floor and leaves the reviewed patch
untouched costs the rebasing lane **nothing**, while a base move landing in the
floor invalidates its artifact **outright**, with no patch-identity relief. So:

- **Lanes that are outside the floor *and* touch no file in common are free to
  each other**, in any order — sequence them by whatever is ready. Both halves are
  required. The identity is byte-sensitive to hunk bodies **including context
  lines** (ADR-0027 §2), so two non-floor lanes editing nearby regions of one file
  still invalidate the second one's artifact when it rebases: its context moved,
  so its identity moved. Clearing the floor buys nothing there. §3's overlap check
  is what establishes the second half, and it is worth running at *slice* time and
  not only before merging.
- **A lane holding a floor path is the expensive merge, so put it last**, when
  nothing else is open to rebase across it. Merging it first taxes every other
  lane in the wave a full round each.
- **Two floor-touching lanes in one wave means one of them pays.** That is a
  reason to split them across waves, not a cost to absorb quietly — and note
  `docs/adr/**` is *in* the floor, so an ADR lane and a contract lane are both
  expensive and each wants its own quiet window.

The corollary for §2: a wave is cheapest when at most one lane touches the floor
and no two lanes share a file. Fence for both when you slice the work — a
collision found at merge time has already been paid for.

**A contract ADR merges before its implementation** (golden rule 5, ADR-0015 §5).
Where a lane split into an ADR PR and an implementation PR, the order is
load-bearing and nothing mechanical enforces it — both PRs are green and
mergeable in either order.

**Merge without `--admin`.** Branch protection requires no approving review, so
the ordinary merge path works — and that matters, because `--admin` does not
just skip an approval queue, it skips *evidence*: a red `gate`, and the
`strict`-protection check that the branch is current. Leaving the flag off means
GitHub enforces both for you. If a merge is refused, read the reason rather than
reaching for the flag.

```bash
sha=$(gh pr view <n> --json headRefOid --jq .headRefOid)
gh pr checks <n> --watch --fail-fast || exit 1
[ "$(gh pr view <n> --json mergeStateStatus --jq .mergeStateStatus)" = BEHIND ] && exit 1
gh pr merge <n> --rebase --delete-branch --match-head-commit "$sha"
```

Each line guards a different hole, and the first two are belt-and-braces now
that protection enforces them — worth keeping, because they fail *before* the
merge attempt with a reason you can read. `--watch`: bare `gh pr checks` exits
immediately while checks are *pending*, reporting "no checks reported yet" so the
merge proceeds anyway. The `BEHIND` recheck: `main` can land another PR while
yours is being checked. `--match-head-commit` is the one nothing else covers — an
agent pushing in the same window otherwise gets its commit merged unreviewed, and
no protection setting sees that.

**A rebase may or may not invalidate the review record.** `just ship` anchors a
review to *content*, not to a commit (ADR-0027 §2), so `gh pr update-branch
--rebase` is a **base move**: the artifact still covers the head where the move
leaves the reviewed patch untouched and clears ADR-0027 §3's floor, and costs a
fresh round where it does not. `CONTRIBUTING.md` → "Report the review, then mark
it ready" holds the conditions; do not reason them out from memory, and note that
`docs/adr/**` is inside the floor, so an ADR lane pays a round for a rebase that
an implementation lane would not.

Nothing on the PR enforces this — `gate` re-runs green on the new head and
protection has no opinion about review records — so it is the merger's job to
check. Branch protection is `strict`, so a stale branch must be updated before it
can merge; the cheap resolution is ordering (above). Merge while the branch is
current.

**Where an update is unavoidable, the new SHA always needs its own gate and its
own `ship`; it needs a fresh *review* only where the base move fails ADR-0027
§2's conditions.** Say which of the two you are asking for when you send a lane
back, because the default a worker reaches for is the expensive one: `ship`
refusing looks like "run a review," and a lane left to its own judgement will buy
a round it did not owe.

So say which, and say it from your own reading of the base move rather than
leaving it open. Where you expect §2 to cover it: rebase, re-gate, re-`ship`, run
**no** review. `worker.md` holds the drill that checks this *before* the push, and
splits the two outcomes — a refusal the lane's own verification **predicted** is a
real round, reported with its figures for you to authorise; a refusal that
**contradicts** that verification is a STOP, quoted verbatim. Rule on the first;
read the second, because it means one of the two readings of ADR-0027 §2 is wrong
and a round spent papering over it tells you nothing and cannot be refunded.

Rebase-merge only; the repo forbids squash and merge commits.

**Release the clone after the merge.** A lane leaves its clone sitting on the
merged feature branch, and §1's test calls a clone free only if it is on `main`
and clean — so an unreleased clone reads as busy forever and the next batch
either overrides the test by eye or resets by hand:

```bash
git -C "$clone" switch main --quiet && git -C "$clone" pull --ff-only
cherry=$(git -C "$clone" cherry main <area>/<slug>) || { echo "cherry failed"; exit 1; }
if [[ $cherry == *"+ "* ]]; then
  echo "unmerged commits — leave the branch alone and find out why"
else
  git -C "$clone" branch -D <area>/<slug>
fi
```

**Check with `cherry`, not `branch -d`.** Rebase-merge rewrites the commits, so
the local tip is never an ancestor of `main` and the ancestry-based `-d` refuses
on a lane that *did* land — which trains you to reach for `-D` reflexively, and
`-D` on a lane that did *not* land discards it silently. `git cherry` compares
patch ids instead, so it answers the question ancestry cannot: did this work
reach `main` in any form?

**Test for the absence of `+`, not for empty output.** Verified on git 2.53:
`cherry` omits a commit whose patch is already upstream, so a fully landed lane
prints nothing and only unmerged commits appear, each prefixed `+`. The two tests
therefore agree today — but they stop agreeing the moment any commit on the branch
*is* unmerged, and `+` is the property that actually matters: **a single `+` line
means unmerged work, and nothing may delete that branch.** Emptiness is a
side-effect of the current output format; `+` is the question.

That is also why the guard is a conditional rather than three sequential
commands. `-D` is unrecoverable, and this is the one snippet here where getting it
wrong destroys a lane's work rather than merely failing.

For the same reason it **captures `cherry` and matches the variable**, instead of
piping into `grep -q`. Two ways a pipeline reaches the delete branch by accident:
`grep -q` exits at its first match and leaves `git cherry` writing into a closed
pipe, which under `set -o pipefail` makes the whole pipeline non-zero and sends a
branch full of `+` lines down the `else`; and a `git cherry` that *fails* — a
mistyped branch name — prints nothing at all, which any "did it match?" test reads
as "nothing unmerged." Every default here has to fail toward keeping the branch.

**Renaming a clone breaks its `.venv`** (absolute paths): `rm -rf .venv && just
setup` after. Never rename a clone an agent is running in.

## 6. Watch the cost

Parallelism is capped by clones deliberately (ADR-0015 Consequences): nothing
detects two agents colliding, so lane separation is the dispatcher's job and
does not scale by adding agents. The dominant cost is agent tokens and the
dominant waste is rework from a thin brief — prefer fewer, larger, well-fenced
lanes.

**These commands are illustrations, not an implementation.** Extracting them
into tested scripts has been proposed and is declined: that is the
`claim-workspace.sh` shape ADR-0015 deleted — ~856 lines of shell plus ~1,770
of shell tests — whose `fix(dev)` commits dominated the history. Adversarial
review will keep proposing hardening for conditions this repo does not have
(hundreds of open PRs, hostile concurrent pushes); harden the two or three
paths that have actually failed and leave the rest as prose. If this file needs
its own test suite, it has become the thing ADR-0015 removed.
