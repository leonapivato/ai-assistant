---
name: find-parallel-work
description: Survey the roadmap and core/protocols.py to find independent subsystem slices ready to hand to agents, then draft a GitHub tracking issue for them. Use when asked to find, plan, or scope parallel work for multiple agents, or to open an issue coordinating that work.
---

# find-parallel-work

Produces one GitHub tracking issue laying out a batch of independent,
non-colliding work slices, each sized for a single agent in a single clone.
This is a dev-process tool for building `ai-assistant` itself, not a product
feature. It **proposes**; the operator decides what actually gets dispatched.

## 1. Survey a current `origin/main`

State on disk can be stale, and a lane list computed from a stale tree proposes
work that is already done. Read the ref, not the checkout:

Resolve the ref to a commit **once**, then read everything from that commit.
`origin/main` is a moving target — a concurrent fetch between two `git show`
calls would mix a roadmap from one commit with protocols from another, and the
staleness check in step 4 would compare against a third:

```bash
git fetch origin
surveyed="$(git rev-parse origin/main^{commit})"   # every read below uses this
git show "$surveyed:docs/roadmap.md"
git show "$surveyed:src/ai_assistant/core/protocols.py"
git show "$surveyed:src/ai_assistant/core/types.py"
git show "$surveyed:VISION.md"   # step 3 cites a principle from it — read the ref, not your copy
```

For the derived picture — module counts per package, Protocol inventory, ADR
states — `project_status.py` reads a *checkout*, not a ref, so point it at a
disposable one rather than at wherever you happen to be standing (you are
normally on a feature branch, which has neither `origin/main`'s content nor a
fast-forward path to it):

```bash
tmp="$(mktemp -d)"
# Clean up on any exit path — a failure between add and remove would otherwise
# leave a worktree registered, and the two steps are independent so neither
# blocks the other.
trap 'git worktree remove --force "$tmp/survey" 2>/dev/null || true; rm -rf "$tmp"' EXIT
git worktree add --detach --quiet "$tmp/survey" "$surveyed"   # the same commit, not the ref
# Run the *surveyed* commit's own copy of the script, not the one on your
# branch: if origin/main changed how packages are classified, your branch's
# version would analyse the new tree with stale logic and mis-rank lanes.
python3 "$tmp/survey/scripts/project_status.py" --root "$tmp/survey"
```

`--root` exists for exactly this — the script is stdlib-only and runnable bare,
so it needs no environment in the temporary checkout.

Also check what is already claimed by open work:

```bash
gh pr list --state open --limit 200 --json number,title,headRefName,body
gh issue list --state open --limit 200 --json number,title,body
```

Set `--limit` on **both**: `gh pr list` defaults to 30 and `gh issue list` to
30, so a subsystem claimed by an older open item silently falls off the page and
reads as available. Raise them further if the repo ever carries more open items
than that.

Read the **bodies**, not just the titles: a PR called "First vertical follow-up"
on a branch named `feature/next` can claim the `tools` subsystem in a checklist
line and be invisible to a title scan.

Open PRs and issues are where work-in-flight lives (ADR-0015). There is no
ledger file; do not look for one.

## 2. Compute candidates

A subsystem is a valid candidate only if **all** of:

1. No open PR or issue already covers it.
2. It maps to one of the roadmap's **first-vertical seven artifacts**
   (`UserProfile`, `Memory`, `CurrentContext`, `Goal`, `ToolDefinition`,
   `ActionPlan`, `FeedbackEvent`). An unchecked build-sequence item that isn't
   one of the seven belongs in "Out of scope" as second-wave.
3. `project_status.py`'s module count is consistent with rule 2. That count is
   "a rough progress proxy," not a completion test — a subsystem can be built
   with few dense modules. If the count and the roadmap checklist **disagree**,
   drop the lane and name the discrepancy rather than guessing which is right.

For each candidate, note whether it needs an entry in `core/protocols.py`,
`core/types.py`, or both — a Protocol method can take or return a type that
does not exist yet, and public data crossing a subsystem boundary must live in
`core/types.py`.

**Cross-check the batch as a whole.** Two lanes that both touch `core/` are not
independent: the second would build against a contract about to change. Either
keep one `core/`-touching lane plus pure leaves, or explicitly sequence the
second to start after the first's contract PR merges. State which; don't leave
it implicit.

## 3. Draft the issue

One issue for the batch, not one per lane.

- **Title**: names the batch (e.g. "Parallel work: planning + tools contracts").
- **Why**: 2–3 sentences tying the batch to a specific `VISION.md` principle and
  `docs/roadmap.md` line.
- **One checklist section per lane**, each with: the subsystem and roadmap
  artifact(s) it delivers, a proposed `<area>/<slug>` branch name, and whether
  it touches `core/protocols.py`, `core/types.py`, or both.

For a `core/`-touching lane, the checklist item says the contract ADR ships as
its own PR and merges before the implementation (ADR-0015 §5). **Do not assign
ADR numbers here** — the operator assigns them at dispatch. Proposing a number
in an issue that sits open for a week just recreates the stale-ledger problem.

- **Out of scope**: anything excluded in step 2 and why, so it isn't
  re-litigated in comments.

## 4. Confirm before posting

`gh issue create` posts to shared state. Print the drafted body and get explicit
confirmation first — never auto-fire it.

State can go stale while confirmation is pending, and a lane that merged in the
meantime is exactly the "work already done" this skill exists not to propose.
Using `$surveyed` from step 1 — the commit every read actually came from —
**immediately before** `gh issue create`:

1. `git fetch origin` and compare against `$surveyed`. If it moved, redo steps 1–3
   against the new commit — an issue rescan alone will not catch a lane that
   merged, since a merged lane leaves no open issue behind.
2. Re-run **both** scans from step 1 — PRs *and* issues — regardless of whether
   the ref moved. Someone can open an overlapping PR, or an issue, while
   `origin/main` stands still; an issues-only rescan misses the PR case
   entirely.
3. If either changed the draft, show the revised body and get confirmation
   again — never post a body that was not the one approved.

Both are courtesy checks, not reservations; merged and posted state is
authoritative, nothing before it.
